import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import xml.etree.ElementTree as ET
import time
import uuid
import random

# --- [AI 및 검색 기능] ---
from tavily import TavilyClient   # (필수) 검색 담당
from openai import OpenAI         # (필수) 요약 담당 -> 이게 꼭 있어야 해요!
from duckduckgo_search import DDGS # (선택) 혹시 모를 비상용

# --- [주식 및 차트 기능 (기존 기능 유지)] ---
import yfinance as yf             # 주가 데이터
import plotly.graph_objects as go # 차트 그리기

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 세션 초기화 ---
for key in ['page', 'auth_status', 'vote_data', 'comment_data', 'selected_stock', 'watchlist', 'view_mode', 'news_topic']:
    if key not in st.session_state:
        if key == 'page': st.session_state[key] = 'intro'
        elif key == 'watchlist': st.session_state[key] = []
        elif key in ['vote_data', 'comment_data', 'user_votes']: st.session_state[key] = {}
        elif key == 'view_mode': st.session_state[key] = 'all'
        elif key == 'news_topic': st.session_state[key] = "💰 공모가 범위/확정 소식"
        else: st.session_state[key] = None

# --- CSS 스타일 ---
st.markdown("""
    <style>
    /* 전체 앱 스타일 */
    .stApp { background-color: #FFFFFF; color: #333333; }
    
    .intro-card {
        background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%);
        padding: 50px 30px; border-radius: 30px; color: white !important;
        text-align: center; margin-top: 20px; 
        box-shadow: 0 20px 40px rgba(110, 142, 251, 0.3);
    }
    .intro-title { font-size: 40px; font-weight: 900; margin-bottom: 10px; color: white !important; }
    
    .feature-grid { display: flex; justify-content: space-around; gap: 15px; margin-bottom: 25px; }
    .feature-item {
        background: rgba(255, 255, 255, 0.2);
        padding: 20px 10px; border-radius: 20px; flex: 1;
        backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.3);
        color: white !important; text-align: center;
    }
    
    .grid-card { 
        background-color: #ffffff !important; 
        padding: 25px; border-radius: 20px; 
        border: 1px solid #eef2ff; box-shadow: 0 10px 20px rgba(0,0,0,0.05); 
        text-align: center; color: #333333 !important; height: 100%;
    }
    
    .quote-card {
        background: linear-gradient(145deg, #ffffff, #f9faff);
        padding: 25px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.05); text-align: center;
        max-width: 650px; margin: 40px auto; color: #333333 !important;
    }
    
    .comment-box { background-color: #f8f9fa; padding: 10px; border-radius: 10px; margin-bottom: 5px; border-left: 3px solid #dee2e6; color: #333; }
    button p { font-weight: bold !important; }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 로직 (캐싱 최적화 적용) ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

@st.cache_data(ttl=43200) # 12시간마다 갱신
def get_daily_quote():
    # 1. 예비용 명언 리스트 (한글 번역 추가됨)
    backup_quotes = [
        {"eng": "Opportunities don't happen. You create them.", "kor": "기회는 찾아오는 것이 아닙니다. 당신이 만드는 것입니다.", "author": "Chris Grosser"},
        {"eng": "The best way to predict the future is to create it.", "kor": "미래를 예측하는 가장 좋은 방법은 미래를 창조하는 것입니다.", "author": "Peter Drucker"},
        {"eng": "Do not be embarrassed by your failures, learn from them and start again.", "kor": "실패를 부끄러워하지 마세요. 배우고 다시 시작하세요.", "author": "Richard Branson"},
        {"eng": "Innovation distinguishes between a leader and a follower.", "kor": "혁신이 리더와 추종자를 구분합니다.", "author": "Steve Jobs"},
        {"eng": "It’s not about ideas. It’s about making ideas happen.", "kor": "아이디어 자체가 중요한 게 아닙니다. 실행하는 것이 중요합니다.", "author": "Scott Belsky"},
        {"eng": "The only way to do great work is to love what you do.", "kor": "위대한 일을 하는 유일한 방법은 그 일을 사랑하는 것입니다.", "author": "Steve Jobs"},
        {"eng": "Risk comes from not knowing what you're doing.", "kor": "위험은 자신이 무엇을 하는지 모르는 데서 옵니다.", "author": "Warren Buffett"},
        {"eng": "Success is walking from failure to failure with no loss of enthusiasm.", "kor": "성공이란 열정을 잃지 않고 실패를 거듭해 나가는 능력입니다.", "author": "Winston Churchill"}
    ]

    try:
        # 1. API로 영어 명언 가져오기
        res = requests.get("https://api.quotable.io/random?tags=business", timeout=2).json()
        eng_text = res['content']
        author = res['author']
        
        # 2. 한글 번역 시도 (기존 뉴스 번역 API 활용)
        kor_text = ""
        try:
            trans_url = "https://api.mymemory.translated.net/get"
            trans_res = requests.get(trans_url, params={'q': eng_text, 'langpair': 'en|ko'}, timeout=2).json()
            if trans_res['responseStatus'] == 200:
                kor_text = trans_res['responseData']['translatedText'].replace("&quot;", "'").replace("&amp;", "&")
        except:
            pass # 번역 실패 시 빈 칸

        # 번역 실패 시 예비 멘트 혹은 영어만 리턴 방지
        if not kor_text: 
            kor_text = "Global Business Quote"

        return {"eng": eng_text, "kor": kor_text, "author": author}

    except:
        # API 실패 시, 예비 리스트에서 랜덤 선택
        return random.choice(backup_quotes)
@st.cache_data(ttl=86400) # 24시간 (재무제표는 분기마다 바뀌므로 하루 종일 캐싱해도 안전)
def get_financial_metrics(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/stock/metric?symbol={symbol}&metric=all&token={api_key}"
        res = requests.get(url, timeout=5).json()
        metrics = res.get('metric', {})
        return {
            "growth": metrics.get('salesGrowthYoy', None),
            "op_margin": metrics.get('operatingMarginTTM', None),
            "net_margin": metrics.get('netProfitMarginTTM', None),
            "debt_equity": metrics.get('totalDebt/totalEquityQuarterly', None)
        } if metrics else None
    except: return None

@st.cache_data(ttl=86400) # 24시간 (기업 프로필도 거의 안 바뀜)
def get_company_profile(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={api_key}"
        res = requests.get(url, timeout=5).json()
        return res if res and 'name' in res else None
    except: return None

@st.cache_data(ttl=14400) # [수정] 4시간 (IPO 일정은 하루에 여러 번 바뀌지 않으므로 길게 잡음)
def get_extended_ipo_data(api_key):
    start = (datetime.now() - timedelta(days=540)).strftime('%Y-%m-%d')
    end = (datetime.now() + timedelta(days=120)).strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/calendar/ipo?from={start}&to={end}&token={api_key}"
    try:
        res = requests.get(url, timeout=5).json()
        df = pd.DataFrame(res.get('ipoCalendar', []))
        if not df.empty: df['공모일_dt'] = pd.to_datetime(df['date'])
        return df
    except: return pd.DataFrame()

# 주가(Price)는 실시간성이 중요하므로 캐싱하지 않거나 아주 짧게(1~5분) 잡는 것이 좋습니다.
def get_current_stock_price(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
        return requests.get(url, timeout=2).json().get('c', 0)
    except: return 0

# [뉴스 감성 분석 함수 - 내부 연산이므로 별도 캐싱 불필요]
def analyze_sentiment(text):
    text = text.lower()
    pos_words = ['jump', 'soar', 'surge', 'rise', 'gain', 'buy', 'outperform', 'beat', 'success', 'growth', 'up', 'high', 'profit', 'approval']
    neg_words = ['drop', 'fall', 'plunge', 'sink', 'loss', 'miss', 'fail', 'risk', 'down', 'low', 'crash', 'suit', 'ban', 'warning']
    score = 0
    for w in pos_words:
        if w in text: score += 1
    for w in neg_words:
        if w in text: score -= 1
    
    if score > 0: return "긍정", "#e6f4ea", "#1e8e3e"
    elif score < 0: return "부정", "#fce8e6", "#d93025"
    else: return "일반", "#f1f3f4", "#5f6368"

@st.cache_data(ttl=3600) # [수정] 1시간 (3600초) 동안 뉴스 다시 안 부름!
def get_real_news_rss(company_name):
    """구글 뉴스 RSS + 한글 번역 + 감성 분석"""
    try:
        query = f"{company_name} stock news"
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        response = requests.get(url, timeout=3)
        root = ET.fromstring(response.content)
        
        news_items = []
        for item in root.findall('./channel/item')[:5]:
            title_en = item.find('title').text
            link = item.find('link').text
            pubDate = item.find('pubDate').text
            
            # 1. 감성 분석
            sent_label, bg, color = analyze_sentiment(title_en)
            
            # 2. 날짜 포맷
            try: date_str = " ".join(pubDate.split(' ')[1:3])
            except: date_str = "Recent"

            # 3. 한글 번역 (MyMemory API)
            try:
                trans_url = "https://api.mymemory.translated.net/get"
                res = requests.get(trans_url, params={'q': title_en, 'langpair': 'en|ko'}, timeout=1).json()
                if res['responseStatus'] == 200:
                    title_ko = res['responseData']['translatedText'].replace("&quot;", "'").replace("&amp;", "&")
                    display_title = f"{title_en}<br><span style='font-size:14px; color:#555; font-weight:normal;'>🇰🇷 {title_ko}</span>"
                else: display_title = title_en
            except: display_title = title_en
            
            news_items.append({
                "title": display_title, "link": link, "date": date_str,
                "sent_label": sent_label, "bg": bg, "color": color
            })
        return news_items
    except: return []

# [추가: 뉴스 감성 분석 함수]
def analyze_sentiment(text):
    text = text.lower()
    pos_words = ['jump', 'soar', 'surge', 'rise', 'gain', 'buy', 'outperform', 'beat', 'success', 'growth', 'up', 'high', 'profit', 'approval']
    neg_words = ['drop', 'fall', 'plunge', 'sink', 'loss', 'miss', 'fail', 'risk', 'down', 'low', 'crash', 'suit', 'ban', 'warning']
    score = 0
    for w in pos_words:
        if w in text: score += 1
    for w in neg_words:
        if w in text: score -= 1
    
    if score > 0: return "긍정", "#e6f4ea", "#1e8e3e"
    elif score < 0: return "부정", "#fce8e6", "#d93025"
    else: return "일반", "#f1f3f4", "#5f6368"

@st.cache_data(ttl=300)
def get_real_news_rss(company_name):
    """구글 뉴스 RSS + 한글 번역 + 감성 분석"""
    try:
        query = f"{company_name} stock news"
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        response = requests.get(url, timeout=3)
        root = ET.fromstring(response.content)
        
        news_items = []
        for item in root.findall('./channel/item')[:5]:
            title_en = item.find('title').text
            link = item.find('link').text
            pubDate = item.find('pubDate').text
            
            # 1. 감성 분석
            sent_label, bg, color = analyze_sentiment(title_en)
            
            # 2. 날짜 포맷
            try: date_str = " ".join(pubDate.split(' ')[1:3])
            except: date_str = "Recent"

            # 3. 한글 번역 (MyMemory API)
            try:
                trans_url = "https://api.mymemory.translated.net/get"
                res = requests.get(trans_url, params={'q': title_en, 'langpair': 'en|ko'}, timeout=1).json()
                if res['responseStatus'] == 200:
                    title_ko = res['responseData']['translatedText'].replace("&quot;", "'").replace("&amp;", "&")
                    display_title = f"{title_en}<br><span style='font-size:14px; color:#555; font-weight:normal;'>🇰🇷 {title_ko}</span>"
                else: display_title = title_en
            except: display_title = title_en
            
            news_items.append({
                "title": display_title, "link": link, "date": date_str,
                "sent_label": sent_label, "bg": bg, "color": color
            })
        return news_items
    except: return []

# [수정] Tavily 검색 + Groq(무료 AI) 요약 함수 (최신 모델 적용)
@st.cache_data(show_spinner=False, ttl=86400)
def get_ai_summary(query):
    """
    Tavily API로 검색하고, Groq(무료 LLM)로 요약하는 함수
    """
    tavily_key = st.secrets.get("TAVILY_API_KEY")
    groq_key = st.secrets.get("GROQ_API_KEY") 

    if not tavily_key or not groq_key:
        return "⚠️ API 키 설정 오류: Secrets를 확인하세요."

    try:
        # 1. Tavily 검색
        tavily = TavilyClient(api_key=tavily_key)
        search_result = tavily.search(query=query, search_depth="basic", max_results=3)
        
        if not search_result.get('results'):
            return None # 결과 없으면 조용히 넘어감 (UI에서 처리)

        context = "\n".join([r['content'] for r in search_result['results']])
        
        # 2. Groq 요약 요청
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key
        )
        
        response = client.chat.completions.create(
            # 여기가 변경되었습니다! (최신 고성능 모델)
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role": "system", "content": "You are a financial expert. Summarize the key facts in Korean within 3 sentences."},
                {"role": "user", "content": f"Context:\n{context}\n\nQuery: {query}\n\nPlease summarize appropriately."}
            ]
        )
        return response.choices[0].message.content

    except Exception as e:
        # 에러가 나면 화면에 보여줌
        return f"🚫 오류: {str(e)}"
        
# --- 화면 제어 시작 ---

# 1. 인트로
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 10, 1])
    with col_center:
        st.markdown("""
            <div class='intro-card'>
                <div class='intro-title'>Unicornfinder</div>
                <div class='feature-grid'>
                    <div class='feature-item'><div style='font-size:28px;'>📅</div>IPO 스케줄</div>
                    <div class='feature-item'><div style='font-size:28px;'>📊</div>AI 가격 예측</div>
                    <div class='feature-item'><div style='font-size:28px;'>🗳️</div>관심기업 관리</div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        if st.button("시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()

# 2. 로그인 화면
elif st.session_state.page == 'login':
    st.write("<br>" * 5, unsafe_allow_html=True)
    _, col_m, _ = st.columns([1, 1.2, 1])
    
    # [가상 DB] 가입된 사용자 목록을 기억하기 위한 임시 저장소
    # 앱을 새로고침하면 초기화되지만, 사용하는 동안은 기억합니다.
    if 'db_users' not in st.session_state:
        st.session_state.db_users = ["010-0000-0000"] # 테스트용: 관리자 번호는 이미 가입된 것으로 간주
    
    with col_m:
        # 로그인 단계 초기화
        if 'login_step' not in st.session_state: st.session_state.login_step = 'choice'

        # [Step 1] 첫 선택 화면 (로그인 vs 회원가입 분리)
        if st.session_state.login_step == 'choice':
            st.write("")
            
            # 버튼 1: 기존 회원 로그인 (바로 입력창으로)
            if st.button("로그인", use_container_width=True, type="primary"):
                st.session_state.login_step = 'login_input' # 로그인 입력 단계로 이동
                st.rerun()
                
            # 버튼 2: 신규 회원 가입 (안내 화면으로)
            if st.button("회원가입", use_container_width=True):
                st.session_state.login_step = 'ask_signup' # 가입 안내 단계로 이동
                st.rerun()
                
            # 버튼 3: 비회원 둘러보기
            if st.button("구경하기", use_container_width=True):
                st.session_state.auth_status = 'guest'
                st.session_state.page = 'stats'
                st.rerun()

        # [Step 2-A] 로그인 입력 화면 (기존 회원용)
        elif st.session_state.login_step == 'login_input':
            st.markdown("### 🔑 로그인")
            phone_login = st.text_input("가입하신 휴대폰 번호를 입력하세요", placeholder="010-0000-0000", key="login_phone")
            
            l_c1, l_c2 = st.columns([2, 1])
            with l_c1:
                if st.button("접속하기", use_container_width=True, type="primary"):
                    # 가입된 번호인지 확인
                    if phone_login in st.session_state.db_users:
                        st.session_state.auth_status = 'user'
                        st.session_state.user_phone = phone_login # 세션에 정보 저장
                        st.success(f"반갑습니다! {phone_login}님")
                        st.session_state.page = 'stats'
                        st.session_state.login_step = 'choice'
                        st.rerun()
                    else:
                        st.error("가입되지 않은 번호입니다. 회원가입을 먼저 진행해주세요.")
            with l_c2:
                if st.button("뒤로가기", use_container_width=True):
                    st.session_state.login_step = 'choice'
                    st.rerun()

        # [Step 2-B] 회원가입 안내 화면 (신규 회원용)
        elif st.session_state.login_step == 'ask_signup':
            st.info("회원가입시 IPO정보알림받기 및 관심기업관리가 가능합니다.")
            c1, c2 = st.columns(2)
            if c1.button("✅ 가입 진행", use_container_width=True):
                st.session_state.login_step = 'signup_input' # 가입 입력 단계로 이동
                st.rerun()
            if c2.button("❌ 취소", use_container_width=True):
                st.session_state.login_step = 'choice'
                st.rerun()

        # [Step 3] 가입 정보 입력 (신규 회원용)
        elif st.session_state.login_step == 'signup_input':
            st.markdown("### 📝 정보 입력")
            phone_signup = st.text_input("사용하실 휴대폰 번호를 입력하세요", placeholder="010-0000-0000", key="signup_phone")
            
            s_c1, s_c2 = st.columns([2, 1])
            with s_c1:
                if st.button("가입 완료", use_container_width=True, type="primary"):
                    if len(phone_signup) >= 10:
                        # 이미 존재하는지 확인
                        if phone_signup in st.session_state.db_users:
                            st.warning("이미 가입된 번호입니다. '기존 회원 로그인'을 이용해주세요.")
                        else:
                            # [DB 저장] 신규 회원을 리스트에 추가
                            st.session_state.db_users.append(phone_signup)
                            
                            st.session_state.auth_status = 'user'
                            st.session_state.user_phone = phone_signup
                            st.balloons() # 가입 축하 효과
                            st.toast("회원가입을 축하합니다!", icon="🎉")
                            st.session_state.page = 'stats'
                            st.session_state.login_step = 'choice'
                            st.rerun()
                    else: st.error("올바른 번호를 입력해주세요.")
            with s_c2:
                if st.button("취소", key="back_signup"):
                    st.session_state.login_step = 'choice'
                    st.rerun()

    st.write("<br>" * 2, unsafe_allow_html=True)
    q = get_daily_quote()
    
    # [수정] 한글(kor)이 추가된 HTML 디자인
    st.markdown(f"""
        <div class='quote-card'>
            <b>"{q['eng']}"</b>
            <br>
            <span style='font-size:14px; color:#555; font-weight:normal;'>{q['kor']}</span>
            <br><br>
            <small>- {q['author']} -</small>
        </div>
    """, unsafe_allow_html=True)

# 3. 성장 단계 분석 (대시보드) - 심플 버전 (박스 제거)
elif st.session_state.page == 'stats':
    st.write("<br>", unsafe_allow_html=True)
    
    # 이미지 파일명 (사용자 지정)
    img_baby = "new_unicorn.png"
    img_adult = "hot_unicorn.png"
    img_child = "fav_unicorn.png"
    
    c1, c2, c3 = st.columns(3)
    
    # 1. NEW 섹션
    with c1:
        # 박스(<div class='grid-card'>) 제거 -> 이미지 바로 출력
        if os.path.exists(img_baby): 
            st.image(img_baby, use_container_width=True)
        
        # 버튼 (텍스트 역할)
        if st.button("신규상장", use_container_width=True, key="go_all"):
            st.session_state.view_mode = 'all'
            st.session_state.page = 'calendar'
            st.rerun()

    # 2. HOT 섹션
    with c2:
        # 박스 제거
        if os.path.exists(img_adult): 
            st.image(img_adult, use_container_width=True)
            
        if st.button("인기상승", use_container_width=True, key="go_hot"):
            st.session_state.view_mode = 'hot'
            st.session_state.page = 'calendar'
            st.rerun()

    # 3. MY 섹션
    with c3:
        # 박스 제거
        if os.path.exists(img_child): 
            st.image(img_child, use_container_width=True)
            
        watch_count = len(st.session_state.watchlist)
        if st.button(f"나의 관심 ({watch_count})", use_container_width=True, type="primary", key="go_watch"):
            st.session_state.view_mode = 'watchlist'
            st.session_state.page = 'calendar'
            st.rerun()

# 4. 캘린더 페이지 (모바일 최적화: 수직 중앙 정렬 & 행 일치)
elif st.session_state.page == 'calendar':
    # [CSS] 스타일 정의
    st.markdown("""
        <style>
        /* 1. 기본 설정 */
        * { box-sizing: border-box !important; color: #333333 !important; }
        
        /* 2. 상단 여백 확보 */
        .block-container {
            padding-top: 4rem !important;
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
            max-width: 100% !important;
        }

        /* 3. 버튼 스타일 (타이트하게 조임) */
        .stButton button {
            background-color: transparent !important;
            border: none !important;
            padding: 0 !important;
            margin: 0 !important;
            color: #333 !important;
            text-align: left !important;
            box-shadow: none !important;
            width: 100% !important;
            display: block !important;
            overflow: hidden !important;
            white-space: nowrap !important;
            text-overflow: ellipsis !important;
            height: auto !important;
            line-height: 1.1 !important; /* 줄 간격 좁힘 */
        }
        .stButton button p { font-weight: bold; font-size: 14px; margin-bottom: 0px; }

        /* 4. [모바일 레이아웃 핵심] */
        @media (max-width: 640px) {
            
            /* (A) 상단 필터: 줄바꿈 허용 */
            div[data-testid="stHorizontalBlock"]:nth-of-type(1) {
                flex-wrap: wrap !important;
                gap: 10px !important;
                padding-bottom: 5px !important;
            }
            div[data-testid="stHorizontalBlock"]:nth-of-type(1) > div {
                min-width: 100% !important;
                max-width: 100% !important;
                flex: 1 1 100% !important;
            }

            /* (B) 리스트 구역: 가로 고정 & 수직 중앙 정렬 (핵심!) */
            div[data-testid="stHorizontalBlock"]:not(:nth-of-type(1)) {
                flex-direction: row !important;
                flex-wrap: nowrap !important;
                gap: 0px !important;
                width: 100% !important;
                align-items: center !important; /* 위아래 중앙 정렬 */
            }

            /* (C) 컬럼 내부 정렬 강제 (내용물이 흩어지지 않게 모음) */
            div[data-testid="column"] {
                display: flex !important;
                flex-direction: column !important;
                justify-content: center !important; /* 수직 가운데 */
                min-width: 0px !important;
                padding: 0px 2px !important;
            }

            /* (D) 리스트 컬럼 비율 (7:3) */
            div[data-testid="stHorizontalBlock"]:not(:nth-of-type(1)) > div[data-testid="column"]:nth-of-type(1) {
                flex: 0 0 70% !important;
                max-width: 70% !important;
                overflow: hidden !important;
            }
            div[data-testid="stHorizontalBlock"]:not(:nth-of-type(1)) > div[data-testid="column"]:nth-of-type(2) {
                flex: 0 0 30% !important;
                max-width: 30% !important;
            }

            /* (E) 폰트 및 간격 미세 조정 */
            .mobile-sub { font-size: 10px !important; color: #888 !important; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: -2px; line-height: 1.1; }
            .price-main { font-size: 13px !important; font-weight: bold; white-space: nowrap; line-height: 1.1; }
            .price-sub { font-size: 10px !important; color: #666 !important; white-space: nowrap; line-height: 1.1; }
            .date-text { font-size: 10px !important; color: #888 !important; margin-top: 1px; line-height: 1.1; }
            .header-text { font-size: 12px !important; line-height: 1.0; }
        }
        </style>
    """, unsafe_allow_html=True)

    st.sidebar.button("⬅️ 메인으로", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    
    # 1. 데이터 가져오기
    all_df_raw = get_extended_ipo_data(MY_API_KEY)
    view_mode = st.session_state.get('view_mode', 'all')
    
    if not all_df_raw.empty:
        all_df = all_df_raw.dropna(subset=['exchange'])
        all_df = all_df[all_df['exchange'].astype(str).str.upper() != 'NONE']
        all_df = all_df[all_df['symbol'].astype(str).str.strip() != ""]
        today = datetime.now().date()
        
        # 2. 필터 로직
        if view_mode == 'watchlist':
            st.title("⭐ 나의 관심 종목")
            display_df = all_df[all_df['symbol'].isin(st.session_state.watchlist)]
        else:
            col_f1, col_f2 = st.columns([2, 1])
            with col_f1:
                period = st.radio("📅 조회 기간", ["상장 예정 (90일)", "최근 6개월", "최근 12개월", "최근 18개월"], horizontal=True)
            with col_f2:
                sort_option = st.selectbox("🎯 리스트 정렬", ["최신순 (기본)", "🚀 수익률 높은순 (실시간)", "📈 매출 성장률순 (AI)"])
            
            if period == "상장 예정 (90일)":
                display_df = all_df[(all_df['공모일_dt'].dt.date >= today) & (all_df['공모일_dt'].dt.date <= today + timedelta(days=90))]
            elif period == "최근 6개월": 
                display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=180))]
            elif period == "최근 12개월": 
                display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=365))]
            elif period == "최근 18개월": 
                display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=540))]

        # 정렬 로직
        display_df['live_price'] = 0.0
        if not display_df.empty:
            if sort_option == "최신순 (기본)":
                display_df = display_df.sort_values(by='공모일_dt', ascending=False)
            elif sort_option == "🚀 수익률 높은순 (실시간)":
                 with st.spinner("🔄 시세 조회 중..."):
                    returns = []
                    prices = []
                    for idx, row in display_df.iterrows():
                        try:
                            p_ipo = float(str(row.get('price','0')).replace('$','').split('-')[0])
                            p_curr = get_current_stock_price(row['symbol'], MY_API_KEY)
                            ret = ((p_curr - p_ipo) / p_ipo) * 100 if p_ipo > 0 and p_curr > 0 else -9999
                        except: ret = -9999; p_curr = 0
                        returns.append(ret); prices.append(p_curr)
                    display_df['temp_return'] = returns; display_df['live_price'] = prices
                    display_df = display_df.sort_values(by='temp_return', ascending=False)
            elif sort_option == "📈 매출 성장률순 (AI)":
                 with st.spinner("📊 재무 분석 중..."):
                    growths = []
                    for idx, row in display_df.iterrows():
                        try:
                            fins = get_financial_metrics(row['symbol'], MY_API_KEY)
                            g = float(fins['growth']) if fins else -9999
                        except: g = -9999
                        growths.append(g)
                    display_df['temp_growth'] = growths
                    display_df = display_df.sort_values(by='temp_growth', ascending=False)

        # ----------------------------------------------------------------
        # [핵심] 리스트 레이아웃 (7 : 3 비율)
        # ----------------------------------------------------------------
        
        if not display_df.empty:
            st.write("---")
            
  

            # 2. 데이터 리스트
            for i, row in display_df.iterrows():
                p_val = pd.to_numeric(str(row.get('price','')).replace('$','').split('-')[0], errors='coerce')
                p_val = p_val if p_val and p_val > 0 else 0
                
                # 가격 HTML
                live_p = row.get('live_price', 0)
                if live_p > 0:
                    pct = ((live_p - p_val)/p_val)*100
                    color = "#d93025" if pct < 0 else "#1e8e3e"
                    price_html = f"""
                        <div class='price-main' style='color:{color};'>${live_p:,.2f} ({pct:+.0f}%)</div>
                        <div class='price-sub'>IPO: ${p_val:,.2f}</div>
                    """
                else:
                    price_html = f"""
                        <div class='price-main'>${p_val:,.2f}</div>
                        <div class='price-sub'>공모가</div>
                    """
                
                # 날짜 HTML
                date_html = f"<div class='date-text'>{row['date']}</div>"

                # 2단 컬럼 배치 (7:3 비율 적용)
                c1, c2 = st.columns([7, 3])
                
                # [왼쪽 70%] 기업명 + 하단정보
                with c1:
                    # 기업명 버튼
                    if st.button(f"{row['name']}", key=f"btn_list_{i}"):
                        st.session_state.selected_stock = row.to_dict()
                        st.session_state.page = 'detail'
                        st.rerun()
                    
                    try: s_val = int(row.get('numberOfShares',0)) * p_val / 1000000
                    except: s_val = 0
                    size_str = f" | ${s_val:,.0f}M" if s_val > 0 else ""
                    
                    # [수정] margin-top을 0에 가깝게 조정하여 위 버튼과 찰싹 붙임
                    st.markdown(f"<div class='mobile-sub' style='margin-top:-2px; padding-left:2px;'>{row['symbol']} | {row.get('exchange','-')}{size_str}</div>", unsafe_allow_html=True)

                # [오른쪽 30%] 가격 + 날짜 (우측 정렬)
                with c2:
                    st.markdown(f"<div style='text-align:right;'>{price_html}{date_html}</div>", unsafe_allow_html=True)
                
                st.markdown("<div style='border-bottom:1px solid #f0f2f6; margin: 4px 0;'></div>", unsafe_allow_html=True)

        else:
            st.info("조건에 맞는 종목이 없습니다.")

        

# 5. 상세 페이지 (기능/디자인 100% 복구 + 에러 수정 완료)
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    
    # [중요] 변수 초기화 (NameError 방지)
    profile = None
    fin_data = None
    current_p = 0
    off_val = 0

    if stock:
        # [1. 데이터 로딩 및 초기 설정]
        today = datetime.now().date()
        try: 
            ipo_dt = stock['공모일_dt'].date() if hasattr(stock['공모일_dt'], 'date') else pd.to_datetime(stock['공모일_dt']).date()
        except: 
            ipo_dt = today
        
        status_emoji = "🐣" if ipo_dt > (today - timedelta(days=365)) else "🦄"
        date_str = ipo_dt.strftime('%Y-%m-%d') # 상장일 문자열 생성

        if st.button("⬅️ 목록으로"): 
            st.session_state.page = 'calendar'; st.rerun()

        # API 데이터 호출
        with st.spinner(f"🤖 {stock['name']} 데이터를 정밀 분석 중입니다..."):
            try: off_val = float(str(stock.get('price', '0')).replace('$', '').split('-')[0].strip())
            except: off_val = 0
            
            try:
                current_p = get_current_stock_price(stock['symbol'], MY_API_KEY)
                profile = get_company_profile(stock['symbol'], MY_API_KEY) 
                fin_data = get_financial_metrics(stock['symbol'], MY_API_KEY)
            except: pass

        # [2. 헤더 섹션: 상장일 추가 및 등락률 표시]
        # 요청사항: 기업명 (상장일 / 공모가격 / 현재가격 / 증감비율)
        if current_p > 0 and off_val > 0:
            pct = ((current_p - off_val) / off_val) * 100
            color = "#00ff41" if pct >= 0 else "#ff4b4b"
            icon = "▲" if pct >= 0 else "▼"
            # 상장일(date_str) 추가
            p_html = f"({date_str} / 공모 ${off_val} / 현재 ${current_p} <span style='color:{color}'><b>{icon} {abs(pct):.1f}%</b></span>)"
        else:
            p_html = f"({date_str} / 공모 ${off_val} / 상장 대기)"

        st.markdown(f"<h1>{status_emoji} {stock['name']} <small>{p_html}</small></h1>", unsafe_allow_html=True)
        st.write("---")

        # [3. 탭 메뉴 구성]
        tab0, tab1, tab2, tab3 = st.tabs(["📰 주요 뉴스", "📋 주요 공시", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])

        # --- Tab 0: 뉴스 & 심층 분석 (수정: 비즈니스 모델 집중 모드) ---
        with tab0:
            
            st.caption("Tavily AI 검색 엔진이 최신 웹 정보를 수집하고 AI가 핵심 내용을 요약합니다.")

            # [1] 검색어 생성 (비즈니스 모델만 설정)
            q_biz = f"{stock['name']} IPO stock company business model revenue stream competitive advantage"
            
            # [2] 비즈니스 모델 섹션 (화면 전체 너비 사용)
            st.markdown(f"""
    <div style="margin-top: 20px; margin-bottom:15px;">
        <h3 style="margin:0; color:#333; font-size:22px; font-weight:700; line-height:1.4;">
            비즈니스 모델
        </h3>
    </div>""", unsafe_allow_html=True)
            
            # 로딩 및 결과 표시
            with st.spinner(f"🤖 AI가 {stock['name']}의 사업 구조를 분석하고 있습니다..."):
                # 아까 수정한 Tavily+Groq 함수 호출
                biz_info = get_ai_summary(q_biz)
                
                if biz_info:
                    # 초록색 박스로 깔끔하게 표시
                    st.success(biz_info)
                else:
                    st.error("⚠️ 정보를 찾을 수 없습니다. (신생 스팩주이거나 정보가 부족할 수 있습니다)")
                    
            # 구글 검색 링크 (보조)
            st.markdown(f"""
                <div style="text-align: right; margin-top: 5px;">
                    <a href="https://www.google.com/search?q={q_biz}" target="_blank" style="text-decoration:none; color:#666; font-size:14px;">
                        👉 구글에서 원문 검색 결과 보기
                    </a>
                </div>
            """, unsafe_allow_html=True)

            st.write("---")
            
            # [3] 뉴스 리스트 (기존 기능 유지)
            st.markdown(f"""
    <div style="margin-top: 10px; margin-bottom:15px;">
        <h3 style="margin:0; color:#333; font-size:22px; font-weight:700; line-height:1.4;">
            {stock['name']} 관련 최신 뉴스 Top 5
        </h3>
    </div>""", unsafe_allow_html=True)
            
            rss_news = get_real_news_rss(stock['name'])
            tags = ["분석", "시장", "전망", "전략", "수급"]
            
            for i in range(5):
                if rss_news and i < len(rss_news):
                    n = rss_news[i]
                    tag = tags[i]
                    st.markdown(f"""
                        <a href="{n['link']}" target="_blank" style="text-decoration:none; color:inherit;">
                            <div style="padding:15px; border:1px solid #eee; border-radius:10px; margin-bottom:10px; box-shadow:0 2px 5px rgba(0,0,0,0.03); transition: transform 0.2s;">
                                <div style="display:flex; justify-content:space-between;">
                                    <div><span style="color:#6e8efb; font-weight:bold;">TOP {i+1}</span> | {tag} <span style="background:{n['bg']}; color:{n['color']}; padding:2px 5px; border-radius:4px; font-size:11px;">{n['sent_label']}</span></div>
                                    <small style="color:#888;">{n['date']}</small>
                                </div>
                                <div style="margin-top:5px; font-weight:600; font-size:15px;">{n['title']}</div>
                            </div>
                        </a>
                    """, unsafe_allow_html=True)
                else:
                    if i == 0: 
                        st.warning("⚠️ 현재 표시할 최신 뉴스가 없습니다.")
                        st.markdown(f"[👉 구글 뉴스 검색 바로가기](https://www.google.com/search?q={stock['name']}&tbm=nws)")
                        break

        # --- [Tab 1: 핵심 정보 (공시 문서 링크 전용)] ---
        with tab1:
            # 0. 기업 기본 프로필
            if profile:
                st.markdown(f"**🏢 {stock['name']}** | {profile.get('finnhubIndustry','-')} | {profile.get('currency','USD')}")
            
            st.write("---")

            # 1. 문서 선택 버튼 그리드
            if 'core_topic' not in st.session_state or st.session_state.core_topic == "financial":
                st.session_state.core_topic = "S-1"

            r1_c1, r1_c2, r1_c3 = st.columns(3)
            r2_c1, r2_c2 = st.columns(2)

            if r1_c1.button("S-1 (최초신고서)", use_container_width=True): st.session_state.core_topic = "S-1"
            if r1_c2.button("S-1/A (수정신고)", use_container_width=True): st.session_state.core_topic = "S-1/A"
            if r1_c3.button("F-1 (해외기업)", use_container_width=True): st.session_state.core_topic = "F-1"
            
            if r2_c1.button("FWP (IR/로드쇼)", use_container_width=True): st.session_state.core_topic = "FWP"
            if r2_c2.button("424B4 (최종확정)", use_container_width=True): st.session_state.core_topic = "424B4"

            # 2. 콘텐츠 설정
            topic = st.session_state.core_topic
            
            def_meta = {
                "S-1": {"t": "증권신고서 (S-1)", "d": "상장을 위해 최초로 제출하는 서류입니다. 사업 모델과 리스크가 상세히 적혀있습니다.", "is_doc": True},
                "S-1/A": {"t": "정정신고서 (S-1/A)", "d": "공모가 밴드와 발행 주식 수가 확정되는 수정 문서입니다.", "is_doc": True},
                "FWP": {"t": "투자설명회 (FWP)", "d": "기관 투자자 대상 로드쇼(Roadshow)에서 사용된 PPT 자료입니다.", "is_doc": True},
                "424B4": {"t": "최종설명서 (Prospectus)", "d": "공모가가 확정된 후 발행되는 최종 문서로, 조달 자금 규모를 확정합니다.", "is_doc": True},
                "F-1": {"t": "해외기업 신고서 (F-1)", "d": "미국 외 기업이 상장할 때 S-1 대신 제출하는 서류입니다.", "is_doc": True},
            }
            
            if topic not in def_meta: topic = "S-1"
            curr_meta = def_meta[topic]

            # --- UI 렌더링 ---
            
            # (1) 문서 정의 설명 (파란 박스)
            st.info(f"💡 **{curr_meta['t']}란?**\n\n{curr_meta['d']}")

            # (2) 하단: 원문 링크 버튼
            import urllib.parse
            import re

            cik = profile.get('cik', '') if profile else ''
            raw_name = stock['name']
            
            # 이름 정제 로직
            clean_name = re.sub(r'[,.]', '', raw_name)
            clean_name = re.sub(r'\s+(Inc|Corp|Ltd|PLC|LLC|Co|SA|NV)\b.*$', '', clean_name, flags=re.IGNORECASE).strip()
            if len(clean_name) < 2: clean_name = raw_name

            # URL 생성
            if cik:
                enc_topic = urllib.parse.quote(topic)
                sec_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={enc_topic}&owner=include&count=40"
            else:
                query = f'"{clean_name}" {topic}'
                enc_query = urllib.parse.quote(query)
                sec_url = f"https://www.sec.gov/edgar/search/#/q={enc_query}&dateRange=all"

            # [수정] 버튼 텍스트를 심플하게 'SEC 원문공시'로 통일
            btn_text = "🏛️ SEC 원문공시 ↗"

            st.markdown(f"""
                <a href="{sec_url}" target="_blank" style="text-decoration:none;">
                    <button style='width:100%; padding:15px; background:white; border:1px solid #004e92; color:#004e92; border-radius:10px; font-weight:bold; cursor:pointer; transition:0.3s; box-shadow: 0 2px 5px rgba(0,0,0,0.05);'>
                        {btn_text}
                    </button>
                </a>
            """, unsafe_allow_html=True)

        # --- Tab 2: AI 가치 평가 (누락된 상세 로직 및 디자인 복구) ---
        with tab2:
            # 가상 점수 계산 로직
            growth_rate = 0.45  # (실제로는 fin_data 등에서 가져와야 함)
            profit_margin = -0.1
            
            growth_score = min(100, int(growth_rate * 150 + 20))
            profit_score = max(10, min(100, int((profit_margin + 0.3) * 200)))
            interest_score = 85 + (len(stock['symbol']) % 15)
            total_score = (growth_score * 0.4) + (profit_score * 0.3) + (interest_score * 0.3)
            
            # 적정가 계산
            fair_low = off_val * (1 + (total_score - 50) / 200) if off_val > 0 else 20.0
            fair_high = fair_low * 1.25
            undervalued_pct = ((fair_low - off_val) / off_val) * 100 if off_val > 0 else 0

            # 1. 방법론 카드 (누락되었던 부분 복구)
            st.markdown("##### 가치 평가 방법론 상세 (Academic Methodology)")
            p_cols = st.columns(3)
            methodologies = [
                {"title": "Relative Valuation", "author": "Kim & Ritter (1999)", "desc": "동종 업계 유사 기업의 P/S, P/E 배수를 적용합니다.", "link": "https://scholar.google.com/scholar?q=Kim+Ritter+1999+Valuing+IPO"},
                {"title": "Fair Value Model", "author": "Purnanandam (2004)", "desc": "공모가와 내재 가치의 괴리율을 측정합니다.", "link": "https://scholar.google.com/scholar?q=Purnanandam+2004+Are+IPOs+Priced+Right"},
                {"title": "Margin of Safety", "author": "Loughran & Ritter", "desc": "장기 수익성을 예측하여 안전 마진을 계산합니다.", "link": "https://scholar.google.com/scholar?q=Loughran+Ritter+IPO+Long-run+Performance"}
            ]

            for i, m in enumerate(methodologies):
                with p_cols[i]:
                    st.markdown(f"""
                        <div style='border-top: 4px solid #6e8efb; background-color: #f8f9fa; padding: 15px; border-radius: 10px; height: 180px; display: flex; flex-direction: column; justify-content: space-between;'>
                            <div>
                                <p style='font-size: 11px; font-weight: bold; color: #6e8efb; margin-bottom: 2px;'>{m['title']}</p>
                                <p style='font-size: 13px; font-weight: 600; color: #333;'>{m['author']}</p>
                                <p style='font-size: 12px; color: #555; line-height: 1.4;'>{m['desc']}</p>
                            </div>
                            <a href='{m['link']}' target='_blank' style='text-decoration: none;'>
                                <button style='width: 100%; background-color: #ffffff; border: 1px solid #6e8efb; color: #6e8efb; border-radius: 5px; font-size: 11px; cursor: pointer; padding: 5px 0;'>논문 보기 ↗</button>
                            </a>
                        </div>
                    """, unsafe_allow_html=True)

            st.write("<br>", unsafe_allow_html=True)
            
            # 2. 종합 점수 및 적정가 (복구)
            st.markdown(f"#### AI 가치 분석 및 적정가 리포트")
            col_metrics = st.columns(3)
            col_metrics[0].metric("성장성 점수 (G)", f"{growth_score}점"); col_metrics[0].progress(growth_score/100)
            col_metrics[1].metric("수익성 점수 (P)", f"{profit_score}점"); col_metrics[1].progress(profit_score/100)
            col_metrics[2].metric("시장 관심도 (I)", f"{interest_score}점"); col_metrics[2].progress(interest_score/100)

            st.write("---")
            res_col1, res_col2 = st.columns([1.5, 1])
            with res_col1:
                st.markdown(f"""
                    <div style='background-color: #ffffff; padding: 25px; border-radius: 15px; border: 1px solid #eef2ff; box-shadow: 0 4px 12px rgba(0,0,0,0.05);'>
                        <p style='color: #666; font-size: 14px; margin-bottom: 5px;'>AI 추정 적정 가치 범위 (Fair Value)</p>
                        <h2 style='color: #6e8efb; margin-bottom: 10px;'>${fair_low:.2f} — ${fair_high:.2f}</h2>
                        <p style='color: {"#28a745" if undervalued_pct > 0 else "#dc3545"}; font-weight: bold; font-size: 16px;'>
                            현재 공모가 대비 약 {abs(undervalued_pct):.1f}% {"저평가" if undervalued_pct > 0 else "고평가"} 상태
                        </p>
                    </div>
                """, unsafe_allow_html=True)
            with res_col2:
                st.markdown(f"**🤖 {stock['symbol']} 종합 매력도**")
                st.title(f"{total_score:.1f} / 100")
                status = "매우 높음" if total_score > 75 else ("보통" if total_score > 50 else "주의")
                st.info(f"종합 투자 매력도는 **'{status}'** 단계입니다.")

            with st.expander("🔬 AI 알고리즘 산출 수식 보기"):
                st.latex(r"Score_{total} = (G \times 0.4) + (P \times 0.3) + (I \times 0.3)")

        # --- Tab 3: 최종 투자 결정 ---
        with tab3:
            import uuid  # 고유 ID 생성을 위해 필요 (상단 import에 추가해도 됨)

            # [설정] 관리자 휴대폰 번호 (여기에 본인 번호를 입력하세요)
            ADMIN_PHONE = "010-0000-0000" 
            
            sid = stock['symbol']
            
            # 세션 데이터 초기화
            if sid not in st.session_state.vote_data: st.session_state.vote_data[sid] = {'u': 10, 'f': 3}
            if sid not in st.session_state.comment_data: st.session_state.comment_data[sid] = []
            if 'user_votes' not in st.session_state: st.session_state.user_votes = {}
            
            # 현재 접속자 정보 가져오기 (없으면 'guest')
            current_user = st.session_state.get('user_phone', 'guest')
            is_admin = (current_user == ADMIN_PHONE)

            # --- 1. 투표 기능 (기존 유지) ---
            st.markdown("### 🗳️ 투자 매력도 투표")
            if st.session_state.auth_status == 'user':
                if sid not in st.session_state.user_votes:
                    v1, v2 = st.columns(2)
                    if v1.button("🦄 Unicorn (상승 예측)", use_container_width=True, key=f"vu_{sid}"): 
                        st.session_state.vote_data[sid]['u'] += 1
                        st.session_state.user_votes[sid] = 'u'
                        st.rerun()
                    if v2.button("💸 Fallen Angel (하락 예측)", use_container_width=True, key=f"vf_{sid}"): 
                        st.session_state.vote_data[sid]['f'] += 1
                        st.session_state.user_votes[sid] = 'f'
                        st.rerun()
                else:
                    my_vote = "유니콘" if st.session_state.user_votes[sid] == 'u' else "폴른엔젤"
                    st.success(f"✅ 이미 '{my_vote}'에 투표하셨습니다.")
            else:
                st.warning("🔒 투표는 회원만 참여 가능합니다.")

            # 결과 바 표시
            uv, fv = st.session_state.vote_data[sid]['u'], st.session_state.vote_data[sid]['f']
            total_votes = uv + fv
            if total_votes > 0:
                ratio = uv / total_votes
                st.progress(ratio)
                st.caption(f"유니콘 {int(ratio*100)}% vs 폴른엔젤 {100-int(ratio*100)}% ({total_votes}명 참여)")
            
            st.write("---")

            # --- 2. 커뮤니티 의견 (베스트 댓글순 정렬 + 좋아요/싫어요) ---
            st.markdown("### 💬 주주 토론방")
            
            # (A) 댓글 입력창 (기존과 동일, 데이터 구조만 변경)
            if st.session_state.auth_status == 'user':
                with st.form(key=f"comment_form_{sid}", clear_on_submit=True):
                    user_input = st.text_area("의견 남기기", placeholder="건전한 투자 문화를 위해 매너를 지켜주세요.", height=80)
                    
                    # 버튼 크기 맞춤 (3:1 비율)
                    btn_c1, btn_c2 = st.columns([3, 1])
                    with btn_c2:
                        submit_btn = st.form_submit_button("등록하기", use_container_width=True, type="primary")
                    
                    if submit_btn and user_input:
                        now_time = datetime.now().strftime("%m.%d %H:%M")
                        new_comment = {
                            "id": str(uuid.uuid4()),    
                            "t": user_input,            
                            "d": now_time,              
                            "u": "익명의 유니콘",        
                            "uid": current_user,
                            # [추가] 좋아요/싫어요 누른 사람들의 ID를 저장할 리스트
                            "likes": [],
                            "dislikes": []
                        }
                        st.session_state.comment_data[sid].insert(0, new_comment)
                        st.toast("의견이 등록되었습니다!", icon="✅")
                        st.rerun()
            else:
                st.info("🔒 로그인 후 토론에 참여할 수 있습니다.")

            # (B) 댓글 리스트 출력 (베스트순 정렬 + 투표 기능 + 우측 정렬)
            comments = st.session_state.comment_data.get(sid, [])
            
            if comments:
                # [핵심] 기존 댓글에 'likes' 키가 없으면 에러가 나므로 방어 코드 추가 (마이그레이션)
                for c in comments:
                    if 'likes' not in c: c['likes'] = []
                    if 'dislikes' not in c: c['dislikes'] = []

                # [핵심] 좋아요(likes) 개수가 많은 순서대로 정렬 (내림차순)
                comments.sort(key=lambda x: len(x['likes']), reverse=True)

                st.markdown(f"<div style='margin-bottom:10px; color:#666; font-size:14px;'>총 <b>{len(comments)}</b>개의 의견 (인기순)</div>", unsafe_allow_html=True)
                
                delete_target_id = None # 삭제할 댓글 임시 저장

                for c in comments:
                    # 좋아요/싫어요 수 계산
                    n_likes = len(c['likes'])
                    n_dislikes = len(c['dislikes'])
                    
                    # 카드 UI
                    st.markdown(f"""
                    <div style='background-color: #f8f9fa; padding: 15px; border-radius: 15px; margin-bottom: 5px; border: 1px solid #eee;'>
                        <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:5px;'>
                            <div style='font-weight:bold; font-size:14px; color:#444;'>👤 {c.get('u', '익명')}</div>
                            <div style='font-size:12px; color:#999;'>{c['d']}</div>
                        </div>
                        <div style='font-size:15px; color:#333; line-height:1.5; white-space: pre-wrap; margin-bottom:5px;'>{c['t']}</div>
                    </div>
                    """, unsafe_allow_html=True)

                    # [기능] 좋아요/싫어요/삭제 버튼 액션 바 (우측 정렬 수정됨)
                    # 5.5(빈공간) : 1.5(좋아요) : 1.5(싫어요) : 1.5(삭제) 비율로 나눔
                    col_spacer, col_like, col_dislike, col_del = st.columns([5.5, 1.5, 1.5, 1.5])
                    
                    # 1. 좋아요 버튼
                    is_liked = current_user in c['likes']
                    like_icon = "👍" if is_liked else "👍"
                    
                    with col_like:
                        if st.button(f"{like_icon} {n_likes}", key=f"like_{c['id']}", use_container_width=True):
                            if st.session_state.auth_status == 'user':
                                if current_user in c['likes']:
                                    c['likes'].remove(current_user) # 이미 눌렀으면 취소
                                else:
                                    c['likes'].append(current_user) # 추가
                                    if current_user in c['dislikes']: c['dislikes'].remove(current_user) # 싫어요 눌렀었으면 취소
                                st.rerun()
                            else:
                                st.toast("로그인이 필요합니다.", icon="🔒")

                    # 2. 싫어요 버튼
                    is_disliked = current_user in c['dislikes']
                    dislike_icon = "👎" if is_disliked else "👎"
                    
                    with col_dislike:
                        if st.button(f"{dislike_icon} {n_dislikes}", key=f"dislike_{c['id']}", use_container_width=True):
                            if st.session_state.auth_status == 'user':
                                if current_user in c['dislikes']:
                                    c['dislikes'].remove(current_user) # 취소
                                else:
                                    c['dislikes'].append(current_user) # 추가
                                    if current_user in c['likes']: c['likes'].remove(current_user) # 좋아요 취소
                                st.rerun()
                            else:
                                st.toast("로그인이 필요합니다.", icon="🔒")

                    # 3. 삭제 버튼 (작성자 or 관리자)
                    comment_author_id = c.get('uid', '')
                    is_author = (current_user == comment_author_id) and (current_user != 'guest')
                    
                    with col_del:
                        if is_author or is_admin:
                            if st.button("🗑️ 삭제", key=f"del_{c['id']}", use_container_width=True):
                                delete_target_id = c
                        else:
                            # 버튼 줄을 맞추기 위해 권한이 없어도 빈 공간은 유지
                            st.write("") 
                    
                    st.write("") # 카드 간 간격

                # 삭제 실행
                if delete_target_id:
                    st.session_state.comment_data[sid].remove(delete_target_id)
                    st.toast("댓글이 삭제되었습니다.", icon="🗑️")
                    st.rerun()
                    
            else:
                st.markdown("<div style='text-align:center; padding:30px; color:#999;'>첫 번째 베스트 댓글의 주인공이 되어보세요! 👑</div>", unsafe_allow_html=True)
            
            st.write("---")

           # --- 3. 보관함 버튼 (타임캡슐 예측 기능 추가) ---
            st.markdown("### ⭐ 관심 종목 관리 & 타임캡슐")
            
            # [필수] 예측 데이터 저장을 위한 세션 초기화 (없으면 생성)
            if 'watchlist_predictions' not in st.session_state:
                st.session_state.watchlist_predictions = {}

            col_act1, col_act2 = st.columns([2.5, 1.5])
            
            # (1) 텍스트/상태 표시 영역
            with col_act1:
                if sid not in st.session_state.watchlist:
                    st.markdown("""
                    <div style='padding-top:5px;'>
                        이 기업의 <b>5년 뒤 미래</b>는 어떨까요?<br>
                        <span style='color:#666; font-size:14px;'>예측을 선택하여 관심종목에 추가하세요!</span>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    # 저장된 예측 값 가져오기
                    my_pred = st.session_state.watchlist_predictions.get(sid, "N/A")
                    
                    if my_pred == "UP":
                        pred_badge = "<span style='background:#e6f4ea; color:#1e8e3e; padding:3px 8px; border-radius:5px; font-weight:bold;'>🚀 5년 뒤 +50% 상승</span>"
                    elif my_pred == "DOWN":
                        pred_badge = "<span style='background:#fce8e6; color:#d93025; padding:3px 8px; border-radius:5px; font-weight:bold;'>📉 5년 뒤 -50% 하락</span>"
                    else:
                        pred_badge = "<span>관심 종목</span>"

                    st.markdown(f"""
                    <div style='padding-top:5px;'>
                        현재 <b>{stock['name']}</b>을(를) 보관 중입니다.<br>
                        나의 예측: {pred_badge}
                    </div>
                    """, unsafe_allow_html=True)

            # (2) 버튼 액션 영역
            with col_act2:
                if sid not in st.session_state.watchlist:
                    # 아직 안 담은 경우 -> 예측 버튼 2개 노출
                    c_up, c_down = st.columns(2)
                    with c_up:
                        if st.button("📈 UP", help="5년 뒤 50% 이상 상승", use_container_width=True):
                            st.session_state.watchlist.append(sid)
                            st.session_state.watchlist_predictions[sid] = "UP"
                            st.balloons()
                            st.toast(f"'{stock['name']}' 상승 예측으로 저장 완료!", icon="🚀")
                            st.rerun()
                    with c_down:
                        if st.button("📉 DOWN", help="5년 뒤 50% 이상 하락", use_container_width=True):
                            st.session_state.watchlist.append(sid)
                            st.session_state.watchlist_predictions[sid] = "DOWN"
                            st.toast(f"'{stock['name']}' 하락 예측으로 저장 완료!", icon="📉")
                            st.rerun()
                else:
                    # 이미 담은 경우 -> 해제 버튼
                    if st.button("🗑️ 보관 해제", use_container_width=True): 
                        st.session_state.watchlist.remove(sid)
                        # 예측 데이터도 같이 삭제할지, 남겨둘지 선택 (여기선 깔끔하게 삭제)
                        if sid in st.session_state.watchlist_predictions:
                            del st.session_state.watchlist_predictions[sid]
                        st.toast("관심 목록에서 삭제되었습니다.", icon="🗑️")
                        st.rerun()





































































































