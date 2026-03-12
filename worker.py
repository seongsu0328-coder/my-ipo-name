import os
import time
import json
import re
import requests
import pandas as pd
import numpy as np
import logging
# 💡 [핵심 제거] import yfinance as yf 가 완전히 삭제되었습니다!
from datetime import datetime, timedelta

from supabase import create_client
import google.generativeai as genai

# ==========================================
# [1] 환경 설정 & 디버깅 로그
# ==========================================
print(f"🚀 Worker Process 시작: {datetime.now()}")

# 1. 환경 변수 로드
raw_url = os.environ.get("SUPABASE_URL", "")
if "/rest/v1" in raw_url:
    SUPABASE_URL = raw_url.split("/rest/v1")[0].rstrip('/')
else:
    SUPABASE_URL = raw_url.rstrip('/')

SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
GENAI_API_KEY = os.environ.get("GENAI_API_KEY", "")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")  # 💡 [신규 추가] FMP 키 로드

# 💡 [디버깅] 배달 상태 확인
print(f"DEBUG: SUPABASE_URL 존재 = {bool(SUPABASE_URL)}")
print(f"DEBUG: SUPABASE_KEY 존재 = {bool(SUPABASE_KEY)}")
print(f"DEBUG: GENAI_API_KEY 존재 = {bool(GENAI_API_KEY)}")
print(f"DEBUG: FMP_API_KEY 존재 = {bool(FMP_API_KEY)}")  # 💡 [신규 추가] FMP 키 확인 로그

# 💡 [핵심 제거] logging.getLogger('yfinance').setLevel(logging.CRITICAL) 가 삭제되었습니다!

# 2. 필수 연결 체크
if not (SUPABASE_URL and SUPABASE_KEY):
    print("❌ 환경변수 누락으로 종료")
    exit()

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase 클라이언트 연결 성공")
except Exception as e:
    print(f"❌ Supabase 초기화 실패: {e}")
    exit()

# 3. AI 모델 설정 (하이브리드 전략: 엄격 모델 & 검색 허용 모델 분리)
model_strict = None
model_search = None
if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)
    try:
        # [1] 환각 원천 차단용 일반 모델
        model_strict = genai.GenerativeModel('gemini-2.0-flash')
        
        # 🚨 [2] 하이브리드 엔진 - 구글 서버 400 에러를 원천 차단하는 최신 단일 규격
        try:
            model_search = genai.GenerativeModel(
                model_name='gemini-2.0-flash',
                tools=[{"google_search": {}}]
            )
            print("✅ AI 하이브리드 모델 로드 성공 (Google Search 엔진 공식 설정 완료)")
        except Exception as e_tool:
            print(f"⚠️ 구글 검색 도구 로드 최종 실패: {e_tool}")
            model_search = None

    except Exception as e:
        print(f"⚠️ AI 모델 로드 에러: {e}")

# 💡 [중요] 다국어 지원 언어 리스트 정의
SUPPORTED_LANGS = {
    'ko': '전문적인 한국어(Korean)',
    'en': 'Professional English',
    'ja': '専門的な日本語(Japanese)',
    'zh': '简体中文(Simplified Chinese)'
}

def fetch_sec_filing_text(ticker, doc_type, api_key, cik=None):
    try:
        accession_num = None
        filed_date = None

        # [1단계: FMP 1차 탐색] FMP API는 숫자(CIK)를 받으면 고장 나므로, 무조건 '티커(문자)'로 먼저 검색합니다.
        search_url = f"https://financialmodelingprep.com/stable/sec-filings?symbol={ticker}&type={doc_type}&limit=1&apikey={api_key}"
        r = requests.get(search_url, timeout=5)
        
        if r.status_code == 200:
            res_data = r.json()
            if isinstance(res_data, list) and len(res_data) > 0:
                accession_num = res_data[0].get('accessionNumber')
                filed_date = res_data[0].get('fillingDate')

        # [2단계: SEC EDGAR CIK 우회] 🚨 대표님 의도 복원!
        # 티커가 변경되었거나 신규 상장이라 FMP가 못 찾은 경우, CIK를 이용해 SEC 공식 서버를 강제로 뒤집니다.
        if not accession_num and cik:
            time.sleep(0.5) 
            sec_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
            sec_res = requests.get(sec_url, headers=SEC_HEADERS, timeout=5)
            if sec_res.status_code == 200:
                filings = sec_res.json().get('filings', {}).get('recent', {})
                forms = filings.get('form', [])
                acc_nums = filings.get('accessionNumber', [])
                dates = filings.get('filingDate', [])
                
                for i, form in enumerate(forms):
                    # F-1/A 등 파생 서류명까지 유연하게 잡아냄
                    if doc_type.upper() in str(form).upper():
                        accession_num = acc_nums[i]
                        filed_date = dates[i]
                        print(f"🕵️‍♂️ [SEC Bypass] 티커 변경/누락 극복! {ticker}의 {doc_type} 번호 CIK로 탈취 성공: {accession_num}")
                        break

        # 번호를 끝내 못 찾았으면 종료
        if not accession_num: return None, None

        # [3단계: 본문 텍스트 추출] 찾은 문서 번호로 텍스트를 가져옵니다.
        text_url = f"https://financialmodelingprep.com/stable/sec-filing-full-text?accessionNumber={accession_num}&apikey={api_key}"
        txt_res = requests.get(text_url, timeout=7)
        full_text = ""
        if txt_res.status_code == 200:
            txt_data = txt_res.json()
            if isinstance(txt_data, list) and len(txt_data) > 0:
                full_text = txt_data[0].get('content', '')

        # [4단계: 최후의 보루] FMP 텍스트 변환이 늦어지면 SEC에서 생원문을 직접 긁어옵니다.
        if (not full_text or len(full_text) < 100) and cik:
            print(f"⚠️ FMP 텍스트 지연 발생. SEC 서버에서 원문 직접 추출 시도: {ticker} ({doc_type})")
            acc_no_clean = str(accession_num).replace('-', '')
            cik_int = str(int(cik))
            raw_txt_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_no_clean}/{accession_num}.txt"
            
            raw_res = requests.get(raw_txt_url, headers=SEC_HEADERS, timeout=10)
            if raw_res.status_code == 200:
                clean_text = re.sub(r'<[^>]+>', ' ', raw_res.text)
                clean_text = re.sub(r'\s+', ' ', clean_text)
                full_text = clean_text
                print(f"✅ [SEC Scraping] SEC 본진 원문 확보 완료! ({len(full_text)} 자)")

        if full_text and len(full_text) > 100:
            return filed_date, full_text[:40000]
        
        return filed_date, None

    except Exception as e:
        print(f"❌ [{ticker}] {doc_type} 본문 추출 최종 실패: {e}")
        return None, None

        # 💡 [Stable 주소로 교체 완료]
        text_url = f"https://financialmodelingprep.com/stable/sec-filing-full-text?accessionNumber={accession_num}&apikey={api_key}"
        txt_res = requests.get(text_url, timeout=7)
        full_text = ""
        if txt_res.status_code == 200:
            txt_data = txt_res.json()
            if isinstance(txt_data, dict) and "Error Message" in txt_data:
                print(f"🚫 [Tab 0 SEC 텍스트 차단됨: {doc_type}] -> {txt_data['Error Message']}")
            elif isinstance(txt_data, list) and len(txt_data) > 0:
                full_text = txt_data[0].get('content', '')

        if (not full_text or len(full_text) < 100) and cik:
            print(f"⚠️ FMP 텍스트 지연 발생. SEC 서버에서 원문 직접 추출 시도: {ticker} ({doc_type})")
            acc_no_clean = str(accession_num).replace('-', '')
            cik_int = str(int(cik))
            raw_txt_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_no_clean}/{accession_num}.txt"
            
            raw_res = requests.get(raw_txt_url, headers=SEC_HEADERS, timeout=10)
            if raw_res.status_code == 200:
                clean_text = re.sub(r'<[^>]+>', ' ', raw_res.text)
                clean_text = re.sub(r'\s+', ' ', clean_text)
                full_text = clean_text
                print(f"✅ [SEC Scraping] SEC 본진 원문 확보 완료! ({len(full_text)} 자)")

        if full_text and len(full_text) > 100:
            return filed_date, full_text[:40000]
        
        return filed_date, None

    except Exception as e:
        print(f"❌ [{ticker}] {doc_type} 본문 추출 최종 실패: {e}")
        return None, None

# ==========================================
# [2] 헬퍼 함수: FMP 통신 방어막 v3 (Stable API 맞춤형)
# ==========================================
def get_fmp_data_with_cache(symbol, api_type, url, valid_hours=24):
    """
    FMP Stable API의 404, 400 에러를 "데이터 없음"으로 우아하게 처리합니다.
    """
    cache_key = f"RAW_FMP_{api_type}_{symbol}"
    limit_time = (datetime.now() - timedelta(hours=valid_hours)).isoformat()
    
    try:
        res = supabase.table("analysis_cache").select("content, updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time).execute()
        if res.data:
            return json.loads(res.data[0]['content'])
    except: pass

    try:
        response = requests.get(url, timeout=7)
        
        # 🚨 [방어막 1] Stable API에서 데이터가 없을 때 보내는 400, 404 처리
        if response.status_code in [400, 404]:
            print(f"⚠️ [FMP 데이터 없음] {api_type} -> 해당 기업({symbol})은 아직 이 데이터가 존재하지 않습니다.")
            return None
            
        # 🚨 [방어막 2] 그 외 진짜 서버 통신 에러
        if response.status_code != 200:
            print(f"🚫 [FMP 서버 지연] {api_type} (HTTP {response.status_code})")
            return None
            
        try:
            res_json = response.json()
        except ValueError: 
            return None
            
        if isinstance(res_json, dict) and ("Error Message" in res_json or "Error" in res_json):
            print(f"🚫 [FMP 권한 차단됨] {api_type} -> 사유: {res_json.get('Error Message', 'Unknown')}")
            return None 
            
        if res_json:
            batch_upsert("analysis_cache", [{
                "cache_key": cache_key,
                "content": json.dumps(res_json),
                "updated_at": datetime.now().isoformat()
            }], on_conflict="cache_key")
            return res_json
            
    except Exception as e:
        print(f"❌ FMP API 기타 에러 ({api_type}): {e}")
    
    return None

def sanitize_value(v):
    if v is None or pd.isna(v): return None
    if isinstance(v, (np.floating, float)):
        return float(v) if not (np.isinf(v) or np.isnan(v)) else 0.0
    if isinstance(v, (np.integer, int)): return int(v)
    if isinstance(v, (np.bool_, bool)): return bool(v)
    return str(v).strip().replace('\x00', '')

def batch_upsert(table_name, data_list, on_conflict="ticker"):
    if not data_list: return
    endpoint = f"{SUPABASE_URL}/rest/v1/{table_name}?on_conflict={on_conflict}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal,resolution=merge-duplicates" 
    }
    clean_batch = []
    for item in data_list:
        payload = {k: sanitize_value(v) for k, v in item.items()}
        if payload.get(on_conflict):
            clean_batch.append(payload)
    if not clean_batch: return
    try:
        resp = requests.post(endpoint, json=clean_batch, headers=headers)
        if resp.status_code in [200, 201, 204]:
            print(f"✅ [{table_name}] {len(clean_batch)}개 저장 성공")
        else:
            print(f"❌ [{table_name}] 저장 실패 ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"❌ [{table_name}] 통신 에러: {e}")

def get_target_stocks():
    if not FINNHUB_API_KEY: return pd.DataFrame()
    now = datetime.now()
    ranges = [
        (now - timedelta(days=200), now + timedelta(days=35)), 
        (now - timedelta(days=380), now - timedelta(days=170)), 
        (now - timedelta(days=560), now - timedelta(days=350))
    ]
    all_data = []
    for start_dt, end_dt in ranges:
        url = f"https://finnhub.io/api/v1/calendar/ipo?from={start_dt.strftime('%Y-%m-%d')}&to={end_dt.strftime('%Y-%m-%d')}&token={FINNHUB_API_KEY}"
        try:
            res = requests.get(url, timeout=10).json()
            if res.get('ipoCalendar'): all_data.extend(res['ipoCalendar'])
        except: continue
        
    if not all_data: return pd.DataFrame()
    df = pd.DataFrame(all_data).dropna(subset=['symbol'])
    df['symbol'] = df['symbol'].astype(str).str.strip()
    return df.drop_duplicates(subset=['symbol'])

# 💡 [추가] 메인 루프에서 수익률 상위 50개를 계산하기 위한 현재가 로드 함수
def get_current_prices():
    try:
        res = supabase.table("price_cache").select("ticker, price").execute()
        return {item['ticker']: float(item['price']) for item in res.data if item['price']}
    except: return {}

# ==========================================
# [추가] 프리미엄 유저 대상 통계적 급등 알림 엔진 (FMP 최적화 버전)
# ==========================================
def run_premium_alert_engine(df_calendar):
    print("🕵️ 프리미엄 알림 엔진 가동 (기간별 통계 모드: 1일~1년)...")
    today = datetime.now().date()
    new_alerts = []
    
    # DB에서 최신 가격 가져오기
    price_map = get_current_prices()

    for _, row in df_calendar.iterrows():
        ticker = row['symbol']
        name = row['name']
        current_p = price_map.get(ticker, 0.0)
        
        try: ipo_date = pd.to_datetime(row['date']).date()
        except: continue
        
        # --- 1. 일정 기반 알림 (상장예정, 락업해제) ---
        if ipo_date == today + timedelta(days=3):
            new_alerts.append({
                "ticker": ticker, "alert_type": "UPCOMING", "title": f"{ticker} 상장 D-3", 
                "message": "상장전 월가 기관의 평가를 미리 확인하세요."
            })
        
        if ipo_date + timedelta(days=180) == today + timedelta(days=7):
            new_alerts.append({
                "ticker": ticker, "alert_type": "LOCKUP", "title": f"{ticker} 락업해제 D-7", 
                "message": "내부자 보호예수 물량이 해제될 예정으로 주가 변동성이 올라갈 수 있습니다."
            })

        if current_p <= 0: continue

        # --- 2. 기간별 통계적 유의 상승 로직 (FMP API 적용) ---
        try:
            # 24시간 방어막이 쳐진 캐시 헬퍼 사용
            url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}?timeseries=260&apikey={FMP_API_KEY}"
            res = get_fmp_data_with_cache(ticker, "HIST", url, valid_hours=24)
            
            # res가 None이 아닐 때만 historical 데이터를 추출
            hist = res.get('historical', []) if res else []
                        
            if len(hist) >= 2:
                p_1d = hist[1]['close'] # 1일 전 (어제) 종가
                if p_1d > 0 and ((current_p - p_1d) / p_1d) * 100 >= 12.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1D", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 1일 동안 {((current_p - p_1d) / p_1d) * 100:.1f}% 상승"})
            
            if len(hist) >= 5:
                p_1w = hist[4]['close'] # 1주일 전 종가
                if p_1w > 0 and ((current_p - p_1w) / p_1w) * 100 >= 20.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1W", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 1주 동안 {((current_p - p_1w) / p_1w) * 100:.1f}% 상승"})

            if len(hist) >= 10:
                p_2w = hist[9]['close']
                if p_2w > 0 and ((current_p - p_2w) / p_2w) * 100 >= 30.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_2W", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 2주 동안 {((current_p - p_2w) / p_2w) * 100:.1f}% 상승"})

            if len(hist) >= 20:
                p_4w = hist[19]['close']
                if p_4w > 0 and ((current_p - p_4w) / p_4w) * 100 >= 40.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_4W", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 4주 동안 {((current_p - p_4w) / p_4w) * 100:.1f}% 상승"})

            if len(hist) >= 63:
                p_3m = hist[62]['close']
                if p_3m > 0 and ((current_p - p_3m) / p_3m) * 100 >= 60.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_3M", "title": f"{ticker} 중기 급등 포착", "message": f"{ticker} 주가 최근 3개월 동안 {((current_p - p_3m) / p_3m) * 100:.1f}% 상승"})

            if len(hist) >= 250:
                p_1y = hist[-1]['close'] # 가장 오래된 데이터 (약 1년 전)
                if p_1y > 0 and ((current_p - p_1y) / p_1y) * 100 >= 150.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1Y", "title": f"{ticker} 장기 급등 포착", "message": f"{ticker} 주가 최근 1년 동안 {((current_p - p_1y) / p_1y) * 100:.1f}% 상승"})
        except Exception as e: 
            pass

        # --- 3. 공모가 돌파 및 회복 시그널 ---
        try: ipo_p = float(str(row.get('price', '0')).replace('$', '').split('-')[0])
        except: ipo_p = 0.0

        if ipo_p > 0:
            surge_pct_ipo = ((current_p - ipo_p) / ipo_p) * 100
            if surge_pct_ipo >= 20.0:
                new_alerts.append({
                    "ticker": ticker, "alert_type": "SURGE_IPO", "title": f"{ticker} (+{surge_pct_ipo:.1f}%)", 
                    "message": f"현재가 ${current_p:.2f}로 공모가 대비 강력한 상승세"
                })
            elif 0 <= surge_pct_ipo < 3.0:
                new_alerts.append({
                    "ticker": ticker, "alert_type": "REBOUND", "title": f"{ticker} 공모가 회복", 
                    "message": f"주가가 다시 공모가(${ipo_p}) 위로 올라섰습니다. 바닥 확인 신호입니다."
                })

        # --- 4. 기관 투자심리 호조 시그널 ---
        try:
            tab4_key = f"{ticker}_Tab4_ko"
            res_tab4 = supabase.table("analysis_cache").select("content").eq("cache_key", tab4_key).execute()
            if res_tab4.data:
                import json
                tab4_data = json.loads(res_tab4.data[0]['content'])
                rating_val = str(tab4_data.get('rating', '')).upper()
                score_val = str(tab4_data.get('score', '0')).strip()
                if ("BUY" in rating_val) or (score_val in ["4", "5"]):
                    new_alerts.append({
                        "ticker": ticker, "alert_type": "INST_UPGRADE", "title": f"{ticker} 기관투자자평가상향조정(Buy grade)", 
                        "message": f"월가 분석 결과, 투자 의견이 '{tab4_data.get('rating')}'(으)로 평가되었습니다."
                    })
        except: pass
            
    if new_alerts:
        batch_upsert("premium_alerts", new_alerts, on_conflict="ticker,alert_type")
        print(f"✅ {len(new_alerts)}개의 프리미엄 신호가 DB에 적재되었습니다.")

# ==========================================
# [3] AI 분석 함수들 (프롬프트 100% 보존 + 방어막 추가)
# ==========================================

# ==========================================
# [SEC EDGAR API 헬퍼 함수] - 무료, 주 1회 호출용
# ==========================================
# SEC API는 User-Agent 헤더(이름+이메일)가 없으면 접속을 차단하므로 필수로 넣어야 합니다.
SEC_HEADERS = {'User-Agent': 'UnicornFinder App admin@unicornfinder.com'}

# ==========================================
# [SEC EDGAR API 헬퍼 함수] 
# ==========================================
SEC_HEADERS = {'User-Agent': 'UnicornFinder App admin@unicornfinder.com'}

def normalize_company_name(name):
    """회사 이름에서 특수문자, 대소문자, Inc/Corp 등을 제거하여 순수 텍스트만 추출합니다."""
    if not name or pd.isna(name): return ""
    name = str(name).lower()
    # Inc, Corp, Co, Ltd, Plc, Group 등의 흔한 법인 형태소 제거
    name = re.sub(r'\b(inc|corp|corporation|co|ltd|plc|group|company|holdings)\b\.?', '', name)
    # 영문자와 숫자만 남기고 모두 제거 (띄어쓰기 포함)
    name = re.sub(r'[^a-z0-9]', '', name)
    return name

def get_sec_master_mapping():
    """SEC에서 공식 데이터를 받아와 CIK 매핑과 '공식 티커' 매핑 두 가지 사전을 반환합니다."""
    try:
        res = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS, timeout=10)
        data = res.json()
        
        cik_mapping = {}         # { "AAPL": "0000320193" } (기존용도)
        name_to_ticker_map = {}  # { "apple": "AAPL" } (티커 교정용도)
        
        for k, v in data.items():
            official_ticker = v['ticker']
            cik_str = str(v['cik_str']).zfill(10)
            raw_title = v['title']
            
            cik_mapping[official_ticker] = cik_str
            
            # 회사 이름을 정규화해서 딕셔너리에 저장
            clean_name = normalize_company_name(raw_title)
            if clean_name:
                name_to_ticker_map[clean_name] = official_ticker
                
        return cik_mapping, name_to_ticker_map
    except Exception as e:
        print(f"SEC Mapping Error: {e}")
        return {}, {}

def get_fallback_cik(ticker, company_name, api_key):
    """[3중 추적 엔진] 명단에 없는 기업의 CIK를 3가지 방법으로 기어코 찾아냅니다."""
    # 1단계: FMP 기업 프로필 API에서 직접 추출
    try:
        url = f"https://financialmodelingprep.com/stable/profile?symbol={ticker}&apikey={api_key}"
        res = requests.get(url, timeout=5).json()
        if res and isinstance(res, list) and 'cik' in res[0] and res[0]['cik']:
            return str(res[0]['cik']).zfill(10)
    except: pass

    # 2단계: SEC EDGAR에 티커(Ticker)로 강제 검색
    try:
        url = f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={ticker}&action=getcompany&output=atom"
        res = requests.get(url, headers=SEC_HEADERS, timeout=5)
        match = re.search(r'<cik>(\d+)</cik>', res.text)
        if match: return str(match.group(1)).zfill(10)
    except: pass
    
    # 3단계: SEC EDGAR에 '회사 이름'으로 강제 검색
    if company_name:
        try:
            clean_name = str(company_name).split()[0].replace(',', '').strip()
            url = f"https://www.sec.gov/cgi-bin/browse-edgar?company={clean_name}&action=getcompany&output=atom"
            res = requests.get(url, headers=SEC_HEADERS, timeout=5)
            match = re.search(r'<cik>(\d+)</cik>', res.text)
            if match: return str(match.group(1)).zfill(10)
        except: pass
        
    return None


def check_sec_specific_filing(cik, target_form):
    """특정 CIK 기업이 10-K, RW, S-1 등의 서류를 제출했는지 확인하고 가장 최근 날짜를 반환합니다."""
    try:
        time.sleep(0.5) # SEC 초당 10회 제한 방어
        res = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=SEC_HEADERS, timeout=10)
        filings = res.json().get('filings', {}).get('recent', {})
        
        forms = filings.get('form', [])
        dates = filings.get('filingDate', [])
        
        # 최신 제출본부터 검사
        for i, form in enumerate(forms):
            if target_form.upper() in str(form).upper():
                return dates[i] # 서류가 있으면 제출 날짜 반환 (예: '2025-10-12')
        return None # 서류가 없으면 None
    except:
        return None

# ==========================================
# [신규 추가] FMP 프리미엄 헬퍼 함수 (Tab 0 용)
# ==========================================
def fetch_fmp_8k_events(symbol, api_key):
    """[Tab 0] 기업의 최근 8-K(중대 이벤트: M&A, 소송, 임원교체 등)를 가져옵니다."""
    try:
        # 💡 [Stable 주소로 교체 완료]
        url = f"https://financialmodelingprep.com/stable/sec-filings?symbol={symbol}&type=8-K&limit=3&apikey={api_key}"
        res = requests.get(url, timeout=5).json()
        
        if isinstance(res, dict) and "Error Message" in res:
            print(f"🚫 [Tab 0 8-K 차단됨] -> {res['Error Message']}")
            return "No recent 8-K events."
            
        if res and isinstance(res, list) and len(res) > 0:
            events = [f"- Date: {r.get('fillingDate')} | Link: {r.get('finalLink')}" for r in res]
            return "\n".join(events)
        return "No recent 8-K events."
    except Exception as e:
        print(f"8-K Fetch Error for {symbol}: {e}")
        return "No recent 8-K events."
        
def fetch_fmp_premium_news(symbol, api_key):
    try:
        url = f"https://financialmodelingprep.com/stable/news/stock-latest?symbol={symbol}&limit=5&apikey={api_key}"
        res = requests.get(url, timeout=5).json()
        if isinstance(res, dict) and "Error Message" in res:
            print(f"🚫 [Tab 1 프리미엄 뉴스 차단됨] -> {res['Error Message']}")
            return "No recent premium news."
        if res and isinstance(res, list) and len(res) > 0:
            news_list = [f"- [{r.get('publishedDate')}] {r.get('title')} (Source: {r.get('site')})" for r in res]
            return "\n".join(news_list)
        return "No recent premium news."
    except: return "No recent premium news."

def fetch_fmp_earnings_call(symbol, api_key):
    try:
        # 1단계: 가능한 연도와 분기를 먼저 리스트로 조회
        list_url = f"https://financialmodelingprep.com/stable/earnings-transcript-list?symbol={symbol}&apikey={api_key}"
        list_res = requests.get(list_url, timeout=5).json()
        
        if not list_res or isinstance(list_res, dict): return "No earnings call transcript available."
        
        # 2단계: 가장 최신 분기 데이터(인덱스 0)의 연도와 분기 파싱
        latest = list_res[0]
        year = latest.get('year')
        quarter = latest.get('quarter')
        
        # 3단계: 실제 트랜스크립트 텍스트 조회
        url = f"https://financialmodelingprep.com/stable/earning-call-transcript?symbol={symbol}&year={year}&quarter={quarter}&apikey={api_key}"
        res = requests.get(url, timeout=5).json()
        
        if isinstance(res, dict) and "Error Message" in res: return "No earnings call transcript available."
        if res and isinstance(res, list) and len(res) > 0:
            content = res[0].get('content', '')[:3000]
            return f"[Quarter: {quarter} / Year: {year}]\n{content}..."
        return "No earnings call transcript available."
    except: return "No earnings call transcript available."


# ==========================================
# [신규 추가] FMP 프리미엄 헬퍼 함수 (Tab 0 용)
# ==========================================
def fetch_fmp_8k_events(symbol, api_key):
    """[Tab 0] 기업의 최근 8-K(중대 이벤트: M&A, 소송, 임원교체 등)를 가져옵니다."""
    try:
        url = f"https://financialmodelingprep.com/stable/sec-filings?symbol={symbol}&type=8-K&limit=3&apikey={api_key}"
        res = requests.get(url, timeout=5).json()
        if res and isinstance(res, list) and len(res) > 0:
            events = [f"- Date: {r.get('fillingDate')} | Link: {r.get('finalLink')}" for r in res]
            return "\n".join(events)
        return "No recent 8-K events."
    except Exception as e:
        print(f"8-K Fetch Error for {symbol}: {e}")
        return "No recent 8-K events."


# ==========================================
# [완전 교체] run_tab0_analysis 함수 (에러 영구 차단 + 20-F 하이브리드 탐색)
# ==========================================
def run_tab0_analysis(ticker, company_name, ipo_status="Active", ipo_date_str=None, cik_mapping=None):
    if 'model_strict' not in globals() or not model_strict: return
    
    # 🚀 [1] CIK 실시간 확보 로직 (PAYP 성공의 열쇠)
    cik = cik_mapping.get(ticker) if (cik_mapping is not None) else None
    if not cik:
        cik = get_fallback_cik(ticker, company_name, FMP_API_KEY)
        if cik:
            if cik_mapping is not None: cik_mapping[ticker] = cik
            print(f"🔍 [CIK 실시간 획득] {company_name}({ticker}) -> {cik} 추적 성공")
        else:
            print(f"⚠️ [CIK 획득 실패] {company_name}({ticker})의 고유번호를 찾을 수 없습니다.")

    # ---------------------------------------------------------
    # 🚨 [2] 에러 원천 차단: 보조 함수들을 루프보다 무조건 먼저 선언합니다.
    # ---------------------------------------------------------
    def get_localized_meta(lang, doc_type):
        meta_dict = {
            "ko": {
                "S-1": {"p": "Risk Factors, Use of Proceeds, MD&A", "s": "1문단: [핵심 비즈니스 및 스케일] 비즈니스 모델과 MAU, 매출 등 구체적 수치 명시\n2문단: [수익화 및 성장 전략] 시장 규모(TAM) 및 공모 자금의 실질적 사용처\n3문단: [치명적 리스크] 단순 나열이 아닌, 재무/운영에 타격을 줄 가장 치명적인 리스크 1가지"},
                "S-1/A": {"p": "Pricing Terms, Dilution, Changes", "s": "1문단: [변경 사항] 이전 S-1 대비 변경된 핵심 펀더멘털이나 수치\n2문단: [밸류에이션] 제시된 공모가 범위와 그에 따른 시가총액/밸류에이션 분석\n3문단: [주주 영향] 기존 주주 가치 희석 정도와 신규 투자자 관점의 매력도"},
                "F-1": {"p": "Business Scale, Foreign Risk, ADS Structure", "s": "1문단: [비즈니스 스케일 및 우위] MAU, 거래액(GMV), 매출 등 구체적 지표를 동반한 시장 지배력\n2문단: [지배구조 및 주주 권리] ADS 발행 구조 및 지배주주(Controlled Company) 지분율이 일반 주주에게 미치는 영향\n3문단: [로컬 리스크] 환율, 해당 국가 특유의 규제 등 외국 국적 기업으로서의 재무적/정치적 리스크"},
                "FWP": {"p": "Roadshow Highlights, Growth Strategy", "s": "1문단: [핵심 투자 하이라이트] 경영진이 투자자에게 세일즈하는 핵심 비전과 성장 지표\n2문단: [시장 확장 전략] 구체적인 타겟 시장(TAM) 및 신규 수익 모델\n3문단: [공략 의지 및 톤앤매너] 숫자로 뒷받침된 회사의 목표 달성 가능성 (※ 주의: 인수단 연락처 등 법적 문구 무시)"},
                "424B4": {"p": "Final Price, Underwriting, IPO Outcome", "s": "1문단: [최종 가격 및 수요] 확정 공모가의 위치(상단/하단)와 시장 수요 해석\n2문단: [자금 조달 규모] 확정된 조달 자금 총액과 최우선 투입처\n3문단: [유통 물량] 주관사단 및 배정 물량 바탕 상장 초기 유통물량/오버행 예측"},
                "RW": {"p": "Withdrawal Reason, Market Condition", "s": "1문단: [철회 사유] 상장 철회(Withdrawal)를 결정하게 된 핵심 배경\n2문단: [재무적 타격] 자본 조달 실패가 기업 유동성에 미치는 영향\n3문단: [향후 행보] 재상장 시도 또는 M&A 피인수 등 대안 시나리오"},
                "Form 25": {"p": "Delisting Reason, Shareholder Impact", "s": "1문단: [상장 폐지 사유] 자발적 상폐, 피인수, 규정 위반 등 정확한 사유\n2문단: [주주 권리] 상장 폐지 후 기존 주식의 처리 방안 및 주주 권리\n3문단: [향후 상태] 장외시장(OTC) 거래 가능성 및 향후 기업 존속 여부"},
                "10-K": {"p": "Annual Revenue, Operating Income, Growth Rate", "s": "1문단: [연간 성과] 지난 1년간의 실제 매출액($)과 영업이익($), 전년비 성장률(%)\n2문단: [사업 확장] 핵심 사업부별 실적 기여도와 비즈니스 모델 변화\n3문단: [리스크 전망] 향후 재무 수치에 직접적 타격을 줄 수 있는 위험 요소"},
                "10-Q": {"p": "Quarterly Revenue, Net Income, Cash Balances", "s": "1문단: [분기 실적] 이번 분기 실제 매출($) 및 순이익($), 전년 동기 대비 증감률(%)\n2문단: [현금 현황] 보유 현금성 자산의 실제 수치와 단기 유동성 분석\n3문단: [가이던스] 경영진이 제시한 다음 분기 예상 수치 및 성장 근거"},
                "BS": {"p": "Total Assets, Total Liabilities, Cash, Debt", "s": "1문단: [자산 구조] 현금성 자산을 포함한 유동/비유동 자산의 실제 수치($)\n2문단: [부채와 자본] 총부채와 자기자본의 실제 금액($) 및 부채비율\n3문단: [건전성 진단] 수치를 근거로 한 실질적인 단기 지급 능력 및 런웨이 평가"},
                "IS": {"p": "Revenue Growth, Margins, EPS", "s": "1문단: [매출 성과] 실제 매출액(Revenue) 수치와 전년 대비 성장률(%)\n2문단: [이익률 평가] 영업이익과 순이익의 실제 수치($)를 통한 마진 분석\n3문단: [수익성 품질] 주당순이익(EPS)과 일회성 비용 유무를 통한 수익 창출력 요약"},
                "CF": {"p": "Operating CF, CAPEX, FCF", "s": "1문단: [영업현금흐름] 영업활동 현금흐름 수치($)를 통한 자체 자금 창출력 평가\n2문단: [투자 및 CAPEX] 자본적 지출(CAPEX)의 실제 금액과 투자 방향성\n3문단: [현금 생존력] 잉여현금흐름(FCF) 도출 및 추가 자금 조달 필요성 진단"}
            },
            "en": {
                "S-1": {"p": "Risk Factors, Use of Proceeds, MD&A", "s": "Para 1: [Core Business & Scale] Specify business model and concrete figures like MAU and Revenue.\nPara 2: [Monetization & Growth Strategy] Market size (TAM) and actual use of proceeds.\nPara 3: [Critical Risk] One most critical risk that will impact financials/operations, not just a simple list."},
                "S-1/A": {"p": "Pricing Terms, Dilution, Changes", "s": "Para 1: [Changes] Core fundamentals or numbers changed compared to the previous S-1.\nPara 2: [Valuation] Proposed price band and resulting market cap/valuation analysis.\nPara 3: [Shareholder Impact] Dilution for existing shareholders and attractiveness for new investors."},
                "F-1": {"p": "Business Scale, Foreign Risk, ADS Structure", "s": "Para 1: [Business Scale & Edge] Market dominance backed by specific metrics like MAU, GMV, and Revenue.\nPara 2: [Governance & Shareholder Rights] ADS issuance structure and impact of the Controlled Company status on retail shareholders.\nPara 3: [Local Risks] Financial/political risks as a foreign entity, such as FX and local regulations."},
                "FWP": {"p": "Roadshow Highlights, Growth Strategy", "s": "Para 1: [Key Investment Highlights] Core vision and growth metrics pitched by management to investors.\nPara 2: [Market Expansion Strategy] Specific target market (TAM) and new revenue models.\nPara 3: [Commitment & Tone] Feasibility of company goals backed by numbers (※ NOTE: Ignore legal boilerplate like underwriter contacts)."},
                "424B4": {"p": "Final Price, Underwriting, IPO Outcome", "s": "Para 1: [Final Price & Demand] Position of the final IPO price (top/bottom) and market demand interpretation.\nPara 2: [Fundraising Scale] Total amount raised and top priority for fund deployment.\nPara 3: [Float Volume] Expected initial float/overhang based on underwriter allocations."},
                "RW": {"p": "Withdrawal Reason, Market Condition", "s": "Para 1: [Withdrawal Reason] Core background behind the decision to withdraw the IPO.\nPara 2: [Financial Impact] Impact of the fundraising failure on corporate liquidity.\nPara 3: [Future Plans] Alternative scenarios like re-IPO attempts or M&A acquisition."},
                "Form 25": {"p": "Delisting Reason, Shareholder Impact", "s": "Para 1: [Delisting Reason] Exact reason such as voluntary, M&A, or regulatory violation.\nPara 2: [Shareholder Rights] Treatment of existing shares and shareholder rights post-delisting.\nPara 3: [Future Status] Possibility of OTC trading and future corporate existence."},
                "10-K": {"p": "Annual Revenue, Operating Income, Growth Rate", "s": "Para 1: [Annual Performance] Actual Revenue ($), Operating Income ($), and YoY Growth Rate (%) over the past year.\nPara 2: [Business Expansion] Performance contribution by core segments and business model changes.\nPara 3: [Risk Outlook] Risk factors that could directly impact future financial metrics."},
                "10-Q": {"p": "Quarterly Revenue, Net Income, Cash Balances", "s": "Para 1: [Quarterly Results] Actual Revenue ($), Net Income ($), and YoY Growth Rate (%) for this quarter.\nPara 2: [Cash Status] Actual figures of cash equivalents and short-term liquidity analysis.\nPara 3: [Guidance] Management's expected figures for the next quarter and basis for growth."},
                "BS": {"p": "Total Assets, Total Liabilities, Cash, Debt", "s": "Para 1: [Asset Structure] Actual figures ($) of current/non-current assets including cash equivalents.\nPara 2: [Liabilities & Equity] Actual figures ($) of total debt, equity, and debt-to-equity ratio.\nPara 3: [Solvency Diagnosis] Practical assessment of short-term liquidity and runway based on the numbers."},
                "IS": {"p": "Revenue Growth, Margins, EPS", "s": "Para 1: [Revenue Performance] Actual Revenue figures and YoY Growth Rate (%).\nPara 2: [Margin Evaluation] Margin analysis using actual figures ($) of Operating and Net Income.\nPara 3: [Earnings Quality] Summary of profit generation capability via EPS and presence of one-off costs."},
                "CF": {"p": "Operating CF, CAPEX, FCF", "s": "Para 1: [Operating CF] Assessment of self-funding capability via actual Operating Cash Flow ($).\nPara 2: [Investment & CAPEX] Actual amount of Capital Expenditures (CAPEX) and investment direction.\nPara 3: [Cash Survival] Derivation of Free Cash Flow (FCF) and diagnosis of additional funding needs."}
            },
            "ja": {
                "S-1": {"p": "リスク要因, 資金使途, MD&A", "s": "第1段落：[中核事業と規模] ビジネスモデルとMAU、売上などの具体的数値を明記\n第2段落：[収益化と成長戦略] 市場規模(TAM)と公募資金の実質的な使途\n第3段落：[致命的リスク] 単なる羅列ではなく、財務/運営に打撃を与える最も致命的なリスク1つ"},
                "S-1/A": {"p": "条件決定, 希薄化, 変更点", "s": "第1段落：[変更事項] 以前のS-1と比較して変更された中核ファンダメンタルズや数値\n第2段落：[バリュエーション] 提示された公募価格帯とそれに伴う時価総額/バリュエーション分析\n第3段落：[株主への影響] 既存株主の価値希薄化の程度と新規投資家視点での魅力度"},
                "F-1": {"p": "事業規模, 海外リスク, ADS構造", "s": "第1段落：[事業規模と優位性] MAU、取引額(GMV)、売上などの具体的指標を伴う市場支配力\n第2段落：[ガバナンスと株主の権利] ADS発行構造および支配株主(Controlled Company)の持分比率が一般株主に与える影響\n第3段落：[ローカルリスク] 為替、当該国特有の規制など外国籍企業としての財務的/政治的リスク"},
                "FWP": {"p": "ロードショーのハイライト, 成長戦略", "s": "第1段落：[中核投資ハイライト] 経営陣が投資家にアピールする中核ビジョンと成長指標\n第2段落：[市場拡張戦略] 具体的なターゲット市場(TAM)と新規収益モデル\n第3段落：[攻略の意志とトーン] 数値で裏付けられた目標達成の可能性（※注意：引受人の連絡先などの免責事項は無視）"},
                "424B4": {"p": "最終価格, 引受シンジケート, 上場結果", "s": "第1段落：[最終価格と需要] 確定公募価格の位置(上限/下限)と市場需要の解釈\n第2段落：[資金調達規模] 確定した調達資金総額と最優先の投入先\n第3段落：[流通株式数] 引受シンジケートおよび配分物量に基づく上場初期の流通株式/オーバーハング予測"},
                "RW": {"p": "撤回理由, 市場環境", "s": "第1段落：[撤回事由] 上場撤回(Withdrawal)を決定した中核的な背景\n第2段落：[財務的打撃] 資金調達の失敗が企業の流動性に与える影響\n第3段落：[今後の動向] 再上場の試みまたはM&Aによる買収などの代替シナリオ"},
                "Form 25": {"p": "上場廃止理由, 株主への影響", "s": "第1段落：[上場廃止事由] 自主的廃止、買収、規定違反などの正確な理由\n第2段落：[株主の権利] 上場廃止後の既存株式の処理方法および株主の権利\n第3段落：[今後の状態] 店頭市場(OTC)での取引の可能性および今後の企業の存続可否"},
                "10-K": {"p": "通期売上高, 営業利益, 成長率", "s": "第1段落：[通期実績] 過去1年間の実際の売上高($)と営業利益($)、前年比成長率(%)\n第2段落：[事業拡張] 中核事業セグメント別の業績貢献度とビジネスモデルの変化\n第3段落：[リスク展望] 今後の財務数値に直接的な打撃を与え得る危険要因"},
                "10-Q": {"p": "四半期売上, 純利益, 現金残高", "s": "第1段落：[四半期実績] 当四半期の実際の売上($)および純利益($)、前年同期比増減率(%)\n第2段落：[現金状況] 保有する現金性資産の実際の数値と短期流動性分析\n第3段落：[ガイダンス] 経営陣が提示した次四半期の予想数値と成長の根拠"},
                "BS": {"p": "資産合計, 負債合計, 現金, 負債", "s": "第1段落：[資産構造] 現金性資産を含む流動/非流動資産の実際の数値($)\n第2段落：[負債と資本] 総負債と自己資本の実際の金額($)および負債比率\n第3段落：[健全性診断] 数値に基づく実質的な短期支払能力およびランウェイの評価"},
                "IS": {"p": "売上成長, 利益率, EPS", "s": "第1段落：[売上実績] 実際の売上高(Revenue)数値と前年比成長率(%)\n第2段落：[利益率評価] 営業利益と純利益の実際の数値($)を通じたマージン分析\n第3段落：[収益の質] EPSと一過性費用の有無を通じた収益創出力の要約"},
                "CF": {"p": "営業CF, CAPEX, FCF", "s": "第1段落：[営業キャッシュフロー] 営業CF数値($)を通じた独自の資金創出力の評価\n第2段落：[投資とCAPEX] 資本的支出(CAPEX)の実際の金額と投資の方向性\n第3段落：[現金の生存力] フリーキャッシュフロー(FCF)の算出および追加資金調達の必要性診断"}
            },
            "zh": {
                "S-1": {"p": "风险因素, 资金用途, MD&A", "s": "第一段：[核心业务与规模] 明确业务模型及MAU、营收等具体数据\n第二段：[变现与增长战略] 市场规模(TAM)及募集资金的实际用途\n第三段：[致命风险] 指出1个将对财务/运营造成打击的最致命风险，而非简单罗列"},
                "S-1/A": {"p": "定价条款, 股权稀释, 变更点", "s": "第一段：[变更事项] 与此前S-1相比，核心基本面或数据的变化\n第二段：[估值] 给出的发行价区间及相应的市值/估值分析\n第三段：[股东影响] 现有股东价值的稀释程度及对新投资者的吸引力"},
                "F-1": {"p": "业务规模, 海外风险, ADS结构", "s": "第一段：[业务规模与优势] 带有MAU、交易额(GMV)、营收等具体指标的市场统治力\n第二段：[治理与股东权利] ADS发行结构及控股股东(Controlled Company)持股比例对散户的影响\n第三段：[本地风险] 汇率、该国特有监管等作为外国企业的财务/政治风险"},
                "FWP": {"p": "路演亮点, 增长战略", "s": "第一段：[核心投资亮点] 管理层向投资者推介的核心愿景与增长指标\n第二段：[市场扩张战略] 具体的目标市场(TAM)及新的盈利模式\n第三段：[攻坚意愿与基调] 用数据支撑的公司目标达成可能性（※注意：忽略承销商联系方式等免责声明）"},
                "424B4": {"p": "最终价格, 承销, IPO结果", "s": "第一段：[最终价格与需求] 最终定价的位置(上限/下限)及市场需求解读\n第二段：[融资规模] 确定的融资总额及最优先的资金投入方向\n第三段：[流通盘] 基于承销团及配售情况的上市初期流通股/抛压预测"},
                "RW": {"p": "撤回原因, 市场环境", "s": "第一段：[撤回原因] 决定撤回上市(Withdrawal)的核心背景\n第二段：[财务打击] 融资失败对企业流动性的影响\n第三段：[未来动向] 尝试重新上市或被M&A收购等替代方案"},
                "Form 25": {"p": "退市原因, 股东影响", "s": "第一段：[退市原因] 自愿退市、被收购、违规等准确原因\n第二段：[股东权利] 退市后现有股票的处理方案及股东权利\n第三段：[未来状态] 场外市场(OTC)交易的可能性及企业未来的存续状态"},
                "10-K": {"p": "年度营收, 营业利润, 增长率", "s": "第一段：[年度表现] 过去一年的实际营收($)和营业利润($)，及同比增幅(%)\n第二段：[业务扩张] 核心业务板块的业绩贡献度及商业模式的变化\n第三段：[风险展望] 可能对未来财务数据造成直接打击的危险因素"},
                "10-Q": {"p": "季度营收, 净利润, 现金储备", "s": "第一段：[季度业绩] 本季度的实际营收($)和净利润($)，及同比增幅(%)\n第二段：[现金状况] 持有的现金及现金等价物实际数值与短期流动性分析\n第三段：[业绩指引] 管理层给出的下季度预期数值及增长依据"},
                "BS": {"p": "总资产, 总负债, 现金, 债务", "s": "第一段：[资产结构] 包含现金等价物的流动/非流动资产的实际数值($)\n第二段：[负债与资本] 总负债和股东权益的实际金额($)及资产负债率\n第三段：[健康度诊断] 基于数据对短期偿债能力及资金存续期的实质性评估"},
                "IS": {"p": "营收增长, 毛利率, EPS", "s": "第一段：[营收表现] 实际营收(Revenue)数值及同比增长率(%)\n第二段：[利润率评估] 通过营业利润和净利润的实际数值($)进行利润率分析\n第三段：[收益质量] 结合每股收益(EPS)及有无一次性费用总结盈利能力"},
                "CF": {"p": "经营CF, CAPEX, FCF", "s": "第一段：[经营现金流] 通过经营活动现金流数值($)评估企业的自我造血能力\n第二段：[投资与CAPEX] 资本支出(CAPEX)的实际金额及投资方向\n第三段：[现金存续力] 推算自由现金流(FCF)并诊断是否需要额外融资"}
            }
        }
        lang_group = meta_dict.get(lang, meta_dict['ko'])
        # Fallback to Korean structure if a doc type is somehow missing
        fallback_meta = meta_dict['ko'].get(doc_type, meta_dict['ko']['S-1'])
        return lang_group.get(doc_type, fallback_meta)

    def get_format_instruction(lang):
        # 💡 [복원 및 강화] **[소제목]** 형식 유지 + 줄바꿈(Enter 2번) 강제 + 분량(4~5문장) 통제 + 숫자 강조 금지
        if lang == 'en': 
            return "- Write exactly 3 paragraphs. Separate each paragraph with a blank line (Enter twice).\n- Each paragraph MUST be 4-5 sentences long.\n- Begin each paragraph with a bold subheading like **[Subheading]**.\n- DO NOT bold numbers."
        elif lang == 'ja': 
            return "- 必ず3つの段落に分け、各段落の間には空行（Enter 2回）を入れてください。\n- 各段落は必ず4〜5文で構成してください。\n- 各段落の先頭は必ず **[見出し]** のように太字にして始めてください。\n- 本文の数値に太字（**）は絶対に使用しないでください。"
        elif lang == 'zh': 
            return "- 必须严格分为3个段落，每段之间留有空行（按两下Enter）。\n- 每个段落必须包含4-5个句子。\n- 每个段落必须以加粗的 **[副标题]** 开头。\n- 绝对不要对正文中的数字使用加粗。"
        else: 
            return "- 반드시 3개의 문단으로 작성하며, 문단과 문단 사이에는 반드시 '빈 줄(Enter 2번)'을 넣어 분리하세요.\n- 각 문단은 반드시 4~5줄(문장) 길이로 작성하세요.\n- 각 문단은 반드시 **[소제목]** 형태로 굵게 강조하여 시작하세요.\n- 단, 본문 내용의 '숫자'에는 절대 강조(**) 기호를 쓰지 마세요."

    def get_missing_document_message(lang, doc_type):
        msg_map = {
            "ko": {
                "S-1": "**[안내]** 해당 기업은 해외 국적 발행인(Foreign Issuer) 또는 SPAC으로 식별됩니다. 상세 공시 데이터는 **[F-1]** 섹션을 참조하십시오.",
                "F-1": "**[안내]** 미국 내국 법인(Domestic Issuer)으로 확인되었습니다. 규정에 따른 공시 내역은 **[S-1]** 섹션에서 제공됩니다.",
                "S-1/A": "**[공시대기중]** 최초 신고서 제출 이후의 정정 신고서(S-1/A)가 아직 공시되지 않았습니다. 공모가 밴드 확정 시 실시간 업데이트됩니다.",
                "FWP": "**[공시대기중]** 현재 해당 기업의 추가 로드쇼 자료나 마케팅용 자유 양식 증권신고서(FWP)가 SEC에 등록되지 않은 상태입니다.",
                "424B4": "**[공시대기중]** 최종 공모가 확정 서류(424B4)는 통상 상장 직전 24~48시간 이내에 수립됩니다. 확정 즉시 분석 리포트가 생성됩니다.",
                "RW": "**[상태양호]** 현재 상장 철회(RW)와 관련된 특이 사항이 발견되지 않았습니다. 상장 절차가 정상 궤도 내에서 진행 중입니다.",
                "Form 25": "**[상태양호]** 상장 폐지(Delisting) 관련 이벤트가 감지되지 않았습니다. 해당 종목은 정규 시장 내에서 활성 상태를 유지하고 있습니다.",
                "DEFAULT": "**[안내]** 해당 서류의 제출 기한이 도래하지 않았거나 시스템 내의 아카이빙 작업이 진행 중입니다."
            },
            "en": {
                "S-1": "**[Issuer Classification]** Identified as a Foreign Issuer or SPAC. Please refer to the **[F-1]** section for primary disclosure data.",
                "F-1": "**[Issuer Classification]** Identified as a US Domestic Issuer. Regulatory filings are provided in the **[S-1]** section.",
                "S-1/A": "**[Filing Status]** The amended registration statement (S-1/A) following the initial filing has not yet been disclosed. Real-time updates will follow upon price band finalization.",
                "FWP": "**[Supplemental Info]** No additional roadshow materials or Free Writing Prospectuses (FWP) have been registered with the SEC at this time.",
                "424B4": "**[Pricing Finalization]** The final prospectus (424B4) is typically established within 24-48 hours prior to the IPO. Analysis will be generated immediately upon confirmation.",
                "RW": "**[Offering Status]** No specific issues regarding withdrawal (RW) have been detected. The IPO process is proceeding within the normal track.",
                "Form 25": "**[Listing Status]** No delisting events (Form 25) have been detected. The ticker remains active within the regular market.",
                "DEFAULT": "**[Data Sync]** The filing deadline has not yet been met, or archiving within the SEC EDGAR system is currently in progress."
            },
            "ja": {
                "S-1": "**[発行体分類]** 外国籍発行体（Foreign Issuer）またはSPACとして識別されました。詳細な公示データは **[F-1]** セクションをご参照ください。",
                "F-1": "**[発行体分類]** 米国内국法人（Domestic Issuer）として確認されました。規定に基づく公示内容は **[S-1]** セクションで提供されます。",
                "S-1/A": "**[公示ステータス]** 初回届出書提出後の訂正届出書（S-1/A）はまだ公示されていません。公募価格帯の確定時にリアルタイムで更新されます。",
                "FWP": "**[補足情報]** 現在、当該企業の追加ロードショー資料やマーケティング用自由方式目論見書（FWP）はSECに登録されていません。",
                "424B4": "**[価格確定]** 最終公募価格確定書類（424B4）は通常、上場直前の24〜48時間以内に作成されます。確定次第、分析レポートが生成されます。",
                "RW": "**[募集ステータス]** 現在、上場撤回（RW）に関する特記事項は見当たりません。上場手続きは正常な軌道で進行中です。",
                "Form 25": "**[上場ステータス]** 上場廃止（Delisting）関連のイベントは検知されていません。当該銘柄は正規市場内で活性状態を維持しています。",
                "DEFAULT": "**[データ同期]** 当該書類の提出期限が未到来か、SEC EDGARシステム内でのアーカイブ処理が進行中です。"
            },
            "zh": {
                "S-1": "**[发行人分类]** 该企业被识别为外国发行人 (Foreign Issuer) 或 SPAC。请参阅 **[F-1]** 栏目获取详细公告数据。",
                "F-1": "**[发行人分类]** 已确认该企业为美国本土发行人 (Domestic Issuer)。根据规定的公告内容请在 **[S-1]** 栏目查看。",
                "S-1/A": "**[申报状态]** 提交首次登记表后的修订案 (S-1/A) 尚未公布。发行价区间确定后将实时更新。",
                "FWP": "**[补充信息]** 目前该企业尚未在 SEC 注册额外的路演资料或营销用自由撰写招股说明书 (FWP)。",
                "424B4": "**[定价确认]** 最终定价公告 (424B4) 通常在上市前 24-48 小时内完成。确认后将立即生成分析报告。",
                "RW": "**[发行状态]** 目前未发现与撤回上市 (RW) 相关的异常情况。上市程序正处于正常推进轨道。",
                "Form 25": "**[上市状态]** 未检测到退市 (Delisting) 相关事件。该股票在正规市场内保持活跃状态。",
                "DEFAULT": "**[数据同步]** 该文件的提交截止日期尚未到期，或 SEC EDGAR 系统正在进行归档处理。"
            }
        }
        lang_dict = msg_map.get(lang, msg_map['ko'])
        return lang_dict.get(doc_type, lang_dict.get('DEFAULT'))

    def get_localized_instruction(lang, ticker, topic, company_name, meta, sec_fact_prompt, format_inst, filing_text=""):
        base_msg = ""
        if filing_text and len(filing_text) > 100:
            base_msg = f"\n\n[ACTUAL SEC FILING CONTENT - MUST USE THIS AS SOURCE]\n{filing_text}\n"
        else:
            base_msg = "\n\n(Note: Actual filing content is currently unavailable.)\n"

        # 🚨 [언어별 맞춤형 철권 통제 규칙]
        if lang == 'en':
            # 💡 [핵심] f""" 로 변경하여 {ticker} 변수 삽입
            common_rules = f"""
[STRICT RULES FOR WALL STREET ANALYST]
1. HARD NUMBERS ONLY: Extract Revenue, Profit, MAU, GMV, or Market Share figures. If a number exists in the text, it MUST be in the summary.
2. NO VAGUE FILLERS: Never use phrases like "aims to increase awareness." Replace them with specific data.
3. NO AI CHAT: 🚨 DO NOT use phrases like "Here is the report" or "Understood". Start the very first word with the actual analysis.
4. NO MAIN TITLE: 🚨 DO NOT write a main title or report header like "## Company Analysis Report" at the top. Just output the 3 paragraphs directly.
5. LANGUAGE PURITY: 🚨 You MUST write entirely in English. DO NOT mix any other languages.
6. NEVER CONFUSE TICKER: 🚨 The correct ticker is '{ticker}'. Do NOT mistake document types (like FWP, S-1) for the ticker symbol.
"""
            return f"You are a Lead Buy-Side Analyst.\nTarget: {company_name} ({ticker}) - {topic}\n{sec_fact_prompt}\n{base_msg}\n{common_rules}\n[Structure]\n{meta['s']}\n{format_inst}"

        elif lang == 'ja':
            common_rules = f"""
[ウォール街アナリストのための厳格な規則]
1. 数値データ必須: 売上、利益、MAU、GMV、または市場シェアの数値を必ず抽出してください。本文に数値がある場合、必ず要約に含めてください。
2. 曖昧な表現禁止: 「認知度向上を目指す」のような曖昧なフレーズは使用せず、具体的なデータに置き換えてください。
3. AIの挨拶禁止: 🚨 「承知いたしました」「レポートは以下の通りです」などの挨拶は絶対に使用しないでください。最初の文字からすぐに分析内容を始めてください。
4. メインタイトル禁止: 🚨 最上部に「## 企業分析レポート」のような見出しやタイトルは絶対に書かないでください。すぐに3つの段落のみを出力してください。
5. 言語の純粋性: 🚨 全て自然な日本語のみで記述してください。英語の文章を混ぜないでください。企業名/ティッカー以外のすべての専門用語は日本語に翻訳してください。
6. ティッカー誤記厳禁: 🚨 正確なティッカーは '{ticker}' です。FWPやS-1などの「書類名」をティッカーと勘違いして記述しないでください。
"""
            return f"あなたはバイサイドのシニアアナリストです。\n分析対象: {company_name} ({ticker}) - {topic}\n{sec_fact_prompt}\n{base_msg}\n{common_rules}\n[構成]\n{meta['s']}\n{format_inst}"

        elif lang == 'zh':
            common_rules = f"""
[华尔街分析师的严格规则]
1. 必须包含具体数据: 请提取营收、利润、MAU、GMV或市场份额等数据。如果原文中有数字，摘要中必须包含。
2. 禁止模糊表达: 绝对不要使用“旨在提高知名度”等模糊词语。请用具体数据代替。
3. 禁止AI问候语: 🚨 绝对不要使用“好的”、“以下是报告”等词语。从第一个字开始直接输出分析内容。
4. 禁止主标题: 🚨 绝对不要在顶部写“## 公司分析报告”之类的主标题。直接输出3个段落即可。
5. 语言纯洁性: 🚨 必须完全使用简体中文编写。严禁混入英文句子。除特定的公司名称/代码外，所有专业术语必须翻译成中文。
6. 严禁混淆代码: 🚨 准确的股票代码是 '{ticker}'。绝对不要将 FWP、S-1 等“文件类型”误认为是股票代码。
"""
            return f"您是买方资深分析师。\n分析目标: {company_name} ({ticker}) - {topic}\n{sec_fact_prompt}\n{base_msg}\n{common_rules}\n[结构要求]\n{meta['s']}\n{format_inst}"

        else: # ko
            common_rules = f"""
[월스트리트 애널리스트를 위한 엄격한 작성 규칙]
1. 수치 데이터 필수: 매출, 이익, MAU, GMV 또는 시장 점유율 수치를 반드시 추출하세요. 원문에 숫자가 있다면 요약본에 무조건 포함되어야 합니다.
2. 추상적 표현 금지: "인지도를 높이는 것을 목표로 한다" 같은 모호한 문구를 절대 쓰지 말고, 구체적인 데이터로 대체하세요.
3. AI 인사말 금지: 🚨 "알겠습니다", "요약해 드리겠습니다" 같은 인사말이나 서론을 절대 쓰지 마세요. 첫 글자부터 곧바로 분석 내용(본론)만 출력하세요.
4. 메인 제목 금지: 🚨 글 맨 위에 "## 기업 분석 보고서" 같은 메인 제목(타이틀)을 절대 달지 마세요. 곧바로 3개의 문단만 작성하세요.
5. 언어 순수성: 🚨 반드시 순수한 한국어로만 작성하세요. 영어 문장을 섞어 쓰지 마세요. 고유한 기업명/티커를 제외한 모든 영단어는 한국어로 번역하세요.
6. 어투(문체) 고정: 🚨 반드시 모든 문장의 끝을 '~습니다', '~합니다', '~입니다' 형태의 정중한 존댓말(경어체)로 마무리하세요. '~한다', '~이다' 형태의 평어체는 절대 금지합니다.
7. 티커(Ticker) 오기재 절대 금지: 🚨 해당 기업의 정확한 티커 심볼은 '{ticker}'입니다. FWP, S-1, F-1 같은 'SEC 문서명'을 티커 심볼로 착각해서 기재하는 치명적인 실수를 절대 하지 마세요.
"""
            return f"당신은 월스트리트 바이사이드(Buy-side) 수석 애널리스트입니다.\n분석 대상: {company_name} ({ticker}) - {topic}\n{sec_fact_prompt}\n{base_msg}\n{common_rules}\n[내용 구성 지침]\n{meta['s']}\n{format_inst}"
    # ---------------------------------------------------------
    # 🚀 [3] 기업 상태 및 기간 분석
    # ---------------------------------------------------------
    status_lower = str(ipo_status).lower()
    is_withdrawn = any(x in status_lower for x in ['철회', '취소', 'withdrawn'])
    is_delisted = any(x in status_lower for x in ['폐지', 'delisted'])
    
    days_passed = 0
    is_over_1y = False
    if ipo_date_str:
        try:
            ipo_dt = pd.to_datetime(ipo_date_str).date()
            days_passed = (datetime.now().date() - ipo_dt).days
            if days_passed > 365: is_over_1y = True
        except: pass

    valid_hours = 168 if (is_withdrawn or is_delisted or is_over_1y) else 24
    limit_time_str = (datetime.now() - timedelta(hours=valid_hours)).isoformat()

    # 대상 서류 배정
    if is_withdrawn: target_topics = ["S-1", "S-1/A", "F-1", "RW"]
    elif is_delisted: target_topics = ["S-1", "10-K", "20-F", "Form 25"]
    elif is_over_1y: target_topics = ["10-K", "10-Q", "BS", "IS", "CF"]
    else: target_topics = ["S-1", "S-1/A", "F-1", "FWP", "424B4"]

    # ---------------------------------------------------------
    # 🚀 [4] 8-K 분석 섹션 (다국어 프롬프트 100% 보존)
    # ---------------------------------------------------------
    f_date_8k, f_text_8k = fetch_sec_filing_text(ticker, "8-K", FMP_API_KEY, cik)
    if f_text_8k and len(f_text_8k) > 100:
        raw_cache_key = f"{ticker}_8K_RawData_v3"
        try:
            res_raw = supabase.table("analysis_cache").select("content").eq("cache_key", raw_cache_key).execute()
            if not res_raw.data or f_text_8k[:500] != res_raw.data[0]['content'][:500]:
                batch_upsert("analysis_cache", [{"cache_key": raw_cache_key, "content": f_text_8k[:2000], "updated_at": datetime.now().isoformat()}], "cache_key")
                batch_upsert("premium_alerts", [{"ticker": ticker, "alert_type": "8K_UPDATE", "title": f"{ticker} 8-K 업데이트", "message": "새로운 8-K(중대 이벤트) 공시 본문 분석이 완료되었습니다."}], on_conflict="ticker,alert_type")
                
                for lang_code in SUPPORTED_LANGS.keys():
                    cache_key_8k = f"{company_name}_8-K_Tab0_v16_{lang_code}"
                    
                    # 💡 [핵심 수정] 8-K도 다른 서류들과 동일하게 "소제목 형태"를 강제하도록 문구 변경!
                    if lang_code == 'ko':
                        meta_8k = {"p": "Material Events", "s": "1문단: **[핵심 이벤트]** 발생 사유 요약\n2문단: **[재무 파급력]** 영향 분석\n3문단: **[향후 전망]** 투자 포인트"}
                    elif lang_code == 'ja':
                        meta_8k = {"p": "重要イベント", "s": "第1段落：**[核心イベント]** 発生理由の要約\n第2段落：**[財務影響]** 影響分析\n第3段落：**[今後の展望]** 投資ポイント"}
                    elif lang_code == 'zh':
                        meta_8k = {"p": "重大事件", "s": "第一段：**[核心事件]** 发生原因摘要\n第二段：**[财务影响]** 影响分析\n第三段：**[未来展望]** 投资要点"}
                    else: # en
                        meta_8k = {"p": "Material Events", "s": "Para 1: **[Core Event]** Reason summary\nPara 2: **[Financial Impact]** Analysis\nPara 3: **[Future Outlook]** Key points"}
                        
                    prompt_8k = get_localized_instruction(lang_code, ticker, "8-K", company_name, meta_8k, f"[SEC FACT CHECK] Filed on {f_date_8k}", get_format_instruction(lang_code), f_text_8k[:40000])
                    
                    try:
                        # 💡 [핵심 수정] model -> model_strict 로 이름 변경!
                        resp_8k = model_strict.generate_content(prompt_8k)
                        if resp_8k and resp_8k.text:
                            batch_upsert("analysis_cache", [{"cache_key": cache_key_8k, "content": resp_8k.text.strip(), "updated_at": datetime.now().isoformat()}], "cache_key")
                            print(f"🚨 [{ticker}] 8-K 본문 분석 캐싱 완료 ({lang_code})")
                    except: pass
        except: pass

    # ---------------------------------------------------------
    # 🚀 [5] 통합 서류 루프 (우선순위 탐색 + 스마트 Bypass 적용)
    # ---------------------------------------------------------
    for topic in target_topics:
        f_date, f_text = None, None
        
        # 🚨 [확장 완료] 각 서류별로 수정본이나 대체 서류까지 싹 다 뒤져서 찾아옵니다!
        if topic in ["BS", "IS", "CF", "10-K"]:
            priority_targets = ["10-K", "10-K/A", "20-F", "20-F/A"]
        elif topic == "10-Q":
            priority_targets = ["10-Q", "10-Q/A"] # 💡 분기 보고서 수정본 방어 추가!
        elif topic == "F-1":
            priority_targets = ["F-1", "F-1/A", "20-F"] 
        elif topic == "S-1":
            priority_targets = ["S-1", "S-1/A"]
        elif topic == "424B4":
            # 424B4가 없더라도 424B3, 424B5로 공모가가 확정되는 경우 추적
            priority_targets = ["424B4", "424B3", "424B5"]
        else:
            priority_targets = [topic]

        # 우선순위 리스트를 순회하며 하나라도 500자 이상 확보되면 멈춤
        for target in priority_targets:
            f_date, f_text = fetch_sec_filing_text(ticker, target, FMP_API_KEY, cik)
            if f_text and len(f_text) > 500:
                print(f"✅ [{ticker}] {topic} 분석 소스 확보 완료: {target}")
                break

        # 다국어 캐싱 및 AI 호출
        for lang_code in SUPPORTED_LANGS.keys():
            cache_key = f"{company_name}_{topic}_Tab0_v16_{lang_code}"
            try:
                res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time_str).execute()
                if res.data: continue 
            except: pass

            # 스마트 Bypass (부재 시 안내 멘트)
            if not f_text or len(f_text) < 100:
                missing_msg = get_missing_document_message(lang_code, topic)
                formatted_msg = f"<div style='background-color:#f8f9fa; padding:15px; border-radius:8px; color:#555; font-size:15px; line-height:1.6;'>{missing_msg}</div>"
                batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": formatted_msg, "updated_at": datetime.now().isoformat()}], "cache_key")
                continue

            # 진짜 본문 분석 실행
            current_fact_prompt = f"\n[SEC FACT CHECK] Filed on {f_date}."
            meta = get_localized_meta(lang_code, topic)
            prompt = get_localized_instruction(lang_code, ticker, topic, company_name, meta, current_fact_prompt, get_format_instruction(lang_code), f_text)
            
            try:
                response = model_strict.generate_content(prompt)
                if response and response.text:
                    batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": response.text.strip(), "updated_at": datetime.now().isoformat()}], "cache_key")
                    print(f"✅ [{ticker}] {topic} 진짜 본문 분석 완료 ({lang_code})")
            except Exception as e:
                print(f"❌ [{ticker}] {topic} AI 에러: {e}")
                time.sleep(1)

def get_tab0_ec_premium_prompt(lang, ticker, raw_data):
    if lang == 'en':
        return f"""You are a Lead Buy-Side Analyst on Wall Street. Summarize the latest Earnings Call Transcript for {ticker}.
[Strict Rules]
1. Write ENTIRELY in English. DO NOT mix other languages.
2. Write exactly 3 paragraphs:
   - Para 1: [Key Financials & Guidance]
   - Para 2: [Strategic Updates & Growth Drivers]
   - Para 3: [Q&A Highlights]
3. Each paragraph must be 4-5 sentences long, packed with hard numbers and professional insights.
4. DO NOT use markdown bold (**) for numbers.
5. Omit greetings and start the main content immediately with a cold, objective tone.

[Raw Data]:
{raw_data}"""

    elif lang == 'ja':
        return f"""あなたはウォール街のシニア・バイサイドアナリストです。提供されたデータに基づき、{ticker}の最新のアーニングコール(Earnings Call)を日本語で深層要約してください。
[厳格な作成ルール]
1. 全て自然な日本語のみで記述してください。
2. 必ず以下の3つの段落に分けて作成してください：
   - 第1段落: [核心業績とガイダンス]
   - 第2段落: [戦略アップデートと成長ドライバー]
   - 第3段落: [Q&Aハイライト]
3. 各段落は4〜5文で構成し、具体的な数値と専門的な洞察を含めてください。
4. 数値に強調記号（**）は絶対に使用しないでください。
5. 挨拶は省略し、すぐに本題に入ってください。冷静で客観的な分析トーンを維持してください。

[Raw Data]:
{raw_data}"""

    elif lang == 'zh':
        return f"""您是华尔街的资深买方分析师。请根据提供的数据，用简体中文深度总结 {ticker} 的最新财报电话会议(Earnings Call)。
[严格编写规则]
1. 必须完全使用简体中文编写，严禁混用其他语言。
2. 必须严格分为以下3个段落：
   - 第一段: [核心业绩与财务指引]
   - 第二段: [战略更新与增长驱动力]
   - 第三段: [问答环节(Q&A)亮点]
3. 每个段落应包含4-5句话，并提供具体数据和深刻的专业见解。
4. 绝对不要使用星号（**）对数字进行加粗。
5. 省略问候语，直接进入正文。保持冷静、客观和分析的基调。

[Raw Data]:
{raw_data}"""

    else: # ko
        return f"""당신은 월가 수석 바이사이드(Buy-side) 애널리스트입니다. 제공된 데이터를 바탕으로 {ticker}의 최신 어닝 콜(Earnings Call) 스크립트를 한국어로 심층 요약하세요.
[작성 규칙 - 엄격 준수]
1. 반드시 순수한 한국어로만 작성하세요.
2. 반드시 아래 3개의 문단으로 나누어 작성하세요:
   - 1문단: [핵심 실적 및 향후 가이던스]
   - 2문단: [경영진 전략 업데이트 및 성장 동력]
   - 3문단: [애널리스트 Q&A 세션 핵심 하이라이트]
3. 각 문단은 4~5줄(문장) 길이로 묵직하고 구체적인 수치를 포함해 작성하세요.
4. 숫자에 별표(**) 강조를 절대 사용하지 마세요.
5. 인사말을 생략하고 첫 글자부터 본론만 작성하세요. 모든 문장은 반드시 '~습니다', '~ㅂ니다' 형태의 격식 있고 정중한 존댓말(합쇼체)로 작성하세요. (예: ~합니다, ~입니다, ~됩니다, ~전망됩니다 등). 절대 '~한다', '~이다' 형태의 평어체를 사용하지 마세요.

[Raw Data]:
{raw_data}"""

def run_tab0_premium_collection(ticker, company_name):
    """Tab 0의 프리미엄 데이터(어닝 콜)를 수집하고 요약하여 캐싱합니다."""
    if 'model_strict' not in globals() or not model_strict: return
    try:
        limit_time_str = (datetime.now() - timedelta(hours=168)).isoformat() # 어닝콜은 자주 안바뀌므로 7일 유지
        
        # 💡 [안전망 추가] 연도와 분기를 먼저 찾고 최신 트랜스크립트를 호출 (400 에러 완벽 방지)
        try:
            list_url = f"https://financialmodelingprep.com/stable/earnings-transcript-list?symbol={ticker}&apikey={FMP_API_KEY}"
            list_res = requests.get(list_url, timeout=5).json()
            latest = list_res[0] if (isinstance(list_res, list) and len(list_res) > 0) else {"year": "2024", "quarter": 1}
        except:
            latest = {"year": "2024", "quarter": 1}

        url = f"https://financialmodelingprep.com/stable/earning-call-transcript?symbol={ticker}&year={latest.get('year')}&quarter={latest.get('quarter')}&apikey={FMP_API_KEY}"
        ec_raw = get_fmp_data_with_cache(ticker, "RAW_EARNINGS_CALL", url, valid_hours=168)
        
        is_ec_valid = isinstance(ec_raw, list) and len(ec_raw) > 0

        for lang_code in SUPPORTED_LANGS.keys():
            if is_ec_valid:
                ec_summary_key = f"{ticker}_PremiumEarningsCall_v1_{lang_code}"
                try:
                    res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", ec_summary_key).gt("updated_at", limit_time_str).execute()
                    if not res.data:
                        # 텍스트가 너무 길면 AI 토큰 초과 우려가 있으므로 앞부분 15,000자만 발췌
                        content = ec_raw[0].get('content', '')[:15000] 
                        prompt = get_tab0_ec_premium_prompt(lang_code, ticker, content)
                        
                        for attempt in range(3):
                            try:
                                resp = model_strict.generate_content(prompt)
                                if resp and resp.text:
                                    paragraphs = [p.strip() for p in resp.text.split('\n') if len(p.strip()) > 20]
                                    indent_size = "14px" if lang_code == "ko" else "0px"
                                    html_str = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in paragraphs])
                                    
                                    batch_upsert("analysis_cache", [{"cache_key": ec_summary_key, "content": html_str, "updated_at": datetime.now().isoformat()}], "cache_key")
                                    print(f"✅ [{ticker}] 어닝 콜 요약 캐싱 완료 ({lang_code})")
                                    break
                            except Exception as e: time.sleep(1)
                except: pass
    except Exception as e:
        print(f"Tab0 Premium EC Error for {ticker}: {e}")

# ==========================================
# [신규 추가] Tab 2 프리미엄 요약 전용 프롬프트 및 수집 함수 (ESG 등급)
# ==========================================
def get_tab2_esg_premium_prompt(lang, ticker, raw_data):
    if lang == 'en':
        return f"""You are a Lead ESG Analyst on Wall Street. Summarize the latest ESG (Environmental, Social, Governance) data for {ticker}.
[Strict Rules]
1. Write ENTIRELY in English. DO NOT mix other languages.
2. Write exactly 3 paragraphs:
   - Para 1: [Environmental Impact & Risk]
   - Para 2: [Social Responsibility]
   - Para 3: [Corporate Governance & Ethics]
3. Each paragraph must be 4-5 sentences long, packed with specific ESG scores and professional insights.
4. DO NOT use markdown bold (**) for numbers.
5. Omit greetings and start immediately with a professional, objective tone.

[Raw Data]:
{raw_data}"""

    elif lang == 'ja':
        return f"""あなたはウォール街のシニアESGアナリストです。提供されたデータに基づき、{ticker}の最新のESG(環境、社会、ガバナンス)評価を日本語で深層要約してください。
[厳格な作成ルール]
1. 全て自然な日本語のみで記述してください。
2. 必ず以下の3つの段落に分けて作成してください：
   - 第1段落: [環境への影響とリスク (E)]
   - 第2段落: [社会的責任 (S)]
   - 第3段落: [企業統治と倫理 (G)]
3. 各段落は4〜5文で構成し、具体的なESGスコアと専門的な洞察を含めてください。
4. 数値に強調記号（**）は絶対に使用しないでください。
5. 挨拶は省略し、すぐに本題に入ってください。冷静で客観的な分析トーンを維持してください。

[Raw Data]:
{raw_data}"""

    elif lang == 'zh':
        return f"""您是华尔街的资深ESG分析师。请根据提供的数据，用简体中文深度总结 {ticker} 的最新ESG（环境、社会、治理）评级。
[严格编写规则]
1. 必须完全使用简体中文编写，严禁混用其他语言。
2. 必须严格分为以下3个段落：
   - 第一段: [环境影响与风险 (E)]
   - 第二段: [社会责任 (S)]
   - 第三段: [公司治理与伦理 (G)]
3. 每个段落应包含4-5句话，并提供具体的ESG分数和深刻的专业见解。
4. 绝对不要使用星号（**）对数字进行加粗。
5. 省略问候语，直接进入正文。保持冷静、客观和分析的基调。

[Raw Data]:
{raw_data}"""

    else: # ko
        return f"""당신은 월가 수석 ESG 애널리스트입니다. 제공된 데이터를 바탕으로 {ticker}의 최신 ESG(환경, 사회, 지배구조) 평가 등급을 한국어로 심층 요약하세요.
[작성 규칙 - 엄격 준수]
1. 반드시 순수한 한국어로만 작성하세요.
2. 반드시 아래 3개의 문단으로 나누어 작성하세요:
   - 1문단: [환경(E) 리스크 및 지속가능성]
   - 2문단: [사회적(S) 책임 및 파급력]
   - 3문단: [지배구조(G) 및 투명성 평가]
3. 각 문단은 4~5줄(문장) 길이로 구체적인 ESG 점수를 포함해 작성하세요.
4. 숫자에 별표(**) 강조를 절대 사용하지 마세요.
5. 인사말을 생략하고 첫 글자부터 본론만 작성하세요. 모든 문장은 반드시 '~습니다', '~ㅂ니다' 형태의 격식 있고 정중한 존댓말(합쇼체)로 작성하세요. (예: ~합니다, ~입니다, ~됩니다, ~전망됩니다 등). 절대 '~한다', '~이다' 형태의 평어체를 사용하지 마세요.

[Raw Data]:
{raw_data}"""

def run_tab2_premium_collection(ticker, company_name):
    """Tab 2의 프리미엄 데이터(ESG 평가)를 수집하고 요약하여 캐싱합니다."""
    if 'model_strict' not in globals() or not model_strict: return
    try:
        limit_time_str = (datetime.now() - timedelta(hours=168)).isoformat() # ESG는 자주 안 바뀌므로 7일 유지
        
        # 💡 [Stable 변경 완료] ESG Ratings
        url = f"https://financialmodelingprep.com/stable/esg-ratings?symbol={ticker}&apikey={FMP_API_KEY}"
        esg_raw = get_fmp_data_with_cache(ticker, "RAW_ESG", url, valid_hours=168)
        
        is_esg_valid = isinstance(esg_raw, list) and len(esg_raw) > 0

        for lang_code in SUPPORTED_LANGS.keys():
            if is_esg_valid:
                esg_summary_key = f"{ticker}_PremiumESG_v1_{lang_code}"
                try:
                    res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", esg_summary_key).gt("updated_at", limit_time_str).execute()
                    if not res.data:
                        content = str(esg_raw[0]) # 첫 번째 요소(최신 ESG 데이터) 추출
                        prompt = get_tab2_esg_premium_prompt(lang_code, ticker, content)
                        
                        for attempt in range(3):
                            try:
                                resp = model_strict.generate_content(prompt)
                                if resp and resp.text:
                                    paragraphs = [p.strip() for p in resp.text.split('\n') if len(p.strip()) > 20]
                                    indent_size = "14px" if lang_code == "ko" else "0px"
                                    html_str = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in paragraphs])
                                    
                                    batch_upsert("analysis_cache", [{"cache_key": esg_summary_key, "content": html_str, "updated_at": datetime.now().isoformat()}], "cache_key")
                                    print(f"✅ [{ticker}] ESG 분석 캐싱 완료 ({lang_code})")
                                    break
                            except Exception as e: time.sleep(1)
                except: pass
    except Exception as e:
        print(f"Tab2 Premium ESG Error for {ticker}: {e}")

# ==========================================
# [수정] Tab 1 프리미엄 요약 전용 프롬프트 생성 함수 (다국어 분리 완벽 적용)
# ==========================================
def get_tab1_premium_prompt(lang, type_name, raw_data):
    if lang == 'en':
        return f"""You are a Senior Wall Street Analyst. Summarize the latest corporate trends based on the provided [Raw Data] ({type_name}).
        
[Strict Rules]
1. Write ENTIRELY in English. Do not mix other languages.
2. Write exactly 3 paragraphs (4-5 sentences each).
3. You MUST include the following elements based on the data and your professional insights:
   - Para 1: Core products/services, primary target audience, and main revenue composition.
   - Para 2: Key competitors, market position, recent trends, and future strategic plans.
   - Para 3: Potential risk factors, operational challenges, and overall analytical evaluation.
4. Replace vague statements with concrete numerical data (%, $, volume, market share, etc.) wherever possible.
5. DO NOT use markdown bold (**) for numbers.
6. Omit greetings and start the main content immediately. Maintain a cold, objective, and analytical tone.

[Raw Data]:
{raw_data}"""

    elif lang == 'ja':
        return f"""あなたはウォール街のシニアアナリストです。提供された [Raw Data] ({type_name}) を分析し、非常に詳細で密度の高い企業インテリジェンスレポートを日本語で作成してください。
        
[厳格な作成ルール]
1. 全て自然な日本語のみで記述してください。
2. 必ず3つの段落（各4〜5文）に分けて作成してください。
3. データと専門的な洞察に基づき、以下の要素を必ず含めてください：
   - 第1段落: 主力製品・サービス、主要ターゲット顧客層、および中核となる売上構成。
   - 第2段落: 主要な競合他社、市場でのポジション、最近の動向、および今後の成長計画。
   - 第3段落: 潜在的なリスク要因、経営上の課題、およびアナリストとしての総合評価。
4. 曖昧な表現を避け、可能な限り具体的な数値（%、$、数量、市場シェアなど）を活用してください。
5. 数値に強調記号（**）は絶対に使用しないでください。
6. 挨拶は省略し、すぐに本題に入ってください。冷静で客観的な分析トーンを維持してください。

[Raw Data]:
{raw_data}"""

    elif lang == 'zh':
        return f"""您是华尔街的高级分析师。请分析提供的 [Raw Data] ({type_name})，并用简体中文提供一份高度详细、高密度的企业情报报告。
        
[严格编写规则]
1. 必须完全使用简体中文编写，严禁混用其他语言。
2. 必须严格分为3个段落（每段4-5句话）。
3. 结合数据与专业见解，必须包含以下核心要素：
   - 第一段: 核心产品/服务、主要目标客户群以及主要营收构成。
   - 第二段: 主要竞争对手、市场地位、近期动态以及未来的战略规划。
   - 第三段: 潜在的风险因素、运营挑战以及分析师视角的综合评估。
4. 拒绝模糊表达，尽可能使用具体的数据（如 %、$、数量、市场份额等）来支撑分析。
5. 绝对不要使用星号（**）对数字进行加粗。
6. 省略问候语，直接进入正文。保持冷静、客观和分析的基调。

[Raw Data]:
{raw_data}"""

    else: # ko
        return f"""당신은 월가 출신의 수석 애널리스트입니다. 아래 제공된 [Raw Data]({type_name})를 심층 분석하여, 내용의 밀도가 매우 높은 전문가용 기업 동향 리포트를 한국어로 작성하세요.
        
[작성 규칙 - 엄격 준수]
1. 반드시 순수한 한국어로만 작성하세요.
2. 반드시 3개의 문단으로 나누어 작성하며, 각 문단은 4~5줄(문장) 길이로 상세히 작성하세요.
3. 아래의 필수 요소를 반드시 포함하여 묵직하고 전문적인 통찰을 담아내세요:
   - 1문단: 기업의 주력 제품/서비스, 주요 마케팅(타겟) 대상, 그리고 주요 매출을 이루는 구성
   - 2문단: 시장 내 주요 경쟁 상대, 최근 동향 및 향후 성장 계획
   - 3문단: 잠재적 위험 요소(리스크) 및 월가 애널리스트 관점의 종합 평가
4. 추상적인 표현을 배제하고 가급적 구체적인 수치(%, $, 수량, 점유율 등)를 적극적으로 활용하세요.
5. 숫자에 별표(**) 강조를 절대 사용하지 마세요.
6. 인사말을 생략하고 첫 글자부터 본론만 작성하며, '~습니다', '~ㅂ니다' 형태의 냉철하고 분석적인 어조를 유지하세요.

[Raw Data]:
{raw_data}"""

# ==========================================
# [수정] Tab 1: 뉴스 및 비즈니스 (언어 분리 및 생애주기 맞춤형)
# ==========================================
def run_tab1_analysis(ticker, company_name, ipo_status="Active", ipo_date_str=None):
    if 'model_strict' not in globals() or not model_strict: return
    
    now = datetime.now()
    status_lower = str(ipo_status).lower()
    is_withdrawn = bool(re.search(r'\b(withdrawn|rw|철회|취소)\b', status_lower))
    is_delisted_or_otc = bool(re.search(r'\b(delisted|폐지|otc)\b', status_lower))
    
    is_over_3m = False
    is_over_1y = False
    try:
        if ipo_date_str:
            days_passed = (now.date() - pd.to_datetime(ipo_date_str).date()).days
            if days_passed > 365: is_over_1y = True
            elif days_passed > 90: is_over_3m = True
    except: pass

    # 기업 상태 및 상장 기간별 동적 캐싱 주기
    if is_withdrawn or is_delisted_or_otc or is_over_1y: valid_hours = 24 * 7  
    elif is_over_3m: valid_hours = 24 * 3  
    elif "상장예정" in ipo_status or "30일" in ipo_status: valid_hours = 6
    else: valid_hours = 24

    limit_time_str = (now - timedelta(hours=valid_hours)).isoformat()
    current_date = now.strftime("%Y-%m-%d")
    current_year = now.strftime("%Y")

    # [1] 데이터 확보 (Stable API)
    profile_url = f"https://financialmodelingprep.com/stable/profile?symbol={ticker}&apikey={FMP_API_KEY}"
    profile_data = get_fmp_data_with_cache(ticker, "PROFILE", profile_url, valid_hours=168)
    biz_desc = profile_data[0].get('description') or "" if profile_data else ""

    news_url = f"https://financialmodelingprep.com/stable/news/stock-latest?symbol={ticker}&limit=15&apikey={FMP_API_KEY}"
    news_data = get_fmp_data_with_cache(ticker, "RAW_NEWS_15", news_url, valid_hours=6)
    
    valid_news = [n for n in (news_data or []) if n and str(n.get('symbol', '')).upper() == ticker.upper()]
    fmp_news_context = "\n".join([f"- Title: {n.get('title')} | Date: {n.get('publishedDate')} | Link: {n.get('url')}" for n in valid_news])

    # 💡 하이브리드 판단
    is_fmp_poor = (len(biz_desc) < 50) or (len(valid_news) == 0)
    can_search = is_fmp_poor and (model_search is not None)
    current_model = model_search if can_search else model_strict

    # =========================================================
    # [2] 4개 국어 순회 생성 (프롬프트 완벽 분리)
    # =========================================================
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Tab1_v5_{lang_code}" 
        
        try:
            res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time_str).execute()
            if res.data: continue 
        except: pass

        # ---------------------------------------------------------
        # 🇰🇷 한국어 프롬프트
        # ---------------------------------------------------------
        if lang_code == 'ko':
            sys_prompt = "당신은 최고 수준의 증권사 리서치 센터의 시니어 애널리스트입니다."
            lang_instruction = "반드시 자연스러운 한국어만 사용하세요.\n🚨 [어투 고정]: 모든 문장의 끝은 반드시 '~습니다', '~합니다', '~입니다' 형태의 정중한 존댓말(경어체)로 마무리하십시오. '~한다', '~이다' 형태의 평어체는 절대 금지합니다."
            search_directive = f"🚨 [강제 검색] FMP 데이터가 부족합니다. 즉시 구글 검색 도구를 사용하여 '{company_name} {ticker} business model' 및 '{company_name} 최신 뉴스'를 검색하십시오." if can_search else "🚨 [환각 금지] 오직 제공된 [Part 1], [Part 2] 데이터만 사용하세요."
            
            if is_withdrawn:
                t1_label = "[작업 1: 상장 철회(Withdrawn) 심층 진단]"
                t1_struct = "- 1문단: [철회 배경 진단] 시장 환경 악화 여부 및 내부 펀더멘털/규제 이슈 분석\n- 2문단: [재무적 타격] 자본 조달 실패가 기업의 단기 유동성에 미치는 영향\n- 3문단: [생존 전략] M&A 피인수, 우회 상장, 추가 사모 펀딩 등 대안 시나리오"
            elif is_delisted_or_otc:
                t1_label = "[작업 1: OTC/장외시장 거래 리스크 진단]"
                t1_struct = "- 1문단: [장외 편입 배경] 비즈니스 모델 요약 및 정규 시장 미진입(또는 강등) 사유\n- 2문단: [투자 리스크] 거래량 부족에 따른 유동성 위험(Liquidity Risk) 및 정보 비대칭성 진단\n- 3문단: [장기 전망] 사업 지속 가능성(Going Concern) 및 정규 시장 재진입 가능성"
            elif is_over_1y:
                t1_label = "[작업 1: 상장 1년 차 펀더멘털 점검]"
                t1_struct = "- 1문단: [목표 달성도] IPO 당시 제시했던 비전 대비 현재 핵심 펀더멘털 달성 여부\n- 2문단: [수익성 평가] 흑자 전환(Path to Profitability) 현황 및 잉여현금흐름(FCF)\n- 3문단: [자본 효율성] 투자(CAPEX/R&D) 성과 및 장기적 주주 가치 환원 전략"
            else:
                t1_label = "[작업 1: 신규 IPO 비즈니스 심층 분석]"
                t1_struct = "- 1문단: 구체적 수치를 동반한 비즈니스 모델 및 핵심 제품/서비스 설명\n- 2문단: 시장 점유율, 수익 구조, 그리고 주요 경쟁사와의 명확한 경쟁 우위/열위 비교\n- 3문단: 향후 신사업 확장 계획 및 최근 산업 트렌드"
                
            t2_label = "[작업 2: 최신 뉴스 수집 및 전문 번역]"
            json_format = f"""{{ "biz_summary": "여기에 3문단의 비즈니스 분석 내용을 넣으세요. (줄바꿈은 \\n 사용)", "news_list": [ {{ "title_en": "Original English Title", "translated_title": "한국 경제신문 헤드라인 스타일로 번역된 제목(마크다운 제외)", "link": "URL", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""

        # ---------------------------------------------------------
        # 🇺🇸 영어 프롬프트
        # ---------------------------------------------------------
        elif lang_code == 'en':
            sys_prompt = "You are a senior analyst at a top-tier brokerage research center."
            lang_instruction = "Your entire response MUST be strictly in Professional English."
            search_directive = f"🚨 [TOOL USE] FMP data is missing. IMMEDIATELY use Google Search for '{company_name} {ticker} business model' and its latest news." if can_search else "🚨 [STRICT RULE] Write ONLY using the text data provided below."
            
            if is_withdrawn:
                t1_label = "[Task 1: Withdrawn IPO Diagnosis]"
                t1_struct = "- Para 1: [Withdrawal Background] Market conditions, internal fundamentals, or regulatory issues.\n- Para 2: [Financial Impact] Impact of funding failure on short-term liquidity.\n- Para 3: [Survival Strategy] Alternative scenarios like M&A, direct listing, or private funding."
            elif is_delisted_or_otc:
                t1_label = "[Task 1: OTC Market Risk Analysis]"
                t1_struct = "- Para 1: [Delisting Background] Business model summary and reasons for delisting/downgrade.\n- Para 2: [Investment Risk] Liquidity risks due to low volume and information asymmetry.\n- Para 3: [Long-term Outlook] Going concern assessment and potential for re-listing."
            elif is_over_1y:
                t1_label = "[Task 1: Post-IPO Fundamental Check]"
                t1_struct = "- Para 1: [Goal Achievement] Whether core fundamentals matched the IPO vision.\n- Para 2: [Profitability] Path to profitability and Free Cash Flow (FCF) status.\n- Para 3: [Capital Efficiency] CAPEX/R&D outcomes and shareholder return strategies."
            else:
                t1_label = "[Task 1: Deep Business Model Analysis]"
                t1_struct = "- Para 1: Business model and core products/services with specific figures.\n- Para 2: Market share, revenue structure, and clear competitive advantage/disadvantage against peers.\n- Para 3: Future expansion plans and latest industry trends."
                
            t2_label = "[Task 2: Latest News Collection]"
            json_format = f"""{{ "biz_summary": "3 paragraphs of analysis (use \\n)", "news_list": [ {{ "title_en": "Original English Title", "translated_title": "Professional WSJ style headline (No quotes)", "link": "URL", "sentiment": "Positive/Negative/Neutral", "date": "YYYY-MM-DD" }} ] }}"""

        # ---------------------------------------------------------
        # 🇯🇵 일본어 프롬프트
        # ---------------------------------------------------------
        elif lang_code == 'ja':
            sys_prompt = "あなたは最高レベルの証券会社リサーチセンターのシニアアナリストです。"
            lang_instruction = "必ず自然で専門的な日本語のみで作成してください。"
            search_directive = f"🚨 [強制検索] データが不足しています。直ちにGoogle検索で「{company_name} {ticker} business model」および最新ニュースを検索してください。" if can_search else "🚨 [厳格な規則] 以下に提供されたテキストデータのみを使用してください。"
            
            if is_withdrawn:
                t1_label = "[タスク 1: 上場撤回(Withdrawn) 深層診断]"
                t1_struct = "- 第1段落: [撤回の背景] 市場環境の悪化、内部ファンダメンタルズ、または規制問題の分析\n- 第2段落: [財務的打撃] 資金調達失敗が企業の短期流動性に与える影響\n- 第3段落: [生存戦略] M&Aによる買収、直接上場、追加の私募資金調達などの代替シナリオ"
            elif is_delisted_or_otc:
                t1_label = "[タスク 1: OTC/店頭市場 取引リスク診断]"
                t1_struct = "- 第1段落: [上場廃止の背景] ビジネスモデルの要約と、正規市場に参入できない(または降格した)理由\n- 第2段落: [投資リスク] 取引量不足に伴う流動性リスクおよび情報非対称性の診断\n- 第3段落: [長期展望] 事業の持続可能性(Going Concern)と正規市場への再上場の可能性"
            elif is_over_1y:
                t1_label = "[タスク 1: 上場1年目のファンダメンタルズ点検]"
                t1_struct = "- 第1段落: [目標達成度] IPO当時に提示したビジョンに対する現在の核心ファンダメンタルズの達成状況\n- 第2段落: [収益性評価] 黒字転換(Path to Profitability)の現状とフリーキャッシュフロー(FCF)の状態\n- 第3段落: [資本効率] 投資(CAPEX/R&D)の成果と長期的な株主還元戦略"
            else:
                t1_label = "[タスク 1: 新規IPOビジネス深層分析]"
                t1_struct = "- 第1段落: 具体的な数値を伴うビジネスモデルと主要製品/サービスの説明\n- 第2段落: 市場シェア、収益構造、および主要な競合他社との明確な競争優位性/劣位性の比較\n- 第3段落: 今後の新規事業拡張計画および最新の業界トレンド"
                
            t2_label = "[タスク 2: 最新ニュースの収集と専門的な翻訳]"
            json_format = f"""{{ "biz_summary": "3つの段落の分析内容(\\n使用)", "news_list": [ {{ "title_en": "Original Title", "translated_title": "日経新聞のヘッドライン風(記号なし)", "link": "URL", "sentiment": "Positive/Negative/Neutral", "date": "YYYY-MM-DD" }} ] }}"""

        # ---------------------------------------------------------
        # 🇨🇳 중국어 프롬프트
        # ---------------------------------------------------------
        else: # zh
            sys_prompt = "您是顶尖券商研究中心的高级分析师。"
            lang_instruction = "必须只用自然流畅的专业简体中文编写。"
            search_directive = f"🚨 [强制搜索] FMP数据不足。请立即使用Google搜索查找“{company_name} {ticker} business model”以及最新新闻。" if can_search else "🚨 [严格规则] 只能使用下面提供的文本数据进行编写。"
            
            if is_withdrawn:
                t1_label = "[任务 1: 撤回上市(Withdrawn) 深度诊断]"
                t1_struct = "- 第一段: [撤回背景] 市场环境恶化、内部基本面或监管问题的分析。\n- 第二段: [财务打击] 融资失败对企业短期流动性的影响。\n- 第三段: [生存战略] M&A收购、直接上市或私募融资等替代方案。"
            elif is_delisted_or_otc:
                t1_label = "[任务 1: OTC/场外市场交易风险诊断]"
                t1_struct = "- 第一段: [退市背景] 商业模式摘要及未能进入（或降级出）正规市场的原因。\n- 第二段: [投资风险] 由于交易量不足导致的流动性风险及信息不对称诊断。\n- 第三段: [长期展望] 持续经营能力(Going Concern)评估及重新上市的可能性。"
            elif is_over_1y:
                t1_label = "[任务 1: 上市一周年基本面检查]"
                t1_struct = "- 第一段: [目标达成度] 评估当前核心基本面是否达到IPO时提出的愿景。\n- 第二段: [盈利能力] 扭亏为盈(Path to Profitability)现状及自由现金流(FCF)状况。\n- 第三段: [资本效率] 资本支出(CAPEX)/研发(R&D)成果及长期股东回报战略。"
            else:
                t1_label = "[任务 1: 新 IPO 业务深度分析]"
                t1_struct = "- 第一段: 包含具体数据的商业模式及核心产品/服务说明。\n- 第二段: 市场份额、盈利结构，以及与主要竞争对手的明确竞争优劣势比较。\n- 第三段: 未来的新业务扩张计划及行业最新趋势。"
                
            t2_label = "[任务 2: 收集最新新闻并专业翻译]"
            json_format = f"""{{ "biz_summary": "3个段落的分析内容(使用\\n)", "news_list": [ {{ "title_en": "Original Title", "translated_title": "财经新闻头条风格(不含特殊符号)", "link": "URL", "sentiment": "Positive/Negative/Neutral", "date": "YYYY-MM-DD" }} ] }}"""

        # ---------------------------------------------------------
        # [최종 프롬프트 조립]
        # ---------------------------------------------------------
        prompt = f"""
        {sys_prompt}
        Target: {company_name} ({ticker})
        Date: {current_date}

        [Part 1: Official Business Profile]
        {biz_desc if biz_desc else "Data unavailable."}

        [Part 2: Official FMP News]
        {fmp_news_context if fmp_news_context else "Data unavailable."}

        {t1_label}
        {search_directive}
        1. Language Rule: {lang_instruction}
        2. Format: Write EXACTLY 3 paragraphs based on the structure below. Each paragraph must be 4-5 sentences long.
        {t1_struct}
        3. Prohibition: 🚨 ABSOLUTELY DO NOT use introductions like "Here is the report", "Understood", "알겠습니다". Start the main analysis immediately. DO NOT use markdown bold (**) or bullet points.

        {t2_label}
        - Extract the Top 5 most important latest news from [Part 2] or Google Search.
        - If 'ko' language, the 'sentiment' MUST be "긍정", "부정", "일반". Otherwise, MUST be "Positive", "Negative", "Neutral".
        
        <JSON_START>
        {json_format}
        <JSON_END>
        """

        for attempt in range(3):
            try:
                response = current_model.generate_content(prompt)
                
                if not response or not hasattr(response, 'text') or not response.text:
                    print(f"⚠️ [{ticker}] AI 응답이 비어있습니다. (시도 {attempt+1}/3)")
                    time.sleep(1); continue
                
                full_text = response.text

                # 한글 오염 방어막
                if lang_code != 'ko':
                    check_text = full_text.replace("Positive", "").replace("Negative", "").replace("Neutral", "")
                    if re.search(r'[가-힣]', check_text):
                        time.sleep(1); continue 

                news_list = []
                json_str = ""
                biz_analysis = ""

                tag_match = re.search(r'<JSON_START>(.*?)<JSON_END>', full_text, re.DOTALL)
                if tag_match:
                    json_str = tag_match.group(1).strip()
                else:
                    bracket_match = re.search(r'(\[\s*\{.*?\}\s*\])', full_text, re.DOTALL)
                    if bracket_match:
                        json_str = bracket_match.group(1).strip()
                    else:
                        dict_match = re.search(r'(\{.*"news_list".*\})', full_text, re.DOTALL)
                        if dict_match: json_str = dict_match.group(1).strip()

                if json_str:
                    try:
                        parsed_data = json.loads(json_str)
                        valid_data = parsed_data if parsed_data is not None else []
                        temp_list = valid_data.get("news_list", []) if isinstance(valid_data, dict) else valid_data
                        
                        if isinstance(temp_list, list):
                            temp_list.sort(key=lambda x: x.get('date', '1970-01-01'), reverse=True)
                            news_list = temp_list[:5]
                    except:
                        news_list = []

                if json_str:
                    biz_analysis = full_text.replace(json_str, "").replace("<JSON_START>", "").replace("<JSON_END>", "").strip()
                else:
                    biz_analysis = full_text.split("[")[0].split("{")[0].replace("<JSON_START>", "").strip()

                # 서론 및 마크다운 찌꺼기 완벽 제거
                intro_pattern = r'^(알겠습니다|네,|작성하겠습니다|요청사항에|.*?보고서입니다|Understood|Certainly|Here is|I will|This is|承知いたしました|作成します|これは|好的|明白了|为您编写|这是).*?(\n|$)'
                biz_analysis = re.sub(intro_pattern, '', biz_analysis, flags=re.IGNORECASE | re.MULTILINE).strip()
                biz_analysis = re.sub(r'#.*', '', biz_analysis).strip()
                
                safe_biz_text = biz_analysis if biz_analysis else ""
                paragraphs = [p.strip() for p in safe_biz_text.split('\n') if p.strip() and len(p.strip()) > 20]
                
                indent_size = "14px" if lang_code == "ko" else "0px"
                html_output = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in paragraphs])

                # 뉴스 배지 색상 적용
                if isinstance(news_list, list):
                    for n in news_list:
                        if n is None: continue 
                        s_val = str(n.get('sentiment', 'Neutral')).strip().lower()
                        if "pos" in s_val or "긍정" in s_val: n['bg'], n['color'] = "#e6f4ea", "#1e8e3e"
                        elif "neg" in s_val or "부정" in s_val: n['bg'], n['color'] = "#fce8e6", "#d93025"
                        else: n['bg'], n['color'] = "#f1f3f4", "#5f6368"

                # DB 저장
                batch_upsert("analysis_cache", [{
                    "cache_key": cache_key,
                    "content": json.dumps({"html": html_output, "news": news_list}, ensure_ascii=False),
                    "updated_at": now.isoformat()
                }], on_conflict="cache_key")
                
                print(f"✅ [{ticker}] Tab 1 분석 성공 ({lang_code}) - {'Search' if is_fmp_poor else 'Strict'}")
                break 
                
            except Exception as e:
                print(f"❌ [{ticker}] Tab 1 분석 중 치명적 오류 ({lang_code}): {e}")
                time.sleep(1)
    # =========================================================
    # [A] 4개 국어 순회 생성
    # =========================================================
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Tab1_v5_{lang_code}"
        
        try:
            res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time_str).execute()
            if res.data: continue 
        except: pass

        if lang_code == 'ja':
            sys_prompt = "あなたは最高レベルの証券会社リサーチセンターのシニアアナリストです。すべての回答は必ず日本語で作成してください。"
            task2_label = "[タスク2: 最新ニュースの収集と専門的な翻訳]"
            target_lang = "日本語(Japanese)"
            lang_instruction = "必ず自然な日本語のみで作成してください。"
            json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "日経新聞のヘッドライン風に翻訳されたタイトル(記号なし)", "link": "...", "sentiment": "肯定/否定/一般", "date": "YYYY-MM-DD" }} ] }}"""
        elif lang_code == 'en':
            sys_prompt = "You are a senior analyst at a top-tier brokerage research center. You MUST write strictly in English."
            task2_label = "[Task 2: Latest News Collection and Professional Translation]"
            target_lang = "English"
            lang_instruction = "Your entire response MUST be in English only."
            json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "Professional WSJ style headline (No markdown/quotes)", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""
        elif lang_code == 'zh':  
            sys_prompt = "您是顶尖券商研究中心的高级分析师。必须只用简体中文编写。"
            task2_label = "[任务2: 收集最新新闻并专业翻译]"
            target_lang = "简体中文(Simplified Chinese)"
            lang_instruction = "必须只用自然流畅的简体中文编写。"
            json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "财经新闻头条风格的中文标题(不含特殊符号)", "link": "...", "sentiment": "肯定/否定/一般", "date": "YYYY-MM-DD" }} ] }}"""
        else:
            sys_prompt = "당신은 최고 수준의 증권사 리서치 센터의 시니어 애널리스트입니다. 반드시 한국어로 작성하세요."
            task2_label = "[작업 2: 최신 뉴스 수집 및 전문 번역]"
            target_lang = "한국어(Korean)"
            lang_instruction = "반드시 자연스러운 한국어만 사용하세요.\n모든 문장은 반드시 '~습니다', '~ㅂ니다' 형태의 존댓말로 작성해 주십시오."
            json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "한국 경제신문 헤드라인 스타일로 번역된 제목(마크다운 제외)", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""

        # 🚨 [핵심 변경] FMP 데이터 유무 및 다국어(ko, en, ja, zh)에 따른 프롬프트 완벽 분리
        if is_fmp_poor:
            if lang_code == 'en':
                task1_label = "[Task 1: S-1 Based Deep Business Overview]"
                task1_structure = """
                - 🚨 [Differentiation] DO NOT mention financials, IPO terms, or risks (covered in other tabs).
                - 🚨 [Must Include 1] Include specific numbers (MAU, revenue breakdown, market share, etc.) instead of vague descriptions.
                - 🚨 [Must Include 2] Clearly describe competitive advantages (or disadvantages) by comparing with key peers.
                - Para 1: Business model and core products/services with specific figures.
                - Para 2: Market share, revenue structure, and clear competitive advantage/disadvantage against peers.
                - Para 3: Future expansion plans and latest market trends.
                """
                search_directive = f"""
                - 🚨 [Force Search] FMP data is insufficient. IMMEDIATELY use Google Search for "{company_name} {ticker} business model" and "{company_name} market share competitors".
                - Summarize in great detail based on actual facts and figures from the search.
                """
            elif lang_code == 'ja':
                task1_label = "[タスク 1: S-1ベースのビジネス深層要約]"
                task1_structure = """
                - 🚨 [差別化ルール] 財務状況、上場条件、リスクは他のタブで扱うため、絶対に言及しないでください。
                - 🚨 [必須項目 1] 曖昧な説明を避け、具体的な数値（MAU、売上比率、シェアなど）を必ず含めてください。
                - 🚨 [必須項目 2] 主要な競合他社（Peers）との明確な比較を通じて、この企業ならではの競争優位性（または劣位性）を必ず記述してください。
                - 第1段落: 具体的な数値を伴うビジネスモデルと主要製品/サービスの説明。
                - 第2段落: 市場シェア、収益構造、および主要な競合他社との明確な競争優位性/劣位性の比較。
                - 第3段落: 今後の新規事業拡張計画および最新の市場トレンド。
                """
                search_directive = f"""
                - 🚨 [強制検索] FMPデータが不足しています。直ちにGoogle検索で「{company_name} {ticker} business model」、「{company_name} market share competitors」を検索してください。
                - 検索された「実際の事実と数値」に基づいて、非常に詳細に要約してください。
                """
            elif lang_code == 'zh':
                task1_label = "[任务 1: 基于 S-1 的业务深度摘要]"
                task1_structure = """
                - 🚨 [差异化规则] 绝对不要提及财务状况、上市条件或风险（这些在其他标签页中处理）。
                - 🚨 [必须包含 1] 必须包含具体数据（如MAU、营收占比、市场份额等），拒绝模糊表达。
                - 🚨 [必须包含 2] 必须通过与主要竞争对手（Peers）的明确比较，阐述该企业独有的竞争优势（或劣势）。
                - 第一段: 包含具体数据的商业模式及核心产品/服务说明。
                - 第二段: 市场份额、盈利结构，以及与主要竞争对手的明确竞争优劣势比较。
                - 第三段: 未来的新业务扩张计划及最新市场趋势。
                """
                search_directive = f"""
                - 🚨 [强制搜索] FMP数据不足。请立即使用Google搜索查找“{company_name} {ticker} business model”和“{company_name} market share competitors”。
                - 基于搜索到的“实际事实和数据”进行非常详细的总结。
                """
            else: # ko
                task1_label = "[작업 1: S-1 기반 비즈니스 심층 요약]"
                task1_structure = """
                - 🚨 [차별화 규칙] 재무 상태나 상장 조건, 리스크는 다른 탭에서 다루므로 절대 언급하지 마세요.
                - 🚨 [필수 포함 1] 막연한 설명 대신 가급적 구체적인 수치(MAU, 매출 비중, 점유율 등)를 반드시 1개 이상 포함하세요.
                - 🚨 [필수 포함 2] 주요 경쟁사(Peers)와의 명확한 비교를 통해 이 기업만의 경쟁 우위(또는 열위)를 반드시 서술하세요.
                - 1문단: 구체적 수치를 동반한 비즈니스 모델 및 핵심 제품/서비스 설명
                - 2문단: 시장 점유율, 수익 구조, 그리고 주요 경쟁사와의 명확한 경쟁 우위/열위 비교
                - 3문단: 향후 신사업 확장 계획 및 최신 시장 트렌드
                """
                search_directive = f"""
                - 🚨 [강제 검색] FMP 데이터가 부족합니다. 즉시 구글 검색을 통해 "{company_name} {ticker} business model", "{company_name} market share competitors"를 찾아주세요.
                - 검색된 '실제 팩트와 수치'를 바탕으로 매우 상세히 요약하세요.
                """
        else:
            if lang_code == 'en':
                task1_label = "[Task 1: Deep Business Model Analysis]"
                task1_structure = """
                - 🚨 [Must Include 1] Include specific numbers (revenue breakdown, user count, etc.) instead of vague descriptions.
                - 🚨 [Must Include 2] Clearly describe competitive advantages (or disadvantages) by comparing with key peers.
                - Para 1: Business model and core products/services with specific figures.
                - Para 2: Market share, revenue structure, and clear competitive advantage/disadvantage against peers.
                - Para 3: Future expansion plans and industry trends.
                """
                search_directive = """
                - 🚨 [Strict Rule] Write ONLY using the [Part 1] text data provided below. Google search and hallucination are strictly prohibited.
                """
            elif lang_code == 'ja':
                task1_label = "[タスク 1: 新規IPOビジネス深層分析]"
                task1_structure = """
                - 🚨 [必須項目 1] 曖昧な説明を避け、具体的な数値（売上比率、ユーザー数など）を必ず含めてください。
                - 🚨 [必須項目 2] 主要な競合他社（Peers）との明確な比較を通じて、この企業ならではの競争優位性（または劣位性）を必ず記述してください。
                - 第1段落: 具体的な数値を伴うビジネスモデルと主要製品/サービスの説明。
                - 第2段落: 市場シェア、収益構造、および主要な競合他社との明確な競争優位性/劣位性の比較。
                - 第3段落: 今後の新規事業拡張計画および業界トレンド。
                """
                search_directive = """
                - 🚨 [厳格な規則] 以下に提供された [Part 1] のテキストデータのみを使用して作成してください。Google検索や推測は絶対に禁止です。
                """
            elif lang_code == 'zh':
                task1_label = "[任务 1: 新 IPO 业务深度分析]"
                task1_structure = """
                - 🚨 [必须包含 1] 必须包含具体数据（如营收占比、用户数等），拒绝模糊表达。
                - 🚨 [必须包含 2] 必须通过与主要竞争对手（Peers）的明确比较，阐述该企业独有的竞争优势（或劣势）。
                - 第一段: 包含具体数据的商业模式及核心产品/服务说明。
                - 第二段: 市场份额、盈利结构，以及与主要竞争对手的明确竞争优劣势比较。
                - 第三段: 未来的新业务扩张计划及行业趋势。
                """
                search_directive = """
                - 🚨 [严格规则] 只能使用下面提供的 [Part 1] 文本数据进行编写。严禁使用Google搜索和主观臆测。
                """
            else: # ko
                task1_label = "[작업 1: 신규 IPO 비즈니스 심층 분석]"
                task1_structure = """
                - 🚨 [필수 포함 1] 막연한 설명 대신 가급적 구체적인 수치(매출 비중, 가입자 수 등)를 반드시 포함하세요.
                - 🚨 [필수 포함 2] 주요 경쟁사(Peers)와의 명확한 비교를 통해 이 기업만의 경쟁 우위(또는 열위)를 반드시 서술하세요. 
                - 1문단: 구체적 수치를 동반한 비즈니스 모델 및 핵심 제품/서비스 설명
                - 2문단: 시장 점유율, 수익 구조, 그리고 주요 경쟁사와의 명확한 경쟁 우위/열위 비교
                - 3문단: 향후 신사업 확장 계획 및 산업 트렌드
                """
                search_directive = """
                - 🚨 [환각 완전 금지] 오직 아래 제공된 [Part 1] 텍스트 데이터만을 사용하여 작성하십시오. 구글 검색 및 유추 절대 금지.
                """

        prompt = f"""
        {sys_prompt}
        분석 대상: {company_name} ({ticker})
        오늘 날짜: {current_date}

        [Part 1: Official Business Profile (Source: FMP)]
        {biz_desc if biz_desc else "Data unavailable."}

        [Part 2: Official FMP News]
        {fmp_news_context if fmp_news_context else "Data unavailable."}

        {task1_label}
        {search_directive}
        1. 언어: {lang_instruction}
        2. 포맷: 반드시 3개의 문단으로 나누어 작성하세요. (각 문단은 4~5문장 길이)
            {task1_structure}
        3. 금지: 🚨 첫문장에 "알겠습니다", "작성하겠습니다" "보고서 입니다" 같은 AI 특유의 대답이나 인사말은 절대 금지합니다! 글의 첫 글자부터 곧바로 기업 분석 본문을 시작하세요. "## Company Analysis" 같은 제목이나 숫자 넘버링도 금지합니다.
        
         {task2_label}
        - [Part 2]의 뉴스 데이터를 바탕으로 반드시 **최신순 상위 5개(Top 5)**를 추출하세요.
        - 만약 데이터가 부족하더라도 있는 만큼 최대한(최대 5개) 작성하세요. 데이터가 전혀 없으면 빈 리스트 [] 를 반환하세요.
        - sentiment 값은 시스템을 위해 반드시 "긍정", "부정", "일반" 중 하나로 한국어로 출력하세요.

        {task1_label}
        {search_directive}
        1. Language: {lang_instruction}
        2. Format: Must be written in exactly 3 paragraphs. (Each paragraph should be 4-5 sentences long)
            {task1_structure}
        3. Prohibition: 🚨 ABSOLUTELY PROHIBITED: Do not start the first sentence with greetings or meta-talk like "Understood," "I will write," or "This is the analysis report." Start the analysis IMMEDIATELY with the core content. Do not use headers like "## Company Analysis" or numbering.
        
        {task2_label}
        - Based on the news data in [Part 2], extract exactly the **Top 5** latest news items.
        - If data is insufficient, provide as many as possible (up to 5). Return an empty list [] if no news exists.
        - The 'sentiment' value MUST be output in english as one of: "Positive", "Negative", "Neutral" for system compatibility. 


        {task1_label}
        {search_directive}
        1. 语言: {lang_instruction}
        2. 格式: 必须严格分为 3 个自然段。（每个段落包含 4-5 句话）
            {task1_structure}
        3. 禁止: 🚨 【绝对禁止】严禁在第一句出现“好的”、“明白了”、“为您编写”或“这是分析报告”等AI客套话或开场白！请从第一个字开始直接进入公司分析正文。禁止使用“## Company Analysis”等标题或数字编号。
        
        {task2_label}
        - 根据 [Part 2] 中的新闻数据，务必提取**最新前 5 条 (Top 5)**。
        - 如果数据不足，请尽力提供（最多 5 条）。如果完全没有数据，请返回空列表 []。
        - 为了系统兼容性，'sentiment' 的值必须以英文输出为以下单词之一："Positive"、"Negative" 或 "Neutral"。

        {task1_label}
        {search_directive}
        1. 言語: {lang_instruction}
        2. フォーマット: 必ず 3 つの段落に分けて作成してください。（各段落は 4〜5 文の長さ）
            {task1_structure}
        3. 禁止事項: 🚨 【厳禁】一行目に「承知いたしました」、「作成します」、「報告書です」などの挨拶や導入文は絶対に書かないでください。最初の文字からすぐに企業分析の本論を開始してください。「## Company Analysis」のような見出しや数字のナンバリングも禁止です。
        
        {task2_label}
        - [Part 2] のニュースデータに基づき、必ず**最新順の上位 5 件 (Top 5)**を抽出してください。
        - データが不足している場合でも、ある分だけ最大 5 件まで作成してください。データが全くない場合は空のリスト [] を返してください。
        - システム互換性の目的で、'sentiment' の値は必ず英語の "Positive"、"Negative"、"Neutral" のいずれかを出力してください。
        
        <JSON_START>
        {json_format}
        <JSON_END>
        """

        for attempt in range(3):
            try:
                response = current_model.generate_content(prompt)
                
                # 🚨 [방어 1] AI 응답 자체가 없거나 차단된 경우 처리
                if not response or not hasattr(response, 'text') or not response.text:
                    print(f"⚠️ [{ticker}] AI 응답이 비어있거나 차단되었습니다. (시도 {attempt+1}/3)")
                    time.sleep(1); continue
                
                full_text = response.text

                # 1. 변수 초기화 (에러 원천 차단)
                news_list = []
                json_str = ""
                biz_analysis = ""

                # 2. JSON 추출 (Greedy 매칭으로 5개 전체 확보)
                tag_match = re.search(r'<JSON_START>(.*?)<JSON_END>', full_text, re.DOTALL)
                if tag_match:
                    json_str = tag_match.group(1).strip()
                else:
                    # <JSON_START> 태그가 없으면 가장 큰 [ ] 덩어리를 찾음
                    bracket_match = re.search(r'(\[.*\])', full_text, re.DOTALL)
                    if bracket_match:
                        json_str = bracket_match.group(1).strip()

                # 3. 뉴스 리스트 파싱 및 5개 선별
                if json_str:
                    try:
                        parsed_data = json.loads(json_str)
                        # parsed_data가 None일 경우를 대비해 []로 대체
                        valid_data = parsed_data if parsed_data is not None else []
                        
                        # 리스트 형태면 바로 사용, dict 형태면 'news' 키 확인
                        temp_list = valid_data.get("news", []) if isinstance(valid_data, dict) else valid_data
                        
                        if isinstance(temp_list, list):
                            # 최신순 정렬 후 5개만 컷 (15개 소스 중 정예 멤버)
                            temp_list.sort(key=lambda x: x.get('date', '1970-01-01'), reverse=True)
                            news_list = temp_list[:5]
                    except:
                        news_list = [] # JSON 깨지면 빈 리스트로 초기화

                # 4. 분석 본문 정제 (JSON 찌꺼기 제거)
                if json_str:
                    biz_analysis = full_text.replace(json_str, "").replace("<JSON_START>", "").replace("<JSON_END>", "").strip()
                else:
                    # JSON을 못 찾았을 경우 대비한 안전 분할
                    biz_analysis = full_text.split("[")[0].split("{")[0].replace("<JSON_START>", "").strip()

                # 5. 서론 찌꺼기 및 마크다운 제거
                intro_pattern = r'^(알겠습니다|네,|작성하겠습니다|요청사항에|.*?보고서입니다|Understood|Certainly|Here is|I will|This is|承知いたしました|作成します|これは|好的|明白了|为您编写|这是).*?(\n|$)'
                biz_analysis = re.sub(intro_pattern, '', biz_analysis, flags=re.IGNORECASE | re.MULTILINE).strip()
                biz_analysis = re.sub(r'#.*', '', biz_analysis).strip()
                
                # 🔍 [DEBUG] 렌더링 직전 변수 상태 현장 검증
                print(f"🔍 [DEBUG - {ticker}] biz_analysis 타입: {type(biz_analysis)}")
                print(f"🔍 [DEBUG - {ticker}] news_list 타입: {type(news_list)}")
                if news_list is not None:
                    print(f"🔍 [DEBUG - {ticker}] news_list 실제 내용: {news_list}")

                # 6. HTML 렌더링 (news_list와 별도로 본문 보장)
                safe_biz_text = biz_analysis if biz_analysis else ""
                # 만약 여기서 biz_analysis가 None이면 .split에서 터질 수 있습니다.
                paragraphs = [p.strip() for p in safe_biz_text.split('\n') if p.strip() and len(p.strip()) > 20]
                
                indent_size = "14px" if lang_code == "ko" else "0px"
                html_output = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in paragraphs])

                # 7. Sentiment 배지 색상 매핑
                if isinstance(news_list, list):
                    # 🚨 여기서 news_list가 None이면 for문 진입 시 에러가 날 수 있습니다.
                    for n in news_list:
                        if n is None: continue # 리스트 안에 None 요소가 섞인 경우 방어
                        s_val = str(n.get('sentiment', 'Neutral')).strip().lower()
                        if "positive" in s_val: n['bg'], n['color'] = "#e6f4ea", "#1e8e3e"
                        elif "negative" in s_val: n['bg'], n['color'] = "#fce8e6", "#d93025"
                        else: n['bg'], n['color'] = "#f1f3f4", "#5f6368"

                # 8. 최종 저장 (뉴스 5개를 카드 하나에 담는 구조 유지)
                batch_upsert("analysis_cache", [{
                    "cache_key": cache_key,
                    "content": json.dumps({"html": html_output, "news": news_list}, ensure_ascii=False),
                    "updated_at": now.isoformat()
                }], on_conflict="cache_key")
                
                # 🚨 [에러 지점 수정] news_list가 확실히 리스트인지 체크 후 로그 출력
                final_news_count = len(news_list) if isinstance(news_list, list) else 0
                print(f"✅ [{ticker}] Tab 1 분석 성공 (뉴스 {final_news_count}개 선별)")
                
                # 뉴스가 선별되었거나 데이터가 없는 종목이면 루프 종료
                if final_news_count > 0 or is_fmp_poor:
                    break 
                
            except Exception as e:
                # 🚨 여기서 NoneType 에러가 나더라도 '건너뜀' 로그를 찍고 다음 종목으로 넘어감
                print(f"❌ [{ticker}] 분석 중 치명적 오류: {e}")
                time.sleep(1)
                
    # =========================================================
    # 🚀 [B] 프리미엄 전용 데이터 수집 (기업 공식 보도자료)
    # =========================================================
    try:
        pr_url = f"https://financialmodelingprep.com/stable/press-releases?symbol={ticker}&limit=5&apikey={FMP_API_KEY}"
        pr_raw = get_fmp_data_with_cache(ticker, "RAW_PR", pr_url, valid_hours=12)
        
        # 🚨 [환각 완벽 차단] FMP가 보낸 데이터가 에러 딕셔너리({})가 아닌 정상 리스트([])일 때만 통과!
        is_pr_valid = isinstance(pr_raw, list) and len(pr_raw) > 0

        for lang_code in SUPPORTED_LANGS.keys():
            if is_pr_valid: # 💡 방어막 통과 시에만 AI 호출
                pr_summary_key = f"{ticker}_PressReleaseSummary_v1_{lang_code}"
                try:
                    res_p = supabase.table("analysis_cache").select("updated_at").eq("cache_key", pr_summary_key).gt("updated_at", limit_time_str).execute()
                    if not res_p.data:
                        prompt_p = get_tab1_premium_prompt(lang_code, "Official Press Release", pr_raw)
                        for attempt in range(3):
                            try:
                                resp_p = model_strict.generate_content(prompt_p)
                                if resp_p and resp_p.text:
                                    p_paragraphs = [p.strip() for p in resp_p.text.split('\n') if len(p.strip()) > 20]
                                    indent_size = "14px" if lang_code == "ko" else "0px"
                                    html_p = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in p_paragraphs])
                                    
                                    batch_upsert("analysis_cache", [{"cache_key": pr_summary_key, "content": html_p, "updated_at": now.isoformat()}], "cache_key")
                                    print(f"✅ [{ticker}] 기업 공식 보도자료 캐싱 완료 ({lang_code})")
                                    break
                            except: time.sleep(1)
                except: pass

    except Exception as e:
        print(f"Premium FMP Collection Error for {ticker}: {e}")


def run_tab4_analysis(ticker, company_name, ipo_status="Active", ipo_date_str=None, analyst_data=None):
    # 🚨 [수정] model -> model_strict 로 방어막 변경
    if 'model_strict' not in globals() or not model_strict: return False
    
    status_lower = str(ipo_status).lower()
    is_stable = bool(re.search(r'\b(withdrawn|rw|철회|취소|delisted|폐지)\b', status_lower))
    
    if not is_stable and ipo_date_str:
        try:
            ipo_dt = pd.to_datetime(ipo_date_str).date()
            if (datetime.now().date() - ipo_dt).days > 365: is_stable = True
        except: pass

    valid_hours = 168 if is_stable else 24
    limit_time_str = (datetime.now() - timedelta(hours=valid_hours)).isoformat()

    # =========================================================
    # [A] 기존 무료 제공 데이터 (Google Search 기관 리포트)
    # =========================================================
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Tab4_v4_Premium_{lang_code}" 
        
        try:
            res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time_str).execute()
            if res.data: continue 
        except: pass

        # 💡 [FMP 데이터 주입]
        fmp_context = ""
        if analyst_data and analyst_data.get('target') != 'N/A':
            fmp_context = f"""
[Wall Street Consensus (FMP Premium Data)]
- Consensus Rating: {analyst_data.get('consensus')}
- Target Price (Average): ${analyst_data.get('target')} (High: ${analyst_data.get('high')}, Low: ${analyst_data.get('low')})
"""

        if lang_code == 'en':
            prompt = f"""You are an IPO analyst from Wall Street.
Use the Google search tool to find and analyze the latest institutional reports for {company_name} ({ticker}).
{fmp_context}

[Instructions]
1. **Language Rule**: MUST write entirely in English. DO NOT mix any Korean words.
2. **Analysis Depth**: Provide a professional analysis including specific figures and evidence (especially Target Price if available).
3. **Pros & Cons**: Clearly derive and reflect exactly 2 positive factors (Pros) and 2 negative factors (Cons).
4. **Score**: Evaluate the overall positive/expectation level of the Wall Street report as an integer from 1 (Worst) to 5 (Moonshot/Best).
5. **Output Format**: Strictly output ONLY the JSON format below. 100% compliance with the 'Value' instructions.
6. **Link Location**: NEVER put URLs inside the main body text. You MUST only put them inside the "links" array.

<JSON_START>
{{
    "target_price": "Insert FMP Average Target Price (e.g., $150.00) or 'N/A'",
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell",
    "score": "Integer from 1 to 5",
    "summary": "Professional 3-line summary in English. Mention Target Price if provided.",
    "pro_con": "**Pros**:\\n- Detail 1\\n- Detail 2\\n\\n**Cons**:\\n- Detail 1\\n- Detail 2",
    "links": [ {{"title": "Report Title", "link": "URL"}} ]
}}
<JSON_END>"""

        elif lang_code == 'ja':
            prompt = f"""あなたはウォール街出身のIPO専門アナリストです。
Google検索を使用して、{company_name} ({ticker})に関する最新の機関投資家レポートを見つけ分析してください。
{fmp_context}

[作成指針]
1. **言語規則**: 全て自然な日本語のみで記述してください。韓国語を絶対に混ぜないでください。
2. **分析の深さ**: 具体的な数値や根拠（特に目標株価）を含む専門的な分析を提供してください。
3. **Pros & Cons**: 肯定的な要素(長所)を2つ、否定的な要素(短所)を2つ明確に導き出して反映させてください。
4. **スコア**: ウォール街のレポートの総合的な期待レベルを1(最悪)から5(最高)までの整数で評価してください。
5. **出力形式**: 以下の<JSON_START>フォーマットの指示を100%遵守して出力してください。
6. **リンクの位置**: 本文の中には絶対にURLを入れず、必ず「links」配列の中にのみ記入してください。

<JSON_START>
{{
    "target_price": "FMPの平均目標株価を挿入 (例: $150.00) または 'N/A'",
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell (英語維持)",
    "score": "1から5までの整数",
    "summary": "日本語での専門的な3行要約 (目標株価の言及を含む)",
    "pro_con": "**長所(Pros)**:\\n- 詳細内容1\\n- 詳細内容2\\n\\n**短所(Cons)**:\\n- リスク要因1\\n- リスク要因2",
    "links": [ {{"title": "レポートタイトル", "link": "URL"}} ]
}}
<JSON_END>"""

        elif lang_code == 'zh':
            prompt = f"""您是华尔街的专业IPO分析师。
请使用Google搜索工具查找并分析关于 {company_name} ({ticker}) 的最新机构报告。
{fmp_context}

[编写指南]
1. **语言规则**: 必须只用简体中文编写。严禁混用韩语。
2. **分析深度**: 提供包含具体数据和依据的专业分析（特别是目标价）。
3. **Pros & Cons**: 明确提取2个积极因素(优点)和2个消极因素(缺点)。
4. **评分**: 将华尔街报告的综合预期水平评为1(最差)到5(极佳)的整数。
5. **输出格式**: 100%严格遵守以下<JSON_START>格式中“值”的指示进行填写。
6. **链接位置**: 绝对不要在正文中放入URL，必须只填写在“links”数组中。

<JSON_START>
{{
    "target_price": "插入FMP平均目标价 (如: $150.00) 或 'N/A'",
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell (保留英文)",
    "score": "1到5的整数",
    "summary": "包含目标价背景的专业中文三行摘要",
    "pro_con": "**优点(Pros)**:\\n- 详细分析1\\n- 详细分析2\\n\\n**缺点(Cons)**:\\n- 风险因素1\\n- 风险因素2",
    "links": [ {{"title": "报告标题", "link": "URL"}} ]
}}
<JSON_END>"""

        else: # ko
            prompt = f"""당신은 월가 출신의 IPO 전문 분석가입니다. 
구글 검색 도구를 사용하여 {company_name} ({ticker})에 대한 최신 기관 리포트(Seeking Alpha, Renaissance Capital 등)를 찾아 심층 분석하세요.
{fmp_context}

[작성 지침]
1. **언어 규칙**: 반드시 자연스러운 한국어로 번역하여 작성하세요.
2. **분석 깊이**: 구체적인 수치나 근거를 포함하여 전문적으로 분석하세요.
3. **Pros & Cons**: 긍정적 요소(Pros) 2가지와 부정적 요소(Cons) 2가지를 명확히 도출하여 반영하세요.
4. **Score**: 월가 리포트의 종합적인 긍정/기대 수준을 1점(최악)부터 5점(대박) 사이의 정수로 평가하세요.
5. **출력 형식**: 아래 제공된 <JSON_START> 양식의 '값(Value)' 부분에 적힌 언어와 지시사항을 100% 준수하여 채워 넣으세요.
6. **링크 위치**: 본문 안에는 절대 URL을 넣지 말고, 반드시 "links" 배열 안에만 기입하세요.

<JSON_START>
{{
    "target_price": "FMP 평균 목표 주가 삽입 (예: $150.00) 또는 'N/A'",
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell 중 택 1 (영어 유지)",
    "score": "1~5 사이의 정수 (예: 4)",
    "summary": "한국어 전문 3줄 요약 (목표 주가 맥락을 포함할 것)",
    "pro_con": "**장점(Pros)**:\\n- 구체적 분석 내용 1\\n- 구체적 분석 내용 2\\n\\n**단점(Cons)**:\\n- 구체적 리스크 요인 1\\n- 구체적 리스크 요인 2",
    "links": [ {{"title": "리포트 제목", "link": "URL"}} ]
}}
<JSON_END>"""
        
        for attempt in range(3):
            try:
                # 🚨 [핵심 수정] model_search가 None일 경우 안전한 model_strict로 자동 전환
                target_model = model_search if model_search is not None else model_strict
                response = target_model.generate_content(prompt)
                full_text = response.text
                
                if lang_code != 'ko':
                    if re.search(r'[가-힣]', full_text):
                        if attempt < 2:
                            time.sleep(1); continue 
                        else: break 
                
                json_str = ""
                json_match = re.search(r'<JSON_START>(.*?)<JSON_END>', full_text, re.DOTALL)
                if json_match: json_str = json_match.group(1).strip()
                else:
                    json_match = re.search(r'\{.*\}', full_text, re.DOTALL)
                    json_str = json_match.group(0).strip() if json_match else ""

                if json_str:
                    clean_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)
                    try:
                        parsed_json = json.loads(clean_str, strict=False)
                        batch_upsert("analysis_cache", [{
                            "cache_key": cache_key, 
                            "content": json.dumps(parsed_json, ensure_ascii=False), 
                            "updated_at": datetime.now().isoformat()
                        }], on_conflict="cache_key")
                    except: pass
                        
                break 
            except Exception as e:
                time.sleep(1)

    # =========================================================
    # 🚀 [B] 프리미엄 전용 데이터 수집 (Upgrades/Downgrades & Peers)
    # =========================================================
    try:
        # 💡 [Stable 변경 완료] API v4 및 언더바(_)를 stable과 하이픈(-)으로 교체
        ud_url = f"https://financialmodelingprep.com/stable/upgrades-downgrades?symbol={ticker}&apikey={FMP_API_KEY}"
        ud_raw = get_fmp_data_with_cache(ticker, "RAW_UPGRADES", ud_url, valid_hours=24)
        
        peers_url = f"https://financialmodelingprep.com/stable/stock-peers?symbol={ticker}&apikey={FMP_API_KEY}"
        peers_raw = get_fmp_data_with_cache(ticker, "RAW_PEERS", peers_url, valid_hours=24)

        # 🚨 [환각 방어막] 진짜 데이터인지 엄격 검사
        is_ud_valid = isinstance(ud_raw, list) and len(ud_raw) > 0
        is_peers_valid = isinstance(peers_raw, list) and len(peers_raw) > 0

        for lang_code in SUPPORTED_LANGS.keys():
            if is_ud_valid:
                ud_summary_key = f"{ticker}_PremiumUpgrades_v1_{lang_code}"
                try:
                    res_ud = supabase.table("analysis_cache").select("updated_at").eq("cache_key", ud_summary_key).gt("updated_at", limit_time_str).execute()
                    if not res_ud.data:
                        prompt_ud = get_tab4_premium_prompt(lang_code, "Upgrades and Downgrades History", ticker, ud_raw)
                        for attempt in range(3):
                            try:
                                resp_ud = model_strict.generate_content(prompt_ud)
                                if resp_ud and resp_ud.text:
                                    ud_paragraphs = [p.strip() for p in resp_ud.text.split('\n') if len(p.strip()) > 20]
                                    indent_size = "14px" if lang_code == "ko" else "0px"
                                    html_ud = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in ud_paragraphs])
                                    batch_upsert("analysis_cache", [{"cache_key": ud_summary_key, "content": html_ud, "updated_at": datetime.now().isoformat()}], "cache_key")
                                    print(f"✅ [{ticker}] 투자의견 히스토리 캐싱 완료 ({lang_code})")
                                    break
                            except Exception as e: time.sleep(1)
                except: pass

            if is_peers_valid:
                peers_summary_key = f"{ticker}_PremiumPeers_v1_{lang_code}"
                try:
                    res_p = supabase.table("analysis_cache").select("updated_at").eq("cache_key", peers_summary_key).gt("updated_at", limit_time_str).execute()
                    if not res_p.data:
                        prompt_p = get_tab4_premium_prompt(lang_code, "Stock Peers & Competitors", ticker, peers_raw)
                        for attempt in range(3):
                            try:
                                resp_p = model_strict.generate_content(prompt_p)
                                if resp_p and resp_p.text:
                                    p_paragraphs = [p.strip() for p in resp_p.text.split('\n') if len(p.strip()) > 20]
                                    indent_size = "14px" if lang_code == "ko" else "0px"
                                    html_p = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in p_paragraphs])
                                    batch_upsert("analysis_cache", [{"cache_key": peers_summary_key, "content": html_p, "updated_at": datetime.now().isoformat()}], "cache_key")
                                    print(f"✅ [{ticker}] 경쟁사 비교 캐싱 완료 ({lang_code})")
                                    break
                            except Exception as e: time.sleep(1)
                except: pass
    except Exception as e:
        print(f"Premium Tab 4 FMP Error for {ticker}: {e}")
        
# ==========================================
# [신규 추가] Tab 4 프리미엄 요약 전용 프롬프트 (다국어 완벽 분리)
# ==========================================
def get_tab4_premium_prompt(lang, type_name, ticker, raw_data):
    if lang == 'en':
        return f"""You are a Senior Wall Street Analyst. Analyze the following [Raw Data] ({type_name}) for {ticker}.
        
[Strict Rules]
1. Write ENTIRELY in English. Do not mix other languages.
2. Write exactly 3 paragraphs.
3. Each paragraph must be 4-5 sentences long, containing deep and professional insights.
4. DO NOT use markdown bold (**) for numbers.
5. Omit greetings and start the main content immediately. Maintain a cold, objective, and analytical tone.

[Raw Data]:
{raw_data}"""

    elif lang == 'ja':
        return f"""あなたはウォール街のシニアアナリストです。提供された [Raw Data] ({type_name}) に基づいて、{ticker} に関する分析を日本語で要約してください。
        
[厳格な作成ルール]
1. 全て自然な日本語のみで記述してください。
2. 必ず3つの段落に分けて作成してください。
3. 各段落は4〜5文で構成し、重厚で専門的な洞察を含めてください。
4. 数値に強調記号（**）は絶対に使用しないでください。
5. 挨拶は省略し、すぐに本題に入ってください。冷静で客観的な分析トーンを維持してください。

[Raw Data]:
{raw_data}"""

    elif lang == 'zh':
        return f"""您是华尔街的高级分析师。请根据提供的 [Raw Data] ({type_name})，用简体中文对 {ticker} 进行深度分析。
        
[严格编写规则]
1. 必须完全使用简体中文编写，严禁混用其他语言。
2. 必须严格分为3个段落。
3. 每个段落应包含4-5句话，并提供深刻、专业的见解。
4. 绝对不要使用星号（**）对数字进行加粗。
5. 省略问候语，直接进入正文。保持冷静、客观和分析的基调。

[Raw Data]:
{raw_data}"""

    else: # ko
        return f"""당신은 월가 출신의 수석 애널리스트입니다. 아래 제공된 [Raw Data]({type_name})를 바탕으로 {ticker}의 상황을 한국어로 심층 분석하세요.
        
[작성 규칙 - 엄격 준수]
1. 반드시 순수한 한국어로만 작성하세요.
2. 반드시 3개의 문단으로 나누어 작성하세요.
3. 각 문단은 4~5줄(문장) 길이로 묵직하고 전문적인 통찰을 담으세요.
4. 숫자에 별표(**) 강조를 절대 사용하지 마세요.
5. 인사말을 생략하고 첫 글자부터 본론만 작성하세요. 냉철하고 분석적인 어조를 유지하세요.

[Raw Data]:
{raw_data}"""


# ==========================================
# [수정] FMP 프리미엄 11개 지표 통합 수집 헬퍼 (안전망 강화 버전)
# ==========================================
def fetch_premium_financials(symbol, api_key):
    """11가지 핵심 지표를 모두 수집하며, 권한 에러 발생 시 로그를 띄웁니다."""
    fin_data = {
        'growth': 'N/A', 'net_margin': 'N/A', 'op_margin': 'N/A', 'pe': 'N/A',
        'roe': 'N/A', 'debt_equity': 'N/A', 'pb': 'N/A', 'accruals': 'Unknown',
        'dcf_price': 'N/A', 'current_price': 'N/A', 'rating': 'N/A',
        'recommendation': 'N/A', 'health_score': 'N/A'
    }
    
    def safe_fmp_get(url, name):
        res = requests.get(url, timeout=5).json()
        if isinstance(res, dict) and "Error Message" in res:
            print(f"🚫 [재무 데이터 차단됨: {name}] -> {res['Error Message']}")
            return []
        return res

    try:
        # 1. 손익계산서
        inc_url = f"https://financialmodelingprep.com/stable/income-statement?symbol={symbol}&limit=2&apikey={api_key}"
        inc_res = safe_fmp_get(inc_url, "Income Statement")
        if isinstance(inc_res, list) and len(inc_res) > 0:
            rev = float(inc_res[0].get('revenue', 0))
            net_inc = float(inc_res[0].get('netIncome', 0))
            op_inc = float(inc_res[0].get('operatingIncome', 0))
            prev_rev = float(inc_res[1].get('revenue', rev)) if len(inc_res) > 1 else rev
            
            fin_data['growth'] = f"{((rev - prev_rev) / prev_rev) * 100:+.1f}%" if prev_rev else "N/A"
            fin_data['net_margin'] = f"{(net_inc / rev) * 100:.1f}%" if rev else "N/A"
            fin_data['op_margin'] = f"{(op_inc / rev) * 100:.1f}%" if rev else "N/A"
        
        # 2. 주요 지표
        m_url = f"https://financialmodelingprep.com/stable/key-metrics-ttm?symbol={symbol}&apikey={api_key}"
        m_res = safe_fmp_get(m_url, "Key Metrics TTM")
        if isinstance(m_res, list) and len(m_res) > 0:
            m = m_res[0]
            fin_data['pe'] = f"{m.get('peRatioTTM', 0):.1f}x" if m.get('peRatioTTM') else "N/A"
            fin_data['roe'] = f"{m.get('roeTTM', 0) * 100:.1f}%" if m.get('roeTTM') else "N/A"
            fin_data['debt_equity'] = f"{m.get('debtToEquityTTM', 0) * 100:.1f}%" if m.get('debtToEquityTTM') else "N/A"
            fin_data['pb'] = m.get('pbRatioTTM', 'N/A')

        # 3. 현금흐름 (Accruals)
        cf_url = f"https://financialmodelingprep.com/stable/cash-flow-statement?symbol={symbol}&limit=1&apikey={api_key}"
        cf_res = safe_fmp_get(cf_url, "Cash Flow")
        if isinstance(cf_res, list) and len(cf_res) > 0 and fin_data['net_margin'] != 'N/A':
            ocf = float(cf_res[0].get('operatingCashFlow', 0))
            fin_data['accruals'] = "Low" if (fin_data.get('netIncome', 0) - ocf) <= 0 else "High"
        else:
            fin_data['accruals'] = "Unknown"

        # 4. DCF 적정주가
        dcf_url = f"https://financialmodelingprep.com/stable/discounted-cash-flow?symbol={symbol}&apikey={api_key}"
        dcf_res = safe_fmp_get(dcf_url, "DCF")
        if isinstance(dcf_res, list) and len(dcf_res) > 0:
            fin_data['dcf_price'] = f"${dcf_res[0].get('dcf', 0.0):.2f}"
            fin_data['current_price'] = f"${dcf_res[0].get('Stock Price', 0.0):.2f}"

        # 5. 퀀트 Rating
        r_url = f"https://financialmodelingprep.com/stable/rating?symbol={symbol}&apikey={api_key}"
        r_res = safe_fmp_get(r_url, "Quant Rating")
        if isinstance(r_res, list) and len(r_res) > 0:
            fin_data['rating'] = r_res[0].get('rating', 'N/A')
            fin_data['recommendation'] = r_res[0].get('ratingRecommendation', 'N/A')
            fin_data['health_score'] = r_res[0].get('ratingScore', 'N/A')

    except Exception as e:
        print(f"Data Fetch Error for {symbol}: {e}")
    
    return fin_data

    
# ==========================================
# [신규 추가] FMP 애널리스트 목표가 & 컨센서스 수집 헬퍼
# ==========================================
def fetch_analyst_estimates(symbol, api_key):
    data = {"target": "N/A", "high": "N/A", "low": "N/A", "consensus": "N/A"}
    try:
        pt_url = f"https://financialmodelingprep.com/stable/price-target-consensus?symbol={symbol}&apikey={api_key}"
        pt_res = requests.get(pt_url, timeout=5).json()
        if isinstance(pt_res, dict) and "Error Message" in pt_res:
            print(f"🚫 [Tab 4 목표가 차단됨] -> {pt_res['Error Message']}")
        elif isinstance(pt_res, list) and len(pt_res) > 0 and isinstance(pt_res[0], dict):
            data['target'] = pt_res[0].get('targetConsensus', 'N/A')
            data['high'] = pt_res[0].get('targetHigh', 'N/A')
            data['low'] = pt_res[0].get('targetLow', 'N/A')

        rec_url = f"https://financialmodelingprep.com/stable/analyst-stock-recommendations?symbol={symbol}&limit=1&apikey={api_key}"
        rec_res = requests.get(rec_url, timeout=5).json()
        if isinstance(rec_res, dict) and "Error Message" in rec_res:
            print(f"🚫 [Tab 4 투자의견 차단됨] -> {rec_res['Error Message']}")
        elif isinstance(rec_res, list) and len(rec_res) > 0 and isinstance(rec_res[0], dict):
            data['consensus'] = rec_res[0].get('ratingRecommendation', 'N/A')
    except Exception as e: 
        print(f"Analyst Data Fetch Error for {symbol}: {e}")
    return data

# ==========================================
# [신규 추가] Tab 4 프리미엄 요약 전용 프롬프트 및 수집 함수 (M&A 및 인수합병)
# ==========================================
def get_tab4_ma_premium_prompt(lang, ticker, raw_data):
    if lang == 'en':
        return f"""You are a Lead M&A Analyst on Wall Street. Summarize the latest Mergers and Acquisitions (M&A) data for {ticker}.
[Strict Rules]
1. Write ENTIRELY in English. DO NOT mix other languages.
2. Write exactly 3 paragraphs:
   - Para 1: [Recent M&A Transactions & Targets]
   - Para 2: [Deal Size & Strategic Purpose]
   - Para 3: [Synergy & Valuation Impact]
3. Each paragraph must be 4-5 sentences long, packed with specific deal values and professional insights.
4. DO NOT use markdown bold (**) for numbers.
5. Omit greetings and start immediately with a professional, objective tone.

[Raw Data]:
{raw_data}"""

    elif lang == 'ja':
        return f"""あなたはウォール街のシニアM&Aアナリストです。提供されたデータに基づき、{ticker}の最新の「M&Aおよび企業買収履歴」を日本語で深層要約してください。
[厳格な作成ルール]
1. 全て自然な日本語のみで記述してください。
2. 必ず以下の3つの段落に分けて作成してください：
   - 第1段落: [最近のM&A取引とターゲット企業]
   - 第2段落: [取引規模と戦略的目的]
   - 第3段落: [シナジー効果とバリュエーションへの影響]
3. 各段落は4〜5文で構成し、具体的な買収金額と専門的な洞察を含めてください。
4. 数値に強調記号（**）は絶対に使用しないでください。
5. 挨拶は省略し、すぐに本題に入ってください。冷静で客観的な分析トーンを維持してください。

[Raw Data]:
{raw_data}"""

    elif lang == 'zh':
        return f"""您是华尔街的资深并购(M&A)分析师。请根据提供的数据，用简体中文深度总结 {ticker} 的最新「M&A及企业并购记录」。
[严格编写规则]
1. 必须完全使用简体中文编写，严禁混用其他语言。
2. 必须严格分为以下3个段落：
   - 第一段: [近期并购交易与目标企业]
   - 第二段: [交易规模与战略目的]
   - 第三段: [协同效应与估值(Valuation)影响]
3. 每个段落应包含4-5句话，并提供具体的交易金额和深刻的专业见解。
4. 绝对不要使用星号（**）对数字进行加粗。
5. 省略问候语，直接进入正文。保持冷静、客观和分析的基调。

[Raw Data]:
{raw_data}"""

    else: # ko
        return f"""당신은 월가 수석 M&A 애널리스트입니다. 제공된 데이터를 바탕으로 {ticker}의 최신 'M&A 및 기업 인수합병 내역'을 한국어로 심층 요약하세요.
[작성 규칙 - 엄격 준수]
1. 반드시 순수한 한국어로만 작성하세요.
2. 반드시 아래 3개의 문단으로 나누어 작성하세요:
   - 1문단: [최근 인수합병(M&A) 내역 및 타겟 기업]
   - 2문단: [거래 규모 및 전략적 목적]
   - 3문단: [시너지 효과 및 기업가치(Valuation) 파급력]
3. 각 문단은 4~5줄(문장) 길이로 구체적인 인수 금액($) 수치를 포함해 작성하세요.
4. 숫자에 별표(**) 강조를 절대 사용하지 마세요.
5. 인사말을 생략하고 첫 글자부터 본론만 작성하세요. 모든 문장은 반드시 '~습니다', '~ㅂ니다' 형태의 격식 있고 정중한 존댓말(합쇼체)로 작성하세요. (예: ~합니다, ~입니다, ~됩니다, ~전망됩니다 등). 절대 '~한다', '~이다' 형태의 평어체를 사용하지 마세요.

[Raw Data]:
{raw_data}"""

def run_tab4_ma_premium_collection(ticker, company_name):
    """Tab 4의 프리미엄 데이터(M&A 내역)를 수집하고 요약하여 캐싱합니다."""
    if 'model_strict' not in globals() or not model_strict: return
    try:
        limit_time_str = (datetime.now() - timedelta(hours=168)).isoformat() # M&A도 자주 안 터지므로 7일 유지
        
        # FMP의 M&A 데이터 호출 (Stable 규격)
        url = f"https://financialmodelingprep.com/stable/search-mergers-acquisitions?name={ticker}&apikey={FMP_API_KEY}"
        ma_raw = get_fmp_data_with_cache(ticker, "RAW_MA_HISTORY", url, valid_hours=168)
        
        is_ma_valid = isinstance(ma_raw, list) and len(ma_raw) > 0

        for lang_code in SUPPORTED_LANGS.keys():
            if is_ma_valid:
                ma_summary_key = f"{ticker}_PremiumMA_v1_{lang_code}"
                try:
                    res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", ma_summary_key).gt("updated_at", limit_time_str).execute()
                    if not res.data:
                        # M&A 내역 텍스트 변환 (최대 10개)
                        import json
                        content = json.dumps(ma_raw[:10]) 
                        prompt = get_tab4_ma_premium_prompt(lang_code, ticker, content)
                        
                        for attempt in range(3):
                            try:
                                resp = model_strict.generate_content(prompt)
                                if resp and resp.text:
                                    paragraphs = [p.strip() for p in resp.text.split('\n') if len(p.strip()) > 20]
                                    indent_size = "14px" if lang_code == "ko" else "0px"
                                    html_str = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in paragraphs])
                                    
                                    batch_upsert("analysis_cache", [{"cache_key": ma_summary_key, "content": html_str, "updated_at": datetime.now().isoformat()}], "cache_key")
                                    print(f"✅ [{ticker}] M&A 분석 캐싱 완료 ({lang_code})")
                                    break
                            except Exception as e: time.sleep(1)
                except: pass
    except Exception as e:
        print(f"Tab4 Premium M&A Error for {ticker}: {e}")
    
# ==========================================
# [완벽 수정] Tab 3: 미시 지표 (독립된 3D 카드 요약 + 표준 재무분석 리포트)
# ==========================================
def run_tab3_analysis(ticker, company_name, metrics, ipo_date_str=None):
    if 'model_strict' not in globals() or not model_strict: return False
    
    days_passed = 0
    try:
        if ipo_date_str:
            days_passed = (datetime.now().date() - pd.to_datetime(ipo_date_str).date()).days
    except: pass

    valid_hours = 24 * 30 if days_passed > 90 else 24 * 7 
    limit_time_str = (datetime.now() - timedelta(hours=valid_hours)).isoformat()
    
    # 💡 [검색 엔진 최적화] 데이터가 없으면 구체적인 쿼리로 구글 검색 강제 지시
    is_fmp_fin_poor = (str(metrics.get('growth', 'N/A')) in ['N/A', '', 'None'])
    can_fin_search = is_fmp_fin_poor and (model_search is not None)
    current_tab3_model = model_search if can_fin_search else model_strict
    
    # 대표님이 지정해주신 카드별 타겟 지표 맵핑
    g1_context = f"[Business Growth & Profitability] Sales Growth: {metrics.get('growth', 'N/A')}, Net Margin: {metrics.get('net_margin', 'N/A')}, Piotroski Score: {metrics.get('health_score', 'N/A')}/9"
    g2_context = f"[Financial Health & Quality] Debt to Equity: {metrics.get('debt_equity', 'N/A')}, Accruals Quality: {metrics.get('accruals', 'Unknown')}"
    g3_context = f"[Market Valuation] Forward P/E: {metrics.get('pe', 'N/A')}, DCF Target Price: {metrics.get('dcf_price', 'N/A')}, Current Price: {metrics.get('current_price', 'N/A')}"

    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key_sum = f"{ticker}_Tab3_Summary_{lang_code}"
        cache_key_full = f"{ticker}_Tab3_v2_Premium_{lang_code}"
        
        try:
            res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key_full).gt("updated_at", limit_time_str).execute()
            if res.data: continue 
        except: pass

        # ----------------------------------------------------
        # 🚀 다국어 프롬프트 완벽 분리 (역할/지침 명확화)
        # ----------------------------------------------------
        if lang_code == 'ko':
            search_directive = f"\n🚨 [강제 검색] FMP 데이터가 비어있습니다. 즉시 구글 검색 도구를 실행하여 '{company_name} {ticker} 2024 2025 실적 발표(financial results)'를 검색하세요. '18억 달러 매출' 등 실제 수치를 반드시 찾아 리포트에 포함시키세요. 수치가 없으면 시장 점유율이나 최신 뉴스 동향이라도 실측치로 넣으십시오." if can_fin_search else ""
            
            # [Call 1] 카드 요약 (지표의 학술적 해석)
            sum_p = f"당신은 월가의 수석 퀀트 애널리스트입니다. {company_name}({ticker})의 다음 지표들을 학문적이고 정량적인 기준(Criteria)으로 해석하여 3개의 독립된 대시보드 카드 요약을 작성하세요.\n[1번 카드]: {g1_context}\n[2번 카드]: {g2_context}\n[3번 카드]: {g3_context}\n{search_directive}"
            sum_i = """
            [UI 카드 작성 규칙 - 절대 엄수]
            1. 3개의 완전히 독립된 텍스트 덩어리만 출력하세요. '1번 카드:', 'Card 1:' 등 어떠한 형태의 제목이나 숫자 넘버링도 절대 쓰지 마세요.
            2. 반드시 아래의 정확한 포맷으로만 출력하세요.
               [포맷]: (성장률, 마진, 피오트로스키 점수를 바탕으로 비즈니스 성장성 및 수익성을 진단하는 4~5문장) |||SEP||| (부채비율과 발생액 품질을 바탕으로 재무 건전성 및 이익의 질을 진단하는 4~5문장) |||SEP||| (PER과 DCF 적정주가를 바탕으로 현재 시장 가치 평가를 진단하는 4~5문장)
            3. 구분자 '|||SEP|||' 이외의 어떠한 특수기호나 줄바꿈도 단락 사이에 넣지 마세요.
            4. 🚨 [어투 고정]: 모든 문장은 반드시 '~습니다', '~합니다' 형태의 정중한 존댓말(경어체)로 마무리하십시오. 평어체는 절대 금지합니다.
            """
            
            # [Call 2] 하단 전문 (표준 재무 분석)
            full_p = f"다음 데이터를 사용하여 {company_name}({ticker})의 펀더멘털을 다루는 '표준 정통 재무 분석 리포트'를 작성하세요.\n데이터: {g1_context}, {g2_context}, {g3_context}\n{search_directive}"
            full_i = """
            [작성 규칙 - 절대 엄수]
            1. 메인 제목이나 이모지(예: 🎓 CFA 리포트)를 절대 쓰지 마세요. 첫 글자부터 바로 소제목으로 시작하세요.
            2. 🚨 구체적 수치 인용 필수: 반드시 검색되거나 제공된 '정확한 수치'를 본문에 직접 인용하여 전문적인 재무 분석을 수행하세요.
            3. 🚨 핵심 재무 수치 및 비율(Ratio) 활용: 분석의 전문성을 높이기 위해, 데이터가 허락하는 선에서 표준적인 재무 분석에 보편적으로 사용되는 절대적 규모 수치(예: 매출액, 영업이익액, 순이익, 잉여현금흐름 등)와 핵심 비율(예: ROE, 영업이익률, 부채비율, 유동비율 등)을 총합 10개 내외로 적극 참고하여 문맥에 자연스럽게 녹여내세요.
            4. 반드시 아래 3개의 소제목을 괄호만 사용하여 작성하세요: [수익성 및 성장성 분석], [재무 건전성 및 현금흐름], [적정 가치 및 종합 투자의견]. 마크다운 굵은 글씨(**)는 절대 금지.
            5. 🚨 소제목을 쓴 후 바로 다음에 본문 내용을 작성하세요. 각 단락은 4~5문장 길이로 꽉 채워서 작성하세요.
            6. '데이터가 없어 분석이 어렵다'는 변명이나 투덜거림은 절대 쓰지 마세요.
            7. 🚨 [어투 고정]: 모든 문장은 반드시 '~습니다', '~합니다' 형태의 정중한 존댓말(경어체)로 마무리하십시오.
            """

        elif lang_code == 'ja':
            search_directive = f"\n🚨 [強制検索] データが不足しています。直ちにGoogle検索で「{company_name} {ticker} 2024 2025 financial results」を検索し、具体的な数値を見つけて必ず含めてください。" if can_fin_search else ""
            
            sum_p = f"あなたはウォール街のシニアクオンツアナリストです。{company_name}({ticker})の次の指標を学術的・定量的な基準で解釈し、3つの独立したダッシュボードカード要約を作成してください。\n[1]: {g1_context}\n[2]: {g2_context}\n[3]: {g3_context}\n{search_directive}"
            sum_i = """
            [UIカード作成規則]
            1. 3つの完全に独立したテキストのみを出力してください。「カード1:」のような見出しや番号は一切禁止です。
            2. フォーマット: (成長率、マージン、ピオトロスキースコアに基づくビジネスの成長性と収益性の診断 4〜5文) |||SEP||| (負債比率と発生額の質に基づく財務健全性と利益の質の診断 4〜5文) |||SEP||| (PERとDCFに基づく市場バリュエーション診断 4〜5文)
            3. 区切り文字 '|||SEP|||' のみを使用してください。丁寧な日本語（〜です/ます）を使用してください。
            """
            
            full_p = f"次のデータを用いて {company_name}({ticker}) の標準的な本格的財務分析レポートを作成してください。\nデータ: {g1_context}, {g2_context}, {g3_context}\n{search_directive}"
            full_i = """
            [厳格な規則]
            1. メインタイトルや絵文字は絶対に使用しないでください。
            2. 🚨 具体的な数値を必ず引用し、専門的な財務分析を行ってください。
            3. 🚨 財務数値および指標の活用: 分析の専門性を高めるため、データが許す限り、標準的な財務分析で一般的に使用される主要な数値や比率（例：売上高、営業利益、純利益、フリーキャッシュフロー、ROE、営業利益率、負債比率など）を合計10個程度参照し、文脈に自然に組み込んでください。
            4. 必ず3つの小見出しを括弧のみで使用してください: [収益性と成長性の分析], [財務健全性とキャッシュフロー], [適正価値と総合投資意見]。太字(**)禁止。
            5. 🚨 小見出しの直後に本文を書き始めてください。各段落は必ず4〜5文で構成してください。
            6. 「データがない」という言い訳は絶対にしないでください。
            7. 丁寧な日本語（〜です/ます）を使用してください。
            """

        elif lang_code == 'zh':
            search_directive = f"\n🚨 [强制搜索] 数据不足。请立即使用Google搜索查找“{company_name} {ticker} 2024 2025 financial results”，并必须在报告中包含具体数据。" if can_fin_search else ""
            
            sum_p = f"作为华尔街的资深量化分析师，请根据学术和定量标准解读 {company_name}({ticker}) 的以下指标，撰写3个独立的仪表板卡片摘要。\n[1]: {g1_context}\n[2]: {g2_context}\n[3]: {g3_context}\n{search_directive}"
            sum_i = """
            [UI卡片规则]
            1. 必须输出3段完全独立的纯文本。绝对不要使用任何像“卡片1:”这样的标题或数字编号。
            2. 格式必须为: (基于增长率、利润率和皮奥特罗斯基分数诊断业务增长与盈利能力 4-5句话) |||SEP||| (基于债务比率和应计利润质量诊断财务健康与利润质量 4-5句话) |||SEP||| (基于市盈率和DCF诊断市场估值水平 4-5句话)
            3. 仅使用 '|||SEP|||' 作为分隔符，不要加入任何其他换行符。使用专业简体中文编写。
            """
            
            full_p = f"请使用以下数据为 {company_name}({ticker}) 撰写一份标准的深度财务分析报告。\n数据: {g1_context}, {g2_context}, {g3_context}\n{search_directive}"
            full_i = """
            [严格规则]
            1. 绝对不要写主标题或表情符号。
            2. 🚨 必须引用具体的财务数据进行专业的分析。
            3. 🚨 财务数据与指标的应用: 为提升专业深度，在数据允许的范围内，请积极参考并融入标准财务分析中普遍使用的核心绝对数值和比率（如：营收、营业利润、净利润、自由现金流、ROE、营业利润率、资产负债率等），总计约10个左右，并使其自然融入语境。
            4. 必须使用3个带方括号的副标题，绝对不要使用加粗(**): [盈利能力与增长性分析], [财务健康与现金流], [合理估值与综合投资意见]。
            5. 🚨 副标题后直接开始写正文。每个段落必须包含4-5句话。
            6. 绝对不要抱怨数据缺失。
            """

        else: # en
            search_directive = f"\n🚨 [FORCE SEARCH] FMP data is missing. You MUST use Google Search for '\"{company_name}\" \"{ticker}\" financial results 2024 OR 2025'. Include exact numbers." if can_fin_search else ""
            
            sum_p = f"As a Wall Street Quant Analyst, interpret these metrics for {company_name}({ticker}) based on academic/quantitative criteria to write 3 independent card summaries.\n[1]: {g1_context}\n[2]: {g2_context}\n[3]: {g3_context}\n{search_directive}"
            sum_i = """
            [STRICT UI FORMAT RULES]
            1. You MUST output EXACTLY 3 text blocks separated ONLY by '|||SEP|||'. DO NOT use numbers or titles like 'Card 1:'.
            2. Output FORMAT MUST BE: (Diagnose business growth & profitability using growth/margin/Piotroski score in 4-5 sentences) |||SEP||| (Diagnose financial health & earnings quality using debt/accruals in 4-5 sentences) |||SEP||| (Diagnose market valuation using PE/DCF in 4-5 sentences).
            """
            
            full_p = f"Write a standard fundamental financial analysis report for {company_name}({ticker}).\nData: {g1_context}, {g2_context}, {g3_context}\n{search_directive}"
            full_i = """
            [STRICT RULES]
            1. NO MAIN TITLES or emojis. Start immediately.
            2. QUOTE HARD NUMBERS: You MUST base your professional analysis on the specific numerical data provided.
            3. 🚨 FINANCIAL FIGURES & RATIOS: To enhance professional depth, actively incorporate up to 10 standard financial metrics, absolute figures, and ratios (e.g., Revenue, Operating Income, Net Income, Free Cash Flow, ROE, Operating Margin, Debt-to-Equity) naturally into the context where data permits.
            4. Use EXACTLY 3 subheadings with brackets ONLY: [Profitability & Growth Analysis], [Financial Health & Cash Flow], [Valuation & Final Verdict]. DO NOT use markdown bold (**).
            5. 🚨 Write the paragraph immediately after the subheading. Each paragraph MUST be exactly 4-5 sentences long.
            6. NEVER complain about missing data.
            """

        try:
            # 1. 3D 카드 요약 생성
            res_sum = current_tab3_model.generate_content(sum_p + sum_i)
            if res_sum and res_sum.text:
                # 💡 [핵심 방어막] AI가 실수로 1. 2. 이나 제목을 붙인 경우 정규식으로 강력하게 잘라냄
                clean_sum = res_sum.text.strip()
                clean_sum = re.sub(r'(?i)(\*\*.*?\*\*|Card \d+:|카드 \d+:|カード\d+:|卡片\d+:|\d+\.)', '', clean_sum)
                
                batch_upsert("analysis_cache", [{"cache_key": cache_key_sum, "content": clean_sum.strip(), "updated_at": datetime.now().isoformat()}], "cache_key")

            # 2. 하단 전문 리포트 (표준 재무분석) 생성
            res_full = current_tab3_model.generate_content(full_p + full_i)
            if res_full and res_full.text:
                clean_full = res_full.text.replace("**", "").strip()
                batch_upsert("analysis_cache", [{"cache_key": cache_key_full, "content": clean_full, "updated_at": datetime.now().isoformat()}], "cache_key")
                
            print(f"✅ [{ticker}] Tab 3 미시 지표 분석 완료 ({lang_code}) - {'Search' if can_fin_search else 'Strict'}")
        except Exception as e:
            print(f"❌ [{ticker}] Tab 3 미시 지표 AI 에러 ({lang_code}): {e}")
            time.sleep(1)
            
# ==========================================
# [신규 추가] Tab 3 프리미엄 요약 전용 프롬프트 (다국어 완벽 분리)
# ==========================================
def get_tab3_premium_prompt(lang, type_name, ticker, raw_data):
    if lang == 'en':
        return f"""You are a Senior Wall Street Analyst. Analyze the following [Raw Data] ({type_name}) for {ticker}.
        
[Strict Rules]
1. Write ENTIRELY in English. Do not mix other languages.
2. Write exactly 3 paragraphs.
3. Each paragraph must be 4-5 sentences long, containing deep and professional insights.
4. DO NOT use markdown bold (**) for numbers.
5. Omit greetings and start the main content immediately. Maintain a cold, objective, and analytical tone.

[Raw Data]:
{raw_data}"""

    elif lang == 'ja':
        return f"""あなたはウォール街のシニアアナリストです。提供された [Raw Data] ({type_name}) に基づいて、{ticker} の業績・見通しを日本語で深層分析してください。
        
[厳格な作成ルール]
1. 全て自然な日本語のみで記述してください。
2. 必ず3つの段落に分けて作成してください。
3. 各段落は4〜5文で構成し、重厚で専門的な洞察を含めてください。
4. 数値に強調記号（**）は絶対に使用しないでください。
5. 挨拶は省略し、すぐに本題に入ってください。冷静で客観的な分析トーンを維持してください。

[Raw Data]:
{raw_data}"""

    elif lang == 'zh':
        return f"""您是华尔街的高级分析师。请根据提供的 [Raw Data] ({type_name})，用简体中文对 {ticker} 的业绩与预期进行深度分析。
        
[严格编写规则]
1. 必须完全使用简体中文编写，严禁混用其他语言。
2. 必须严格分为3个段落。
3. 每个段落应包含4-5句话，并提供深刻、专业的见解。
4. 绝对不要使用星号（**）对数字进行加粗。
5. 省略问候语，直接进入正文。保持冷静、客观和分析的基调。

[Raw Data]:
{raw_data}"""

    else: # ko
        return f"""당신은 월가 출신의 수석 애널리스트입니다. 아래 제공된 [Raw Data]({type_name})를 바탕으로 {ticker}의 실적 흐름 및 향후 전망을 한국어로 심층 분석하세요.
        
[작성 규칙 - 엄격 준수]
1. 반드시 순수한 한국어로만 작성하세요.
2. 반드시 3개의 문단으로 나누어 작성하세요.
3. 각 문단은 4~5줄(문장) 길이로 묵직하고 전문적인 통찰을 담으세요.
4. 숫자에 별표(**) 강조를 절대 사용하지 마세요.
5. 인사말을 생략하고 첫 글자부터 본론만 작성하세요. 
   모든 문장은 반드시 '~습니다', '~ㅂ니다' 형태의 격식 있고 정중한 존댓말(합쇼체)로 작성해 주십시오. 
   절대 '~한다', '~이다' 형태의 평어체를 사용하지 마세요.

[Raw Data]:
{raw_data}"""


# =========================================================
# 🚀 [NEW] Tab 3 프리미엄 전용 데이터 수집 함수
# =========================================================
def run_tab3_premium_collection(ticker, company_name):
    try:
        limit_time_str = (datetime.now() - timedelta(hours=24)).isoformat()
        
        surp_url = f"https://financialmodelingprep.com/stable/earnings-surprises?symbol={ticker}&apikey={FMP_API_KEY}"
        surp_raw = get_fmp_data_with_cache(ticker, "RAW_SURPRISE", surp_url, valid_hours=24)
        
        est_url = f"https://financialmodelingprep.com/stable/analyst-estimates?symbol={ticker}&period=annual&limit=2&apikey={FMP_API_KEY}"
        est_raw = get_fmp_data_with_cache(ticker, "RAW_ESTIMATE", est_url, valid_hours=24)

        # 🚨 [환각 방어막] 진짜 데이터인지 엄격 검사
        is_surp_valid = isinstance(surp_raw, list) and len(surp_raw) > 0
        is_est_valid = isinstance(est_raw, list) and len(est_raw) > 0

        for lang_code in SUPPORTED_LANGS.keys():
            if is_surp_valid:
                surp_summary_key = f"{ticker}_PremiumSurprise_v1_{lang_code}"
                try:
                    res_s = supabase.table("analysis_cache").select("updated_at").eq("cache_key", surp_summary_key).gt("updated_at", limit_time_str).execute()
                    if not res_s.data:
                        prompt_s = get_tab3_premium_prompt(lang_code, "Earnings Surprises (Beat/Miss)", ticker, surp_raw)
                        for attempt in range(3):
                            try:
                                resp_s = model_strict.generate_content(prompt_s)
                                if resp_s and resp_s.text:
                                    s_paragraphs = [p.strip() for p in resp_s.text.split('\n') if len(p.strip()) > 20]
                                    indent_size = "14px" if lang_code == "ko" else "0px"
                                    html_s = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in s_paragraphs])
                                    batch_upsert("analysis_cache", [{"cache_key": surp_summary_key, "content": html_s, "updated_at": datetime.now().isoformat()}], "cache_key")
                                    print(f"✅ [{ticker}] 어닝서프라이즈 캐싱 완료 ({lang_code})")
                                    break
                            except Exception as e: time.sleep(1)
                except: pass

            if is_est_valid:
                est_summary_key = f"{ticker}_PremiumEstimate_v1_{lang_code}"
                try:
                    res_e = supabase.table("analysis_cache").select("updated_at").eq("cache_key", est_summary_key).gt("updated_at", limit_time_str).execute()
                    if not res_e.data:
                        prompt_e = get_tab3_premium_prompt(lang_code, "Analyst Future Estimates (Revenue & EPS)", ticker, est_raw)
                        for attempt in range(3):
                            try:
                                resp_e = model_strict.generate_content(prompt_e)
                                if resp_e and resp_e.text:
                                    e_paragraphs = [p.strip() for p in resp_e.text.split('\n') if len(p.strip()) > 20]
                                    indent_size = "14px" if lang_code == "ko" else "0px"
                                    html_e = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in e_paragraphs])
                                    batch_upsert("analysis_cache", [{"cache_key": est_summary_key, "content": html_e, "updated_at": datetime.now().isoformat()}], "cache_key")
                                    print(f"✅ [{ticker}] 실적전망치 캐싱 완료 ({lang_code})")
                                    break
                            except Exception as e: time.sleep(1)
                except: pass
    except Exception as e:
        print(f"Premium Tab 3 FMP Error for {ticker}: {e}")

# ==========================================
# [신규 추가] Tab 3 프리미엄 요약 전용 프롬프트 및 수집 함수 (부문별 매출 비중)
# ==========================================
def get_tab3_revenue_premium_prompt(lang, ticker, raw_data):
    if lang == 'en':
        return f"""You are a Lead Equity Analyst on Wall Street. Summarize the Revenue Product Segmentation data for {ticker}.
[Strict Rules]
1. Write ENTIRELY in English. DO NOT mix other languages.
2. Write exactly 3 paragraphs:
   - Para 1: [Core Business Segments & Revenue Breakdown]
   - Para 2: [Growth Drivers & Profitability Contribution]
   - Para 3: [Diversification & Risk Assessment]
3. Each paragraph must be 4-5 sentences long, packed with specific revenue percentages and professional insights.
4. DO NOT use markdown bold (**) for numbers.
5. Omit greetings and start immediately with a professional, objective tone.

[Raw Data]:
{raw_data}"""

    elif lang == 'ja':
        return f"""あなたはウォール街のシニア・エクイティ・アナリストです。提供されたデータに基づき、{ticker}の「部門別売上比率 (Revenue Segmentation)」を日本語で深層要約してください。
[厳格な作成ルール]
1. 全て自然な日本語のみで記述してください。
2. 必ず以下の3つの段落に分けて作成してください：
   - 第1段落: [中核事業部門と売上比率]
   - 第2段落: [成長牽引部門と収益貢献度]
   - 第3段落: [事業多角化の水準とリスク]
3. 各段落は4〜5文で構成し、具体的な売上比率（％）と専門的な洞察を含めてください。
4. 数値に強調記号（**）は絶対に使用しないでください。
5. 挨拶は省略し、すぐに本題に入ってください。冷静で客観的な分析トーンを維持してください。

[Raw Data]:
{raw_data}"""

    elif lang == 'zh':
        return f"""您是华尔街的资深股票分析师。请根据提供的数据，用简体中文深度总结 {ticker} 的「各部门营收占比 (Revenue Segmentation)」。
[严格编写规则]
1. 必须完全使用简体中文编写，严禁混用其他语言。
2. 必须严格分为以下3个段落：
   - 第一段: [核心业务部门及营收占比]
   - 第二段: [增长驱动部门与盈利贡献度]
   - 第三段: [业务多元化水平及风险评估]
3. 每个段落应包含4-5句话，并提供具体的营收百分比和深刻的专业见解。
4. 绝对不要使用星号（**）对数字进行加粗。
5. 省略问候语，直接进入正文。保持冷静、客观和分析的基调。

[Raw Data]:
{raw_data}"""

    else: # ko
        return f"""당신은 월가 수석 주식 애널리스트입니다. 제공된 데이터를 바탕으로 {ticker}의 '부문별 매출 비중(Revenue Segmentation)'을 한국어로 심층 요약하세요.
[작성 규칙 - 엄격 준수]
1. 반드시 순수한 한국어로만 작성하세요.
2. 반드시 아래 3개의 문단으로 나누어 작성하세요:
   - 1문단: [핵심 사업 부문 및 매출 비중]
   - 2문단: [성장 주도 부문 및 수익성 기여도]
   - 3문단: [사업 다각화 수준 및 집중 리스크 평가]
3. 각 문단은 4~5줄(문장) 길이로 구체적인 매출 비중(%) 수치를 포함해 작성하세요.
4. 숫자에 별표(**) 강조를 절대 사용하지 마세요.
5. 인사말을 생략하고 첫 글자부터 본론만 작성하세요. 모든 문장은 반드시 '~습니다', '~ㅂ니다' 형태의 격식 있고 정중한 존댓말(합쇼체)로 작성하세요. (예: ~합니다, ~입니다, ~됩니다, ~전망됩니다 등). 절대 '~한다', '~이다' 형태의 평어체를 사용하지 마세요.

[Raw Data]:
{raw_data}"""

def run_tab3_revenue_premium_collection(ticker, company_name):
    """Tab 3의 프리미엄 데이터(부문별 매출 비중)를 수집하고 요약하여 캐싱합니다."""
    if 'model_strict' not in globals() or not model_strict: return
    try:
        limit_time_str = (datetime.now() - timedelta(hours=168)).isoformat() # 매출 비중은 연간/분기 데이터이므로 7일 캐싱
        
        # FMP의 Product Segmentation 데이터 호출 (1년치)
        url = f"https://financialmodelingprep.com/stable/revenue-product-segmentation?symbol={ticker}&structure=flat&period=annual&apikey={FMP_API_KEY}"
        rev_raw = get_fmp_data_with_cache(ticker, "RAW_REVENUE_SEGMENT", url, valid_hours=168)
        
        # FMP API v4는 딕셔너리 형태로 리턴되는 경우가 많아 리스트로 감싸거나 변환 확인
        is_rev_valid = (isinstance(rev_raw, list) and len(rev_raw) > 0) or (isinstance(rev_raw, dict) and len(rev_raw) > 0 and "Error Message" not in rev_raw)

        for lang_code in SUPPORTED_LANGS.keys():
            if is_rev_valid:
                rev_summary_key = f"{ticker}_PremiumRevenueSeg_v1_{lang_code}"
                try:
                    res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", rev_summary_key).gt("updated_at", limit_time_str).execute()
                    if not res.data:
                        # 텍스트 형태(JSON String)로 변환하여 AI에게 전달
                        import json
                        content = json.dumps(rev_raw[0] if isinstance(rev_raw, list) else rev_raw) 
                        prompt = get_tab3_revenue_premium_prompt(lang_code, ticker, content)
                        
                        for attempt in range(3):
                            try:
                                resp = model_strict.generate_content(prompt)
                                if resp and resp.text:
                                    paragraphs = [p.strip() for p in resp.text.split('\n') if len(p.strip()) > 20]
                                    indent_size = "14px" if lang_code == "ko" else "0px"
                                    html_str = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in paragraphs])
                                    
                                    batch_upsert("analysis_cache", [{"cache_key": rev_summary_key, "content": html_str, "updated_at": datetime.now().isoformat()}], "cache_key")
                                    print(f"✅ [{ticker}] 매출 비중 분석 캐싱 완료 ({lang_code})")
                                    break
                            except Exception as e: time.sleep(1)
                except: pass
    except Exception as e:
        print(f"Tab3 Premium Revenue Seg Error for {ticker}: {e}")

# ==========================================
# [수정/완전판] Tab 2: 거시 지표 수집 (FMP 연동 + 실시간 연산 + 독립된 3D 카드 다국어 분석)
# ==========================================
def update_macro_data(df):
    if 'model_strict' not in globals() or not model_strict: return
    
    valid_hours = 24
    limit_time_str = (datetime.now() - timedelta(hours=valid_hours)).isoformat()
    
    try:
        res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", "Market_Dashboard_Metrics").gt("updated_at", limit_time_str).execute()
        if res.data: 
            print("✅ 거시 지표(Tab 2)는 24시간이 경과하지 않아 기존 캐시를 유지합니다.")
            return
    except: pass

    print("🌍 거시 지표(Tab 2) 실제 데이터 업데이트 및 연산 중...")
    
    today = datetime.now()
    data = {
        "ipo_return": 0.0, "ipo_volume": 0, "unprofitable_pct": 0.0,
        "withdrawal_rate": 0.0, "vix": 20.0, "fear_greed": 50, 
        "buffett_val": 195.0, "pe_ratio": 24.0
    }
    
    try:
        if not df.empty:
            df['dt'] = pd.to_datetime(df['date'], errors='coerce')
            upcoming = df[(df['dt'] > today) & (df['dt'] <= today + timedelta(days=30))]
            data["ipo_volume"] = len(upcoming)
            
            past_1y = df[(df['dt'] >= today - timedelta(days=365)) & (df['dt'] <= today)]
            if len(past_1y) > 0:
                withdrawn_cnt = len(past_1y[past_1y['status'].str.lower().str.contains('withdrawn|철회', na=False)])
                data["withdrawal_rate"] = (withdrawn_cnt / len(past_1y)) * 100
                
            data["unprofitable_pct"] = 75.0 if data["ipo_volume"] > 15 else 60.0
            data["ipo_return"] = 18.5 if data["vix"] < 15 else 5.2
    except Exception as e: pass

    try:
        q_url = f"https://financialmodelingprep.com/stable/quote?symbol=^VIX,SPY,^W5000&apikey={FMP_API_KEY}"
        q_res = requests.get(q_url, timeout=5).json()
        if isinstance(q_res, list):
            q_map = {item['symbol']: item for item in q_res}
            if '^VIX' in q_map: data["vix"] = float(q_map['^VIX'].get('price', 20.0))
            if 'SPY' in q_map: data["pe_ratio"] = float(q_map['SPY'].get('pe', 24.5))
            if '^W5000' in q_map:
                w5000_price = float(q_map['^W5000'].get('price', 0))
                if w5000_price > 0:
                    data["buffett_val"] = ((w5000_price * 1.1) / 1000 / 28.0) * 100

        r_url = f"https://financialmodelingprep.com/stable/market-risk-premium?apikey={FMP_API_KEY}"
        r_res = requests.get(r_url, timeout=5).json()
        if isinstance(r_res, list) and len(r_res) > 0:
            us_risk = next((item for item in r_res if item.get('country') == 'United States'), None)
            if us_risk:
                data["fear_greed"] = max(0, min(100, 100 - ((float(us_risk.get('totalEquityRiskPremium', 5.0)) - 3.0) * 20))) 
    except Exception as e: pass

    batch_upsert("analysis_cache", [{
        "cache_key": "Market_Dashboard_Metrics",
        "content": json.dumps(data),
        "updated_at": datetime.now().isoformat()
    }], on_conflict="cache_key")

    # =======================================================
    # 🚀 [C] AI 리포트 생성 (독립된 3개의 UI 카드용)
    # =======================================================
    g1_context = f"Sentiment/Liquidity (IPO Return: {data['ipo_return']}%, Withdrawal Rate: {data['withdrawal_rate']}%)"
    g2_context = f"Risk/Supply (Upcoming IPOs: {data['ipo_volume']}, Unprofitable Ratio: {data['unprofitable_pct']}%)"
    g3_context = f"Macro/Valuation (VIX: {data['vix']}, Fear&Greed: {data['fear_greed']}, Buffett Indicator: {data['buffett_val']}%, S&P500 PE: {data['pe_ratio']}x)"

    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key_summary = f"Global_Market_Summary_{lang_code}"
        cache_key_full = f"Global_Market_Dashboard_{lang_code}"
        
        # 💡 [Call 1] 완전히 독립된 3개의 UI 카드 요약 (명확한 가이드)
        if lang_code == 'ko':
            sum_p = f"월가 수석 전략가로서 다음 3개 그룹의 데이터를 바탕으로 3개의 독립적인 대시보드 카드 요약을 작성하세요.\n[1번 카드 데이터]: {g1_context}\n[2번 카드 데이터]: {g2_context}\n[3번 카드 데이터]: {g3_context}"
            sum_i = """
            [UI 카드 작성 규칙 - 절대 엄수]
            1. 당신의 답변은 웹사이트의 서로 다른 3개의 독립된 카드에 각각 들어갈 텍스트입니다. 자연스럽게 이어지는 에세이가 아닙니다.
            2. 반드시 아래의 정확한 포맷으로만 출력하세요. 숫자 넘버링(1. 2.)이나 별도의 제목은 절대 쓰지 마세요.
               [포맷]: (1번 카드: 초기 수익률과 철회율 데이터를 바탕으로 투기적 광기 및 위험 선호도 진단 3~4문장) |||SEP||| (2번 카드: 상장 예정 물량과 미수익 기업 비중을 결합하여 공급 과잉 및 질적 저하 리스크 분석 3~4문장) |||SEP||| (3번 카드: VIX, 공포탐욕지수, 밸류에이션(PE/버핏지수)을 결합하여 증시 전반의 거시적 과열 여부 진단 3~4문장)
            3. 구분자 '|||SEP|||' 이외의 어떠한 특수기호나 줄바꿈도 단락 사이에 넣지 마세요.
            4. 모든 문장은 '~습니다/ㅂ니다' 형태의 정중체를 사용하세요.
            """
        elif lang_code == 'en':
            sum_p = f"Write 3 completely independent dashboard card summaries.\n[Card 1 Data]: {g1_context}\n[Card 2 Data]: {g2_context}\n[Card 3 Data]: {g3_context}"
            sum_i = """
            [UI Card Rules]
            1. Output EXACTLY 3 independent texts for 3 separate UI cards. Do not write a flowing essay.
            2. Output FORMAT MUST BE: (Card 1: Diagnose speculative mania using IPO return and withdrawal rate in 3-4 sentences) |||SEP||| (Card 2: Analyze supply risk using upcoming IPOs and unprofitable ratio in 3-4 sentences) |||SEP||| (Card 3: Evaluate macroeconomic overheating using VIX, Fear&Greed, Buffett, and PE in 3-4 sentences).
            3. DO NOT use numbers (1. 2. 3.) or titles. Separate strictly by '|||SEP|||'. Write in English.
            """
        elif lang_code == 'ja':
            sum_p = f"3つの独立したダッシュボードカードの要約を作成してください。\n[カード1のデータ]: {g1_context}\n[カード2のデータ]: {g2_context}\n[カード3のデータ]: {g3_context}"
            sum_i = """
            [UIカード作成規則]
            1. 3つの異なるカードに挿入される、完全に独立した3つの文章を出力してください。
            2. フォーマット: (カード1: 初期収益率と撤回率に基づく投機的熱狂の診断 3〜4文) |||SEP||| (カード2: 上場予定件数と赤字企業比率による供給リスク分析 3〜4文) |||SEP||| (カード3: VIX、Fear&Greed、バフェット指数、PEを結合したマクロ的な過熱感の評価 3〜4文)
            3. 番号(1. 2.)や見出しは禁止です。区切り文字 '|||SEP|||' のみを使用してください。丁寧な日本語を使用してください。
            """
        elif lang_code == 'zh':
            sum_p = f"请为3个独立的仪表板卡片撰写摘要。\n[卡片1数据]: {g1_context}\n[卡片2数据]: {g2_context}\n[卡片3数据]: {g3_context}"
            sum_i = """
            [UI卡片规则]
            1. 必须输出3段完全独立的文字，用于3个不同的UI卡片。不要写成连贯的文章。
            2. 格式必须为: (卡片1: 结合初期收益率与撤回率诊断投机狂热 3-4句话) |||SEP||| (卡片2: 结合上市排队数量与亏损企业占比分析供给风险 3-4句话) |||SEP||| (卡片3: 结合VIX、恐慌贪婪指数、巴菲特指标和PE评估宏观经济是否过热 3-4句话)
            3. 严禁使用数字编号或标题。必须仅用 '|||SEP|||' 隔开。使用专业简体中文编写。
            """

        # 💡 [Call 2] 하단 전문(Global Macro Strategic Matrix)
        if lang_code == 'ko':
            full_p = f"월가 수석 전략가로서 다음 데이터를 바탕으로 현재 글로벌 거시경제 및 IPO 시장 환경에 대한 심층 분석 리포트를 작성하세요.\n[1번]: {g1_context}\n[2번]: {g2_context}\n[3번]: {g3_context}"
            full_i = """
            [작성 규칙]
            1. 메인 제목(## 분석 등)은 절대 쓰지 마세요.
            2. 반드시 3개의 소제목을 괄호만 사용하여 작성하세요: [시장 유동성 및 투기 심리], [공급 리스크 및 질적 평가], [매크로 환경 및 밸류에이션]. 소제목에 마크다운 굵은 글씨(**)는 절대 사용하지 마세요.
            3. 🚨 소제목을 쓴 후, 바로 다음 줄(빈 줄 없이)에 본문 내용을 작성하세요. (단, 하나의 단락이 끝나고 다음 소제목으로 넘어갈 때만 빈 줄을 한 번 띄우세요.)
            4. 제공된 수치(VIX, PE 등)를 반드시 본문에 포함하여 근거로 제시하세요.
            5. 모든 문장은 '~습니다/ㅂ니다' 형태의 정중체를 사용하세요.
            """
        elif lang_code == 'en':
            full_p = f"Write a deep-dive macroeconomic report using this data:\n[1]: {g1_context}\n[2]: {g2_context}\n[3]: {g3_context}"
            full_i = """
            [Rules]
            1. NO MAIN TITLE.
            2. Use EXACTLY 3 subheadings with brackets only: [Market Liquidity & Speculation], [Supply Risk & Quality], [Macro Environment & Valuation]. DO NOT use markdown bold (**).
            3. 🚨 Write the paragraph immediately on the next line after the subheading WITHOUT a blank line. Only separate different sections (end of paragraph and the next subheading) with a blank line.
            4. You MUST quote the exact numbers provided.
            """
        elif lang_code == 'ja':
            full_p = f"次のデータを用いてマクロ経済の深層分析レポートを作成してください:\n[1]: {g1_context}\n[2]: {g2_context}\n[3]: {g3_context}"
            full_i = """
            [規則]
            1. メインタイトルは禁止。
            2. 必ず3つの小見出しを括弧のみで使用してください: [市場の流動性と投機心理], [供給リスクと質的評価], [マクロ環境とバリュエーション]。マークダウンの太字(**)は絶対に使用しないでください。
            3. 🚨 小見出しの直後の行に、空行を入れずに本文を書き始めてください。セクション間（本文の終わりと次の小見出しの間）のみ空行を入れてください。
            4. 提供された数値を必ず引用してください。
            """
        else: # zh
            full_p = f"请使用以下数据撰写宏观经济深度分析报告:\n[1]: {g1_context}\n[2]: {g2_context}\n[3]: {g3_context}"
            full_i = """
            [规则]
            1. 严禁写主标题。
            2. 必须使用3个带方括号的副标题，绝对不要使用Markdown加粗(**): [市场流动性与投机情绪], [供给风险与质量评估], [宏观环境与估值]。
            3. 🚨 副标题后的下一行直接开始写正文，中间绝对不要留空行。仅在段落结束与下一个副标题之间留空行。
            4. 必须在正文中引用提供的具体数据。
            """

        # 🚀 [복구 완료] 실제로 AI를 호출하고 DB에 저장하는 누락되었던 로직
        try:
            # 1. 3D 카드 요약 3개 조각 생성 및 저장
            res_sum = model_strict.generate_content(sum_p + sum_i)
            if res_sum and res_sum.text:
                batch_upsert("analysis_cache", [{"cache_key": cache_key_summary, "content": res_sum.text.strip(), "updated_at": datetime.now().isoformat()}], "cache_key")

            # 2. 하단 전문 리포트 생성 및 저장
            res_full = model_strict.generate_content(full_p + full_i)
            if res_full and res_full.text:
                batch_upsert("analysis_cache", [{"cache_key": cache_key_full, "content": res_full.text.strip(), "updated_at": datetime.now().isoformat()}], "cache_key")
                
            print(f"✅ 거시 지표 AI 분석 완료 ({lang_code})")
        except Exception as e:
            print(f"❌ 거시 지표 AI 에러 ({lang_code}): {e}")

# ==========================================
# [수정] Tab 6: 스마트머니 통합 데이터 수집 (국회의원 & 공매도 추가)
# ==========================================
def fetch_smart_money_data(symbol, api_key):
    """FMP API 4종 세트를 캐싱 방어막과 함께 수집합니다."""
    data = {"insider": [], "institutional": [], "senate": [], "fail_to_deliver": []}
    
    in_url = f"https://financialmodelingprep.com/stable/insider-trading?symbol={symbol}&limit=10&apikey={api_key}"
    data["insider"] = get_fmp_data_with_cache(symbol, "SMART_IN", in_url) or []

    inst_url = f"https://financialmodelingprep.com/stable/institutional-ownership?symbol={symbol}&apikey={api_key}"
    res_inst = get_fmp_data_with_cache(symbol, "SMART_INST", inst_url)
    data["institutional"] = res_inst[:10] if isinstance(res_inst, list) else []
    
    sen_url = f"https://financialmodelingprep.com/stable/senate-trading?symbol={symbol}&apikey={api_key}"
    res_sen = get_fmp_data_with_cache(symbol, "SMART_SENATE", sen_url)
    data["senate"] = res_sen[:5] if isinstance(res_sen, list) else []
    
    ftd_url = f"https://financialmodelingprep.com/stable/fail-to-deliver?symbol={symbol}&apikey={api_key}"
    data["fail_to_deliver"] = get_fmp_data_with_cache(symbol, "SMART_FTD", ftd_url) or []

    return data

def run_tab6_analysis(ticker, company_name, smart_money_data):
    """Tab 6: 스마트머니 4대 지표 통합 감시 AI 리포트 생성"""
    # 🚨 [수정] model -> model_strict 로 방어막 변경
    if 'model_strict' not in globals() or not model_strict: return False
    
    valid_hours = 24 
    limit_time_str = (datetime.now() - timedelta(hours=valid_hours)).isoformat()
    
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Tab6_SmartMoney_v1_{lang_code}"
        
        try:
            res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time_str).execute()
            if res.data: continue 
        except: pass

        # 💡 [핵심] 구분자 |||SEP||| 를 사용하여 앱에서 4개 항목을 쪼개서 이쁘게 렌더링할 수 있게 유도
        if lang_code == 'en':
            prompt = f"""You are a Wall Street Insider & Institutional Flow Analyst.
Analyze the Smart Money data for {company_name} ({ticker}): {smart_money_data}

[Format Rules]
- Write STRICTLY in English.
- Use EXACTLY these 4 separators between sections: |||SEP|||
- NO intro/outro greetings.

[Section 1: Insider] Analyze if executives are secretly buying/selling.
|||SEP|||
[Section 2: Institutional] Analyze if mega-whales are sweeping up this stock.
|||SEP|||
[Section 3: US Senate] Analyze if any US Senators traded this stock recently. (Warning if buying before good news). If empty, say "No recent Senate trading detected."
|||SEP|||
[Section 4: Short Squeeze (FTD)] Analyze Fail-To-Deliver data. If numbers are surging, warn about a potential short squeeze. If empty, say "No significant short-selling pressure detected."
"""
        elif lang_code == 'ja':
            prompt = f"""あなたはウォール街の内部者取引および機関投資家フローの専門アナリストです。
{company_name} ({ticker})のスマートマネーデータを分析してください: {smart_money_data}

[フォーマット規則]
- 全て日本語で記述してください。
- 各セクションの間には必ず |||SEP||| という区切り文字を入れてください（合計3回）。
- 挨拶や前置きは絶対に書かないでください。

[セクション1: 内部者] 役員が密かに株を売買しているか分析。
|||SEP|||
[セクション2: 機関投資家] 巨大機関が買い集めているか分析。
|||SEP|||
[セクション3: 米国上院議員] 最近、米国の上院議員がこの株を取引したか分析。データがない場合は「最近の上院議員の取引は検出されていません」と記載。
|||SEP|||
[セクション4: 空売り(FTD)] Fail-To-Deliverデータを分析し、数値が急増していればショートスクイーズの警告を出す。データがない場合は「有意な空売り圧力は検出されていません」と記載。
"""
        elif lang_code == 'zh':
            prompt = f"""您是华尔街内幕交易与机构资金流向的专业分析师。
请分析 {company_name} ({ticker}) 的聪明钱数据: {smart_money_data}

[格式规则]
- 必须只用简体中文编写。
- 各部分之间必须使用 |||SEP||| 作为分隔符（共3次）。
- 绝对不要写问候语或开场白。

[第1部分: 内幕交易] 分析高管是否在暗中买卖。
|||SEP|||
[第2部分: 机构动向] 分析华尔街巨头是否在扫货。
|||SEP|||
[第3部分: 美国参议员] 分析近期是否有美国参议员(Senate)交易该股票。如果没有数据，请写“近期未检测到参议员交易”。
|||SEP|||
[第4部分: 卖空(FTD)] 分析未能交收(FTD)数据。如果数值激增，请警告可能出现轧空(Short Squeeze)。如果没有数据，请写“未检测到明显的卖空压力”。
"""
        else: # ko
            prompt = f"""당신은 월스트리트 내부자 거래 및 자금 흐름(Smart Money) 전문 애널리스트입니다.
{company_name} ({ticker})의 스마트머니 데이터를 심층 분석하세요: {smart_money_data}

[포맷 규칙 - 엄격 준수]
- 반드시 순수한 한국어로만 작성하세요.
- 모든 문장은 반드시 '~습니다', '~ㅂ니다' 형태의 정중한 존댓말(합쇼체)로 마무리하십시오.
- 각 항목 사이에 반드시 |||SEP||| 구분자를 넣으세요. (총 3개의 구분자가 들어가야 함)
- 인사말, 요약, 결론 등 불필요한 서론/본론은 절대 쓰지 마세요.

[항목 1: 내부자 거래] CEO/임원들의 최근 매수/매도 동향.
|||SEP|||
[항목 2: 대형 기관] 블랙록, 뱅가드 등 고래들의 매집 현황.
|||SEP|||
[항목 3: 미국 상원의원] 미국 상원의원(Senate)들의 최근 주식 거래 내역. 입법/정책 호재를 앞두고 선취매 했는지 감시. 데이터가 없으면 "최근 보고된 상원의원 거래 내역이 없습니다."
|||SEP|||
[항목 4: 공매도 미결제(FTD)] 기관들의 공매도 상환 실패(Fail To Deliver) 물량 분석. 수치가 급증했다면 숏 스퀴즈(Short Squeeze) 폭등 가능성 경고. 데이터가 없으면 "현재 유의미한 공매도 압력이 없습니다."
"""
        
        for attempt in range(3):
            try:
                # 🚨 [수정] model -> model_strict 로 변경
                response = model_strict.generate_content(prompt)
                res_text = response.text
                
                if lang_code != 'ko' and re.search(r'[가-힣]', res_text):
                    time.sleep(1); continue 
                        
                batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": res_text, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
                break 
            except Exception as e:
                time.sleep(1)


# ==========================================
# [추가] 프리미엄 유저 대상 통계적 급등 알림 엔진
# ==========================================
def run_premium_alert_engine(df_calendar):
    print("🕵️ 프리미엄 알림 엔진 가동 (FMP 캐싱 최적화 버전)...")
    today = datetime.now().date()
    new_alerts = []
    
    # DB에서 실시간 가격 맵 로드
    price_map = get_current_prices()

    for _, row in df_calendar.iterrows():
        ticker = row['symbol']
        name = row['name']
        current_p = price_map.get(ticker, 0.0)
        
        try: ipo_date = pd.to_datetime(row['date']).date()
        except: continue
        
        # --- 1. 일정 기반 알림 (기존 로직 유지) ---
        if ipo_date == today + timedelta(days=3):
            new_alerts.append({
                "ticker": ticker, "alert_type": "UPCOMING", "title": f"{ticker} 상장 D-3", 
                "message": "상장전 월가 기관의 평가를 미리 확인하세요."
            })
        
        if ipo_date + timedelta(days=180) == today + timedelta(days=7):
            new_alerts.append({
                "ticker": ticker, "alert_type": "LOCKUP", "title": f"{ticker} 락업해제 D-7", 
                "message": "내부자 보호예수 물량이 해제될 예정으로 주가 변동성이 올라갈 수 있습니다."
            })

        if current_p <= 0: continue

        # --- 2. 기간별 통계적 유의 상승 로직 (FMP API 캐싱 적용) ---
        try:
            # 💡 [교체 완료] 직접 호출 대신 캐시 방어막 함수를 사용합니다.
            url = f"https://financialmodelingprep.com/stable/historical-price-eod/full?symbol={ticker}&timeseries=260&apikey={FMP_API_KEY}"
            # 주가 데이터는 하루(24시간) 동안 캐싱된 것을 사용합니다.
            res = get_fmp_data_with_cache(ticker, "HIST", url, valid_hours=24)
            
            # 데이터가 유효할 때만 로직 실행
            if res and 'historical' in res:
                hist = res.get('historical', [])
                
                # FMP 데이터는 인덱스 0이 가장 최신
                if len(hist) >= 2:
                    p_1d = hist[1]['close'] # 1일 전 종가
                    if p_1d > 0 and ((current_p - p_1d) / p_1d) * 100 >= 12.0:
                        new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1D", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 1일 동안 {((current_p - p_1d) / p_1d) * 100:.1f}% 상승"})
                
                if len(hist) >= 5:
                    p_1w = hist[4]['close']
                    if p_1w > 0 and ((current_p - p_1w) / p_1w) * 100 >= 20.0:
                        new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1W", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 1주 동안 {((current_p - p_1w) / p_1w) * 100:.1f}% 상승"})

                if len(hist) >= 10:
                    p_2w = hist[9]['close']
                    if p_2w > 0 and ((current_p - p_2w) / p_2w) * 100 >= 30.0:
                        new_alerts.append({"ticker": ticker, "alert_type": "SURGE_2W", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 2주 동안 {((current_p - p_2w) / p_2w) * 100:.1f}% 상승"})

                if len(hist) >= 20:
                    p_4w = hist[19]['close']
                    if p_4w > 0 and ((current_p - p_4w) / p_4w) * 100 >= 40.0:
                        new_alerts.append({"ticker": ticker, "alert_type": "SURGE_4W", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 4주 동안 {((current_p - p_4w) / p_4w) * 100:.1f}% 상승"})

                if len(hist) >= 63:
                    p_3m = hist[62]['close']
                    if p_3m > 0 and ((current_p - p_3m) / p_3m) * 100 >= 60.0:
                        new_alerts.append({"ticker": ticker, "alert_type": "SURGE_3M", "title": f"{ticker} 중기 급등 포착", "message": f"{ticker} 주가 최근 3개월 동안 {((current_p - p_3m) / p_3m) * 100:.1f}% 상승"})

                if len(hist) >= 250:
                    p_1y = hist[-1]['close'] # 약 1년 전
                    if p_1y > 0 and ((current_p - p_1y) / p_1y) * 100 >= 150.0:
                        new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1Y", "title": f"{ticker} 장기 급등 포착", "message": f"{ticker} 주가 최근 1년 동안 {((current_p - p_1y) / p_1y) * 100:.1f}% 상승"})
        
        except Exception as e: 
            pass

        # --- 3. 공모가 돌파 및 회복 시그널 (기존 로직 유지) ---
        try:
            ipo_p = float(str(row.get('price', '0')).replace('$', '').split('-')[0])
            if ipo_p > 0:
                surge_pct_ipo = ((current_p - ipo_p) / ipo_p) * 100
                if surge_pct_ipo >= 20.0:
                    new_alerts.append({
                        "ticker": ticker, "alert_type": "SURGE_IPO", "title": f"{ticker} (+{surge_pct_ipo:.1f}%)", 
                        "message": f"현재가 ${current_p:.2f}로 공모가 대비 강력한 상승세"
                    })
                elif 0 <= surge_pct_ipo < 3.0:
                    new_alerts.append({
                        "ticker": ticker, "alert_type": "REBOUND", "title": f"{ticker} 공모가 회복", 
                        "message": f"주가가 다시 공모가(${ipo_p}) 위로 올라섰습니다. 바닥 확인 신호입니다."
                    })
        except: pass

        # --- 4. 월가 기관 투자심리 호조 시그널 ---
        try:
            tab4_key = f"{ticker}_Tab4_ko"
            res_tab4 = supabase.table("analysis_cache").select("content").eq("cache_key", tab4_key).execute()
            if res_tab4.data:
                tab4_data = json.loads(res_tab4.data[0]['content'])
                rating_val = str(tab4_data.get('rating', '')).upper()
                score_val = str(tab4_data.get('score', '0')).strip()
                if ("BUY" in rating_val) or (score_val in ["4", "5"]):
                    new_alerts.append({
                        "ticker": ticker, "alert_type": "INST_UPGRADE", "title": f"{ticker} 기관투자자평가상향조정(Buy grade)", 
                        "message": f"월가 분석 결과, 투자 의견이 '{tab4_data.get('rating')}'(으)로 평가되었습니다."
                    })
        except: pass
            
    if new_alerts:
        batch_upsert("premium_alerts", new_alerts, on_conflict="ticker,alert_type")
        print(f"✅ {len(new_alerts)}개의 프리미엄 신호가 DB에 적재되었습니다.")


# ==========================================
# [4] 메인 실행 루프
# ==========================================
def main():
    print(f"🚀 Worker Start: {datetime.now()}")
    
    df = get_target_stocks()
    if df.empty: 
        print("⚠️ 수집된 IPO 종목이 없습니다.")
        return

    print("\n📋 [stock_cache] 명단 업데이트 및 신규 편입 식별 시작...")
    
    try:
        res_known = supabase.table("stock_cache").select("symbol").execute()
        known_tickers = {item['symbol'] for item in res_known.data}
    except Exception as e:
        print(f"⚠️ 기존 Ticker 로드 실패 (초기화 상태로 간주): {e}")
        known_tickers = set()
        
    now_iso = datetime.now().isoformat()
    today_date = datetime.now().date()
    stock_list = []
    sudden_additions = [] 
    
    for _, row in df.iterrows():
        sym = str(row['symbol'])
        
        try: ipo_dt = pd.to_datetime(row['date']).date()
        except: ipo_dt = today_date
        
        if known_tickers and (sym not in known_tickers) and (ipo_dt <= today_date):
            sudden_additions.append(sym)
            
        stock_list.append({
            "symbol": sym,
            "name": str(row['name']) if pd.notna(row['name']) else "Unknown",
            "last_updated": now_iso 
        })
        
    if sudden_additions:
        try:
            old_res = supabase.table("analysis_cache").select("content").eq("cache_key", "SUDDEN_ADDITIONS_LIST").execute()
            if old_res.data:
                old_list = json.loads(old_res.data[0]['content'])
                sudden_additions = list(set(old_list + sudden_additions))
        except: pass
        
        batch_upsert("analysis_cache", [{
            "cache_key": "IPO_CALENDAR_DATA",
            "content": df.to_json(orient='records'),
            "updated_at": datetime.now().isoformat()
        }], on_conflict="cache_key")
        print(f"✨ 신규 편입(스팩/직상장) 누적 {len(sudden_additions)}개 식별 및 DB 저장 완료.")

    batch_upsert("stock_cache", stock_list, on_conflict="symbol")
    update_macro_data(df)
    
    # ------------------ 💡 18개월 이내 상장 기업 타겟팅 ------------------
    print("🔥 타겟 종목 선별 중 (35일 상장예정 + 18개월 신규상장)...")
    price_map = get_current_prices() 
    
    today = datetime.now()
    df['dt'] = pd.to_datetime(df['date'])
    
    target_symbols = set()
    
    # 1. 상장 예정(35일)
    upcoming = df[(df['dt'] > today) & (df['dt'] <= today + timedelta(days=35))]
    target_symbols.update(upcoming['symbol'].tolist())
    print(f"   -> 상장 예정(35일): {len(upcoming)}개")
    
    # 2. 최근 상장(18개월 = 540일)
    past_18m = df[(df['dt'] >= today - timedelta(days=540)) & (df['dt'] <= today)]
    target_symbols.update(past_18m['symbol'].tolist())
    print(f"   -> 최근 상장(18개월): {len(past_18m)}개")

    print(f"✅ 최종 분석 대상: 총 {len(target_symbols)}개 종목 (중복 제거)")

    target_df = df[df['symbol'].isin(target_symbols)]
    total = len(target_df)
    
    print("\n🏛️ SEC EDGAR CIK 매핑 데이터 로드 중 (API 최적화)...")
    cik_mapping, name_to_ticker_map = get_sec_master_mapping()
    print(f"✅ 총 {len(cik_mapping)}개의 SEC 식별번호 확보 완료.")
    
    print(f"\n🤖 AI 심층 분석 시작 (총 {total}개 종목 다국어 캐싱)...")
    
    import time
    WORKER_START_TIME = time.time()
    MAX_RUN_TIME_SEC = 5.5 * 3600  # 5.5시간(19,800초)

    # 🚨 AAPL 테스트 모드 삭제 완료. 18개월 타겟 전체 루프 시작!
    for idx, row in target_df.iterrows():
        # 5.5시간 강제 종료 방어막
        if time.time() - WORKER_START_TIME > MAX_RUN_TIME_SEC:
            print("⏳ [알림] 깃허브 6시간 제한 임박! 서버 강제 다운을 막기 위해 작업을 일시 중단합니다.")
            break

        original_symbol = row.get('symbol')
        name = row.get('name')
        
        clean_name = normalize_company_name(name)
        official_symbol = name_to_ticker_map.get(clean_name, original_symbol)
        
        if original_symbol != official_symbol:
            print(f"🔧 [티커 교정 작동] {name}: {original_symbol} ➡️ {official_symbol}")
            if official_symbol in cik_mapping:
                cik_mapping[original_symbol] = cik_mapping[official_symbol]
        
        print(f"[{idx+1}/{total}] {original_symbol} 분석 중...", flush=True)
        
        try:
            c_status = row.get('status', 'Active')
            c_date = row.get('date', None)
            
            # Tab 0 & Tab 1 (기본 + 프리미엄)
            run_tab1_analysis(official_symbol, name, c_status, c_date)
            run_tab0_analysis(official_symbol, name, c_status, c_date, cik_mapping)
            run_tab0_premium_collection(official_symbol, name)
            run_tab2_premium_collection(official_symbol, name) 
            
            # Tab 4: 목표가 수집 및 투자의견/M&A
            try:
                analyst_metrics = fetch_analyst_estimates(official_symbol, FMP_API_KEY)
                run_tab4_analysis(official_symbol, name, c_status, c_date, analyst_metrics)
                run_tab4_ma_premium_collection(official_symbol, name) 
            except Exception as e:
                print(f"Tab4 Analyst Data Error for {official_symbol}: {e}")
                pass
            
            # Tab 3: 11지표 통합 수집 및 재무 분석
            try:
                unified_metrics = fetch_premium_financials(official_symbol, FMP_API_KEY)
                
                batch_upsert("analysis_cache", [{
                    "cache_key": f"{official_symbol}_Raw_Financials",
                    "content": json.dumps(unified_metrics, ensure_ascii=False),
                    "updated_at": datetime.now().isoformat()
                }], on_conflict="cache_key")
                
                run_tab3_analysis(official_symbol, name, unified_metrics)
                run_tab3_premium_collection(official_symbol, name)
                run_tab3_revenue_premium_collection(official_symbol, name) 
                
            except Exception as e:
                print(f"Tab3 Premium Data Error for {official_symbol}: {e}")
                pass

            # Tab 6: 스마트머니 수집 및 분석
            try:
                smart_money_data = fetch_smart_money_data(official_symbol, FMP_API_KEY)
                run_tab6_analysis(official_symbol, name, smart_money_data)
            except Exception as e:
                print(f"Tab6 Smart Money Error for {official_symbol}: {e}")
                pass
            
            time.sleep(1.2)
            
        except Exception as e:
            # 🚨 바로 여기입니다! 기존의 "분석 건너뜀" 코드를 지우고 아래 내용을 넣으세요.
            import traceback 
            print(f"\n🚨 [{original_symbol}] 분석 중 치명적 오류 발생!")
            print(f"사유: {e}")
            print("-" * 30)
            traceback.print_exc() # 에러가 발생한 정확한 파일 위치와 줄 번호를 출력합니다.
            print("-" * 30)
            continue

    run_premium_alert_engine(df)
    
    # 💡 [생존 신고] 메인 워커 작업이 끝난 후 앱에 상태 알림
    batch_upsert("analysis_cache", [{"cache_key": "WORKER_LAST_RUN", "content": "alive", "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
            
    print(f"\n🏁 모든 작업 종료: {datetime.now()}")

if __name__ == "__main__":
    main()
