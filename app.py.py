import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder - 미국 IPO 추적기", layout="wide", page_icon="🦄")

# API 키 설정
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

# --- 세션 상태 초기화 ---
if 'auth_status' not in st.session_state:
    st.session_state.auth_status = None
if 'page' not in st.session_state:
    st.session_state.page = 'stats' # 로그인 후 첫 페이지는 통계로 설정

# --- [데이터 분석 함수] ---
@st.cache_data(ttl=86400) # 24시간마다 갱신
def get_market_stats(api_key):
    current_year = datetime.now().year
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    
    # 올해 1월 1일부터 오늘까지의 실제 데이터 호출
    params = {'from': f'{current_year}-01-01', 'to': datetime.now().strftime('%Y-%m-%d'), 'token': api_key}
    try:
        response = requests.get(base_url, params=params).json()
        count_this_year = len(response.get('ipoCalendar', []))
    except:
        count_this_year = 0
    
    avg_10y = 280 # 최근 10년 고정 평균치
    return count_this_year, avg_10y

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
    st.markdown("<h1 style='text-align: center;'>🦄 Unicornfinder</h1>", unsafe_allow_html=True)
    st.markdown("<h3 style='text-align: center;'>당신의 다음 유니콘을 찾아보세요</h3>", unsafe_allow_html=True)
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1
