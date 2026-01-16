import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- CSS 스타일: 버튼, 카드 디자인, 하단 푸터 ---
st.markdown("""
    <style>
    /* 하단 고정 푸터 스타일 */
    .footer {
        position: fixed; left: 0; bottom: 0; width: 100%;
        background-color: white; color: #888888; text-align: center;
        padding: 10px; font-size: 11px; border-top: 1px solid #eeeeee; z-index: 999;
    }
    /* 탐험 버튼 스타일 (3D) */
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
    /* 화살표 버튼 스타일 */
    div.stButton > button[key^="p_"], div.stButton > button[key^="n_"] {
        font-size: 50px !important; font-weight: 900 !important;
        padding: 0px !important; border-radius: 12px !important;
        width: 100% !important; height: 85px !important;
        background-color: #ffffff !important; border: 3px solid #6e8efb !important;
        color: #6e8efb !important; box-shadow: 0px 5px 0px #6e8efb !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
    }
    /* 리스트 내 상세보기 버튼 */
    div.stButton > button[key^="btn_"] {
        background-color: #ffffff !important; color: #6e8efb !important;
        border: 1px solid #6e8efb !important; font-weight: bold !important;
        height: 35px !important; line-height: 1 !important;
    }
    .card-text {
        text-align: center; font-size: 1.3rem; padding: 25px;
        background-color: #f8f9fa; border-radius: 20px;
        margin-top: 15px; color: #333; border: 1px solid #eee;
    }
    </style>
""", unsafe_allow_html=True)

# API 키 및 세션 설정
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"
if 'auth_status' not in st.session_state: st.session_state.auth_status = None
if 'page' not in st.session_state: st.session_state.page = 'stats'
if 'swipe_idx' not in st.session_state: st.session_state.swipe_idx = 0

# --- 기능 1: 공통 푸터 ---
def show_footer():
    st.markdown("""
        <div class='footer'>
            본 서비스는 Finnhub API 데이터를 기반으로 하며, 로고에는 Clearbit API 등 외부 데이터를 활용하였습니다. 
            | 상세 수치는 공시 시점에 따라 차이가 있을 수 있습니다.
        </div>
    """, unsafe_allow_html=True)

# --- 기능 2: 상세 정보 팝업 다이얼로그 ---
@st.dialog("🚀 기업 상세 AI 분석")
def show_details(row):
    logo_url = f"https://logo.clearbit.com/{row['티커']}.com"
    col_l, col_r = st.columns([1, 4])
    with col_l:
        st.image(logo_url, width=80, fallback="https://via.placeholder.com/80?text=Logo")
    with col_r:
        st.subheader(f"{row['기업명']} ({row['티커']})")
        st.caption(f"{row['거래소']} 상장 예정 | 공모일: {row['공모일']}")

    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("희망가/공모가", row['희망가/공모가'])
    c2.metric("공모 규모", row['공모규모($)'])
    c3.metric("발행 주식수", f"{row['주식수']:,}")

    st.markdown("#### 🤖 AI 투자 요약 브리핑")
    st.info(f"""
    - **핵심 정보:** {row['기업명']}은(는) 이번 IPO를 통해 공격적인 시장 확장을 계획하고 있습니다.
    - **자금 활용:** 조달 자금은 주로 **{row['자금용도']}** 목적으로 사용될 예정입니다.
    - **투자 참고:** 주관사는 **{row['언더라이터']}**이며, 보호예수 기간은 약 **{row['보호예수']}**입니다.
    """)

    st.divider()
    b1, b2 = st.columns(2)
    b1.link_button("📄 SEC 공식 공시(S-1) 확인", row['공시'], use_container_width=True)
    b2.link_button("📊 Yahoo Finance 재무 지표", row['재무'], use_container_width=True)
    st.caption("ℹ️ 로고 데이터는 Clearbit API 기반이며 실제와 다를 수 있습니다.")

# --- 데이터 로직 ---
@st.cache_data(ttl=600)
def get_ipo_data(api_key, days_ahead):
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    params = {'from': (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'), 
              'to': (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d'), 'token': api_key}
    try:
        response = requests.get(base_url, params=params).json()
        return pd.DataFrame(response['ipoCalendar']) if 'ipoCalendar' in response else pd.DataFrame()
    except: return pd.DataFrame()

# ==========================================
# 화면 1: 로그인
# ==========================================
if st.session_state.auth_status is None:
    st.write("<div style='text-align: center; margin-top: 50px;'><h1>🦄 Unicornfinder</h1><h3>당신의 다음 유니콘을 찾아보세요</h3></div>", unsafe_allow_html=True)
    st.divider()
    _, col_m, _ = st.columns([1, 2, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000", key="phone_input")
        c1, c2 = st.columns(2)
        if c1.button("회원 로그인", use_container_width=True): 
            if len(phone) > 9: st.session_state.auth_status = 'user'; st.rerun()
        if c2.button("비회원 시작", use_container_width=True): st.session_state.auth_status = 'guest'; st.rerun()
    st.stop()

# ==========================================
# 화면 2: 시장 분석 카드
# ==========================================
if st.session_state.page == 'stats':
    st.title("🦄 Unicornfinder 분석")
    st.divider()
    stages = [
        {"name": "유아기", "img": "baby_unicorn.png", "desc": "상장 0~2년차 기업입니다."},
        {"name": "아동기", "img": "child_unicorn.png", "desc": "상장 3~5년차 기업입니다."},
        {"name": "성인기", "img": "adult_unicorn.png", "desc": "중견기업 단계입니다."},
        {"name": "노년기", "img": "old_unicorn.png", "desc": "대기업 단계입니다."}
    ]
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
    st.markdown(f"<div class='card-text'>{stage['desc']}</div>", unsafe_allow_html=True)
    if stage['name'] == "유아기":
        if st.button("탐험", key="go_cal_baby"): st.session_state.page = 'calendar'; st.rerun()

# ==========================================
# 화면 3: 캘린더 (안정적인 리스트 정렬 방식)
# ==========================================
elif st.session_state.page == 'calendar':
    st.sidebar.header("⚙️ 필터 설정")
    if st.sidebar.button("⬅️ 돌아가기"): st.session_state.page = 'stats'; st.rerun()
    days_ahead = st.sidebar.slider("조회 기간(일) 설정", 0, 60, 30, 5)

    st.header("🚀 실시간 유아기 유니콘 캘린더")
    df = get_ipo_data(MY_API_KEY, days_ahead)

    if not df.empty:
        # 데이터 가공
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df['numberOfShares'] = pd.to_numeric(df['numberOfShares'], errors='coerce')
        df['공모일'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        df['희망가/공모가'] = df['price'].apply(lambda x: f"${x:,.2f}" if x > 0 else "공시 확인(미정)")
        df['공모규모($)'] = (df['price'] * df['numberOfShares']).apply(lambda x: f"${x:,.0f}" if x > 0 else "계산 불가")
        
        # 필드 매핑
        df['자금용도'] = "운영 자금 및 전략적 투자"
        df['보호예수'] = "상장 후 180일"
        df['언더라이터'] = "주요 IB 주관사"
        df['공시'] = df['symbol'].apply(lambda x: f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={x}")
        df['재무'] = df['symbol'].apply(lambda x: f"https://finance.yahoo.com/quote/{x}/financials")
        
        result_df = df.sort_values(by='공모일')

        st.info("💡 각 기업 우측의 **상세보기** 버튼을 클릭하여 AI 분석 리포트를 확인하세요.")
        
        # 헤더 출력
        st.write("---")
        h1, h2, h3, h4 = st.columns([1, 2, 1, 0.8])
        h1.write("**📅 공모일**")
        h2.write("**🏢 기업명 (티커)**")
        h3.write("**💰 예상 가격**")
        h4.write("**🔍 분석**")
        st.write("---")

        # 리스트 출력 (버전 에러 없는 루프 방식)
        for i, row in result_df.iterrows():
            c1, c2, c3, c4 = st.columns([1, 2, 1, 0.8])
            c1.write(row['공모일'])
            c2.write(f"**{row['name']}** ({row['symbol']})")
            c3.write(row['희망가/공모가'])
            if c4.button("상세보기", key=f"btn_{row['symbol']}"):
                show_details(row)
            st.write("") # 가독성을 위한 줄바꿈 효과
            
    else:
        st.warning(f"최근 5일부터 향후 {days_ahead}일 사이에 예정된 IPO 데이터가 없습니다.")

    show_footer()
