import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

# 1. 환경 설정
st.set_page_config(page_title="미국 주식 IPO 알리미", layout="wide")

# --- 로그인/세션 상태 관리 ---
if 'auth_status' not in st.session_state:
    st.session_state.auth_status = None  # None: 초기화면, 'user': 로그인, 'guest': 비회원

# 2. 진입 화면 (로그인이 안 된 상태일 때만 표시)
if st.session_state.auth_status is None:
    st.title("🚀 미국 주식 IPO 알리미")
    st.subheader("반갑습니다! 서비스를 시작하려면 접속 방식을 선택해 주세요.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.info("### 📱 휴대폰 번호로 가입")
        phone_number = st.text_input("휴대폰 번호 입력", placeholder="010-0000-0000")
        if st.button("가입 및 접속하기"):
            if len(phone_number) > 9: # 간단한 번호 체크
                st.session_state.auth_status = 'user'
                st.rerun()
            else:
                st.error("올바른 번호를 입력해 주세요.")
                
    with col2:
        st.success("### 👤 비회원 접속")
        st.write("가입 없이 바로 IPO 정보를 확인합니다.")
        if st.button("비회원으로 시작하기"):
            st.session_state.auth_status = 'guest'
            st.rerun()
    st.stop() # 아래 코드를 실행하지 않고 여기서 멈춤

# --- 여기서부터는 접속 후 화면 ---
# 로그아웃 버튼 (사이드바에 추가)
if st.sidebar.button("로그아웃/초기화면"):
    st.session_state.auth_status = None
    st.rerun()

MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

st.title("🚀 미국 주식 상장 예정(IPO) 캘린더")
if st.session_state.auth_status == 'user':
    st.caption("✅ 정회원 모드로 접속 중입니다.")
else:
    st.caption("🔓 비회원 모드로 접속 중입니다.")

# [이후 데이터 로드 및 표 출력 코드는 이전과 동일하게 유지]
@st.cache_data(ttl=600)
def get_ipo_data(api_key, days_ahead):
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    start_date = datetime.now().strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
    params = {'from': start_date, 'to': end_date, 'token': api_key}
    try:
        response = requests.get(base_url, params=params)
        data = response.json()
        return pd.DataFrame(data['ipoCalendar']) if 'ipoCalendar' in data else pd.DataFrame()
    except:
        return pd.DataFrame()

days = st.sidebar.slider("조회 기간(일)", 7, 90, 30)
exclude_spac = st.sidebar.checkbox("SPAC 기업 제외", value=True)

df = get_ipo_data(MY_API_KEY, days)

if not df.empty:
    if exclude_spac:
        df = df[~df['name'].str.contains('SPAC|Acquisition|Unit|Blank Check', case=False, na=False)]
    
    display_df = df[['date', 'symbol', 'name', 'price', 'numberOfShares', 'exchange']].copy()
    display_df['📄 공시'] = display_df['symbol'].apply(lambda x: f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={x}")
    display_df['📊 재무'] = display_df['symbol'].apply(lambda x: f"https://finance.yahoo.com/quote/{x}/financials")
    display_df['💬 토론'] = display_df['symbol'].apply(lambda x: f"https://finance.yahoo.com/quote/{x}/community")
    
    display_df.columns = ['상장일', '티커', '기업명', '공모가($)', '주식수', '거래소', '공시', '재무', '토론']

    st.data_editor(
        display_df,
        column_config={
            "공시": st.column_config.LinkColumn(display_text="보기"),
            "재무": st.column_config.LinkColumn(display_text="보기"),
            "토론": st.column_config.LinkColumn(display_text="참여"),
        },
        hide_index=True, use_container_width=True, disabled=True
    )
else:
    st.warning("데이터가 없습니다.")
