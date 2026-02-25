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

def run_tab0_analysis(ticker, company_name):
    """Tab 0: 공시 5종 분석"""
    if not model: return
    
    def_meta = {
        "S-1": {
            "points": "Risk Factors(특이 소송/규제), Use of Proceeds(자금 용도의 건전성), MD&A(성장 동인)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 해당 문서에서 발견된 가장 중요한 투자 포인트 분석
            2. 두 번째 문단: 실질적 성장 가능성과 재무적 의미 분석
            3. 세 번째 문단: 핵심 리스크 1가지와 그 파급 효과 및 대응책
            """
        },
        "S-1/A": {
            "points": "Pricing Terms(수요예측 분위기), Dilution(신규 투자자 희석률), Changes(이전 제출본과의 차이점)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 이전 S-1 대비 변경된 핵심 사항 분석
            2. 두 번째 문단: 제시된 공모가 범위의 적정성 및 수요예측 분위기 분석
            3. 세 번째 문단: 기존 주주 가치 희석 정도와 투자 매력도 분석
            """
        },
        "F-1": {
            "points": "Foreign Risk(지정학적 리스크), Accounting(GAAP 차이), ADS(주식 예탁 증서 구조)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 기업이 글로벌 시장에서 가진 독보적인 경쟁 우위
            2. 두 번째 문단: 환율, 정치, 회계 등 해외 기업 특유의 리스크 분석
            3. 세 번째 문단: 미국 예탁 증서(ADS) 구조가 주주 권리에 미치는 영향
            """
        },
        "FWP": {
            "points": "Graphics(시장 점유율 시각화), Strategy(미래 핵심 먹거리), Highlights(경영진 강조 사항)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 경영진이 로드쇼에서 강조하는 미래 성장 비전
            2. 두 번째 문단: 경쟁사 대비 부각시키는 기술적/사업적 차별화 포인트
            3. 세 번째 문단: 자료 톤앤매너로 유추할 수 있는 시장 공략 의지
            """
        },
        "424B4": {
            "points": "Underwriting(주관사 등급), Final Price(기관 배정 물량), IPO Outcome(최종 공모 결과)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 확정 공모가의 위치와 시장 수요 해석
            2. 두 번째 문단: 확정된 조달 자금의 투입 우선순위 점검
            3. 세 번째 문단: 주관사단 및 배정 물량 바탕 상장 초기 유통물량 예측
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

    for topic in ["S-1", "S-1/A", "F-1", "FWP", "424B4"]:
        curr_meta = def_meta[topic]
        
        for lang_code, target_lang in SUPPORTED_LANGS.items():
            cache_key = f"{company_name}_{topic}_Tab0_v11_{lang_code}"
            
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

def run_tab1_analysis(ticker, company_name, ipo_status="Active"):
    """Tab 1: 비즈니스 요약 및 뉴스 (워커용 - 상태별 프롬프트 자동 분기)"""
    if not model: return False
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    
    # 💡 [1. 동적 캐싱 로직] 
    if ipo_status == "상장예정(30일이내)": valid_hours = 6
    elif ipo_status in ["상장대기", "상장연기", "상장폐지"]: valid_hours = 24 * 7
    else: valid_hours = 24
        
    limit_time_str = (now - timedelta(hours=valid_hours)).isoformat()
    
    # 💡 [상태 판별] 상장 철회/취소/폐지/연기 여부 확인
    status_lower = str(ipo_status).lower()
    is_cancelled = any(x in status_lower for x in ['연기', '폐지', '철회', '취소', 'delayed', 'delisted', 'withdrawn'])
    
    for lang_code, target_lang_str in SUPPORTED_LANGS.items():
        # app.py와 캐시 키를 완벽히 동기화 (상태값 포함)
        cache_key = f"{ticker}_Tab1_v3_{lang_code}_{ipo_status}"
        
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
        - 반드시 구글 검색을 실행하여 최신 정보를 확인하세요.
        - {current_date} 기준, 최근 1년 이내의 뉴스 5개를 선정하세요.
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
                        # 💡 [최신 뉴스 정렬 로직] 워커에서도 DB 저장 전에 최신순으로 정렬!
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
    
    print(f"\n🤖 AI 심층 분석 시작 (총 {total}개 종목 다국어 캐싱)...")
    
    for idx, row in target_df.iterrows():
        symbol = row.get('symbol')
        name = row.get('name')
        
        print(f"[{idx+1}/{total}] {symbol} 분석 중...", flush=True)
        
        try:
            # 💡 [핵심] 캘린더 row에서 상태(status)와 날짜(date)를 꺼내서 워커에게 전달합니다.
            c_status = row.get('status', 'Active')
            c_date = row.get('date', None)
            
            # Tab1 도 아까 수정한 대로 상태를 넘겨받을 수 있게 맞춰줍니다.
            run_tab1_analysis(symbol, name, c_status)
            run_tab0_analysis(symbol, name, c_status, c_date)
            run_tab4_analysis(symbol, name)
            
            try:
                tk = yf.Ticker(symbol)
                run_tab3_analysis(symbol, name, {"pe": tk.info.get('forwardPE', 0)})
            except: pass
            
            time.sleep(1.2)
            
        except Exception as e:
            print(f"⚠️ {symbol} 분석 건너뜀: {e}")
            continue

    # 💡 [핵심 추가] 모든 AI 분석이 완료된 후, 전체 캘린더를 대상으로 알림 엔진 가동
    run_premium_alert_engine(df)
            
    print(f"\n🏁 모든 작업 종료: {datetime.now()}")

if __name__ == "__main__":
    main()
