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
for key in ['page', 'auth_status', 'vote_data', 'comment_data', 'selected_stock', 'watchlist']:
    if key not in st.session_state:
        if key == 'page': st.session_state[key] = 'intro'
        elif key == 'watchlist': st.session_state[key] = []
        elif key in ['vote_data', 'comment_data']: st.session_state[key] = {}
        else: st.session_state[key] = None

# --- CSS 스타일 (인트로, 카드, 투표창 모두 포함) ---
st.markdown("""
    <style>
    /* 인트로 카드 및 기능 그리드 */
    .intro-card {
        background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%);
        padding: 60px 40px; border-radius: 30px; color: white;
        text-align: center; margin-top: 20px; box-shadow: 0 20px 40px rgba(110, 142, 251, 0.3);
    }
    .intro-title { font-size: 45px; font-weight: 900; margin-bottom: 15px; letter-spacing: -1px; }
    .intro-subtitle { font-size: 19px; opacity: 0.9; margin-bottom: 40px; }
    .feature-grid { display: flex; justify-content: space-around; gap: 20px; margin-bottom: 30px; }
    .feature-item {
        background: rgba(255, 255, 255, 0.15);
        padding: 25px 15px; border-radius: 20px; flex: 1;
        backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.2);
    }
    .feature-icon { font-size: 30px; margin-bottom: 10px; }
    .feature-text { font-size: 15px; font-weight: 600; }

    /* 명언 및 일반 카드 */
    .quote-card {
        background: linear-gradient(145deg, #ffffff, #f9faff);
        padding: 25px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.05); text-align: center;
        max-width: 650px; margin: 40px auto; color: #333333 !important;
    }
    .grid-card { 
        background-color: #ffffff; padding: 25px; border-radius: 20px; 
        border: 1px solid #eef2ff; box-shadow: 0 10px 20px rgba(0,0,0,0.05); 
        text-align: center; color: #333; height: 100%;
    }

    /* 투표 및 댓글창 */
    .vote-container { background-color: #f8faff; padding: 25px; border-radius: 20px; border: 1px solid #eef2ff; margin-bottom: 20px; color: #333; }
    .comment-box { background: white; padding: 12px; border-radius: 10px; border-left: 4px solid #6e8efb; margin-bottom: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); color: #333; }
    .info-box { background-color: #f0f4ff; padding: 15px; border-radius: 12px; border-left: 5px solid #6e8efb; margin-bottom: 10px; color: #333; text-align: left; }
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
    except:
        return {"eng": "Opportunities don't happen. You create them.", "kor": "기회는 일어나는 것이 아니라 만드는 것이다.", "author": "Chris Grosser"}

@st.cache_data(ttl=600)
def get_extended_ipo_data(api_key):
    start = (datetime.now() - timedelta(days=540)).strftime('%Y-%m-%d')
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

# 1. 인트로 페이지 (3단 카드 복구)
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 8, 1])
    with col_center:
        st.markdown("""
            <div class='intro-card'>
                <div class='intro-title'>UNICORN FINDER</div>
                <div class='intro-subtitle'>미국 시장의 차세대 주역을 가장 먼저 발견하세요</div>
                <div class='feature-grid'>
                    <div class='feature-item'><div class='feature-icon'>📅</div><div class='feature-text'>IPO 스케줄<br>실시간 트래킹</div></div>
                    <div class='feature-item'><div class='feature-icon'>📊</div><div class='feature-text'>AI기반 분석<br>데이터 예측</div></div>
                    <div class='feature-item'><div class='feature-icon'>🗳️</div><div class='feature-text'>집단 지성<br>글로벌 심리 투표</div></div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        if st.button("탐험 시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()

# 2. 로그인 페이지 (명언 복구)
elif st.session_state.page == 'login':
    st.write("<br>" * 4, unsafe_allow_html=True)
    _, col_m, _ = st.columns([1, 1.5, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000")
        c1, c2 = st.columns(2)
        if c1.button("회원 로그인", use_container_width=True):
            st.session_state.auth_status = 'user'; st.session_state.page = 'stats'; st.rerun()
        if c2.button("비회원 시작", use_container_width=True):
            st.session_state.auth_status = 'guest'; st.session_state.page = 'stats'; st.rerun()
    
    q = get_daily_quote()
    st.markdown(f"<div class='quote-card'><small>TODAY'S INSIGHT</small><b>\"{q['eng']}\"</b><small>({q['kor']})</small><br><br><small>- {q['author']} -</small></div>", unsafe_allow_html=True)

# 3. 시장 분석 (유아/아동 2단계 및 상세 설명 복구)
elif st.session_state.page == 'stats':
    st.title("🦄 유니콘 성장 단계 분석")
    stages = [
        {"name": "New 유니콘", "img": "baby_unicorn.png", "icon": "🌱", "avg": "연 180개", "time": "약 1.5년", "rate": "45%"},
        {"name": "My 유니콘", "img": "child_unicorn.png", "icon": "🦄", "avg": "연 120개", "time": "약 4년", "rate": "65%"}
    ]
    
    c1, c2 = st.columns(2)
    cols = [c1, c2]
    for i, stage in enumerate(stages):
        with cols[i]:
            st.markdown(f"<div class='grid-card'><h3>{stage['name']}</h3>", unsafe_allow_html=True)
            if os.path.exists(stage['img']): st.image(Image.open(stage['img']), use_container_width=True)
            else: st.markdown(f"<div style='font-size:80px; padding:20px;'>{stage['icon']}</div>", unsafe_allow_html=True)
            
            if st.button(f"🔎 {stage['name']} 탐험", key=f"btn_{i}", use_container_width=True): 
                st.session_state.page = 'calendar'; st.rerun()
            
            st.markdown(f"""
                <div style='margin-top:15px; font-size:14px; color:#666;'>
                    평균 IPO: {stage['avg']}<br>평균 생존: {stage['time']}<br>성장 성공률: {stage['rate']}
                </div></div>
            """, unsafe_allow_html=True)

# 4. 캘린더 (18개월 필터 복구)
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    st.header("🚀 IPO 리서치 센터")
    all_df = get_extended_ipo_data(MY_API_KEY)
    
    if not all_df.empty:
        today = datetime.now().date()
        period = st.radio("조회 기간 설정", ["상장 예정", "최근 6개월", "최근 12개월", "최근 18개월", "전체"], horizontal=True)
        
        if period == "상장 예정":
            display_df = all_df[all_df['공모일_dt'].dt.date >= today].sort_values(by='공모일_dt')
        elif period == "최근 6개월":
            display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=180))].sort_values(by='공모일_dt', ascending=False)
        elif period == "최근 12개월":
            display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=365))].sort_values(by='공모일_dt', ascending=False)
        elif period == "최근 18개월":
            display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=540))].sort_values(by='공모일_dt', ascending=False)
        else:
            display_df = all_df.sort_values(by='공모일_dt', ascending=False)
        
        st.write("---")
        h1, h2, h3, h4, h5 = st.columns([1.2, 3.5, 1.2, 1.5, 1.2])
        h1.write("**공모일**"); h2.write("**기업명**"); h3.write("**공모가**"); h4.write("**규모**"); h5.write("**현재가**")
        
        for i, row in display_df.iterrows():
            col1, col2, col3, col4, col5 = st.columns([1.2, 3.5, 1.2, 1.5, 1.2])
            is_p = row['공모일_dt'].date() <= today
            col1.markdown(f"<span style='color:{'#888' if is_p else '#4f46e5'};'>{row['date']}</span>", unsafe_allow_html=True)
            if col2.button(row['name'], key=f"n_{row['symbol']}_{i}", use_container_width=True):
                st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()
            
            p = pd.to_numeric(row['price'], errors='coerce') or 0
            s = pd.to_numeric(row['numberOfShares'], errors='coerce') or 0
            col3.write(f"${p:,.2f}" if p > 0 else "미정")
            col4.write(f"${(p*s/1000000):,.1f}M" if p*s > 0 else "대기")
            
            if is_p:
                cp = get_current_stock_price(row['symbol'], MY_API_KEY)
                col5.markdown(f"<span style='color:{'#28a745' if cp >= p else '#dc3545'}; font-weight:bold;'>${cp:,.2f}</span>" if cp > 0 else "-", unsafe_allow_html=True)
            else: col5.write("대기")

# 5. 상세 리서치 (3단계 탭 및 관심종목 버튼 완벽 복구)
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        st.title(f"🚀 {stock['name']} 심층 분석")
        
        tab1, tab2, tab3 = st.tabs(["📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])

        with tab1:
            st.subheader("🔍 투자자 검색 상위 5대 지표")
            c1, c2 = st.columns([1, 2.5])
            with c1: st.image(f"https://logo.clearbit.com/{stock['symbol']}.com", width=200)
            with c2:
                p = pd.to_numeric(stock.get('price'), errors='coerce') or 0
                s = pd.to_numeric(stock.get('numberOfShares'), errors='coerce') or 0
                st.markdown(f"<div class='info-box'><b>1. 예상 공모가:</b> ${p:,.2f}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>2. 공모 규모:</b> ${(p*s/1000000):,.1f}M USD</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>3. 상장 거래소:</b> {stock.get('exchange', 'NYSE/NASDAQ')}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>4. 보호예수 기간:</b> 상장 후 180일</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>5. 주요 주간사:</b> 글로벌 Top-tier 투자은행</div>", unsafe_allow_html=True)

        with tab2:
            st.subheader("⚖️ AI 가치 평가 (학술 모델)")
            fp_min, fp_max = p * 1.12, p * 1.38
            ca, cb = st.columns(2)
            with ca:
                st.metric("AI 추정 적정가 범위", f"${fp_min:,.2f} ~ ${fp_max:,.2f}")
                st.markdown("#### **참조 모델**\n- Ritter(1991) IPO 성과 분석\n- Fama-French 5-Factor")
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
            st.write(f"유니콘 지수: {int(uv/(uv+fv)*100)}% ({uv+fv}명 참여)")
            st.markdown("</div>", unsafe_allow_html=True)

            st.write("**2. 커뮤니티 의견**")
            nc = st.text_input("의견 등록", key=f"ci_{sid}")
            if st.button("등록", key=f"cb_{sid}") and nc:
                st.session_state.comment_data[sid].insert(0, {"t": nc, "d": "방금 전"}); st.rerun()
            for c in st.session_state.comment_data[sid][:3]:
                st.markdown(f"<div class='comment-box'><small>{c['d']}</small><br>{c['t']}</div>", unsafe_allow_html=True)

            st.write("---")
            st.write("**3. 마이 리서치 보관함**")
            if sid not in st.session_state.watchlist:
                if st.button("⭐ 관심 종목으로 등록하고 상장 알림 받기", use_container_width=True, type="primary", key=f"reg_{sid}"):
                    st.session_state.watchlist.append(sid); st.balloons(); st.toast("보관함 추가 완료!"); st.rerun()
            else:
                st.success(f"✅ {stock['name']} 종목이 보관함에 저장되어 있습니다.")
                if st.button("❌ 관심 종목 해제", key=f"del_{sid}"):
                    st.session_state.watchlist.remove(sid); st.rerun()

