import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- CSS 스타일: 3D 버튼, 카드 디자인, 고정 푸터 ---
st.markdown("""
    <style>
    /* 하단 고정 푸터 스타일 */
    .footer {
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        background-color: white;
        color: #888888;
        text-align: center;
        padding: 10px;
        font-size: 11px;
        border-top: 1px solid #eeeeee;
        z-index: 999;
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
    /* 화살표 버튼 스타일 */
    div.stButton > button[key^="p_"], div.stButton > button[key^="n_"] {
        font-size: 50px !important; font-weight: 900 !important;
        padding: 0px !important; border-radius: 12px !important;
        width: 100% !important; height: 85px !important;
        background-color: #ffffff !important; border: 3px solid #6e8efb !important;
        color: #6e8efb !important; box-shadow: 0px 5px 0px #6e8efb !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
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

# --- 기능 1: 공통 푸터 함수 ---
def show_footer():
    st.markdown("""
        <div class='footer'>
            본 서비스는 Finnhub API 데이터를 기반으로 하며, 기업 로고에는 Clearbit API 등 외부 무료 데이터를 활용하였습니다. 
            상세 수치는 공시 시점에 따라 차이가 있을 수 있습니다.
        </div>
    """, unsafe_allow_html=True)

# --- 기능 2: 상세 정보 팝업 다이얼로그 (로고 & AI 요약 포함) ---
@st.dialog("🚀 기업 상세 AI 분석")
def show_details(row):
    # Clearbit API를 이용한 로고 로드
    logo_url = f"https://logo.clearbit.com/{row['티커']}.com"
    
    col_l, col_r = st.columns([1, 4])
    with col_l:
        st.image(logo_url, width=80, fallback="https://via.placeholder.com/80?text=Logo")
    with col_r:
        st.subheader(f"{row['기업명']} ({row['티커']})")
        st.caption(f"{row['거래소']} 상장 예정 | 공모일: {row['공모일']}")

    st.divider()
    
    # 핵심 지표 섹션
    c1, c2, c3 = st.columns(3)
    c1.metric("예상 공모가", row['희망가/공모가'])
    c2.metric("공모 규모", row['공모규모($)'])
    c3.metric("발행 주식수", f"{row['주식수']:,}")

    # AI 요약 섹션
    st.markdown("#### 🤖 AI 투자 요약 브리핑")
    st.info(f"""
    - **핵심 정보:** {row['기업명']}은(는) 이번 IPO를 통해 성장을 가속화할 예정입니다.
    - **자금 활용:** 조달된 자금은 주로 **{row['자금용도']}** 목적으로 사용됩니다.
    - **주요 정보:** 보호예수 기간은 **{row['보호예수']}**이며, 주관사는 **{row['언더라이터']}**입니다.
    - **분석 의견:** 현재 표시된 가격이 '미정'인 경우 상장 직전 SEC 공시를 통해 확정 가액을 확인하시기 바랍니다.
    """)

    st.divider()
    st.markdown("#### 🔗 데이터 더 보기")
    b1, b2 = st.columns(2)
    b1.link_button("📄 SEC 공식 공시(S-1) 확인", row['공시'], use_container_width=True)
    b2.link_button("📊 Yahoo Finance 재무 지표", row['재무'], use_container_width=True)
    st.caption("ℹ️ 로고 데이터는 Clearbit API 기반이며 실제와 다를 수 있습니다.")

# --- 데이터 로직 ---
@st.cache_data(ttl=600)
def get_ipo_data(api_key, days_ahead):
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    params = {
        'from': (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'), 
        'to': (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d'), 
        'token': api_key
    }
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
# 화면 2: 시장 분석 카드 (Swipe)
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
        if st.button("탐험", key="go_cal_baby"):
            st.session_state.page = 'calendar'
            st.rerun()

# ==========================================
# 화면 3: 캘린더 (날짜 추가, 클릭 시 팝업 연동)
# ==========================================
elif st.session_state.page == 'calendar':
    st.sidebar.header("⚙️ 필터 설정")
    if st.sidebar.button("⬅️ 돌아가기"):
        st.session_state.page = 'stats'
        st.rerun()
    
    st.sidebar.divider()
    days_ahead = st.sidebar.slider("조회 기간(일) 설정", 0, 60, 30, 5)

    st.header("🚀 실시간 유아기 유니콘 캘린더")
    df = get_ipo_data(MY_API_KEY, days_ahead)

    if not df.empty:
        # 데이터 처리
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df['numberOfShares'] = pd.to_numeric(df['numberOfShares'], errors='coerce')
        df['공모일'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        
        # 가격 표시 로직 (0이거나 없으면 미정)
        def get_price_display(val):
            return f"${val:,.2f}" if pd.notna(val) and val > 0 else "공시 확인(미정)"
        df['희망가/공모가'] = df['price'].apply(get_price_display)
        
        # 공모규모 계산
        df['공모규모_num'] = df['price'] * df['numberOfShares']
        def get_deal_size_display(val):
            return f"${val:,.0f}" if pd.notna(val) and val > 0 else "계산 불가"
        df['공모규모($)'] = df['공모규모_num'].apply(get_deal_size_display)
        
        # 기타 고정 필드 매핑
        df['자금용도'] = "운영 자금 및 전략적 투자"
        df['보호예수'] = "상장 후 180일"
        df['언더라이터'] = "주요 IB 주관"
        df['공시'] = df['symbol'].apply(lambda x: f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={x}")
        df['재무'] = df['symbol'].apply(lambda x: f"https://finance.yahoo.com/quote/{x}/financials")
        
        # 테이블 컬럼 재구성 (공모일 맨 왼쪽)
        result_df = df[['공모일', 'name', 'symbol', '희망가/공모가', 'numberOfShares', '공모규모($)', '자금용도', '보호예수', '언더라이터', 'exchange', '공시', '재무']]
        result_df.columns = ['공모일', '기업명', '티커', '희망가/공모가', '주식수', '공모규모($)', '자금용도', '보호예수', '언더라이터', '거래소', '공시', '재무']
        result_df = result_df.sort_values(by='공모일')

        st.info("💡 **리스트의 행을 클릭**하면 상세 분석과 기업 로고가 나타납니다.")

        # 클릭 감지를 위한 데이터프레임 (on_select 사용)
        event = st.dataframe(
            result_df,
            column_config={
                "공시": None, "재무": None, "자금용도": None, "보호예수": None, "언더라이터": None,
                "주식수": st.column_config.NumberColumn(format="%d"),
            },
            hide_index=True,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single_row"
        )

        # 행 선택 시 다이얼로그 팝업 호출
        if len(event.selection.rows) > 0:
            selected_idx = event.selection.rows[0]
            show_details(result_df.iloc[selected_idx])
            
    else:
        st.warning(f"최근 5일부터 향후 {days_ahead}일 사이에 예정된 IPO 데이터가 없습니다.")

    # 하단 출처 표시
    show_footer()
