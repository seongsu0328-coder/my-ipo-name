import streamlit as st
import pandas as pd
import json
from utils.db_helper import get_daily_signal_counts, get_upcoming_ipo_teaser

# [1] 페이지 설정
st.set_page_config(page_title="UnicornFinder", layout="wide", page_icon="🦄")

# [2] 언어 세션 초기화 및 선택
if 'lang' not in st.session_state:
    st.session_state.lang = 'ko'

# 커스텀 CSS: 하얀 바탕, 빨간 글씨 테마 및 배너 스타일
st.markdown("""
    <style>
    .main { background-color: #FFFFFF; }
    .hero-title { color: #FF0000; font-size: 4rem; font-weight: 900; margin-bottom: 0px; text-align: center; }
    .hero-sub { color: #FF0000; font-size: 1.5rem; font-weight: 600; margin-top: 0px; text-align: center; }
    .stMetric { background-color: #F8F9FA; padding: 15px; border-radius: 10px; border: 1px solid #FFEEEE; }
    div[data-testid="stExpander"] { border: 1px solid #FFEEEE !important; }
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

# [3] 다국어 텍스트 사전
UI_TEXT = {
    "live_title": {"ko": "📡 오늘의 실시간 데이터 생산 현황", "en": "📡 Today's Live Production", "ja": "📡 本日のデータ生産状況", "zh": "📡 今日实时数据生产"},
    "upcoming_title": {"ko": "🚀 상장 예정 기업 미리보기 (30일 이내)", "en": "🚀 Upcoming IPO Preview", "ja": "🚀 上場予定プレビュー", "zh": "🚀 上市预告"},
    "membership_title": {"ko": "💎 유니콘파인더 멤버십 혜택 상세 비교", "en": "💎 Membership Benefits", "ja": "💎 メンバーシップ特典比較", "zh": "💎 会员权益对比"},
    "cta_btn": {"ko": "🚀 유니콘 파인더 앱 입장하기 (무료 시작)", "en": "🚀 Enter App (Start Free)", "ja": "🚀 アプリに入場", "zh": "🚀 进入应用"},
    "item_unit": {"ko": "개", "en": "items", "ja": "個", "zh": "个"}
}

# 세부 시그널 라벨 (요청하신 대로 세부 내역으로 노출)
SIGNAL_LABELS = {
    "8K_UPDATE": {"ko": "🚨 중대 공시 분석 (8-K)", "en": "🚨 8-K Critical Analysis", "ja": "🚨 重大開示分析 (8-K)", "zh": "🚨 重大公告分析 (8-K)"},
    "EarningsCall": {"ko": "🎙️ 어닝 콜 심층 요약", "en": "🎙️ Earnings Call Summary", "ja": "🎙️ アーニングコール要約", "zh": "🎙️ 财报电话会议摘要"},
    "EarningsSurprise": {"ko": "📊 어닝 서프라이즈 감지", "en": "📊 Earnings Surprise", "ja": "📊 サプライズ検知", "zh": "📊 业绩超预期检测"},
    "AnalystEstimates": {"ko": "📈 실적 전망치 업데이트", "en": "📈 Estimates Updated", "ja": "📈 業績予想更新", "zh": "📈 业绩预期更新"},
    "SURGE_IPO": {"ko": "🚀 공모가 대비 20% 급등", "en": "🚀 20% IPO Surge", "ja": "🚀 公募価格比20%急騰", "zh": "🚀 较发行价大涨20%"},
    "SURGE_1D": {"ko": "📈 당일 단기 급등 시그널", "en": "📈 Intraday Surge", "ja": "📈 当日急騰シグナル", "zh": "📈 当日暴涨信号"},
    "SmartMoney": {"ko": "🐋 실시간 자금 흐름 추적", "en": "🐋 Smart Money Flow", "ja": "🐋 資金追跡レポート", "zh": "🐋 聪明钱追踪"},
    "ESGRating": {"ko": "🌱 ESG 리스크 평가", "en": "🌱 ESG Risk Rating", "ja": "🌱 ESG評価更新", "zh": "🌱 ESG风险评级"},
}

# [4] Hero Section (화이트 바탕 + 레드 텍스트)
st.markdown('<p class="hero-title">Unicornfinder</p>', unsafe_allow_html=True)
st.markdown('<p class="hero-sub">Find your unicorn with Unicornfinder</p>', unsafe_allow_html=True)
st.write("<br>", unsafe_allow_html=True)

# [5] 실시간 데이터 생산 현황 (세부 내역형)
st.subheader(UI_TEXT['live_title'][L])
counts = get_daily_signal_counts()

if counts:
    cols = st.columns(4)
    active_items = [(k, v) for k, v in counts.items() if k in SIGNAL_LABELS]
    for i, (key, val) in enumerate(active_items):
        with cols[i % 4]:
            label = SIGNAL_LABELS[key][L]
            st.markdown(f"""
                <div style="padding:15px; border-radius:12px; background:#FFFFFF; border:1px solid #FFEEEE; border-left:5px solid #FF0000; margin-bottom:10px;">
                    <span style="font-size:0.85rem; color:#666; font-weight:600;">{label}</span><br>
                    <span style="font-size:1.4rem; font-weight:bold; color:#FF0000;">{val} <small style="font-size:0.8rem; color:#888;">{UI_TEXT['item_unit'][L]}</small></span>
                </div>
            """, unsafe_allow_html=True)
else:
    st.info("데이터 집계 중..." if L=='ko' else "Aggregating data...")

st.write("---")

# [6] 상장 예정 기업 미리보기 (정보 확장판)
st.subheader(UI_TEXT['upcoming_title'][L])
df_teaser = get_upcoming_ipo_teaser()

if not df_teaser.empty:
    for _, row in df_teaser.iterrows():
        # 발행총액 계산 (주식수 * 공모가)
        try:
            shares = float(row.get('numberOfShares', 0))
            price_low = float(str(row.get('price', '0')).replace('$','').split('-')[0])
            total_offering = f"${(shares * price_low / 1000000):,.1f}M"
        except: total_offering = "TBD"

        with st.container():
            c1, c2 = st.columns([1, 3])
            with c1:
                st.markdown(f"### {row['symbol']}")
                st.markdown(f"**{row['name']}**")
            with c2:
                # 상세 스펙 렌더링
                spec_cols = st.columns(4)
                spec_cols[0].metric("공모가", row['price'])
                spec_cols[1].metric("발행총액", total_offering)
                spec_cols[2].metric("상장시장", row['exchange'])
                spec_cols[3].metric("상장예정일", row['date'])
                
                # 프리미엄 락업 섹션
                lock_cols = st.columns(2)
                lock_cols[0].markdown("🔍 **Analyst Ratings** : `🔒 Premium`")
                lock_cols[1].markdown("⭐ **IPO Scoop Scores** : `🔒 Premium`")
            st.divider()
else:
    st.info("상장 예정 정보 없음")

# [7] 멤버십 비교표 (기획 확정안 상세 버전)
st.write("<br>", unsafe_allow_html=True)
st.subheader(UI_TEXT['membership_title'][L])

membership_data = {
    "분류": ["핵심 가치", "데이터 수준", "상세 데이터", "AI 엔진", "특화 기능", "투자 가이드", "핵심 서비스"],
    "Premium (월 12,000원)": [
        "Wall Street Professional Data",
        "표준 데이터 (Standard Data) 90%",
        "• 재무 11대 지표 분석\n• 월가 컨센서스/목표가\n• 기업 공식 보도자료 분석",
        "AI 기반 텍스트 요약 (Summarization)",
        "❌ (분석 리포트만 제공)",
        "데이터 및 분석 리포트",
        "공시/지표/뉴스 요약본 제공"
    ],
    "Premium Plus (월 18,000원)": [
        "AI Investment Navigation",
        "CNN/RNN 기반 알파 그룹 메타데이터",
        "• 8-K 돌발 공시 & 어닝콜 요약\n• 실시간 자금 흐름(내부자/기관) 추적\n• Premium 모든 데이터 포함",
        "동적 군집화 (Dynamic Clustering)",
        "• 적중률 상위 5% 우위집단 추적\n• 검증된 정보 소비 경로 공유",
        "[독점] 실시간 투자 내비게이션",
        "• 우위집단 정보소비패턴 제공\n• Z-score 기반 급등 알림"
    ]
}

df_member = pd.DataFrame(membership_data).set_index("분류")
st.table(df_member)

# [8] 하단 CTA 버튼
st.write("<br>", unsafe_allow_html=True)
if st.button(UI_TEXT['cta_btn'][L], use_container_width=True, type="primary"):
    st.switch_page("pages/01_App.py")

st.markdown("<p style='text-align: center; color: #888; font-size: 0.8rem; margin-top: 30px;'>© 2026 UnicornFinder. All rights reserved.</p>", unsafe_allow_html=True)
