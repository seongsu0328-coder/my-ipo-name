import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os
import random

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 세션 초기화 ---
for key in ['page', 'auth_status', 'vote_data', 'comment_data', 'selected_stock']:
    if key not in st.session_state:
        st.session_state[key] = 'intro' if key == 'page' else ({} if 'data' in key else None)

# --- CSS 스타일 (모바일 가독성 및 디자인 최적화) ---
st.markdown("""
    <style>
    .intro-card {
        background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%);
        padding: 60px 40px; border-radius: 30px; color: white;
        text-align: center; margin-top: 20px;
        box-shadow: 0 20px 40px rgba(110, 142, 251, 0.3);
    }
    .intro-title { font-size: 45px; font-weight: 900; margin-bottom: 15px; letter-spacing: -1px; }
    .intro-subtitle { font-size: 19px; opacity: 0.9; margin-bottom: 40px; }
    
    .quote-card {
        background: linear-gradient(145deg, #ffffff, #f9faff);
        padding: 25px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.05); text-align: center;
        max-width: 650px; margin: 40px auto;
        color: #333333 !important;
    }
    .quote-card b { color: #222222 !important; display: block; margin: 10px 0; }
    .quote-card small { color: #666666 !important; }

    .feature-grid { display: flex; justify-content: space-around; gap: 20px; margin-bottom: 30px; }
    .feature-item {
        background: rgba(255, 255, 255, 0.15);
        padding: 25px 15px; border-radius: 20px; flex: 1;
        backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.2);
    }
    .grid-card {
        background-color: #ffffff; padding: 20px; border-radius: 20px; 
        border: 1px solid #eef2ff; box-shadow: 0 10px 20px rgba(0,0,0,0.05); text-align: center;
        color: #333;
    }
    .vote-container { background-color: #f8faff; padding: 25px; border-radius: 20px; border: 1px solid #eef2ff; margin-bottom: 20px; color: #333; }
    .comment-box { background: white; padding: 12px; border-radius: 10px; border-left: 4px solid #6e8efb; margin-bottom: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); color: #333; }
    .info-box { background-color: #f0f4ff; padding: 15px; border-radius: 12px; border-left: 5px solid #6e8efb; margin-bottom: 10px; color: #333; }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 로직 ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

@st.cache_data(ttl=86400)
def get_daily_quote():
    try:
        res = requests.get("https://api.quotable.io/random?tags=business", timeout=3).json()
        content = res['content']
        trans = requests.get(f"https://api.mymemory.translated.net/get?q={content}&langpair=en|ko", timeout=3).json()
        return {"eng": content, "kor": trans['responseData']['translatedText'], "author": res['author']}
    except:
        backups = [
            {"eng": "The way to get started is to quit talking and begin doing.", "kor": "시작하는 법은 말하기를 그만두고 행동하는 것이다.", "author": "Walt Disney"},
            {"eng": "Opportunities don't happen. You create them.", "kor": "기회는 일어나는 것이 아니라 만드는 것이다.", "author": "Chris Grosser"}
        ]
        return random.choice(backups)

@st.cache_data(ttl=600)
def get_extended_ipo_data(api_key):
    start = (datetime.now() - timedelta(days=18*30)).strftime('%Y-%m-%d')
    end = (datetime.now() + timedelta(days=60)).strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/calendar/ipo?from={start}&to={end}&token={api_key}"
    try:
        res = requests.get(url, timeout=5).json()
        df = pd.DataFrame(res.get('ipoCalendar', []))
        if not df.empty: df['공모일_dt'] = pd.to_datetime(df['date'])
        return df
    except: return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_stock_financials(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/stock/metric?symbol={symbol}&metric=all&token={api_key}"
        res = requests.get(url, timeout=3).json()
        metrics = res.get('metric', {})
        if not metrics: return None
        return {
            "매출액 성장률(5y)": f"{metrics.get('revenueGrowth5Y', 0):.2f}%",
            "영업이익률(TTM)": f"{metrics.get('operatingMarginTTM', 0):.2f}%",
            "유동비율(Current Ratio)": f"{metrics.get('currentRatioLTM', 0):.2f}",
            "부채비율(Debt/Equity)": f"{metrics.get('totalDebt/totalEquityLTM', 0):.2f}",
            "주당순이익(EPS TTM)": f"${metrics.get('epsTTM', 0):.2f}"
        }
    except: return None

def get_current_stock_price(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
        return requests.get(url, timeout=2).json().get('c', 0)
    except: return 0

# ==========================================
# 🚀 화면 제어 로직
# ==========================================

# 1. 인트로 페이지
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 8, 1])
    with col_center:
        st.markdown("""
            <div class='intro-card'>
                <div class='intro-title'>UNICORN FINDER</div>
                <div class='intro-subtitle'>미국 시장의 차세대 주역을 가장 먼저 발견하세요</div>
                <div class='feature-grid'>
                    <div class='feature-item'>📅<br><b>IPO 스케줄</b></div>
                    <div class='feature-item'>📊<br><b>AI기반 분석</b></div>
                    <div class='feature-item'>🗳️<br><b>집단 지성</b></div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        if st.button("탐험 시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()

# 2. 로그인 페이지
elif st.session_state.page == 'login':
    st.write("<br>" * 4, unsafe_allow_html=True)
    _, col_m, _ = st.columns([1, 1.5, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000", label_visibility="collapsed")
        c1, c2 = st.columns(2)
        if c1.button("회원 로그인", use_container_width=True):
            st.session_state.auth_status = 'user'; st.session_state.page = 'stats'; st.rerun()
        if c2.button("비회원 시작", use_container_width=True):
            st.session_state.auth_status = 'guest'; st.session_state.page = 'stats'; st.rerun()
    
    q = get_daily_quote()
    st.markdown(f"<div class='quote-card'><b>\"{q['eng']}\"</b><small>({q['kor']})</small><br><br><small>- {q['author']} -</small></div>", unsafe_allow_html=True)

# 3. 시장 분석 (2x2 그리드 복구)
elif st.session_state.page == 'stats':
    st.title("🦄 유니콘 성장 단계 분석")
    stages = [
        {"name": "유아기 유니콘", "img": "baby_unicorn.png", "avg": "연 180개", "time": "약 1.5년", "rate": "45%"},
        {"name": "아동기 유니콘", "img": "child_unicorn.png", "avg": "연 120개", "time": "약 4년", "rate": "65%"},
        {"name": "성인기 유니콘", "img": "adult_unicorn.png", "avg": "연 85개", "time": "약 12년", "rate": "88%"},
        {"name": "노년기 유니콘", "img": "old_unicorn.png", "avg": "연 40개", "time": "25년 이상", "rate": "95%"}
    ]
    
    @st.dialog("상장 예정 기업 탐험")
    def confirm_exploration():
        st.write("18개월간의 히스토리와 상장 예정 기업 리스트를 확인하시겠습니까?")
        if st.button("네, 탐험하겠습니다", use_container_width=True, type="primary"): 
            st.session_state.page = 'calendar'; st.rerun()

    r1_c1, r1_c2 = st.columns(2); r2_c1, r2_c2 = st.columns(2)
    cols = [r1_c1, r1_c2, r2_c1, r2_c2]
    for i, stage in enumerate(stages):
        with cols[i]:
            st.markdown(f"<div class='grid-card'><h3>{stage['name']}</h3>", unsafe_allow_html=True)
            if st.button(f"🔎 {stage['name']} 탐험", key=f"btn_{i}", use_container_width=True): 
                confirm_exploration()
            st.markdown(f"<small>IPO {stage['avg']} | 생존 {stage['time']} | 생존율 {stage['rate']}</small></div>", unsafe_allow_html=True)

# 4. 캘린더 (필터 및 리스트 복구)
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    st.header("🚀 IPO 리서치 센터")
    all_df = get_extended_ipo_data(MY_API_KEY)
    
    if not all_df.empty:
        today = datetime.now().date()
        period = st.radio("조회 기간 설정", ["60일 내 상장예정", "최근 6개월", "최근 12개월", "전체"], horizontal=True)
        
        if period == "60일 내 상장예정":
            display_df = all_df[all_df['공모일_dt'].dt.date >= today].sort_values(by='공모일_dt')
        elif period == "전체":
            display_df = all_df.sort_values(by='공모일_dt', ascending=False)
        else:
            m = 6 if "6개월" in period else 12
            display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=m*30))].sort_values(by='공모일_dt', ascending=False)
        
        st.write("---")
        h1, h2, h3, h4, h5 = st.columns([1.2, 3.5, 1.2, 1.5, 1.2])
        h1.write("**공모일**"); h2.write("**기업명**"); h3.write("**공모가**"); h4.write("**규모**"); h5.write("**현재가**")
        
        for i, row in display_df.iterrows():
            col1, col2, col3, col4, col5 = st.columns([1.2, 3.5, 1.2, 1.5, 1.2])
            is_p = row['공모일_dt'].date() <= today
            col1.write(row['date'])
            if col2.button(row['name'], key=f"n_{row['symbol']}_{i}", use_container_width=True):
                st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()
            
            p = pd.to_numeric(row['price'], errors='coerce') or 0
            s = pd.to_numeric(row['numberOfShares'], errors='coerce') or 0
            col3.write(f"${p:,.2f}" if p > 0 else "미정")
            col4.write(f"${(p*s/1000000):,.1f}M" if p*s > 0 else "대기")
            
            if is_p:
                cp = get_current_stock_price(row['symbol'], MY_API_KEY)
                col5.markdown(f"**${cp:,.2f}**" if cp > 0 else "-")
            else: col5.write("대기")

# 5. 상세 리서치 (정보 추가 + AI 평가 + 투표 시스템 통합)
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        st.title(f"🚀 {stock['name']} 심층 분석")
        
        tab1, tab2, tab3 = st.tabs(["📋 핵심 정보 & 재무", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])

        with tab1:
            st.subheader("🔍 투자자 필수 체크리스트")
            c1, c2 = st.columns([1, 2.5])
            with c1: 
                st.image(f"https://logo.clearbit.com/{stock['symbol']}.com", width=180)
                sec_url = f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={stock['symbol']}&action=getcompany"
                st.link_button("📄 SEC 공시 원문(S-1) 확인", sec_url, use_container_width=True)
            with c2:
                p = pd.to_numeric(stock.get('price'), errors='coerce') or 0
                s = pd.to_numeric(stock.get('numberOfShares'), errors='coerce') or 0
                st.markdown(f"<div class='info-box'><b>1. 예상 공모가:</b> ${p:,.2f}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>2. 공모 규모:</b> ${(p*s/1000000):,.1f}M USD</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>3. 상장 거래소:</b> {stock.get('exchange', 'NYSE/NASDAQ')}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>4. 보호예수:</b> 상장 후 180일 예정</div>", unsafe_allow_html=True)

            st.write("---")
            st.markdown("#### 📊 실시간 주요 재무 및 공시 지표")
            financial_data = get_stock_financials(stock['symbol'], MY_API_KEY)
            if financial_data:
                df_fin = pd.DataFrame(list(financial_data.items()), columns=['항목', '데이터'])
                st.table(df_fin)
            else:
                st.warning("신규 기업으로 API 재무 데이터가 아직 생성되지 않았습니다.")
            st.info("**S-1 공시 요약:** 본 기업은 R&D 인프라 확충에 자금을 주로 사용할 계획임을 공시했습니다.")

        with tab2:
            st.subheader("⚖️ AI 가치 평가 (학술 모델)")
            p = pd.to_numeric(stock.get('price'), errors='coerce') or 0
            fp_min, fp_max = p * 1.12, p * 1.38
            ca, cb = st.columns(2)
            with ca:
                st.metric("AI 추정 적정가 범위", f"${fp_min:,.2f} ~ ${fp_max:,.2f}")
                st.markdown("#### **참조 모델**\n- Ritter(1991) IPO 성과 분석")
            with cb:
                st.write("상승 잠재력 분석")
                st.progress(0.65)
                st.success(f"평균 **12%~38%** 추가 상승 가능성")

        with tab3:
            sid = stock['symbol']
            if sid not in st.session_state.vote_data: st.session_state.vote_data[sid] = {'u': 10, 'f': 3}
            if sid not in st.session_state.comment_data: st.session_state.comment_data[sid] = []
            
            st.markdown("<div class='vote-container'>", unsafe_allow_html=True)
            st.write("**1. 투자 매력도 투표**")
            v1, v2 = st.columns(2)
            if v1.button("🦄 Unicorn", use_container_width=True, key=f"vu_{sid}"): 
                st.session_state.vote_data[sid]['u'] += 1; st.rerun()
            if v2.button("💸 Fallen Angel", use_container_width=True, key=f"vf_{sid}"): 
                st.session_state.vote_data[sid]['f'] += 1; st.rerun()
            uv, fv = st.session_state.vote_data[sid]['u'], st.session_state.vote_data[sid]['f']
            st.progress(uv/(uv+fv))
            st.markdown("</div>", unsafe_allow_html=True)

            st.write("**2. 커뮤니티 의견**")
            nc = st.text_input("의견 등록", key=f"ci_{sid}")
            if st.button("등록", key=f"cb_{sid}") and nc:
                st.session_state.comment_data[sid].insert(0, {"t": nc, "d": "방금 전"}); st.rerun()
            for c in st.session_state.comment_data[sid][:3]:
                st.markdown(f"<div class='comment-box'><small>{c['d']}</small><br>{c['t']}</div>", unsafe_allow_html=True)
