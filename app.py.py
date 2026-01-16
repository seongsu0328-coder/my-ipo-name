import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- CSS 스타일 (기존과 동일) ---
st.markdown("""
    <style>
    div.stButton > button[key="go_cal_baby"] {
        display: block !important; margin: 20px auto !important;     
        width: 260px !important; height: 85px !important;
        font-size: 32px !important; font-weight: 900 !important;
        color: #ffffff !important;
        background: linear-gradient(145deg, #6e8efb, #a777e3) !important;
        border: none !important; border-radius: 20px !important;
        text-shadow: 2px 2px 0px #4a69bd !important;
        box-shadow: 0px 8px 0px #3c569b, 0px 15px 20px rgba(0,0,0,0.3) !important;
    }
    div.stButton > button[key^="p_"], div.stButton > button[key^="n_"] {
        font-size: 50px !important; font-weight: 900 !important;
        padding: 0px !important; border-radius: 12px !important;
        width: 100% !important; height: 85px !important;
        background-color: #ffffff !important; border: 3px solid #6e8efb !important;
        color: #6e8efb !important; box-shadow: 0px 5px 0px #6e8efb !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
    }
    .card-text {
        text-align: center; font-size: 1.3rem; padding: 25px;
        background-color: #f8f9fa; border-radius: 20px;
        margin-top: 15px; color: #333; border: 1px solid #eee;
    }
    </style>
""", unsafe_allow_html=True)

# API 키 및 세션 설정
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"
if 'auth_status' not in st.session_state: st.session_state.auth_status = None
if 'page' not in st.session_state: st.session_state.page = 'stats'
if 'swipe_idx' not in st.session_state: st.session_state.swipe_idx = 0

# --- 데이터 로직 ---
@st.cache_data(ttl=600)
def get_ipo_data(api_key, days_ahead):
    # 과거 5일부터 사용자가 설정한 미래 날짜까지 가져오기
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    params = {'from': (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'), 
              'to': (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d'), 
              'token': api_key}
    try:
        response = requests.get(base_url, params=params).json()
        return pd.DataFrame(response['ipoCalendar']) if 'ipoCalendar' in response else pd.DataFrame()
    except: return pd.DataFrame()

# (화면 1: 로그인 로직 생략 - 기존과 동일)
if st.session_state.auth_status is None:
    st.write("<div style='text-align: center; margin-top: 50px;'><h1>🦄 Unicornfinder</h1><h3>당신의 다음 유니콘을 찾아보세요</h3></div>", unsafe_allow_html=True)
    st.divider()
    _, col_m, _ = st.columns([1, 2, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000", key="phone_input")
        c1, c2 = st.columns(2)
        if c1.button("회원 로그인", use_container_width=True): 
            if len(phone) > 9: st.session_state.auth_status = 'user'; st.rerun()
        if c2.button("비회원 시작", use_container_width=True): st.session_state.auth_status = 'guest'; st.rerun()
    st.stop()

# 화면 2: 카드 슬라이드
if st.session_state.page == 'stats':
    st.title("🦄 Unicornfinder 분석")
    st.divider()
    stages = [{"name": "유아기", "img": "baby_unicorn.png", "desc": "상장 0~2년차 기업입니다."}, {"name": "아동기", "img": "child_unicorn.png", "desc": "상장 3~5년차 기업입니다."}, {"name": "성인기", "img": "adult_unicorn.png", "desc": "중견기업 단계입니다."}, {"name": "노년기", "img": "old_unicorn.png", "desc": "대기업 단계입니다."}]
    idx = st.session_state.swipe_idx
    stage = stages[idx]
    st.markdown(f"<h2 style='text-align: center; color: #6e8efb;'>{stage['name']} 유니콘</h2>", unsafe_allow_html=True)
    _, ci, _ = st.columns([1, 2, 1])
    with ci:
        if os.path.exists(stage['img']): st.image(Image.open(stage['img']), use_container_width=True)
        else: st.info(f"[{stage['name']} 이미지]")
    _, n1, n2, _ = st.columns([1.8, 0.7, 0.7, 1.8])
    if n1.button("◀", key=f"p_{idx}"): st.session_state.swipe_idx = (idx-1)%4; st.rerun()
    if n2.button("▶", key=f"n_{idx}"): st.session_state.swipe_idx = (idx+1)%4; st.rerun()
    st.markdown(f"<div class='card-text'>{stage['desc']}</div>", unsafe_allow_html=True)
    if stage['name'] == "유아기":
        if st.button("탐험", key="go_cal_baby"): st.session_state.page = 'calendar'; st.rerun()

# ==========================================
# 화면 3: 캘린더 (날짜 조절 슬라이더 추가)
# ==========================================
elif st.session_state.page == 'calendar':
    # 사이드바 설정
    st.sidebar.header("⚙️ 필터 설정")
    if st.sidebar.button("⬅️ 돌아가기"):
        st.session_state.page = 'stats'
        st.rerun()
    
    st.sidebar.divider()
    # 날짜 범위 조절 슬라이더 복구 (0일~60일)
    days_ahead = st.sidebar.slider("조회 기간 설정 (오늘 기준 이후)", min_value=0, max_value=60, value=30, step=5)
    st.sidebar.caption(f"현재 오늘부터 {days_ahead}일 뒤까지 조회 중입니다.")

    st.header(f"🚀 실시간 유아기 유니콘 캘린더 (향후 {days_ahead}일)")
    
    # 슬라이더에서 받은 days_ahead 값을 API에 전달
    df = get_ipo_data(MY_API_KEY, days_ahead)

    if not df.empty:
        # 데이터 처리 (가격 복구 로직 포함)
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df['numberOfShares'] = pd.to_numeric(df['numberOfShares'], errors='coerce')
        
        def get_price_display(val):
            if pd.isna(val) or val <= 0: return "공시 확인(미정)"
            return f"${val:,.2f}"
        df['희망가/공모가'] = df['price'].apply(get_price_display)
        
        df['공모규모_num'] = df['price'] * df['numberOfShares']
        def get_deal_size_display(val):
            if pd.isna(val) or val <= 0: return "계산 불가"
            return f"${val:,.0f}"
        df['공모규모($)'] = df['공모규모_num'].apply(get_deal_size_display)
        
        df['자금용도'] = "공시(S-1) 참조"
        df['보호예수'] = "180일(통상)"
        df['언더라이터'] = "주관사 확인" 
        df['📄 공시'] = df['symbol'].apply(lambda x: f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={x}")
        df['📊 재무'] = df['symbol'].apply(lambda x: f"https://finance.yahoo.com/quote/{x}/financials")
        
        result_df = df[['name', 'symbol', '희망가/공모가', 'numberOfShares', '공모규모($)', '자금용도', '보호예수', '언더라이터', 'exchange', '📄 공시', '📊 재무']]
        result_df.columns = ['기업명', '티커', '희망가/공모가', '주식수', '공모규모($)', '자금용도', '보호예수', '언더라이터', '거래소', '공시', '재무']

        st.data_editor(
            result_df,
            column_config={
                "주식수": st.column_config.NumberColumn(format="%d"),
                "공시": st.column_config.LinkColumn(display_text="SEC 확인"),
                "재무": st.column_config.LinkColumn(display_text="재무 지표"),
            },
            hide_index=True, use_container_width=True
        )
    else:
        st.warning(f"최근 5일부터 향후 {days_ahead}일 사이에 예정된 IPO 데이터가 없습니다.")
