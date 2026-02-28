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

    # 💡 [핵심] 12가지 문서의 세부 지시사항을 4개 국어로 완벽 번역 매핑
    def get_localized_meta(lang, doc_type):
        meta_dict = {
            "ko": {
                "S-1": {"p": "Risk Factors(특이 소송/규제), Use of Proceeds(자금 용도의 건전성), MD&A(성장 동인)", "s": "1문단: 발견된 가장 중요한 투자 포인트\n2문단: 실질적 성장 가능성과 재무적 의미\n3문단: 핵심 리스크 1가지와 그 파급 효과 및 대응책"},
                "S-1/A": {"p": "Pricing Terms(수요예측 분위기), Dilution(신규 투자자 희석률), Changes(이전 제출본과의 차이점)", "s": "1문단: 이전 S-1 대비 변경된 핵심 사항\n2문단: 제시된 공모가 범위의 적정성 및 수요예측 분위기\n3문단: 기존 주주 가치 희석 정도와 투자 매력도"},
                "F-1": {"p": "Foreign Risk(지정학적 리스크), Accounting(GAAP 차이), ADS(주식 예탁 증서 구조)", "s": "1문단: 기업이 글로벌 시장에서 가진 독보적인 경쟁 우위\n2문단: 환율, 정치, 회계 등 해외 기업 특유의 리스크\n3문단: 미국 예탁 증서(ADS) 구조가 주주 권리에 미치는 영향"},
                "FWP": {"p": "Graphics(시장 점유율 시각화), Strategy(미래 핵심 먹거리), Highlights(경영진 강조 사항)", "s": "1문단: 경영진が 로드쇼에서 강조하는 미래 성장 비전\n2문단: 경쟁사 대비 기술적/사업적 차별화 포인트\n3문단: 자료 톤앤매너로 유추할 수 있는 시장 공략 의지"},
                "424B4": {"p": "Underwriting(주관사 등급), Final Price(기관 배정 물량), IPO Outcome(최종 공모 결과)", "s": "1문단: 확정 공모가의 위치와 시장 수요 해석\n2문단: 확정된 조달 자금의 투입 우선순위\n3문단: 주관사단 및 배정 물량 바탕 상장 초기 유통물량 예측"},
                "RW": {"p": "Withdrawal Reason(철회 사유), Market Condition(시장 환경 악화 여부), Future Plans(향후 계획)", "s": "1문단: 상장 철회(Withdrawal) 결정적 사유 및 배경\n2문단: 상장 철회가 기업 재무 및 기존 투자자에게 미치는 영향\n3문단: 향후 재상장 또는 M&A 등 향후 계획"},
                "Form 25": {"p": "Delisting Reason(상장폐지 사유), M&A(인수합병 여부), Shareholder Impact(주주 영향)", "s": "1문단: 상장 폐지(Delisting)의 정확한 사유(인수합병, 자진상폐, 규정위반 등)\n2문단: 상장 폐지 후 기존 주주의 권리 및 주식 처리 방안\n3문단: 장외시장(OTC) 거래 가능성 및 향후 기업 상태"},
                "10-K": {"p": "Business Overview(사업 개요), Risk Factors(위험 요소), MD&A(경영진 분석)", "s": "1문단: 지난 1년간의 핵심 사업 성과 및 비즈니스 모델 변화\n2문단: 경영진이 강조하는(MD&A) 주요 재무 실적과 당면 과제\n3문단: 새롭게 부각된 위험 요소(Risk Factors) 및 장기 전망"},
                "10-Q": {"p": "Quarterly Earnings(분기 실적), Short-term Guidance(단기 가이던스), Recent Changes(최근 변동사항)", "s": "1문단: 해당 분기의 매출 및 이익 달성 현황 요약\n2문단: 전년 동기 대비 주요 변화와 그 원인\n3문단: 다음 분기 가이던스 및 단기 리스크 요인"},
                "BS": {"p": "Assets(자산 구성), Liabilities(부채 및 상환 능력), Equity(자본 건전성)", "s": "1문단: 유동 자산과 비유동 자산의 핵심 구성비 및 특징\n2문단: 부채 비율, 이자 발생 부채 등 재무 리스크 진단\n3문단: 자본 충실도 및 종합적인 재무 건전성(Solvency) 평가"},
                "IS": {"p": "Revenue Growth(매출 성장), Margins(이익률), EPS(주당순이익)", "s": "1문단: 탑라인(매출) 성장 추이와 주요 견인 사업부 분석\n2문단: 매출원가 및 판관비 통제에 따른 영업이익률/순이익률 평가\n3문단: 최종 수익성(EPS 등) 및 이익의 질(Quality of Earnings) 요약"},
                "CF": {"p": "Operating CF(영업현금), Investing CF(투자현금), Financing CF(재무현금)", "s": "1문단: 영업활동을 통한 순수 현금 창출 능력 평가\n2문단: CAPEX 등 투자활동 현금흐름의 공격성 및 방향성\n3문단: 차입/상환 및 배당 등 재무활동과 최종 잉여현금흐름(FCF) 상태"}
            },
            "en": {
                "S-1": {"p": "Risk Factors, Use of Proceeds (Soundness), MD&A (Growth Drivers)", "s": "Paragraph 1: The most important investment points found in this document.\nParagraph 2: Real business growth potential and financial implications.\nParagraph 3: One core risk, its ripple effects, and countermeasures."},
                "S-1/A": {"p": "Pricing Terms (Demand sentiment), Dilution, Changes from previous filing", "s": "Paragraph 1: Core changes compared to the previous S-1.\nParagraph 2: Appropriateness of pricing terms and expected demand.\nParagraph 3: Dilution for new investors and investment attractiveness."},
                "F-1": {"p": "Foreign Risk (Geopolitical), Accounting (GAAP diff), ADS (Depository Receipt)", "s": "Paragraph 1: The company's unique competitive advantage in the global market.\nParagraph 2: Specific risks for foreign companies (FX, politics, accounting).\nParagraph 3: Impact of the ADS structure on shareholder rights."},
                "FWP": {"p": "Graphics (Market share), Strategy (Future drivers), Highlights (Management focus)", "s": "Paragraph 1: Future growth vision emphasized by management in the roadshow.\nParagraph 2: Technical/business differentiation points against competitors.\nParagraph 3: Market penetration willingness inferred from the tone and manner."},
                "424B4": {"p": "Underwriting (Tier), Final Price (Allocation), IPO Outcome", "s": "Paragraph 1: Interpretation of the final IPO price and market demand.\nParagraph 2: Priority of how the raised funds will be used.\nParagraph 3: Expected initial float based on underwriters and lock-ups."},
                "RW": {"p": "Withdrawal Reason, Market Condition, Future Plans", "s": "Paragraph 1: The decisive reason and background for the IPO withdrawal.\nParagraph 2: Impact of the withdrawal on corporate finance and existing investors.\nParagraph 3: Future plans such as M&A or re-attempting IPO."},
                "Form 25": {"p": "Delisting Reason, M&A, Shareholder Impact", "s": "Paragraph 1: Exact reason for delisting (M&A, voluntary, violations, etc.).\nParagraph 2: Impact on shareholder rights and stock treatment after delisting.\nParagraph 3: Possibility of OTC trading and future corporate status."},
                "10-K": {"p": "Business Overview, Risk Factors, MD&A", "s": "Paragraph 1: Core business performance and model changes over the past year.\nParagraph 2: Key financial results and challenges highlighted in MD&A.\nParagraph 3: Newly highlighted Risk Factors and long-term outlook."},
                "10-Q": {"p": "Quarterly Earnings, Short-term Guidance, Recent Changes", "s": "Paragraph 1: Summary of revenue and profit achieved in this quarter.\nParagraph 2: Major YoY changes and their causes.\nParagraph 3: Guidance for the next quarter and short-term risks."},
                "BS": {"p": "Assets, Liabilities, Equity", "s": "Paragraph 1: Key composition and characteristics of current and non-current assets.\nParagraph 2: Diagnosis of financial risks such as debt ratio and interest-bearing debt.\nParagraph 3: Capital adequacy and comprehensive solvency evaluation."},
                "IS": {"p": "Revenue Growth, Margins, EPS", "s": "Paragraph 1: Top-line revenue growth trend and key driving business units.\nParagraph 2: Evaluation of operating/net margin based on cost control.\nParagraph 3: Final profitability (EPS) and summary of Quality of Earnings."},
                "CF": {"p": "Operating CF, Investing CF, Financing CF", "s": "Paragraph 1: Evaluation of pure cash generation through operating activities.\nParagraph 2: Aggressiveness and direction of investing cash flows like CAPEX.\nParagraph 3: Financing activities and final Free Cash Flow (FCF) status."}
            },
            "ja": {
                "S-1": {"p": "Risk Factors (特異な訴訟・規制), Use of Proceeds (資金使途の健全性), MD&A (成長要因)", "s": "第1段落：この文書で確認できる最も重要な投資ポイント\n第2段落：実質的な成長可能性と財務的意味\n第3段落：核心的なリスク1つ、その波及効果および対応策"},
                "S-1/A": {"p": "Pricing Terms (需要予測), Dilution (希薄化), Changes (前回からの変更点)", "s": "第1段落：前回のS-1からの主な変更点\n第2段落：提示された公募価格帯の妥当性と需要予測の雰囲気\n第3段落：既存株主の価値希薄化の程度と投資魅力度"},
                "F-1": {"p": "Foreign Risk (地政学的リスク), Accounting (GAAP差異), ADS (米国預託証券)", "s": "第1段落：企業がグローバル市場で持つ独自の競争優位性\n第2段落：為替、政治、会計など海外企業特有のリスク\n第3段落：米国預託証券（ADS）構造が株主の権利に与える影響"},
                "FWP": {"p": "Graphics (市場シェアの視覚化), Strategy (未来の成長エンジン), Highlights (経営陣の強調点)", "s": "第1段落：経営陣がロードショーで強調する未来の成長ビジョン\n第2段落：競合他社と比較した技術的・事業的な差別化ポイント\n第3段落：資料のトーン＆マナーから推測される市場攻略への意欲"},
                "424B4": {"p": "Underwriting (主幹事ランク), Final Price (機関配分), IPO Outcome", "s": "第1段落：確定した公募価格の位置づけと市場需要の解釈\n第2段落：確定した調達資金の投入優先順位\n第3段落：引受シンジケートおよび配分に基づく上場初期の流通株式予測"},
                "RW": {"p": "Withdrawal Reason (撤回の理由), Market Condition (市場環境の悪化), Future Plans (今後の計画)", "s": "第1段落：該当企業の上場撤回（Withdrawal）の決定的な理由と背景\n第2段落：上場撤回が企業の財務および既存投資家に与える影響\n第3段落：今後の再上場またはM&Aなどの今後の計画"},
                "Form 25": {"p": "Delisting Reason (上場廃止の理由), M&A (買収合併), Shareholder Impact (株主への影響)", "s": "第1段落：上場廃止（Delisting）の正確な理由（M&A、自主的、規定違反など）\n第2段落：上場廃止後の既存株主の権利および株式の取り扱い\n第3段落：店頭市場（OTC）での取引可能性および今後の企業状態"},
                "10-K": {"p": "Business Overview (事業概要), Risk Factors (リスク要因), MD&A (経営陣の分析)", "s": "第1段落：過去1年間の核心的な事業成果およびビジネスモデルの変化\n第2段落：経営陣が強調する主要な財務実績と直面する課題\n第3段落：新たに浮上したリスク要因および長期的な展望"},
                "10-Q": {"p": "Quarterly Earnings (四半期業績), Short-term Guidance, Recent Changes", "s": "第1段落：該当四半期の売上および利益達成状況の要約\n第2段落：前年同期比の主な変化とその原因\n第3段落：次四半期のガイダンスおよび短期的なリスク要因"},
                "BS": {"p": "Assets (資産構成), Liabilities (負債と返済能力), Equity (資本の健全性)", "s": "第1段落：流動資産と非流動資産の主な構成比と特徴\n第2段落：負債比率、有利子負債などの財務リスクの診断\n第3段落：自己資本の充実度および総合的な財務健全性（Solvency）の評価"},
                "IS": {"p": "Revenue Growth (売上成長), Margins (利益率), EPS (一株当たり利益)", "s": "第1段落：売上の成長推移と主要な牽引事業部門の分析\n第2段落：売上原価および販管費の統制に基づく利益率の評価\n第3段落：最終的な収益性（EPSなど）と利益の質（Quality of Earnings）の要約"},
                "CF": {"p": "Operating CF (営業CF), Investing CF (投資CF), Financing CF (財務CF)", "s": "第1段落：営業活動を通じた純粋な現金創出力の評価\n第2段落：CAPEXなど投資活動キャッシュフローの攻撃性と方向性\n第3段落：借入・返済や配当などの財務活動と、最終的なフリーキャッシュフロー状態"}
            },
            "zh": {
                "S-1": {"p": "Risk Factors (特殊诉讼/监管), Use of Proceeds (资金用途), MD&A (增长驱动力)", "s": "第一段：该文件中最重要的投资亮点\n第二段：实质性增长潜力及其财务意义\n第三段：一个核心风险，其连锁反应及应对措施"},
                "S-1/A": {"p": "Pricing Terms (定价氛围), Dilution (股权稀释), Changes (与前次差异)", "s": "第一段：与之前S-1相比的核心变化\n第二段：定价区间的合理性及需求氛围分析\n第三段：现有股东的价值稀释程度及投资吸引力"},
                "F-1": {"p": "Foreign Risk (地缘政治风险), Accounting (GAAP差异), ADS (存托凭证)", "s": "第一段：企业在全球市场中独有的竞争优势\n第二段：外汇、政治、会计等海外企业特有风险分析\n第三段：美国存托凭证（ADS）结构对股东权利的影响"},
                "FWP": {"p": "Graphics (市场份额), Strategy (未来引擎), Highlights (管理层强调)", "s": "第一段：管理层在路演中强调的未来增长愿景\n第二段：与竞争对手相比的技术/业务差异化优势\n第三段：从资料的基调推测的市场开拓意愿"},
                "424B4": {"p": "Underwriting (承销商等级), Final Price (机构配售), IPO Outcome", "s": "第一段：最终发行价的定位及市场需求解读\n第二段：确定募集资金的投入优先顺序\n第三段：基于承销团队及配售情况的上市初期流通股预测"},
                "RW": {"p": "Withdrawal Reason (撤回原因), Market Condition (市场恶化), Future Plans (未来计划)", "s": "第一段：该企业撤回上市的决定性原因及背景\n第二段：撤回上市对企业财务及现有投资者的影响\n第三段：未来再次上市或并购等计划"},
                "Form 25": {"p": "Delisting Reason (退市原因), M&A (并购), Shareholder Impact (股东影响)", "s": "第一段：退市的准确原因（并购、自愿退市、违规等）\n第二段：退市后现有股东的权利及股票处理方案\n第三段：场外市场（OTC）交易的可能性及未来企业状态"},
                "10-K": {"p": "Business Overview (业务概览), Risk Factors (风险因素), MD&A (管理层分析)", "s": "第一段：过去一年的核心业务成果及商业模式变化\n第二段：管理层强调的主要财务业绩和面临的挑战\n第三段：新出现的风险因素及长期展望"},
                "10-Q": {"p": "Quarterly Earnings (季度业绩), Short-term Guidance, Recent Changes", "s": "第一段：该季度营收及利润达成情况的摘要\n第二段：同比主要变化及其原因\n第三段：下季度业绩指引及短期风险因素"},
                "BS": {"p": "Assets (资产构成), Liabilities (偿债能力), Equity (资本健康度)", "s": "第一段：流动资产与非流动资产的核心构成比及特征\n第二段：负债率、有息负债等财务风险诊断\n第三段：资本充足度及综合偿债能力评估"},
                "IS": {"p": "Revenue Growth (营收增长), Margins (利润率), EPS (每股收益)", "s": "第一段：营收增长趋势及主要驱动业务部门分析\n第二段：基于成本和费用控制的营业利润率/净利率评估\n第三段：最终盈利能力（EPS）及盈利质量总结"},
                "CF": {"p": "Operating CF (经营CF), Investing CF (投资CF), Financing CF (筹资CF)", "s": "第一段：通过经营活动创造纯现金的能力评估\n第二段：资本支出等投资现金流的激进程度及方向\n第三段：借款/还款、分红等筹资活动及最终自由现金流状况"}
            }
        }
        return meta_dict.get(lang, meta_dict['ko']).get(doc_type, meta_dict['ko']['S-1'])

    # 💡 [핵심] 출력 포맷팅 규칙도 언어별로 완벽 번역
    def get_format_instruction(lang):
        if lang == 'en':
            return """[Output Format Rules - STRICTLY FOLLOW]
            - Each paragraph MUST begin with a translated **[Heading]**, followed by a space and the content. Do NOT line break after the heading.
            - [Length] Write exactly 4 to 5 detailed sentences per paragraph to make it rich in content.
            - Correct Example: **[Investment Point]** The company's main advantage is...
            - Forbidden: **[Investment Point - 투자포인트]** (DO NOT mix Korean)
            - Forbidden: **[Investment Point]** \n The company... (DO NOT line break)"""
        elif lang == 'ja':
            return """[出力形式および翻訳規則 - 厳守すること]
            - 各段落の始めは必ず日本語に翻訳された **[見出し]** から始め、改行せずにスペースを1つ空けて本文を続けてください。
            - [分量条件] 単なる要約ではありません。各段落ごとに必ず4〜5文程度の詳細で充実した内容を記述してください。
            - 正しい例：**[投資ポイント]** 同社の最大の強みは...
            - 禁止例（韓国語の併記禁止）：**[投資ポイント - 투자포인트]** (絶対に混ぜないこと)
            - 禁止例（見出し後の改行禁止）：**[投資ポイント]** \n 同社は... (X)"""
        elif lang == 'zh':
            return """[输出格式及翻译规则 - 必须严格遵守]
            - 每个段落的开头必须是中文的 **[副标题]**，不要换行，空一格后直接接着写正文。
            - [篇幅要求] 这不是简短摘要！每个段落必须写4到5句详细且充实的内容。
            - 正确示例：**[投资要点]** 该公司的最大优势是...
            - 禁止示例（严禁标注韩语）：**[投资要点 - 투자포인트]** (严禁混用韩语)
            - 禁止示例（副标题后严禁换行）：**[投资要点]** \n 该公司... (X)"""
        else:
            return """[출력 형식 및 번역 규칙 - 반드시 지킬 것]
            - 각 문단의 시작은 반드시 **[소제목]**으로 시작한 뒤, 줄바꿈 없이 한 칸 띄우고 바로 내용을 이어가세요.
            - [분량 조건] 전체 요약이 아닙니다! 각 문단마다 반드시 4~5문장씩 내용을 상세하고 풍성하게 채워 넣으세요.
            - 금지 예시(소제목 뒤 줄바꿈 절대 금지): **[투자 포인트]** \n 해당 기업은... (X)"""

    for topic in target_topics:
        sec_fact_prompt = ""
        sec_search_target = "10-K" if topic in ["BS", "IS", "CF"] else topic
        
        if cik:
            filed_date = check_sec_specific_filing(cik, sec_search_target)
            if filed_date:
                sec_fact_prompt = f"\n[SEC FACT CHECK] The company officially filed '{sec_search_target}' on {filed_date}."
            else:
                sec_fact_prompt = f"\n[SEC FACT CHECK] '{sec_search_target}' is not found in SEC EDGAR. Use Google search to summarize the current status."
        
        for lang_code, target_lang in SUPPORTED_LANGS.items():
            cache_key = f"{company_name}_{topic}_Tab0_v13_{lang_code}"
            
            try:
                res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time_str).execute()
                if res.data: continue 
            except: pass

            # 동적 지시사항 로드
            meta = get_localized_meta(lang_code, topic)
            format_inst = get_format_instruction(lang_code)

            if lang_code == 'en':
                prompt = f"""You are a senior analyst from Wall Street.
Target: {company_name} - {topic}
Checkpoints: {meta['p']}
{sec_fact_prompt}

[Writing Instructions]
- STRICTLY write entirely in English. DO NOT mix Korean.
- DO NOT introduce yourself.

[Content Structure]
{meta['s']}

{format_inst}"""

            elif lang_code == 'ja':
                prompt = f"""あなたはウォール街出身の専門分析家です。
分析対象: {company_name} - {topic}
チェックポイント: {meta['p']}
{sec_fact_prompt}

[作成指針]
- 必ず自然な日本語のみで作成し、韓国語を絶対に混ぜないでください。
- 自己紹介や挨拶は一切しないでください。

[段落の構成内容]
{meta['s']}

{format_inst}"""

            elif lang_code == 'zh':
                prompt = f"""您是华尔街的专业高级分析师。
分析目标: {company_name} - {topic}
检查重点: {meta['p']}
{sec_fact_prompt}

[编写指南]
- 必须只用流畅的简体中文编写，严禁混用韩语。
- 绝对不要自我介绍。

[段落结构]
{meta['s']}

{format_inst}"""

            else:
                prompt = f"""당신은 월가 출신의 전문 분석가입니다.
분석 대상: {company_name} - {topic}
체크포인트: {meta['p']}
{sec_fact_prompt}

[작성 지침]
- 반드시 한국어로만 작성하세요.
- 자기소개나 인사말은 절대 하지 마세요.

[내용 구성 지침]
{meta['s']}

{format_inst}"""
            
            for attempt in range(3):
                try:
                    response = model.generate_content(prompt)
                    res_text = response.text
                    
                    # 💡 [방어막 작동] 외국어 답변에 한글이 섞이면 파기
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

        if lang_code == 'ja':
            sys_prompt = "あなたは最高レベルの証券会社リサーチセンターのシニアアナリストです。すべての回答は必ず日本語で作成してください。"
            task2_label = "[タスク2: 最新ニュースの収集]"
            target_lang = "日本語(Japanese)"
            lang_instruction = "必ず自然な日本語のみで作成してください。"
            json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "日本語に翻訳されたタイトル", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""
        elif lang_code == 'en':
            sys_prompt = "You are a senior analyst at a top-tier brokerage research center. You MUST write strictly in English."
            task2_label = "[Task 2: Latest News Collection]"
            target_lang = "English"
            lang_instruction = "Your entire response MUST be in English only."
            json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "Same as English Title", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""
        elif lang_code == 'zh':  
            sys_prompt = "您是顶尖券商研究中心的高级分析师。必须只用简体中文编写。"
            task2_label = "[任务2: 收集最新新闻]"
            target_lang = "简体中文(Simplified Chinese)"
            lang_instruction = "必须只用自然流畅的简体中文编写。"
            json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "中文标题", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""
        else:
            sys_prompt = "당신은 최고 수준의 증권사 리서치 센터의 시니어 애널리스트입니다. 반드시 한국어로 작성하세요."
            task2_label = "[작업 2: 최신 뉴스 수집]"
            target_lang = "한국어(Korean)"
            lang_instruction = "반드시 자연스러운 한국어만 사용하세요."
            json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "한국어로 번역된 제목", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""

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
                
                break
            except Exception as e:
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
    
    print("\n🏛️ SEC EDGAR CIK 매핑 데이터 로드 중 (API 최적화)...")
    cik_mapping, name_to_ticker_map = get_sec_master_mapping()
    print(f"✅ 총 {len(cik_mapping)}개의 SEC 식별번호 확보 완료.")
    
    print(f"\n🤖 AI 심층 분석 시작 (총 {total}개 종목 다국어 캐싱)...")
    
    for idx, row in target_df.iterrows():
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
                tk = yf.Ticker(official_symbol)
                # 여기도 official_symbol 로 변경!
                run_tab3_analysis(official_symbol, name, {"pe": tk.info.get('forwardPE', 0)})
            except: pass
            
            time.sleep(1.2)
            
        except Exception as e:
            print(f"⚠️ {original_symbol} 분석 건너뜀: {e}")
            continue

    run_premium_alert_engine(df)
            
    print(f"\n🏁 모든 작업 종료: {datetime.now()}")

if __name__ == "__main__":
    main()
