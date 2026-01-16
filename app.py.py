import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- CSS 스타일 ---
st.markdown("""
    <style>
    /* 여백 및 폰트 최적화 */
    .stApp { background-color: #ffffff; }
    
    /* 2번째 화면 단계 제목 스타일 */
    .stage-title { 
        text-align: center; 
        color: #4a69bd; 
        font-size: 38px; 
        font-weight: 900; 
        margin-top: -30px; 
        margin-bottom: 20px;
        letter-spacing: -1px;
    }
    
    .stats-box {
        background-color: #f8faff; padding: 20px; border-radius: 12px;
        text-align: center; border: 1px solid #e1e8f0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.02);
    }
    .stats-label { font-size: 14px; color: #777; font-weight: bold; margin-bottom: 5px; }
    .stats-value { font-size: 22px; color: #2e4172; font-weight: 900; }
    
    /* 기업명 버튼 */
    div.stButton > button[key^="name_"] {
        background-color: transparent !important; border: none !important;
        color: #6e8efb !important; font-weight: 800 !important; font-size: 18px !important;
    }

    /* 하단 탐험 버튼 */
    div.stButton > button[key^="go_cal_"] {
        display: block !important; margin: 30px auto !important;     
        width: 300px !important; height: 80px !important;
        font-size: 24px !important; font-weight: 900 !important;
        color: #ffffff !important;
        background: linear-gradient(135deg, #6e8efb, #a777e3) !important;
        border: none !important; border-radius: 50px !important;
        box-shadow: 0px 10px 20px rgba(110, 142, 251, 0.4) !important;
        transition: all 0.3s ease !important;
    }
    
    .sector-tag {
        background-color: #f0f3ff; color: #5c67f2; padding: 2px 10px;
        border-radius: 4px; font-size: 11px; font-weight: 700;
    }
    </style>
""", unsafe_allow_html=True)

# 세션 상태 초기화
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"
for key in ['auth_status', 'page', 'swipe_idx', 'selected_stock']:
    if key not in st.session_state:
        st.session_state[key] = None if key in ['auth_status', 'selected_stock'] else ('stats' if key == 'page' else 0)

# 데이터 호출 함수
@st.cache_data(ttl=600)
def get_ipo_data(api_key, days_ahead):
    today_str = datetime.now().strftime('%Y-%m-%d')
    future_limit_str = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    params = {'from': today_str, 'to': future_limit_str, 'token': api_key}
    try:
        response = requests.get(base_url, params=params).json()
        if 'ipoCalendar' in response:
            df = pd.DataFrame(response['ipoCalendar'])
            return df[df['name'].notna() & (df['name'] != '')]
        return pd.DataFrame()
    except: return pd.DataFrame()

# ==========================================
# 🚀 화면 1: 로그인
# ==========================================
if st.session_state.auth_status is None:
    st.write("<div style='text-align: center; margin-top: 80px;'><h1>🦄 Unicornfinder</h1><p>성공적인 IPO 투자의 시작</p></div>", unsafe_allow_html=True)
    st.divider()
    _, col_m, _ = st.columns([1, 1.5, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000")
        if st.button("시작하기", use_container_width=True):
            if len(phone) > 9: st.session_state.auth_status = 'user'; st.rerun()
    st.stop()

# ==========================================
# 🚀 화면 2: 시장 분석 (타이틀/이모지 제거 및 간소화)
# ==========================================
if st.session_state.page == 'stats':
    # 상단 이모지/Unicornfinder 제목 삭제
    
    stages = [
        {"name": "유아기 유니콘", "img": "baby_unicorn.png", "avg_count": "연평균 180개", "survival_time": "약 1.5년", "survival_rate": "45%", "desc": "상장 0~2년차: 폭발적인 잠재력과 변동성이 공존하는 시기"},
        {"name": "아동기 유니콘", "img": "child_unicorn.png", "avg_count": "연평균 120개", "survival_time": "약 4년", "survival_rate": "65%", "desc": "상장 3~5년차: 비즈니스 모델이 시장에 안착하는 시기"},
        {"name": "성인기 유니콘", "img": "adult_unicorn.png", "avg_count": "연평균 85개", "survival_time": "약 12년", "survival_rate": "88%", "desc": "상장 6~15년차: 안정적인 이익 구조와 배당을 고민하는 시기"},
        {"name": "노년기 유니콘", "img": "old_unicorn.png", "avg_count": "연평균 40개", "survival_time": "25년 이상", "survival_rate": "95%", "desc": "상장 20년 이상: S&P 500을 이끄는 시장의 거인들"}
    ]
    idx = st.session_state.swipe_idx
    stage = stages[idx]
    
    # 1. 단계 제목만 크게 표시
    st.markdown(f"<div class='stage-title'>{stage['name']}</div>", unsafe_allow_html=True)
    
    # 2. 이미지 슬라이더 영역
    _, b1, ci, b2, _ = st.columns([1, 0.4, 2, 0.4, 1])
    with b1: st.write("<br><br><br><br>", unsafe_allow_html=True); n1 = st.button("◀", key="p_btn")
    with ci:
        if os.path.exists(stage['img']): st.image(Image.open(stage['img']), use_container_width=True)
        else: st.info(f"[{stage['name']} 캐릭터 이미지]")
    with b2: st.write("<br><br><br><br>", unsafe_allow_html=True); n2 = st.button("▶", key="n_btn")
    
    if n1: st.session_state.swipe_idx = (idx-1)%4; st.rerun()
    if n2: st.session_state.swipe_idx = (idx+1)%4; st.rerun()

    # 3. 핵심 수치 박스
    c1, c2, c3 = st.columns(3)
    with c1: st.markdown(f"<div class='stats-box'><div class='stats-label'>평균 상장 개수</div><div class='stats-value'>{stage['avg_count']}</div></div>", unsafe_allow_html=True)
    with c2: st.markdown(f"<div class='stats-box'><div class='stats-label'>평균 생존 기간</div><div class='stats-value'>{stage['survival_time']}</div></div>", unsafe_allow_html=True)
    with c3: st.markdown(f"<div class='stats-box'><div class='stats-label'>기업 생존율</div><div class='stats-value'>{stage['survival_rate']}</div></div>", unsafe_allow_html=True)
    
    st.markdown(f"<p style='text-align: center; margin-top: 25px; font-size: 18px; color: #555;'>{stage['desc']}</p>", unsafe_allow_html=True)

    # 4. 탐험 버튼 (유아기/아동기 구분)
    if "유아기" in stage['name']:
        if st.button("상장 캘린더 탐험하기", key="go_cal_baby"): st.session_state.page = 'calendar'; st.rerun()
    elif "아동기" in stage['name']:
        if st.button("성장 지표 분석하기", key="go_cal_child"): st.session_state.page = 'growth_stats'; st.rerun()

# ==========================================
# 🚀 이후 페이지 (캘린더, 상세분석 등 기존 코드 유지)
# ==========================================
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    df = get_ipo_data(MY_API_KEY, 60)
    if not df.empty:
        st.header("🚀 상장 예정 기업")
        # (기존의 캘린더 렌더링 로직...)
        for i, row in df.iterrows():
             if st.button(row['name'], key=f"name_{i}"):
                 st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()
