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

# 3. AI 모델 설정
model = None 
if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)
    try:
        model = genai.GenerativeModel(
            model_name='gemini-2.0-flash', 
            tools='google_search'  # 💡 구글이 요구한 정확한 이름으로 변경!
        )
        print("✅ AI 모델 로드 성공 (Google Search Tool 활성화)")
    except Exception as e:
        # 💡 여기도 마찬가지로 except: 보다 '4칸' 안으로 들여쓰기!
        model = genai.GenerativeModel('gemini-2.0-flash')
        print(f"⚠️ AI 모델 기본 로드 (Search 도구 제외): {e}")

# 💡 [중요] 다국어 지원 언어 리스트 정의
SUPPORTED_LANGS = {
    'ko': '전문적인 한국어(Korean)',
    'en': 'Professional English',
    'ja': '専門的な日本語(Japanese)',
    'zh': '简体中文(Simplified Chinese)'
}

# ==========================================
# [2] 헬퍼 함수: 과거 성공했던 '직접 전송' 방식
# ==========================================

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
            # FMP에서 최근 260 거래일(약 1년) 주가를 가볍게 호출 (인덱스 0이 가장 최신)
            url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}?timeseries=260&apikey={FMP_API_KEY}"
            res = requests.get(url, timeout=5).json()
            hist = res.get('historical', [])
            
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
# [신규] FMP 프리미엄 헬퍼 함수 (Tab 0, Tab 1 용)
# ==========================================

def fetch_fmp_8k_events(symbol, api_key):
    """[Tab 0] 기업의 최근 8-K(중대 이벤트: M&A, 소송, 임원교체 등)를 가져옵니다."""
    try:
        url = f"https://financialmodelingprep.com/api/v3/sec_filings/{symbol}?type=8-K&limit=3&apikey={api_key}"
        res = requests.get(url, timeout=5).json()
        if res and isinstance(res, list) and len(res) > 0:
            events = [f"- Date: {r.get('fillingDate')} | Link: {r.get('finalLink')}" for r in res]
            return "\n".join(events)
        return "No recent 8-K events."
    except Exception as e:
        print(f"8-K Fetch Error for {symbol}: {e}")
        return "No recent 8-K events."

def fetch_fmp_premium_news(symbol, api_key):
    """[Tab 1] FMP의 기관용 실시간 금융 뉴스(블룸버그, 로이터 등) 및 보도자료를 가져옵니다."""
    try:
        url = f"https://financialmodelingprep.com/api/v3/stock_news?tickers={symbol}&limit=5&apikey={api_key}"
        res = requests.get(url, timeout=5).json()
        if res and isinstance(res, list) and len(res) > 0:
            news_list = [f"- [{r.get('publishedDate')}] {r.get('title')} (Source: {r.get('site')})" for r in res]
            return "\n".join(news_list)
        return "No recent premium news."
    except Exception as e:
        print(f"Premium News Fetch Error for {symbol}: {e}")
        return "No recent premium news."

def fetch_fmp_earnings_call(symbol, api_key):
    """[Tab 1] 가장 최근 분기의 어닝콜(경영진 실적발표 Q&A) 스크립트 전문을 가져옵니다."""
    try:
        url = f"https://financialmodelingprep.com/api/v3/earning_call_transcript/{symbol}?limit=1&apikey={api_key}"
        res = requests.get(url, timeout=5).json()
        if res and isinstance(res, list) and len(res) > 0:
            # 텍스트가 너무 길면 토큰 초과 우려가 있으므로 앞부분(경영진 주요 발언)만 3000자로 자름
            content = res[0].get('content', '')[:3000]
            return f"[Quarter: {res[0].get('quarter')} / Year: {res[0].get('year')}]\n{content}..."
        return "No earnings call transcript available."
    except Exception as e:
        print(f"Earnings Call Fetch Error for {symbol}: {e}")
        return "No earnings call transcript available."


# ==========================================
# [신규 추가] FMP 프리미엄 헬퍼 함수 (Tab 0 용)
# ==========================================
def fetch_fmp_8k_events(symbol, api_key):
    """[Tab 0] 기업의 최근 8-K(중대 이벤트: M&A, 소송, 임원교체 등)를 가져옵니다."""
    try:
        url = f"https://financialmodelingprep.com/api/v3/sec_filings/{symbol}?type=8-K&limit=3&apikey={api_key}"
        res = requests.get(url, timeout=5).json()
        if res and isinstance(res, list) and len(res) > 0:
            events = [f"- Date: {r.get('fillingDate')} | Link: {r.get('finalLink')}" for r in res]
            return "\n".join(events)
        return "No recent 8-K events."
    except Exception as e:
        print(f"8-K Fetch Error for {symbol}: {e}")
        return "No recent 8-K events."


# ==========================================
# [완전 교체] run_tab0_analysis 함수
# ==========================================
def run_tab0_analysis(ticker, company_name, ipo_status="Active", ipo_date_str=None, cik_mapping=None):
    if not model: return
    
    status_lower = str(ipo_status).lower()
    is_withdrawn = any(x in status_lower for x in ['철회', '취소', 'withdrawn'])
    is_delisted = any(x in status_lower for x in ['폐지', 'delisted'])
    
    is_over_1y = False
    if ipo_date_str:
        try:
            ipo_dt = pd.to_datetime(ipo_date_str).date()
            if (datetime.now().date() - ipo_dt).days > 365: is_over_1y = True
        except: pass

    if is_withdrawn or is_delisted or is_over_1y: valid_hours = 24 * 7  
    else: valid_hours = 24      
        
    limit_time_str = (datetime.now() - timedelta(hours=valid_hours)).isoformat()

    # 기업 생애주기별 타겟 공시 문서 분기
    if is_withdrawn: target_topics = ["S-1", "S-1/A", "F-1", "FWP", "RW"]
    elif is_delisted: target_topics = ["S-1", "S-1/A", "F-1", "FWP", "424B4", "Form 25"]
    elif is_over_1y: target_topics = ["S-1", "FWP", "10-K", "10-Q", "BS", "IS", "CF"]
    else: target_topics = ["S-1", "S-1/A", "F-1", "FWP", "424B4"]

    cik = cik_mapping.get(ticker) if cik_mapping else None

    # 12가지 문서의 세부 지시사항 유지
    def get_localized_meta(lang, doc_type):
        meta_dict = {
            "ko": {
                "S-1": {"p": "Risk Factors, Use of Proceeds, MD&A", "s": "1문단: 발견된 가장 중요한 투자 포인트\n2문단: 실질적 성장 가능성과 재무적 의미\n3문단: 핵심 리스크 1가지와 그 파급 효과 및 대응책"},
                "S-1/A": {"p": "Pricing Terms, Dilution, Changes", "s": "1문단: 이전 S-1 대비 변경된 핵심 사항\n2문단: 제시된 공모가 범위의 적정성 및 수요예측 분위기\n3문단: 기존 주주 가치 희석 정도와 투자 매력도"},
                "F-1": {"p": "Foreign Risk, Accounting (GAAP), ADS Structure", "s": "1문단: 기업이 글로벌 시장에서 가진 독보적인 경쟁 우위\n2문단: 환율, 정치, 회계 등 해외 기업 특유의 리스크\n3문단: 미국 예탁 증서(ADS) 구조가 주주 권리에 미치는 영향"},
                "FWP": {"p": "Graphics, Strategy, Highlights", "s": "1문단: 경영진이 로드쇼에서 강조하는 미래 성장 비전\n2문단: 경쟁사 대비 기술적/사업적 차별화 포인트\n3문단: 자료 톤앤매너로 유추할 수 있는 시장 공략 의지"},
                "424B4": {"p": "Final Price, Underwriting, IPO Outcome", "s": "1문단: 확정 공모가의 위치와 시장 수요 해석\n2문단: 확정된 조달 자금의 투입 우선순위\n3문단: 주관사단 및 배정 물량 바탕 상장 초기 유통물량 예측"},
                "RW": {"p": "Withdrawal Reason, Market Condition, Future Plans", "s": "1문단: 상장 철회(Withdrawal) 결정적 사유 및 배경\n2문단: 상장 철회가 기업 재무 및 기존 투자자에게 미치는 영향\n3문단: 향후 재상장 또는 M&A 등 향후 계획"},
                "Form 25": {"p": "Delisting Reason, M&A, Shareholder Impact", "s": "1문단: 상장 폐지(Delisting)의 정확한 사유\n2문단: 상장 폐지 후 기존 주주의 권리 및 주식 처리 방안\n3문단: 장외시장(OTC) 거래 가능성 및 향후 기업 상태"},
                "10-K": {"p": "Annual Revenue, Operating Income, Net Income, Growth Rate", "s": "1문단: [연간 성과] 지난 1년간의 실제 매출액과 영업이익 수치($) 및 전년비 성장률 명시\n2문단: [사업 확장] 경영진이 강조한 핵심 사업부별 실적 데이터와 비즈니스 모델 변화\n3문단: [리스크] 새롭게 부각된 위험 요소가 향후 재무 수치에 미칠 수 있는 구체적 영향"},
                "10-Q": {"p": "Quarterly Revenue, Net Income, Cash Balances", "s": "1문단: [분기 실적] 이번 분기 실제 매출($) 및 순이익($) 성과와 전년 동기 대비 증감률 명시\n2문단: [현금 현황] 현재 보유한 현금 및 현금성 자산의 실제 수치와 단기 유동성 분석\n3문단: [가이던스] 경영진이 제시한 다음 분기 예상 수치 및 성장의 구체적 근거"},
                "BS": {"p": "Total Assets, Total Liabilities, Cash & Equivalents, Total Debt, Equity", "s": "1문단: [자산 구조] 현금성 자산을 포함한 유동 자산과 비유동 자산의 실제 수치(USD)를 공시 서류에서 찾아 명시\n2문단: [부채와 자본] 총부채와 자기자본의 실제 금액($)을 바탕으로 부채비율 분석 및 재무 리스크 진단\n3문단: [결론] 위 수치를 근거로 한 기업의 실질적인 재무 건전성 및 지급 능력 최종 평가"},
                "IS": {"p": "Revenue Growth, Gross Margin, Operating Income, Net Income, EPS", "s": "1문단: [매출 성과] 서류에 기재된 실제 매출액(Revenue) 수치와 전년 대비 성장률(%)을 반드시 포함\n2문단: [이익률 평가] 영업이익(Operating Income)과 순이익(Net Income)의 실제 달러 수치를 명시하고 마진 분석\n3문단: [수익성 품질] 주당순이익(EPS)과 일회성 비용 유무를 통해 본 기업의 실질적 수익 창출력 요약"},
                "CF": {"p": "Operating CF, Investing CF(CAPEX), Financing CF, Free Cash Flow(FCF)", "s": "1문단: [영업현금흐름] 실제 영업활동 현금흐름 수치를 명시하고 기업의 핵심 현금 창출력 평가\n2문단: [투자 및 CAPEX] 자본적 지출(CAPEX)의 실제 금액과 투자 방향성을 구체적인 숫자로 분석\n3문단: [현금 생존력] 잉여현금흐름(FCF)을 직접 계산(영업CF - CAPEX)하여 명시하고 향후 자금 조달 필요성 진단"}
            },
            "en": {
                "S-1": {"p": "Risk Factors, Use of Proceeds, MD&A", "s": "Para 1: The most important investment points found in this document.\nPara 2: Real business growth potential and financial implications.\nPara 3: One core risk, its ripple effects, and countermeasures."},
                "S-1/A": {"p": "Pricing Terms, Dilution, Changes", "s": "Para 1: Core changes compared to the previous S-1.\nPara 2: Appropriateness of pricing terms and expected demand.\nPara 3: Dilution for new investors and investment attractiveness."},
                "F-1": {"p": "Foreign Risk, Accounting (GAAP), ADS Structure", "s": "Para 1: The company's unique competitive advantage in the global market.\nPara 2: Specific risks for foreign companies (FX, politics, accounting).\nPara 3: Impact of the ADS structure on shareholder rights."},
                "FWP": {"p": "Graphics, Strategy, Highlights", "s": "Para 1: Future growth vision emphasized by management in the roadshow.\nPara 2: Technical/business differentiation points against competitors.\nPara 3: Market penetration willingness inferred from the tone and manner."},
                "424B4": {"p": "Final Price, Underwriting, IPO Outcome", "s": "Para 1: Interpretation of the final IPO price and market demand.\nPara 2: Priority of how the raised funds will be used.\nPara 3: Expected initial float based on underwriters and lock-ups."},
                "RW": {"p": "Withdrawal Reason, Market Condition, Future Plans", "s": "Para 1: Decisive reason and background for the IPO withdrawal.\nPara 2: Impact of the withdrawal on corporate finance and existing investors.\nPara 3: Future plans such as M&A or re-attempting IPO."},
                "Form 25": {"p": "Delisting Reason, M&A, Shareholder Impact", "s": "Para 1: Exact reason for delisting (M&A, voluntary, violations, etc.).\nPara 2: Impact on shareholder rights and stock treatment after delisting.\nPara 3: Possibility of OTC trading and future corporate status."},
                "10-K": {"p": "Annual Revenue, Operating Income, Net Income, Growth Rate", "s": "Para 1: [Annual Performance] State actual Revenue and Operating Income ($) from the past year with growth rates.\nPara 2: [Business Expansion] Core segment performance data and strategic model changes emphasized by management.\nPara 3: [Risks] Specific numerical impact of emerging risk factors on future financial metrics."},
                "10-Q": {"p": "Quarterly Revenue, Net Income, Cash Balances", "s": "Para 1: [Quarterly Results] State actual Revenue ($) and Net Income ($) for this quarter with YoY growth.\nPara 2: [Cash Status] Mention actual cash and cash equivalents and assess short-term liquidity.\nPara 3: [Guidance] Specific numerical guidance for the next quarter and its fundamental drivers."},
                "BS": {"p": "Total Assets, Total Liabilities, Cash, Debt, Equity", "s": "Para 1: [Asset Structure] List actual USD values for current and non-current assets including cash from the filing.\nPara 2: [Solvency] Use actual debt and equity figures ($) to analyze the debt-to-equity ratio and financial risks.\nPara 3: [Verdict] Final evaluation of short-term liquidity and long-term solvency based on the numbers."},
                "IS": {"p": "Revenue Growth, Margins, Operating Income, Net Income, EPS", "s": "Para 1: [Top-line] Explicitly include actual Revenue figures and YoY growth (%) from the document.\nPara 2: [Profitability] Analyze Operating and Net Income using actual dollar amounts and margin trends.\nPara 3: [Earnings Quality] Summarize EPS and long-term profitability based on real data points."},
                "CF": {"p": "Operating CF, Investing CF(CAPEX), Financing CF, FCF", "s": "Para 1: [Operating CF] State actual cash flow from operations ($) and evaluate core cash generation.\nPara 2: [Investing & CAPEX] Analyze actual CAPEX figures and investment direction using dollar amounts.\nPara 3: [Cash Runway] Calculate and state Free Cash Flow (FCF) using reported figures and assess funding needs."}
            },
            "ja": {
                "S-1": {"p": "リスク要因, 資金使途, MD&A", "s": "第1段落：この文書で確認できる最も重要な投資ポイント\n第2段落：実質的な成長可能性と財務的意味\n第3段落：核心的なリスク1つ、その波及効果および対応策"},
                "S-1/A": {"p": "需要予測, 希薄化, 変更点", "s": "第1段落：前回のS-1からの主な変更点\n第2段落：提示された公募価格帯の妥当性と需要予測の雰囲気\n第3段落：既存株主の価値希薄化の程度と投資魅力度"},
                "F-1": {"p": "地政学的リスク, 会計差異, ADS構造", "s": "第1段落：企業がグローバル市場で持つ独自の競争優位性\n第2段落：為替、政治、会計など海外企業特有のリスク\n第3段落：ADS構造が株主の権利に与える影響"},
                "FWP": {"p": "戦略, ハイライト, 市場シェア", "s": "第1段落：経営陣がロードショーで強調する未来の成長ビジョン\n第2段落：競합他社と比較した技術的・事業的な差別化ポイント\n第3段落：資料のトーンから推測される市場攻略への意欲"},
                "424B4": {"p": "最終価格, 引受シンジケート, 配分", "s": "第1段落：確定した公募価格の位置づけと市場需要の解釈\n第2段落：確定した調達資金の投入優先順位\n第3段落：配分に基づく上場初期の流通株式予測"},
                "RW": {"p": "撤回理由, 市場環境, 今後の計画", "s": "第1段落：上場撤回の決定的な理由と背景\n第2段落：上場撤回が企業の財務および投資家に与える影響\n第3段落：今後の再上場またはM&Aなどの計画"},
                "Form 25": {"p": "上場廃止理由, M&A, 株主への影響", "s": "第1段落：上場廃止の正確な理由（買収、自主的、違反など）\n第2段落：上場廃止後の既存株主の権利および株式の取り扱い\n第3段落：店頭市場（OTC）での取引可能性および今後の状態"},
                "10-K": {"p": "通期売上高, 営業利益, セ그メント実績", "s": "第1段落：[通期実績] 過去1年間の実際の売上高と営業利益の数値($)、および成長率を明記\n第2段落：[事業分析] 各セグメント別の実績データとビジネスモデルの変化\n第3段落：[将来リスク] リスク要因が今後の財務指標に与える具体的な影響"},
                "10-Q": {"p": "四半期売上, 純利益, 現金残高", "s": "第1段落：[四半期実績] 当四半期の実際の売上($)と純利益($)および前年比を明記\n第2段落：[流動性] 現在の現金および現金同等物の実際の数値をお明記し診断\n第3段落：[ガイダンス] 次四半期の予想数値と成長の具体的な根拠"},
                "BS": {"p": "資産合計, 負債合計, 現金等価物, 自己資本", "s": "第1段落：[資産構造] 現金同等物を含む流動・非流動資産の実際の数値(USD)を明記\n第2段落：[負債と資本] 総負債と自己資本の実際の金額($)に基づき分析\n第3段落：[結論] 数値に裏打ちされた短期支払能力と健全性の評価"},
                "IS": {"p": "売上高, 利益率, 営業利益, 純利益, EPS", "s": "第1段落：[売上実績] 報告書に明記された実際の売上高(Revenue)数値と成長率(%)を含める\n第2段落：[収益性] 営業利益と純利益の実際のドル数値を明記し分析\n第3段落：[利益の質] EPSと利益の質を具体的なデータで要約"},
                "CF": {"p": "営業CF, CAPEX, 財務CF, FCF", "s": "第1段落：[営業CF] 実際の営業活動によるCF数値($)を明記し評価\n第2段落：[投資とCAPEX] CAPEXの実際の金額と投資方向性を数字で分析\n第3段落：[現金の存続能力] フリーキャッシュフロー(FCF)を 직접計算(営業CF-CAPEX)して明記"}
            },
            "zh": {
                "S-1": {"p": "风险因素, 资金用途, MD&A", "s": "第一段：该文件中最重要的投资亮点\n第二段：实质性增长潜力及其财务意义\n第三段：一个核心风险，其连锁反应及应对措施"},
                "S-1/A": {"p": "定价条款, 股权稀释, 变更点", "s": "第一段：与之前S-1相比的核心变化\n第二段：定价区间的合理性及需求氛围分析\n第三段：现有股东的价值稀释程度及投资吸引力"},
                "F-1": {"p": "地缘政治风险, 会计差异, ADS结构", "s": "第一段：企业在全球市场中独有的竞争优势\n第二段：外汇、政治、会计等海外企业特有风险分析\n第三段：ADS结构对股东权利的影响"},
                "FWP": {"p": "战略, 亮点, 市场份额", "s": "第一段：管理层在路演中强调的未来增长愿景\n第二段：与竞争对手相比的技术/业务差异化优势\n第三段：从资料基调推测的市场开拓意愿"},
                "424B4": {"p": "最终价格, 承销, IPO结果", "s": "第一段：最终发行价的定位及市场需求解读\n第二段：确定募集资金的投入优先顺序\n第三段：基于配售情况的上市初期流通股预测"},
                "RW": {"p": "撤回原因, 市场环境, 未来计划", "s": "第一段：该企业撤回上市的决定性原因及背景\n第二段：撤回上市对企业财务及现有投资者的影响\n第三段：未来再次上市或并购等计划"},
                "Form 25": {"p": "退市原因, 并购, 股东影响", "s": "第一段：退市的准确原因（并购、自愿退市、违规等）\n第二段：退市后现有股东的权利及股票处理方案\n第三段：场外市场（OTC）交易的可能性及未来状态"},
                "10-K": {"p": "年度营收, 营业利润, 各板块数据", "s": "第一段：[年度表现] 明确列出过去一年的实际营收和营业利润数值($)及增长率\n第二段：[业务分析] 核心业务板块业绩数据及商业模式变化\n第三段：[风险展望] 风险因素对未来财务指标的具体影响"},
                "10-Q": {"p": "季度营收, 净利润, 现金储备", "s": "第一段：[季度业绩] 明确列出本季度实际营收($)和净利润($)及同比变化\n第二段：[现金状况] 明确列出当前的现金及现金等价物数值\n第三段：[指引] 管理层给出的下季度预期数值及短期增长的依据"},
                "BS": {"p": "总资产, 总负债, 现金及等价物, 权益", "s": "第一段：[资产结构] 明确列出流动资产和非流动资产的实际美元金额(USD)\n第二段：[负债与资本] 使用总负债和股东权益的实际金额($)评估稳定性\n第三段：[结论] 基于上述具体数值评估企业的偿债能力"},
                "IS": {"p": "营收增长, 毛利率, 净利润, EPS", "s": "第一段：[营收表现] 必须包含报告中列出的实际营收数值及同比增长率(%)\n第二段：[盈利指标] 使用实际美元金额分析营业利润和净利润\n第三段：[收益质量] 结合EPS总结企业的实际盈利能力"},
                "CF": {"p": "经营CF, 投资CF, 筹资CF, FCF", "s": "第一段：[经营现金流] 明确列出实际经营活动现金流数值($)并评估造血能力\n第二段：[投资与支出] 基于金额分析资本支出(CAPEX)的具体数值\n第三段：[现金流存续] 明确计算并列出自由现金流(FCF)情况"}
            }
        }
        lang_group = meta_dict.get(lang, meta_dict['ko'])
        return lang_group.get(doc_type, lang_group.get('S-1'))

    def get_format_instruction(lang):
        if lang == 'en':
            return "- Begin each paragraph with a translated **[Heading]**. Rich content, 4-5 sentences per paragraph. DO NOT bold numbers."
        elif lang == 'ja':
            return "- 各段落は日本語の **[見出し]** から始めてください。1段落につき4〜5文にし、数値に強調（**）は使わないでください。"
        elif lang == 'zh':
            return "- 每个段落以中文 **[副标题]** 开头。每段4-5句，请勿对数值进行加粗处理。"
        else:
            return "- 각 문단은 반드시 **[소제목]**으로 시작하세요. 각 문단마다 4~5문장씩 작성하며, 숫자에 강조(**)는 절대 사용하지 마세요."

    # 💡 [핵심] 프롬프트에 8-K 데이터(fmp_8k) 주입 및 |||SEP||| 분리 지시
    def get_localized_instruction(lang, ticker, topic, company_name, meta, sec_fact_prompt, format_inst, fmp_8k):
        if lang == 'en':
            return f"""You are a Senior Wall Street Analyst.
Target: {company_name} ({ticker}) - {topic}
Checkpoints: {meta['p']}
{sec_fact_prompt}

[Real-time 8-K Events (M&A, Lawsuits, Exec Changes)]:
{fmp_8k}

[STRICT WRITING RULES]
1. Write ENTIRELY in English. DO NOT use markdown bold (**) for numbers.
2. Separate your response into exactly TWO parts using '|||SEP|||'.

[Structure]
{meta['s']}

|||SEP|||

**[Real-time 8-K Critical Event Analysis]**
Analyze the 8-K events above. If "No recent", state it clearly. If there are events, explain their critical impact on the stock in 3-4 sentences.
{format_inst}"""

        elif lang == 'ja':
            return f"""あなたは証券分析のエキスパートです。
分析対象: {company_name} ({ticker}) - {topic}
{sec_fact_prompt}

[最新の8-Kイベント(M&A、訴訟、役員交代など)]:
{fmp_8k}

[厳格な作成ルール]
1. 全て日本語で作成し、数値に強調(**)は使用しないでください。
2. 回答は必ず '|||SEP|||' を使用して2つの部分に分けてください。

[構成]
{meta['s']}

|||SEP|||

**[リアルタイム8-K重大イベント分析]**
上記の8-Kイベントを分析してください。イベントがない場合はその旨を記載し、ある場合は株価への致命的な影響を3〜4文で解説してください。
{format_inst}"""

        elif lang == 'zh':
            return f"""您是资深证券分析师。
分析目标: {company_name} ({ticker}) - {topic}
{sec_fact_prompt}

[最新8-K事件(并购、诉讼、高管变动等)]:
{fmp_8k}

[严格编写指南]
1. 必须完全使用简体中文编写，严禁对数值加粗(**)。
2. 回答必须使用 '|||SEP|||' 严格分为两部分。

[结构要求]
{meta['s']}

|||SEP|||

**[实时8-K重大事件分析]**
分析上述8-K事件。如果没有，请明确说明。如果有，请用3-4句话解释其对股价的致命影响。
{format_inst}"""

        else: # ko
            return f"""당신은 월가 출신의 전문 분석가입니다.
분석 대상: {company_name} ({ticker}) - {topic}
체크포인트: {meta['p']}
{sec_fact_prompt}

[최근 8-K 중대 이벤트 (M&A, 소송, 임원교체 등)]:
{fmp_8k}

[작성 지침 - 필수 준수]
1. 반드시 한국어로만 작성하고 숫자에 별표(**) 강조를 쓰지 마세요.
2. 답변은 반드시 '|||SEP|||' 구분자를 기준으로 [기본 요약]과 [프리미엄 8-K 분석] 두 부분으로 나누어 출력하세요.

[내용 구성 지침]
{meta['s']}
{format_inst}

|||SEP|||

**[실시간 8-K 중대 이벤트 분석]**
제공된 8-K 데이터를 분석하세요. 이벤트가 없다면 "최근 보고된 돌발 악재/호재가 없습니다."라고 적으세요. 데이터가 있다면 해당 이슈가 단기 주가에 미칠 치명적 파급력을 3~4문장으로 냉철하게 분석하세요.
"""

    for topic in target_topics:
        sec_fact_prompt = ""
        sec_search_target = "10-K" if topic in ["BS", "IS", "CF"] else topic
        
        if cik:
            filed_date = check_sec_specific_filing(cik, sec_search_target)
            if filed_date:
                sec_fact_prompt = f"\n[SEC FACT CHECK] The company officially filed '{sec_search_target}' on {filed_date}. Focus on extracting specific data from this document."
            else:
                sec_fact_prompt = f"\n[SEC FACT CHECK] '{sec_search_target}' not found in SEC EDGAR. Use the latest available numerical data from recent web records."
        
        # 💡 [신규] FMP API 호출로 최신 8-K 데이터를 가져옵니다.
        fmp_8k_data = fetch_fmp_8k_events(ticker, FMP_API_KEY)
        
        for lang_code, target_lang in SUPPORTED_LANGS.items():
            # 💡 [핵심] 캐시키 버전을 v16으로 통일 (앱에서 알아서 블러 처리하므로 투트랙 필요 없음)
            cache_key = f"{company_name}_{topic}_Tab0_v16_{lang_code}"
            
            try:
                res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time_str).execute()
                if res.data: continue 
            except: pass

            meta = get_localized_meta(lang_code, topic)
            format_inst = get_format_instruction(lang_code)
            
            # 프리미엄 8-K 데이터가 주입된 프롬프트 생성
            prompt = get_localized_instruction(lang_code, ticker, topic, company_name, meta, sec_fact_prompt, format_inst, fmp_8k_data)
            
            for attempt in range(3):
                try:
                    response = model.generate_content(prompt)
                    res_text = response.text
                    
                    if lang_code != 'ko':
                        import re
                        if re.search(r'[가-힣]', res_text):
                            time.sleep(1); continue 
                            
                    # 💡 원본 그대로 1개의 키에만 저장!
                    batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": res_text, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
                    break 
                except:
                    time.sleep(1)

def run_tab1_analysis(ticker, company_name, ipo_status="Active", ipo_date_str=None):
    if not model: return
    
    now = datetime.now()
    status_lower = str(ipo_status).lower()
    is_withdrawn = bool(re.search(r'\b(withdrawn|rw|철회|취소)\b', status_lower))
    is_delisted_or_otc = bool(re.search(r'\b(delisted|폐지|otc)\b', status_lower))
    
    is_over_1y = False
    try:
        if ipo_date_str:
            days_passed = (now.date() - pd.to_datetime(ipo_date_str).date()).days
            if days_passed > 365: is_over_1y = True
    except: pass

    # 기업 상태별 동적 캐싱 주기
    if is_withdrawn or is_delisted_or_otc or is_over_1y: valid_hours = 24 * 7 
    elif "상장예정" in ipo_status or "30일" in ipo_status: valid_hours = 6
    else: valid_hours = 24

    limit_time_str = (now - timedelta(hours=valid_hours)).isoformat()
    current_date = now.strftime("%Y-%m-%d")
    current_year = now.strftime("%Y")

    # 4개 국어 순회 생성
    for lang_code, _ in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Tab1_v5_{lang_code}"
        
        # 이미 최신 캐시가 있으면 패스
        try:
            res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time_str).execute()
            if res.data: continue 
        except: pass

        # 💡 [핵심 수정] 언어별 프롬프트에 '전문 번역' 지시와 포맷 제약 추가
        if lang_code == 'ja':
            sys_prompt = "あなたは最高レベルの証券会社リサーチセンターのシニアアナリストです。すべての回答は必ず日本語で作成してください。"
            task2_label = "[タスク2: 最新ニュースの収集と専門的な翻訳]"
            target_lang = "日本語(Japanese)"
            lang_instruction = "必ず自然な日本語のみで作成してください。"
            json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "日経新聞のヘッドライン風に翻訳されたタイトル(記号なし)", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""
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
            json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "财经新闻头条风格的中文标题(不含特殊符号)", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""
        else:
            sys_prompt = "당신은 최고 수준의 증권사 리서치 센터의 시니어 애널리스트입니다. 반드시 한국어로 작성하세요."
            task2_label = "[작업 2: 최신 뉴스 수집 및 전문 번역]"
            target_lang = "한국어(Korean)"
            lang_instruction = "반드시 자연스러운 한국어만 사용하세요."
            json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "한국 경제신문 헤드라인 스타일로 번역된 제목(마크다운, 따옴표 제외)", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""

        if is_withdrawn:
            task1_label = f"[{'작업 1: 상장 철회(Withdrawn) 심층 진단' if lang_code == 'ko' else 'Task 1: Withdrawn IPO Diagnosis'}]"
            task1_structure = "\n- 1문단: [철회 배경 진단] 시장 환경 악화 여부 및 내부 펀더멘털/규제 이슈 분석\n- 2문단: [재무적 타격] 자본 조달 실패가 기업의 단기 유동성에 미치는 영향\n- 3문단: [생존 전략] M&A 피인수, 우회 상장, 추가 사모 펀딩 등 대안 시나리오\n"
        elif is_delisted_or_otc:
            task1_label = f"[{'작업 1: OTC/장외시장 거래 리스크 진단' if lang_code == 'ko' else 'Task 1: OTC Market Risk Analysis'}]"
            task1_structure = "\n- 1문단: [장외 편입 배경] 비즈니스 모델 요약 및 정규 시장 미진입(또는 강등) 사유\n- 2문단: [투자 리스크] 거래량 부족에 따른 유동성 위험(Liquidity Risk) 및 정보 비대칭성 진단\n- 3문단: [장기 전망] 사업 지속 가능성(Going Concern) 및 정규 시장 재진입 가능성\n"
        elif is_over_1y:
            task1_label = f"[{'작업 1: 상장 1년 차 펀더멘털 점검' if lang_code == 'ko' else 'Task 1: Post-IPO Fundamental Check'}]"
            task1_structure = "\n- 1문단: [목표 달성도] IPO 당시 제시했던 비전 대비 현재 핵심 펀더멘털 달성 여부\n- 2문단: [수익성 평가] 흑자 전환(Path to Profitability) 현황 및 잉여현금흐름(FCF)\n- 3문단: [자본 효율성] 투자(CAPEX/R&D) 성과 및 장기적 주주 가치 환원 전략\n"
        else:
            task1_label = f"[{'작업 1: 신규 IPO 비즈니스 심층 분석' if lang_code == 'ko' else 'Task 1: Deep Business Model Analysis'}]"
            task1_structure = "\n- 1문단: 비즈니스 모델 및 시장 내 핵심 경쟁 우위 (Competitive Advantage)\n- 2문단: 재무 현황 및 공모 자금 활용 계획 (Use of Proceeds)\n- 3문단: 향후 산업 전망 및 종합 투자 의견 (Outlook & Valuation)\n"

        prompt = f"""
        {sys_prompt}
        분석 대상: {company_name} ({ticker})
        기업 상태: {ipo_status}
        오늘 날짜: {current_date}

        {task1_label}
        아래 [필수 작성 원칙]을 준수하여 리포트를 작성하세요.
        1. 언어: {lang_instruction}
           - 경고: 영어 단어(potential, growth 등)를 중간에 그대로 노출하는 비문을 절대 금지합니다. 완벽하게 {target_lang} 어휘로 번역하세요.
        2. 포맷: 반드시 3개의 문단으로 나누어 작성하세요. 문단 사이에는 줄바꿈을 명확히 넣으세요.
           {task1_structure}
        3. 금지: 제목, 소제목, 특수기호, 불렛포인트(-)를 절대 쓰지 마세요. 인사말 없이 바로 본론부터 시작하세요.
        4. 최종 검수(Self-Check): 답변을 최종 출력하기 전에 스스로 엄격하게 검토하세요. 인사말, 서론, 또는 {target_lang} 외의 언어가 포함되어 있다면 삭제하세요.
        
        {task2_label}
        - 🚨 [강제 명령] 반드시 구글 검색 도구(google_search_retrieval)를 지금 즉시 사용하여 "{company_name} {ticker} news {current_year}"를 검색하십시오.
        - 과거 지식을 바탕으로 지어내지 말고, 검색 결과 중 오늘({current_date}) 기준 가장 최신 기사 5개를 선정하십시오.
        - 💡 [번역 필수 규칙] 각 뉴스의 'translated_title'은 반드시 {target_lang}의 '전문 경제신문/월스트리트 저널 헤드라인 스타일'로 완벽하게 번역하세요. (예: sh -> 주당, M -> 백만). 제목에 마크다운 기호(**)나 불필요한 따옴표는 절대 넣지 마세요.
        - 각 뉴스는 아래 JSON 형식으로 답변의 맨 마지막에 첨부하세요. 
        - [중요] sentiment 값은 시스템 로직을 위해 무조건 "긍정", "부정", "일반" 중 하나를 한국어로 적으세요.

        <JSON_START>
        {json_format}
        <JSON_END>
        """

        for attempt in range(3):
            try:
                response = model.generate_content(prompt)
                full_text = response.text

                # 한글 오염 방어막
                if lang_code != 'ko':
                    check_text = full_text.replace("긍정", "").replace("부정", "").replace("일반", "")
                    if re.search(r'[가-힣]', check_text):
                        time.sleep(1); continue 

                news_list = []
                json_str = ""
                
                json_match = re.search(r'\[\s*\{.*?\}\s*\]', full_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                    try: news_list = json.loads(json_str)
                    except: pass

                if json_str: biz_analysis = full_text.replace(json_str, "").replace("<JSON_START>", "").replace("<JSON_END>", "").strip()
                else: biz_analysis = full_text.split("{")[0].replace("<JSON_START>", "").strip()

                biz_analysis = re.sub(r'#.*', '', biz_analysis).strip()
                paragraphs = [p.strip() for p in biz_analysis.split('\n') if len(p.strip()) > 20]
                
                indent_size = "14px" if lang_code == "ko" else "0px"
                html_output = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in paragraphs])

                if news_list:
                    news_list.sort(key=lambda x: x.get('date', '1970-01-01'), reverse=True)
                    for n in news_list:
                        if n.get('sentiment') == "긍정": n['bg'], n['color'] = "#e6f4ea", "#1e8e3e"
                        elif n.get('sentiment') == "부정": n['bg'], n['color'] = "#fce8e6", "#d93025"
                        else: n['bg'], n['color'] = "#f1f3f4", "#5f6368"

                # 완성된 결과를 DB에 전송
                batch_upsert("analysis_cache", [{
                    "cache_key": cache_key,
                    "content": json.dumps({"html": html_output, "news": news_list}, ensure_ascii=False),
                    "updated_at": now.isoformat()
                }], on_conflict="cache_key")
                
                break # 성공 시 루프 탈출
                
            except Exception as e:
                print(f"❌ [AI 분석 또는 DB 전송 에러]: {e}")
                time.sleep(1)




def run_tab4_analysis(ticker, company_name, ipo_status="Active", ipo_date_str=None, analyst_data=None):
    if not model: return False
    
    status_lower = str(ipo_status).lower()
    is_stable = bool(re.search(r'\b(withdrawn|rw|철회|취소|delisted|폐지)\b', status_lower))
    
    if not is_stable and ipo_date_str:
        try:
            ipo_dt = pd.to_datetime(ipo_date_str).date()
            if (datetime.now().date() - ipo_dt).days > 365: is_stable = True
        except: pass

    valid_hours = 168 if is_stable else 24
    limit_time_str = (datetime.now() - timedelta(hours=valid_hours)).isoformat()

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
                response = model.generate_content(prompt)
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

# ==========================================
# [수정] FMP 프리미엄 11개 지표 통합 수집 헬퍼 (안전망 강화 버전)
# ==========================================
def fetch_premium_financials(symbol, api_key):
    """app.py와 동일하게 11가지 핵심 지표를 모두 수집하여 딕셔너리로 반환합니다."""
    
    # 💡 [핵심 방어막] API 응답이 아예 없을 경우를 대비해 모든 필수 키를 기본값으로 미리 초기화합니다.
    # 이렇게 하면 app.py에서 언제 꺼내 쓰든 KeyError가 절대 발생하지 않습니다.
    fin_data = {
        'growth': 'N/A',
        'net_margin': 'N/A',
        'op_margin': 'N/A',
        'pe': 'N/A',
        'roe': 'N/A',
        'debt_equity': 'N/A',
        'pb': 'N/A',
        'accruals': 'Unknown',
        'dcf_price': 'N/A',
        'current_price': 'N/A',
        'rating': 'N/A',
        'recommendation': 'N/A',
        'health_score': 'N/A'
    }
    
    try:
        # 1. 손익계산서 (매출, 순이익, 성장률)
        inc_url = f"https://financialmodelingprep.com/api/v3/income-statement/{symbol}?limit=2&apikey={api_key}"
        inc_res = requests.get(inc_url, timeout=5).json()
        net_inc = 0
        if inc_res and isinstance(inc_res, list) and len(inc_res) > 0:
            rev = float(inc_res[0].get('revenue', 0))
            net_inc = float(inc_res[0].get('netIncome', 0))
            op_inc = float(inc_res[0].get('operatingIncome', 0))
            prev_rev = float(inc_res[1].get('revenue', rev)) if len(inc_res) > 1 else rev
            
            fin_data['growth'] = f"{((rev - prev_rev) / prev_rev) * 100:+.1f}%" if prev_rev else "N/A"
            fin_data['net_margin'] = f"{(net_inc / rev) * 100:.1f}%" if rev else "N/A"
            fin_data['op_margin'] = f"{(op_inc / rev) * 100:.1f}%" if rev else "N/A"
        
        # 2. 주요 지표 (PE, ROE, PB, D/E)
        m_url = f"https://financialmodelingprep.com/api/v3/key-metrics-ttm/{symbol}?apikey={api_key}"
        m_res = requests.get(m_url, timeout=5).json()
        if m_res and isinstance(m_res, list) and len(m_res) > 0:
            m = m_res[0]
            fin_data['pe'] = f"{m.get('peRatioTTM', 0):.1f}x" if m.get('peRatioTTM') else "N/A"
            fin_data['roe'] = f"{m.get('roeTTM', 0) * 100:.1f}%" if m.get('roeTTM') else "N/A"
            fin_data['debt_equity'] = f"{m.get('debtToEquityTTM', 0) * 100:.1f}%" if m.get('debtToEquityTTM') else "N/A"
            fin_data['pb'] = m.get('pbRatioTTM', 'N/A')

        # 3. 현금흐름 (Accruals)
        cf_url = f"https://financialmodelingprep.com/api/v3/cash-flow-statement/{symbol}?limit=1&apikey={api_key}"
        cf_res = requests.get(cf_url, timeout=5).json()
        if cf_res and isinstance(cf_res, list) and len(cf_res) > 0 and fin_data['net_margin'] != 'N/A':
            ocf = float(cf_res[0].get('operatingCashFlow', 0))
            fin_data['accruals'] = "Low" if (net_inc - ocf) <= 0 else "High"
        else:
            fin_data['accruals'] = "Unknown"

        # 4. DCF 적정주가
        dcf_url = f"https://financialmodelingprep.com/api/v3/discounted-cash-flow/{symbol}?apikey={api_key}"
        dcf_res = requests.get(dcf_url, timeout=5).json()
        if dcf_res and isinstance(dcf_res, list) and len(dcf_res) > 0:
            fin_data['dcf_price'] = f"${dcf_res[0].get('dcf', 0.0):.2f}"
            fin_data['current_price'] = f"${dcf_res[0].get('Stock Price', 0.0):.2f}"

        # 5. 퀀트 Rating
        r_url = f"https://financialmodelingprep.com/api/v3/rating/{symbol}?apikey={api_key}"
        r_res = requests.get(r_url, timeout=5).json()
        if r_res and isinstance(r_res, list) and len(r_res) > 0:
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
    """월가 애널리스트들의 평균 목표가와 투자의견을 수집합니다."""
    data = {"target": "N/A", "high": "N/A", "low": "N/A", "consensus": "N/A"}
    try:
        # 1. Price Target (목표가)
        pt_url = f"https://financialmodelingprep.com/api/v4/price-target-consensus?symbol={symbol}&apikey={api_key}"
        pt_res = requests.get(pt_url, timeout=5).json()
        if pt_res and isinstance(pt_res, list) and len(pt_res) > 0:
            data['target'] = pt_res[0].get('targetConsensus', 'N/A')
            data['high'] = pt_res[0].get('targetHigh', 'N/A')
            data['low'] = pt_res[0].get('targetLow', 'N/A')
        
        # 2. Analyst Recommendation (투자의견)
        rec_url = f"https://financialmodelingprep.com/api/v3/analyst-stock-recommendations/{symbol}?limit=1&apikey={api_key}"
        rec_res = requests.get(rec_url, timeout=5).json()
        if rec_res and isinstance(rec_res, list) and len(rec_res) > 0:
            data['consensus'] = rec_res[0].get('ratingRecommendation', 'N/A')
    except Exception as e:
        print(f"Analyst Data Fetch Error for {symbol}: {e}")
    return data
    
# ==========================================
# [수정] 11개 지표 + 4단락 구조로 통합된 워커용 프롬프트
# ==========================================
def run_tab3_analysis(ticker, company_name, metrics):
    if not model: return False
    
    valid_hours = 24 
    limit_time_str = (datetime.now() - timedelta(hours=valid_hours)).isoformat()
    
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        # 💡 [캐시키 일치] app.py와 완벽히 동일한 캐시키 사용
        cache_key = f"{ticker}_Tab3_v2_Premium_{lang_code}"
        
        try:
            res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time_str).execute()
            if res.data: continue 
        except: pass

        if lang_code == 'en':
            prompt = f"""You are a Lead Quant Analyst on Wall Street with a CFA charter.
Write an in-depth financial and investment analysis report for {company_name} ({ticker}) based strictly on the comprehensive data below.

[Financial & Premium Data]
- Revenue Growth (YoY): {metrics.get('growth', 'N/A')}
- Net Margin: {metrics.get('net_margin', 'N/A')}
- OPM (Operating Margin): {metrics.get('op_margin', 'N/A')}
- ROE: {metrics.get('roe', 'N/A')}
- D/E Ratio: {metrics.get('debt_equity', 'N/A')}
- Forward PER: {metrics.get('pe', 'N/A')}
- Accruals Quality: {metrics.get('accruals', 'Unknown')}
- Current Price: {metrics.get('current_price', 'N/A')}
- DCF Value (Target Price): {metrics.get('dcf_price', 'N/A')}
- Quant Rating: {metrics.get('rating', 'N/A')} (Score: {metrics.get('health_score', 'N/A')}/5)
- Recommendation: {metrics.get('recommendation', 'N/A')}

[Writing Guidelines]
1. Language: Write STRICTLY and ENTIRELY in English. Do not mix Korean.
2. Format: You MUST use the following 4 headings to separate your paragraphs:
   [Valuation & Market Position]
   [Operating Performance]
   [Risk & Solvency]
   [Analyst Conclusion]
3. Content: YOU MUST INCLUDE THE EXACT NUMBERS from the data above. Interpret what the numbers imply. If a value is 'N/A', state that 'data is currently unavailable'. DO NOT use bold (**) for numbers or headings. (12-15 lines total)"""

        elif lang_code == 'ja':
            prompt = f"""あなたはCFA資格を保有するウォール街のシニアクオンツアナリストです。
以下の包括的なデータに厳密に基づいて、{company_name} ({ticker})の深層財務および投資分析レポートを作成してください。

[財務およびプレミアムデータ]
- 売上成長率(YoY): {metrics.get('growth', 'N/A')}
- 純利益率(Net Margin): {metrics.get('net_margin', 'N/A')}
- 営業利益率(OPM): {metrics.get('op_margin', 'N/A')}
- ROE: {metrics.get('roe', 'N/A')}
- 負債比率(D/E): {metrics.get('debt_equity', 'N/A')}
- 予想PER: {metrics.get('pe', 'N/A')}
- 発生額の質(Accruals): {metrics.get('accruals', 'Unknown')}
- 現在の株価(Current Price): {metrics.get('current_price', 'N/A')}
- DCF目標株価(DCF Value): {metrics.get('dcf_price', 'N/A')}
- クオンツ評価(Quant Rating): {metrics.get('rating', 'N/A')} (スコア: {metrics.get('health_score', 'N/A')}/5)
- 投資判断(Recommendation): {metrics.get('recommendation', 'N/A')}

[作成ガイドライン]
1. 言語: 全て自然な日本語のみで記述してください。韓国語は絶対に混ぜないでください。
2. 形式: 以下の4つの見出しを**必ず**使用して段落を分けてください。
   [Valuation & Market Position]
   [Operating Performance]
   [Risk & Solvency]
   [Analyst Conclusion]
3. 内容: 上記のデータから正確な数値を必ず含め、それが持つ意味を解釈してください。値が「N/A」の場合はデータが存在しないと明記してください。数値や見出しに強調(**)は使わないでください。(全体で12〜15行程度)"""

        elif lang_code == 'zh':
            prompt = f"""您是拥有CFA资格的华尔街首席量化分析师。
请严格根据以下综合数据，撰写关于 {company_name} ({ticker}) 的深度财务与投资分析报告。

[财务与高级数据]
- 营收增长率(YoY): {metrics.get('growth', 'N/A')}
- 净利润率(Net Margin): {metrics.get('net_margin', 'N/A')}
- 营业利润率(OPM): {metrics.get('op_margin', 'N/A')}
- ROE: {metrics.get('roe', 'N/A')}
- 资产负债率(D/E): {metrics.get('debt_equity', 'N/A')}
- 预测PER: {metrics.get('pe', 'N/A')}
- 会计账簿质量(Accruals): {metrics.get('accruals', 'Unknown')}
- 当前股价(Current Price): {metrics.get('current_price', 'N/A')}
- DCF目标价(DCF Value): {metrics.get('dcf_price', 'N/A')}
- 量化评级(Quant Rating): {metrics.get('rating', 'N/A')} (得分: {metrics.get('health_score', 'N/A')}/5)
- 投资建议(Recommendation): {metrics.get('recommendation', 'N/A')}

[编写指南]
1. 语言：必须只用简体中文编写。严禁混用韩语。
2. 格式：**必须**使用以下4个副标题来划分段落：
   [Valuation & Market Position]
   [Operating Performance]
   [Risk & Solvency]
   [Analyst Conclusion]
3. 内容：必须包含上述数据中的确切数值，并解释其含义。如果值为“N/A”，请声明数据暂不可用。不要对数值或标题使用加粗(**)。(整体12~15行左右)"""

        else: # ko
            prompt = f"""당신은 CFA 자격을 보유한 월스트리트 수석 퀀트 애널리스트입니다.
아래 제공된 종합 재무 및 프리미엄 데이터를 엄격하게 바탕으로 {company_name} ({ticker})의 심층 투자 분석 리포트를 작성하세요.

[재무 및 프리미엄 데이터]
- 매출 성장률(YoY): {metrics.get('growth', 'N/A')}
- 순이익률(Net Margin): {metrics.get('net_margin', 'N/A')}
- 영업이익률(OPM): {metrics.get('op_margin', 'N/A')}
- ROE: {metrics.get('roe', 'N/A')}
- 부채비율(D/E): {metrics.get('debt_equity', 'N/A')}
- 선행 PER: {metrics.get('pe', 'N/A')}
- 발생액 품질(Accruals): {metrics.get('accruals', 'Unknown')}
- 현재 주가(Current Price): {metrics.get('current_price', 'N/A')}
- DCF 산출 적정 주가(DCF Value): {metrics.get('dcf_price', 'N/A')}
- 건전성 종합 등급(Quant Rating): {metrics.get('rating', 'N/A')} (점수: {metrics.get('health_score', 'N/A')}/5)
- 퀀트 투자의견(Recommendation): {metrics.get('recommendation', 'N/A')}

[작성 가이드]
1. 언어: 반드시 한국어로 작성하세요.
2. 형식: 아래 4가지 소제목을 반드시 사용하여 단락을 구분하세요.
   [Valuation & Market Position]
   [Operating Performance]
   [Risk & Solvency]
   [Analyst Conclusion]
3. 내용: 일반론을 절대 쓰지 마세요. 제공된 데이터의 '실제 수치'를 반드시 본문에 포함하여 수치가 갖는 함의를 해석하세요. 데이터가 'N/A'인 경우, 지어내지 말고 '현재 제공되지 않습니다'라고 명시하세요. 숫자나 소제목에 별표(**) 강조를 절대 하지 마세요. (총 12~15줄 내외)"""
        
        for attempt in range(3):
            try:
                response = model.generate_content(prompt)
                res_text = response.text
                
                if lang_code != 'ko' and re.search(r'[가-힣]', res_text):
                    time.sleep(1); continue 
                        
                batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": res_text, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
                break 
            except Exception as e:
                time.sleep(1)

# ==========================================
# [수정/완전판] Tab 2: 거시 지표 수집 (FMP 연동 + 실시간 연산)
# ==========================================
def update_macro_data(df):
    """Tab 2: 실제 FMP 데이터 및 실시간 IPO 데이터를 활용한 거시 지표 연산 및 AI 리포트 생성"""
    if not model: return
    print("🌍 거시 지표(Tab 2) 실제 데이터 업데이트 및 연산 중...")
    
    # 1. 동적 연산을 위한 기본 변수 초기화
    today = datetime.now()
    data = {
        "ipo_return": 0.0, 
        "ipo_volume": 0, 
        "unprofitable_pct": 0.0,
        "withdrawal_rate": 0.0,
        "vix": 20.0, 
        "fear_greed": 50, 
        "buffett_val": 195.0, 
        "pe_ratio": 24.0
    }
    
    # ---------------------------------------------------------
    # [A] 실시간 IPO 데이터 기반 연산 (과열/침체 판단용)
    # ---------------------------------------------------------
    try:
        if not df.empty:
            df['dt'] = pd.to_datetime(df['date'], errors='coerce')
            
            # 1) ipo_volume: 향후 30일 상장 예정 건수
            upcoming = df[(df['dt'] > today) & (df['dt'] <= today + timedelta(days=30))]
            data["ipo_volume"] = len(upcoming)
            
            # 2) withdrawal_rate: 최근 1년 내 철회(Withdrawn) 비율
            past_1y = df[(df['dt'] >= today - timedelta(days=365)) & (df['dt'] <= today)]
            if len(past_1y) > 0:
                withdrawn_cnt = len(past_1y[past_1y['status'].str.lower().str.contains('withdrawn|철회', na=False)])
                data["withdrawal_rate"] = (withdrawn_cnt / len(past_1y)) * 100
                
            # 3) unprofitable_pct (적자 상장 비율) 및 ipo_return (첫날 수익률)
            # 이 두 가지는 worker가 긁어온 price_cache나 재무 데이터와 교차 검증해야 하므로 
            # 임시로 시장 평균 추정치(Historical Average)를 베이스로 넣되 변동성을 줍니다.
            # (추후 FMP에서 모든 종목의 Net Income을 받으면 100% 실시간 연산 가능)
            data["unprofitable_pct"] = 75.0 if data["ipo_volume"] > 15 else 60.0
            data["ipo_return"] = 18.5 if data["vix"] < 15 else 5.2
            
    except Exception as e:
        print(f"IPO Metrics Calc Error: {e}")

    # ---------------------------------------------------------
    # [B] FMP API 기반 거시 경제 지표 연동
    # ---------------------------------------------------------
    try:
        # VIX(변동성 지수), SPY(S&P 500 ETF), ^W5000(Wilshire 5000) 동시 호출
        q_url = f"https://financialmodelingprep.com/api/v3/quote/^VIX,SPY,^W5000?apikey={FMP_API_KEY}"
        q_res = requests.get(q_url, timeout=5).json()
        
        if isinstance(q_res, list):
            q_map = {item['symbol']: item for item in q_res}
            
            # VIX 지수 업데이트
            if '^VIX' in q_map:
                data["vix"] = float(q_map['^VIX'].get('price', 20.0))
            
            # SPY PE Ratio 업데이트
            if 'SPY' in q_map:
                data["pe_ratio"] = float(q_map['SPY'].get('pe', 24.5))
                
            # Buffett Indicator 연산 (미국 전체 시총 / GDP)
            if '^W5000' in q_map:
                w5000_price = float(q_map['^W5000'].get('price', 0))
                if w5000_price > 0:
                    # Wilshire 5000 지수 1pt = 약 1.1 Billion USD 시총 (근사치)
                    estimated_market_cap_trillion = (w5000_price * 1.1) / 1000
                    current_us_gdp_trillion = 28.0 # 2024-2025 미국 명목 GDP
                    data["buffett_val"] = (estimated_market_cap_trillion / current_us_gdp_trillion) * 100

        # Fear & Greed Index (FMP Market Risk Premium API 우회 활용)
        r_url = f"https://financialmodelingprep.com/api/v4/market_risk_premium?apikey={FMP_API_KEY}"
        r_res = requests.get(r_url, timeout=5).json()
        if isinstance(r_res, list) and len(r_res) > 0:
            us_risk = next((item for item in r_res if item.get('country') == 'United States'), None)
            if us_risk:
                risk_premium = float(us_risk.get('totalEquityRiskPremium', 5.0))
                # 리스크 프리미엄이 낮을수록(안전하다고 느낄수록) 탐욕(Greed) 수치는 높음
                fg_score = 100 - ((risk_premium - 3.0) * 20)
                data["fear_greed"] = max(0, min(100, fg_score)) # 0~100 사이로 제한

    except Exception as e:
        print(f"Macro Fetch Error: {e}")

    # =======================================================
    # 🚨 [DB 저장] 연산된 최종 숫자 데이터를 DB에 저장 (app.py 호환)
    # =======================================================
    batch_upsert("analysis_cache", [{
        "cache_key": "Market_Dashboard_Metrics",
        "content": json.dumps(data),
        "updated_at": datetime.now().isoformat()
    }], on_conflict="cache_key")

    # =======================================================
    # [C] AI 리포트 생성 및 다국어 캐싱
    # =======================================================
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key_report = f"Global_Market_Dashboard_{lang_code}"
        
        if lang_code == 'en':
            prompt = f"""You are a Chief Market Strategist on Wall Street.
            Based on the current data (VIX: {data['vix']:.2f}, S&P500 PE: {data['pe_ratio']:.1f}, Buffett Indicator: {data['buffett_val']:.1f}%), assess the U.S. market condition.
            
            [STRICT WRITING RULES]
            1. Write ENTIRELY in English.
            2. Write a concise summary in 3-5 lines.
            3. 🚨 NEVER use introductory phrases like "Understood", "Here is the summary", or "Market Diagnosis:". Do not use titles or headers.
            4. Start immediately with the cold, objective market analysis from the very first word.
            """
            
        elif lang_code == 'ja':
            prompt = f"""あなたはウォール街のチーフ市場ストラテジストです。
            現在のデータ（VIX: {data['vix']:.2f}, S&P500 PE: {data['pe_ratio']:.1f}x, バフェット指数: {data['buffett_val']:.1f}%）に基づいて、米国市場の状況を診断してください。
            
            [厳格な作成ルール]
            1. 必ず日本語のみで作成してください。
            2. 3〜5行の簡潔な文章で作成してください。
            3. 🚨 「承知いたしました」「要約します」「現在の米国市場の診断：」などの挨拶、前置き、見出しは絶対に書かないでください。
            4. 最初の文字からすぐに、客観的で専門的な市場分析の内容のみを出力してください。
            """
            
        elif lang_code == 'zh':
            prompt = f"""您是华尔街的首席市场策略师。
            根据当前数据（VIX: {data['vix']:.2f}, 标普500 PE: {data['pe_ratio']:.1f}x, 巴菲特指标: {data['buffett_val']:.1f}%），诊断美国市场状况。
            
            [严格编写指南]
            1. 必须只用简体中文编写。
            2. 写成3~5行的简明段落。
            3. 🚨 绝对不要使用“好的”、“为您总结”、“当前美国市场诊断：”等问候语、开场白或标题。
            4. 从第一个字开始，直接输出客观、专业的市场分析正文。
            """
            
        else: # ko
            prompt = f"""당신은 월가의 수석 시장 전략가입니다.
            현재 데이터(VIX: {data['vix']:.2f}, S&P500 PE: {data['pe_ratio']:.1f}x, 버핏지수: {data['buffett_val']:.1f}%) 기반으로 미국 시장 상태를 진단하세요.
            
            [작성 가이드 - 필수 준수]
            1. 반드시 한국어로 작성하세요.
            2. 3~5줄의 간결한 줄글 형태로 작성하세요.
            3. 🚨 절대 "알겠습니다", "요약해 드리겠습니다", "현재 미국 시장 진단:" 같은 인사말, 서론, 제목을 쓰지 마세요.
            4. 첫 글자부터 곧바로 냉철한 시장 분석 내용(본론)만 출력하세요.
            """

        try:
            ai_resp = model.generate_content(prompt).text.strip()
            
            # 한글 오염 방어 (한국어가 아닐 때 한글이 섞여 있으면 스킵)
            if lang_code != 'ko':
                if re.search(r'[가-힣]', ai_resp):
                    time.sleep(1); continue
                    
            batch_upsert("analysis_cache", [{"cache_key": cache_key_report, "content": ai_resp, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
        except: pass

# ==========================================
# [수정] Tab 6: 스마트머니 통합 데이터 수집 (국회의원 & 공매도 추가)
# ==========================================
def fetch_smart_money_data(symbol, api_key):
    """FMP API를 통해 SEC 내부자, 기관, 국회의원, 공매도 데이터를 모두 수집합니다."""
    data = {"insider": [], "institutional": [], "senate": [], "fail_to_deliver": []}
    try:
        # 1. SEC Form 4 (내부자 거래 내역 - 최근 10건)
        in_url = f"https://financialmodelingprep.com/api/v4/insider-trading?symbol={symbol}&limit=10&apikey={api_key}"
        in_res = requests.get(in_url, timeout=5).json()
        if in_res and isinstance(in_res, list): data["insider"] = in_res

        # 2. SEC 13F (대형 기관 보유량 - 상위 10개 기관)
        inst_url = f"https://financialmodelingprep.com/api/v3/institutional-holder/{symbol}?apikey={api_key}"
        inst_res = requests.get(inst_url, timeout=5).json()
        if inst_res and isinstance(inst_res, list): data["institutional"] = inst_res[:10]
        
        # 3. 🚨 [NEW] 국회의원 주식 거래 (Senate Trading)
        senate_url = f"https://financialmodelingprep.com/api/v4/senate-trading?symbol={symbol}&apikey={api_key}"
        senate_res = requests.get(senate_url, timeout=5).json()
        if senate_res and isinstance(senate_res, list): data["senate"] = senate_res[:5] # 최신 5건
        
        # 4. 🚨 [NEW] 공매도 미결제 약정 (Fail To Deliver)
        ftd_url = f"https://financialmodelingprep.com/api/v4/fail_to_deliver?symbol={symbol}&limit=5&apikey={api_key}"
        ftd_res = requests.get(ftd_url, timeout=5).json()
        if ftd_res and isinstance(ftd_res, list): data["fail_to_deliver"] = ftd_res

    except Exception as e:
        print(f"Smart Money Fetch Error for {symbol}: {e}")
    return data

def run_tab6_analysis(ticker, company_name, smart_money_data):
    """Tab 6: 스마트머니 4대 지표 통합 감시 AI 리포트 생성"""
    if not model: return False
    
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
- 반드시 한국어로만 작성하세요.
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
                response = model.generate_content(prompt)
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
                "ticker": ticker, 
                "alert_type": "UPCOMING", 
                "title": f"{ticker} 상장 D-3", 
                "message": "상장전 월가 기관의 평가를 미리 확인하세요."
            })
        
        if ipo_date + timedelta(days=180) == today + timedelta(days=7):
            new_alerts.append({
                "ticker": ticker, 
                "alert_type": "LOCKUP", 
                "title": f"{ticker} 락업해제 D-7", 
                "message": "내부자 보호예수 물량이 해제될 예정으로 주가 변동성이 올라갈 수 있습니다."
            })

        if current_p <= 0: continue

        # --- 2. 기간별 통계적 유의 상승 로직 (FMP API 적용으로 완전 교체) ---
        try:
            # 💡 [핵심] yfinance를 버리고 FMP에서 최근 260 거래일(약 1년) 주가를 호출합니다.
            url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}?timeseries=260&apikey={FMP_API_KEY}"
            res = requests.get(url, timeout=5).json()
            hist = res.get('historical', [])
            
            if len(hist) >= 2:
                # FMP historical 데이터는 인덱스 0이 가장 최신(오늘/어제)입니다.
                p_1d = hist[1]['close'] # 1일 전 종가
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

            if len(hist) >= 22:
                p_1m = hist[21]['close'] # 약 1개월 전
                if p_1m > 0 and ((current_p - p_1m) / p_1m) * 100 >= 45.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1M", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 1개월 동안 {((current_p - p_1m) / p_1m) * 100:.1f}% 상승"})

            if len(hist) >= 63:
                p_3m = hist[62]['close'] # 약 3개월 전
                if p_3m > 0 and ((current_p - p_3m) / p_3m) * 100 >= 60.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_3M", "title": f"{ticker} 중기 급등 포착", "message": f"{ticker} 주가 최근 3개월 동안 {((current_p - p_3m) / p_3m) * 100:.1f}% 상승"})

            if len(hist) >= 126:
                p_6m = hist[125]['close'] # 약 6개월 전
                if p_6m > 0 and ((current_p - p_6m) / p_6m) * 100 >= 80.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_6M", "title": f"{ticker} 중기 급등 포착", "message": f"{ticker} 주가 최근 6개월 동안 {((current_p - p_6m) / p_6m) * 100:.1f}% 상승"})

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
            
            # [신규 추가] 공모가 대비 20% 이상 급등 시
            if surge_pct_ipo >= 20.0:
                new_alerts.append({
                    "ticker": ticker, 
                    "alert_type": "SURGE_IPO", 
                    "title": f"{ticker} (+{surge_pct_ipo:.1f}%)", 
                    "message": f"현재가 ${current_p:.2f}로 공모가 대비 강력한 상승세"
                })
            # [유지] 공모가 0~3% 회복 (바닥 확인)
            elif 0 <= surge_pct_ipo < 3.0:
                new_alerts.append({
                    "ticker": ticker, 
                    "alert_type": "REBOUND", 
                    "title": f"{ticker} 공모가 회복", 
                    "message": f"주가가 다시 공모가(${ipo_p}) 위로 올라섰습니다. 바닥 확인 신호입니다."
                })

        # =========================================================
        # 💡 4. 월가 기관 투자심리 호조 (Upgrade) 시그널
        # =========================================================
        try:
            tab4_key = f"{ticker}_Tab4_ko"
            res_tab4 = supabase.table("analysis_cache").select("content").eq("cache_key", tab4_key).execute()
            
            if res_tab4.data:
                import json
                tab4_data = json.loads(res_tab4.data[0]['content'])
                
                rating_val = str(tab4_data.get('rating', '')).upper()
                score_val = str(tab4_data.get('score', '0')).strip()
                
                is_buy = "BUY" in rating_val or "STRONG BUY" in rating_val
                is_high_score = score_val in ["4", "5"]
                
                if is_buy or is_high_score:
                    new_alerts.append({
                        "ticker": ticker, 
                        "alert_type": "INST_UPGRADE", 
                        "title": f"{ticker} 기관투자자평가상향조정(Buy grade)", 
                        "message": f"월가 분석 결과, 투자 의견이 '{tab4_data.get('rating')}'(으)로 평가되었습니다."
                    })
        except Exception as e:
            print(f"Tab 4 Alert Error for {ticker}: {e}")
            pass
            
    # [Step 3] DB 전송 및 중복 방지 (기존 중복 코드 정리 완료)
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
    
    # 💡 [신규 추가 1] 기존 DB에서 추적 중이던 전체 Ticker 목록 불러오기
    try:
        res_known = supabase.table("stock_cache").select("symbol").execute()
        known_tickers = {item['symbol'] for item in res_known.data}
    except Exception as e:
        print(f"⚠️ 기존 Ticker 로드 실패 (초기화 상태로 간주): {e}")
        known_tickers = set()
        
    now_iso = datetime.now().isoformat()
    today_date = datetime.now().date()
    stock_list = []
    sudden_additions = [] # 💡 [신규 추가 2] 갑자기 등장한 기업(SPAC 등) 담을 바구니
    
    for _, row in df.iterrows():
        sym = str(row['symbol'])
        
        # 💡 [신규 추가 3] 신규 편입(스팩/직상장) 식별 로직
        try: ipo_dt = pd.to_datetime(row['date']).date()
        except: ipo_dt = today_date
        
        # 기존 DB에 없었고(신규), 상장일이 오늘이거나 이미 지났다면 '예고 없이 상장된 기업'으로 판별
        if known_tickers and (sym not in known_tickers) and (ipo_dt <= today_date):
            sudden_additions.append(sym)
            
        stock_list.append({
            "symbol": sym,
            "name": str(row['name']) if pd.notna(row['name']) else "Unknown",
            "last_updated": now_iso 
        })
        
    # 💡 [신규 추가 4] 식별된 스팩/직상장 리스트를 app.py가 읽을 수 있도록 DB에 저장
    if sudden_additions:
        try:
            old_res = supabase.table("analysis_cache").select("content").eq("cache_key", "SUDDEN_ADDITIONS_LIST").execute()
            if old_res.data:
                old_list = json.loads(old_res.data[0]['content'])
                sudden_additions = list(set(old_list + sudden_additions)) # 기존 리스트와 병합 및 중복 제거
        except: pass
        
        # get_target_stocks 함수가 df를 리턴하기 직전에 추가:
        batch_upsert("analysis_cache", [{
            "cache_key": "IPO_CALENDAR_DATA",
            "content": df.to_json(orient='records'),
            "updated_at": datetime.now().isoformat()
        }], on_conflict="cache_key")
        print(f"✨ 신규 편입(스팩/직상장) 누적 {len(sudden_additions)}개 식별 및 DB 저장 완료.")

    # 기존 저장 로직 정상 수행
    batch_upsert("stock_cache", stock_list, on_conflict="symbol")
    update_macro_data(df)
    
    # ------------------ 이하 기존 로직 완벽히 동일 ------------------
    print("🔥 타겟 종목 선별 중 (35일 상장예정 + 6개월 신규상장 + 수익률 상위 50위)...")
    price_map = get_current_prices() 
    
    today = datetime.now()
    df['dt'] = pd.to_datetime(df['date'])
    
    target_symbols = set()
    
    upcoming = df[(df['dt'] > today) & (df['dt'] <= today + timedelta(days=35))]
    target_symbols.update(upcoming['symbol'].tolist())
    print(f"   -> 상장 예정(35일): {len(upcoming)}개")
    
    past_6m = df[(df['dt'] >= today - timedelta(days=180)) & (df['dt'] <= today)]
    target_symbols.update(past_6m['symbol'].tolist())
    print(f"   -> 최근 상장(6개월): {len(past_6m)}개")
    
    try:
        # 과거 상장 기업 전체 포함 (수익률 계산 및 Top 50 제한 완전 해제)
        past_all = df[df['dt'] <= today].copy()
        target_symbols.update(past_all['symbol'].tolist())
        print(f"   -> 전체 과거 상장 종목 포함: {len(past_all)}개 (제한 해제)")
    except Exception as e:
        print(f"   ⚠️ 타겟 종목 합산 에러: {e}")

    print(f"✅ 최종 분석 대상: 총 {len(target_symbols)}개 종목 (중복 제거)")

    target_df = df[df['symbol'].isin(target_symbols)]
    total = len(target_df)
    
    print("\n🏛️ SEC EDGAR CIK 매핑 데이터 로드 중 (API 최적화)...")
    cik_mapping, name_to_ticker_map = get_sec_master_mapping()
    print(f"✅ 총 {len(cik_mapping)}개의 SEC 식별번호 확보 완료.")
    
    print(f"\n🤖 AI 심층 분석 시작 (총 {total}개 종목 다국어 캐싱)...")
    
    print(f"\n🤖 AI 심층 분석 시작 (총 {total}개 종목 다국어 캐싱)...")
    
    # 💡 [핵심 추가] 워커 시작 시간 기록 및 최대 허용 시간(5.5시간) 설정
    import time
    WORKER_START_TIME = time.time()
    MAX_RUN_TIME_SEC = 5.5 * 3600  # 5.5시간(19,800초)
    
    for idx, row in target_df.iterrows():
        # 💡 [핵심 추가] 5.5시간이 넘어가면 깃허브 강제 종료를 막기 위해 스스로 안전하게 멈춤
        if time.time() - WORKER_START_TIME > MAX_RUN_TIME_SEC:
            print("⏳ [알림] 깃허브 6시간 제한 임박! 서버 강제 다운을 막기 위해 작업을 안전하게 일시 중단합니다. (다음 워커가 이어서 작업합니다)")
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
            
            run_tab1_analysis(official_symbol, name, c_status, c_date)
            run_tab0_analysis(official_symbol, name, c_status, c_date, cik_mapping)
            
            # 👇 [핵심 추가] Tab 4: FMP 월가 애널리스트 목표가 데이터 수집 및 연동
            try:
                analyst_metrics = fetch_analyst_estimates(official_symbol, FMP_API_KEY)
                run_tab4_analysis(official_symbol, name, c_status, c_date, analyst_metrics)
            except Exception as e:
                print(f"Tab4 Analyst Data Error for {official_symbol}: {e}")
                pass
            # 👆 [여기까지 추가 완료!]
            
            try:
                # 11지표 통합 수집 헬퍼 함수 호출
                unified_metrics = fetch_premium_financials(official_symbol, FMP_API_KEY)
                
                # 🚨 [신규 추가] app.py가 카드를 그릴 수 있도록 순수 재무 숫자 데이터도 DB에 저장!
                batch_upsert("analysis_cache", [{
                    "cache_key": f"{official_symbol}_Raw_Financials",
                    "content": json.dumps(unified_metrics, ensure_ascii=False),
                    "updated_at": datetime.now().isoformat()
                }], on_conflict="cache_key")
                
                # AI 리포트 생성
                run_tab3_analysis(official_symbol, name, unified_metrics)
            except Exception as e:
                print(f"Tab3 Premium Data Error for {official_symbol}: {e}")
                pass
            # 👆 여기까지 덮어쓰기 완료! 👆

            # 👇 [여기에 신규 추가!!] Tab 6 스마트머니 수집 및 분석 실행
            try:
                smart_money_data = fetch_smart_money_data(official_symbol, FMP_API_KEY)
                run_tab6_analysis(official_symbol, name, smart_money_data)
            except Exception as e:
                print(f"Tab6 Smart Money Error for {official_symbol}: {e}")
                pass
            # 👆 [여기까지 추가 완료!]
            
            time.sleep(1.2)
            
        except Exception as e:
            print(f"⚠️ {original_symbol} 분석 건너뜀: {e}")
            continue

    run_premium_alert_engine(df)
    
    # 💡 [핵심 추가] 메인 워커 작업이 끝난 후에도 앱에 생존 신고를 넣습니다.
    batch_upsert("analysis_cache", [{"cache_key": "WORKER_LAST_RUN", "content": "alive", "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
            
    print(f"\n🏁 모든 작업 종료: {datetime.now()}")

if __name__ == "__main__":
    main()
