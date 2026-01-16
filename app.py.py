import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- CSS 스타일: 3D 텍스트 디자인 및 레이아웃 ---
st.markdown("""
    <style>
    .footer {
        position: fixed; left: 0; bottom: 0; width: 100%;
        background-color: white; color: #888888; text-align: center;
        padding: 10px; font-size: 11px; border-top: 1px solid #eeeeee; z-index: 999;
    }
    /* 3페이지 기업명: 3D 효과, 아주 굵게, 테두리 제거 */
    div.stButton > button[key^="name_"] {
        background-color: transparent !important;
        border: none !important;
        color: #6e8efb !important;
        font-weight: 900 !important;
        font-size: 18px !important;
        text-align: left !important;
        padding: 0 !important;
        text-shadow: 1px 1px 0px #eeeeee, 2px 2px 0px #dddddd, 3px 3px 2px rgba(0,0,0,0.15) !important;
        box-shadow: none !important;
        transition: all 0.2s ease;
    }
    div.stButton > button[key^="name_"]:hover {
        color: #a777e3 !important;
        transform: translateY(-2px);
    }
    /* 탐험 버튼 스타일 */
    div.stButton > button[key="go_cal_baby"] {
        display: block !important; margin: 20px auto !important;     
        width: 260px !important; height: 85px !important;
        font-size: 32px !important; font-weight: 900 !important;
        color: #ffffff !important;
        background: linear-gradient(145deg, #6e8efb, #a777e3) !important;
        border: none !important; border-radius: 20px !important;
        text-shadow: 2px 2px 0px #4a69bd !important;
        box-shadow: 0px 8px 0px #3c569b, 0px 15px 20px rgba(0,0,0,0.3) !important;
    }
    /* 상태 표시 텍스트 스타일 */
    .status-pending {
        color: #ff4b4b; font-weight: bold; font-size: 14px;
    }
    </style>
""", unsafe_allow_html=True)

# API 키 및 세션 설정
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"
for key in ['auth_status', 'page', 'swipe_idx', 'selected_stock']:
    if key not in st.session_state:
        st.session_state[key] = None if key in ['auth_status', 'selected_stock'] else ('stats' if key == 'page' else 0)

# 데이터 로직
@st.cache_data(ttl=600)
def get_ipo_data(api_key, days_ahead):
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    params = {'from': (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d'), 
              'to': (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d'), 'token': api_key}
    try:
        response = requests.get(base_url, params=params).json()
        return pd.DataFrame(response['ipoCalendar']) if 'ipoCalendar' in response else pd.DataFrame()
    except: return pd.DataFrame()

# --- 화면 1: 로그인 ---
if st.session_state.auth_status is None:
    st.write("<div style='text-align: center; margin-top: 50px;'><h1>🦄 Unicornfinder</h1><h3>당신의 다음 유니콘을 찾아보세요</h3></div>", unsafe_allow_html=True)
    st.divider()
    _, col_m, _ = st.columns([1, 2, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000", key="login_phone")
        c1, c2 = st.columns(2)
        if c1.button("회원 로그인", use_container_width=True): 
            if len(phone) > 9: st.session_state.auth_status = 'user'; st.rerun()
        if c2.button("비회원 시작", use_container_width=True): st.session_state.auth_status = 'guest'; st.rerun()
    st.stop()

# --- 화면 2: 카드 분석 ---
if st.session_state.page == 'stats':
    st.title("🦄 Unicornfinder 분석")
    stages = [{"name": "유아기", "img": "baby_unicorn.png", "desc": "상장 0~2년차 기업입니다."}, {"name": "아동기", "img": "child_unicorn.png", "desc": "상장 3~5년차 기업입니다."}, {"name": "성인기", "img": "adult_unicorn.png", "desc": "중견기업 단계입니다."}, {"name": "노년기", "img": "old_unicorn.png", "desc": "대기업 단계입니다."}]
    idx = st.session_state.swipe_idx
    stage = stages[idx]
    st.markdown(f"<h2 style='text-align: center; color: #6e8efb;'>{stage['name']} 유니콘</h2>", unsafe_allow_html=True)
    _, ci, _ = st.columns([1, 2, 1])
    with ci:
        if os.path.exists(stage['img']): st.image(Image.open(stage['img']), use_container_width=True)
        else: st.info(f"[{stage['name']} 이미지 준비 중]")
    _, n1, n2, _ = st.columns([1.8, 0.7, 0.7, 1.8])
    if n1.button("◀", key=f"p_{idx}"): st.session_state.swipe_idx = (idx-1)%4; st.rerun()
    if n2.button("▶", key=f"n_{idx}"): st.session_state.swipe_idx = (idx+1)%4; st.rerun()
    if stage['name'] == "유아기":
        if st.button("탐험", key="go_cal_baby"): st.session_state.page = 'calendar'; st.rerun()

# --- 화면 3: 캘린더 (상태 표시 로직 추가) ---
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    st.header("🚀 실시간 유아기 유니콘 캘린더")
    df = get_ipo_data(MY_API_KEY, 30)

    if not df.empty:
        # 데이터 수치화 및 전처리
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df['numberOfShares'] = pd.to_numeric(df['numberOfShares'], errors='coerce')
        df['공모일'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        
        result_df = df.sort_values(by='공모일', ascending=False).reset_index(drop=True)

        st.write("---")
        c1, c2, c3, c4, c5 = st.columns([1.2, 2.5, 0.8, 1.2, 1.8])
        c1.write("**공모일**"); c2.write("**기업명**"); c3.write("**티커**"); c4.write("**희망가**"); c5.write("**상태 및 규모**")
        st.write("---")

        for i, row in result_df.iterrows():
            col1, col2, col3, col4, col5 = st.columns([1.2, 2.5, 0.8, 1.2, 1.8])
            
            # 1. 공모일
            col1.write(row['공모일'])
            
            # 2. 기업명 (3D 효과 버튼)
            if col2.button(row['name'], key=f"name_{row['symbol']}_{i}"):
                st.session_state.selected_stock = row
                st.session_state.page = 'detail'
                st.rerun()
            
            # 3. 티커
            col3.write(row['symbol'])
            
            # 4. 희망가
            price_val = row['price']
            col4.write(f"${price_val:,.2f}" if pd.notna(price_val) and price_val > 0 else "미정")
            
            # 5. 상태 및 규모 (핵심 수정 부분)
            shares = row['numberOfShares']
            if pd.isna(price_val) or pd.isna(shares) or price_val <= 0 or shares <= 0:
                col5.markdown("<span class='status-pending'>⚠️ 상장 보류 및 공시 대기</span>", unsafe_allow_html=True)
            else:
                total_scale = price_val * shares
                col5.write(f"${total_scale:,.0f}")
    else:
        st.warning("조회된 IPO 데이터가 없습니다.")

# --- 화면 4: 상세 분석 ---
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()

    st.title(f"🚀 {stock['name']} 상세 분석")
    col_l, col_r = st.columns([1, 3])
    with col_l:
        logo_url = f"https://logo.clearbit.com/{stock['symbol']}.com"
        try: st.image(logo_url, width=150)
        except: st.info("로고 준비 중")
    with col_r:
        st.subheader(f"{stock['name']} ({stock['symbol']})")
        st.write(f"**상장일:** {stock['공모일']}")
        st.divider()
        m1, m2 = st.columns(2)
        p = stock['price']
        s = stock['numberOfShares']
        m1.metric("희망가", f"${p:,.2f}" if pd.notna(p) and p > 0 else "미정")
        m2.metric("공모 규모", f"${(p*s):,.0f}" if pd.notna(p) and pd.notna(s) and p*s > 0 else "계산 불가")

    st.divider()
    st.info("💡 해당 기업은 현재 시장 상황에 따라 일정이 변동되거나 데이터 업데이트가 지연될 수 있습니다. 정확한 내용은 아래 SEC 공시 링크를 참조하세요.")
    st.link_button("📄 SEC 공식 공시(S-1) 확인", f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={stock['symbol']}", use_container_width=True)
