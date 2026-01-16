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
# 화면 2: 시장 분석 및 이미지 타일 메뉴
# ==========================================
if st.session_state.page == 'stats':
    display_logo_title("Unicornfinder 시장 분석")
    count_this_year, avg_10y, diff = get_market_stats(MY_API_KEY)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("올해 상장 건수", f"{count_this_year}건")
    c2.metric("10년 연평균 상장", f"{avg_10y}건")
    c3.metric("5년 평균 생존율", "48.5%")
    st.divider()

    st.markdown("""
        <style>
        div.stButton > button {
            border: 1px solid #ddd !important;
            background-color: #ffffff !important;
            padding: 10px !important;
            border-radius: 8px !important;
        }
        </style>
    """, unsafe_allow_html=True)

    row1_col1, row1_col2 = st.columns(2)
    with row1_col1:
        try:
            img = Image.open("baby_unicorn.png")
            st.image(img, use_container_width=True)
            if st.button("🍼 유아 유니콘 데이터 확인", use_container_width=True):
                st.session_state.page = 'calendar'
                st.rerun()
        except FileNotFoundError:
            st.warning("baby_unicorn.png 파일을 찾을 수 없습니다.")
            if st.button("🍼 유아 유니콘 (임시 버튼)", use_container_width=True):
                st.session_state.page = 'calendar'
                st.rerun()
        st.markdown("<p style='text-align: center;'><b>[유아]</b> 상장 0~2년차<br>평균 존속 <b>2.1년</b></p>", unsafe_allow_html=True)

    with row1_col2:
        st.write("<h1 style='text-align: center;'>🎈</h1>", unsafe_allow_html=True)
        if st.button("아동 유니콘 분석 준비중", use_container_width=True):
            st.toast("데이터를 수집 중입니다.")
        st.markdown("<p style='text-align: center;'><b>[아동]</b> 상장 3~5년차<br>평균 존속 <b>5.4년</b></p>", unsafe_allow_html=True)

    row2_col1, row2_col2 = st.columns(2)
    with row2_col1:
        st.write("<h1 style='text-align: center;'>👔</h1>", unsafe_allow_html=True)
        st.button("성인 유니콘 준비중", use_container_width=True)
        st.markdown("<p style='text-align: center;'><b>[성인]</b> 미국 중견기업<br>상장 후 평균 <b>12.5년</b></p>", unsafe_allow_html=True)
    with row2_col2:
        st.write("<h1 style='text-align: center;'>🏛️</h1>", unsafe_allow_html=True)
        st.button("노년 유니콘 준비중", use_container_width=True)
        st.markdown("<p style='text-align: center;'><b>[노년]</b> 미국 대기업<br>상장 후 평균 <b>22년 이상</b></p>", unsafe_allow_html=True)

# ==========================================
# 화면 3: 메인 IPO 캘린더
# ==========================================
elif st.session_state.page == 'calendar':
    if st.sidebar.button("⬅️ 분석 화면으로"):
        st.session_state.page = 'stats'
        st.rerun()
    
    st.sidebar.divider()
    days = st.sidebar.slider("전망 기간 설정(일)", 7, 90, 30)
    exclude_spac = st.sidebar.checkbox("SPAC 제외", value=True)

    display_logo_title("유아 유니콘: 실시간 캘린더")
    
    df = get_ipo_data(MY_API_KEY, days)

    if not df.empty:
        if exclude_spac:
            df = df[~df['name'].str.contains('SPAC|Acquisition|Unit|Blank Check', case=False, na=False)]
        
        display_df = df[['date', 'symbol', 'name', 'price', 'numberOfShares', 'exchange']].copy()
        
        # --- 끊겼던 부분: 링크 생성 ---
        display_df['📄 공시'] = display_df['symbol'].apply(lambda x: f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={x}")
        display_df['📊 재무'] = display_df['symbol'].apply(lambda x: f"https://finance.yahoo.com/quote/{x}/financials")
        display_df['💬 토론'] = display_df['symbol'].apply(lambda x: f"https://finance.yahoo.com/quote/{x}/community")
        
        display_df.columns = ['상장일', '티커', '기업명', '가격', '주식수', '거래소', '공시', '재무', '토론']

        st.data_editor(
            display_df,
            column_config={
                "공시": st.column_config.LinkColumn(display_text="보기"),
                "재무": st.column_config.LinkColumn(display_text="보기"),
                "토론": st.column_config.LinkColumn(display_text="참여"),
            },
            hide_index=True, use_container_width=True, disabled=True
        )
        
        st.divider()
        st.subheader("💬 실시간 분석 피드")
        selected_stock = st.selectbox("분석할 기업 선택", display_df['기업명'].tolist())
        if selected_stock:
            ticker = display_df[display_df['기업명'] == selected_stock]['티커'].values[0]
            st.components.v1.iframe(f"https://stocktwits.com/symbol/{ticker}", height=600, scrolling=True)
    else:
        st.warning("데이터가 없습니다.")
