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
        # 💡 아래 줄들이 try: 보다 '4칸' 안으로 들여쓰기 되어야 합니다.
        model = genai.GenerativeModel(
            model_name='gemini-2.0-flash', 
            tools=[{'google_search': {}}] 
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

    # 💡 [핵심] 12가지 문서의 세부 지시사항 - 수치 데이터 강제 명시 로직 반영
    def get_localized_meta(lang, doc_type):
        meta_dict = {
            "ko": {
                "S-1": {"p": "Risk Factors, Use of Proceeds, MD&A", "s": "1문단: 발견된 가장 중요한 투자 포인트\n2문단: 실질적 성장 가능성과 재무적 의미\n3문단: 핵심 리스크 1가지와 그 파급 효과 및 대응책"},
                "S-1/A": {"p": "Pricing Terms, Dilution, Changes", "s": "1문단: 이전 S-1 대비 변경된 핵심 사항\n2문단: 제시된 공모가 범위의 적정성 및 수요예측 분위기\n3문단: 기존 주주 가치 희석 정도와 투자 매력도"},
                "F-1": {"p": "Foreign Risk, Accounting (GAAP), ADS Structure", "s": "1문단: 기업이 글로벌 시장에서 가진 독보적인 경쟁 우위\n2문단: 환율, 정치, 회계 등 해외 기업 특유의 리스크\n3문단: 미국 예탁 증서(ADS) 구조가 주주 권리에 미치는 영향"},
                "FWP": {"p": "Graphics, Strategy, Highlights", "s": "1문단: 경영진이 로드쇼에서 강조하는 미래 성장 비전\n2문단: 경쟁사 대비 기술적/사업적 차별화 포인트\n3문단: 자료 톤앤매너로 유추할 수 있는 시장 공략 의지"},
                "424B4": {"p": "Final Price, Underwriting, IPO Outcome", "s": "1문단: 확정 공모가의 위치와 시장 수요 해석\n2문단: 확정된 조달 자금의 투입 우선순위\n3문단: 주관사단 및 배정 물량 바탕 상장 초기 유통물량 예측"},
                "RW": {"p": "Withdrawal Reason, Market Condition", "s": "1문단: 상장 철회(Withdrawal) 결정적 사유 및 배경\n2문단: 상장 철회가 기업 재무 및 기존 투자자에게 미치는 영향\n3문단: 향후 재상장 또는 M&A 등 향후 계획"},
                "Form 25": {"p": "Delisting Reason, M&A, Shareholder Impact", "s": "1문단: 상장 폐지(Delisting)의 정확한 사유\n2문단: 상장 폐지 후 기존 주주의 권리 및 주식 처리 방안\n3문단: 장외시장(OTC) 거래 가능성 및 향후 기업 상태"},
                "10-K": {"p": "Annual Revenue, Operating Income, Net Income, Growth Rate", "s": "1문단: [연간 성과] 지난 1년간의 **실제 매출액과 영업이익 수치($)** 및 전년비 성장률 명시\n2문단: [사업 확장] 경영진이 강조한 핵심 사업부별 **실적 데이터**와 비즈니스 모델 변화\n3문단: [리스크] 새롭게 부각된 위험 요소가 향후 **재무 수치에 미칠 수 있는 구체적 영향**"},
                "10-Q": {"p": "Quarterly Revenue, Net Income, Cash Balances", "s": "1문단: [분기 실적] 이번 분기 **실제 매출($) 및 순이익($)** 성과와 전년 동기 대비 증감률 명시\n2문단: [현금 현황] 현재 보유한 **현금 및 현금성 자산의 실제 수치**와 단기 유동성 분석\n3문단: [가이던스] 경영진이 제시한 다음 분기 예상 수치 및 성장의 구체적 근거"},
                "BS": {"p": "Total Assets, Total Liabilities, Cash & Equivalents, Total Debt, Equity", "s": "1문단: [자산 구조] 현금성 자산을 포함한 유동 자산과 비유동 자산의 **실제 수치(USD)**를 명시\n2문단: [부채와 자본] 총부채와 자기자본의 **실제 금액($)**을 바탕으로 부채비율을 분석\n3문단: [결론] 위 수치를 근거로 한 기업의 재무 건전성 및 지급 능력 최종 평가"},
                "IS": {"p": "Revenue, Gross Margin, Operating Income, Net Income, EPS", "s": "1문단: [매출 성과] 서류에 기재된 **실제 매출액(Revenue) 수치와 성장률(%)**을 반드시 포함\n2문단: [수익성] 영업이익(Operating Income)과 순이익(Net Income)의 **실제 달러 수치** 명시\n3문단: [수익성 품질] 주당순이익(EPS)과 일회성 비용 유무를 수치 기반으로 요약"},
                "CF": {"p": "Operating CF, Investing CF(CAPEX), Financing CF, FCF", "s": "1문단: [영업현금흐름] 실제 영업활동 현금흐름 **수치($)**를 명시하고 현금 창출력 평가\n2문단: [투자 및 CAPEX] **자본적 지출(CAPEX)의 실제 금액**과 투자 방향성 분석\n3문단: [현금 생존력] **잉여현금흐름(FCF)을 직접 계산(영업CF-CAPEX)**하여 수치로 명시"}
            },
            "en": {
                "S-1": {"p": "Risk Factors, Use of Proceeds, MD&A", "s": "Para 1: Key investment highlights found in the filing.\nPara 2: Strategic growth potential and financial implications.\nPara 3: Critical risk factor and its impact on shareholders."},
                "10-K": {"p": "Full-year Revenue, Operating Income, Segment Data", "s": "Para 1: [Annual Performance] State **actual Revenue and Operating Income ($)** with YoY growth.\nPara 2: [Operations] Analyze core business unit **performance data** and strategic shifts.\nPara 3: [Risk Outlook] Specific **numerical impact** of new risks on long-term goals."},
                "10-Q": {"p": "Quarterly Revenue, Net Income, Cash Reserves", "s": "Para 1: [Quarterly Results] State **actual Revenue and Net Income ($)** with YoY comparison.\nPara 2: [Liquidity] List **actual cash and cash equivalents** and assess solvency.\nPara 3: [Guidance] Specific numerical guidance for the next quarter and its drivers."},
                "BS": {"p": "Assets, Liabilities, Cash, Debt, Equity", "s": "Para 1: [Asset Structure] List **actual USD values** for current and non-current assets.\nPara 2: [Debt & Equity] Use **actual debt and equity figures ($)** to analyze stability.\nPara 3: [Solvency] Final evaluation based purely on the reported financial numbers."},
                "IS": {"p": "Revenue, Gross Margin, Net Income, EPS", "s": "Para 1: [Top-line] Explicitly include **actual Revenue and YoY growth (%)**.\nPara 2: [Profitability] Analyze Operating/Net Income using **actual dollar amounts**.\nPara 3: [Earnings Quality] Summarize EPS and profit quality using specific financial data."},
                "CF": {"p": "Operating CF, CAPEX, FCF, Financing", "s": "Para 1: [Operating] State **actual cash flow from operations ($)** and efficiency.\nPara 2: [Investing] Analyze **actual CAPEX spending** and direction using dollar amounts.\nPara 3: [Cash Runway] **Calculate and state FCF (OCF - CAPEX)** using reported figures."}
            },
            "ja": {
                "S-1": {"p": "リスク要因, 資金使途, MD&A", "s": "第1段落：この文書で確認できる最も重要な投資ポイント\n第2段落：成長可能性と財務的な意味合い\n第3段落：核心的なリスクとその対応策"},
                "10-K": {"p": "通期売上高, 営業利益, セグメント実績", "s": "第1段落：[通期実績] 過去1年間の**実際の売上高と営業利益の数値($)**および成長率を明記\n第2段落：[事業分析] 経営陣が強調する事業部別の**実績データ**とモデルの変化\n第3段落：[将来リスク] リスク要因が今後の**財務指標に与える具体的な影響**"},
                "10-Q": {"p": "四半期売上, 純利益, 現金残高", "s": "第1段落：[四半期実績] 当四반期の**実際の売上($)と純利益($)**および前年比を明記\n第2段落：[流動性] 現在の**現金および現金同等物の数値**を明記し、支払能力を診断\n第3段落：[ガイダンス] 次四半期の予想数値と成長の具体的な根拠"},
                "BS": {"p": "資産合計, 負債合計, 現金等価物, 自己資本", "s": "第1段落：[資産構造] 現金同等物を含む流動・非流動資産の**実際の数値(USD)**を明記\n第2段落：[負債と資本] 総負債と自己資本の**実際の金額($)**に基づき分析\n第3段落：[結論] 数値に裏打ちされた短期支払能力と長期的な健全性の評価"},
                "IS": {"p": "売上高, 利益率, 営業利益, 純利益, EPS", "s": "第1段落：[売上実績] 報告書に明記された**実際の売上高(Revenue)数値と成長率(%)**を含める\n第2段落：[収益性] 営業利益と純利益の**実際のドル数値**を明記し分析\n第3段落：[利益の質] EPSと一回性費用の分析による収益創出能力の要約"},
                "CF": {"p": "営業CF, CAPEX, 財務CF, フリーキャッシュフロー(FCF)", "s": "第1段落：[営業CF] **実際の営業活動によるCF数値($)**を明記し評価\n第2段落：[投資とCAPEX] **CAPEXの実際の金額**と投資方向性を数字で分析\n第3段落：[現金の存続能力] **フリーキャッシュフロー(FCF)を直接計算(営業CF-CAPEX)**して明記"}
            },
            "zh": {
                "S-1": {"p": "风险因素, 资金用途, MD&A", "s": "第一段：该文件中最重要的投资亮点\n第二段：实质性增长潜力及其财务意义\n第三段：一个核心风险及其连锁反应"},
                "10-K": {"p": "年度营收, 营业利润, 业务板块数据", "s": "第一段：[年度表现] 明确列出过去一年的**实际营收和营业利润数值($)**及增长率\n第二段：[业务分析] 管理层强调的核心板块**业绩数据**及商业模式变化\n第三段：[风险展望] 风险因素对未来**财务指标的具体影响**"},
                "10-Q": {"p": "季度营收, 净利润, 现金储备", "s": "第一段：[季度业绩] 明确列出本季度**实际营收($)和净利润($)**及同比变化\n第二段：[现金状况] 明确列出当前的**现金及现金等价物数值**，评估偿债能力\n第三段：[指引] 管理层给出的下季度预期数值及短期增长的依据"},
                "BS": {"p": "总资产, 总负债, 现金及等价物, 权益", "s": "第一段：[资产结构] 明确列出流动资产和非流动资产的**实际美元金额(USD)**\n第二段：[负债与资本] 使用总负债和股东权益的**实际金额($)**评估稳定性\n第三段：[结论] 基于上述具体数值评估偿债能力及长期财务状况"},
                "IS": {"p": "营收增长, 毛利率, 营业利润, 净利润, EPS", "s": "第一段：[营收表现] 必须包含报告中列出的**实际营收数值及同比增长率(%)**\n第二段：[盈利指标] 使用**实际美元金额**分析营业利润和净利润\n第三段：[收益质量] 结合EPS和非经常性损益，总结实际盈利能力"},
                "CF": {"p": "经营CF, 投资CF, 筹资CF, FCF", "s": "第一段：[经营现金流] 明确列出**实际经营活动现金流数值($)**并评估造血能力\n第二段：[投资与支出] 基于金额分析**资本支出(CAPEX)的具体数值**\n第三段：[现金流存续] **明确计算并列出自由现金流(FCF)**情况"}
            }
        }
        lang_group = meta_dict.get(lang, meta_dict['ko'])
        return lang_group.get(doc_type, lang_group.get('S-1'))

    # 💡 [핵심] 지시사항(Instructions) 자체를 타겟 언어로 발행하여 일관성 유지
    def get_localized_instruction(lang, ticker, topic, company_name, meta, sec_fact_prompt, format_inst):
        if lang == 'en':
            return f"""You are a Senior Wall Street Analyst.
Target: {company_name} ({ticker}) - {topic}
Checkpoints: {meta['p']}
{sec_fact_prompt}

[STRICT WRITING RULES]
1. Write ENTIRELY in English.
2. DO NOT provide general definitions (e.g., 'Revenue is important').
3. YOU MUST find and include REAL NUMBERS (USD, %) from the filings.
4. If numbers are not in the provided fact check, search specifically for '{company_name} latest {topic} financial data'.
5. NO self-introductions.

[Structure]
{meta['s']}

{format_inst}"""
        elif lang == 'ja':
            return f"""あなたは証券分析のエキスパートです。
分析対象: {company_name} ({ticker}) - {topic}
チェックポイント: {meta['p']}
{sec_fact_prompt}

[厳格な作成ルール]
1. 全て日本語で作成してください。韓国語を絶対に混ぜないでください。
2. 一般的な定義（例：「売上は重要です」など）は一切禁止します。
3. 必ず最新の開示書類から**実際の数値（USD、$）とパーセンテージ（%）**を引用してください。
4. 自己紹介や挨拶は不要です。

[構成]
{meta['s']}

{format_inst}"""
        elif lang == 'zh':
            return f"""您是资深证券分析师。
分析目标: {company_name} ({ticker}) - {topic}
检查重点: {meta['p']}
{sec_fact_prompt}

[严格编写指南]
1. 必须完全使用简体中文编写。严禁混用韩语。
2. 严禁提供空洞的理论描述（如：'营收对公司很重要'）。
3. 必须从报告中找出并列出**具体的美元金额($)和百分比(%)数值**。
4. 不要进行自我介绍。

[结构要求]
{meta['s']}

{format_inst}"""
        else: # ko
            return f"""당신은 월가 출신의 전문 분석가입니다.
분석 대상: {company_name} ({ticker}) - {topic}
체크포인트: {meta['p']}
{sec_fact_prompt}

[작성 지침 - 필수 준수]
1. 반드시 한국어로만 작성하세요.
2. 일반적인 정의나 이론적인 설명(예: '영업현금흐름은 중요합니다')은 절대 하지 마세요.
3. 반드시 공시 서류에 기재된 **실제 달러($) 수치와 퍼센트(%)**를 찾아 언급하세요.
4. 수치를 찾을 수 없는 경우에만 예외적으로 팩트 위주로 작성하세요.
5. 자기소개나 인사말은 절대 하지 말고 ~입니다, ~합니다, ~습니다 등으로 문장을 끝내세요.

[내용 구성 지침]
{meta['s']}

{format_inst}"""

    def get_format_instruction(lang):
        if lang == 'en':
            return "- Begin each paragraph with a translated **[Heading]**. Rich content, 4-5 sentences per paragraph."
        elif lang == 'ja':
            return "- 各段落は日本語の **[見出し]** から始めてください。1段落につき4〜5文の充実した内容にしてください。"
        elif lang == 'zh':
            return "- 每个段落以中文 **[副标题]** 开头。每段必须包含4-5句详尽的内容。"
        else:
            return "- 각 문단은 반드시 **[소제목]**으로 시작하세요. 각 문단마다 4~5문장씩 상세하고 풍성하게 작성하세요."

    for topic in target_topics:
        sec_fact_prompt = ""
        sec_search_target = "10-K" if topic in ["BS", "IS", "CF"] else topic
        
        if cik:
            filed_date = check_sec_specific_filing(cik, sec_search_target)
            if filed_date:
                sec_fact_prompt = f"\n[SEC FACT CHECK] The company officially filed '{sec_search_target}' on {filed_date}. Focus on extracting specific data from this document."
            else:
                sec_fact_prompt = f"\n[SEC FACT CHECK] '{sec_search_target}' not found in SEC EDGAR. Use the latest available numerical data from recent web records."
        
        for lang_code, target_lang in SUPPORTED_LANGS.items():
            cache_key = f"{company_name}_{topic}_Tab0_v15_FullNumerical_{lang_code}"
            
            try:
                res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time_str).execute()
                if res.data: continue 
            except: pass

            meta = get_localized_meta(lang_code, topic)
            format_inst = get_format_instruction(lang_code)
            
            # 타겟 언어로 된 지시사항 생성
            prompt = get_localized_instruction(lang_code, ticker, topic, company_name, meta, sec_fact_prompt, format_inst)
            
            for attempt in range(3):
                try:
                    response = model.generate_content(prompt)
                    res_text = response.text
                    
                    if lang_code != 'ko':
                        import re
                        if re.search(r'[가-힣]', res_text):
                            time.sleep(1); continue 
                            
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




def run_tab4_analysis(ticker, company_name, ipo_status="Active", ipo_date_str=None):
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

    for lang_code, _ in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Tab4_v3_{lang_code}" 
        
        try:
            res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time_str).execute()
            if res.data: continue 
        except: pass

        # 💡 [핵심] 기존 6가지 지침을 해당 언어로 100% 직역하여 유지
        if lang_code == 'en':
            prompt = f"""You are an IPO analyst from Wall Street.
Use the Google search tool to find and analyze the latest institutional reports (Seeking Alpha, Renaissance Capital, etc.) for {company_name} ({ticker}).

[Instructions]
1. **Language Rule**: MUST write entirely in English. DO NOT mix any Korean words.
2. **Analysis Depth**: Provide a professional analysis including specific figures and evidence.
3. **Pros & Cons**: Clearly derive and reflect exactly 2 positive factors (Pros) and 2 negative factors (Cons).
4. **Score**: Evaluate the overall positive/expectation level of the Wall Street report as an integer from 1 (Worst) to 5 (Moonshot/Best).
5. **Output Format**: Strictly follow the language and instructions written in the 'Value' part of the <JSON_START> format provided below (100% compliance).
6. **Link Location**: NEVER put URLs inside the main body text. You MUST only put them inside the "links" array.

<JSON_START>
{{
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell",
    "score": "Integer from 1 to 5",
    "summary": "Professional 3-line summary in English",
    "pro_con": "**Pros**:\\n- Detail 1\\n- Detail 2\\n\\n**Cons**:\\n- Detail 1\\n- Detail 2",
    "links": [ {{"title": "Report Title", "link": "URL"}} ]
}}
<JSON_END>"""

        elif lang_code == 'ja':
            prompt = f"""あなたはウォール街出身のIPO専門アナリストです。
Google検索ツールを使用して、{company_name} ({ticker})に関する最新の機関投資家レポート（Seeking Alpha、Renaissance Capitalなど）を見つけ、深く分析してください。

[作成指針]
1. **言語規則**: 全て自然な日本語のみで記述してください。韓国語を絶対に混ぜないでください。
2. **分析の深さ**: 具体的な数値や根拠を含む専門的な分析を提供してください。
3. **Pros & Cons**: 肯定的な要素(長所)を2つ、否定的な要素(短所)を2つ明確に導き出して反映させてください。
4. **スコア(Score)**: ウォール街のレポートの総合的な肯定/期待レベルを1点(最悪)から5点(大当たり)までの整数で評価してください。
5. **出力形式**: 以下に提供された<JSON_START>フォーマットの「値(Value)」部分に記載されている言語と指示を100%遵守して記入してください。
6. **リンクの位置**: 本文の中には絶対にURLを入れず、必ず「links」配列の中にのみ記入してください。

<JSON_START>
{{
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell (この項目のみ英語を維持)",
    "score": "1から5までの整数",
    "summary": "日本語での専門的な3行要約",
    "pro_con": "**長所(Pros)**:\\n- 詳細な分析内容1\\n- 詳細な分析内容2\\n\\n**短所(Cons)**:\\n- リスク要因1\\n- リスク要因2",
    "links": [ {{"title": "レポートのタイトル", "link": "URL"}} ]
}}
<JSON_END>"""

        elif lang_code == 'zh':
            prompt = f"""您是华尔街的专业IPO分析师。
请使用Google搜索工具查找并深度分析关于 {company_name} ({ticker}) 的最新机构报告（如Seeking Alpha, Renaissance Capital等）。

[编写指南]
1. **语言规则**: 必须只用简体中文编写。严禁在回答中混用韩语。
2. **分析深度**: 提供包含具体数据和依据的专业分析。
3. **Pros & Cons**: 明确提取并反映2个积极因素(优点)和2个消极因素(缺点)。
4. **评分(Score)**: 将华尔街报告的综合积极/预期水平评为1(最差)到5(极佳)之间的整数。
5. **输出格式**: 100%严格遵守下面提供的 <JSON_START> 格式中“值(Value)”部分的语言和指示进行填写。
6. **链接位置**: 绝对不要在正文中放入URL，必须只填写在“links”数组中。

<JSON_START>
{{
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell (保留英文)",
    "score": "1到5的整数",
    "summary": "专业中文三行摘要",
    "pro_con": "**优点(Pros)**:\\n- 详细分析内容1\\n- 详细分析内容2\\n\\n**缺点(Cons)**:\\n- 风险因素1\\n- 风险因素2",
    "links": [ {{"title": "报告标题", "link": "URL"}} ]
}}
<JSON_END>"""

        else:
            prompt = f"""당신은 월가 출신의 IPO 전문 분석가입니다. 
구글 검색 도구를 사용하여 {company_name} ({ticker})에 대한 최신 기관 리포트(Seeking Alpha, Renaissance Capital 등)를 찾아 심층 분석하세요.

[작성 지침]
1. **언어 규칙**: 반드시 자연스러운 한국어로 번역하여 작성하세요.
2. **분석 깊이**: 구체적인 수치나 근거를 포함하여 전문적으로 분석하세요.
3. **Pros & Cons**: 긍정적 요소(Pros) 2가지와 부정적 요소(Cons) 2가지를 명확히 도출하여 반영하세요.
4. **Score**: 월가 리포트의 종합적인 긍정/기대 수준을 1점(최악)부터 5점(대박) 사이의 정수로 평가하세요.
5. **출력 형식**: 아래 제공된 <JSON_START> 양식의 '값(Value)' 부분에 적힌 언어와 지시사항을 100% 준수하여 채워 넣으세요.
6. **링크 위치**: 본문 안에는 절대 URL을 넣지 말고, 반드시 "links" 배열 안에만 기입하세요.

<JSON_START>
{{
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell 중 택 1 (영어 유지)",
    "score": "1~5 사이의 정수 (예: 4)",
    "summary": "한국어 전문 3줄 요약",
    "pro_con": "**장점(Pros)**:\\n- 구체적 분석 내용 1\\n- 구체적 분석 내용 2\\n\\n**단점(Cons)**:\\n- 구체적 리스크 요인 1\\n- 구체적 리스크 요인 2",
    "links": [ {{"title": "리포트 제목", "link": "URL"}} ]
}}
<JSON_END>"""
        
        for attempt in range(3):
            try:
                response = model.generate_content(prompt)
                full_text = response.text
                
                # 💡 [방어막 작동] 외국어 답변에 한글이 섞이면 파기
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

def run_tab3_analysis(ticker, company_name, metrics):
    """Tab 3: 프리미엄 재무 데이터 및 DCF 적정주가 분석 리포트 (다국어 완벽 분리)"""
    if not model: return False
    
    valid_hours = 24 
    limit_time_str = (datetime.now() - timedelta(hours=valid_hours)).isoformat()
    
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Financial_Report_Tab3_{lang_code}"
        
        try:
            res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time_str).execute()
            if res.data: continue 
        except: pass

        # 💡 [핵심] 언어별 프롬프트 완벽 분리 및 소제목 강제 지정
        if lang_code == 'en':
            prompt = f"""You are a Lead Quant Analyst on Wall Street.
Write an in-depth financial report for {company_name} ({ticker}) based on the FMP Premium data below.

[FMP Premium Data]
- Current Price: {metrics.get('current_price', 'N/A')}
- DCF Value (Target Price): {metrics.get('dcf_price', 'N/A')}
- Quant Rating: {metrics.get('rating', 'N/A')} (Score: {metrics.get('health_score', 'N/A')}/5)
- Recommendation: {metrics.get('recommendation', 'N/A')}
- P/E Ratio: {metrics.get('pe', 'N/A')} | ROE: {metrics.get('roe', 'N/A')} | P/B Ratio: {metrics.get('pb', 'N/A')}

[Writing Guidelines]
1. Language: Write STRICTLY and ENTIRELY in English. Do not mix Korean.
2. Format: You MUST use the following 3 headings:
   **[DCF Valuation & Price Target]**
   **[Quant Health Score]**
   **[Analyst Conclusion]**
3. Content: Analyze the gap between DCF value and current price. Evaluate fundamental health based on the Quant Rating and ROE. (10-12 lines total)"""

        elif lang_code == 'ja':
            prompt = f"""あなたはウォール街のシニアクオンツアナリストです。
以下のFMPプレミアムデータに基づいて、{company_name} ({ticker})の深層財務レポートを作成してください。

[FMPプレミアムデータ]
- 現在の株価(Current Price): {metrics.get('current_price', 'N/A')}
- DCF目標株価(DCF Value): {metrics.get('dcf_price', 'N/A')}
- クオンツ評価(Quant Rating): {metrics.get('rating', 'N/A')} (スコア: {metrics.get('health_score', 'N/A')}/5)
- 投資判断(Recommendation): {metrics.get('recommendation', 'N/A')}
- P/E Ratio: {metrics.get('pe', 'N/A')} | ROE: {metrics.get('roe', 'N/A')} | P/B Ratio: {metrics.get('pb', 'N/A')}

[作成ガイドライン]
1. 言語: 全て自然な日本語のみで記述してください。韓国語は絶対に混ぜないでください。
2. 形式: 以下の3つの見出しを**必ず**使用してください。
   **[DCFバリュエーションと目標株価]**
   **[クオンツ・ヘルススコア]**
   **[アナリストの結論]**
3. 内容: DCF価値と現在価格の乖離率を解釈し、クオンツ評価に基づいてファンダメンタルズを評価してください。(全体で10〜12行程度)"""

        elif lang_code == 'zh':
            prompt = f"""您是华尔街的首席量化分析师。
请根据以下FMP高级数据，撰写关于 {company_name} ({ticker}) 的深度财务报告。

[FMP高级数据]
- 当前股价(Current Price): {metrics.get('current_price', 'N/A')}
- DCF目标价(DCF Value): {metrics.get('dcf_price', 'N/A')}
- 量化评级(Quant Rating): {metrics.get('rating', 'N/A')} (得分: {metrics.get('health_score', 'N/A')}/5)
- 投资建议(Recommendation): {metrics.get('recommendation', 'N/A')}
- P/E Ratio: {metrics.get('pe', 'N/A')} | ROE: {metrics.get('roe', 'N/A')} | P/B Ratio: {metrics.get('pb', 'N/A')}

[编写指南]
1. 语言：必须只用简体中文编写。严禁混用韩语。
2. 格式：**必须**使用以下3个副标题：
   **[DCF估值与目标价]**
   **[量化健康评分]**
   **[分析师结论]**
3. 内容：分析DCF估值与当前股价之间的差距，并基于量化评级评估公司的基本面健康状况。(整体10~12行左右)"""

        else: # ko
            prompt = f"""당신은 CFA 자격을 보유한 월스트리트 수석 퀀트 애널리스트입니다.
아래 FMP 프리미엄 데이터를 바탕으로 {company_name} ({ticker})의 심층 재무 리포트를 작성하세요.

[FMP 프리미엄 데이터]
- 현재 주가(Current Price): {metrics.get('current_price', 'N/A')}
- DCF 산출 적정 주가(DCF Value): {metrics.get('dcf_price', 'N/A')}
- 건전성 종합 등급(Quant Rating): {metrics.get('rating', 'N/A')} (점수: {metrics.get('health_score', 'N/A')}/5)
- 퀀트 투자의견: {metrics.get('recommendation', 'N/A')}
- P/E Ratio: {metrics.get('pe', 'N/A')} | ROE: {metrics.get('roe', 'N/A')} | P/B Ratio: {metrics.get('pb', 'N/A')}

[작성 가이드]
1. 언어: 반드시 한국어로 작성하세요.
2. 형식: 아래 3가지 소제목을 반드시 사용하여 단락을 구분하세요.
   **[DCF 적정주가 및 밸류에이션]**
   **[퀀트 헬스 스코어]**
   **[애널리스트 종합 의견]**
3. 내용: 단순 수치 나열을 피하고, DCF 괴리율(%) 분석과 종합 등급이 뜻하는 펀더멘털 상태를 전문가 시각에서 해석하세요. (총 10~12줄)"""
        
        for attempt in range(3):
            try:
                response = model.generate_content(prompt)
                res_text = response.text
                
                # 방어막: 타겟 언어가 한국어가 아닐 때 한글이 감지되면 재시도
                if lang_code != 'ko' and re.search(r'[가-힣]', res_text):
                    time.sleep(1); continue 
                        
                batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": res_text, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
                break 
            except Exception as e:
                time.sleep(1)

def update_macro_data(df):
    """Tab 2: 거시 지표 분석 코멘트"""
    if not model: return
    print("🌍 거시 지표(Tab 2) 업데이트 중...")
    
    data = {"ipo_return": 15.2, "ipo_volume": len(df), "vix": 14.5, "fear_greed": 60} 
    
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key_report = f"Global_Market_Dashboard_Tab2_{lang_code}"
        prompt = f"""
        당신은 월가의 수석 시장 전략가(Chief Market Strategist)입니다.
        현재 시장 데이터(VIX: {data['vix']:.2f}, IPO수익률: {data['ipo_return']:.1f}%) 기반으로 현재 미국 주식 시장과 IPO 시장의 상태를 진단하는 일일 브리핑을 작성하세요.

        [작성 가이드]
        - 언어: 반드시 '{target_lang}'로 작성하세요. (다른 언어 절대 혼용 금지)
        - 형식: 줄글로 된 3~5줄의 요약 리포트로 제목, 소제목, 헤더(##), 인사말을 절대 포함하지 마세요.
        """
        
        # 💡 [방어막 추가] 최대 3회 재시도 루프
        for attempt in range(3):
            try:
                ai_resp = model.generate_content(prompt).text
                
                if lang_code != 'ko':
                    if re.search(r'[가-힣]', ai_resp):
                        time.sleep(1); continue # 한글 감지 시 재시도

                ai_resp = re.sub(r'^#+.*$', '', ai_resp, flags=re.MULTILINE).strip()
                batch_upsert("analysis_cache", [{"cache_key": cache_key_report, "content": ai_resp, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
                break # 성공 시 루프 탈출
            except:
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

        # --- 2. 기간별 통계적 유의 상승 로직 (1일~12개월 초정밀 세분화) ---
        try:
            tk_yf = yf.Ticker(ticker)
            hist = tk_yf.history(period="1y")
            if len(hist) < 2: continue

            if len(hist) >= 2:
                p_1d = hist['Close'].iloc[-2]
                chg_1d = ((current_p - p_1d) / p_1d) * 100
                if chg_1d >= 12.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1D", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 1일 동안 {chg_1d:.1f}% 상승"})
            
            if len(hist) >= 5:
                p_1w = hist['Close'].iloc[-5]
                chg_1w = ((current_p - p_1w) / p_1w) * 100
                if chg_1w >= 20.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1W", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 1주 동안 {chg_1w:.1f}% 상승"})

            if len(hist) >= 10:
                p_2w = hist['Close'].iloc[-10]
                chg_2w = ((current_p - p_2w) / p_2w) * 100
                if chg_2w >= 30.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_2W", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 2주 동안 {chg_2w:.1f}% 상승"})

            if len(hist) >= 20:
                p_4w = hist['Close'].iloc[-20]
                chg_4w = ((current_p - p_4w) / p_4w) * 100
                if chg_4w >= 40.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_4W", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 4주 동안 {chg_4w:.1f}% 상승"})

            if len(hist) >= 22:
                p_1mo = hist['Close'].iloc[-22]
                chg_1mo = ((current_p - p_1mo) / p_1mo) * 100
                if chg_1mo >= 45.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1M", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 1개월 동안 {chg_1mo:.1f}% 상승"})

            if len(hist) >= 63:
                p_3m = hist['Close'].iloc[-63]
                chg_3m = ((current_p - p_3m) / p_3m) * 100
                if chg_3m >= 60.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_3M", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 3개월 동안 {chg_3m:.1f}% 상승"})

            if len(hist) >= 126:
                p_6m = hist['Close'].iloc[-126]
                chg_6m = ((current_p - p_6m) / p_6m) * 100
                if chg_6m >= 80.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_6M", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 6개월 동안 {chg_6m:.1f}% 상승"})

            if len(hist) >= 250:
                p_1y = hist['Close'].iloc[0]
                chg_1y = ((current_p - p_1y) / p_1y) * 100
                if chg_1y >= 150.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1Y", "title": f"{ticker} 단기 급등 포착", "message": f"{ticker} 주가 최근 1년 동안 {chg_1y:.1f}% 상승"})
        except: pass

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
        
        batch_upsert("analysis_cache", [{
            "cache_key": "SUDDEN_ADDITIONS_LIST",
            "content": json.dumps(sudden_additions),
            "updated_at": now_iso
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
            run_tab4_analysis(official_symbol, name, c_status, c_date)
            
            try:
                metrics = {}
                # 1. 기본 메트릭 (PE, PB 등)
                res_m = requests.get(f"https://financialmodelingprep.com/api/v3/key-metrics-ttm/{official_symbol}?apikey={FMP_API_KEY}", timeout=5).json()
                if isinstance(res_m, list) and len(res_m) > 0:
                    metrics['pe'] = res_m[0].get('peRatioTTM', 'N/A')
                    metrics['pb'] = res_m[0].get('pbRatioTTM', 'N/A')
                    metrics['roe'] = res_m[0].get('roeTTM', 'N/A')
                
                # 2. DCF (현금흐름할인법) 기반 알고리즘 적정 주가
                res_dcf = requests.get(f"https://financialmodelingprep.com/api/v3/discounted-cash-flow/{official_symbol}?apikey={FMP_API_KEY}", timeout=5).json()
                if isinstance(res_dcf, list) and len(res_dcf) > 0:
                    metrics['dcf_price'] = res_dcf[0].get('dcf', 'N/A')
                    metrics['current_price'] = res_dcf[0].get('Stock Price', 'N/A')
                
                # 3. FMP 퀀트 종합 등급 및 헬스 스코어
                res_r = requests.get(f"https://financialmodelingprep.com/api/v3/rating/{official_symbol}?apikey={FMP_API_KEY}", timeout=5).json()
                if isinstance(res_r, list) and len(res_r) > 0:
                    metrics['rating'] = res_r[0].get('rating', 'N/A')
                    metrics['recommendation'] = res_r[0].get('ratingRecommendation', 'N/A')
                    metrics['health_score'] = res_r[0].get('ratingScore', 'N/A')

                run_tab3_analysis(official_symbol, name, metrics)
            except Exception as e:
                print(f"Tab3 Premium Data Error for {official_symbol}: {e}")
                pass
            # 👆 여기까지 덮어쓰기 완료! 👆
            
            time.sleep(1.2)
            
        except Exception as e:
            print(f"⚠️ {original_symbol} 분석 건너뜀: {e}")
            continue

    run_premium_alert_engine(df)
            
    print(f"\n🏁 모든 작업 종료: {datetime.now()}")

if __name__ == "__main__":
    main()
