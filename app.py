import streamlit as st
import pandas as pd
from utils.db_helper import get_daily_signal_counts, get_upcoming_ipo_teaser

# [1] 페이지 설정
st.set_page_config(page_title="UnicornFinder", layout="wide", page_icon="🦄")

# [2] 언어 세션 초기화
if 'lang' not in st.session_state:
    st.session_state.lang = 'ko'

# 커스텀 CSS: 대형 타이틀 및 레드 & 화이트 테마
st.markdown("""
    <style>
    .main { background-color: #FFFFFF; }
    /* 메인 간판 타이틀 */
    .hero-title { 
        color: #FF0000; 
        font-size: 6rem; /* 크기 대폭 확대 */
        font-weight: 900; 
        margin-bottom: 0px; 
        text-align: center; 
        font-family: 'Arial Black', sans-serif;
        line-height: 1;
    }
    .hero-sub { 
        color: #FF0000; 
        font-size: 2.2rem; /* 크기 대폭 확대 */
        font-weight: 600; 
        margin-top: 10px; 
        text-align: center; 
    }
    
    /* 알림 카드 스타일 */
    .stat-card {
        padding: 20px; 
        border-radius: 12px; 
        background: #FFFFFF; 
        border: 1px solid #FFEEEE; 
        border-left: 6px solid #FF0000;
        text-align: center;
        margin-bottom: 15px;
        box-shadow: 0 4px 10px rgba(255, 0, 0, 0.02);
    }
    
    /* 상장 예정 기업 카드 */
    .ipo-card {
        background-color: #FFFFFF;
        border: 1px solid #F0F0F0;
        border-top: 5px solid #FF0000;
        border-radius: 12px;
        padding: 25px 15px;
        text-align: center;
        box-shadow: 0 6px 15px rgba(0,0,0,0.05);
    }
    .ticker-name { font-size: 2.2rem; font-weight: 900; color: #000; }
    .corp-name { font-size: 1rem; color: #666; margin-bottom: 15px; height: 45px; overflow: hidden; font-weight: 500; }
    .spec-val { font-size: 1.2rem; font-weight: 700; color: #333; margin: 4px 0; }
    .rating-text { font-size: 0.9rem; color: #FF0000; font-weight: 700; margin-top: 15px; border-top: 1px solid #EEE; padding-top: 10px; }
    </style>
""", unsafe_allow_html=True)

# 상단 언어 선택 버튼
lang_cols = st.columns([8, 1, 1, 1, 1])
with lang_cols[1]: 
    if st.button("🇰🇷"): st.session_state.lang = 'ko'; st.rerun()
with lang_cols[2]: 
    if st.button("🇺🇸"): st.session_state.lang = 'en'; st.rerun()
with lang_cols[3]: 
    if st.button("🇯🇵"): st.session_state.lang = 'ja'; st.rerun()
with lang_cols[4]: 
    if st.button("🇨🇳"): st.session_state.lang = 'zh'; st.rerun()

L = st.session_state.lang

# [3] Hero Section (초대형 간판)
st.markdown('<p class="hero-title">Unicornfinder</p>', unsafe_allow_html=True)
st.markdown('<p class="hero-sub">Find your unicorn with Unicornfinder</p>', unsafe_allow_html=True)
st.write("<br><br>", unsafe_allow_html=True)

# [4] 실시간 데이터 생산 현황 (12종 전체 공개)
counts = get_daily_signal_counts()

# worker.py 기반 모든 시그널 종류 정의
SIGNAL_LABELS = {
    # 주가 시그널
    "SURGE_IPO": {"ko": "🚀 공모가 대비 20% 급등", "en": "🚀 20% IPO Surge", "ja": "🚀 公募価格比20%急騰", "zh": "🚀 较发行价大涨20%"},
    "SURGE_1D": {"ko": "📈 당일 12% 이상 급등", "en": "📈 12%+ Daily Surge", "ja": "📈 当日12%以上急騰", "zh": "📈 当日大涨12%"},
    "REBOUND": {"ko": "⚓ 바닥 탈출 시그널", "en": "⚓ Rebound Signal", "ja": "⚓ 底打ち反発シグナル", "zh": "⚓ 触底 반발 信号"},
    "INST_UPGRADE": {"ko": "🎯 기관 강력매수 추천", "en": "🎯 Strong Buy Ratings", "ja": "🎯 機関の強力買い推奨", "zh": "🎯 机构强力买入"},
    "LOCKUP": {"ko": "🔔 보호예수 해제 주의보", "en": "🔔 Lock-up Expiry", "ja": "🔔 ロックアップ解除通知", "zh": "🔔 解禁提示"},
    # AI 리포트
    "8K_UPDATE": {"ko": "🚨 8-K 중대공시 분석", "en": "🚨 8-K Critical Analysis", "ja": "🚨 8-K重要開示分析", "zh": "🚨 8-K重大公告分析"},
    "EarningsCall": {"ko": "🎙️ 어닝콜 실시간 요약", "en": "🎙️ Earnings Call Recap", "ja": "🎙️ 決算電話会議要約", "zh": "🎙️ 财报电话会议摘要"},
    "EarningsSurprise": {"ko": "📊 어닝 서프라이즈 추적", "en": "📊 Earnings Surprises", "ja": "📊 サプライズ追跡", "zh": "📊 业绩超预期追踪"},
    "SmartMoney": {"ko": "🐋 스마트머니 자금 추적", "en": "🐋 Smart Money Flow", "ja": "🐋 資金追跡レポート", "zh": "🐋 聪明钱流向追踪"},
    "AnalystEstimates": {"ko": "📈 실적 전망치 갱신", "en": "📈 Analyst Estimates", "ja": "📈 業績予想の更新", "zh": "📈 业绩预期更新"},
    "Upgrades": {"ko": "🎯 투자의견 변화 추이", "en": "🎯 Rating History", "ja": "🎯 投資意見変更履歴", "zh": "🎯 投资评级变动"},
    "ESGRating": {"ko": "🌱 ESG 리스크 평가", "en": "🌱 ESG Risk Ratings", "ja": "🌱 ESG評価レポート", "zh": "🌱 ESG风险评级"}
}

st.subheader("📡 Live Intelligence Production" if L!='ko' else "📡 오늘의 실시간 프리미엄 데이터 생산 현황")
rows = [list(SIGNAL_LABELS.keys())[i:i+4] for i in range(0, len(SIGNAL_LABELS), 4)]

for row_keys in rows:
    cols = st.columns(4)
    for i, key in enumerate(row_keys):
        val = counts.get(key, 0)
        with cols[i]:
            st.markdown(f"""
                <div class="stat-card">
                    <div style="font-size:0.9rem; color:#666; font-weight:600;">{SIGNAL_LABELS[key][L]}</div>
                    <div style="font-size:1.8rem; font-weight:900; color:#FF0000;">{val}</div>
                </div>
            """, unsafe_allow_html=True)

st.write("---")

# [5] 상장 예정 기업 미리보기 (버튼 제거 버전)
st.subheader("🚀 Upcoming IPO Preview" if L!='ko' else "🚀 상장 예정 기업 미리보기 (30일 이내)")
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
                    <div class="ticker-name">{row['symbol']}</div>
                    <div class="corp-name">{row['name']}</div>
                    <div class="spec-val" style="color:#FF0000;">{row['price']}</div>
                    <div class="spec-val">{total_offering}</div>
                    <div class="spec-val" style="font-size:0.95rem;">{row['exchange']}</div>
                    <div class="spec-val" style="font-size:0.95rem; color:#888;">{row['date']}</div>
                    <div class="rating-text">
                        Analyst: Moderate Buy<br>
                        Scoop Score: 3/5
                    </div>
                </div>
            """, unsafe_allow_html=True)
else:
    st.info("데이터를 불러오는 중입니다.")

# [6] 하단 CTA (멤버십 표 없이 바로 앱 입장)
st.write("<br><br>", unsafe_allow_html=True)
col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
with col_btn2:
    if st.button("🚀 ENTER UNICORNFINDER APP", use_container_width=True, type="primary"):
        st.switch_page("pages/01_App.py")

st.markdown("<p style='text-align: center; color: #888; font-size: 0.8rem; margin-top: 50px;'>© 2026 UnicornFinder. All rights reserved.</p>", unsafe_allow_html=True)
