import streamlit as st
import pandas as pd
from utils.db_helper import get_daily_signal_counts, get_upcoming_ipo_teaser

# [1] 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# [2] 언어 세션 초기화 (상세 페이지에서 사용됨)
if 'lang' not in st.session_state:
    st.session_state.lang = 'ko'

# 커스텀 CSS: !important를 사용하여 시스템 스타일을 무시하고 강제 적용
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
        background-color: #FFFFFF;
    }
    
    /* 초대형 브랜드 간판 - !important로 크기 강제 고정 */
    .hero-title { 
        color: #FF0000 !important; 
        font-size: 8rem !important; /* 7rem에서 더 키움 */
        font-weight: 900 !important; 
        text-align: center !important; 
        letter-spacing: -4px !important;
        margin-top: 60px !important;
        margin-bottom: 90px !important;
        line-height: 0.8 !important;
        display: block !important;
    }
    
    /* 텍스트 스타일 통일 (15px) */
    .standard-text {
        font-size: 15px !important;
        color: #555555 !important;
        line-height: 1.5 !important;
    }
    
    .bold-black {
        font-weight: 700 !important;
        color: #000000 !important;
    }
    
    .count-zero {
        color: #BBBBBB !important;
        font-weight: 400 !important;
        font-size: 18px !important;
    }
    
    .count-active {
        color: #000000 !important;
        font-weight: 800 !important;
        font-size: 18px !important;
    }

    /* 상장 예정 기업 카드 */
    .ipo-card {
        background-color: #FFFFFF;
        border: 1px solid #E0E0E0;
        border-radius: 8px;
        padding: 20px;
        text-align: center;
        min-height: 250px;
    }
    
    /* 데이터 생산 현황 박스 */
    .stat-box {
        padding: 15px;
        border-bottom: 1px solid #F0F0F0;
        text-align: left;
    }

    /* 버튼 스타일 조정 */
    div.stButton > button {
        border-radius: 5px;
    }
    </style>
""", unsafe_allow_html=True)

# [3] 언어 선택기 (UI는 영어로 고정, 내부 변수만 변경)
lang_cols = st.columns([8, 0.5, 0.5, 0.5, 0.5])
with lang_cols[1]: 
    if st.button("🇰🇷"): st.session_state.lang = 'ko'; st.toast("App language set to Korean")
with lang_cols[2]: 
    if st.button("🇺🇸"): st.session_state.lang = 'en'; st.toast("App language set to English")
with lang_cols[3]: 
    if st.button("🇯🇵"): st.session_state.lang = 'ja'; st.toast("App language set to Japanese")
with lang_cols[4]: 
    if st.button("🇨🇳"): st.session_state.lang = 'zh'; st.toast("App language set to Chinese")

# [4] Hero Section (초대형 간판)
st.markdown('<h1 class="hero-title">Unicornfinder</h1>', unsafe_allow_html=True)

# [5] REAL-TIME PREMIUM ALERTS
st.markdown('<p class="bold-black" style="font-size: 20px; margin-bottom: 20px;">REAL-TIME PREMIUM ALERTS</p>', unsafe_allow_html=True)
counts = get_daily_signal_counts()

SIGNAL_LABELS_EN = {
    "SURGE_IPO": "IPO Price 20% Surge",
    "SURGE_1D": "Daily 12%+ Surge",
    "REBOUND": "Bottom Rebound Signal",
    "INST_UPGRADE": "Institutional Strong Buy",
    "LOCKUP": "Lock-up Expiry Alert",
    "8K_UPDATE": "8-K Critical Event Analysis",
    "EarningsCall": "Earnings Call Recap",
    "EarningsSurprise": "Earnings Surprise Detection",
    "SmartMoney": "Smart Money Tracking",
    "AnalystEstimates": "Analyst Estimates Revision",
    "Upgrades": "Rating History Tracking",
    "ESGRating": "ESG Risk Assessment"
}

rows = [list(SIGNAL_LABELS_EN.keys())[i:i+4] for i in range(0, len(SIGNAL_LABELS_EN), 4)]
for row_keys in rows:
    cols = st.columns(4)
    for i, key in enumerate(row_keys):
        val = counts.get(key, 0)
        count_style = "count-active" if val > 0 else "count-zero"
        with cols[i]:
            st.markdown(f"""
                <div class="stat-box">
                    <div class="bold-black" style="font-size: 15px;">{SIGNAL_LABELS_EN[key]}</div>
                    <div class="{count_style}">{val}</div>
                </div>
            """, unsafe_allow_html=True)

st.write("<br><br>", unsafe_allow_html=True)

# [6] Upcoming IPO Preview
st.markdown('<p class="bold-black" style="font-size: 20px; margin-bottom: 20px;">UPCOMING IPO PREVIEW (30D)</p>', unsafe_allow_html=True)
df_teaser = get_upcoming_ipo_teaser()

if not df_teaser.empty:
    t_cols = st.columns(5)
    for i, (_, row) in enumerate(df_teaser.iterrows()):
        if i >= 5: break
        
        try:
            shares = float(row.get('numberOfShares', 0))
            price_low = float(str(row.get('price', '0')).replace('$','').split('-')[0])
            total_offering = f"${(shares * price_low / 1000000):,.1f}M"
        except: total_offering = "TBD"

        with t_cols[i]:
            st.markdown(f"""
                <div class="ipo-card">
                    <div class="bold-black" style="font-size: 20px; margin-bottom: 5px;">{row['symbol']}</div>
                    <div class="standard-text" style="height: 40px; margin-bottom: 10px;">{row['name']}</div>
                    <div class="standard-text">{row['price']}</div>
                    <div class="standard-text">{total_offering}</div>
                    <div class="standard-text">{row['exchange']}</div>
                    <div class="standard-text" style="margin-bottom: 15px;">{row['date']}</div>
                    <div style="text-align: left; padding-top: 10px; border-top: 1px solid #EEE;">
                        <div class="standard-text"><span class="bold-black">Analyst: Moderate Buy</span></div>
                        <div class="standard-text"><span class="bold-black">Scoop Score: 3/5</span></div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
else:
    st.info("Syncing upcoming IPO data from SEC EDGAR...")

# [7] 통합 접속 섹션 (Login / Guest / Sign Up)
st.markdown('<p class="bold-black" style="font-size: 20px; margin-bottom: 20px;">GET STARTED</p>', unsafe_allow_html=True)

col_left, col_mid, col_right = st.columns([1, 2, 1])

with col_mid:
    # 탭 기능을 사용하여 깔끔하게 분리
    auth_tabs = st.tabs(["Login", "Explore as Guest", "Sign Up"])
    
    # 1. Login 탭
    with auth_tabs[0]:
        with st.form("login_form"):
            l_id = st.text_input("User ID", placeholder="Enter your ID")
            l_pw = st.text_input("Password", type="password", placeholder="Enter your Password")
            submit_login = st.form_submit_button("SIGN IN", use_container_width=True)
            
            if submit_login:
                if l_id and l_pw:
                    # Supabase에서 유저 정보 확인
                    res = supabase.table("users").select("*").eq("id", l_id).execute()
                    if res.data and res.data[0]['pw'] == l_pw:
                        st.session_state.auth_status = 'user'
                        st.session_state.user_info = res.data[0]
                        st.success(f"Welcome back, {l_id}!")
                        st.switch_page("pages/01_App.py")
                    else:
                        st.error("Invalid ID or Password.")
                else:
                    st.warning("Please fill in all fields.")

    # 2. Explore as Guest 탭
    with auth_tabs[1]:
        st.info("You can view all financial reports and community posts. Posting/Voting will be restricted.")
        if st.button("ENTER AS GUEST (VIEW ONLY)", use_container_width=True, type="primary"):
            st.session_state.auth_status = 'guest'
            st.session_state.user_info = {'id': 'Guest', 'role': 'guest'}
            st.switch_page("pages/01_App.py")

    # 3. Sign Up 탭 (안내)
    with auth_tabs[2]:
        st.write("Join Unicornfinder to get personalized alerts and full access.")
        if st.button("CREATE NEW ACCOUNT", use_container_width=True):
            st.info("Registration flow is currently being optimized. Please explore as a Guest first!")

st.markdown("<p style='text-align: center; color: #BBB; font-size: 13px; margin-top: 80px;'>© 2026 Unicornfinder. Global Institutional-Grade AI Intelligence.</p>", unsafe_allow_html=True)
