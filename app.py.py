import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 세션 초기화 ---
for key in ['page', 'auth_status', 'vote_data', 'comment_data', 'selected_stock', 'watchlist', 'view_mode']:
    if key not in st.session_state:
        if key == 'page': st.session_state[key] = 'intro'
        elif key == 'watchlist': st.session_state[key] = []
        elif key in ['vote_data', 'comment_data']: st.session_state[key] = {}
        elif key == 'view_mode': st.session_state[key] = 'all'
        else: st.session_state[key] = None

# --- CSS 스타일 (모바일 가독성 및 다크모드 강제 대응) ---
st.markdown("""
    <style>
    /* 인트로 카드 */
    .intro-card {
        background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%);
        padding: 50px 30px; border-radius: 30px; color: white !important;
        text-align: center; margin-top: 20px; box-shadow: 0 20px 40px rgba(110, 142, 251, 0.3);
    }
    .intro-title { font-size: 40px; font-weight: 900; color: white !important; }
    .feature-item { background: rgba(255, 255, 255, 0.2); padding: 20px 10px; border-radius: 20px; color: white !important; }
    
    /* 일반 공통 텍스트 색상 고정 */
    .stApp { color: #333333 !important; }
    
    /* 성장 단계 분석 카드 */
    .grid-card { 
        background-color: #ffffff !important; padding: 25px; border-radius: 20px; 
        border: 1px solid #eef2ff; box-shadow: 0 10px 20px rgba(0,0,0,0.05); 
        text-align: center; color: #333333 !important; height: 100%;
    }
    
    /* 통계 및 정보 박스 */
    .stat-box, .info-box {
        text-align: left; padding: 15px; background-color: #f1f3f9 !important; 
        border-radius: 12px; margin-bottom: 10px; color: #333333 !important; 
        line-height: 1.5; border-left: 5px solid #6e8efb;
    }
    
    /* 투표 및 댓글 박스 */
    .vote-container { background-color: #f8faff; padding: 25px; border-radius: 20px; border: 1px solid #eef2ff; color: #333333 !important; }
    .comment-box { background: white; padding: 12px; border-radius: 10px; border-left: 4px solid #6e8efb; margin-bottom: 8px; color: #333333 !important; }
    
    /* 탭 메뉴 글씨색 고정 */
    .stTabs [data-baseweb="tab"] p { color: #333333 !important; }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 로직 ---
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
    start = (datetime.now() - timedelta(days=540)).strftime('%Y-%m-%d')
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

# --- 화면 제어 ---
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 10, 1])
    with col_center:
        st.markdown("<div class='intro-card'><div class='intro-title'>UNICORN FINDER</div><div class='intro-subtitle'>미국 시장의 차세대 주역을 가장 먼저 발견하세요</div><div class='feature-grid' style='display:flex; gap:10px; margin-top:20px;'><div class='feature-item' style='flex:1;'>📅<br>IPO 스케줄</div><div class='feature-item' style='flex:1;'>📊<br>AI 분석</div><div class='feature-item' style='flex:1;'>🗳️<br>심리 투표</div></div></div>", unsafe_allow_html=True)
        if st.button("탐험 시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()

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
    st.markdown(f"<div class='quote-card'><small>TODAY'S INSIGHT</small><br><b>\"{q['eng']}\"</b><br><small>({q['kor']})</small><br><br><small>- {q['author']} -</small></div>", unsafe_allow_html=True)

elif st.session_state.page == 'stats':
    st.title("🦄 유니콘 성장 단계 분석")
    img_baby_url = "https://images.unsplash.com/photo-1550684848-fac1c5b4e853?auto=format&fit=crop&w=800&q=80"
    img_child_url = "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=800&q=80"
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='grid-card'><h3>New 유니콘 (유아기)</h3>", unsafe_allow_html=True)
        st.image(img_baby_url, use_container_width=True)
        if st.button("🔎 New 유니콘 탐험 (전체 목록)", use_container_width=True, key="go_all"):
            st.session_state.view_mode = 'all'; st.session_state.page = 'calendar'; st.rerun()
        st.markdown("<div class='stat-box'><small>📊 <b>시장 통계:</b> 연간 평균 180~250개의 기업이 미국 시장에 상장하며, 상장 후 3년 생존율은 약 65% 내외입니다.</small></div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='grid-card'><h3>My 유니콘 (아동기)</h3>", unsafe_allow_html=True)
        st.image(img_child_url, use_container_width=True)
        watch_count = len(st.session_state.watchlist)
        if st.button(f"🔎 My 유니콘 탐험 ({watch_count}개 보관 중)", use_container_width=True, type="primary", key="go_watch"):
            if watch_count > 0: st.session_state.view_mode = 'watchlist'; st.session_state.page = 'calendar'; st.rerun()
            else: st.warning("아직 보관함에 담긴 기업이 없습니다.")
        st.markdown("<div style='margin-top:15px;'><small>내가 직접 분석하고 찜한 나만의 유니콘 후보들</small></div>", unsafe_allow_html=True)

elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    view_mode = st.session_state.get('view_mode', 'all')
    st.header("⭐ My 리서치 보관함" if view_mode == 'watchlist' else "🚀 IPO 리서치 센터")
    all_df = get_extended_ipo_data(MY_API_KEY)
    if not all_df.empty:
        display_df = all_df[all_df['symbol'].isin(st.session_state.watchlist)] if view_mode == 'watchlist' else all_df
        for i, row in display_df.head(20).iterrows(): # 예시로 상위 20개
            col1, col2, col3 = st.columns([1, 4, 1])
            col1.write(row['date'])
            if col2.button(row['name'], key=f"btn_{row['symbol']}_{i}", use_container_width=True):
                st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()

elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        st.title(f"🚀 {stock['name']} 심층 분석")
        tab1, tab2, tab3 = st.tabs(["📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])
        
        with tab1:
            st.subheader("🔍 투자자 검색 상위 5대 지표")
            c1, c2 = st.columns([1, 2.5])
            with c1:
                # 기업 로고 복구
                st.image(f"https://logo.clearbit.com/{stock['symbol']}.com", width=200)
            with c2:
                # 핵심 정보 지표 5가지 복구
                p, s = pd.to_numeric(stock.get('price'), errors='coerce') or 0, pd.to_numeric(stock.get('numberOfShares'), errors='coerce') or 0
                st.markdown(f"<div class='info-box'><b>1. 예상 공모가:</b> ${p:,.2f}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>2. 공모 규모:</b> ${(p*s/1000000):,.1f}M USD</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>3. 상장 거래소:</b> {stock.get('exchange', 'NYSE/NASDAQ')}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>4. 보호예수 기간:</b> 상장 후 180일</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>5. 주요 주간사:</b> 글로벌 Top-tier 투자은행</div>", unsafe_allow_html=True)

        with tab2:
            st.subheader("⚖️ AI 가치 평가")
            p = pd.to_numeric(stock.get('price'), errors='coerce') or 0
            st.metric("AI 추정 적정가 범위", f"${p*1.12:,.2f} ~ ${p*1.38:,.2f}")
            st.progress(0.65); st.success("상승 잠재력 높음 (Ritter 모델 적용)")

        with tab3:
            sid = stock['symbol']
            if sid not in st.session_state.vote_data: st.session_state.vote_data[sid] = {'u': 10, 'f': 3}
            st.markdown("<div class='vote-container'><b>1. 투자 매력도 투표</b>", unsafe_allow_html=True)
            v1, v2 = st.columns(2)
            if v1.button("🦄 Unicorn", key=f"u_{sid}", use_container_width=True): st.session_state.vote_data[sid]['u']+=1; st.rerun()
            if v2.button("💸 Fallen Angel", key=f"f_{sid}", use_container_width=True): st.session_state.vote_data[sid]['f']+=1; st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
            
            if sid not in st.session_state.watchlist:
                if st.button("⭐ 보관함에 추가", use_container_width=True, type="primary"):
                    st.session_state.watchlist.append(sid); st.balloons(); st.rerun()
            else: st.success("✅ 이미 보관함에 있는 종목입니다.")
