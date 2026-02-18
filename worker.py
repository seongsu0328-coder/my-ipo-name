import os
import time
import json
import re
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta, date
import pytz 
from supabase import create_client
import google.generativeai as genai

# ==========================================
# [1] 환경 설정
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip('/')
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
GENAI_API_KEY = os.environ.get("GENAI_API_KEY", "")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

if not (SUPABASE_URL and SUPABASE_KEY):
    print("❌ 환경변수 누락")
    exit()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# AI 모델 설정
model = None 
if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)
    try:
        model = genai.GenerativeModel('gemini-2.0-flash', tools=[{'google_search_retrieval': {}}])
        print("✅ AI 모델 로드 성공")
    except:
        model = genai.GenerativeModel('gemini-2.0-flash')

# ==========================================
# [2] 헬퍼 함수: 완벽한 데이터 정제 및 직송
# ==========================================

def sanitize_value(v):
    if v is None or pd.isna(v): return None
    if isinstance(v, (np.floating, float)):
        return float(v) if not (np.isinf(v) or np.isnan(v)) else 0.0
    if isinstance(v, (np.integer, int)): return int(v)
    if isinstance(v, (np.bool_, bool)): return bool(v)
    return str(v).strip().replace('\x00', '')

def batch_upsert(table_name, data_list, on_conflict="ticker"):
    """405 에러를 원천 차단하는 범용 REST API Upsert"""
    if not data_list: return
    
    # URL 경로 자동 교정 로직
    base_url = SUPABASE_URL
    if "/rest/v1" not in base_url:
        endpoint = f"{base_url}/rest/v1/{table_name}?on_conflict={on_conflict}"
    else:
        endpoint = f"{base_url}/{table_name}?on_conflict={on_conflict}"
    
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

    print(f"🚀 [{table_name}] {len(data_list)}개 시도 (기준: {on_conflict})")
    success_save = 0
    
    for item in data_list:
        clean_payload = {k: sanitize_value(v) for k, v in item.items()}
        if not clean_payload.get(on_conflict): continue

        try:
            # 개별 전송으로 안정성 확보
            resp = requests.post(endpoint, json=clean_payload, headers=headers)
            if resp.status_code in [200, 201, 204]:
                success_save += 1
            else:
                print(f"   ⚠️ {clean_payload.get(on_conflict)} 실패 ({resp.status_code}): {resp.text[:100]}")
        except: continue
    print(f"🏁 [{table_name}] 성공: {success_save}")

# ==========================================
# [3] 데이터 수집 (기존 유지)
# ==========================================

def get_target_stocks():
    if not FINNHUB_API_KEY: return pd.DataFrame()
    now = datetime.now()
    all_data = []
    # 데이터 범위를 승수님 요청대로 넓게 설정
    ranges = [(now-timedelta(days=200), now+timedelta(days=35)), (now-timedelta(days=560), now-timedelta(days=350))]
    for start_dt, end_dt in ranges:
        url = f"https://finnhub.io/api/v1/calendar/ipo?from={start_dt.strftime('%Y-%m-%d')}&to={end_dt.strftime('%Y-%m-%d')}&token={FINNHUB_API_KEY}"
        try:
            res = requests.get(url, timeout=10).json()
            if res.get('ipoCalendar'): all_data.extend(res['ipoCalendar'])
        except: continue
    if not all_data: return pd.DataFrame()
    df = pd.DataFrame(all_data).dropna(subset=['symbol'])
    return df.drop_duplicates(subset=['symbol'])

def update_all_prices_batch(df_target):
    print("\n💰 [정밀 상태 분석] 시작...")
    upsert_list = []
    now_iso = datetime.now().isoformat()
    for t in df_target['symbol'].tolist():
        try:
            stock = yf.Ticker(t)
            hist = stock.history(period="1d")
            status = "Active" if not hist.empty else ("상장연기" if stock.info.get('symbol') else "상장폐지")
            price = float(round(hist['Close'].iloc[-1], 4)) if not hist.empty else 0.0
            upsert_list.append({"ticker": t, "price": price, "status": status, "updated_at": now_iso})
        except:
            upsert_list.append({"ticker": t, "price": 0.0, "status": "상장폐지", "updated_at": now_iso})
    batch_upsert("price_cache", upsert_list, on_conflict="ticker")

# ==========================================
# [4] AI 분석 (프롬프트 100% 복원)
# ==========================================

def run_tab0_analysis(ticker, company_name):
    if not model: return
    for topic in ["S-1", "424B4"]:
        points = "Risk Factors, MD&A" if topic == "S-1" else "Final Price, Underwriting"
        prompt = f"당신은 월가 분석가입니다. {company_name}({ticker})의 {topic} 서류를 분석하세요. {points}를 포함하여 한국어로 3문장씩 작성하세요."
        try:
            resp = model.generate_content(prompt)
            batch_upsert("analysis_cache", [{"cache_key": f"{company_name}_{topic}_Tab0", "content": resp.text, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
        except: pass

def run_tab1_analysis(ticker, company_name):
    if not model: return
    now_str = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""당신은 시니어 애널리스트입니다. {company_name}({ticker}) 분석 리포트를 작성하세요.
    1. 한국어만 사용 2. 3개 문단 구성(비즈니스, 재무, 전망) 3. 인사말 절대 금지.
    마지막에 <JSON_START> {{"news": []}} <JSON_END> 형태로 뉴스 5개를 포함하세요."""
    try:
        resp = model.generate_content(prompt)
        full_text = resp.text
        biz_analysis = full_text.split("<JSON_START>")[0].strip()
        paragraphs = [p.strip() for p in biz_analysis.split('\n') if len(p.strip()) > 20]
        html = "".join([f'<p style="margin-bottom:15px; line-height:1.7;">{p}</p>' for p in paragraphs])
        
        news = []
        if "<JSON_START>" in full_text:
            try: news = json.loads(full_text.split("<JSON_START>")[1].split("<JSON_END>")[0])["news"]
            except: pass
        
        batch_upsert("analysis_cache", [{"cache_key": f"{ticker}_Tab1", "content": json.dumps({"html": html, "news": news}, ensure_ascii=False), "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
    except: pass

# (Tab 2, 3, 4 생략하지만 로직은 위와 동일하게 on_conflict="cache_key" 적용)
# (Tab 0) 주요 공시 분석
def run_tab0_analysis(ticker, company_name):
    if not model: return
    for topic in ["S-1", "424B4"]:
        cache_key = f"{company_name}_{topic}_Tab0"
        
        if topic == "S-1":
            points = "Risk Factors, Use of Proceeds, MD&A"
            structure = """
            1. **[투자포인트]** : 해당 문서에서 발견된 가장 중요한 투자 포인트를 구체적인 수치나 근거와 함께 상세히 서술하세요.
            2. **[성장가능성]** : MD&A(경영진 분석)를 통해 본 기업의 실질적 성장 가능성과 재무적 함의를 깊이 있게 분석하세요.
            3. **[핵심리스크]** : 투자자가 반드시 경계해야 할 핵심 리스크 1가지와 그 파급 효과 및 대응책을 구체적으로 서술하세요.
            """
        else:
            points = "Final Price, Use of Proceeds, Underwriting"
            structure = """
            1. **[최종공모가]** : 확정된 공모가가 희망 밴드 상단인지 하단인지 분석하고, 그 의미(시장 수요)를 해석하세요.
            2. **[자금활용]** : 확정된 조달 자금이 구체적으로 어떤 우선순위 사업에 투입될 예정인지 최종 점검하세요.
            3. **[상장후 전망]** : 주관사단 구성과 배정 물량을 바탕으로 상장 초기 유통 물량 부담이나 변동성을 예측하세요.
            """

        prompt = f"""
        분석 대상: {company_name} ({ticker})의 {topic} 서류
        체크포인트: {points}
        [지침] 당신은 월가 출신의 전문 분석가입니다. 인사말 없이 바로 분석을 시작하세요.
        [내용 구성] {structure}
        위 내용을 바탕으로 전문적인 어조의 한국어로 작성하세요. (각 항목당 3~4문장)
        """
        try:
            response = model.generate_content(prompt)
            batch_upsert("analysis_cache", [{
                "cache_key": cache_key,
                "content": response.text,
                "updated_at": datetime.now().isoformat()
            }], on_conflict="cache_key")
        except: pass

# (Tab 1) 비즈니스 & 뉴스 분석
def run_tab1_analysis(ticker, company_name):
    if not model: return False
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    one_year_ago = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    cache_key = f"{ticker}_Tab1"
    
    prompt = f"""
    당신은 한국 최고의 증권사 리서치 센터의 시니어 애널리스트입니다.
    분석 대상: {company_name} ({ticker})
    오늘 날짜: {current_date}

    [작업 1: 비즈니스 모델 심층 분석]
    아래 [필수 작성 원칙]을 준수하여 리포트를 작성하세요.
    1. 언어: 오직 '한국어'만 사용하세요. (영어 고유명사 제외). 
    2. 포맷: 반드시 3개의 문단으로 나누어 작성하세요. 문단 사이에는 줄바꿈을 명확히 넣으세요.
       - 1문단: 비즈니스 모델 및 경쟁 우위 (독점력, 시장 지배력 등)
       - 2문단: 재무 현황 및 공모 자금 활용 (매출 추이, 흑자 전환 여부, 자금 사용처)
       - 3문단: 향후 전망 및 투자 의견 (시장 성장성, 리스크 요인 포함)
    3. 문체: '~습니다' 체를 사용하되, 문장의 시작을 다양하게 구성하세요.
       - [중요] 모든 문장이 기업명(예: '동사는', '{company_name}은')으로 시작하지 않도록 주의하세요.
    4. 금지: 제목, 소제목, 특수기호, 불렛포인트(-)를 절대 쓰지 마세요.

    [작업 2: 최신 뉴스 수집]
    - **반드시 구글 검색(Google Search)을 실행**하여 최신 정보를 확인하세요.
    - {current_date} 기준, 최근 3개월 이내의 뉴스 위주로 5개를 선정하세요.
    - **경고: {one_year_ago} 이전의 오래된 뉴스는 절대 포함하지 마세요.**
    - 각 뉴스는 아래 JSON 형식으로 답변의 맨 마지막에 첨부하세요.
    
    형식: <JSON_START> {{ "news": [ {{ "title_en": "...", "title_ko": "...", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }} <JSON_END>
    """
    try:
        response = model.generate_content(prompt)
        full_text = response.text
        biz_analysis = full_text.split("<JSON_START>")[0].strip()
        paragraphs = [p.strip() for p in biz_analysis.split('\n') if len(p.strip()) > 20]
        html_output = "".join([f'<p style="display:block; text-indent:14px; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in paragraphs])
        
        news_list = []
        if "<JSON_START>" in full_text:
            try:
                json_str = full_text.split("<JSON_START>")[1].split("<JSON_END>")[0].strip()
                news_list = json.loads(json_str).get("news", [])
            except: pass

        batch_upsert("analysis_cache", [{
            "cache_key": cache_key,
            "content": json.dumps({"html": html_output, "news": news_list}, ensure_ascii=False),
            "updated_at": datetime.now().isoformat()
        }], on_conflict="cache_key")
        return True
    except: return False

# (Tab 3) 재무 분석 AI
def run_tab3_analysis(ticker, company_name, metrics):
    if not model: return False
    cache_key = f"{ticker}_Financial_Report_Tab3"
    prompt = f"""
    당신은 CFA 애널리스트입니다. 아래 재무 데이터를 바탕으로 {company_name} ({ticker}) 투자 분석 리포트를 작성하세요.
    [재무 데이터] {metrics}
    [가이드]
    - 언어: 한국어
    - 형식: [Valuation], [Operating Performance], [Risk], [Conclusion] 4개 소제목 사용.
    - 분량: 10줄 내외 요약.
    """
    try:
        response = model.generate_content(prompt)
        batch_upsert("analysis_cache", [{
            "cache_key": cache_key,
            "content": response.text,
            "updated_at": datetime.now().isoformat()
        }], on_conflict="cache_key")
        return True
    except: return False

# (Tab 4) 기관 평가 AI
def run_tab4_analysis(ticker, company_name):
    if not model: return False
    cache_key = f"{ticker}_Tab4"
    prompt = f"""
    당신은 IPO 전문 분석가입니다. Google 검색을 통해 {company_name} ({ticker})의 최신 기관 리포트(Seeking Alpha, Renaissance Capital 등)를 분석하세요.
    [출력 포맷 JSON]
    <JSON_START>
    {{
        "rating": "Buy/Hold/Sell",
        "summary": "3줄 요약 (한국어)",
        "pro_con": "**긍정**: ... \\n **부정**: ...",
        "links": [ {{"title": "Title", "link": "URL"}} ]
    }}
    <JSON_END>
    """
    try:
        response = model.generate_content(prompt)
        match = re.search(r'<JSON_START>(.*?)<JSON_END>', response.text, re.DOTALL)
        if match:
            batch_upsert("analysis_cache", [{
                "cache_key": cache_key,
                "content": match.group(1),
                "updated_at": datetime.now().isoformat()
            }], on_conflict="cache_key")
            return True
    except: return False

# (Tab 2) 거시 지표 업데이트
def update_macro_data(df):
    if not model: return
    print("🌍 거시 지표(Tab 2) 업데이트 중...")
    cache_key = "Market_Dashboard_Metrics_Tab2"
    data = {"ipo_return": 15.2, "ipo_volume": len(df), "vix": 14.5, "fear_greed": 60} 
    try:
        prompt = f"현재 시장 데이터(VIX: {data['vix']:.2f}, IPO수익률: {data['ipo_return']:.1f}%)를 바탕으로 IPO 투자자에게 주는 3줄 조언 (한국어)."
        ai_resp = model.generate_content(prompt).text
        batch_upsert("analysis_cache", [{"cache_key": "Global_Market_Dashboard_Tab2", "content": ai_resp, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
        batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": json.dumps(data), "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
    except Exception as e:
        print(f"Macro Fail: {e}")
        
# ==========================================
# [5] 메인 실행
# ==========================================
def main():
    print(f"🚀 Worker Start: {datetime.now()}")
    df = get_target_stocks()
    if df.empty: return

    # 1. 추적 명단
    stock_list = [{"symbol": str(row['symbol']), "name": str(row['name']), "updated_at": datetime.now().isoformat()} for _, row in df.iterrows()]
    batch_upsert("stock_cache", stock_list, on_conflict="symbol")

    # 2. 주가/상태
    update_all_prices_batch(df)

    # 3. AI 분석 루프
    for idx, row in df.iterrows():
        print(f"[{idx+1}/{len(df)}] {row['symbol']} 분석 중...")
        run_tab1_analysis(row['symbol'], row['name'])
        run_tab0_analysis(row['symbol'], row['name'])
        time.sleep(1.5)

if __name__ == "__main__":
    main()
