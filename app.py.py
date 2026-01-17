import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os
import random

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 세션 초기화 ---
for key in ['page', 'auth_status', 'vote_data', 'comment_data', 'selected_stock', 'watchlist']:
    if key not in st.session_state:
        if key == 'page': st.session_state[key] = 'intro'
        elif key == 'watchlist': st.session_state[key] = []
        elif key in ['vote_data', 'comment_data']: st.session_state[key] = {}
        else: st.session_state[key] = None

# --- CSS 스타일 ---
st.markdown("""
    <style>
    .intro-card {
        background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%);
        padding: 60px 40px; border-radius: 30px; color: white;
        text-align: center; margin-top: 20px; box-shadow: 0 20px 40px rgba(110, 142, 251, 0.3);
    }
    .intro-title { font-size: 45px; font-weight: 900; margin-bottom: 15px; letter-spacing: -1px; }
    .intro-subtitle { font-size: 19px; opacity: 0.9; margin-bottom: 40px; }
    
    /* 기능 그리드 스타일 복구 */
    .feature-grid { display: flex; justify-content: space-around; gap: 20px; margin-bottom: 30px; }
    .feature-item {
        background: rgba(255, 255, 255, 0.15);
        padding: 25px 15px; border-radius: 20px; flex: 1;
        backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.2);
    }
    .feature-icon { font-size: 30px; margin-bottom: 10px; }
    .feature-text { font-size: 15px; line-height: 1.4; }

    .quote-card {
        background: linear-gradient(145deg, #ffffff, #f9faff);
        padding: 25px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.05); text-align: center;
        max-width: 650px; margin: 40px auto; color: #333333 !important;
    }
    .grid-card {
        background-color: #ffffff; padding: 25px; border-radius: 20px; 
        border: 1px solid #eef2ff; box-shadow: 0 10px 20px rgba(0,0,0,0.05); text-align: center; color: #333;
    }
    .vote-container { background-color: #f8faff; padding: 25px; border-radius: 20px; border: 1px solid #eef2ff; margin-bottom: 20px; color: #333; }
    .comment-box { background: white; padding: 12px; border-radius: 10px; border-left: 4px solid #6e8efb; margin-bottom: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); color: #333; }
    .info-box { background-color: #f0f4ff; padding: 15px; border-radius: 12px; border-left: 5px solid #6e8efb; margin-bottom: 10px; color: #333; }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 로직 (생략 없이 유지) ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

@st.cache_data(ttl=86400)
def get_daily_quote():
    try:
        res = requests.get("https://api.quotable.io/random?tags=business", timeout=3).json()
        trans = requests.get(f"https://api.mymemory.translated.net/get?q={res['content']}&langpair=en|ko", timeout=3).json()
        return {"eng": res['content'], "kor": trans['responseData']['translatedText'], "author": res['author']}
    except:
        return {"eng": "Opportunities don't happen. You create them.", "kor": "기회는 일어나는 것이 아니라 만드는 것이다.", "author": "Chris Grosser"}

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
# 🚀 화면 제어 로직
# ==========================================

# 1. 인트로 페이지 (기업 소개 상세 복구)
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 8, 1])
    with col_center:
        st.markdown("""
            <div class='intro-card'>
                <div class='intro-title'>UNICORN FINDER</div>
                <div class='intro-subtitle'>미국 시장의 차세대 주역을 가장 먼저 발견하세요</div>
                <div class='feature-grid'>
                    <div class='feature-item'>
                        <div class='feature-icon'>📅</div>
                        <div class='feature-text'><b>IPO 스케줄</b><br>실시간 트래킹</div>
                    </div>
                    <div class='feature-item'>
                        <div class='feature-icon'>📊</div>
                        <div class='feature-text'><b>AI기반 분석</b><br>데이터 예측</div>
                    </div>
                    <div class='feature-item'>
                        <div class='feature-icon'>🗳️</div>
                        <div class='feature-text'><b>집단 지성</b><br>글로벌 심리 투표</div>
                    </div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        if st.button("탐험 시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()

# 2. 로그인 페이지 (명언 포함)
elif st.session_state.page == 'login':
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
    st.markdown(f"""
        <div class='quote-card'>
            <small>TODAY'S INSIGHT</small>
            <b>"{q['eng']}"</b>
            <small>({q['kor']})</small><br><br>
            <small>- {q['author']} -</small>
        </div>
    """, unsafe_allow_html=True)

# 3. 시장 분석 (유아기/아동기 2단계 구성)
elif st.session_state.page == 'stats':
    st.title("🦄 유니콘 성장 단계 분석")
    stages = [
        {"name": "유아기 유니콘", "img": "baby_unicorn.png", "icon": "🌱", "avg": "연 180개", "time": "약 1.5년", "rate": "45%"},
        {"name": "아동기 유니콘", "img": "child_unicorn.png", "icon": "🦄", "avg": "연 120개", "time": "약 4년", "rate": "65%"}
    ]
    
    @st.dialog("상장 예정 기업 탐험")
    def confirm_exploration():
        st.write("초기 성장 단계의 상장 예정 기업 리스트를 확인하시겠습니까?")
        if st.button("네, 탐험하겠습니다", use_container_width=True, type="primary"): 
            st.session_state.page = 'calendar'; st.rerun()

    c1, c2 = st.columns(2)
    cols = [c1, c2]
    for i, stage in enumerate(stages):
        with cols[i]:
            st.markdown(f"<div class='grid-card'><h3>{stage['name']}</h3>", unsafe_allow_html=True)
            if os.path.exists(stage['img']): 
                st.image(Image.open(stage['img']), use_container_width=True)
            else: 
                st.markdown(f"<div style='font-size:80px; padding:20px;'>{stage['icon']}</div>", unsafe_allow_html=True)
            
            if st.button(f"🔎 {stage['name']} 탐험", key=f"btn_{i}", use_container_width=True): 
                confirm_exploration()
            st.markdown(f"<small>IPO {stage['avg']} | 생존 {stage['time']} | 생존율 {stage['rate']}</small></div>", unsafe_allow_html=True)

# 4. 캘린더 및 5. 상세 페이지 (이후 로직은 이전과 동일하게 유지...)
# (중략된 부분은 위에서 제공한 SyntaxError 수정본과 동일합니다)
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    st.header("🚀 IPO 리서치 센터")
    all_df = get_extended_ipo_data(MY_API_KEY)
    if not all_df.empty:
        today = datetime.now().date()
        for i, row in all_df.head(15).iterrows():
            if st.button(f"{row['date']} | {row['name']}", key=f"n_{i}", use_container_width=True):
                st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()

elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        st.title(f"🚀 {stock['name']} 심층 분석")
        tab1, tab2, tab3 = st.tabs(["📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])
        with tab1:
            p = pd.to_numeric(stock.get('price'), errors='coerce') or 0
            s = pd.to_numeric(stock.get('numberOfShares'), errors='coerce') or 0
            st.markdown(f"<div class='info-box'><b>1. 예상 공모가:</b> ${p:,.2f}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='info-box'><b>2. 공모 규모:</b> ${(p*s/1000000):,.1f}M USD</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='info-box'><b>3. 상장 거래소:</b> {stock.get('exchange', 'NYSE/NASDAQ')}</div>", unsafe_allow_html=True)
        with tab3:
            sid = stock['symbol']
            is_watched = sid in st.session_state.watchlist
            if not is_watched:
                if st.button("⭐ 관심 종목으로 등록", use_container_width=True, type="primary"):
                    st.session_state.watchlist.append(sid); st.balloons(); st.rerun()
            else:
                st.success("✅ 보관함 저장 완료"); st.button("❌ 해제", on_click=lambda: st.session_state.watchlist.remove(sid))
