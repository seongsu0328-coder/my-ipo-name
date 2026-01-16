import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

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

# --- 데이터 분석 및 비교 함수 ---
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
    
    avg_10y = 280 # 10년 평균치
    
    # [비교 로직] 오늘 기준 예상 건수 계산
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
# 화면 1: 진입 화면 (로그인)
# ==========================================
if st.session_state.auth_status is None:
    st.write("<div style='text-align: center;'>", unsafe_allow_html=True)
    st.write("# 🦄")
    st.write("# Unicornfinder")
    st.write("### 당신의 다음 유니콘을 찾아보세요")
    st.write("</div>", unsafe_allow_html=True)
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        st.info("### 📱 휴대폰 가입")
        phone_number = st.text_input("휴대폰 번호", placeholder="010-0000-0000", key="phone_input")
        if st.button("Unicornfinder 시작하기", use_container_width=True):
            if len(phone_number) > 9:
                st.session_state.auth_status = 'user'
                st.rerun()
            else:
                st.error("올바른 번호를 입력해 주세요.")
   with col2:
        st.success("### 👤 게스트 접속")
        st.write("가입 없이 서비스를 둘러봅니다.")
        # 아래 줄 끝에 괄호 ')'와 콜론 ':'이 정확히 있는지 확인하세요.
        if st.button("비회원으로 시작하기", use_container_width=True):
            st.session_state.auth_status = 'guest'
            st.rerun()
