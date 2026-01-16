import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- CSS 스타일 (3D 버튼 및 레이아웃) ---
st.markdown("""
    <style>
    /* 3D 탐험 버튼 */
    div.stButton > button[key="go_cal_baby"] {
        display: block !important;
        margin: 10px auto !important;     
        width: 220px !important; 
        height: 75px !important;
        font-size: 28px !important;
        font-weight: 900 !important;
        color: #ffffff !important;
        background: linear-gradient(145deg, #6e8efb, #a777e3) !important;
        border: none !important;
        border-radius: 20px !important;
        text-shadow: 2px 2px 0px #4a69bd, 3px 3px 0px #3c569b !important;
        box-shadow: 0px 8px 0px #3c569b, 0px 15px 20px rgba(0,0,0,0.3) !important;
        transition: all 0.1s ease !important;
    }
    div.stButton > button[key="go_cal_baby"]:active {
        box-shadow: 0px 2px 0px #3c569b !important;
        transform: translateY(6px) !important;
    }
    
    /* 화살표 버튼 */
    div.stButton > button[key^="prev_"], div.stButton > button[key^="next_"] {
        font-size: 24px !important;
        font-weight: bold !important;
        border-radius: 50% !important;
        width: 60px !important;
        height: 60px !important;
    }

    .card-text {
        text-align: center;
        font-size: 1.2rem;
        padding: 20px;
        background-color: #f8f9fa;
        border-radius: 15px;
        margin: 15px 0;
        color: #333;
    }
    </style>
""", unsafe_allow_html=True)

# API 키 및 세션 상태 설정
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

if 'auth_status' not in st.session_state: st.session_state.auth_status = None
if 'page' not in st.session_state: st.session_state.page = 'stats'
if 'swipe_idx' not in st.session_state: st.session_state.swipe_idx = 0

# --- 데이터 로직 함수 ---
@st.cache_data(ttl=86400)
def get_market_stats(api_key):
    return 154, 280, 48.5 

@st.cache_data(ttl=600)
def get_ipo_data(api_key, days_ahead):
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    params = {'from': datetime.now().strftime('%Y-%m-%d'), 
              'to': (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d'), 
              'token': api_key}
    try:
        response = requests.get(base_url, params=params).json()
        return pd.DataFrame(response['ipoCalendar']) if 'ipoCalendar' in response else pd.DataFrame()
    except: return pd.DataFrame()

# ==========================================
# 화면 1: 진입 화면 (회원/비회원 선택 복구)
# ==========================================
if st.session_state.auth_status is None:
    st.write("<div style='text-align: center; margin-top: 50px;'><h1>🦄 Unicornfinder</h1><h3>당신의 다음 유니콘을 찾아보세요</h3></div>", unsafe_allow_html=True)
    st.divider()
    
    _, col_m, _ = st.columns([1, 2, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호 (회원 접속 시)", placeholder="010-0000-0000", key="phone_input")
        
        # 버튼을 나란히 배치하기 위해 컬럼 분할
        btn_col1, btn_col2 = st.columns(2)
        
        with btn_col1:
            if st.button("회원 로그인", use_container_width=True):
                if len(phone) > 9:
                    st.session_state.auth_status = 'user'
                    st.rerun()
                else:
                    st.warning("번호를 입력해주세요.")
        
        with btn_col2:
            if st.button("비회원 시작", use_container_width=True):
                st.session_state.auth_status = 'guest'
                st.rerun()
    st.stop()

# ==========================================
# 화면 2: 시장 분석 + 화살표 카드
# ==========================================
if st.session_state.page == 'stats':
    st.title("🦄 Unicornfinder 분석")
    count_this_year, avg_10y, survival_rate = get_market_stats(MY_API_KEY)
    c1, c2, c3 = st.columns(3)
    c1.metric("올해 상장", f"{count_this_year}건")
    c2.metric("10년 평균", f"{avg_10y}건")
    c3.metric("5년 생존율", f"{survival_rate}%")
    st.divider()

    stages = [
        {"name": "유아기", "img": "baby_unicorn.png", "desc": "상장 0~2년차 기업입니다. 가장 변동성이 크며, 평균 존속 기간은 2.1년입니다."},
        {"name": "아동기", "img": "child_unicorn.png", "desc": "상장 3~5년차 기업으로 시장에 안착하는 단계입니다. 평균 존속 기간은 5.4년입니다."},
        {"name": "성인기", "img": "adult_unicorn.png", "desc": "미국 중견기업 수준으로 성장한 단계입니다. 상장 후 평균 12.5년을 생존합니다."},
        {"name": "노년기", "img": "old_unicorn.png", "desc": "S&P500급 대기업 단계입니다. 상장 후 평균 22년 이상의 생존력을 가집니다."}
    ]

    idx = st.session_state.swipe_idx
    stage = stages[idx]

    st.markdown(f"<h2 style='text-align: center;'>{stage['name']} 유니콘</h2>", unsafe_allow_html=True)
    
    _, col_img, _ = st.columns([1, 2.5, 1])
    with col_img:
        try: st.image(Image.open(stage['img']), use_container_width=True)
        except: st.write(f"이미지 필요: {stage['img']}")

    # 화살표 버튼
    col_prev, col_spacer, col_next = st.columns([1, 4, 1])
    with col_prev:
        if st.button("◀", key=f"prev_{idx}"):
            st.session_state.swipe_idx = (idx - 1) % len(stages)
            st.rerun()
    with col_next:
        if st.button("▶", key=f"next_{idx}"):
            st.session_state.swipe_idx = (idx + 1) % len(stages)
            st.rerun()

    st.markdown(f"<div class='card-text'>{stage['desc']}</div>", unsafe_allow_html=True)

    if stage['name'] == "유아기":
        if st.button("탐험", key="go_cal_baby"):
            st.session_state.page = 'calendar'
            st.rerun()

# ==========================================
# 화면 3: 캘린더 (공시/재무/피드 포함)
# ==========================================
elif st.session_state.page == 'calendar':
    if st.sidebar.button("⬅️ 돌아가기"):
        st.session_state.page = 'stats'
        st.rerun()
    
    st.header("🚀 실시간 유아기 유니콘 캘린더")
    df = get_ipo_data(MY_API_KEY, 30)

    if not df.empty:
        display_df = df[['date', 'symbol', 'name', 'price', 'numberOfShares', 'exchange']].copy()
        display_df['📄 공시'] = display_df['symbol'].apply(lambda x: f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={x}")
        display_df['📊 재무'] = display_df['symbol'].apply(lambda x: f"https://finance.yahoo.com/quote/{x}/financials")
        display_df.columns = ['상장일', '티커', '기업명', '가격', '주식수', '거래소', '공시', '재무']

        st.data_editor(
            display_df,
            column_config={
                "공시": st.column_config.LinkColumn(display_text="SEC 확인"),
                "재무": st.column_config.LinkColumn(display_text="지표 확인"),
            },
            hide_index=True, use_container_width=True
        )
        
        st.divider()
        st.subheader("💬 실시간 분석 피드")
        selected_stock = st.selectbox("분석할 기업 선택", display_df['기업명'].tolist())
        if selected_stock:
            ticker = display_df[display_df['기업명'] == selected_stock]['티커'].values[0]
            st.components.v1.iframe(f"https://stocktwits.com/symbol/{ticker}", height=500, scrolling=True)
