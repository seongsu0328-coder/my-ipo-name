import streamlit as st
import pandas as pd
import json
from utils.db_helper import get_daily_signal_counts, get_upcoming_ipo_teaser

# [1] 페이지 설정
st.set_page_config(page_title="UnicornFinder", layout="wide", page_icon="🦄")

# [2] 언어 세션 초기화
if 'lang' not in st.session_state:
    st.session_state.lang = 'ko'

# 커스텀 CSS: 레드 & 화이트 테마 및 카드 레이아웃
st.markdown("""
    <style>
    .main { background-color: #FFFFFF; }
    .hero-title { color: #FF0000; font-size: 3.2rem; font-weight: 900; margin-bottom: 0px; text-align: center; font-family: 'Arial Black'; }
    .hero-sub { color: #FF0000; font-size: 1.2rem; font-weight: 600; margin-top: -10px; text-align: center; }
    
    /* 병렬 카드 스타일 */
    .ipo-card {
        background-color: #FFFFFF;
        border: 1px solid #FFEEEE;
        border-top: 4px solid #FF0000;
        border-radius: 10px;
        padding: 20px;
        height: 100%;
        text-align: center;
        box-shadow: 0 4px 10px rgba(255, 0, 0, 0.03);
    }
    .ticker-name { font-size: 1.8rem; font-weight: 800; color: #000; margin-bottom: 0px; }
    .corp-name { font-size: 0.9rem; color: #666; margin-bottom: 15px; height: 40px; overflow: hidden; }
    .spec-value { font-size: 1.1rem; font-weight: 700; color: #333; margin: 5px 0; }
    .rating-box { font-size: 0.85rem; color: #FF0000; font-weight: 600; margin-top: 10px; padding-top: 10px; border-top: 1px solid #F0F0F0; }
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

# [3] Hero Section
st.markdown('<p class="hero-title">Unicornfinder</p>', unsafe_allow_html=True)
st.markdown('<p class="hero-sub">Find your unicorn with Unicornfinder</p>', unsafe_allow_html=True)
st.write("<br>", unsafe_allow_html=True)

# [4] 실시간 데이터 생산 현황 (세부 내역형)
counts = get_daily_signal_counts()
SIGNAL_LABELS = {
    "8K_UPDATE": {"ko": "🚨 8-K 중대공시 분석", "en": "🚨 8-K Analysis", "ja": "🚨 8-K重要開示", "zh": "🚨 8-K重大公告"},
    "EarningsCall": {"ko": "🎙️ 어닝콜 심층요약", "en": "🎙️ Earnings Summaries", "ja": "🎙️ 決算要約", "zh": "🎙️ 财报摘要"},
    "EarningsSurprise": {"ko": "📊 어닝 서프라이즈", "en": "📊 Surprises", "ja": "📊 サプライズ", "zh": "📊 业绩超预期"},
    "SmartMoney": {"ko": "🐋 스마트머니 추적", "en": "🐋 Smart Money", "ja": "🐋 資金追跡", "zh": "🐋 聪明钱追踪"},
    "SURGE_IPO": {"ko": "🚀 20% 급등 시그널", "en": "🚀 20% Surge", "ja": "🚀 20%急騰", "zh": "🚀 20%暴涨"},
    "AnalystEstimates": {"ko": "📈 실적 전망치 갱신", "en": "📈 Estimates", "ja": "📈 業績予想", "zh": "📈 业绩预期"}
}

if counts:
    st.subheader("📡 Today's Production" if L!='ko' else "📡 오늘의 실시간 데이터 생산 현황")
    cols = st.columns(len(SIGNAL_LABELS))
    for i, (key, labels) in enumerate(SIGNAL_LABELS.items()):
        val = counts.get(key, 0)
        if val > 0:
            with cols[i % len(cols)]:
                st.markdown(f"""<div style="text-align:center; padding:10px; background:#F8F9FA; border-radius:10px; border:1px solid #FFEEEE;">
                    <div style="font-size:0.8rem; color:#666;">{labels[L]}</div>
                    <div style="font-size:1.4rem; font-weight:bold; color:#FF0000;">{val}</div>
                </div>""", unsafe_allow_html=True)

st.write("---")

# [5] 상장 예정 기업 (가로 병렬 카드형)
st.subheader("🚀 Upcoming IPO Preview" if L!='ko' else "🚀 상장 예정 기업 미리보기 (30일 이내)")
df_teaser = get_upcoming_ipo_teaser()

if not df_teaser.empty:
    t_cols = st.columns(5) # 최대 5개 병렬 배치
    for i, (_, row) in enumerate(df_teaser.iterrows()):
        if i >= 5: break # 5개까지만 노출
        
        # 발행총액 계산
        try:
            shares = float(row.get('numberOfShares', 0))
            price_low = float(str(row.get('price', '0')).replace('$','').split('-')[0])
            total_offering = f"${(shares * price_low / 1000000):,.0f}M"
        except: total_offering = "TBD"

        with t_cols[i]:
            # 카드 내부 구성 (라벨 없이 값 위주)
            st.markdown(f"""
                <div class="ipo-card">
                    <div class="ticker-name">{row['symbol']}</div>
                    <div class="corp-name">{row['name']}</div>
                    <div class="spec-value" style="color:#FF0000;">{row['price']}</div>
                    <div class="spec-value">{total_offering}</div>
                    <div class="spec-value" style="font-size:0.9rem;">{row['exchange']}</div>
                    <div class="spec-value" style="font-size:0.9rem; color:#888;">{row['date']}</div>
                    <div class="rating-box">
                        🔍 Analyst: <span style="color:#333;">Moderate Buy</span><br>
                        ⭐ Scoop: <span style="color:#333;">3/5</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            if st.button("Details", key=f"go_{row['symbol']}", use_container_width=True):
                st.switch_page("pages/01_App.py")
else:
    st.info("상장 예정 정보 업데이트 중")

# [6] 멤버십 혜택 상세 비교표 (기획 확정안)
st.write("<br><br>", unsafe_allow_html=True)
st.subheader("💎 Membership Details" if L!='ko' else "💎 유니콘파인더 멤버십 혜택 상세 비교")

membership_data = {
    "분류": ["핵심 가치", "데이터 수준", "상세 데이터", "AI 엔진", "특화 기능", "투자 가이드", "핵심 서비스"],
    "Premium (1.2만)": [
        "Wall Street Pro Data",
        "표준 데이터 (90%)",
        "기관 지표, 목표가, 보도자료 분석",
        "AI 텍스트 요약",
        "❌ (분석 리포트만 제공)",
        "데이터 제공 및 리포트",
        "주요정보 요약본 제공"
    ],
    "Premium Plus (1.8만)": [
        "AI Investment Navigation",
        "상위 그룹 알파 메타데이터",
        "8-K, 어닝콜, 자금 흐름 추적",
        "동적 군집화 (CNN/RNN)",
        "우위집단 실시간 경로 추적",
        "[독점] 실시간 내비게이션",
        "소비패턴 & Z-score 알림"
    ]
}
st.table(pd.DataFrame(membership_data).set_index("분류"))

# [7] 하단 CTA
st.write("<br>", unsafe_allow_html=True)
if st.button("🚀 Enter UnicornFinder", use_container_width=True, type="primary"):
    st.switch_page("pages/01_App.py")

st.markdown("<p style='text-align: center; color: #888; font-size: 0.8rem; margin-top: 30px;'>© 2026 UnicornFinder. All rights reserved.</p>", unsafe_allow_html=True)
