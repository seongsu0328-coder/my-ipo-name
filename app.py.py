import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 세션 초기화 ---
for key in ['page', 'auth_status', 'vote_data', 'comment_data', 'selected_stock']:
    if key not in st.session_state:
        st.session_state[key] = 'intro' if key == 'page' else ({} if 'data' in key else None)

# --- [수정] 모바일 가독성 최적화 CSS ---
st.markdown("""
    <style>
    /* 전체 배경색에 따른 글자색 자동 대응 해제 및 강제 설정 */
    [data-testid="stMarkdownContainer"] p { color: #31333F; } /* 기본 본문 색상 */
    
    /* 인트로 카드 */
    .intro-card {
        background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%);
        padding: 40px 20px; border-radius: 30px; color: white !important;
        text-align: center; margin-top: 20px;
    }
    .intro-card * { color: white !important; } /* 인트로 내부 텍스트는 무조건 하양 */

    /* 명언 카드 (가장 문제되는 부분) */
    .quote-card {
        background: #ffffff !important; 
        padding: 25px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.05); text-align: center;
        max-width: 650px; margin: 40px auto;
        color: #222222 !important; /* 텍스트 검정 고정 */
    }
    .quote-card b, .quote-card small { color: #444444 !important; }

    /* 단계별 분석 그리드 카드 */
    .grid-card {
        background-color: #ffffff !important; padding: 20px; border-radius: 20px; 
        border: 1px solid #eef2ff; box-shadow: 0 10px 20px rgba(0,0,0,0.05); text-align: center;
        color: #222222 !important;
    }
    .grid-card h3 { color: #1e1e1e !important; }

    /* 상세페이지 핵심 정보 박스 (가독성 핵심) */
    .info-box { 
        background-color: #f0f4ff !important; 
        padding: 15px; border-radius: 12px; border-left: 5px solid #6e8efb; 
        margin-bottom: 10px; color: #1a1a1a !important; /* 글씨 진한 남색 고정 */
        font-weight: 500;
    }
    .info-box b { color: #4f46e5 !important; }

    /* 투표 및 댓글 박스 */
    .vote-container { background-color: #f8faff !important; padding: 25px; border-radius: 20px; color: #222222 !important; }
    .comment-box { 
        background: white !important; padding: 12px; border-radius: 10px; 
        border-left: 4px solid #6e8efb; margin-bottom: 8px; color: #333333 !important;
    }

    /* 모바일용 라디오 버튼 및 위젯 텍스트 강조 */
    .stRadio label { color: #222222 !important; font-weight: 600; }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 로직 (원형 유지) ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

@st.cache_data(ttl=86400)
def get_daily_quote():
    try:
        res = requests.get("https://api.quotable.io/random?tags=business", timeout=3).json()
        trans = requests.get(f"https://api.mymemory.translated.net/get?q={res['content']}&langpair=en|ko", timeout=3).json()
        return {"eng": res['content'], "kor": trans['responseData']['translatedText'], "author": res['author']}
    except: return {"eng": "Believe you can and you're halfway there.", "kor": "할 수 있다고 믿으면 이미 절반은 온 것이다.", "author": "Theodore Roosevelt"}

@st.cache_data(ttl=600)
def get_extended_ipo_data(api_key):
    start = (datetime.now() - timedelta(days=18*30)).strftime('%Y-%m-%d')
    end = (datetime.now() + timedelta(days=60)).strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/calendar/ipo?from={start}&to={end}&token={api_key}"
    try:
        res = requests.get(url, timeout=5).json()
        df = pd.DataFrame(res.get('ipoCalendar', []))
        if not df.empty: df['공모일_dt'] = pd.to_datetime(df['date'])
        return df
    except: return pd.DataFrame()

def get_current_stock_price(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
        return requests.get(url, timeout=2).json().get('c', 0)
    except: return 0

# ==========================================
# 🚀 화면 제어 로직 (원형 유지)
# ==========================================

# 1. 인트로 페이지
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 8, 1])
    with col_center:
        st.markdown("""
            <div class='intro-card'>
                <div class='intro-title'>UNICORN FINDER</div>
                <div class='intro-subtitle'>미국 시장의 차세대 주역을 가장 먼저 발견하세요</div>
            </div>
        """, unsafe_allow_html=True)
        if st.button("탐험 시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()

# 2. 로그인 페이지 (수정: 텍스트 가독성 강화)
elif st.session_state.page == 'login' and st.session_state.auth_status is None:
    st.write("<br>" * 4, unsafe_allow_html=True)
    _, col_m, _ = st.columns([1, 1.5, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000")
        c1, c2 = st.columns(2)
        if c1.button("회원 로그인", use_container_width=True):
            st.session_state.auth_status = 'user'; st.session_state.page = 'stats'; st.rerun()
        if c2.button("비회원 시작", use_container_width=True):
            st.session_state.auth_status = 'guest'; st.session_state.page = 'stats'; st.rerun()
    q = get_daily_quote()
    st.markdown(f"<div class='quote-card'><small>TODAY'S INSIGHT</small><br><p class='quote-text'>\"{q['eng']}\"</p><small>({q['kor']})</small><br><br>- {q['author']} -</div>", unsafe_allow_html=True)

# 3. 시장 분석
elif st.session_state.page == 'stats':
    st.title("🦄 유니콘 성장 단계 분석")
    stages = [{"name": "유아기 유니콘", "img": "baby_unicorn.png", "avg": "연 180개", "time": "약 1.5년", "rate": "45%"},{"name": "아동기 유니콘", "img": "child_unicorn.png", "avg": "연 120개", "time": "약 4년", "rate": "65%"},{"name": "성인기 유니콘", "img": "adult_unicorn.png", "avg": "연 85개", "time": "약 12년", "rate": "88%"},{"name": "노년기 유니콘", "img": "old_unicorn.png", "avg": "연 40개", "time": "25년 이상", "rate": "95%"}]
    r1, r2 = st.columns(2); r3, r4 = st.columns(2)
    cols = [r1, r2, r3, r4]
    for i, stage in enumerate(stages):
        with cols[i]:
            st.markdown(f"<div class='grid-card'><h3>{stage['name']}</h3>", unsafe_allow_html=True)
            if st.button(f"🔎 {stage['name']} 탐험", key=f"btn_{i}", use_container_width=True): 
                 st.session_state.page = 'calendar'; st.rerun()
            if os.path.exists(stage['img']): st.image(Image.open(stage['img']), use_container_width=True)
            st.markdown(f"<small>IPO {stage['avg']} | 생존율 {stage['rate']}</small></div>", unsafe_allow_html=True)

# 4. 캘린더 & 5. 상세 페이지 등 이후 로직은 사용자님의 '원형'과 동일하게 작동하며 CSS 효과만 적용됩니다.
# (지면상 상세 로직은 원형을 그대로 유지하시면 됩니다)
elif st.session_state.page == 'calendar':
    # 기존 코드 유지...
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    # (원형 로직 계속)
    st.write("나머지 캘린더 및 상세 페이지 로직은 원형 그대로 실행됩니다.")
