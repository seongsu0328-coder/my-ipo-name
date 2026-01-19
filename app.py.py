import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import xml.etree.ElementTree as ET  # [필수] 뉴스 RSS 파싱용

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 세션 상태 초기화 (데이터 유지용) ---
session_keys = {
    'page': 'intro',
    'auth_status': None,
    'vote_data': {},      # 종목별 투표 현황
    'comment_data': {},   # 종목별 댓글 리스트
    'user_votes': {},     # 사용자의 투표 기록 (중복 방지)
    'selected_stock': None,
    'watchlist': [],      # 관심 종목 리스트
    'view_mode': 'all',   # 캘린더 보기 모드 (all/hot/watchlist)
    'news_topic': '💰 공모가 범위/확정 소식',
    'login_step': 'choice'
}

for key, default_val in session_keys.items():
    if key not in st.session_state:
        st.session_state[key] = default_val

# --- API 키 설정 ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

# --- CSS 스타일 (전체 디자인) ---
st.markdown("""
    <style>
    /* 전체 배경 흰색 강제 및 폰트 색상 고정 */
    .stApp {
        background-color: #FFFFFF;
        color: #333333;
    }
    
    /* 인트로 카드 스타일 */
    .intro-card {
        background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%);
        padding: 50px 30px; border-radius: 30px; color: white !important;
        text-align: center; margin-top: 20px; 
        box-shadow: 0 20px 40px rgba(110, 142, 251, 0.3);
    }
    .intro-title { font-size: 40px; font-weight: 900; margin-bottom: 10px; color: white !important; }
    
    /* 인트로 아이콘 그리드 */
    .feature-grid { display: flex; justify-content: space-around; gap: 15px; margin-bottom: 25px; }
    .feature-item {
        background: rgba(255, 255, 255, 0.2);
        padding: 20px 10px; border-radius: 20px; flex: 1;
        backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.3);
        color: white !important; text-align: center;
    }
    
    /* 메인 대시보드 카드 */
    .grid-card { 
        background-color: #ffffff !important; 
        padding: 25px; border-radius: 20px; 
        border: 1px solid #eef2ff; box-shadow: 0 10px 20px rgba(0,0,0,0.05); 
        text-align: center; color: #333333 !important; height: 100%;
    }
    .grid-card h3 { margin-bottom: 15px; color: #6e8efb; }
    
    /* 명언 카드 */
    .quote-card {
        background: linear-gradient(145deg, #ffffff, #f9faff);
        padding: 25px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.05); text-align: center;
        max-width: 650px; margin: 40px auto; color: #333333 !important;
    }
    
    /* 댓글 박스 */
    .comment-box { 
        background-color: #f8f9fa; padding: 15px; border-radius: 12px; 
        margin-bottom: 10px; border-left: 3px solid #6e8efb; 
    }
    
    /* 버튼 텍스트 가독성 */
    button p { font-weight: bold !important; }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 로직 함수 모음 ---

@st.cache_data(ttl=43200)
def get_daily_quote():
    """로그인 화면의 명언 가져오기"""
    try:
        res = requests.get("https://api.quotable.io/random?tags=business", timeout=3).json()
        return {"eng": res['content'], "author": res['author']}
    except:
        return {"eng": "Opportunities don't happen. You create them.", "author": "Chris Grosser"}

@st.cache_data(ttl=300)
def get_real_news_rss(company_name):
    """구글 뉴스 RSS를 통해 실시간 기사 제목과 링크 가져오기"""
    try:
        query = f"{company_name} stock IPO"
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        response = requests.get(url, timeout=3)
        root = ET.fromstring(response.content)
        
        news_items = []
        for item in root.findall('./channel/item')[:5]:
            title = item.find('title').text
            link = item.find('link').text
            pubDate = item.find('pubDate').text
            try:
                # 날짜 포맷 단순화 (예: Mon, 15 Jan -> 15 Jan)
                date_str = " ".join(pubDate.split(' ')[1:3])
            except:
                date_str = "Recent"
            news_items.append({"title": title, "link": link, "date": date_str})
        return news_items
    except:
        return []

@st.cache_data(ttl=86400)
def get_financial_metrics(symbol, api_key):
    """재무 지표(성장률, 이익률 등) 가져오기"""
    try:
        url = f"https://finnhub.io/api/v1/stock/metric?symbol={symbol}&metric=all&token={api_key}"
        res = requests.get(url, timeout=5).json()
        metrics = res.get('metric', {})
        if not metrics: return None
        return {
            "growth": metrics.get('salesGrowthYoy', None),
            "op_margin": metrics.get('operatingMarginTTM', None),
            "net_margin": metrics.get('netProfitMarginTTM', None),
            "debt_equity": metrics.get('totalDebt/totalEquityQuarterly', None)
        }
    except: return None

@st.cache_data(ttl=86400)
def get_company_profile(symbol, api_key):
    """기업 프로필(사업 요약, 업종 등) 가져오기"""
    try:
        url = f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={api_key}"
        res = requests.get(url, timeout=5).json()
        return res if res and 'name' in res else None
    except: return None

@st.cache_data(ttl=600)
def get_extended_ipo_data(api_key):
    """IPO 캘린더 데이터 가져오기"""
    start = (datetime.now() - timedelta(days=540)).strftime('%Y-%m-%d')
    end = (datetime.now() + timedelta(days=120)).strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/calendar/ipo?from={start}&to={end}&token={api_key}"
    try:
        res = requests.get(url, timeout=5).json()
        df = pd.DataFrame(res.get('ipoCalendar', []))
        if not df.empty: 
            df['공모일_dt'] = pd.to_datetime(df['date'])
        return df
    except: return pd.DataFrame()

def get_current_stock_price(symbol, api_key):
    """실시간 주가 조회"""
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
        return requests.get(url, timeout=2).json().get('c', 0)
    except: return 0

# ==========================================
# [화면 흐름 제어 (Page Router)]
# ==========================================

# 1. 인트로 페이지
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 10, 1])
    with col_center:
        st.markdown("""
            <div class='intro-card'>
                <div class='intro-title'>Unicornfinder</div>
                <div style='margin-bottom:30px; font-size:18px;'>미국 IPO 시장의 미래를 만나보세요</div>
                <div class='feature-grid'>
                    <div class='feature-item'><div style='font-size:24px;'>📅</div>IPO 스케줄</div>
                    <div class='feature-item'><div style='font-size:24px;'>📊</div>AI 가격 예측</div>
                    <div class='feature-item'><div style='font-size:24px;'>🗳️</div>투자자 투표</div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        if st.button("시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()

# 2. 로그인 페이지
elif st.session_state.page == 'login':
    st.write("<br>" * 5, unsafe_allow_html=True)
    _, col_m, _ = st.columns([1, 1.2, 1])
    with col_m:
        if st.session_state.login_step == 'choice':
            if st.button("📱 회원으로 시작하기", use_container_width=True):
                st.session_state.login_step = 'ask_signup'; st.rerun()
            if st.button("👀 비회원으로 시작하기", use_container_width=True):
                st.session_state.auth_status = 'guest'
                st.session_state.page = 'stats'; st.rerun()
        
        elif st.session_state.login_step == 'ask_signup':
            st.info("회원 가입 시 관심 종목 알림을 받을 수 있습니다.")
            c1, c2 = st.columns(2)
            if c1.button("✅ 진행하기", use_container_width=True):
                st.session_state.login_step = 'input_phone'; st.rerun()
            if c2.button("❌ 취소", use_container_width=True):
                st.session_state.login_step = 'choice'; st.rerun()

        elif st.session_state.login_step == 'input_phone':
            st.markdown("##### 📱 휴대폰 번호 입력")
            phone = st.text_input("번호 입력", placeholder="010-0000-0000")
            if st.button("가입 및 시작", use_container_width=True):
                if len(phone) >= 10:
                    st.session_state.auth_status = 'user'
                    st.session_state.page = 'stats'
                    st.rerun()
                else:
                    st.error("올바른 번호를 입력해주세요.")
            if st.button("뒤로가기"):
                st.session_state.login_step = 'choice'; st.rerun()

    q = get_daily_quote()
    st.markdown(f"<div class='quote-card'><b>\"{q['eng']}\"</b><br><br><small>- {q['author']} -</small></div>", unsafe_allow_html=True)

# 3. 메인 대시보드 (New/Hot/My)
elif st.session_state.page == 'stats':
    st.write("<br>", unsafe_allow_html=True)
    img_baby = "baby_unicorn.png.png"
    img_adult = "adult_unicorn.png.png"
    img_child = "child_unicorn.png.png"
    
    c1, c2, c3 = st.columns(3)
    
    # 1. NEW
    with c1:
        st.markdown("<div class='grid-card'><h3>NEW</h3>", unsafe_allow_html=True)
        if os.path.exists(img_baby): st.image(img_baby, use_container_width=True)
        if st.button("전체 보기", key="go_all", use_container_width=True):
            st.session_state.view_mode = 'all'
            st.session_state.page = 'calendar'; st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # 2. HOT
    with c2:
        st.markdown("<div class='grid-card'><h3>HOT</h3>", unsafe_allow_html=True)
        if os.path.exists(img_adult): st.image(img_adult, use_container_width=True)
        if st.button("주목할 종목", key="go_hot", use_container_width=True):
            st.session_state.view_mode = 'hot'
            st.session_state.page = 'calendar'; st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # 3. MY
    with c3:
        st.markdown("<div class='grid-card'><h3>MY</h3>", unsafe_allow_html=True)
        if os.path.exists(img_child): st.image(img_child, use_container_width=True)
        cnt = len(st.session_state.watchlist)
        if st.button(f"내 보관함 ({cnt})", key="go_watch", use_container_width=True, type="primary"):
            st.session_state.view_mode = 'watchlist'
            st.session_state.page = 'calendar'; st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

# 4. 캘린더 페이지 (리스트 뷰)
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 메인으로", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    
    all_df = get_extended_ipo_data(MY_API_KEY)
    
    if not all_df.empty:
        # 데이터 정제
        all_df = all_df.dropna(subset=['exchange'])
        all_df = all_df[all_df['symbol'].str.strip() != ""]
        today = datetime.now().date()
        
        # 필터링 로직
        if st.session_state.view_mode == 'watchlist':
            display_df = all_df[all_df['symbol'].isin(st.session_state.watchlist)]
            st.title("⭐ 나의 관심 종목")
        else:
            period = st.radio("기간 설정", ["예정 (90일)", "최근 6개월", "최근 1년"], horizontal=True)
            if period == "예정 (90일)":
                display_df = all_df[(all_df['공모일_dt'].dt.date >= today) & (all_df['공모일_dt'].dt.date <= today + timedelta(days=90))]
            elif period == "최근 6개월":
                display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=180))]
            else:
                display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=365))]

        # 리스트 렌더링
        if not display_df.empty:
            st.write("---")
            # 헤더
            cols = st.columns([0.6, 1.2, 2.5, 1.2, 1.2, 1.2, 1.2])
            headers = ["", "공모일", "기업명", "공모가", "규모", "현재가", "거래소"]
            for c, h in zip(cols, headers): c.write(f"**{h}**")

            # 데이터 로우
            for i, row in display_df.iterrows():
                c_icon, c_date, c_name, c_price, c_size, c_curr, c_exch = st.columns([0.6, 1.2, 2.5, 1.2, 1.2, 1.2, 1.2])
                
                # 아이콘 결정 (1년 기준)
                is_baby = row['공모일_dt'].date() > (today - timedelta(days=365))
                icon = "🐣" if is_baby else "🦄"
                bg = "#fff9db" if is_baby else "#f3f0ff"
                
                c_icon.markdown(f"<div style='background:{bg}; width:40px; height:40px; border-radius:10px; text-align:center; padding-top:5px; font-size:20px;'>{icon}</div>", unsafe_allow_html=True)
                c_date.write(row['date'])
                
                with c_name:
                    if st.button(f"{row['name']} ({row['symbol']})", key=f"btn_{row['symbol']}_{i}", use_container_width=True):
                        st.session_state.selected_stock = row.to_dict()
                        st.session_state.page = 'detail'
                        st.rerun()
                
                c_price.write(row.get('price', '-'))
                # 규모 계산 (Price * Shares / 1,000,000)
                try:
                    p = float(str(row.get('price','0')).split('-')[0].replace('$',''))
                    s = int(row.get('numberOfShares',0) or 0)
                    size_val = f"${p*s/1000000:,.0f}M" if p*s > 0 else "-"
                except: size_val = "-"
                c_size.write(size_val)
                
                c_curr.write("-") # 리스트에서는 현재가 생략 (속도 최적화)
                c_exch.write(row.get('exchange', '-'))
        else:
            st.info("조건에 맞는 종목이 없습니다.")

# 5. 상세 페이지 (RSS 뉴스, 예외 처리, 투표/댓글 통합)
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        today = datetime.now().date()
        try:
            ipo_dt = stock['공모일_dt'].date() if hasattr(stock['공모일_dt'], 'date') else pd.to_datetime(stock['공모일_dt']).date()
        except: ipo_dt = today
        
        status_emoji = "🐣" if ipo_dt > (today - timedelta(days=365)) else "🦄"

        if st.button("⬅️ 목록으로"): 
            st.session_state.page = 'calendar'; st.rerun()

        # 데이터 로딩 (Spinner 적용)
        with st.spinner(f"🤖 {stock['name']} 데이터를 분석 중입니다..."):
            try:
                off_val = float(str(stock.get('price', '0')).replace('$', '').split('-')[0].strip())
            except: off_val = 0
            
            # API 호출
            try:
                current_p = get_current_stock_price(stock['symbol'], MY_API_KEY)
                if current_p == 0: st.toast("⚠️ 실시간 주가를 가져오지 못했습니다.", icon="☕")
                profile = get_company_profile(stock['symbol'], MY_API_KEY)
                fin_data = get_financial_metrics(stock['symbol'], MY_API_KEY)
            except:
                current_p, profile, fin_data = 0, None, None

        # 수익률 디자인 적용
        if current_p > 0 and off_val > 0:
            pct = ((current_p - off_val) / off_val) * 100
            color = "#00ff41" if pct >= 0 else "#ff4b4b"
            icon = "▲" if pct >= 0 else "▼"
            p_html = f"(공모 ${off_val} / 현재 ${current_p} <span style='color:{color}'><b>{icon} {abs(pct):.1f}%</b></span>)"
        else:
            p_html = f"(공모 ${off_val} / 상장 대기)"

        st.markdown(f"<h1>{status_emoji} {stock['name']} <small>{p_html}</small></h1>", unsafe_allow_html=True)
        st.write("---")

        # 4개의 탭 구성
        t0, t1, t2, t3 = st.tabs(["📰 실시간 뉴스", "📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])

        # Tab 0: 실시간 뉴스 (RSS)
        with t0:
            st.markdown(f"##### 🔥 {stock['name']} 실시간 주요 뉴스 (Google News)")
            rss_news = get_real_news_rss(stock['name'])
            
            if rss_news:
                for n in rss_news:
                    st.markdown(f"""
                        <a href="{n['link']}" target="_blank" style="text-decoration:none; color:inherit;">
                            <div style="padding:15px; background:white; border-radius:10px; border:1px solid #eee; margin-bottom:10px; box-shadow:0 2px 5px rgba(0,0,0,0.02);">
                                <div style="display:flex; justify-content:space-between;">
                                    <span style="font-weight:bold; font-size:15px; color:#333;">{n['title']}</span>
                                    <span style="font-size:12px; color:#888;">{n['date']}</span>
                                </div>
                            </div>
                        </a>
                    """, unsafe_allow_html=True)
            else:
                st.info("실시간 뉴스를 가져오지 못해 검색 링크를 제공합니다.")
                url = f"https://www.google.com/search?q={stock['name']}+stock+news&tbm=nws"
                st.markdown(f"👉 [Google 뉴스 검색 바로가기]({url})")

        # Tab 1: 핵심 정보
        with t1:
            c1, c2 = st.columns([1.5, 1])
            with c1:
                st.markdown(f"#### 📑 비즈니스 요약")
                desc = profile.get('description', '정보 확인 중...') if profile else "API 호출 한도 초과 (잠시 후 다시 시도)"
                st.markdown(f"<div style='background:#f8f9fa; padding:15px; border-radius:10px; line-height:1.6;'>{desc}</div>", unsafe_allow_html=True)
                st.markdown(f"[SEC EDGAR 공시 원문](https://www.sec.gov/edgar/search/#/q={stock['name'].replace(' ','%20')})")
            with c2:
                st.markdown("#### 📊 재무 현황 (TTM)")
                if fin_data:
                    df_fin = pd.DataFrame([
                        ["매출 성장률", f"{fin_data['growth']}%"],
                        ["영업 이익률", f"{fin_data['op_margin']}%"],
                        ["순이익률", f"{fin_data['net_margin']}%"],
                        ["부채 비율", f"{fin_data['debt_equity']}"]
                    ], columns=["지표", "값"])
                    st.table(df_fin)
                else:
                    st.warning("재무 데이터를 불러올 수 없습니다.")

        # Tab 2: AI 가치 평가
        with t2:
            st.markdown("##### 🔬 AI 가치 평가 모델")
            g_score, p_score, i_score = 75, 60, 85 # (예시 데이터)
            total_score = (g_score * 0.4) + (p_score * 0.3) + (i_score * 0.3)
            
            c1, c2, c3 = st.columns(3)
            c1.metric("성장성", f"{g_score}점"); c1.progress(g_score/100)
            c2.metric("수익성", f"{p_score}점"); c2.progress(p_score/100)
            c3.metric("관심도", f"{i_score}점"); c3.progress(i_score/100)
            
            st.write("---")
            st.markdown(f"### 🤖 종합 점수: {total_score:.1f} / 100")
            if off_val > 0:
                st.success(f"적정 주가 범위: ${off_val*1.1:.2f} ~ ${off_val*1.4:.2f}")

        # Tab 3: 투표 및 커뮤니티
        with t3:
            sid = stock['symbol']
            # 초기화
            if sid not in st.session_state.vote_data: st.session_state.vote_data[sid] = {'u': 10, 'f': 3}
            if sid not in st.session_state.comment_data: st.session_state.comment_data[sid] = []
            if 'user_votes' not in st.session_state: st.session_state.user_votes = {} # 중복 방지

            st.markdown("### 🗳️ 투자 매력도 투표")
            
            # 투표 버튼 (회원 전용)
            if st.session_state.auth_status == 'user':
                if sid not in st.session_state.user_votes:
                    b1, b2 = st.columns(2)
                    if b1.button("🦄 유니콘 (상승)", use_container_width=True, key=f"v_u_{sid}"):
                        st.session_state.vote_data[sid]['u'] += 1
                        st.session_state.user_votes[sid] = 'u'; st.rerun()
                    if b2.button("💸 폴른엔젤 (하락)", use_container_width=True, key=f"v_f_{sid}"):
                        st.session_state.vote_data[sid]['f'] += 1
                        st.session_state.user_votes[sid] = 'f'; st.rerun()
                else:
                    my_vote = "유니콘" if st.session_state.user_votes[sid] == 'u' else "폴른엔젤"
                    st.info(f"✅ 이미 '{my_vote}'에 투표하셨습니다.")
            else:
                st.warning("로그인 후 투표에 참여할 수 있습니다.")

            # 결과 바
            u_cnt = st.session_state.vote_data[sid]['u']
            f_cnt = st.session_state.vote_data[sid]['f']
            total = u_cnt + f_cnt
            if total > 0:
                st.progress(u_cnt / total)
                st.caption(f"유니콘 {int(u_cnt/total*100)}% vs 폴른엔젤 {100-int(u_cnt/total*100)}%")

            st.write("---")
            st.markdown("### 💬 의견 남기기")
            
            # 댓글 작성 (회원 전용)
            if st.session_state.auth_status == 'user':
                msg = st.text_input("의견을 입력하세요", key=f"cmt_{sid}")
                if st.button("등록", key=f"btn_cmt_{sid}") and msg:
                    st.session_state.comment_data[sid].insert(0, {"t": msg, "d": datetime.now().strftime("%H:%M")})
                    st.rerun()
            
            # 댓글 리스트
            for c in st.session_state.comment_data[sid][:3]:
                st.markdown(f"<div class='comment-box'><small>{c['d']}</small><br>{c['t']}</div>", unsafe_allow_html=True)

            st.write("---")
            # 보관함 버튼
            if sid not in st.session_state.watchlist:
                if st.button("⭐ 보관함 담기", type="primary", use_container_width=True):
                    st.session_state.watchlist.append(sid)
                    st.balloons()
                    st.rerun()
            else:
                st.success("✅ 보관함에 담긴 종목입니다.")
                if st.button("❌ 보관함 해제", use_container_width=True):
                    st.session_state.watchlist.remove(sid); st.rerun()
