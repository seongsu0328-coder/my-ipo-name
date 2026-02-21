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
        resp = requests.post(endpoint, json=clean_batch, headers=headers)
        if resp.status_code in [200, 201, 204]:
            print(f"✅ [{table_name}] {len(clean_batch)}개 저장 성공")
        else:
            print(f"❌ [{table_name}] 저장 실패 ({resp.status_code})")
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


# ==========================================
# [3] AI 분석 함수들 (app.py와 완벽 동기화)
# ==========================================

def run_tab0_analysis(ticker, company_name):
    """Tab 0: 공시 분석 (프롬프트 뼈대 및 v9 캐시키 동기화)"""
    if not model: return
    
    def_meta = {
        "S-1": {
            "points": "Risk Factors(특이 소송/규제), Use of Proceeds(자금 용도의 건전성), MD&A(성장 동인)",
            "structure": """
            [내용 구성 - 반드시 3문단으로 나누어 상세하고 풍성하게 작성할 것]
            1. **[투자포인트]** : 해당 문서에서 발견된 가장 중요한 투자 포인트를 구체적인 수치나 근거와 함께 상세히 서술하세요.
            2. **[성장가능성]** : MD&A(경영진 분석)를 통해 본 기업의 실질적 성장 가능성과 재무적 함의를 깊이 있게 분석하세요.
            3. **[핵심리스크]** : 투자자가 반드시 경계해야 할 핵심 리스크 1가지와 그 파급 효과 및 대응책을 구체적으로 서술하세요.
            """
        },
        "424B4": {
            "points": "Underwriting(주관사 등급), Final Price(기관 배정 물량), IPO Outcome(최종 공모 결과)",
            "structure": """
            [내용 구성 - 반드시 3문단으로 나누어 상세하고 풍성하게 작성할 것]
            1. **[최종공모가]** : 확정된 공모가가 희망 밴드 상단인지 하단인지 분석하고, 그 의미(시장 수요)를 해석하세요.
            2. **[자금활용]** : 확정된 조달 자금이 구체적으로 어떤 우선순위 사업에 투입될 예정인지 최종 점검하세요.
            3. **[상장후 전망]** : 주관사단 구성과 배정 물량을 바탕으로 상장 초기 유통 물량 부담이나 변동성을 예측하세요.
            """
        }
    }

    # 워커에서는 핵심 서류 2가지만 우선 처리 (비용/시간 절약)
    for topic in ["S-1", "424B4"]:
        curr_meta = def_meta[topic]
        
        for lang_code, target_lang in SUPPORTED_LANGS.items():
            # 🚨 [핵심] app.py와 동일한 캐시 키 적용 (v9)
            cache_key = f"{company_name}_{topic}_Tab0_v9_{lang_code}"
            
            if lang_code == 'en':
                labels = ["Analysis Target", "Instructions", "Structure & Format", "Writing Style Guide"]
                role_desc = "You are a professional senior analyst from Wall Street."
                no_intro_prompt = 'CRITICAL: NEVER introduce yourself. DO NOT include Korean translations in headings. START IMMEDIATELY with the first English **[Heading]**.'
                lang_directive = "The guide below is in Korean for reference, but you MUST translate all headings and content into English."
            elif lang_code == 'ja':
                labels = ["分析対象", "指針", "内容構成および形式", "文体ガイド"]
                role_desc = "あなたはウォール街出身の専門分析家です。"
                no_intro_prompt = '【重要】自己紹介や挨拶は絶対に禁止です。見出しに韓国語を併記しないでください。1文字目からいきなり日本語の**[見出し]**で本論から始めてください。'
                lang_directive = "構成 가이드는 참고용으로 한국어로 제공되나, 모든 제목과 내용은 반드시 일본어로만 작성하세요."
            else:
                labels = ["분석 대상", "지침", "내용 구성 및 형식 - 반드시 아래 형식을 따를 것", "문체 가이드"]
                role_desc = "당신은 월가 출신의 전문 분석가입니다."
                no_intro_prompt = '자기소개나 인사말, 서론은 절대 하지 마세요. 1글자부터 바로 본론(**[소제목]**)으로 시작하세요.'
                lang_directive = ""

            prompt = f"""
            {labels[0]}: {company_name} - {topic}
            {labels[1]} (Checkpoints): {curr_meta['points']}
            
            [{labels[1]}]
            {role_desc}
            {no_intro_prompt}
            {lang_directive}
            
            [{labels[2]}]
            각 문단의 시작에 해당 언어로 번역된 **[소제목]**을 붙여서 내용을 명확히 구분하고 굵은 글씨를 생략하지 마세요.
            {curr_meta['structure']}

            [{labels[3]}]
            - 반드시 '{target_lang}'로만 작성하세요. (절대 다른 언어를 섞지 마세요)
            - 문장 끝이 끊기지 않도록 매끄럽게 연결하세요.
            """
            try:
                response = model.generate_content(prompt)
                batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": response.text, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
                time.sleep(1)
            except: pass

def run_tab1_analysis(ticker, company_name):
    """Tab 1: 비즈니스 요약 및 뉴스 (v2 캐시키 동기화)"""
    if not model: return False
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    
    LANG_MAP = {
        'ko': '전문적이고 자연스러운 한국어(Korean)',
        'en': 'Professional English',
        'ja': '極めて自然で専門的な日本語(Japanese)'
    }
    
    for lang_code, _ in SUPPORTED_LANGS.items():
        # 🚨 [핵심] app.py와 동일한 캐시 키 적용 (v2)
        cache_key = f"{ticker}_Tab1_v2_{lang_code}"
        target_lang = LANG_MAP.get(lang_code, '한국어')
        
        if lang_code == 'ja':
            task1_label = "[タスク1: ビジネスモデルの深層分析]"
            task2_label = "[タスク2: 最新ニュースの収集]"
            lang_instruction = "必ず自然な日本語のみで作成してください。韓国어나 영어 단어를 섞지 마세요. 기업명만 영어를 허용합니다."
        elif lang_code == 'en':
            task1_label = "[Task 1: Deep Business Model Analysis]"
            task2_label = "[Task 2: Latest News Collection]"
            lang_instruction = "Your entire response MUST be in English only. Do not use any Korean."
        else:
            task1_label = "[작업 1: 비즈니스 모델 심층 분석]"
            task2_label = "[작업 2: 최신 뉴스 수집]"
            lang_instruction = "반드시 자연스러운 한국어만 사용하세요."

        prompt = f"""
        당신은 최고 수준의 증권사 리서치 센터의 시니어 애널리스트입니다. 분석 대상: {company_name} ({ticker}) 오늘 날짜: {current_date}

        {task1_label}
        1. 언어: {lang_instruction}
        2. 포맷: 반드시 3개의 문단(비즈니스 모델, 재무 현황, 향후 전망)으로 나누어 작성하세요.
        3. 금지: 제목, 소제목, 특수기호, 불렛포인트(-)를 절대 쓰지 마세요. 인사말 없이 바로 본론부터 시작하세요.

        {task2_label}
        - 반드시 구글 검색을 실행하여 최근 1년 이내의 뉴스 5개를 선정하세요.
        - [중요] sentiment 값은 시스템 로직을 위해 무조건 "긍정", "부정", "일반" 중 하나를 한국어로 적으세요.
        형식: <JSON_START> {{ "news": [ {{ "title_en": "Original English Title", "translated_title": "{target_lang}로 번역된 제목", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }} <JSON_END>
        """
        try:
            response = model.generate_content(prompt)
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
            time.sleep(1.5)
        except: pass

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
        try:
            response = model.generate_content(prompt)
            batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": response.text, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
            time.sleep(1)
        except: pass

def run_tab4_analysis(ticker, company_name):
    """Tab 4: 월가 기관 분석 (강력 파싱 버전 동기화)"""
    if not model: return False
    
    LANG_MAP = {'ko': '한국어 (Korean)', 'en': '영어 (English)', 'ja': '일본어 (Japanese)'}
    
    for lang_code, _ in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Tab4_{lang_code}"
        target_lang = LANG_MAP.get(lang_code, '한국어 (Korean)')
        lang_instruction = f"Respond strictly in {target_lang}."
        if lang_code == 'ja': lang_instruction = "必ず日本語(Japanese)で作成してください。"

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
            "summary": "{target_lang}에 맞게 번역된 3줄 요약 내용",
            "pro_con": "**Pros**:\\n- 내용\\n\\n**Cons**:\\n- 내용 (언어: {target_lang})",
            "links": [ {{"title": "검색된 리포트 제목", "link": "URL"}} ]
        }}
        <JSON_END>
        """
        try:
            response = model.generate_content(prompt)
            match = re.search(r'<JSON_START>(.*?)<JSON_END>', response.text, re.DOTALL)
            if match:
                clean_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', match.group(1).strip())
                batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": clean_str, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
            time.sleep(1)
        except: pass

def update_macro_data(df):
    """Tab 2: 거시 지표 분석 코멘트"""
    if not model: return
    print("🌍 거시 지표(Tab 2) 업데이트 중...")
    
    # 워커에서는 간단히 기초 데이터만 구성하여 AI 코멘트만 캐싱해둡니다. (실제 수치 계산은 app.py가 담당)
    data = {"ipo_return": 15.2, "ipo_volume": len(df), "vix": 14.5, "fear_greed": 60} 
    
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key_report = f"Global_Market_Dashboard_Tab2_{lang_code}"
        try:
            prompt = f"""
            당신은 월가의 수석 시장 전략가(Chief Market Strategist)입니다.
            현재 시장 데이터(VIX: {data['vix']:.2f}, IPO수익률: {data['ipo_return']:.1f}%) 기반으로 현재 미국 주식 시장과 IPO 시장의 상태를 진단하는 일일 브리핑을 작성하세요.

            [작성 가이드]
            - 언어: 반드시 '{target_lang}'로 작성하세요. (다른 언어 절대 혼용 금지)
            - 형식: 줄글로 된 3~5줄의 요약 리포트로 제목, 소제목, 헤더(##), 인사말을 절대 포함하지 마세요.
            """
            ai_resp = model.generate_content(prompt).text
            # 불필요한 마크다운 기호 정제
            ai_resp = re.sub(r'^#+.*$', '', ai_resp, flags=re.MULTILINE).strip()
            
            batch_upsert("analysis_cache", [{"cache_key": cache_key_report, "content": ai_resp, "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
            time.sleep(1)
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
    
    total = len(df)
    print(f"\n🤖 AI 심층 분석 시작 (총 {total}개 종목)...")
    
    for idx, row in df.iterrows():
        symbol = row.get('symbol')
        name = row.get('name')
        listing_date = row.get('date')
        
        is_old = False
        try:
            if (datetime.now() - datetime.strptime(str(listing_date), "%Y-%m-%d")).days > 365: 
                is_old = True
        except: pass
        
        is_full_update = (datetime.now().weekday() == 0 or not is_old)
        
        print(f"[{idx+1}/{total}] {symbol} 분석 중...", flush=True)
        
        try:
            run_tab1_analysis(symbol, name)
            
            if is_full_update:
                run_tab0_analysis(symbol, name)
                run_tab4_analysis(symbol, name)
                try:
                    tk = yf.Ticker(symbol)
                    run_tab3_analysis(symbol, name, {"pe": tk.info.get('forwardPE', 0)})
                except: pass
            
            time.sleep(1.2) 
            
        except Exception as e:
            print(f"⚠️ {symbol} 분석 건너뜀: {e}")
            continue
            
    print(f"\n🏁 모든 작업 종료: {datetime.now()}")

if __name__ == "__main__":
    main()
