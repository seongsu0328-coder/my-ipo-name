import os
import time
import json
import re
import random
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pytz 
from supabase import create_client
import google.generativeai as genai

# ==========================================
# [1] 환경 설정
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GENAI_API_KEY = os.environ.get("GENAI_API_KEY")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")

if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    print("❌ Supabase 환경변수 누락")
    supabase = None

# [AI 모델 설정 - 3단계 안전 로딩]
model = None 
if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)
    
    # 1. 최신 방식 시도
    try:
        model = genai.GenerativeModel('gemini-2.0-flash', tools=[{'google_search': {}}])
        print("✅ AI 모델 로드 성공 (방법 1: Object)")
    except:
        # 2. 문자열 방식 시도
        try:
            model = genai.GenerativeModel('gemini-2.0-flash', tools='google_search')
            print("✅ AI 모델 로드 성공 (방법 2: String)")
        except:
            # 3. 도구 없이 로드 (비상용)
            try:
                model = genai.GenerativeModel('gemini-2.0-flash')
                print("⚠️ AI 모델 로드 성공 (방법 3: No Tools - 검색 기능 제한됨)")
            except Exception as e:
                print(f"❌ 모델 로드 완전 실패: {e}")
                model = None

# ==========================================
# [2] 헬퍼 함수: 데이터 강력 세척 (JSON 405 에러 방지)
# ==========================================
def sanitize_value(v):
    """모든 데이터를 DB가 좋아하는 형태로 강제 변환"""
    if v is None: return None
    if pd.isna(v): return None 
    
    if isinstance(v, (np.integer, np.int64, np.int32)):
        return int(v)
    if isinstance(v, (np.floating, np.float64, np.float32)):
        if np.isinf(v) or np.isnan(v): return 0.0
        return float(v)
    if isinstance(v, str):
        return v.strip()
    return v

def sanitize_list(data_list):
    cleaned = []
    for item in data_list:
        new_item = {}
        for k, v in item.items():
            new_item[k] = sanitize_value(v)
        cleaned.append(new_item)
    return cleaned

def batch_upsert(table_name, data_list, batch_size=50):
    """세척된 데이터를 50개씩 쪼개서 DB에 저장 (안전성 강화)"""
    if not data_list: return
    
    clean_data = sanitize_list(data_list)
    total = len(clean_data)
    
    for i in range(0, total, batch_size):
        batch = clean_data[i:i+batch_size]
        try:
            supabase.table(table_name).upsert(batch).execute()
        except Exception as e:
            print(f"   ❌ {table_name} Batch Error ({i}~): {e}")
            time.sleep(1)

def get_target_stocks():
    if not FINNHUB_API_KEY: return pd.DataFrame()
    
    now = datetime.now()
    ranges = [
        (now - timedelta(days=200), now + timedelta(days=35)),  
        (now - timedelta(days=380), now - timedelta(days=170)), 
        (now - timedelta(days=560), now - timedelta(days=350))  
    ]
    
    all_data = []
    print("📅 Target List 수집 중...", end=" ")
    for start_dt, end_dt in ranges:
        url = f"https://finnhub.io/api/v1/calendar/ipo?from={start_dt.strftime('%Y-%m-%d')}&to={end_dt.strftime('%Y-%m-%d')}&token={FINNHUB_API_KEY}"
        try:
            time.sleep(0.5) 
            res = requests.get(url, timeout=10).json()
            if res.get('ipoCalendar'): all_data.extend(res['ipoCalendar'])
        except: continue
    
    if not all_data: return pd.DataFrame()
    
    df = pd.DataFrame(all_data)
    df = df.dropna(subset=['symbol'])
    df['symbol'] = df['symbol'].astype(str).str.strip()
    df = df[~df['symbol'].isin(['', 'NONE', 'None', 'nan', 'NAN'])]
    df = df.sort_values('date', ascending=False).drop_duplicates(subset=['symbol'])
    
    print(f"✅ 총 {len(df)}개 유효 종목 발견")
    return df

# ==========================================
# [3] 핵심 기능: 주가 일괄 수집 (스마트 모드 적용)
# ==========================================
def update_all_prices_batch(df_target):
    if df_target.empty: return

    # [스마트 로직] 미국 동부 시간(ET) 기준
    utc_now = datetime.now(pytz.utc)
    est_tz = pytz.timezone('US/Eastern')
    est_now = utc_now.astimezone(est_tz)
    
    if est_now.weekday() >= 5:
        print(f"\n😴 [주말] 주가 수집 생략 ({est_now.strftime('%A')})")
        return

    # 08:00 ~ 20:00 ET (프리~애프터마켓)
    if 8 <= est_now.hour < 20:
        print(f"\n💰 [장 운영/마감 직후] 전 종목 주가 일괄 수집 시작 (현재 ET: {est_now.strftime('%H:%M')})...")
    else:
        # [임시 수정] 초기 데이터 구축을 위해 오늘은 무조건 실행하시려면 아래 주석을 푸세요.
        # pass 
        print(f"\n😴 [장 마감] 주가 수집 생략 (현재 ET: {est_now.strftime('%H:%M')})")
        return
    
    tickers = df_target['symbol'].tolist()
    chunk_size = 50 
    now_iso = datetime.now().isoformat()
    success_cnt = 0
    
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i+chunk_size]
        tickers_str = " ".join(chunk)
        
        try:
            data = yf.download(tickers_str, period="1d", interval="1m", group_by='ticker', threads=True, progress=False)
            upsert_list = []
            
            for t in chunk:
                try:
                    if len(chunk) == 1: price_series = data['Close']
                    else: 
                        if t not in data.columns.levels[0]: continue
                        price_series = data[t]['Close']
                    
                    if not price_series.dropna().empty:
                        last_price = float(price_series.dropna().iloc[-1])
                        
                        if pd.isna(last_price) or np.isnan(last_price) or np.isinf(last_price): continue

                        upsert_list.append({
                            "ticker": t, 
                            "price": last_price, 
                            "updated_at": now_iso
                        })
                except: continue
            
            batch_upsert("price_cache", upsert_list)
            success_cnt += len(upsert_list)
            
        except Exception as e:
            print(f"   Batch Fail: {e}")
            
    print(f"✅ 주가 업데이트 완료: 총 {success_cnt}개 저장됨.\n")

# ==========================================
# [4] AI 분석 함수들 (Tab 0~4) - [Prompt 원본 복원]
# ==========================================

# (Tab 0) 주요 공시 분석
def run_tab0_analysis(ticker, company_name):
    if not model: return
    if not ticker or str(ticker).lower() == 'none': return
    
    target_topics = ["S-1", "424B4"]
    for topic in target_topics:
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
            res = model.generate_content(prompt)
            batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": res.text, "updated_at": datetime.now().isoformat()}])
        except: pass

# (Tab 1) 비즈니스 & 뉴스 분석
def run_tab1_analysis(ticker, company_name):
    if not model: return False
    if not ticker or str(ticker).lower() == 'none': return False
    
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
        }])
        return True
    except: return False

# (Tab 3) 재무 분석 AI
def run_tab3_analysis(ticker, company_name, metrics):
    if not model: return False
    if not ticker or str(ticker).lower() == 'none': return False
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
        }])
        return True
    except: return False

# (Tab 4) 기관 평가 AI
def run_tab4_analysis(ticker, company_name):
    if not model: return False
    if not ticker or str(ticker).lower() == 'none': return False
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
            }])
            return True
    except: return False

# (Tab 2) 거시 지표 업데이트
def update_macro_data(df):
    if not model: return
    print("🌍 거시 지표(Tab 2) 업데이트 중...")
    cache_key = "Market_Dashboard_Metrics_Tab2"
    data = {"ipo_return": 15.2, "ipo_volume": 12, "vix": 14.5, "fear_greed": 60} 
    try:
        prompt = f"현재 시장 데이터(VIX: {data['vix']:.2f}, IPO수익률: {data['ipo_return']:.1f}%)를 바탕으로 IPO 투자자에게 주는 3줄 조언 (한국어)."
        ai_resp = model.generate_content(prompt).text
        batch_upsert("analysis_cache", [{"cache_key": "Global_Market_Dashboard_Tab2", "content": ai_resp, "updated_at": datetime.now().isoformat()}])
        batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": json.dumps(data), "updated_at": datetime.now().isoformat()}])
        print("✅ 거시 지표 업데이트 완료")
    except Exception as e:
        print(f"Macro Fail: {e}")

# ==========================================
# [5] 메인 실행 루프
# ==========================================
def main():
    print(f"🚀 Worker Start: {datetime.now()}")
    
    df = get_target_stocks()
    if df.empty:
        print("종목이 없어 종료합니다.")
        return

    # 1. 추적 명단 저장
    print(f"📝 추적 명단({len(df)}개) DB 등록 중...", end=" ")
    stock_list = []
    for _, row in df.iterrows():
        # 이름이 없으면 Unknown 처리
        safe_name = str(row['name']) if pd.notna(row['name']) else "Unknown"
        stock_list.append({
            "symbol": row['symbol'], 
            "name": safe_name, 
            "updated_at": datetime.now().isoformat()
        })
    # 배치 사이즈를 50으로 줄여서 안정성 확보
    batch_upsert("stock_cache", stock_list, batch_size=50)
    print("✅ 완료")

    # 2. 주가 일괄 업데이트
    update_all_prices_batch(df)

    # 3. 거시 지표
    update_macro_data(df)
    
    # 4. 개별 종목 AI 분석
    total = len(df)
    for idx, row in df.iterrows():
        symbol = row.get('symbol')
        name = row.get('name')
        listing_date = row.get('date')
        
        is_old = False
        try:
            if (datetime.now() - datetime.strptime(str(listing_date), "%Y-%m-%d")).days > 365: is_old = True
        except: pass
        
        # 월요일이거나 신규 종목이면 전체 업데이트, 아니면 뉴스만
        is_full_update = (datetime.now().weekday() == 0 or not is_old)
        
        print(f"[{idx+1}/{total}] {symbol} {'(1년+)' if is_old else '(신규)'}...", end=" ", flush=True)
        
        try:
            if not model:
                print("⚠️ AI 모델 없음 (스킵)")
                continue

            run_tab1_analysis(symbol, name)
            
            if is_full_update:
                run_tab0_analysis(symbol, name)
                run_tab4_analysis(symbol, name)
                try:
                    tk = yf.Ticker(symbol)
                    info = tk.info
                    met = {"pe": info.get('forwardPE', 0)}
                    run_tab3_analysis(symbol, name, met)
                except: pass
                print("✅ 전체")
            else:
                print("✅ 뉴스만")
            
            time.sleep(1.5)
        except Exception as e:
            print(f"❌ {e}")
            continue
            
    print("🏁 모든 작업 종료.")

if __name__ == "__main__":
    if supabase: main()
