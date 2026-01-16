import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

# 1. 페이지 설정 (브라우저 탭 이름 변경)
st.set_page_config(page_title="Unicornfinder - 미국 IPO 추적기", layout="wide", page_icon="🦄")

# --- 로그인/세션 상태 관리 ---
if 'auth_status' not in st.session_state:
    st.session_state.auth_status = None

# 2. 진입 화면 (Unicornfinder 브랜드 적용)
if st.session_state.auth_status is None:
    st.markdown("<h1 style='text-align: center;'>🦄 Unicornfinder</h1>", unsafe_allow_html=True)
    st.markdown("<h3 style='text-align: center;'>당신의 다음 유니콘을 찾아보세요</h3>", unsafe_allow_html=True)
    st.divider()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.info("### 📱 휴대폰 가입")
        phone_number = st.text_input("휴대폰 번호", placeholder="010-0000-0000")
        if st.button("Unicornfinder 시작하기", use_container_width=True):
            if len(phone_number) > 9:
                st.session_state.auth_status = 'user'
                st.rerun()
            else:
                st.error("올바른 번호를 입력해 주세요.")
                
    with col2:
        st.success("### 👤 게스트 접속")
        st.write("가입 없이 유니콘 기업 리스트를 확인합니다.")
        if st.button("비회원으로 둘러보기", use_container_width=True):
            st.session_state.auth_status = 'guest'
            st.rerun()
    st.stop()

# --- 메인 화면 (Unicornfinder 대시보드) ---
# 로그아웃 버튼
if st.sidebar.button("🚪 서비스 종료 (로그아웃)"):
    st.session_state.auth_status = None
    st.rerun()

MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

st.title("🦄 Unicornfinder Dashboard")
st.subheader("실시간 미국 주식 IPO 캘린더")

if st.session_state.auth_status == 'user':
    st.caption("✅ Unicornfinder 멤버로 접속 중")
else:
    st.caption("🔓 게스트 모드로 제한적 접속 중")

# [데이터 로드 함수]
@st.cache_data(ttl=600)
def get_ipo_data(api_key, days_ahead):
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    start_date = datetime.now().strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
    params = {'from': start_date, 'to': end_date, 'token': api_key}
    try:
        response = requests.get(base_url, params=params
