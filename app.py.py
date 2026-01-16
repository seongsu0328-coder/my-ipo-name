import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder - 미국 IPO 추적기", layout="wide", page_icon="🦄")

# API 키 설정
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

# --- 로고 및 타이틀 출력 함수 ---
def display_logo_title(title_text):
    col_logo, col_text = st.columns([0.1, 0.9])
    with col_logo:
        st.write("# 🦄")
    with col_text:
        st.title(title_text)

# --- 세션 상태 초기화 ---
if 'auth_status' not in st.session_state:
    st.session_state.auth_status = None
if 'page' not in st.session_state:
    st.session_state.page = 'stats'

# --- 데이터 분석 함수 ---
@st.cache_data(ttl=86400)
def get_market_stats(api_key):
    current_year = datetime.now().year
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    params = {'from': f'{current_year}-01-01', 'to': datetime.now().strftime('%Y-%m-%d'), 'token': api_key}
    try:
        response = requests.get(base_url, params=params).json()
        count_this_year = len(response.get('ipoCalendar', []))
    except:
        count_this_year = 0
    avg_10y = 280 
    day_of_year = datetime.now().timetuple().tm_yday
    expected_now = (avg_10y / 365) * day_of_year
    diff = count_this_year - expected_now
    return count_this_year, avg_10y, diff

@st.cache_data(ttl=600)
def get_ipo_data(api_key, days_ahead):
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    start_date = datetime.now().strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
    params = {'from': start_date, 'to': end_date, 'token': api_key}
    try:
        response = requests.get(base_url, params=params).json()
        return pd.DataFrame(response['ipoCalendar']) if 'ipoCalendar' in response else pd.DataFrame()
    except:
        return pd.DataFrame()

# ==========================================
# 화면 1: 진입 화면
# ==========================================
if st.session_state.auth_status is None:
    st.write("<div style='text-align: center;'><h1>🦄 Unicornfinder</h1><h3>당신의 다음 유니콘을 찾아보세요</h3></div>", unsafe_allow_html=True)
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000", key="phone_input")
        if st.button("시작하기", use_container_width=True):
            if len(phone) > 9:
                st.session_state.auth_status = 'user'
                st.rerun()
    with col2:
        if st.button("비회원으로 시작하기", use_container_width=True):
            st.session_state.auth_status = 'guest'
            st.rerun()
    st.stop()

# ==========================================
# 화면 2: 시장 분석 및 커스텀 이미지 버튼
# ==========================================
if st.session_state.page == 'stats':
    display_logo_title("Unicornfinder 시장 분석")
    count_this_year, avg_10y, diff = get_market_stats(MY_API_KEY)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("올해 상장 건수", f"{count_this_year}건")
    c2.metric("10년 연평균 상장", f"{avg_10y}건")
    c3.metric("5년 평균 생존율", "48.5%")
    st.divider()

    # --- 이미지 버튼 디자인 CSS ---
    st.markdown("""
        <style>
        div.stButton > button {
            border: none !important;
            background-color: #f0f2f6 !important;
            padding: 10px !important;
            border-radius: 10px !important;
        }
        </style>
    """, unsafe_allow_html=True)

    row1_col1, row1_col2 = st.columns(2)
    
    with row1_col1:
        try:
            # 업로드한 이미지 불러오기
            img = Image.open("baby_unicorn.png")
            st.image(img, use_container_width=True)
            # 이미지 바로 아래 버튼 배치
            if st.button("🍼 유아 유니콘 데이터 보기", use_container_width=True):
                st.session_state.page = 'calendar'
                st.rerun()
        except:
            # 사진이 없을 경우 대비
            st.warning("baby_unicorn.png 파일을 업로드해주세요.")
            if st.button("🍼 유아 유니콘 (임시 버튼)", use_container_width=True):
                st.session_state.page = 'calendar'
                st.rerun()
        st.markdown("<p style='text-align: center;'>상장 0~2년차 / 평균 존속 <b>2.1년</b></p>", unsafe_allow_html=True)

    with row1_col2:
        # 아동 유니콘 (동일한 방식으로 사진 추가 가능)
        st.write("# 🎈") # 임시 아이콘
        if st.button("아동 유니콘 분석 준비중", use_container_width=True):
            st.toast("데이터 준비 중입니다.")
        st.markdown("<p style='text-align: center;'>상장 3~5년차 / 평균 존속 <b>5.4년</b></p>", unsafe_allow_html=True)

    st.write("") # 간격

    row2_col1, row2_col2 = st.columns(2)
    with row2_col1:
        st.write("# 👔")
        st.button("성인 유니콘 준비중", use_container_width=True)
    with row2_col2:
        st.write("# 🏛️")
        st.button("노년 유니콘 준비중", use_container_width=True)

# ==========================================
# 화면 3: 메인 IPO 캘린더
# ==========================================
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    display_logo_title("실시간 IPO 캘린더")
    
    df = get_ipo_data(MY_API_KEY, 30)
    if not df.empty:
        st.dataframe(df[['date', 'symbol', 'name', 'price', 'exchange']], use_container_width=True)
        
        st.divider()
        st.subheader("💬 실시간 분석 피드")
        selected_stock = st.selectbox("기업 선택", df['name'].tolist())
        ticker = df[df['name'] == selected_stock]['symbol'].values[0]
        st.components.v1.iframe(f"https://stocktwits.com/symbol/{ticker}", height=600, scrolling=True)
    else:
        st.warning("상장 예정 데이터가 없습니다.")
