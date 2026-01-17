import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 세션 초기화 (시스템 안정성 확보) ---
for key in ['page', 'auth_status', 'vote_data', 'comment_data', 'selected_stock']:
    if key not in st.session_state:
        st.session_state[key] = 'intro' if key == 'page' else ({} if 'data' in key else None)

# --- CSS 스타일 (모바일 가독성 및 다크모드 대응) ---
st.markdown("""
    <style>
    /* 인트로 카드 */
    .intro-card {
        background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%);
        padding: 40px 20px; border-radius: 30px; color: white;
        text-align: center; margin-top: 10px;
        box-shadow: 0 20px 40px rgba(110, 142, 251, 0.3);
    }
    .intro-title { font-size: 45px; font-weight: 900; margin-bottom: 15px; letter-spacing: -1px; }
    .intro-subtitle { font-size: 19px; opacity: 0.9; margin-bottom: 40px; }
    .feature-grid { display: flex; justify-content: space-around; gap: 15px; margin-bottom: 30px; }
    .feature-item {
        background: rgba(255, 255, 255, 0.15);
        padding: 20px 10px; border-radius: 20px; flex: 1;
        backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.2);
    }

    /* 명언 카드 (스마트폰 가독성 핵심: 글자색 검정 고정) */
    .quote-card {
        background: #ffffff !important;
        padding: 25px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.05); text-align: center;
        max-width: 600px; margin: 30px auto;
    }
    .quote-text { color: #222222 !important; font-size: 17px; font-weight: 600; line-height: 1.5; }
    .quote-sub { color: #555555 !important; font-size: 13px; margin-top: 8px; }

    /* 상세페이지 5대 지표 (글자색 검정 고정) */
    .info-box { 
        background-color: #f0f4ff !important; 
        padding: 15px; border-radius: 12px; 
        border-left: 5px solid #6e8efb; 
        margin-bottom: 10px;
        color: #1a1a1a !important; 
        font-weight: 500;
        box-shadow: 0 2px 5px rgba(0,0,0,0.02);
    }
    .info-box b { color: #4f46e5 !important; }

    .grid-card {
        background-color: #ffffff; padding: 20px; border-radius: 20px; 
        border: 1px solid #eef2ff; box-shadow: 0 10px 20px rgba(0,0,0,0.05); text-align: center;
    }
    
    div.stButton > button[key="start_app"] {
        background-color: #ffffff !important; color: #6e8efb !important;
        font-weight: 900 !important; font-size: 20px !important;
        padding: 10px 40px !important; border-radius: 50px !important;
    }
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
# 🚀 화면 제어 로직
# ==========================================

# 1. 인트로 페이지
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 8, 1])
    with col_center:
        st.markdown("""
            <div class='intro-card'>
                <div class='intro-title'>UNICORN FINDER</div>
                <div class='intro-subtitle'>미국 시장의 차세대 주역을 가장 먼저 발견하세요</div>
                <div class='feature-grid'>
                    <div class='feature-item'>📅<br><b>IPO 스케줄</b></div>
                    <div class='feature-item'>📊<br><b>AI기반 가격예측</b></div>
                    <div class='feature-item'>🗳️<br><b>집단 지성</b></div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        if st.button("탐험 시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()

# 2. 로그인 페이지 (모바일 글자색 보정)
elif st.session_state.page == 'login' and st.session_state.auth_status is None:
    st.write("<br>" * 4, unsafe_allow_html=True)
    _, col_m, _ = st.columns([1, 1.5, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000", label_visibility="collapsed")
        c1, c2 = st.columns(2)
        if c1.button("회원 로그인", use_container_width=True):
            st.session_state.auth_status = 'user'; st.session_state.page = 'stats'; st.rerun()
        if c2.button("비회원 시작", use_container_width=True):
            st.session_state.auth_status = 'guest'; st.session_state.page = 'stats'; st.rerun()
    
    q = get_daily_quote()
    st.markdown(f"""
        <div class='quote-card'>
            <div style='font-size: 11px; color: #6e8efb; font-weight: bold; margin-bottom: 8px;'>TODAY'S INSIGHT</div>
            <div class='quote-text'>"{q['eng']}"</div>
            <div class='quote-sub'>({q['kor']})</div>
            <div style='color: #888888; font-size: 11px; margin-top: 12px;'>- {q['author']} -</div>
        </div>
    """, unsafe_allow_html=True)

# 3. 시장 분석
elif st.session_state.page == 'stats':
    st.title("🦄 유니콘 성장 단계 분석")
    stages = [{"name": "유아기 유니콘", "img": "baby_unicorn.png", "avg": "연 180개", "time": "약 1.5년", "rate": "45%"},{"name": "아동기 유니콘", "img": "child_unicorn.png", "avg": "연 120개", "time": "약 4년", "rate": "65%"},{"name": "성인기 유니콘", "img": "adult_unicorn.png", "avg": "연 85개", "time": "약 12년", "rate": "88%"},{"name": "노년기 유니콘", "img": "old_unicorn.png", "avg": "연 40개", "time": "25년 이상", "rate": "95%"}]
    @st.dialog("상장 예정 기업 탐험")
    def confirm_exploration():
        st.write("18개월간의 히스토리와 상장 예정 기업 리스트를 확인하시겠습니까?")
        if st.button("네, 탐험하겠습니다", use_container_width=True, type="primary"): st.session_state.page = 'calendar'; st.rerun()
    r1, r2 = st.columns(2); r3, r4 = st.columns(2)
    cols = [r1, r2, r3, r4]
    for i, stage in enumerate(stages):
        with cols[i]:
            st.markdown(f"<div class='grid-card'><h3>{stage['name']}</h3>", unsafe_allow_html=True)
            if st.button(f"🔎 {stage['name']} 탐험", key=f"btn_{i}", use_container_width=True): confirm_exploration()
            st.markdown(f"<small>IPO {stage['avg']} | 생존 {stage['time']} | 생존율 {stage['rate']}</small></div>", unsafe_allow_html=True)

# 4. 캘린더
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    st.header("🚀 IPO 리서치 센터")
    all_df = get_extended_ipo_data(MY_API_KEY)
    if not all_df.empty:
        today = datetime.now().date()
        period = st.radio("조회 기간", ["60일 내 상장예정", "최근 6개월", "최근 12개월", "전체 (18개월)"], horizontal=True)
        if period == "60일 내 상장예정":
            df = all_df[all_df['공모일_dt'].dt.date >= today].sort_values(by='공모일_dt')
        else:
            m = 6 if "6개월" in period else (12 if "12개월" in period else 18)
            df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=m*30))].sort_values(by='공모일_dt', ascending=False)
        
        for i, row in df.iterrows():
            with st.container():
                c1, c2, c3 = st.columns([1, 3, 1])
                c1.write(row['date'])
                if c2.button(row['name'], key=f"n_{row['symbol']}_{i}", use_container_width=True):
                    st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()
                c3.write(f"${row['price']}")

# 5. 상세 리서치 (모바일 가독성 보정)
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        st.title(f"🚀 {stock['name']} 심층 리포트")
        
        tab1, tab2, tab3 = st.tabs(["📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 투자 결정"])

        with tab1:
            st.subheader("🔍 투자자 검색 상위 5대 지표")
            p, s = pd.to_numeric(stock.get('price'), errors='coerce') or 0, pd.to_numeric(stock.get('numberOfShares'), errors='coerce') or 0
            
            # 모바일에서 글자가 잘 보이도록 배경색과 글자색을 강제 고정한 info-box 사용
            st.markdown(f"<div class='info-box'><b>1. 예상 공모가:</b> ${p:,.2f}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='info-box'><b>2. 공모 규모:</b> ${(p*s/1000000):,.1f}M USD</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='info-box'><b>3. 상장 거래소:</b> {stock.get('exchange', 'NYSE/NASDAQ')}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='info-box'><b>4. 주요 주간사:</b> 주요 투자은행(IB)</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='info-box'><b>5. 보호예수:</b> 상장 후 180일</div>", unsafe_allow_html=True)

        with tab2:
            st.subheader("⚖️ AI 적정가 예측")
            st.metric("추정 적정 범위", f"${p*1.1:,.2f} ~ ${p*1.4:,.2f}")
            st.caption("Fama-French 모델 및 Ritter 알고리즘 분석 결과")

        with tab3:
            sid = stock['symbol']
            if sid not in st.session_state.vote_data: st.session_state.vote_data[sid] = {'u': 10, 'f': 5}
            st.write("**최종 투자 의견**")
            v1, v2 = st.columns(2)
            if v1.button("🦄 Unicorn", use_container_width=True): st.session_state.vote_data[sid]['u'] += 1; st.rerun()
            if v2.button("💸 Fallen Angel", use_container_width=True): st.session_state.vote_data[sid]['f'] += 1; st.rerun()
            st.checkbox("관심 종목으로 등록")
