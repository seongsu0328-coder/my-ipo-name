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
    .stButton > button[key="go_cal_baby"] {
        display: block !important;
        margin: 0 auto !important;     /* 화면 중앙 배치 */
        width: 150px !important;       /* 버튼 너비 설정 */
        height: 60px !important;
        font-size: 22px !important;
        font-weight: 900 !important;
        color: #ffffff !important;
        background: linear-gradient(145deg, #ff9a9e, #fad0c4) !important;
        border: none !important;
        border-radius: 15px !important;
        /* 3D 텍스트 그림자 효과 */
        text-shadow: 2px 2px 0px #d85d5d, 4px 4px 0px #b04b4b !important;
        /* 3D 버튼 입체감 효과 */
        box-shadow: 0px 6px 0px #d85d5d, 0px 10px 15px rgba(0,0,0,0.2) !important;
        transition: all 0.1s ease !important;
    }
    
    .stButton > button[key="go_cal_baby"]:active {
        box-shadow: 0px 2px 0px #d85d5d !important;
        transform: translateY(4px) !important;
    }

    /* 카드 스타일 */
    .unicorn-card {
        background-color: white;
        padding: 20px;
        border-radius: 20px;
        box-shadow: 0 10px 25px rgba(0,0,0,0.1);
        text-align: center;
        border: 1px solid #eee;
    }
    </style>
""", unsafe_allow_html=True)

# API 키 설정
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

# --- 데이터 분석 함수 (동일) ---
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

# --- 세션 상태 ---
if 'page' not in st.session_state: st.session_state.page = 'stats'
if 'swipe_idx' not in st.session_state: st.session_state.swipe_idx = 0

# 데이터 정의
stages = [
    {"name": "유아기", "img": "baby_unicorn.png", "desc": "상장 0~2년차. 평균 존속 2.1년.", "color": "info"},
    {"name": "아동기", "img": "child_unicorn.png", "desc": "상장 3~5년차. 평균 존속 5.4년.", "color": "success"},
    {"name": "성인기", "img": "adult_unicorn.png", "desc": "중견기업 단계. 평균 존속 12.5년.", "color": "warning"},
    {"name": "노년기", "img": "old_unicorn.png", "desc": "대기업 단계. 평균 존속 22년 이상.", "color": "error"}
]

# ==========================================
# 화면 2: Swipe 인터페이스
# ==========================================
if st.session_state.page == 'stats':
    st.title("🦄 당신의 유니콘 찾기")
    
    # Swipe 조절 슬라이더 (Tinder의 드래그 효과를 대체)
    current_idx = st.select_slider(
        "슬라이드하여 단계를 확인하세요",
        options=[0, 1, 2, 3],
        value=st.session_state.swipe_idx,
        format_func=lambda x: stages[x]['name']
    )
    st.session_state.swipe_idx = current_idx
    
    # 카드 출력
    stage = stages[current_idx]
    
    st.markdown(f"### <div style='text-align: center;'>{stage['name']} 유니콘</div>", unsafe_allow_html=True)
    
    # 이미지 중앙 배치
    col_img1, col_img2, col_img3 = st.columns([1, 2, 1])
    with col_img2:
        try: st.image(Image.open(stage['img']), use_container_width=True)
        except: st.warning(f"{stage['img']} 파일이 없습니다.")
    
    # 설명문구
    st.write(f"<div style='text-align: center; font-size: 18px;'>{stage['desc']}</div>", unsafe_allow_html=True)
    st.write("")

    # 탐험 버튼 (유아기에서만 노출하거나 모든 단계 노출 가능)
    if stage['name'] == "유아기":
        if st.button("탐험", key="go_cal_baby"):
            st.session_state.page = 'calendar'
            st.rerun()
    else:
        # 다른 단계에서는 준비 중 표시 (혹은 동일한 3D 스타일 유지 가능)
        st.write("<div style='text-align:center; color:#888;'>데이터 준비 중</div>", unsafe_allow_html=True)

# ==========================================
# 화면 3: 캘린더
# ==========================================
elif st.session_state.page == 'calendar':
    if st.button("⬅️ 돌아가기"):
        st.session_state.page = 'stats'
        st.rerun()
    st.header("실시간 유아기 유니콘 캘린더")
    # ... 데이터 테이블 출력 로직 ...
    df = get_ipo_data(MY_API_KEY, 30)
    st.dataframe(df, use_container_width=True)
