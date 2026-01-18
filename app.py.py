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

# 5. 상세 페이지 (뉴스 탭 추가)
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        st.title(f"🚀 {stock['name']} 심층 분석")
        
        # 탭 구성 수정: 뉴스 탭 추가
        tab0, tab1, tab2, tab3 = st.tabs(["📰 실시간 뉴스", "📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])
        
        with tab0:
            st.subheader(f"📰 {stock['name']} 실시간 인기 뉴스")
            
            # 1. 투자자 필수 체크 버튼 (상단 배치)
            col_k1, col_k2, col_k3 = st.columns(3)
            with col_k1:
                st.link_button("💰 공모가 범위/확정 소식", f"https://www.google.com/search?q={stock['name']}+IPO+pricing+range", use_container_width=True)
            with col_k2:
                st.link_button("📅 상장 일정/연기 소식", f"https://www.google.com/search?q={stock['name']}+IPO+date+schedule", use_container_width=True)
            with col_k3:
                st.link_button("🥊 경쟁사 비교/분석", f"https://www.google.com/search?q={stock['name']}+vs+competitors+analysis", use_container_width=True)

            st.write("---")
            
            c_left, c_right = st.columns([1.8, 1.2])
            
            with c_left:
                st.markdown(f"##### 🔥 {stock['name']} 관련 조회수 급증 뉴스 Top 5")
                
                # 기업별 맞춤형 검색 키워드 리스트
                # 실제 API 연동 전까지는 기업명을 포함한 최적의 검색 링크 5개를 생성합니다.
                news_topics = [
                    {"title": f"{stock['name']} IPO: 핵심 사업 모델 및 수익성 분석", "query": f"{stock['name']}+business+model+analysis", "tag": "분석"},
                    {"title": f"기관 투자자들이 주목하는 {stock['symbol']} 투자 포인트", "query": f"{stock['symbol']}+stock+investment+points", "tag": "기관"},
                    {"title": f"{stock['name']} 상장 첫날 예상 시가총액은?", "query": f"{stock['name']}+IPO+market+cap+forecast", "tag": "예측"},
                    {"title": f"최근 24시간 {stock['name']} 마켓 센티먼트 리포트", "query": f"{stock['name']}+market+sentiment", "tag": "심리"},
                    {"title": f"{stock['symbol']} 상장 이후 보호예수(Lock-up) 물량 체크", "query": f"{stock['symbol']}+IPO+lock-up+period", "tag": "일정"}
                ]
                
                for i, news in enumerate(news_topics):
                    # 클릭 시 구글 뉴스 검색 결과로 이동하는 링크 생성
                    news_url = f"https://www.google.com/search?q={news['query']}&tbm=nws"
                    
                    st.markdown(f"""
                        <a href="{news_url}" target="_blank" style="text-decoration: none; color: inherit;">
                            <div style="background-color: #f8f9fa; padding: 12px; border-radius: 12px; margin-bottom: 10px; border-left: 5px solid #6e8efb; transition: 0.3s;">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <span style="font-size: 14px; font-weight: bold; color: #6e8efb;">TOP {i+1} · {news['tag']}</span>
                                    <span style="font-size: 12px; color: #888;">실시간 조회중 👁️</span>
                                </div>
                                <div style="margin-top: 5px; font-size: 16px; font-weight: 600; color: #333;">{news['title']}</div>
                                <div style="margin-top: 5px; font-size: 12px; color: #007bff; text-align: right;">뉴스 원문 보기 ↗</div>
                            </div>
                        </a>
                    """, unsafe_allow_html=True)

            with c_right:
                st.markdown("##### 📈 마켓 관심도")
                st.write("")
                # 관심도 시각화 카드
                st.markdown(f"""
                    <div style="background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%); padding: 20px; border-radius: 20px; color: white; text-align: center;">
                        <small>현재 {stock['symbol']} 검색 지수</small>
                        <div style="font-size: 32px; font-weight: 900; margin: 10px 0;">HOT 🔥</div>
                        <div style="font-size: 14px; opacity: 0.9;">뉴스 업데이트 속도: 매우 빠름</div>
                    </div>
                """, unsafe_allow_html=True)
                
                st.write("")
                st.markdown("##### 🔗 주요 금융 채널")
                st.markdown(f"""
                * 📊 [Yahoo Finance 피드](https://finance.yahoo.com/quote/{stock['symbol']})
                * 🌐 [Bloomberg IPO 섹션](https://www.bloomberg.com/search?query={stock['name']})
                * 🗞️ [Seeking Alpha 분석](https://seekingalpha.com/search?q={stock['name']})
                """)

        with tab1:
            st.subheader("🔍 투자자 검색 상위 5대 지표")
            c1, c2 = st.columns([1, 2.5])
            # (기존 로고 및 핵심 정보 코드 유지)
            with c1: st.image(f"https://logo.clearbit.com/{stock['symbol']}.com", width=200)
            with c2:
                p_n = pd.to_numeric(stock.get('price'), errors='coerce') or 0
                s_n = pd.to_numeric(stock.get('numberOfShares'), errors='coerce') or 0
                st.markdown(f"<div class='info-box'><b>1. 예상 공모가:</b> {stock.get('price', 'TBD')}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>2. 공모 규모:</b> ${(p_n*s_n/1000000):,.1f}M USD (예정)</div>" if p_n*s_n > 0 else "<div class='info-box'><b>2. 공모 규모:</b> 분석 중</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>3. 상장 거래소:</b> {stock.get('exchange', 'NYSE/NASDAQ')}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>4. 보호예수 기간:</b> 상장 후 180일</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-box'><b>5. 주요 주간사:</b> 글로벌 Top-tier IB</div>", unsafe_allow_html=True)
            
            st.write("---")
            cc1, cc2 = st.columns(2)
            with cc1:
                st.subheader("📑 주요 기업 공시 (SEC)")
                search_name = stock['name'].replace(" ", "+")
                st.markdown(f"[🔗 SEC 공식 홈페이지 검색](https://www.sec.gov/edgar/search/#/q={search_name})")
            with cc2:
                st.subheader("📊 핵심 재무 요약")
                f_data = {"항목": ["매출 성장률", "영업 이익률", "현금 흐름"], "수치": ["+45.2%", "-12.5%", "Positive"]}
                st.table(pd.DataFrame(f_data))

        with tab2:
            st.subheader("⚖️ AI 가치 평가")
            p_n = pd.to_numeric(stock.get('price'), errors='coerce') or 20.0
            st.metric("AI 추정 적정가 범위", f"${p_n*1.12:,.2f} ~ ${p_n*1.38:,.2f}")
            st.progress(0.65); st.success(f"평균 **12%~38%** 추가 상승 가능성")

        with tab3:
            sid = stock['symbol']
            if sid not in st.session_state.vote_data: st.session_state.vote_data[sid] = {'u': 10, 'f': 3}
            if sid not in st.session_state.comment_data: st.session_state.comment_data[sid] = []
            
            st.write("**1. 투자 매력도 투표**")
            v1, v2 = st.columns(2)
            if v1.button("🦄 Unicorn", use_container_width=True, key=f"vu_{sid}"): 
                st.session_state.vote_data[sid]['u'] += 1; st.rerun()
            if v2.button("💸 Fallen Angel", use_container_width=True, key=f"vf_{sid}"): 
                st.session_state.vote_data[sid]['f'] += 1; st.rerun()
            
            uv, fv = st.session_state.vote_data[sid]['u'], st.session_state.vote_data[sid]['f']
            st.progress(uv/(uv+fv)); st.write(f"유니콘 지수: {int(uv/(uv+fv)*100)}% ({uv+fv}명 참여)")

            st.write("**2. 커뮤니티 의견**")
            nc = st.text_input("의견 등록", key=f"ci_{sid}")
            if st.button("등록", key=f"cb_{sid}") and nc:
                st.session_state.comment_data[sid].insert(0, {"t": nc, "d": "방금 전"}); st.rerun()
            for c in st.session_state.comment_data[sid][:3]:
                st.markdown(f"<div class='comment-box'><small>{c['d']}</small><br>{c['t']}</div>", unsafe_allow_html=True)

            st.write("---")
            if sid not in st.session_state.watchlist:
                if st.button("⭐ 마이 리서치 보관함에 담기", use_container_width=True, type="primary"):
                    st.session_state.watchlist.append(sid); st.balloons(); st.toast("보관함 추가 완료!"); st.rerun()
            else:
                st.success(f"✅ {stock['name']} 종목이 보관함에 저장되어 있습니다.")
                if st.button("❌ 관심 종목 해제"): st.session_state.watchlist.remove(sid); st.rerun()





