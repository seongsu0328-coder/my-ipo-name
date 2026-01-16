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
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000", key="phone_input")
        # 아래 줄 끝에 괄호와 콜론이 있는지 확인!
        if st.button("Unicornfinder 시작하기", use_container_width=True):
            if len(phone) > 9:
                st.session_state.auth_status = 'user'
                st.rerun()
            else:
                st.error("올바른 번호를 입력해 주세요.")
                
    with col2:
        st.success("### 👤 게스트 접속")
        st.write("가입 없이 서비스를 둘러봅니다.")
        if st.button("비회원으로 시작하기", use_container_width=True):
            st.session_state.auth_status = 'guest'
            st.rerun()
    st.stop()
c3.metric("5년 평균 생존율", "48.5%", delta="-51.5% 탈락 위험", delta_color="inverse")

    st.info(f"💡 현재 IPO 시장은 예년 평균 대비 **{market_status}** 상태입니다. IPO 기업의 5년 생존율은 약 48.5%로 일반 벤처기업보다 2배 높습니다.")
    
    st.divider()
    st.subheader("📈 연도별 IPO 트렌드")
    chart_data = pd.DataFrame({
        '연도': ['2020', '2021', '2022', '2023', '2024', f'{datetime.now().year}'],
        '상장건수': [480, 1035, 180, 154, 160, count_this_year]
    })
    st.bar_chart(data=chart_data, x='연도', y='상장건수', color="#6d3fc0")
    
    if st.button("실시간 IPO 캘린더 확인하기 ➡️", use_container_width=True):
        st.session_state.page = 'calendar'
        st.rerun()

# ==========================================
# 화면 3: 메인 IPO 캘린더
# ==========================================
elif st.session_state.page == 'calendar':
    st.sidebar.markdown("## 🦄 Unicornfinder")
    if st.sidebar.button("🚪 로그아웃"):
        st.session_state.auth_status = None
        st.session_state.page = 'stats'
        st.rerun()
    
    st.sidebar.divider()
    days = st.sidebar.slider("전망 기간 설정(일)", 7, 90, 30)
    exclude_spac = st.sidebar.checkbox("SPAC 제외", value=True)

    display_logo_title("Unicornfinder 캘린더")
    
    df = get_ipo_data(MY_API_KEY, days)

    if not df.empty:
        if exclude_spac:
            df = df[~df['name'].str.contains('SPAC|Acquisition|Unit|Blank Check', case=False, na=False)]
        
        display_df = df[['date', 'symbol', 'name', 'price', 'numberOfShares', 'exchange']].copy()
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
        selected_stock = st.selectbox("기업 선택", display_df['기업명'].tolist())
        if selected_stock:
            ticker = display_df[display_df['기업명'] == selected_stock]['티커'].values[0]
            st.components.v1.iframe(f"https://stocktwits.com/symbol/{ticker}", height=600, scrolling=True)
    else:
        st.warning("데이터가 없습니다.")
