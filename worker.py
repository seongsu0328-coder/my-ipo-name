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
from supabase import create_client
import google.generativeai as genai

# ==========================================
# [1] 환경 설정 (GitHub Secrets 연동)
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GENAI_API_KEY = os.environ.get("GENAI_API_KEY")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")

# 클라이언트 초기화
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    print("❌ Supabase 환경변수가 설정되지 않았습니다.")
    supabase = None

# [AI 모델 설정 - 구글 검색 도구 활성화]
model = None 
if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)
    try:
        # [핵심] tools에 google_search_retrieval 추가
        model = genai.GenerativeModel(
            'gemini-2.0-flash',
            tools=[{'google_search_retrieval': {}}] 
        )
        print("✅ AI 모델 로드 성공 (Gemini 2.0 Flash + Google Search)")
    except Exception as e:
        print(f"⚠️ 모델 로드 실패: {e}")
        model = None

# ==========================================
# [2] 헬퍼 함수: 데이터 정제 및 타겟 선정
# ==========================================
def clean_value(val):
    """None, NaN, Inf 값을 0으로 정제"""
    try:
        if val is None or (isinstance(val, (int, float)) and (np.isnan(val) or np.isinf(val))):
            return 0.0
        return float(val)
    except:
        return 0.0

def get_target_stocks():
    """상장 예정(35일) + 지난 18개월 종목 리스트 추출"""
    if not FINNHUB_API_KEY: return pd.DataFrame()
    
    now = datetime.now()
    # 최근 18개월 범위 설정
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
            ipo_list = res.get('ipoCalendar', [])
            if ipo_list: all_data.extend(ipo_list)
        except: continue
    
    if not all_data: return pd.DataFrame()
    
    df = pd.DataFrame(all_data)
    
    # 데이터 정제
    df = df.dropna(subset=['symbol'])
    df['symbol'] = df['symbol'].astype(str).str.strip()
    df = df[~df['symbol'].isin(['', 'NONE', 'None', 'nan', 'NAN'])]
    
    # [중요] symbol과 date를 기준으로 중복 제거 (가장 최신 날짜 우선)
    df = df.sort_values('date', ascending=False).drop_duplicates(subset=['symbol'])
    df = df.reset_index(drop=True)
    
    print(f"✅ 총 {len(df)}개 유효 종목 발견")
    return df

# ==========================================
# [3] 핵심 AI 분석 함수
# ==========================================

# (Tab 0) 주요 공시 분석 (S-1 & 424B4)
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
        else: # 424B4
            points = "Final Price, Use of Proceeds, Underwriting"
            structure = """
            1. **[최종공모가]** : 확정된 공모가가 희망 밴드 상단인지 하단인지 분석하고, 그 의미(시장 수요)를 해석하세요.
            2. **[자금활용]** : 확정된 조달 자금이 구체적으로 어떤 우선순위 사업에 투입될 예정인지 최종 점검하세요.
            3. **[상장후 전망]** : 주관사단 구성과 배정 물량을 바탕으로 상장 초기 유통 물량 부담이나 변동성을 예측하세요.
            """

        prompt = f"""
        분석 대상: {company_name} ({ticker})의 {topic} 서류
        체크포인트: {points}
        
        [지침]
        당신은 월가 출신의 전문 분석가입니다. 인사말 없이 바로 분석을 시작하세요.
        
        [내용 구성]
        {structure}
        
        위 내용을 바탕으로 전문적인 어조의 한국어로 작성하세요. (각 항목당 3~4문장)
        """
        
        try:
            response = model.generate_content(prompt)
            supabase.table("analysis_cache").upsert([
                {
                    "cache_key": cache_key,
                    "content": response.text,
                    "updated_at": datetime.now().isoformat()
                }
            ], on_conflict="cache_key").execute()
        except Exception:
            pass

# (Tab 1) 비즈니스 & 뉴스 분석 [최종 수정본: 동적 날짜 필터링 적용]
def run_tab1_analysis(ticker, company_name):
    if not model: return False
    if not ticker or str(ticker).lower() == 'none': return False
    
    # [수정] 현재 날짜 및 1년 전 날짜 계산
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    one_year_ago = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    
    cache_key = f"{ticker}_Tab1"
    
    # [프롬프트 강화] app.py와 동일한 로직 적용 (동적 날짜)
    prompt = f"""
    당신은 글로벌 IPO 전문 수석 애널리스트입니다.
    분석 대상: {company_name} ({ticker})
    오늘 날짜: {current_date}
    
    [작업 1: 비즈니스 모델 요약]
    - 이 회사의 핵심 수익 구조와 경쟁사 대비 강점을 3개 문단으로 한국어로 설명하세요.
    - 인사말 없이 본론만 작성하세요. (1. 비즈니스 모델/경쟁우위, 2. 재무현황/자금활용, 3. 향후전망/리스크)

    [작업 2: 실시간 뉴스 검색 및 수집]
    - **반드시 구글 검색(Google Search)을 실행**하여 최신 정보를 확인하세요.
    - {current_date} 기준, 최근 3개월 이내의 뉴스만 수집하세요. 
    - **경고: {one_year_ago} 이전의 오래된 뉴스는 절대 포함하지 마세요.**
    - 검색 키워드 예시: "{company_name} latest news", "{ticker} stock news 2025"
    - 상장(IPO) 관련 소식이나 최근 분기 실적 발표가 있다면 최우선으로 반영하세요.

    결과는 반드시 아래 JSON 형식을 지켜 답변 마지막에 포함하세요.
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
                for n in news_list: 
                    if n['sentiment'] == "긍정": n['bg'], n['color'] = "#e6f4ea", "#1e8e3e"
                    elif n['sentiment'] == "부정": n['bg'], n['color'] = "#fce8e6", "#d93025"
                    else: n['bg'], n['color'] = "#f1f3f4", "#5f6368"
            except: pass

        supabase.table("analysis_cache").upsert([
            {
                "cache_key": cache_key,
                "content": json.dumps({"html": html_output, "news": news_list}, ensure_ascii=False),
                "updated_at": datetime.now().isoformat()
            }
        ], on_conflict="cache_key").execute()
        return True
    except Exception:
        return False

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
        supabase.table("analysis_cache").upsert([
            {
                "cache_key": cache_key,
                "content": response.text,
                "updated_at": datetime.now().isoformat()
            }
        ], on_conflict="cache_key").execute()
        return True
    except Exception:
        return False

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
        text = response.text
        
        json_match = re.search(r'<JSON_START>(.*?)<JSON_END>', text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
            result_data = json.loads(re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str), strict=False)
            
            supabase.table("analysis_cache").upsert([
                {
                    "cache_key": cache_key,
                    "content": json.dumps(result_data, ensure_ascii=False),
                    "updated_at": datetime.now().isoformat()
                }
            ], on_conflict="cache_key").execute()
            return True
    except Exception:
        return False
    return False

# (Tab 2) 거시 지표 업데이트
def update_macro_data(df_calendar):
    if not model: return
    print("🌍 거시 지표(Tab 2) 업데이트 중...")
    cache_key = "Market_Dashboard_Metrics_Tab2"
    data = {"ipo_return": 0.0, "ipo_volume": 0, "unprofitable_pct": 0, "withdrawal_rate": 0, "vix": 0.0, "buffett_val": 0.0, "pe_ratio": 0.0, "fear_greed": 50}
    
    try:
        today = datetime.now()
        if not df_calendar.empty:
            df_calendar['공모일_dt'] = pd.to_datetime(df_calendar['date'], errors='coerce')
            df_valid = df_calendar.dropna(subset=['공모일_dt'])
            
            # 상장 후 수익률 (최근 30개)
            traded = df_valid[df_valid['공모일_dt'].dt.date < today.date()].sort_values(by='공모일_dt', ascending=False).head(30)
            
            ret_sum, ret_cnt = 0, 0
            for _, row in traded.iterrows():
                try:
                    if not row['symbol'] or str(row['symbol']).lower() == 'none': continue
                    p_ipo = float(str(row.get('price','0')).replace('$','').split('-')[0])
                    tk = yf.Ticker(row['symbol'])
                    hist = tk.history(period='1d')
                    if not hist.empty and p_ipo > 0:
                        curr = hist['Close'].iloc[-1]
                        ret_sum += ((curr - p_ipo)/p_ipo)*100
                        ret_cnt += 1
                except: pass
            if ret_cnt > 0: data["ipo_return"] = ret_sum / ret_cnt
            
            # 향후 상장 예정 수
            future = df_valid[(df_valid['공모일_dt'].dt.date >= today.date())]
            data["ipo_volume"] = len(future)

        # 시장 지표
        try:
            vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
            data['vix'] = vix
            spy = yf.Ticker("SPY")
            data['pe_ratio'] = spy.info.get('trailingPE', 24.5)
        except: pass
        
        # AI 시장 코멘트
        prompt = f"현재 시장 데이터(VIX: {data['vix']:.2f}, IPO수익률: {data['ipo_return']:.1f}%)를 바탕으로 IPO 투자자에게 주는 3줄 조언 (한국어)."
        try:
            ai_resp = model.generate_content(prompt).text
            supabase.table("analysis_cache").upsert([
                {"cache_key": "Global_Market_Dashboard_Tab2", "content": ai_resp, "updated_at": datetime.now().isoformat()}
            ], on_conflict="cache_key").execute()
        except: pass
        
        supabase.table("analysis_cache").upsert([
            {"cache_key": cache_key, "content": json.dumps(data), "updated_at": datetime.now().isoformat()}
        ], on_conflict="cache_key").execute()
        print("✅ 거시 지표 업데이트 완료")
        
    except Exception as e:
        print(f"❌ Macro Update Fail: {e}")

# [NEW] 전 종목 주가 일괄 수집 및 저장 (캘린더 속도 향상용)
def update_all_prices_batch(df_target):
    if df_target.empty: return
    
    print("💰 전 종목 주가 일괄 업데이트 중...", end=" ", flush=True)
    
    # 1. 티커 리스트 추출
    tickers = df_target['symbol'].tolist()
    # 50개씩 끊어서 처리 (Yfinance 안정성 확보)
    chunk_size = 50
    total_chunks = (len(tickers) // chunk_size) + 1
    
    now_iso = datetime.now().isoformat()
    success_count = 0
    
    try:
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i:i+chunk_size]
            tickers_str = " ".join(chunk)
            
            # Yfinance로 일괄 다운로드
            data = yf.download(tickers_str, period="1d", interval="1m", group_by='ticker', threads=True, progress=False)
            
            upsert_list = []
            for t in chunk:
                try:
                    # 단일 종목일 경우와 다수 종목일 경우 구조가 다름
                    if len(chunk) == 1:
                        price_series = data['Close']
                    else:
                        if t not in data.columns.levels[0]: continue
                        price_series = data[t]['Close']
                    
                    # 데이터가 있고 비어있지 않은 경우
                    if not price_series.dropna().empty:
                        current_price = float(price_series.dropna().iloc[-1])
                        upsert_list.append({
                            "ticker": t,
                            "price": current_price,
                            "updated_at": now_iso
                        })
                except: continue
            
            # DB 저장 (Batch Upsert)
            if upsert_list:
                supabase.table("price_cache").upsert(upsert_list).execute()
                success_count += len(upsert_list)
            
            time.sleep(1) # API 부하 방지
            
        print(f"✅ 완료 ({success_count}/{len(tickers)}개 저장됨)")
        
    except Exception as e:
        print(f"❌ 주가 업데이트 실패: {e}")
        

# ==========================================
# [4] 메인 실행 루프 [핵심 로직 수정]
# ==========================================
def main():
    print(f"🚀 Worker Start: {datetime.now()}")
    
    df = get_target_stocks()
    if df.empty:
        print("종목이 없어 종료합니다.")
        return

    # 1. 추적 명단 저장
    print(f"📝 추적 명단({len(df)}개) DB 등록 중...", end=" ")
    try:
        stock_list = []
        for _, row in df.iterrows():
            if row['symbol']:
                stock_list.append({
                    "symbol": row['symbol'], 
                    "name": row['name'],
                    "updated_at": datetime.now().isoformat()
                })
        supabase.table("stock_cache").upsert(stock_list, on_conflict="symbol").execute()
        print("✅")
    except Exception as e:
        print(f"❌ 실패: {e}")

    # 2. 거시 지표 업데이트 (매일 실행)
    update_macro_data(df)
    
    # 3. 개별 종목 루프
    total = len(df)
    for idx, row in df.iterrows():
        symbol = row.get('symbol')
        name = row.get('name')
        listing_date_str = row.get('date') # 상장일 (Finnhub 'date' 필드)

        if not symbol or str(symbol).strip().upper() in ['NONE', 'NAN', ''] or str(symbol).lower() == 'none':
            continue
            
        # ------------------------------------------------------------------
        # [핵심] 1년 경과 및 업데이트 전략 판단
        # ------------------------------------------------------------------
        is_old_stock = False
        if listing_date_str:
            try:
                # 날짜 형식 파싱 (Finnhub는 보통 YYYY-MM-DD)
                ld = datetime.strptime(str(listing_date_str), "%Y-%m-%d")
                if (datetime.now() - ld).days > 365:
                    is_old_stock = True
            except: 
                # 날짜 파싱 실패 시, 안전하게 '신규 종목' 취급하여 업데이트 진행
                is_old_stock = False
        
        # 전체 업데이트 대상인가? (월요일(0)이거나, 아직 1년 안 된 종목)
        is_full_update_day = (datetime.now().weekday() == 0 or not is_old_stock)
        
        print(f"[{idx+1}/{total}] {symbol} {'(1년+)' if is_old_stock else '(신규)'} 처리 중...", end=" ", flush=True)
        
        try:
            if not model:
                print("⚠️ AI 모델 없음 (스킵)")
                continue

            # =========================================================
            # [전략] Tab 1 (뉴스)은 무조건 매일 실행
            # =========================================================
            run_tab1_analysis(symbol, name)

            # =========================================================
            # [전략] 나머지는 전체 업데이트 날에만 실행
            # =========================================================
            if is_full_update_day:
                run_tab0_analysis(symbol, name)
                run_tab4_analysis(symbol, name)
                
                # Tab 3 재무 데이터 수집 및 분석
                try:
                    tk = yf.Ticker(symbol)
                    info = tk.info
                    metrics_dict = {
                        "growth": f"{info.get('revenueGrowth', 0)*100:.1f}%",
                        "net_margin": f"{info.get('profitMargins', 0)*100:.1f}%",
                        "roe": f"{info.get('returnOnEquity', 0)*100:.1f}%",
                        "pe": f"{info.get('forwardPE', 0):.1f}x"
                    }
                    run_tab3_analysis(symbol, name, metrics_dict)
                except: pass
                
                print("✅ [전체 완료]")
            else:
                print("✅ [뉴스만 완료] (주 1회 대상)")
            
            time.sleep(2) # Rate Limit 방지
            
        except Exception as e:
            print(f"❌ 실패: {e}")
            time.sleep(1)
            continue
            
    print("🏁 모든 작업 종료.")

if __name__ == "__main__":
    if not supabase:
        print("❌ 필수 설정(Supabase) 누락으로 중단됨.")
    else:
        main()
