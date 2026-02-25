import os
import time
import json
import re
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import logging
from datetime import datetime, timedelta

from supabase import create_client
import google.generativeai as genai

# ==========================================
# [1] 환경 설정
# ==========================================
raw_url = os.environ.get("SUPABASE_URL", "")
if "/rest/v1" in raw_url:
    SUPABASE_URL = raw_url.split("/rest/v1")[0].rstrip('/')
else:
    SUPABASE_URL = raw_url.rstrip('/')

SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
GENAI_API_KEY = os.environ.get("GENAI_API_KEY", "")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

logging.getLogger('yfinance').setLevel(logging.CRITICAL)

if not (SUPABASE_URL and SUPABASE_KEY):
    print("❌ 환경변수 누락 (SUPABASE_URL 또는 KEY)")
    exit()

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"❌ Supabase 클라이언트 초기화 실패: {e}")
    exit()

model = None 
if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)
    try:
        model = genai.GenerativeModel('gemini-2.0-flash', tools=[{'google_search_retrieval': {}}])
        print("✅ AI 모델 로드 성공 (Search Tool 활성화)")
    except:
        model = genai.GenerativeModel('gemini-2.0-flash')
        print("⚠️ AI 모델 기본 로드 (Search Tool 제외)")

# 💡 중국어(zh) 지원이 포함된 언어 리스트
SUPPORTED_LANGS = {
    'ko': '전문적인 한국어(Korean)',
    'en': 'Professional English',
    'ja': '専門的な日本語(Japanese)',
    'zh': '简体中文(Simplified Chinese)'
}

# ==========================================
# [2] 헬퍼 함수
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
            pass # 성공 로깅 생략
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
# [추가] 프리미엄 유저 대상 통계적 급등 알림 엔진
# ==========================================
def run_premium_alert_engine(df_calendar):
    print("🕵️ 프리미엄 알림 엔진 가동 (기간별 통계 모드)...")
    today = datetime.now().date()
    new_alerts = []
    
    # DB에서 최신 가격 가져오기 (worker.py에 이미 있는 함수 활용)
    price_map = get_current_prices()

    for _, row in df_calendar.iterrows():
        ticker = row['symbol']
        name = row['name']
        current_p = price_map.get(ticker, 0.0)
        
        try: ipo_date = pd.to_datetime(row['date']).date()
        except: continue
        
        if current_p <= 0: continue

        # (여기에 방금 작성해주신 1일~1년 세분화 로직 전체를 그대로 붙여넣습니다)
        # ... [코드 생략: 1. 일정 기반 알림 ~ 3. 공모가 관련 시그널 등] ...

    # 분석된 알림을 DB에 저장 (중복 방지 적용)
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
    """Tab 0: 공시 문서 분석 (캐싱 방어막 및 SEC 직접 검증 적용)"""
    if not model: return
    
    status_lower = str(ipo_status).lower()
    is_withdrawn = any(x in status_lower for x in ['철회', '취소', 'withdrawn'])
    is_delisted = any(x in status_lower for x in ['폐지', 'delisted'])
    
    is_over_1y = False
    if ipo_date_str:
        try:
            ipo_dt = pd.to_datetime(ipo_date_str).date()
            if (datetime.now().date() - ipo_dt).days > 365:
                is_over_1y = True
        except: pass

    # 💡 [핵심 추가] 상태별 캐시 유효 시간 설정 (1년 이상/철회/폐지는 1주일(168시간), 나머지는 24시간)
    if is_withdrawn or is_delisted or is_over_1y:
        valid_hours = 24 * 7  
    else:
        valid_hours = 24      
        
    limit_time_str = (datetime.now() - timedelta(hours=valid_hours)).isoformat()

    # 타겟 문서 선정
    if is_withdrawn: target_topics = ["S-1", "S-1/A", "F-1", "FWP", "RW"]
    elif is_delisted: target_topics = ["S-1", "S-1/A", "F-1", "FWP", "424B4", "Form 25"]
    elif is_over_1y: target_topics = ["S-1", "FWP", "10-K", "10-Q", "BS", "IS", "CF"]
    else: target_topics = ["S-1", "S-1/A", "F-1", "FWP", "424B4"]

    def_meta = {
        # --- [IPO 상장 진행 서류] ---
        "S-1": {
            "desc": "S-1은 상장을 위해 최초로 제출하는 서류입니다. **Risk Factors**(위험 요소), **Use of Proceeds**(자금 용도), **MD&A**(경영진의 운영 설명)를 확인할 수 있습니다.",
            "points": "Risk Factors(특이 소송/규제), Use of Proceeds(자금 용도의 건전성), MD&A(성장 동인)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 해당 문서에서 발견된 가장 중요한 투자 포인트 분석
            2. 두 번째 문단: 실질적 성장 가능성과 재무적 의미 분석
            3. 세 번째 문단: 핵심 리스크 1가지와 그 파급 효과 및 대응책
            """
        },
        "S-1/A": {
            "desc": "S-1/A는 공모가 밴드와 주식 수가 확정되는 수정 문서입니다. **Pricing Terms**(공모가 확정 범위)와 **Dilution**(기존 주주 대비 희석률)을 확인할 수 있습니다.",
            "points": "Pricing Terms(수요예측 분위기), Dilution(신규 투자자 희석률), Changes(이전 제출본과의 차이점)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 이전 S-1 대비 변경된 핵심 사항 분석
            2. 두 번째 문단: 제시된 공모가 범위의 적정성 및 수요예측 분위기 분석
            3. 세 번째 문단: 기존 주주 가치 희석 정도와 투자 매력도 분석
            """
        },
        "F-1": {
            "desc": "F-1은 해외 기업이 미국 상장 시 제출하는 서류입니다. 해당 국가의 **Foreign Risk**(정치/경제 리스크)와 **Accounting**(회계 기준 차이)을 확인할 수 있습니다.",
            "points": "Foreign Risk(지정학적 리스크), Accounting(GAAP 차이), ADS(주식 예탁 증서 구조)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 기업이 글로벌 시장에서 가진 독보적인 경쟁 우위
            2. 두 번째 문단: 환율, 정치, 회계 등 해외 기업 특유의 리스크 분석
            3. 세 번째 문단: 미국 예탁 증서(ADS) 구조가 주주 권리에 미치는 영향
            """
        },
        "FWP": {
            "desc": "FWP는 기관 투자자 대상 로드쇼(Roadshow) PPT 자료입니다. **Graphics**(비즈니스 모델 시각화)와 **Strategy**(경영진이 강조하는 미래 성장 동력)를 확인할 수 있습니다.",
            "points": "Graphics(시장 점유율 시각화), Strategy(미래 핵심 먹거리), Highlights(경영진 강조 사항)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 경영진이 로드쇼에서 강조하는 미래 성장 비전
            2. 두 번째 문단: 경쟁사 대비 부각시키는 기술적/사업적 차별화 포인트
            3. 세 번째 문단: 자료 톤앤매너로 유추할 수 있는 시장 공략 의지
            """
        },
        "424B4": {
            "desc": "424B4는 공모가가 최종 확정된 후 발행되는 설명서입니다. **Underwriting**(주관사 배정)과 확정된 **Final Price**(최종 공모가)를 확인할 수 있습니다.",
            "points": "Underwriting(주관사 등급), Final Price(기관 배정 물량), IPO Outcome(최종 공모 결과)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 확정 공모가의 위치와 시장 수요 해석
            2. 두 번째 문단: 확정된 조달 자금의 투입 우선순위 점검
            3. 세 번째 문단: 주관사단 및 배정 물량 바탕 상장 초기 유통물량 예측
            """
        },
        # --- [상장 철회 및 폐지 서류] ---
        "RW": {
            "desc": "RW(Registration Withdrawal)는 기업이 상장 절차를 공식적으로 중단하고 증권신고서를 철회할 때 제출하는 문서입니다. 주로 시장 환경 악화나 내부 사정으로 인한 철회 사유가 담깁니다.",
            "points": "Withdrawal Reason(철회 사유), Market Condition(시장 환경 악화 여부), Future Plans(향후 계획)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 해당 기업의 상장 철회(Withdrawal) 결정적 사유 및 배경
            2. 두 번째 문단: 상장 철회가 기업 재무 및 기존 투자자에게 미치는 영향
            3. 세 번째 문단: 향후 재상장 또는 M&A 등 향후 계획
            """
        },
        "Form 25": {
            "desc": "Form 25는 거래소에서 상장 폐지되거나 등록이 취소될 때 제출하는 공식 통지서입니다. 인수합병(M&A)이나 상장 유지 규정 위반 등의 사유를 확인할 수 있습니다.",
            "points": "Delisting Reason(상장폐지 사유), M&A(인수합병 여부), Shareholder Impact(주주 영향)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 상장 폐지(Delisting)의 정확한 사유 (인수합병, 자진 상폐, 규정 위반 등)
            2. 두 번째 문단: 상장 폐지 후 기존 주주의 권리 및 주식 처리 방안
            3. 세 번째 문단: 장외시장(OTC) 거래 가능성 및 향후 기업 상태
            """
        },
        # --- [상장 후 1년 이상 정식 재무 서류] ---
        "10-K": {
            "desc": "10-K는 미국의 상장기업이 매년 SEC에 제출하는 연간 사업보고서입니다. 한 해의 전반적인 사업 성과와 위험 요소를 포괄적으로 다룹니다.",
            "points": "Business Overview(사업 개요), Risk Factors(위험 요소), MD&A(경영진 분석)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 지난 1년간의 핵심 사업 성과 및 비즈니스 모델 변화
            2. 두 번째 문단: 경영진이 강조하는(MD&A) 주요 재무 실적과 당면 과제
            3. 세 번째 문단: 새롭게 부각된 위험 요소(Risk Factors) 및 장기 전망
            """
        },
        "10-Q": {
            "desc": "10-Q는 분기별로 제출되는 실적 보고서입니다. 최근 3개월간의 재무 상태 변화와 단기적인 사업 현황을 파악할 수 있습니다.",
            "points": "Quarterly Earnings(분기 실적), Short-term Guidance(단기 가이던스), Recent Changes(최근 변동사항)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 해당 분기의 매출 및 이익 달성 현황 요약
            2. 두 번째 문단: 전년 동기 대비 주요 변화와 그 원인
            3. 세 번째 문단: 다음 분기 가이던스 및 단기 리스크 요인
            """
        },
        "BS": {
            "desc": "재무상태표(Balance Sheet)는 기업의 자산, 부채, 자본의 현재 상태를 보여줍니다. 기업의 재무 건전성과 지급 능력을 분석합니다.",
            "points": "Assets(자산 구성), Liabilities(부채 및 상환 능력), Equity(자본 건전성)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 유동 자산과 비유동 자산의 핵심 구성비 및 특징
            2. 두 번째 문단: 부채 비율, 이자 발생 부채 등 재무 리스크 진단
            3. 세 번째 문단: 자본 충실도 및 종합적인 재무 건전성(Solvency) 평가
            """
        },
        "IS": {
            "desc": "손익계산서(Income Statement)는 일정 기간 동안의 매출과 비용, 순이익을 나타냅니다. 기업의 수익 창출 능력을 분석합니다.",
            "points": "Revenue Growth(매출 성장), Margins(이익률), EPS(주당순이익)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 탑라인(매출) 성장 추이와 주요 견인 사업부 분석
            2. 두 번째 문단: 매출원가 및 판관비 통제에 따른 영업이익률/순이익률 평가
            3. 세 번째 문단: 최종 수익성(EPS 등) 및 이익의 질(Quality of Earnings) 요약
            """
        },
        "CF": {
            "desc": "현금흐름표(Cash Flow)는 기업에 실제 현금이 어떻게 들어오고 나갔는지를 보여줍니다. 흑자 도산 위험 등을 판별하는 핵심 지표입니다.",
            "points": "Operating CF(영업현금), Investing CF(투자현금), Financing CF(재무현금)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 영업활동을 통한 순수 현금 창출 능력 평가
            2. 두 번째 문단: CAPEX 등 투자활동 현금흐름의 공격성 및 방향성
            3. 세 번째 문단: 차입/상환 및 배당 등 재무활동과 최종 잉여현금흐름(FCF) 상태
            """
        }
    }

    format_instruction = """
    [출력 형식 및 번역 규칙 - 반드시 지킬 것]
    - 각 문단의 시작은 반드시 해당 언어로 번역된 **[소제목]**으로 시작한 뒤, 줄바꿈 없이 한 칸 띄우고 바로 내용을 이어가세요.
    - [분량 조건] 전체 요약이 아닙니다! **각 문단(1, 2, 3)마다 반드시 4~5문장(약 5줄 분량)씩** 내용을 상세하고 풍성하게 채워 넣으세요.
    - 올바른 예시(영어): **[Investment Point]** The company's main advantage is...
    - 올바른 예시(일본어): **[投資ポイント]** 同社の最大の強みは...
    - 금지 예시(한국어 병기 절대 금지): **[Investment Point - 투자포인트]** (X)
    - 금지 예시(소제목 뒤 줄바꿈 절대 금지): **[投資ポイント]** \n 同社は... (X)
    """

    cik = cik_mapping.get(ticker) if cik_mapping else None

    for topic in target_topics:
        curr_meta = def_meta[topic]
        sec_fact_prompt = ""
        sec_search_target = "10-K" if topic in ["BS", "IS", "CF"] else topic
        
        if cik:
            filed_date = check_sec_specific_filing(cik, sec_search_target)
            if filed_date:
                sec_fact_prompt = f"\n[💡 SEC FACT CHECK] 해당 기업은 {filed_date}에 공식적으로 '{sec_search_target}' 서류를 SEC에 제출했습니다. 이 사실과 구글 검색을 기반으로 아래 지침에 맞게 분석하십시오."
            else:
                sec_fact_prompt = f"\n[💡 SEC FACT CHECK] 현재 SEC EDGAR 시스템에 공식 '{sec_search_target}' 서류가 조회되지 않습니다. 구글 뉴스 등을 검색하여 지연 사유나 현재 상황을 대체 요약하십시오."
        
        for lang_code, target_lang in SUPPORTED_LANGS.items():
            cache_key = f"{company_name}_{topic}_Tab0_v13_{lang_code}"
            
            # 💡 [핵심 추가] API 호출 전 DB 캐시 검증! (이 부분이 있어야 1주일 캐싱이 작동합니다)
            try:
                res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time_str).execute()
                if res.data:
                    continue # 캐시가 살아있으면 이 언어는 스킵하고 다음으로 넘어감 (API 요금 $0)
            except: pass

            if lang_code == 'en':
                labels = ["Analysis Target", "Instructions", "Structure & Format", "Writing Style Guide"]
                role_desc = "You are a professional senior analyst from Wall Street."
                no_intro_prompt = 'CRITICAL: NEVER introduce yourself. DO NOT include Korean translations in headings. START IMMEDIATELY with the first English **[Heading]**.'
                lang_directive = "The guide below is in Korean for reference, but you MUST translate all headings and content into English."
            elif lang_code == 'ja':
                labels = ["分析対象", "指針", "内容構成および形式", "文体ガイド"]
                role_desc = "あなたはウォール街出身の専門分析家です。"
                no_intro_prompt = '【重要】自己紹介は絶対に禁止です。見出しに韓国語を併記しないでください。1文字目からいきなり日本語の**[見出し]**で本論から始めてください。'
                lang_directive = "構成 가이드는 참고용으로 한국어로提供되나,すべての見出しと内容は必ず日本語(Japanese)のみで作成してください。"
            elif lang_code == 'zh':
                labels = ["分析目标", "指南", "内容结构和格式", "文体指南"]
                role_desc = "您是华尔街的专业高级分析师。"
                no_intro_prompt = '【重要】绝对不要自我介绍。绝对不要在标题中包含韩语。请直接以中文的**[标题]**开始正文。'
                lang_directive = "结构指南仅供参考，所有标题和内容必须只用简体中文(Simplified Chinese)编写。"
            else:
                labels = ["분석 대상", "지침", "내용 구성 및 형식 - 반드시 아래 형식을 따를 것", "문체 가이드"]
                role_desc = "당신은 월가 출신의 전문 분석가입니다."
                no_intro_prompt = '자기소개나 인사말, 서론은 절대 하지 마세요. 1글자부터 바로 본론(**[소제목]**)으로 시작하세요.'
                lang_directive = ""

            prompt = f"""
            {labels[0]}: {company_name} - {topic}
            {labels[1]} (Checkpoints): {curr_meta['points']}
            {sec_fact_prompt}
            
            [{labels[1]}]
            {role_desc}
            {no_intro_prompt}
            {lang_directive}
            
            [{labels[2]}]
            {curr_meta['structure']}
            {format_instruction}

            [{labels[3]}]
            - 반드시 '{target_lang}'로만 작성하세요. (절대 다른 언어를 섞지 마세요)
            - 문장 끝이 끊기지 않도록 매끄럽게 연결하세요.
            """
            
            for attempt in range(3):
                try:
                    response = model.generate_content(prompt)
                    res_text = response.text
                    
                    if lang_code != 'ko':
                        if re.search(r'[가-힣]', res_text):
                            time.sleep(1); continue 
                            
                    batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": res_text, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
                    break 
                except:
                    time.sleep(1)

def run_tab1_analysis(ticker, company_name, ipo_status="Active"):
    """Tab 1: 비즈니스 요약 및 뉴스 (구글 검색 강제 지시어 + v4 캐시 적용)"""
    if not model: return False
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    current_year = now.strftime("%Y") # 💡 [추가] 2026년 최신 뉴스 강제 검색용
    
    # 💡 [1. 동적 캐싱 로직] 
    if ipo_status == "상장예정(30일이내)": valid_hours = 6
    elif ipo_status in ["상장대기", "상장연기", "상장폐지"]: valid_hours = 24 * 7
    else: valid_hours = 24
        
    limit_time_str = (now - timedelta(hours=valid_hours)).isoformat()
    
    # 💡 [상태 판별] 상장 철회/취소/폐지/연기 여부 확인
    status_lower = str(ipo_status).lower()
    is_cancelled = any(x in status_lower for x in ['연기', '폐지', '철회', '취소', 'delayed', 'delisted', 'withdrawn'])
    
    for lang_code, target_lang_str in SUPPORTED_LANGS.items():
        # 💡 [버전 업데이트] v3 -> v4로 올려서 기존의 환각(옛날 뉴스) 캐시를 무시하고 새로 분석합니다!
        cache_key = f"{ticker}_Tab1_v4_{lang_code}_{ipo_status}"
        
        # 💡 [캐시 검증] 아직 유효 시간이 안 지났다면 생성 스킵! (API 비용 절약)
        try:
            res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time_str).execute()
            if res.data:
                continue # 캐시가 살아있으면 다음 언어로 넘어감
        except: pass

        # ---------------------------------------------------------
        # 💡 언어별 & 상태별 프롬프트 세팅
        # ---------------------------------------------------------
        if lang_code == 'ja':
            sys_prompt = "あなたは最高レベルの証券会社リサーチセンターのシニアアナリストです。すべての回答は必ず日本語で作成してください。"
            task2_label = "[タスク2: 最新ニュースの収集]"
            target_lang = "日本語(Japanese)"
            lang_instruction = "必ず自然な日本語のみで作成してください。"
            json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "日本語に翻訳されたタイトル", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""
            
            if is_cancelled:
                task1_label = "[タスク1: 上場延期/撤回/廃止の事由分析]"
                task1_structure = "1文段: 簡単なビジネスモデル概要\n2文段: Google検索を通じた上場延期・撤回・廃止の決定的な理由 (※検索で明確な理由が見つからない場合は、既存の一般的なビジネスモデル要約で代替すること)\n3文段: 該当企業の今後の見通し"
            else:
                task1_label = "[タスク1: ビジネスモデルの深層分析]"
                task1_structure = "1文段: ビジネスモデルおよび競争優位性\n2文段: 財務状況および公募資金の使途\n3文段: 今後の見通しおよび投資意見"

        elif lang_code == 'en':
            sys_prompt = "You are a senior analyst at a top-tier brokerage research center. You MUST write strictly in English."
            task2_label = "[Task 2: Latest News Collection]"
            target_lang = "English"
            lang_instruction = "Your entire response MUST be in English only."
            json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "Same as English Title", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""
            
            if is_cancelled:
                task1_label = "[Task 1: Analysis of IPO Delay/Withdrawal Reasons]"
                task1_structure = "Paragraph 1: Brief business model overview.\nParagraph 2: The exact reasons and background for the IPO delay, withdrawal, or delisting based on search. (*If a clear reason cannot be found, fallback to the standard business model summary*)\nParagraph 3: Future outlook and current status."
            else:
                task1_label = "[Task 1: Deep Business Model Analysis]"
                task1_structure = "Paragraph 1: Business model and competitive advantage.\nParagraph 2: Financial status and use of proceeds.\nParagraph 3: Future outlook and investment opinion."

        elif lang_code == 'zh':
            sys_prompt = "您是顶尖券商研究中心的高级分析师。必须只用简体中文编写。"
            task2_label = "[任务2: 收集最新新闻]"
            target_lang = "简体中文(Simplified Chinese)"
            lang_instruction = "必须只用自然流畅的简体中文编写。"
            json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "中文标题", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""
            
            if is_cancelled:
                task1_label = "[任务1: 上市推迟/撤回原因深度分析]"
                task1_structure = "第一段：企业简要商业模式概述\n第二段：通过搜索找出的上市推迟、撤回或退市的确切原因 (※如果搜索不到明确原因，请使用常规商业模式摘要代替)\n第三段：企业未来展望及后续计划"
            else:
                task1_label = "[任务1: 商业模式深度分析]"
                task1_structure = "第一段：商业模式及竞争优势\n第二段：财务状况及募资用途\n第三段：未来展望及投资意见"

        else:
            sys_prompt = "당신은 최고 수준의 증권사 리서치 센터의 시니어 애널리스트입니다. 반드시 한국어로 작성하세요."
            task2_label = "[작업 2: 최신 뉴스 수집]"
            target_lang = "한국어(Korean)"
            lang_instruction = "반드시 자연스러운 한국어만 사용하세요."
            json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "한국어로 번역된 제목", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""
            
            if is_cancelled:
                task1_label = "[작업 1: 상장 연기/철회/폐지 사유 집중 분석]"
                task1_structure = "1문단: 기업의 간략한 비즈니스 모델 요약\n2문단: 구글 검색을 통한 상장 연기/철회/폐지의 결정적 사유 및 배경 (※ 만약 명확한 철회/폐지 사유가 검색되지 않으면, 기존의 일반적인 비즈니스 모델 요약으로 대체할 것)\n3문단: 해당 기업의 향후 전망 및 현재 상태"
            else:
                task1_label = "[작업 1: 비즈니스 모델 심층 분석]"
                task1_structure = "1문단: 비즈니스 모델 및 경쟁 우위\n2문단: 재무 현황 및 공모 자금 활용\n3문단: 향후 전망 및 투자 의견"

        # 💡 [핵심 수정] AI가 게으름 피우지 못하게 강력한 검색 지시어 추가
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

        {task2_label}
        - 🚨 [강제 명령] 당신의 과거 지식에 의존하지 마십시오! 반드시 내장된 구글 검색 도구(google_search_retrieval)를 지금 즉시 작동시켜야 합니다.
        - 검색 키워드: "{company_name} {ticker} news {current_year}"
        - 위 키워드로 검색하여 오늘 날짜({current_date}) 기준 가장 최신 기사(최대 1~3개월 이내) 5개를 찾아내십시오. 
        - 검색 결과가 없다면 지어내지 말고 뉴스 리스트를 비워두십시오. 환각(Hallucination)을 엄격히 금지합니다.
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
                
                if lang_code != 'ko':
                    check_text = full_text.replace("긍정", "").replace("부정", "").replace("일반", "")
                    if re.search(r'[가-힣]', check_text):
                        time.sleep(1); continue 
                
                biz_analysis = full_text.split("<JSON_START>")[0].strip()
                biz_analysis = re.sub(r'#.*', '', biz_analysis).strip()
                paragraphs = [p.strip() for p in biz_analysis.split('\n') if len(p.strip()) > 20]
                
                indent_size = "14px" if lang_code == "ko" else "0px"
                html_output = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in paragraphs])
                
                news_list = []
                if "<JSON_START>" in full_text:
                    try: 
                        json_part = full_text.split("<JSON_START>")[1].split("<JSON_END>")[0].strip()
                        news_list = json.loads(json_part).get("news", [])
                        # [최신 뉴스 정렬 로직] 
                        news_list.sort(key=lambda x: x.get('date', '1970-01-01'), reverse=True)
                    except: pass
                    
                batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": json.dumps({"html": html_output, "news": news_list}, ensure_ascii=False), "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
                break
            except:
                time.sleep(1)

def run_tab4_analysis(ticker, company_name):
    """Tab 4: 월가 기관 분석"""
    if not model: return False
    
    for lang_code, _ in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Tab4_{lang_code}"
        
        LANG_MAP = {
            'ko': '한국어 (Korean)',
            'en': '영어 (English)',
            'ja': '일본어 (Japanese)',
            'zh': '简体中文 (Simplified Chinese)'
        }
        target_lang = LANG_MAP.get(lang_code, '한국어 (Korean)')

        if lang_code == 'ja':
            lang_instruction = "必ず日本語(Japanese)のみで作成してください。すべての文章は日本語である必要があります。韓国語は絶対に混ぜないでください。"
            json_format = """
            "summary": "日本語での専門的な3行要約",
            "pro_con": "**Pros(長所)**:\\n- 内容\\n\\n**Cons(短所)**:\\n- 内容 (必ず日本語で)",
            """
        elif lang_code == 'en':
            lang_instruction = "Respond strictly in English. Do not mix Korean. All sentences must be in English."
            json_format = """
            "summary": "Professional 3-line summary in English",
            "pro_con": "**Pros**:\\n- Details\\n\\n**Cons**:\\n- Details (all in English)",
            """
        elif lang_code == 'zh':
            lang_instruction = "必须只用简体中文(Simplified Chinese)编写。绝对不能混用韩语。"
            json_format = """
            "summary": "专业中文三行摘要",
            "pro_con": "**Pros(优点)**:\\n- 内容\\n\\n**Cons(缺点)**:\\n- 内容 (必须用中文)",
            """
        else:
            lang_instruction = "반드시 한국어로 작성하세요."
            json_format = """
            "summary": "한국어 전문 3줄 요약",
            "pro_con": "**Pros(장점)**:\\n- 내용\\n\\n**Cons(단점)**:\\n- 내용 (한국어)",
            """

        prompt = f"""
        당신은 월가 출신의 IPO 전문 분석가입니다. 
        구글 검색 도구를 사용하여 {company_name} ({ticker})에 대한 최신 기관 리포트(Seeking Alpha, Renaissance Capital 등)를 찾아 심층 분석하세요.

        [작성 지침]
        1. 언어: 반드시 '{target_lang}'로 답변하세요. {lang_instruction}
        2. 분석 깊이: 단순 사실 나열이 아닌 구체적인 수치나 근거를 들어 전문적으로 분석하세요.
        3. Pros & Cons: 긍정적 요소(Pros) 2가지와 부정적 요소(Cons) 2가지를 명확히 구분하여 서술하세요.
        4. Rating: 반드시 (Strong Buy/Buy/Hold/Sell) 중 하나로 선택하세요. (이 값은 영어로 유지)
        5. Summary: 전문적인 톤으로 5줄 이내로 핵심만 간결하게 작성하세요.
        6. 링크 위치 구분: 본문 안에는 절대 URL을 넣지 말고, 반드시 "links" 리스트 안에만 정확히 기입하세요.

        <JSON_START>
        {{
            "rating": "Buy/Hold/Sell 중 하나",
            {json_format}
            "links": [ {{"title": "검색된 리포트 제목", "link": "URL"}} ]
        }}
        <JSON_END>
        """
        
        # 💡 [방어막 추가] 최대 3회 재시도 루프
        for attempt in range(3):
            try:
                response = model.generate_content(prompt)
                full_text = response.text
                
                if lang_code != 'ko':
                    if re.search(r'[가-힣]', full_text):
                        time.sleep(1); continue # 한글 감지 시 재시도
                
                match = re.search(r'<JSON_START>(.*?)<JSON_END>', full_text, re.DOTALL)
                if match:
                    clean_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', match.group(1).strip())
                    batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": clean_str, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
                break # 성공 시 루프 탈출
            except:
                time.sleep(1)

def run_tab3_analysis(ticker, company_name, metrics):
    """Tab 3: 재무 데이터 분석 리포트"""
    if not model: return False
    
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Financial_Report_Tab3_{lang_code}"
        
        prompt = f"""
        당신은 CFA 자격을 보유한 수석 주식 애널리스트입니다.
        아래 재무 데이터를 바탕으로 {company_name} ({ticker})에 대한 투자 분석 리포트를 작성하세요.
        재무 데이터: {metrics}

        [작성 가이드]
        1. 언어: 반드시 '{target_lang}'로 작성하세요.
        2. 형식: 아래 4가지 소제목을 반드시 사용하여 단락을 구분하세요. (소제목 자체도 {target_lang}에 맞게 번역하세요)
           **[Valuation & Market Position]**
           **[Operating Performance]**
           **[Risk & Solvency]**
           **[Analyst Conclusion]**
        3. 내용: 수치를 단순 나열하지 말고, 수치가 갖는 함의(프리미엄, 효율성, 리스크 등)를 해석하세요. 분량은 10~12줄 내외로 핵심만 요약하세요.
        """
        
        # 💡 [방어막 추가] 최대 3회 재시도 루프
        for attempt in range(3):
            try:
                response = model.generate_content(prompt)
                res_text = response.text
                
                if lang_code != 'ko':
                    if re.search(r'[가-힣]', res_text):
                        time.sleep(1); continue # 한글 감지 시 재시도
                        
                batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": res_text, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
                break # 성공 시 루프 탈출
            except:
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
            new_alerts.append({"ticker": ticker, "alert_type": "UPCOMING", "title": f"🚀 상장 D-3: {name}", "message": f"{ticker} 종목 상장이 3일 앞으로 다가왔습니다. 월가 기관 평가를 확인하세요."})
        
        if ipo_date + timedelta(days=180) == today + timedelta(days=7):
            new_alerts.append({"ticker": ticker, "alert_type": "LOCKUP", "title": f"🚨 락업 해제 주의: {ticker}", "message": "7일 뒤 내부자 보호예수 물량이 해제됩니다. 오버행 이슈에 대비하세요."})

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
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1D", "title": f"⚡ 1일 단기 급등: {ticker}", "message": f"전일 대비 {chg_1d:.1f}% 상승하며 강력한 단기 수급이 유입되었습니다."})
            
            if len(hist) >= 5:
                p_1w = hist['Close'].iloc[-5]
                chg_1w = ((current_p - p_1w) / p_1w) * 100
                if chg_1w >= 20.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1W", "title": f"📈 1주 추세 돌파: {ticker}", "message": f"최근 1주일간 {chg_1w:.1f}% 상승하며 단기 우상향 추세를 형성했습니다."})

            if len(hist) >= 10:
                p_2w = hist['Close'].iloc[-10]
                chg_2w = ((current_p - p_2w) / p_2w) * 100
                if chg_2w >= 30.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_2W", "title": f"🚀 2주 연속 상승: {ticker}", "message": f"최근 2주간 {chg_2w:.1f}% 상승하며 시장の 강한 주목을 받고 있습니다."})

            if len(hist) >= 20:
                p_4w = hist['Close'].iloc[-20]
                chg_4w = ((current_p - p_4w) / p_4w) * 100
                if chg_4w >= 40.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_4W", "title": f"🔥 4주 모멘텀 포착: {ticker}", "message": f"최근 4주간 {chg_4w:.1f}% 급등하며 견고한 상승 모멘텀을 증명했습니다."})

            if len(hist) >= 22:
                p_1mo = hist['Close'].iloc[-22]
                chg_1mo = ((current_p - p_1mo) / p_1mo) * 100
                if chg_1mo >= 45.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1M", "title": f"🌟 1개월 랠리: {ticker}", "message": f"최근 1개월간 {chg_1mo:.1f}% 상승하며 월간 최고 주도주로 부상했습니다."})

            if len(hist) >= 63:
                p_3m = hist['Close'].iloc[-63]
                chg_3m = ((current_p - p_3m) / p_3m) * 100
                if chg_3m >= 60.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_3M", "title": f"💎 3개월 중기 폭등: {ticker}", "message": f"3개월 전 대비 {chg_3m:.1f}% 상승하며 완벽한 장기 우상향 궤도에 진입했습니다."})

            if len(hist) >= 126:
                p_6m = hist['Close'].iloc[-126]
                chg_6m = ((current_p - p_6m) / p_6m) * 100
                if chg_6m >= 80.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_6M", "title": f"🦄 6개월 퀀텀점프: {ticker}", "message": f"6개월 전 대비 {chg_6m:.1f}% 상승하며 하반기 섹터 대장주로 확인되었습니다."})

            if len(hist) >= 250:
                p_1y = hist['Close'].iloc[0]
                chg_1y = ((current_p - p_1y) / p_1y) * 100
                if chg_1y >= 150.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1Y", "title": f"👑 연간 슈퍼 유니콘: {ticker}", "message": f"지난 1년간 {chg_1y:.1f}%라는 압도적인 수익률을 기록 중입니다. 진정한 텐배거 후보입니다."})
        except: pass

        # --- 3. 공모가 돌파 시그널 ---
        try: ipo_p = float(str(row.get('price', '0')).replace('$', '').split('-')[0])
        except: ipo_p = 0.0

        if ipo_p > 0 and 0 <= (current_p - ipo_p) / ipo_p < 0.03:
            new_alerts.append({"ticker": ticker, "alert_type": "REBOUND", "title": f"🔥 공모가 회복: {ticker}", "message": f"침체기를 끝내고 주가가 다시 공모가(${ipo_p}) 위로 올라섰습니다. 바닥 확인 신호입니다."})

    # [Step 3] DB 전송 및 중복 방지
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

    print("\n📋 [stock_cache] 명단 업데이트 시작...")
    now_iso = datetime.now().isoformat()
    stock_list = []
    
    for _, row in df.iterrows():
        stock_list.append({
            "symbol": str(row['symbol']),
            "name": str(row['name']) if pd.notna(row['name']) else "Unknown",
            "last_updated": now_iso 
        })
    
    batch_upsert("stock_cache", stock_list, on_conflict="symbol")
    update_macro_data(df)
    
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
        past_all = df[df['dt'] <= today].copy()
        def calc_return(row):
            try:
                ipo_p = float(str(row.get('price', '0')).replace('$','').split('-')[0])
                curr_p = price_map.get(row['symbol'], 0.0)
                if ipo_p > 0 and curr_p > 0: return (curr_p - ipo_p) / ipo_p * 100
                return -9999.0
            except: return -9999.0
        past_all['return'] = past_all.apply(calc_return, axis=1)
        top_50 = past_all.sort_values(by='return', ascending=False).head(50)
        target_symbols.update(top_50['symbol'].tolist())
        print(f"   -> 수익률 상위(전체 중): 50개 (1위: {top_50.iloc[0]['symbol']} {top_50.iloc[0]['return']:.1f}%)")
    except Exception as e:
        print(f"   ⚠️ 수익률 계산 에러: {e}")

    print(f"✅ 최종 분석 대상: 총 {len(target_symbols)}개 종목 (중복 제거)")

    target_df = df[df['symbol'].isin(target_symbols)]
    total = len(target_df)
    
    # 💡 [신규 추가] 반복문 시작 전, SEC CIK 매핑 데이터를 딱 한 번만 로드합니다.
    print("\n🏛️ SEC EDGAR CIK 매핑 데이터 로드 중 (API 최적화)...")
    # 방금 수정한 새로운 함수 호출 (두 가지 사전 반환)
    cik_mapping, name_to_ticker_map = get_sec_master_mapping()
    print(f"✅ 총 {len(cik_mapping)}개의 SEC 식별번호 확보 완료.")
    
    print(f"\n🤖 AI 심층 분석 시작 (총 {total}개 종목 다국어 캐싱)...")
    
    for idx, row in target_df.iterrows():
        original_symbol = row.get('symbol')
        name = row.get('name')
        
        # 💡 [핵심 교정] 이름 정규화를 통해 공식 티커를 찾아냅니다.
        clean_name = normalize_company_name(name)
        official_symbol = name_to_ticker_map.get(clean_name, original_symbol)
        
        # 💡 [캐시 불일치 방어막] app.py를 위해 옛날 티커도 진짜 CIK 번호와 연결해 줍니다.
        if original_symbol != official_symbol:
            print(f"🔧 [티커 교정 작동] {name}: {original_symbol} ➡️ {official_symbol}")
            if official_symbol in cik_mapping:
                cik_mapping[original_symbol] = cik_mapping[official_symbol]
        
        print(f"[{idx+1}/{total}] {original_symbol} 분석 중...", flush=True)
        
        try:
            c_status = row.get('status', 'Active')
            c_date = row.get('date', None)
            
            # AI 분석(Tab 0, 1, 4)은 app.py가 찾을 수 있게 무조건 'original_symbol'로 캐싱!
            run_tab1_analysis(original_symbol, name, c_status)
            run_tab0_analysis(original_symbol, name, c_status, c_date, cik_mapping)
            run_tab4_analysis(original_symbol, name)
            
            # 💡 [핵심] 단, 주가(Tab 3)를 가져오는 야후 파이낸스는 무조건 교정된 'official_symbol'을 찔러야 합니다!
            try:
                tk = yf.Ticker(official_symbol)
                # 저장할 때의 키값은 original_symbol로 유지하여 app.py와 동기화
                run_tab3_analysis(original_symbol, name, {"pe": tk.info.get('forwardPE', 0)})
            except: pass
            
            time.sleep(1.2)
            
        except Exception as e:
            print(f"⚠️ {original_symbol} 분석 건너뜀: {e}")
            continue

    # 모든 AI 분석이 완료된 후, 전체 캘린더를 대상으로 알림 엔진 가동
    run_premium_alert_engine(df)
            
    print(f"\n🏁 모든 작업 종료: {datetime.now()}")

if __name__ == "__main__":
    main()
