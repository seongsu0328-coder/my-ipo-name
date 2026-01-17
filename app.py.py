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
for key in ['page', 'auth_status', 'vote_data', 'comment_data', 'selected_stock']:
    if key not in st.session_state:
        st.session_state[key] = 'intro' if key == 'page' else ({} if 'data' in key else None)

# --- CSS 스타일 ---
st.markdown("""
    <style>
    .intro-card {
        background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%);
        padding: 60px 40px; border-radius: 30px; color: white;
        text-align: center; margin-top: 20px; box-shadow: 0 20px 40px rgba(110, 142, 251, 0.3);
    }
    .intro-title { font-size: 45px; font-weight: 900; margin-bottom: 15px; letter-spacing: -1px; }
    .quote-card {
        background: linear-gradient(145deg, #ffffff, #f9faff);
        padding: 25px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.05); text-align: center;
        max-width: 650px; margin: 40px auto; color: #333333 !important;
    }
    .grid-card {
        background-color: #ffffff; padding: 20px; border-radius: 20px; 
        border: 1px solid #eef2ff; box-shadow: 0 10px 20px rgba(0,0,0,0.05); text-align: center; color: #333;
    }
    .info-box { background-color: #f0f4ff; padding: 15px; border-radius: 12px; border-left: 5px solid #6e8efb; margin-bottom: 10px; color: #333; }
    .vote-container { background-color: #f8faff; padding: 25px; border-radius: 20px; border: 1px solid #eef2ff; margin-bottom: 20px; color: #333; }
    .comment-box { background: white; padding: 12px; border-radius: 10px; border-left: 4px solid #6e8efb; margin-bottom: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); color: #333; }
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
    start = (datetime.now() - timedelta(days=18*30)).strftime('%Y-%m-%d')
    end = (datetime.now() + timedelta(days=60)).strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/calendar/ipo?from={start}&to={end}&token={api_key}"
    try:
        res = requests.get(url, timeout=5).json()
        df = pd.DataFrame(res.get('ipoCalendar', []))
        if not df.empty: df['공모일_dt'] = pd.to_datetime(df['date'])
        return df
    except: return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_stock_financials(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/stock/metric?symbol={symbol}&metric=all&token={api_key}"
        res = requests.get(url, timeout=3).json()
        m = res.get('metric', {})
        if not m: return None
        return {"매출성장률(5y)": f"{m.get('revenueGrowth5Y', 0):.2f}%", "영업이익률": f"{m.get('operatingMarginTTM', 0):.2f}%", "부채비율": f"{m.get('totalDebt/totalEquityLTM', 0):.2f}"}
    except: return None

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
        st.markdown("<div class='intro-card'><div class='intro-title'>UNICORN FINDER</div><p>미국 시장의 차세대 주역을 발견하세요</p></div>", unsafe_allow_html=True)
        if st.button("탐험 시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()

# 2. 로그인 페이지
elif st.session_state.page == 'login':
    st.write("<br>" * 4, unsafe_allow_html=True)
    _, col_m, _ = st.columns([1, 1.5, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000")
        if st.button("시작하기", use_container_width=True):
            st.session_state.auth_status = 'user'; st.session_state.page = 'stats'; st.rerun()
    q = get_daily_quote()
    st.markdown(f"<div class='quote-card'><b>\"{q['eng']}\"</b><br><small>({q['kor']})</small><br><small>- {q['author']} -</small></div>", unsafe_allow_html=True)

# 3. 시장 분석 (그림 복구 완료)
elif st.session_state.page == 'stats':
    st.title("🦄 유니콘 성장 단계 분석")
    stages = [
        {"name": "유아기 유니콘", "img": "baby_unicorn.png", "icon": "🌱", "avg": "연 180개", "time": "1.5년", "rate": "45%"},
        {"name": "아동기 유니콘", "img": "child_unicorn.png", "icon": "🦄", "avg": "연 120개", "time": "4년", "rate": "65%"},
        {"name": "성인기 유니콘", "img": "adult_unicorn.png", "icon": "🚀", "avg": "연 85개", "time": "12년", "rate": "88%"},
        {"name": "노년기 유니콘", "img": "old_unicorn.png", "icon": "👑", "avg": "연 40개", "time": "25년+", "rate": "95%"}
    ]
    r1_c1, r1_c2 = st.columns(2); r2_c1, r2_c2 = st.columns(2)
    cols = [r1_c1, r1_c2, r2_c1, r2_c2]
    for i, stage in enumerate(stages):
        with cols[i]:
            st.markdown(f"<div class='grid-card'><h3>{stage['name']}</h3>", unsafe_allow_html=True)
            if os.path.exists(stage['img']): st.image(Image.open(stage['img']), use_container_width=True)
            else: st.markdown(f"<div style='font-size:80px; padding:10px;'>{stage['icon']}</div>", unsafe_allow_html=True)
            if st.button(f"🔎 {stage['name']} 탐험", key=f"btn_{i}", use_container_width=True):
                st.session_state.page = 'calendar'; st.rerun()
            st.markdown(f"<small>IPO {stage['avg']} | 생존 {stage['time']} | 생존율 {stage['rate']}</small></div>", unsafe_allow_html=True)

# 4. 캘린더 (리스트)
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    all_df = get_extended_ipo_data(MY_API_KEY)
    if not all_df.empty:
        for i, row in all_df.head(10).iterrows():
            if st.button(f"{row['date']} | {row['name']} ({row['symbol']})", key=f"l_{i}", use_container_width=True):
                st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()

# 5. 상세 리서치 (지표 순서 재배치 및 최종 결정항목 추가)
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        st.title(f"🚀 {stock['name']} 심층 분석")
        tab1, tab2, tab3 = st.tabs(["📋 핵심 정보 & 재무", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])

        with tab1:
            st.subheader("🔍 투자자 관심 5대 지표")
            c1, c2 = st.columns([1, 2.5])
            with c1: st.image(f"https://logo.clearbit.com/{stock['symbol']}.com", width=180)
            with c2:
                p = pd.to_numeric(stock.get('price'), errors='coerce') or 0
                s = pd.to_numeric(stock.get('numberOfShares'), errors='coerce') or 0
                st.markdown(f"<div class='info-box'><b>1. 예상 공모가:</b> ${p:,.2f}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>2. 공모 규모:</b> ${(p*s/1000000):,.1f}M USD</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>3. 상장 거래소:</b> {stock.get('exchange', 'NYSE/NASDAQ')}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>4. 보호예수:</b> 상장 후 180일 예정</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>5. 주요 주간사:</b> 글로벌 Top-tier IB</div>", unsafe_allow_html=True)
            st.write("---")
            st.markdown("#### 📊 주요 재무 및 공시 지표")
            fin = get_stock_financials(stock['symbol'], MY_API_KEY)
            if fin: st.table(pd.DataFrame(list(fin.items()), columns=['항목', '데이터']))
            else: st.info("상장 예정 기업으로 재무 데이터가 업데이트 중입니다.")

        with tab2:
            st.subheader("⚖️ AI 가치 평가")
            st.metric("추정 적정가", f"${(p*1.2):,.2f}", delta="20% 잠재력")

        with tab3:
            sid = stock['symbol']
            if sid not in st.session_state.vote_data: st.session_state.vote_data[sid] = {'u': 10, 'f': 3}
            st.subheader("1. 투자 매력도 투표")
            v1, v2 = st.columns(2)
            if v1.button("🦄 Unicorn", key=f"u_{sid}"): st.session_state.vote_data[sid]['u'] += 1; st.rerun()
            if v2.button("💸 Fallen", key=f"f_{sid}"): st.session_state.vote_data[sid]['f'] += 1; st.rerun()
            st.subheader("2. 커뮤니티 의견")
            st.text_input("의견 등록", key=f"in_{sid}")
            st.write("---")
            st.subheader("3. 최종 관심 설정")
            if st.checkbox("★ 이 기업을 '최종 관심 종목'으로 등록하시겠습니까?", key=f"watch_{sid}"):
                st.balloons(); st.success("관심 종목 등록 완료! 상장 알림이 활성화되었습니다.")
