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

# [worker.py 상단 수정본]
if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)
    try:
        # 404 에러 방지 핵심: 모델 이름을 인자명(model_name)으로 직접 전달
        model = genai.GenerativeModel(
            model_name='gemini-1.5-flash', 
            tools='google_search'
        )
        # 성공 시 로그 출력 (GitHub Actions 로그에서 확인용)
        print("✅ AI 모델 로드 성공 (Google Search 도구 장착)")
    except Exception as e:
        print(f"⚠️ v1beta 도구 장착 실패, 일반 모델로 전환: {e}")
        model = genai.GenerativeModel('gemini-1.5-flash')
else:
    print("❌ GENAI_API_KEY가 설정되지 않았습니다.")
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
    # [기술 수정] 중복 및 유령 데이터(NoneType) 제거 로직 강화
    df = df.drop_duplicates(subset=['symbol', 'date'])
    df = df.dropna(subset=['symbol'])
    df = df[df['symbol'].astype(str).str.strip() != ""]
    df = df.reset_index(drop=True)
    
    print(f"✅ 총 {len(df)}개 종목 발견")
    return df

# ==========================================
# [3] 핵심 AI 분석 함수 (원본 내용 보존 + 기술 결함 수정)
# ==========================================

# (Tab 0) 주요 공시 분석 (S-1 & 424B4)
def run_tab0_analysis(ticker, company_name):
    if not ticker or str(ticker).lower() == 'none': return
    
    target_topics = ["S-1", "424B4"]
    for topic in target_topics:
        cache_key = f"{company_name}_{topic}_Tab0"
        
        # [기술 수정] 기존 check.data 건너뛰기 로직 삭제 (매일 강제 업데이트)

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
            # [기술 수정] 리스트 형식 및 on_conflict 추가
            supabase.table("analysis_cache").upsert([
                {
                    "cache_key": cache_key,
                    "content": response.text,
                    "updated_at": datetime.now().isoformat()
                }
            ], on_conflict="cache_key").execute()
        except Exception as e:
            print(f"  └─ Tab0 ({topic}) Error: {e}")

# (Tab 1) 비즈니스 & 뉴스 분석
def run_tab1_analysis(ticker, company_name):
    if not ticker or str(ticker).lower() == 'none': return False
    cache_key = f"{ticker}_Tab1"
    
    prompt = f"""
    당신은 한국 최고의 애널리스트입니다. 분석 대상: {company_name} ({ticker})
    
    [작업 1: 비즈니스 모델 심층 분석]
    - 언어: 한국어
    - 포맷: 3개 문단 (1.비즈니스 모델/경쟁우위, 2.재무현황/자금활용, 3.향후전망/리스크)
    - 인사말 생략하고 바로 본론 시작.

    [작업 2: 최신 뉴스 수집]
    - Google 검색 도구를 사용하여 이 기업의 최신 뉴스 5개를 찾으세요.
    - JSON 형식으로 답변 마지막에 첨부하세요.
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
    except Exception as e:
        print(f"  └─ Tab1 Error: {e}")
        return False

# (Tab 3) 재무 분석 AI
def run_tab3_analysis(ticker, company_name, metrics):
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
    except Exception as e:
        print(f"  └─ Tab3 AI Error: {e}")
        return False

# (Tab 4) 기관 평가 AI
def run_tab4_analysis(ticker, company_name):
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
    except Exception as e:
        print(f"  └─ Tab4 Error: {e}")
        return False
    return False

# (Tab 2) 거시 지표 업데이트
def update_macro_data(df_calendar):
    print("🌍 거시 지표(Tab 2) 업데이트 중...")
    cache_key = "Market_Dashboard_Metrics_Tab2"
    data = {"ipo_return": 0.0, "ipo_volume": 0, "unprofitable_pct": 0, "withdrawal_rate": 0, "vix": 0.0, "buffett_val": 0.0, "pe_ratio": 0.0, "fear_greed": 50}
    
    try:
        today = datetime.now()
        if not df_calendar.empty:
            # [기술 수정] 날짜 형식을 'datetime' 객체로 확실히 변환
            df_calendar['공모일_dt'] = pd.to_datetime(df_calendar['date'], errors='coerce')
            df_valid = df_calendar.dropna(subset=['공모일_dt'])
            
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
            
            future = df_valid[(df_valid['공모일_dt'].dt.date >= today.date())]
            data["ipo_volume"] = len(future)

        try:
            vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
            data['vix'] = vix
            spy = yf.Ticker("SPY")
            data['pe_ratio'] = spy.info.get('trailingPE', 24.5)
        except: pass
        
        prompt = f"현재 시장 데이터(VIX: {data['vix']:.2f}, IPO수익률: {data['ipo_return']:.1f}%)를 바탕으로 IPO 투자자에게 주는 3줄 조언 (한국어)."
        ai_resp = model.generate_content(prompt).text
        
        supabase.table("analysis_cache").upsert([
            {"cache_key": "Global_Market_Dashboard_Tab2", "content": ai_resp, "updated_at": datetime.now().isoformat()}
        ], on_conflict="cache_key").execute()
        
        supabase.table("analysis_cache").upsert([
            {"cache_key": cache_key, "content": json.dumps(data), "updated_at": datetime.now().isoformat()}
        ], on_conflict="cache_key").execute()
        print("✅ 거시 지표 업데이트 완료")
        
    except Exception as e:
        print(f"❌ Macro Update Fail: {e}")

# ==========================================
# [4] 메인 실행 루프
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

    # 2. 거시 지표 업데이트
    update_macro_data(df)
    
    # 3. 개별 종목 루프
    total = len(df)
    for idx, row in df.iterrows():
        symbol = row.get('symbol')
        name = row.get('name')
        
        if not symbol or str(symbol).lower() == 'none': continue
            
        print(f"[{idx+1}/{total}] {symbol} 분석 중...", end=" ", flush=True)
        
        try:
            # 각 탭 실행
            run_tab0_analysis(symbol, name)
            run_tab1_analysis(symbol, name)
            run_tab4_analysis(symbol, name)
            
            # Tab 3 전용 데이터 수집
            tk = yf.Ticker(symbol)
            info = tk.info
            growth = info.get('revenueGrowth', 0) * 100
            net_margin = info.get('profitMargins', 0) * 100
            roe = info.get('returnOnEquity', 0) * 100
            
            metrics_dict = {
                "growth": f"{growth:.1f}%",
                "net_margin": f"{net_margin:.1f}%",
                "roe": f"{roe:.1f}%",
                "pe": f"{info.get('forwardPE', 0):.1f}x"
            }
            run_tab3_analysis(symbol, name, metrics_dict)
            
            print("✅")
            time.sleep(3) # Rate Limit 방지용
            
        except Exception as e:
            print(f"❌ 실패: {e}")
            time.sleep(5)
            
    print("🏁 모든 작업 종료.")

if __name__ == "__main__":
    if not supabase or not model:
        print("❌ 필수 설정 누락으로 중단됨.")
    else:
        main()
