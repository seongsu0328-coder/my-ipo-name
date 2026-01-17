import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 세션 초기화 (시스템 안정성 확보) ---
for key in ['page', 'auth_status', 'vote_data', 'comment_data', 'selected_stock']:
    if key not in st.session_state:
        st.session_state[key] = 'intro' if key == 'page' else ({} if 'data' in key else None)

# --- CSS 스타일 (원형 디자인 유지) ---
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
    .feature-grid { display: flex; justify-content: space-around; gap: 20px; margin-bottom: 30px; }
    .feature-item {
        background: rgba(255, 255, 255, 0.15);
        padding: 25px 15px; border-radius: 20px; flex: 1;
        backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.2);
    }
    .feature-icon { font-size: 32px; margin-bottom: 12px; }
    .feature-text { font-size: 15px; font-weight: 600; line-height: 1.4; }

    .quote-card {
        background: linear-gradient(145deg, #ffffff, #f9faff);
        padding: 25px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.05); text-align: center;
        max-width: 650px; margin: 40px auto;
    }
    .grid-card {
        background-color: #ffffff; padding: 20px; border-radius: 20px; 
        border: 1px solid #eef2ff; box-shadow: 0 10px 20px rgba(0,0,0,0.05); text-align: center;
    }
    .vote-container { background-color: #f8faff; padding: 25px; border-radius: 20px; border: 1px solid #eef2ff; }
    .comment-box { background: white; padding: 12px; border-radius: 10px; border-left: 4px solid #6e8efb; margin-bottom: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .sector-tag { background-color: #eef2ff; color: #4f46e5; padding: 2px 8px; border-radius: 5px; font-size: 12px; font-weight: bold; }
    
    div.stButton > button[key="start_app"] {
        background-color: #ffffff !important; color: #6e8efb !important;
        font-weight: 900 !important; font-size: 22px !important;
        padding: 12px 60px !important; border-radius: 50px !important;
        border: none !important; box-shadow: 0 10px 25px rgba(0,0,0,0.15) !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 로직 ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

@st.cache_data(ttl=86400)
def get_daily_quote():
    try:
        res = requests.get("https://api.quotable.io/random?tags=business", timeout=3).json()
        trans = requests.get(f"https://api.mymemory.translated.net/get?q={res['content']}&langpair=en|ko", timeout=3).json()
        return {"eng": res['content'], "kor": trans['responseData']['translatedText'], "author": res['author']}
    except: return {"eng": "AI will not replace you. A person using AI will.", "kor": "AI가 당신을 대체하지 않을 것입니다. AI를 사용하는 사람이 당신을 대체할 것입니다.", "author": "Unknown"}

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

def get_current_stock_price(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
        return requests.get(url, timeout=2).json().get('c', 0)
    except: return 0

# ==========================================
# 🚀 화면 제어 로직
# ==========================================

# 1. 인트로 페이지 (수정된 AI 가격예측 문구 포함)
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 8, 1])
    with col_center:
        st.markdown("""
            <div class='intro-card'>
                <div class='intro-title'>UNICORN FINDER</div>
                <div class='intro-subtitle'>미국 시장의 차세대 주역을 가장 먼저 발견하세요</div>
                <div class='feature-grid'>
                    <div class='feature-item'>
                        <div class='feature-icon'>📅</div>
                        <div class='feature-text'><b>IPO 스케줄</b><br>상장 예정 기업 실시간 트래킹</div>
                    </div>
                    <div class='feature-item'>
                        <div class='feature-icon'>📊</div>
                        <div class='feature-text'><b>AI기반 가격예측</b><br>데이터 기반 서비스 제공</div>
                    </div>
                    <div class='feature-item'>
                        <div class='feature-icon'>🗳️</div>
                        <div class='feature-text'><b>집단 지성</b><br>글로벌 투자자 심리 투표</div>
                    </div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        if st.button("탐험 시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()

# 2. 로그인 페이지 (중앙 정렬 명언 복구)
elif st.session_state.page == 'login' and st.session_state.auth_status is None:
    st.write("<br>" * 6, unsafe_allow_html=True)
    _, col_m, _ = st.columns([1, 1.5, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000", label_visibility="collapsed")
        c1, c2 = st.columns(2)
        if c1.button("회원 로그인", use_container_width=True) and len(phone) > 9:
            st.session_state.auth_status = 'user'; st.session_state.page = 'stats'; st.rerun()
        if c2.button("비회원 시작", use_container_width=True):
            st.session_state.auth_status = 'guest'; st.session_state.page = 'stats'; st.rerun()
    
    q = get_daily_quote()
    st.markdown(f"""
        <div class='quote-card'>
            <div style='font-size: 11px; color: #6e8efb; font-weight: bold; margin-bottom: 8px; letter-spacing: 1px;'>TODAY'S INSIGHT</div>
            <div style='font-size: 16px; color: #333; font-weight: 600; line-height: 1.5;'>"{q['eng']}"</div>
            <div style='font-size: 13px; color: #666; margin-top: 6px;'>({q['kor']})</div>
            <div style='color: #aaa; font-size: 11px; margin-top: 12px;'>- {q['author']} -</div>
        </div>
    """, unsafe_allow_html=True)

# 3. 시장 분석 (2x2 그리드)
elif st.session_state.page == 'stats':
    st.title("🦄 유니콘 성장 단계 분석")
    stages = [{"name": "유아기 유니콘", "img": "baby_unicorn.png", "avg": "연 180개", "time": "약 1.5년", "rate": "45%"},{"name": "아동기 유니콘", "img": "child_unicorn.png", "avg": "연 120개", "time": "약 4년", "rate": "65%"},{"name": "성인기 유니콘", "img": "adult_unicorn.png", "avg": "연 85개", "time": "약 12년", "rate": "88%"},{"name": "노년기 유니콘", "img": "old_unicorn.png", "avg": "연 40개", "time": "25년 이상", "rate": "95%"}]
    
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
            if st.button(f"🔎 {stage['name']} 탐험", key=f"btn_{i}", use_container_width=True): confirm_exploration()
            if os.path.exists(stage['img']): st.image(Image.open(stage['img']), use_container_width=True)
            else: st.info(f"[{stage['name']} 이미지 준비중]")
            st.markdown(f"<div style='background:#f8faff; padding:10px; border-radius:10px; margin-top:10px;'><small>IPO {stage['avg']} | 생존 {stage['time']} | 생존율 {stage['rate']}</small></div>", unsafe_allow_html=True)

# 4. 캘린더 (기간 필터 및 현재가)
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    st.header("🚀 IPO 리서치 센터")
    
    all_df = get_extended_ipo_data(MY_API_KEY)
    if not all_df.empty:
        today = datetime.now().date()
        period = st.radio("조회 기간 설정", ["60일 내 상장예정", "최근 6개월", "최근 12개월", "전체 (18개월)"], horizontal=True)
        
        if period == "60일 내 상장예정":
            display_df = all_df[all_df['공모일_dt'].dt.date >= today].sort_values(by='공모일_dt')
        else:
            months = 6 if "6개월" in period else (12 if "12개월" in period else 18)
            cutoff = today - timedelta(days=months * 30)
            display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= cutoff)].sort_values(by='공모일_dt', ascending=False)

        st.write("---")
        h1, h2, h3, h4, h5 = st.columns([1.2, 3.5, 1.2, 1.5, 1.2])
        h1.write("**공모일**"); h2.write("**기업명**"); h3.write("**공모가**"); h4.write("**규모**"); h5.write("**현재가**")
        st.write("---")
        for i, row in display_df.iterrows():
            col1, col2, col3, col4, col5 = st.columns([1.2, 3.5, 1.2, 1.5, 1.2])
            is_p = row['공모일_dt'].date() <= today
            col1.markdown(f"<span style='color:{'#888' if is_p else '#4f46e5'};'>{row['date']}</span>", unsafe_allow_html=True)
            if col2.button(row['name'], key=f"n_{row['symbol']}_{i}", use_container_width=True):
                st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()
            p = pd.to_numeric(row['price'], errors='coerce') or 0
            s = pd.to_numeric(row['numberOfShares'], errors='coerce') or 0
            col3.write(f"${p:,.2f}" if p > 0 else "미정")
            col4.write(f"${(p*s):,.0f}" if p*s > 0 else "대기")
            if is_p:
                cp = get_current_stock_price(row['symbol'], MY_API_KEY)
                col5.markdown(f"<span style='color:{'#28a745' if cp >= p else '#dc3545'}; font-weight:bold;'>${cp:,.2f}</span>" if cp > 0 else "-", unsafe_allow_html=True)
            else: col5.write("대기")

# 5. 상세 리서치 (탭별 상세 분석 및 투표)
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        st.title(f"🚀 {stock['name']} 상세 리서치")
        
        cl, cr = st.columns([1, 4])
        with cl: st.image(f"https://logo.clearbit.com/{stock['symbol']}.com", width=150)
        with cr:
            st.subheader(f"{stock['name']} ({stock['symbol']})")
            st.markdown(f"**업종:** <span class='sector-tag'>Technology & Infrastructure</span>", unsafe_allow_html=True)
            m1, m2, m3 = st.columns(3)
            p = pd.to_numeric(stock.get('price'), errors='coerce') or 0
            m1.metric("공모가", f"${p:,.2f}")
            m2.metric("현재가", f"${get_current_stock_price(stock['symbol'], MY_API_KEY):,.2f}")
            m3.metric("보호예수", "180일")

        st.write("---")
        t1, t2, t3 = st.tabs(["📌 기업 분석", "📄 SEC 공시", "💰 재무 정보"])
        with t1:
            st.write(f"**{stock['name']}**은 업계 내 강력한 경쟁 우위를 바탕으로 성장 중입니다.")
            st.info("AI 및 자동화 기술을 도입하여 운영 효율성을 극대화하고 있습니다.")
        with t2:
            st.link_button("📄 SEC S-1 공시 보기", f"https://www.sec.gov/cgi-bin/browse-edgar?company={stock['name'].replace(' ', '+')}", use_container_width=True)
        with t3:
            st.write("최근 연간 매출 성장률: **+38%**")
            st.link_button("📈 Yahoo Finance 상세 지표", f"https://finance.yahoo.com/quote/{stock['symbol']}/financials", use_container_width=True)

        st.write("---")
        st.subheader("🗳️ Investor Sentiment")
        sid = stock['symbol']
        if sid not in st.session_state.vote_data: st.session_state.vote_data[sid] = {'u': 20, 'f': 5}
        if sid not in st.session_state.comment_data: st.session_state.comment_data[sid] = []
        
        vcol, ccol = st.columns(2)
        with vcol:
            st.markdown("<div class='vote-container'>", unsafe_allow_html=True)
            v1, v2 = st.columns(2)
            if v1.button("🦄 유니콘이다", key=f"uv_{sid}", use_container_width=True): st.session_state.vote_data[sid]['u'] += 1; st.rerun()
            if v2.button("💸 거품이다", key=f"fv_{sid}", use_container_width=True): st.session_state.vote_data[sid]['f'] += 1; st.rerun()
            uv, fv = st.session_state.vote_data[sid]['u'], st.session_state.vote_data[sid]['f']
            st.progress(uv / (uv + fv))
            st.write(f"유니콘 지수: **{int(uv/(uv+fv)*100)}%**")
            st.markdown("</div>", unsafe_allow_html=True)
        with ccol:
            nc = st.text_input("커뮤니티 투자 의견", key=f"in_{sid}")
            if st.button("의견 등록", key=f"bn_{sid}") and nc:
                st.session_state.comment_data[sid].insert(0, {"t": nc, "d": datetime.now().strftime("%H:%M")})
                st.rerun()
            for c in st.session_state.comment_data[sid][:3]:
                st.markdown(f"<div class='comment-box'><small>{c['d']}</small><br>{c['t']}</div>", unsafe_allow_html=True)
