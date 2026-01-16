import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 3D 글씨체 및 버튼 중앙 정렬 CSS ---
st.markdown("""
    <style>
    /* 3D 효과를 주는 탐험 버튼 스타일 */
    div.stButton > button[key="go_cal_baby"] {
        display: block !important;
        margin: 30px auto !important;     /* 화면 중앙 배치 및 상하 여백 */
        width: 200px !important; 
        height: 70px !important;
        font-size: 26px !important;
        font-weight: 900 !important;
        color: #ffffff !important;
        background: linear-gradient(145deg, #6e8efb, #a777e3) !important;
        border: none !important;
        border-radius: 20px !important;
        /* 3D 텍스트 그림자 */
        text-shadow: 2px 2px 0px #4a69bd, 3px 3px 0px #3c569b !important;
        /* 3D 버튼 입체감 */
        box-shadow: 0px 8px 0px #3c569b, 0px 15px 20px rgba(0,0,0,0.3) !important;
        transition: all 0.1s ease !important;
    }
    
    div.stButton > button[key="go_cal_baby"]:active {
        box-shadow: 0px 2px 0px #3c569b !important;
        transform: translateY(6px) !important;
    }

    /* 카드 텍스트 중앙 정렬 */
    .card-text {
        text-align: center;
        font-size: 1.2rem;
        margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)

# API 키 설정
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

# --- 세션 상태 초기화 ---
if 'auth_status' not in st.session_state:
    st.session_state.auth_status = None
if 'page' not in st.session_state:
    st.session_state.page = 'stats'
if 'swipe_idx' not in st.session_state:
    st.session_state.swipe_idx = 0

# --- 데이터 분석 함수 ---
@st.cache_data(ttl=600)
def get_ipo_data(api_key, days_ahead):
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    start_date = datetime.now().strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
    params = {'from': start_date, 'to': end_date, 'token': api_key}
    try:
        response = requests.get(base_url, params=params).json()
        return pd.DataFrame(response['ipoCalendar']) if 'ipoCalendar' in response else pd.DataFrame()
    except: return pd.DataFrame()

# ==========================================
# 화면 1: 진입 화면 (로그인 창 복구)
# ==========================================
if st.session_state.auth_status is None:
    st.write("<div style='text-align: center; margin-top: 50px;'><h1>🦄 Unicornfinder</h1><h3>당신의 다음 유니콘을 찾아보세요</h3></div>", unsafe_allow_html=True)
    st.divider()
    
    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000", key="phone_input")
        if st.button("시작하기", key="start_btn", use_container_width=True):
            if len(phone) > 9:
                st.session_state.auth_status = 'user'
                st.rerun()
        
        if st.button("비회원으로 시작하기", key="guest_btn", use_container_width=True):
            st.session_state.auth_status = 'guest'
            st.rerun()
    st.stop()  # 로그인 전까지 아래 코드를 실행하지 않음

# ==========================================
# 화면 2: Tinder 스타일 Swipe 인터페이스
# ==========================================
if st.session_state.page == 'stats':
    st.title("🦄 Unicornfinder 분석")
    
    # 데이터 정의
    stages = [
        {"name": "유아기", "img": "baby_unicorn.png", "desc": "상장 0~2년차 기업입니다. 가장 변동성이 크며, 평균 존속 기간은 2.1년입니다."},
        {"name": "아동기", "img": "child_unicorn.png", "desc": "상장 3~5년차 기업으로 시장에 안착하는 단계입니다. 평균 존속 기간은 5.4년입니다."},
        {"name": "성인기", "img": "adult_unicorn.png", "desc": "미국 중견기업 수준으로 성장한 단계입니다. 상장 후 평균 12.5년을 생존합니다."},
        {"name": "노년기", "img": "old_unicorn.png", "desc": "S&P500급 대기업 단계입니다. 상장 후 평균 22년 이상의 생존력을 가집니다."}
    ]

    # 슬라이더로 Swipe 구현
    current_idx = st.select_slider(
        "슬라이드하여 단계를 탐험하세요 (좌우 드래그)",
        options=[0, 1, 2, 3],
        value=st.session_state.swipe_idx,
        format_func=lambda x: stages[x]['name']
    )
    st.session_state.swipe_idx = current_idx
    stage = stages[current_idx]

    st.markdown(f"<h2 style='text-align: center;'>{stage['name']} 유니콘</h2>", unsafe_allow_html=True)

    # 이미지 중앙 배치
    _, col_img, _ = st.columns([1, 3, 1])
    with col_img:
        try:
            st.image(Image.open(stage['img']), use_container_width=True)
        except:
            st.warning(f"{stage['img']} 파일이 없습니다.")

    # 설명글 중앙 배치
    st.markdown(f"<div class='card-text'>{stage['desc']}</div>", unsafe_allow_html=True)

    # [유아기] 단계에서만 '탐험' 버튼 등장 (3D 스타일 & 중앙 배치)
    if stage['name'] == "유아기":
        if st.button("탐험", key="go_cal_baby"):
            st.session_state.page = 'calendar'
            st.rerun()

# ==========================================
# 화면 3: 메인 IPO 캘린더
# ==========================================
elif st.session_state.page == 'calendar':
    if st.sidebar.button("⬅️ 돌아가기"):
        st.session_state.page = 'stats'
        st.rerun()
    
    st.header("🚀 실시간 IPO 캘린더 (유아기)")
    df = get_ipo_data(MY_API_KEY, 30)
    
    if not df.empty:
        st.dataframe(df[['date', 'symbol', 'name', 'price', 'exchange']], use_container_width=True)
    else:
        st.warning("데이터가 없습니다.")
