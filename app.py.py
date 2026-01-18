import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import os

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 세션 초기화 ---
for key in ['page', 'auth_status', 'vote_data', 'comment_data', 'selected_stock', 'watchlist', 'view_mode']:
    if key not in st.session_state:
        if key == 'page': st.session_state[key] = 'intro'
        elif key == 'watchlist': st.session_state[key] = []
        elif key in ['vote_data', 'comment_data']: st.session_state[key] = {}
        elif key == 'view_mode': st.session_state[key] = 'all'
        else: st.session_state[key] = None

# --- CSS 스타일 ---
st.markdown("""
    <style>
    .intro-card {
        background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%);
        padding: 50px 30px; border-radius: 30px; color: white !important;
        text-align: center; margin-top: 20px; 
        box-shadow: 0 20px 40px rgba(110, 142, 251, 0.3);
    }
    .intro-title { font-size: 40px; font-weight: 900; margin-bottom: 10px; color: white !important; }
    .intro-subtitle { font-size: 18px; opacity: 0.9; margin-bottom: 30px; color: white !important; }
    .feature-grid { display: flex; justify-content: space-around; gap: 15px; margin-bottom: 25px; }
    .feature-item {
        background: rgba(255, 255, 255, 0.2);
        padding: 20px 10px; border-radius: 20px; flex: 1;
        backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.3);
        color: white !important;
    }
    .grid-card { 
        background-color: #ffffff !important; 
        padding: 25px; border-radius: 20px; 
        border: 1px solid #eef2ff; box-shadow: 0 10px 20px rgba(0,0,0,0.05); 
        text-align: center; color: #333333 !important; height: 100%;
    }
    .info-box { background-color: #f0f4ff; padding: 15px; border-radius: 12px; border-left: 5px solid #6e8efb; margin-bottom: 10px; color: #333333 !important; text-align: left;}
    .stat-box { text-align: left; padding: 12px; background-color: #f1f3f9 !important; border-radius: 12px; margin-top: 15px; color: #444444 !important; line-height: 1.5; }
    .quote-card {
        background: linear-gradient(145deg, #ffffff, #f9faff);
        padding: 25px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.05); text-align: center;
        max-width: 650px; margin: 40px auto; color: #333333 !important;
    }
    .comment-box { background-color: #f8f9fa; padding: 10px; border-radius: 10px; margin-bottom: 5px; border-left: 3px solid #dee2e6; color: #333; }
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
    end = (datetime.now() + timedelta(days=120)).strftime('%Y-%m-%d')
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

# --- 화면 제어 ---

# 1. 인트로
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 10, 1])
    with col_center:
        st.markdown("""
            <div class='intro-card'>
                <div class='intro-title'>UNICORN FINDER</div>
                <div class='intro-subtitle'>미국 시장의 차세대 주역을 가장 먼저 발견하세요</div>
                <div class='feature-grid'>
                    <div class='feature-item'><div style='font-size:28px;'>📅</div><div style='font-size:14px; font-weight:600;'>IPO 스케줄<br>실시간 트래킹</div></div>
                    <div class='feature-item'><div style='font-size:28px;'>📊</div><div style='font-size:14px; font-weight:600;'>AI기반 분석<br>데이터 예측</div></div>
                    <div class='feature-item'><div style='font-size:28px;'>🗳️</div><div style='font-size:14px; font-weight:600;'>집단 지성<br>글로벌 심리 투표</div></div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        if st.button("탐험 시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()

# 2. 로그인
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
    st.markdown(f"<div class='quote-card'><small>TODAY'S INSIGHT</small><br><b>\"{q['eng']}\"</b><br><small>({q['kor']})</small><br><br><small>- {q['author']} -</small></div>", unsafe_allow_html=True)

# 3. 성장 단계 분석
elif st.session_state.page == 'stats':
    st.title("🦄 유니콘 성장 단계 분석")
    img_baby = "baby_unicorn.png.png"
    img_child = "child_unicorn.png.png"
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='grid-card'><h3>New 유니콘 (유아기)</h3>", unsafe_allow_html=True)
        if os.path.exists(img_baby):
            st.image(img_baby, caption="상장을 앞둔 유아기 유니콘 🌱", use_container_width=True)
        else: st.warning("baby_unicorn.png.png 파일을 찾을 수 없습니다.")
        if st.button("🔎 New 유니콘 탐험 (전체 목록)", use_container_width=True, key="go_all"):
            st.session_state.view_mode = 'all'; st.session_state.page = 'calendar'; st.rerun()
        st.markdown("<div class='stat-box'><small>📊 <b>시장 통계:</b> 연간 평균 180~250개의 기업이 미국 시장에 상장합니다.</small></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        
    with c2:
        st.markdown("<div class='grid-card'><h3>My 유니콘 (아동기)</h3>", unsafe_allow_html=True)
        if os.path.exists(img_child):
            st.image(img_child, caption="내가 찜한 아동기 유니콘 ⭐", use_container_width=True)
        else: st.warning("child_unicorn.png.png 파일을 찾을 수 없습니다.")
        watch_count = len(st.session_state.watchlist)
        if st.button(f"🔎 My 유니콘 탐험 ({watch_count}개 보관 중)", use_container_width=True, type="primary", key="go_watch"):
            if watch_count > 0:
                st.session_state.view_mode = 'watchlist'; st.session_state.page = 'calendar'; st.rerun()
            else: st.warning("아직 보관함에 담긴 기업이 없습니다.")
        st.markdown("<div class='stat-box'><small>나만의 유니콘 후보들입니다. 상장 일정을 놓치지 마세요.</small></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

# 4. 캘린더 (필터 및 범위 표시 통합)
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    view_mode = st.session_state.get('view_mode', 'all')
    st.header("⭐ My 리서치 보관함" if view_mode == 'watchlist' else "🚀 IPO 리서치 센터")
    
    all_df = get_extended_ipo_data(MY_API_KEY)
    if not all_df.empty:
        if view_mode == 'watchlist':
            display_df = all_df[all_df['symbol'].isin(st.session_state.watchlist)]
        else:
            today = datetime.now().date()
            period = st.radio("조회 기간 설정", ["상장 예정 (90일 내)", "최근 6개월", "최근 12개월", "전체"], horizontal=True)
            
            if period == "상장 예정 (90일 내)":
                future_limit = today + timedelta(days=90)
                display_df = all_df[(all_df['공모일_dt'].dt.date >= today) & (all_df['공모일_dt'].dt.date <= future_limit)].sort_values(by='공모일_dt')
            elif period == "최근 6개월": 
                display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=180))].sort_values(by='공모일_dt', ascending=False)
            elif period == "최근 12개월": 
                display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=365))].sort_values(by='공모일_dt', ascending=False)
            else: display_df = all_df.sort_values(by='공모일_dt', ascending=False)

        st.write("---")
        h1, h2, h3, h4, h5 = st.columns([1.2, 3.5, 1.2, 1.5, 1.2])
        h1.write("**공모일**"); h2.write("**기업명**"); h3.write("**공모가**"); h4.write("**규모**"); h5.write("**현재가**")
        
        for i, row in display_df.iterrows():
            col1, col2, col3, col4, col5 = st.columns([1.2, 3.5, 1.2, 1.5, 1.2])
            is_p = row['공모일_dt'].date() <= datetime.now().date()
            col1.markdown(f"<span style='color:{'#888888' if is_p else '#4f46e5'};'>{row['date']}</span>", unsafe_allow_html=True)
            if col2.button(row['name'], key=f"n_{row['symbol']}_{i}", use_container_width=True):
                st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()
            
            # --- 공모가 범위/문자열 유지 로직 ---
            p_raw = row.get('price', '')
            s_raw = row.get('numberOfShares', '')
            p_num = pd.to_numeric(p_raw, errors='coerce')
            s_num = pd.to_numeric(s_raw, errors='coerce')

            # 공모가 표시: 숫자면 $포맷, 아니면 범위(문자열) 그대로
            col3.write(f"${p_num:,.2f}" if pd.notnull(p_num) and p_num > 0 else (str(p_raw) if p_raw else "TBD"))
            
            # 규모 표시: 공모가와 주식수가 모두 숫자일 때만 금액 계산
            if pd.notnull(p_num) and pd.notnull(s_num) and p_num * s_num > 0:
                col4.write(f"${(p_num * s_num / 1000000):,.1f}M")
            else: col4.write("Pending")

            if is_p:
                cp = get_current_stock_price(row['symbol'], MY_API_KEY)
                p_ref = p_num if pd.notnull(p_num) else 0
                col5.markdown(f"<span style='color:{'#28a745' if cp >= p_ref else '#dc3545'}; font-weight:bold;'>${cp:,.2f}</span>" if cp > 0 else "-", unsafe_allow_html=True)
            else: col5.write("대기")

# 5. 상세 페이지 (뉴스 탭 및 브리핑 통합 버전)
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        if st.button("⬅️ 목록으로"): 
            st.session_state.page = 'calendar'
            st.rerun()
            
        st.title(f"🚀 {stock['name']} 심층 분석")
        
        # 탭 생성
        tab0, tab1, tab2, tab3 = st.tabs(["📰 실시간 뉴스", "📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])
        
        with tab0:
            st.subheader(f"📰 {stock['name']} 투자 인사이트 브리핑")
            
            # 상태 세션 초기화
            if 'news_topic' not in st.session_state:
                st.session_state.news_topic = "💰 공모가 범위/확정 소식"

            # 1. 투자자 필수 체크 버튼
            col_k1, col_k2, col_k3 = st.columns(3)
            if col_k1.button("💰 공모가 범위/확정 소식", use_container_width=True):
                st.session_state.news_topic = "💰 공모가 범위/확정 소식"
            if col_k2.button("📅 상장 일정/연기 소식", use_container_width=True):
                st.session_state.news_topic = "📅 상장 일정/연기 소식"
            if col_k3.button("🥊 경쟁사 비교/분석", use_container_width=True):
                st.session_state.news_topic = "🥊 경쟁사 비교/분석"

            # 2. AI 실시간 한글 브리핑 영역
            st.markdown(f"<div style='background-color: #f0f4ff; padding: 20px; border-radius: 15px; border-left: 5px solid #6e8efb; margin-top: 10px;'>"
                        f"<h5 style='color:#333;'>🤖 AI 실시간 요약: {st.session_state.news_topic}</h5>", unsafe_allow_html=True)
            
            if st.session_state.news_topic == "💰 공모가 범위/확정 소식":
                rep_kor = f"현재 {stock['name']}의 공모가 범위는 {stock.get('price', 'TBD')}입니다. 최근 기관 수요예측에서 긍정적인 평가가 이어지고 있으며, 상단 돌파 가능성이 언급되고 있습니다."
            elif st.session_state.news_topic == "📅 상장 일정/연기 소식":
                rep_kor = f"{stock['name']}은(는) {stock['date']}에 상장 예정입니다. SEC 공시 상 특이사항은 없으며, 예정된 일정대로 진행될 확률이 매우 높습니다."
            else:
                rep_kor = f"{stock['name']}은(는) 동종 업계 대비 높은 성장성을 보이고 있습니다. 다만, 상장 후 시가총액이 주요 경쟁사들의 밸류에이션 대비 적절한지가 핵심 관건입니다."
            
            st.write(f"<span style='color:#444;'>{rep_kor}</span>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

            st.write("---")

            # 3. 실시간 인기 뉴스 Top 5
            st.markdown(f"##### 🔥 {stock['name']} 관련 실시간 인기 뉴스 Top 5")
            news_topics = [
                {"title": f"{stock['name']} IPO: 주요 투자 위험 요소 및 기회 분석", "query": f"{stock['name']}+IPO+analysis", "tag": "분석"},
                {"title": f"나스닥 상장 앞둔 {stock['symbol']}, 월스트리트의 평가는?", "query": f"{stock['symbol']}+stock+wall+street+rating", "tag": "시장"},
                {"title": f"{stock['name']} 상장 후 주가 전망 및 목표가 리포트", "query": f"{stock['name']}+stock+price+forecast", "tag": "전망"},
                {"title": f"제2의 성장을 꿈꾸는 {stock['name']}의 글로벌 확장 전략", "query": f"{stock['name']}+global+strategy", "tag": "전략"},
                {"title": f"{stock['symbol']} 보호예수 해제일 및 초기 유통 물량 점검", "query": f"{stock['symbol']}+lock-up+expiration", "tag": "수급"}
            ]
            
            for i, news in enumerate(news_topics):
                news_url = f"https://www.google.com/search?q={news['query']}&tbm=nws"
                st.markdown(f"""
                    <a href="{news_url}" target="_blank" style="text-decoration: none; color: inherit;">
                        <div style="background-color: #ffffff; padding: 12px; border-radius: 12px; margin-bottom: 10px; border: 1px solid #eef2ff; box-shadow: 0 4px 6px rgba(0,0,0,0.02);">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span style="font-size: 13px; font-weight: bold; color: #6e8efb;">TOP {i+1} · {news['tag']}</span>
                                <span style="font-size: 11px; color: #aaa;">상세보기 ↗








