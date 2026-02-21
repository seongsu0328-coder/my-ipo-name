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
    print("❌ 환경변수 누락")
    exit()

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"❌ Supabase 초기화 실패: {e}")
    exit()

# 모델 이원화
search_model = None   
standard_model = None 

if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)
    try:
        search_model = genai.GenerativeModel('gemini-2.0-flash', tools=[{'google_search_retrieval': {}}])
        standard_model = genai.GenerativeModel('gemini-2.0-flash')
        print("✅ AI 모델 로드 성공 (Search / Standard 이원화)")
    except Exception as e:
        print(f"❌ AI 모델 로드 실패: {e}")

SUPPORTED_LANGS = {
    'ko': '전문적인 한국어(Korean)',
    'en': 'Professional English',
    'ja': '専門的な日本語(Japanese)'
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
        requests.post(endpoint, json=clean_batch, headers=headers)
    except Exception as e:
        print(f"❌ [{table_name}] 업로드 에러: {e}")

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

# 💡 [신규] price_worker가 모아둔 최신 가격 가져오기
def get_current_prices():
    try:
        # price_cache 테이블에서 전체 조회
        res = supabase.table("price_cache").select("ticker, price").execute()
        return {item['ticker']: float(item['price']) for item in res.data if item['price']}
    except:
        return {}

# ==========================================
# [3] AI 분석 함수들 (비용 최적화 적용)
# ==========================================

# Tab 0: 일반 모델 (무료)
def run_tab0_analysis(ticker, company_name):
    if not standard_model: return
    
    def_meta = {
        "S-1": "Risk Factors(특이 소송/규제), Use of Proceeds(자금 용도의 건전성), MD&A(성장 동인)",
        "S-1/A": "Pricing Terms(수요예측 분위기), Dilution(신규 투자자 희석률), Changes(이전 제출본과의 차이점)",
        "F-1": "Foreign Risk(지정학적 리스크), Accounting(GAAP 차이), ADS(주식 예탁 증서 구조)",
        "FWP": "Graphics(시장 점유율 시각화), Strategy(미래 핵심 먹거리), Highlights(경영진 강조 사항)",
        "424B4": "Underwriting(주관사 등급), Final Price(기관 배정 물량), IPO Outcome(최종 공모 결과)"
    }

    format_instruction = """
    [출력 형식 및 번역 규칙 - 반드시 지킬 것]
    - 각 문단의 시작은 반드시 해당 언어로 번역된 **[소제목]**으로 시작한 뒤, 줄바꿈 없이 한 칸 띄우고 바로 내용을 이어가세요.
    - [분량 조건] 전체 요약이 아닙니다! **각 문단(1, 2, 3)마다 반드시 4~5문장(약 5줄 분량)씩** 내용을 상세하고 풍성하게 채워 넣으세요.
    - 금지 예시: **[Heading - 한국어]** (X), **[Heading]** \n Content (X)
    """

    for topic in ["S-1", "S-1/A", "F-1", "FWP", "424B4"]:
        if topic not in def_meta: continue
        points = def_meta[topic]
        
        for lang_code, target_lang in SUPPORTED_LANGS.items():
            cache_key = f"{company_name}_{topic}_Tab0_v11_{lang_code}"
            
            prompt = f"""
            Role: Wall Street Senior Analyst.
            Task: Analyze {company_name} ({ticker})'s {topic} filing points: {points}.
            Language: Strictly in {target_lang}.
            
            [Structure]
            1. First paragraph: Analysis of key investment points in the document.
            2. Second paragraph: Analysis of growth potential and financial implications.
            3. Third paragraph: One key risk factor and its impact.

            {format_instruction}
            """
            try:
                response = standard_model.generate_content(prompt)
                batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": response.text, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
                time.sleep(0.5)
            except: pass

# Tab 1: 검색 1회 -> 번역 3회 (비용 절감)
def run_tab1_analysis(ticker, company_name):
    if not search_model or not standard_model: return
    
    # 1. [검색 단계] 영어로 1번만 검색
    source_text = ""
    try:
        search_prompt = f"""
        Find the detailed business model and 5 recent news articles (last 1 year) for {company_name} ({ticker}).
        Output the news in JSON format inside <NEWS_JSON> tags, and business summary as plain text.
        """
        source_resp = search_model.generate_content(search_prompt)
        source_text = source_resp.text
    except: return 

    # 2. [번역 단계] 
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Tab1_v2_{lang_code}"
        
        if lang_code == 'ja':
            lang_instruction = "必ず日本語(Japanese)のみで作成してください。"
            json_format = f"""{{ "news": [ {{ "title_en": "Original Title", "translated_title": "日本語タイトル", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""
        elif lang_code == 'en':
            lang_instruction = "Write strictly in English."
            json_format = f"""{{ "news": [ {{ "title_en": "Original Title", "translated_title": "Original Title", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""
        else:
            lang_instruction = "반드시 한국어로 작성하세요."
            json_format = f"""{{ "news": [ {{ "title_en": "Original Title", "translated_title": "한국어 제목", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""

        prompt = f"""
        Based on the provided source info below, create a report for {company_name} ({ticker}).
        Source Info: {source_text[:10000]} 

        [Task 1: Business Model]
        - Write 3 paragraphs (Model, Financials, Outlook) in {target_lang}. {lang_instruction}
        - No headers, just plain text paragraphs.

        [Task 2: News]
        - Extract 5 news from source and format as JSON.
        - Important: Keep 'sentiment' value as "긍정", "부정", or "일반" (Korean) regardless of output language.
        
        <JSON_START>
        {json_format}
        <JSON_END>
        """
        try:
            response = standard_model.generate_content(prompt)
            full_text = response.text
            
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
                except: pass
            
            batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": json.dumps({"html": html_output, "news": news_list}, ensure_ascii=False), "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
            time.sleep(1)
        except: pass

# Tab 3: 일반 모델 (무료)
def run_tab3_analysis(ticker, company_name, metrics):
    if not standard_model: return
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Financial_Report_Tab3_{lang_code}"
        prompt = f"""
        Role: CFA Analyst.
        Task: Write a financial report for {company_name} based on: {metrics}.
        Language: {target_lang}.
        Format: 4 sections [Valuation], [Operating], [Risk], [Conclusion].
        Length: 10-12 lines total.
        """
        try:
            response = standard_model.generate_content(prompt)
            batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": response.text, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
            time.sleep(0.5)
        except: pass

# Tab 4: 검색 1회 -> 번역 3회 (비용 절감)
def run_tab4_analysis(ticker, company_name):
    if not search_model or not standard_model: return

    # 1. [검색 단계] 영어로 기관 리포트 검색
    source_text = ""
    try:
        search_prompt = f"Find recent institutional analyst ratings, price targets, and pros/cons reports for {company_name} ({ticker})."
        source_resp = search_model.generate_content(search_prompt)
        source_text = source_resp.text
    except: return

    # 2. [번역 단계]
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Tab4_{lang_code}"
        
        if lang_code == 'ja':
            json_format = '"summary": "3行要約", "pro_con": "**Pros(長所)**:\\n- 内容\\n\\n**Cons(短所)**:\\n- 内容 (必ず日本語で)",'
        elif lang_code == 'en':
            json_format = '"summary": "3-line summary", "pro_con": "**Pros**:... **Cons**:..."'
        else:
            json_format = '"summary": "3줄 요약", "pro_con": "**Pros(장점)**... **Cons(단점)**..."'

        prompt = f"""
        Using the source info below, create an institutional report summary for {company_name} ({ticker}).
        Source Info: {source_text[:8000]}
        Language: {target_lang} (Strictly).
        
        <JSON_START>
        {{
            "rating": "Buy/Hold/Sell",
            {json_format},
            "links": [{{"title": "Report Title", "link": "URL"}}]
        }}
        <JSON_END>
        """
        try:
            response = standard_model.generate_content(prompt)
            match = re.search(r'<JSON_START>(.*?)<JSON_END>', response.text, re.DOTALL)
            if match:
                clean_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', match.group(1).strip())
                batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": clean_str, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
            time.sleep(1)
        except: pass

def update_macro_data(df):
    if not standard_model: return
    print("🌍 거시 지표(Tab 2) 업데이트 중...")
    data = {"ipo_return": 15.2, "ipo_volume": len(df), "vix": 14.5, "fear_greed": 60} 
    
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key = f"Global_Market_Dashboard_Tab2_{lang_code}"
        try:
            prompt = f"Market Data: {data}. Write a 3-line daily market briefing in {target_lang}. No headers."
            ai_resp = standard_model.generate_content(prompt).text
            ai_resp = re.sub(r'^#+.*$', '', ai_resp, flags=re.MULTILINE).strip()
            batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": ai_resp, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
        except: pass

# ==========================================
# [4] 메인 실행 루프
# ==========================================
def main():
    print(f"🚀 Worker Start: {datetime.now()}")
    
    df = get_target_stocks()
    if df.empty: 
        print("⚠️ 수집된 IPO 종목이 없습니다.")
        return

    # [1] 전체 명단 DB 업데이트 (Hot 여부 상관없이 목록은 최신화)
    print("\n📋 [stock_cache] 명단 업데이트...")
    now_iso = datetime.now().isoformat()
    stock_list = [{"symbol": str(row['symbol']), "name": str(row['name']) or "Unknown", "last_updated": now_iso} for _, row in df.iterrows()]
    batch_upsert("stock_cache", stock_list, on_conflict="symbol")

    # [2] 매크로 업데이트 (비용 거의 없음)
    update_macro_data(df)
    
    # ----------------------------------------------------
    # 💡 [핵심] Hot 종목 선별 로직 (상장 예정 + 상위 수익률 30위)
    # ----------------------------------------------------
    print("🔥 Hot 종목 선별 중...")
    price_map = get_current_prices() # price_worker가 모은 최신 가격
    
    today = datetime.now()
    hot_symbols = set()
    
    # (1) 상장 예정 종목 (오늘 이후 ~ 35일 이내)
    try:
        df['dt'] = pd.to_datetime(df['date'])
        upcoming = df[(df['dt'] > today) & (df['dt'] <= today + timedelta(days=35))]
        hot_symbols.update(upcoming['symbol'].tolist())
        print(f"   -> 상장 예정: {len(upcoming)}개")
    except: pass
    
    # (2) 최근 12개월 상장 중 수익률 상위 30개
    try:
        past_12m = df[(df['dt'] >= today - timedelta(days=365)) & (df['dt'] <= today)].copy()
        
        # 수익률 계산 함수
        def calc_return(row):
            try:
                # IPO 가격 파싱 ($10.00-12.00 형태 처리)
                ipo_p_str = str(row.get('price', '0')).replace('$','').split('-')[0]
                ipo_p = float(ipo_p_str)
                curr_p = price_map.get(row['symbol'], 0.0)
                
                if ipo_p > 0 and curr_p > 0:
                    return (curr_p - ipo_p) / ipo_p * 100
                return -9999.0 # 가격 정보 없으면 하위로
            except:
                return -9999.0
        
        past_12m['return'] = past_12m.apply(calc_return, axis=1)
        top_30 = past_12m.sort_values(by='return', ascending=False).head(30)
        hot_symbols.update(top_30['symbol'].tolist())
        print(f"   -> 수익률 상위: 30개 (1위: {top_30.iloc[0]['symbol']} {top_30.iloc[0]['return']:.1f}%)")
        
    except Exception as e:
        print(f"   ⚠️ 수익률 계산 중 에러: {e}")

    print(f"✅ 최종 Hot 종목: 총 {len(hot_symbols)}개")

    # ----------------------------------------------------
    # [3] 분석 루프 시작
    # ----------------------------------------------------
    total = len(df)
    print(f"\n🤖 AI 심층 분석 시작 (총 {total}개 중 Hot 종목 위주 실행)...")
    
    for idx, row in df.iterrows():
        symbol = row.get('symbol')
        name = row.get('name')
        
        is_hot = symbol in hot_symbols
        # 월요일이거나 Hot 종목이면 전체 업데이트 (그 외에는 비용 절약을 위해 스킵)
        is_full_update = (today.weekday() == 0 or is_hot)
        
        print(f"[{idx+1}/{total}] {symbol} (Hot:{is_hot}) 처리 중...", flush=True)
        
        try:
            # 1. Tab 1, 4 (돈 드는 검색 모델): 오직 Hot 종목만 실행!
            if is_hot:
                run_tab1_analysis(symbol, name)
                if is_full_update:
                    run_tab4_analysis(symbol, name)
            
            # 2. Tab 0, 3 (돈 안 드는 일반 모델): 필요 시 실행 (비용 부담 없음)
            if is_full_update:
                run_tab0_analysis(symbol, name)
                try:
                    tk = yf.Ticker(symbol)
                    run_tab3_analysis(symbol, name, {"pe": tk.info.get('forwardPE', 0)})
                except: pass
            
            time.sleep(0.5) 
            
        except Exception as e:
            print(f"⚠️ {symbol} 건너뜀: {e}")
            continue
            
    print(f"\n🏁 모든 작업 종료: {datetime.now()}")

if __name__ == "__main__":
    main()
