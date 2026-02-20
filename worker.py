import os
import time
import json
import re
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import logging
from datetime import datetime, timedelta, date
from supabase import create_client
import google.generativeai as genai

# ==========================================
# [1] 환경 설정
# ==========================================

# 1. Supabase URL 보정
raw_url = os.environ.get("SUPABASE_URL", "")
if "/rest/v1" in raw_url:
    SUPABASE_URL = raw_url.split("/rest/v1")[0].rstrip('/')
else:
    SUPABASE_URL = raw_url.rstrip('/')

SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
GENAI_API_KEY = os.environ.get("GENAI_API_KEY", "")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

# 2. yfinance 불필요한 에러 로그 차단
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

if not (SUPABASE_URL and SUPABASE_KEY):
    print("❌ 환경변수 누락 (SUPABASE_URL 또는 KEY)")
    exit()

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"❌ Supabase 클라이언트 초기화 실패: {e}")
    exit()

# AI 모델 설정
model = None 
if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)
    try:
        model = genai.GenerativeModel('gemini-2.0-flash', tools=[{'google_search_retrieval': {}}])
        print("✅ AI 모델 로드 성공 (Search Tool 활성화)")
    except:
        model = genai.GenerativeModel('gemini-2.0-flash')
        print("⚠️ AI 모델 기본 로드 (Search Tool 제외)")

# [추가] 다국어 지원 맵
SUPPORTED_LANGS = {
    'ko': '전문적인 한국어(Korean)',
    'en': 'Professional English',
    'ja': '専門的な日本語(Japanese)'
}

# ==========================================
# [2] 헬퍼 함수: 데이터 정제 및 직송 (Universal Upsert)
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
            print(f"❌ [{table_name}] 저장 실패 ({resp.status_code})")
            if resp.status_code == 405:
                 print("   💡 [힌트] Supabase RLS 정책 또는 Key 권한을 확인하세요.")
    except Exception as e:
        print(f"❌ [{table_name}] 통신 에러: {e}")

# ==========================================
# [3] 데이터 수집 및 상태 분석 로직
# ==========================================

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


# ==========================================
# [4] AI 분석 함수들 (기존 프롬프트 유지 + 언어변수 추가)
# ==========================================

def run_tab0_analysis(ticker, company_name):
    if not model: return
    for topic in ["S-1", "424B4"]:
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
            
        for lang_code, target_lang in SUPPORTED_LANGS.items():
            cache_key = f"{company_name}_{topic}_Tab0_{lang_code}"
            prompt = f"분석 대상: {company_name} ({ticker}) {topic} 서류\n체크포인트: {points}\n[지침] 월가 전문 분석가 어조.\n[내용 구성] {structure}\n반드시 '{target_lang}'로 각 항목당 3~4문장 작성하세요."
            try:
                response = model.generate_content(prompt)
                batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": response.text, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
                time.sleep(1)
            except: pass

def run_tab1_analysis(ticker, company_name):
    if not model: return False
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Tab1_{lang_code}"
        
        prompt = f"""
        당신은 한국 최고의 증권사 시니어 애널리스트입니다. 분석 대상: {company_name} ({ticker}) 오늘 날짜: {current_date}
        [작업 1: 비즈니스 모델 심층 분석]
        1. 언어: 반드시 '{target_lang}'로만 작성. 2. 포맷: 반드시 3개 문단(비즈니스 모델, 재무 현황, 향후 전망) 3. 문체: '~습니다' 체 4. 금지: 제목/소제목/인사말 절대 금지.
        [작업 2: 최신 뉴스 수집]
        - 구글 검색을 통해 최근 3개월 내 뉴스 5개를 선정하여 JSON으로 답변 마지막에 첨부하세요.
        형식: <JSON_START> {{ "news": [ {{ "title_ko": "{target_lang} 제목", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }} <JSON_END>
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
                    json_part = full_text.split("<JSON_START>")[1].split("<JSON_END>")[0].strip()
                    news_list = json.loads(json_part).get("news", [])
                except: pass
                
            batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": json.dumps({"html": html_output, "news": news_list}, ensure_ascii=False), "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
            time.sleep(1.5)
        except: pass

def run_tab3_analysis(ticker, company_name, metrics):
    if not model: return False
    
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Financial_Report_Tab3_{lang_code}"
        prompt = f"당신은 CFA 애널리스트입니다. {company_name}({ticker})의 재무 데이터 {metrics}를 바탕으로 [Valuation], [Operating Performance], [Risk], [Conclusion] 4개 항목 리포트를 반드시 '{target_lang}'로 10줄 요약하세요."
        try:
            response = model.generate_content(prompt)
            batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": response.text, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
            time.sleep(1)
        except: pass

def run_tab4_analysis(ticker, company_name):
    if not model: return False
    
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Tab4_{lang_code}"
        prompt = f"IPO 전문 분석가로서 Google 검색을 통해 {company_name}({ticker})의 최신 기관 리포트를 분석하고 아래 JSON 형식으로 출력하세요. 언어는 반드시 '{target_lang}'로 작성.\n<JSON_START> {{ \"rating\": \"Buy/Hold/Sell\", \"summary\": \"3줄 요약\", \"pro_con\": \"긍정/부정\", \"links\": [] }} <JSON_END>"
        try:
            response = model.generate_content(prompt)
            match = re.search(r'<JSON_START>(.*?)<JSON_END>', response.text, re.DOTALL)
            if match:
                batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": match.group(1), "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
            time.sleep(1)
        except: pass

def update_macro_data(df):
    if not model: return
    print("🌍 거시 지표(Tab 2) 업데이트 중...")
    
    cache_key_data = "Market_Dashboard_Metrics_Tab2"
    data = {"ipo_return": 15.2, "ipo_volume": len(df), "vix": 14.5, "fear_greed": 60} 
    batch_upsert("analysis_cache", [{"cache_key": cache_key_data, "content": json.dumps(data), "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
    
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key_report = f"Global_Market_Dashboard_Tab2_{lang_code}"
        try:
            prompt = f"현재 시장 데이터(VIX: {data['vix']:.2f}, IPO수익률: {data['ipo_return']:.1f}%) 기반 IPO 투자 조언 3줄. 반드시 '{target_lang}'로 작성하세요."
            ai_resp = model.generate_content(prompt).text
            batch_upsert("analysis_cache", [{"cache_key": cache_key_report, "content": ai_resp, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
            time.sleep(1)
        except: pass

# ==========================================
# [5] 메인 실행 루프
# ==========================================
def main():
    print(f"🚀 Worker Start: {datetime.now()}")
    
    # [1] 대상 종목 수집
    df = get_target_stocks()
    if df.empty: 
        print("⚠️ 수집된 IPO 종목이 없습니다.")
        return

    # [2] 추적 명단 저장 
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

    # [4] 거시 지표 업데이트 (Tab 2)
    update_macro_data(df)
    
    # [5] 개별 종목 AI 분석 루프
    total = len(df)
    print(f"\n🤖 AI 심층 분석 시작 (총 {total}개 종목)...")
    
    for idx, row in df.iterrows():
        symbol = row.get('symbol')
        name = row.get('name')
        listing_date = row.get('date')
        
        # 상장한 지 1년이 넘었는지 확인
        is_old = False
        try:
            if (datetime.now() - datetime.strptime(str(listing_date), "%Y-%m-%d")).days > 365: 
                is_old = True
        except: 
            pass
        
        # 월요일이거나 신규 종목인 경우에만 전체 업데이트
        is_full_update = (datetime.now().weekday() == 0 or not is_old)
        
        print(f"[{idx+1}/{total}] {symbol} 분석 중...", flush=True)
        
        try:
            # 기본 분석 (뉴스 및 비즈니스 모델)
            run_tab1_analysis(symbol, name)
            
            if is_full_update:
                # 심층 분석 (공시, 기관 리포트, 재무)
                run_tab0_analysis(symbol, name)
                run_tab4_analysis(symbol, name)
                try:
                    tk = yf.Ticker(symbol)
                    run_tab3_analysis(symbol, name, {"pe": tk.info.get('forwardPE', 0)})
                except: 
                    pass
            
            # API 할당량 준수를 위한 짧은 휴식 (루프 내부의 휴식과 더불어 추가 안정성 확보)
            time.sleep(1.2) 
            
        except Exception as e:
            print(f"⚠️ {symbol} 분석 건너뜀: {e}")
            continue
            
    print(f"\n🏁 모든 작업 종료: {datetime.now()}")

if __name__ == "__main__":
    main()
