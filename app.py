import streamlit as st
import pandas as pd
from utils.db_helper import get_daily_signal_counts, get_upcoming_ipo_teaser

# [1] 페이지 설정
st.set_page_config(page_title="UnicornFinder", layout="wide", page_icon="🦄")

# [2] 언어 세션 초기화 및 선택 (기존 app.py 스타일)
if 'lang' not in st.session_state:
    st.session_state.lang = 'ko'

# 상단 언어 선택 버튼 (가로 배치)
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
    "hero_sub": {
        "ko": "월가 AI 분석을 내 손안에, 스마트한 IPO 투자의 내비게이션",
        "en": "Wall Street AI Analysis in Your Hand, The Navigation for Smart IPO Investing",
        "ja": "ウォール街のAI分析をあなたの手に、スマートなIPO投資のナビゲーション",
        "zh": "华尔街AI分析尽在掌握，智能IPO投资导航"
    },
    "live_title": {
        "ko": "📡 오늘의 실시간 데이터 생산 현황",
        "en": "📡 Today's Live Data Production",
        "ja": "📡 本日のリアルタイムデータ生産状況",
        "zh": "📡 今日实时数据生产情况"
    },
    "upcoming_title": {
        "ko": "🚀 상장 예정 기업 미리보기 (30일 이내)",
        "en": "🚀 Upcoming IPO Teaser (Next 30 Days)",
        "ja": "🚀 上場予定企業のプレビュー（30日以内）",
        "zh": "🚀 上市预告（30天内）"
    },
    "membership_title": {
        "ko": "💎 멤버십 혜택 상세 비교",
        "en": "💎 Membership Benefits Comparison",
        "ja": "💎 メンバーシップ特典の詳細比較",
        "zh": "💎 会员权益详细对比"
    },
    "cta_btn": {
        "ko": "🚀 유니콘 파인더 앱 입장하기 (무료 시작)",
        "en": "🚀 Enter UnicornFinder App (Start Free)",
        "ja": "🚀 ユニコーンファインダーアプリに入場（無料開始）",
        "zh": "🚀 进入 UnicornFinder 应用（免费开始）"
    },
    "item_unit": {"ko": "개", "en": "items", "ja": "個", "zh": "个"},
    "lock_msg": {
        "ko": "🔒 상세 리포트와 목표 주가는 앱에서 확인 가능합니다.",
        "en": "🔒 Full reports & target prices are available in the app.",
        "ja": "🔒 詳細レポートと目標株価はアプリで確認できます。",
        "zh": "🔒 详细报告和目标价可在应用中查看。"
    }
}

# 시그널 라벨 다국어
SIGNAL_LABELS = {
    "SURGE_IPO": {"ko": "🚀 20% 급등 (SURGE_IPO)", "en": "🚀 20% Surge (SURGE_IPO)", "ja": "🚀 20%急騰 (SURGE_IPO)", "zh": "🚀 20%暴涨 (SURGE_IPO)"},
    "SURGE_1D": {"ko": "📈 단기 급등 (SURGE_1D)", "en": "📈 Intraday Surge (SURGE_1D)", "ja": "📈 短期急騰 (SURGE_1D)", "zh": "📈 短期暴涨 (SURGE_1D)"},
    "REBOUND": {"ko": "⚓ 바닥 신호 (REBOUND)", "en": "⚓ Rebound Signal (REBOUND)", "ja": "⚓ 底打ち信号 (REBOUND)", "zh": "⚓ 筑底信号 (REBOUND)"},
    "INST_UPGRADE": {"ko": "🎯 기관 매수 시그널", "en": "🎯 Inst. Buy Signal", "ja": "🎯 機関投資家買い信号", "zh": "🎯 机构买入信号"},
    "8K_UPDATE": {"ko": "🚨 중대 공시 분석 (8K)", "en": "🚨 8-K Critical Analysis", "ja": "🚨 重大開示分析 (8K)", "zh": "🚨 重大公告分析 (8K)"},
    "EarningsCall": {"ko": "🎙️ 어닝 콜 요약", "en": "🎙️ Earnings Call Summary", "ja": "🎙️ アーニングコール要約", "zh": "🎙️ 财报电话会议摘要"},
    "EarningsSurprise": {"ko": "📊 어닝 서프라이즈 분석", "en": "📊 Earnings Surprise", "ja": "📊 サプライズ分析", "zh": "📊 业绩超预期分析"},
    "AnalystEstimates": {"ko": "📈 실적 전망치 변경", "en": "📈 Estimates Updated", "ja": "📈 業績予想変更", "zh": "📈 业绩预期变更"},
    "ESGRating": {"ko": "🌱 ESG 평가 업데이트", "en": "🌱 ESG Rating Update", "ja": "🌱 ESG評価更新", "zh": "🌱 ESG评级更新"},
    "Upgrades": {"ko": "🎯 투자의견 히스토리", "en": "🎯 Rating History", "ja": "🎯 投資意見履歴", "zh": "🎯 投资评级历史"},
    "MAReport": {"ko": "🤝 M&A 인수합병 분석", "en": "🤝 M&A Synergy Analysis", "ja": "🤝 M&A合併分析", "zh": "🤝 M&A并购分析"},
    "SmartMoney": {"ko": "🐋 스마트머니 포착", "en": "🐋 Smart Money Tracker", "ja": "🐋 スマートマネー捕捉", "zh": "🐋 聪明钱追踪"},
}

# [4] Hero Section
st.markdown(f"""
    <div style="text-align: center; padding: 50px 20px; background: linear-gradient(135deg, #0e1117 0%, #232732 100%); color: white; border-radius: 20px; border: 1px solid #30363d; margin-bottom: 30px;">
        <h1 style="font-size: 3rem; font-weight: 800; margin-bottom: 10px;">Find your unicorn with Unicornfinder</h1>
        <p style="font-size: 1.3rem; opacity: 0.9;">{UI_TEXT['hero_sub'][L]}</p>
    </div>
""", unsafe_allow_html=True)

# [5] 실시간 데이터 생산 현황
st.subheader(UI_TEXT['live_title'][L])
counts = get_daily_signal_counts()

if counts:
    cols = st.columns(4)
    active_items = [(k, v) for k, v in counts.items() if k in SIGNAL_LABELS]
    for i, (key, val) in enumerate(active_items):
        with cols[i % 4]:
            label = SIGNAL_LABELS[key][L]
            st.markdown(f"""
                <div style="padding:15px; border-radius:12px; background:#f8f9fa; border-left:5px solid #6a11cb; margin-bottom:10px;">
                    <span style="font-size:0.85rem; color:#666; font-weight:600;">{label}</span><br>
                    <span style="font-size:1.4rem; font-weight:bold; color:#000;">{val} <small style="font-size:0.8rem; color:#888;">{UI_TEXT['item_unit'][L]}</small></span>
                </div>
            """, unsafe_allow_html=True)
else:
    st.info("데이터 집계 중..." if L=='ko' else "Aggregating data...")

st.write("---")

# [6] 상장 예정 기업 (맛보기)
st.subheader(UI_TEXT['upcoming_title'][L])
df_teaser = get_upcoming_ipo_teaser()
if not df_teaser.empty:
    t_cols = st.columns(len(df_teaser))
    for i, (_, row) in enumerate(df_teaser.iterrows()):
        with t_cols[i]:
            st.markdown(f"""
                <div style="padding: 20px; border-radius: 15px; border: 1px solid #eee; background: white; min-height: 180px;">
                    <h3 style="margin: 0; color: #6a11cb;">{row['symbol']}</h3>
                    <p style="font-weight: 700; margin-bottom: 8px;">{row['name']}</p>
                    <span style="font-size: 0.85rem; color: #888;">{row['date']} | {row['price']}</span>
                </div>
            """, unsafe_allow_html=True)
            st.caption(UI_TEXT['lock_msg'][L])
else:
    st.info("상장 예정 정보 없음" if L=='ko' else "No upcoming IPOs found.")

# [7] 멤버십 비교표 (4개 국어 번역 적용)
st.write("<br><br>", unsafe_allow_html=True)
st.subheader(UI_TEXT['membership_title'][L])

membership_data = {
    "분류": ["핵심 가치", "상세 데이터", "AI 엔진", "특화 기능"],
    "Premium": {
        "ko": ["Wall Street Data", "재무지표/목표가", "AI 텍스트 요약", "리포트 중심"],
        "en": ["Wall Street Data", "Financials/Targets", "AI Summarization", "Report Based"],
        "ja": ["Wall Street Data", "財務指標/目標株価", "AIテキスト要約", "レポート中心"],
        "zh": ["Wall Street Data", "财务指标/目标价", "AI文本摘要", "报告中心"]
    },
    "Premium Plus": {
        "ko": ["AI Navigation", "8-K/어닝콜/자금추적", "Dynamic Clustering", "우위집단 경로 추적"],
        "en": ["AI Navigation", "8-K/Earnings Call/Flows", "Dynamic Clustering", "Alpha Group Tracking"],
        "ja": ["AI Navigation", "8-K/アーニングコール/資金追跡", "Dynamic Clustering", "優位集団の追跡"],
        "zh": ["AI Navigation", "8-K/财报电话/资金追踪", "Dynamic Clustering", "优势群体追踪"]
    }
}

df_member = pd.DataFrame({
    "Category": membership_data["분류"],
    "Premium": membership_data["Premium"][L],
    "Premium Plus": membership_data["Premium Plus"][L]
}).set_index("Category")
st.table(df_member)

# [8] 하단 CTA 버튼
st.write("<br>", unsafe_allow_html=True)
if st.button(UI_TEXT['cta_btn'][L], use_container_width=True, type="primary"):
    st.switch_page("pages/01_App.py")
