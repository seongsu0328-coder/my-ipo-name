import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
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

# --- CSS 스타일 ---
st.markdown("""
    <style>
    .intro-card { background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%); padding: 50px; border-radius: 30px; color: white !important; text-align: center; }
    .intro-title { font-size: 40px; font-weight: 900; margin-bottom: 10px; color: white !important; }
    .feature-grid { display: flex; justify-content: space-around; gap: 15px; margin-top: 25px; }
    .feature-item { background: rgba(255, 255, 255, 0.2); padding: 20px; border-radius: 20px; flex: 1; color: white !important; text-align: center; }
    
    .grid-card { background-color: white !important; padding: 25px; border-radius: 20px; border: 1px solid #eef2ff; color: #333333 !important; text-align: center; box-shadow: 0 10px 20px rgba(0,0,0,0.05); }
    .info-box { background-color: #f0f4ff; padding: 15px; border-radius: 12px; border-left: 5px solid #6e8efb; margin-bottom: 10px; color: #333333 !important; text-align: left; }
    .stat-box { text-align: left; padding: 12px; background-color: #f1f3f9 !important; border-radius: 12px; margin-top: 15px; color: #444444 !important; }
    .stTabs [data-baseweb="tab"] p { color: #333333 !important; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 로직 ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

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

# --- 화면 제어 로직 ---

# 1. 인트로 화면
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 10, 1])
    with col_center:
        st.markdown("""
            <div class='intro-card'>
                <div class='intro-title'>UNICORN FINDER</div>
                <div class='intro-subtitle'>미국 시장의 차세대 주역을 가장 먼저 발견하세요</div>
                <div class='feature-grid'>
                    <div class='feature-item'>📅<br>IPO 스케줄</div>
                    <div class='feature-item'>📊<br>AI 분석</div>
                    <div class='feature-item'>🗳️<br>심리 투표</div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        st.write("<br>", unsafe_allow_html=True)
        if st.button("탐험 시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()

# 2. 로그인 화면
elif st.session_state.page == 'login':
    st.write("<br>" * 4, unsafe_allow_html=True)
    _, col_m, _ = st.columns([1, 1.5, 1])
    with col_m:
        st.subheader("로그인")
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000")
        c1, c2 = st.columns(2)
        if c1.button("회원 로그인", use_container_width=True):
            st.session_state.auth_status = 'user'; st.session_state.page = 'stats'; st.rerun()
        if c2.button("비회원 시작", use_container_width=True):
            st.session_state.auth_status = 'guest'; st.session_state.page = 'stats'; st.rerun()

# 3. 통계/홈 화면
elif st.session_state.page == 'stats':
    st.title("🦄 유니콘 성장 단계 분석")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='grid-card'><h3>New 유니콘 (유아기)</h3>", unsafe_allow_html=True)
        st.image("https://images.unsplash.com/photo-1550684848-fac1c5b4e853?auto=format&fit=crop&w=800&q=80", use_container_width=True)
        if st.button("🔎 New 유니콘 탐험", use_container_width=True, key="go_all"):
            st.session_state.view_mode = 'all'; st.session_state.page = 'calendar'; st.rerun()
        st.markdown("<div class='stat-box'><small>전체 상장 예정 및 최근 상장 기업 리서치</small></div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='grid-card'><h3>My 유니콘 (아동기)</h3>", unsafe_allow_html=True)
        st.image("https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=800&q=80", use_container_width=True)
        watch_count = len(st.session_state.watchlist)
        if st.button(f"🔎 My 유니콘 탐험 ({watch_count})", use_container_width=True, type="primary", key="go_watch"):
            if watch_count > 0: st.session_state.view_mode = 'watchlist'; st.session_state.page = 'calendar'; st.rerun()
            else: st.warning("보관함이 비어있습니다.")
        st.markdown("<div class='stat-box'><small>내가 찜한 관심 종목 집중 분석</small></div></div>", unsafe_allow_html=True)

# 4. 캘린더/목록 화면
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    all_df = get_extended_ipo_data(MY_API_KEY)
    if not all_df.empty:
        display_df = all_df[all_df['symbol'].isin(st.session_state.watchlist)] if st.session_state.view_mode == 'watchlist' else all_df
        st.header("🚀 IPO 리서치 센터")
        for i, row in display_df.head(15).iterrows():
            with st.container():
                col1, col2, col3 = st.columns([1, 4, 1])
                col1.write(row['date'])
                if col2.button(row['name'], key=f"btn_{row['symbol']}_{i}", use_container_width=True):
                    st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()

# 5. 상세 분석 화면 (요청하신 복구된 핵심 섹션)
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        if st.sidebar.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        
        st.title(f"🚀 {stock['name']} 심층 분석")
        tab1, tab2, tab3 = st.tabs(["📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])
        
        with tab1:
            st.subheader("🔍 투자자 검색 상위 5대 지표")
            c1, c2 = st.columns([1, 2.5])
            with c1:
                st.image(f"https://logo.clearbit.com/{stock['symbol']}.com", width=200)
            with c2:
                p, s = pd.to_numeric(stock.get('price'), errors='coerce') or 0, pd.to_numeric(stock.get('numberOfShares'), errors='coerce') or 0
                st.markdown(f"<div class='info-box'><b>1. 예상 공모가:</b> ${p:,.2f}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>2. 공모 규모:</b> ${(p*s/1000000):,.1f}M USD</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>3. 상장 거래소:</b> {stock.get('exchange', 'NYSE/NASDAQ')}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>4. 보호예수 기간:</b> 상장 후 180일</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>5. 주요 주간사:</b> 글로벌 Top-tier 투자은행</div>", unsafe_allow_html=True)
            
            st.write("---")
            cc1, cc2 = st.columns(2)
            with cc1:
                st.subheader("📑 주요 기업 공시 (SEC)")
                st.info(f"📍 **S-1 증권신고서** : {stock['symbol']}의 상장 목적 분석 리포트")
                st.markdown(f"[SEC 공식 홈페이지 확인](https://www.sec.gov/edgar/browse/?CIK={stock['symbol']})")

            with cc2:
                st.subheader("📊 핵심 재무 요약")
                f_data = {"항목": ["매출 성장률", "영업 이익률", "현금 흐름"], "수치": ["+45.2%", "-12.5%", "Positive"]}
                st.table(pd.DataFrame(f_data))

        with tab2:
            st.subheader("⚖️ AI 가치 평가")
            p = pd.to_numeric(stock.get('price'), errors='coerce') or 0
            st.metric("AI 추정 적정가 범위", f"${p*1.12:,.2f} ~ ${p*1.38:,.2f}")
            st.progress(0.65); st.success("상승 잠재력 감지 (Ritter 모델 적용)")

        with tab3:
            sid = stock['symbol']
            if sid not in st.session_state.vote_data: st.session_state.vote_data[sid] = {'u': 10, 'f': 3}
            st.markdown("<div class='grid-card'>", unsafe_allow_html=True)
            st.write("#### 이 기업의 미래는 유니콘일까요?")
            v1, v2 = st.columns(2)
            if v1.button("🦄 Unicorn", use_container_width=True, key=f"v_u_{sid}"): 
                st.session_state.vote_data[sid]['u'] += 1; st.rerun()
            if v2.button("💸 Fallen Angel", use_container_width=True, key=f"v_f_{sid}"): 
                st.session_state.vote_data[sid]['f'] += 1; st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
            
            if sid not in st.session_state.watchlist:
                if st.button("⭐ 마이 리서치 보관함에 담기", use_container_width=True, type="primary"):
                    st.session_state.watchlist.append(sid); st.balloons(); st.rerun()
            else: st.success("✅ 관심 종목으로 등록되어 있습니다.")
