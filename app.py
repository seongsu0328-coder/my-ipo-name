import streamlit as st
import pandas as pd
from utils.db_helper import get_daily_signal_counts, get_upcoming_ipo_teaser

# [1] 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# [2] 언어 세션 초기화 (상세 페이지에서 사용됨)
if 'lang' not in st.session_state:
    st.session_state.lang = 'ko'

# 커스텀 CSS: 글로벌 전문 금융 터미널 스타일
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
        background-color: #FFFFFF;
    }
    
    /* 초대형 브랜드 간판 */
    .hero-title { 
        color: #FF0000; 
        font-size: 7rem; 
        font-weight: 900; 
        text-align: center; 
        letter-spacing: -2px;
        margin-top: 50px;
        margin-bottom: 80px;
        line-height: 1;
    }
    
    /* 텍스트 스타일 통일 */
    .standard-text {
        font-size: 15px;
        color: #555555;
        line-height: 1.5;
    }
    
    .bold-black {
        font-weight: 700;
        color: #000000;
    }
    
    .count-zero {
        color: #BBBBBB;
        font-weight: 400;
    }
    
    .count-active {
        color: #000000;
        font-weight: 800;
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
    </style>
""", unsafe_allow_html=True)

# [3] 언어 선택기 (UI는 영어로 고정이지만, 내부 변수만 변경)
lang_cols = st.columns([8, 0.5, 0.5, 0.5, 0.5])
with lang_cols[1]: 
    if st.button("🇰🇷", help="Set App language to Korean"): st.session_state.lang = 'ko'; st.toast("Language set to Korean")
with lang_cols[2]: 
    if st.button("🇺🇸", help="Set App language to English"): st.session_state.lang = 'en'; st.toast("Language set to English")
with lang_cols[3]: 
    if st.button("🇯🇵", help="Set App language to Japanese"): st.session_state.lang = 'ja'; st.toast("Language set to Japanese")
with lang_cols[4]: 
    if st.button("🇨🇳", help="Set App language to Chinese"): st.session_state.lang = 'zh'; st.toast("Language set to Chinese")

# [4] Hero Section (English Only)
st.markdown('<p class="hero-title">Unicornfinder</p>', unsafe_allow_html=True)

# [5] REAL-TIME PREMIUM ALERTS (English Only)
st.markdown('<p class="bold-black" style="font-size: 20px; margin-bottom: 20px;">LIVE INTELLIGENCE PRODUCTION</p>', unsafe_allow_html=True)
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

# 4개씩 배치
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
                    <div class="{count_style}" style="font-size: 18px;">{val}</div>
                </div>
            """, unsafe_allow_html=True)

st.write("<br><br>", unsafe_allow_html=True)

# [6] Upcoming IPO Preview (English Only)
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

# [7] CTA Section
st.write("<br><br>", unsafe_allow_html=True)
col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
with col_btn2:
    if st.button("ENTER UNICORNFINDER APP", use_container_width=True, type="primary"):
        st.switch_page("pages/01_App.py")

st.markdown("<p style='text-align: center; color: #BBB; font-size: 13px; margin-top: 80px;'>© 2026 Unicornfinder. Global Institutional-Grade AI Intelligence.</p>", unsafe_allow_html=True)
