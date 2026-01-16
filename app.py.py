import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder - 미국 IPO 추적기", layout="wide", page_icon="🦄")

# API 키 설정
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

# --- [모바일 최적화 CSS 스타일] ---
st.markdown("""
    <style>
    /* 1. 버튼 내부 글자가 모바일에서도 잘 보이도록 설정 */
    div.stButton > button {
        border: 1px solid #ddd !important;
        background-color: #ffffff !important; /* 배경을 흰색으로 고정 */
        color: #333333 !important;           /* 글자색을 진한 회색으로 고정 */
        padding: 10px 2px !important;        /* 좌우 패딩 최소화 */
        border-radius: 10px !important;
        font-size: 16px !important;          /* 모바일 적정 폰트 크기 */
        font-weight: bold !important;
        width: 100% !important;
        display: block !important;
    }
    
    /* 2. 메트릭(상단 지표) 글자 크기 조정 */
    [data-testid="stMetricValue"] {
        font-size: 24px !important;
    }
    
    /* 3. 이미지 테두리 둥글게 */
    [data-testid="stImage"] img {
        border-radius: 12px;
    }
    </style>
""", unsafe_allow_html=True)

# --- 로고 및 타이틀 출력 함수 ---
def display_logo_title(title_text):
    col_logo, col_text = st.columns([0.15, 0.85])
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
        if st.button("시작하기", key="start_btn", use_container_width=True):
            if len(phone) > 9:
                st.session_state.auth_status = 'user'
                st.rerun()
    with col2:
        if st.button("비회원으로 시작하기", key="guest_btn", use_container_width=True):
            st.session_state.auth_status = 'guest'
            st.rerun()
    st.stop()

# ==========================================
# 화면 2: 시장 분석 및 정보 팝업 메뉴
# ==========================================
if st.session_state.page == 'stats':
    display_logo_title("Unicornfinder 분석")
    count_this_year, avg_10y, diff = get_market_stats(MY_API_KEY)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("올해 상장", f"{count_this_year}건")
    c2.metric("10년 평균", f"{avg_10y}건")
    c3.metric("생존율", "48.5%")
    st.divider()

    row1_col1, row1_col2 = st.columns(2)
    
    # --- [유아기] ---
    with row1_col1:
        try: st.image(Image.open("baby_unicorn.png"), use_container_width=True)
        except: st.write("사진: baby_unicorn.png")
        if st.button("유아기", key="btn_baby", use_container_width=True):
            st.info("**[유아기]** 상장 0~2년차 기업. 평균 존속 2.1년.")
            if st.button("실시간 캘린더 이동", key="go_cal_baby"):
                st.session_state.page = 'calendar'
                st.rerun()

    # --- [아동기] ---
    with row1_col2:
        try: st.image(Image.open("child_unicorn.png"), use_container_width=True)
        except: st.write("사진: child_unicorn.png")
        if st.button("아동기", key="btn_child", use_container_width=True):
            st.success("**[아동기]** 상장 3~5년차 기업. 평균 존속 5.4년.")

    st.write("") 

    row2_col1, row2_col2 = st.columns(2)
    # --- [성인기] ---
    with row2_col1:
        try: st.image(Image.open("adult_unicorn.png"), use_container_width=True)
        except: st.write("사진: adult_unicorn.png")
        if st.button("성인기", key="btn_adult", use_container_width=True):
            st.warning("**[성인기]** 미국 중견기업 단계. 평균 존속 12.5년.")

    # --- [노년기] ---
    with row2_col2:
        try: st.image(Image.open("old_unicorn.png"), use_container_width=True)
        except: st.write("사진: old_unicorn.png")
        if st.button("노년기", key="btn_old", use_container_width=True):
            st.error("**[노년기]** S&P500 대기업 단계. 평균 존속 22년 이상.")

# ==========================================
# 화면 3: 메인 IPO 캘린더
# ==========================================
elif st.session_state.page == 'calendar':
    if st.sidebar.button("⬅️ 돌아가기"):
        st.session_state.page = 'stats'
        st.rerun()
    
    display_logo_title("실시간 IPO 캘린더")
    st.sidebar.divider()
    days = st.sidebar.slider("전망 기간(일)", 7, 90, 30)
    
    df = get_ipo_data(MY_API_KEY, days)

    if not df.empty:
        display_df = df[['date', 'symbol', 'name', 'price', 'numberOfShares', 'exchange']].copy()
        display_df['📄 공시'] = display_df['symbol'].apply(lambda x: f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={x}")
        display_df.columns = ['상장일', '티커', '기업명', '가격', '주식수', '거래소', '공시']

        st.data_editor(
            display_df,
            column_config={"공시": st.column_config.LinkColumn(display_text="SEC")},
            hide_index=True, use_container_width=True
        )
    else:
        st.warning("데이터가 없습니다.")
