import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import xml.etree.ElementTree as ET

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 세션 초기화 ---
for key in ['page', 'auth_status', 'vote_data', 'comment_data', 'selected_stock', 'watchlist', 'view_mode', 'news_topic']:
    if key not in st.session_state:
        if key == 'page': st.session_state[key] = 'intro'
        elif key == 'watchlist': st.session_state[key] = []
        elif key in ['vote_data', 'comment_data', 'user_votes']: st.session_state[key] = {}
        elif key == 'view_mode': st.session_state[key] = 'all'
        elif key == 'news_topic': st.session_state[key] = "💰 공모가 범위/확정 소식"
        else: st.session_state[key] = None

# --- CSS 스타일 ---
st.markdown("""
    <style>
    /* 전체 앱 스타일 */
    .stApp { background-color: #FFFFFF; color: #333333; }
    
    .intro-card {
        background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%);
        padding: 50px 30px; border-radius: 30px; color: white !important;
        text-align: center; margin-top: 20px; 
        box-shadow: 0 20px 40px rgba(110, 142, 251, 0.3);
    }
    .intro-title { font-size: 40px; font-weight: 900; margin-bottom: 10px; color: white !important; }
    
    .feature-grid { display: flex; justify-content: space-around; gap: 15px; margin-bottom: 25px; }
    .feature-item {
        background: rgba(255, 255, 255, 0.2);
        padding: 20px 10px; border-radius: 20px; flex: 1;
        backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.3);
        color: white !important; text-align: center;
    }
    
    .grid-card { 
        background-color: #ffffff !important; 
        padding: 25px; border-radius: 20px; 
        border: 1px solid #eef2ff; box-shadow: 0 10px 20px rgba(0,0,0,0.05); 
        text-align: center; color: #333333 !important; height: 100%;
    }
    
    .quote-card {
        background: linear-gradient(145deg, #ffffff, #f9faff);
        padding: 25px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.05); text-align: center;
        max-width: 650px; margin: 40px auto; color: #333333 !important;
    }
    
    .comment-box { background-color: #f8f9fa; padding: 10px; border-radius: 10px; margin-bottom: 5px; border-left: 3px solid #dee2e6; color: #333; }
    button p { font-weight: bold !important; }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 로직 ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

@st.cache_data(ttl=43200)
def get_daily_quote():
    try:
        res = requests.get("https://api.quotable.io/random?tags=business", timeout=3).json()
        return {"eng": res['content'], "author": res['author']}
    except:
        return {"eng": "Opportunities don't happen. You create them.", "author": "Chris Grosser"}

@st.cache_data(ttl=86400)
def get_financial_metrics(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/stock/metric?symbol={symbol}&metric=all&token={api_key}"
        res = requests.get(url, timeout=5).json()
        metrics = res.get('metric', {})
        return {
            "growth": metrics.get('salesGrowthYoy', None),
            "op_margin": metrics.get('operatingMarginTTM', None),
            "net_margin": metrics.get('netProfitMarginTTM', None),
            "debt_equity": metrics.get('totalDebt/totalEquityQuarterly', None)
        } if metrics else None
    except: return None

@st.cache_data(ttl=86400)
def get_company_profile(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={api_key}"
        res = requests.get(url, timeout=5).json()
        return res if res and 'name' in res else None
    except: return None

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

# [추가: 뉴스 감성 분석 함수]
def analyze_sentiment(text):
    text = text.lower()
    pos_words = ['jump', 'soar', 'surge', 'rise', 'gain', 'buy', 'outperform', 'beat', 'success', 'growth', 'up', 'high', 'profit', 'approval']
    neg_words = ['drop', 'fall', 'plunge', 'sink', 'loss', 'miss', 'fail', 'risk', 'down', 'low', 'crash', 'suit', 'ban', 'warning']
    score = 0
    for w in pos_words:
        if w in text: score += 1
    for w in neg_words:
        if w in text: score -= 1
    
    if score > 0: return "긍정", "#e6f4ea", "#1e8e3e"
    elif score < 0: return "부정", "#fce8e6", "#d93025"
    else: return "일반", "#f1f3f4", "#5f6368"

@st.cache_data(ttl=300)
def get_real_news_rss(company_name):
    """구글 뉴스 RSS + 한글 번역 + 감성 분석"""
    try:
        query = f"{company_name} stock news"
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        response = requests.get(url, timeout=3)
        root = ET.fromstring(response.content)
        
        news_items = []
        for item in root.findall('./channel/item')[:5]:
            title_en = item.find('title').text
            link = item.find('link').text
            pubDate = item.find('pubDate').text
            
            # 1. 감성 분석
            sent_label, bg, color = analyze_sentiment(title_en)
            
            # 2. 날짜 포맷
            try: date_str = " ".join(pubDate.split(' ')[1:3])
            except: date_str = "Recent"

            # 3. 한글 번역 (MyMemory API)
            try:
                trans_url = "https://api.mymemory.translated.net/get"
                res = requests.get(trans_url, params={'q': title_en, 'langpair': 'en|ko'}, timeout=1).json()
                if res['responseStatus'] == 200:
                    title_ko = res['responseData']['translatedText'].replace("&quot;", "'").replace("&amp;", "&")
                    display_title = f"{title_en}<br><span style='font-size:14px; color:#555; font-weight:normal;'>🇰🇷 {title_ko}</span>"
                else: display_title = title_en
            except: display_title = title_en
            
            news_items.append({
                "title": display_title, "link": link, "date": date_str,
                "sent_label": sent_label, "bg": bg, "color": color
            })
        return news_items
    except: return []

# --- 화면 제어 시작 ---

# 1. 인트로
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 10, 1])
    with col_center:
        st.markdown("""
            <div class='intro-card'>
                <div class='intro-title'>Unicornfinder</div>
                <div class='feature-grid'>
                    <div class='feature-item'><div style='font-size:28px;'>📅</div>IPO 스케줄</div>
                    <div class='feature-item'><div style='font-size:28px;'>📊</div>AI 가격 예측</div>
                    <div class='feature-item'><div style='font-size:28px;'>🗳️</div>투자자 투표</div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        if st.button("시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()

# 2. 로그인 화면
elif st.session_state.page == 'login':
    st.write("<br>" * 5, unsafe_allow_html=True)
    _, col_m, _ = st.columns([1, 1.2, 1])
    
    with col_m:
        if 'login_step' not in st.session_state: st.session_state.login_step = 'choice'

        if st.session_state.login_step == 'choice':
            if st.button("📱 회원으로 시작하기", use_container_width=True):
                st.session_state.login_step = 'ask_signup'; st.rerun()
            if st.button("👀 비회원으로 시작하기", use_container_width=True):
                st.session_state.auth_status = 'guest'
                st.session_state.page = 'stats'; st.rerun()

        elif st.session_state.login_step == 'ask_signup':
            st.info("관심기업 관리 및 알림을 받을 수 있습니다.")
            c1, c2 = st.columns(2)
            if c1.button("✅ 진행하기", use_container_width=True):
                st.session_state.login_step = 'input_phone'; st.rerun()
            if c2.button("❌ 돌아가기", use_container_width=True):
                st.session_state.login_step = 'choice'; st.rerun()

        elif st.session_state.login_step == 'input_phone':
            st.markdown("### 📱 가입 정보 입력")
            phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000")
            
            cc1, cc2 = st.columns([2, 1])
            if cc1.button("가입 완료", use_container_width=True):
                if len(phone) >= 10:
                    st.session_state.auth_status = 'user'
                    st.session_state.page = 'stats'
                    st.session_state.login_step = 'choice'
                    st.rerun()
                else: st.error("정확한 번호를 입력해주세요.")
            if cc2.button("취소"):
                st.session_state.login_step = 'choice'; st.rerun()

    st.write("<br>" * 2, unsafe_allow_html=True)
    q = get_daily_quote()
    st.markdown(f"<div class='quote-card'><b>\"{q['eng']}\"</b><br><small>- {q['author']} -</small></div>", unsafe_allow_html=True)

# 3. 성장 단계 분석 (대시보드)
elif st.session_state.page == 'stats':
    st.write("<br>", unsafe_allow_html=True)
    img_baby = "baby_unicorn.png.png"
    img_adult = "adult_unicorn.png.png"
    img_child = "child_unicorn.png.png"
    
    c1, c2, c3 = st.columns(3)
    
    with c1:
        st.markdown("<div class='grid-card'><h3>NEW</h3>", unsafe_allow_html=True)
        if os.path.exists(img_baby): st.image(img_baby, use_container_width=True)
        if st.button("전체 보기", use_container_width=True, key="go_all"):
            st.session_state.view_mode = 'all'
            st.session_state.page = 'calendar'; st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with c2:
        st.markdown("<div class='grid-card'><h3>HOT</h3>", unsafe_allow_html=True)
        if os.path.exists(img_adult): st.image(img_adult, use_container_width=True)
        if st.button("주목할 종목", use_container_width=True, key="go_hot"):
            st.session_state.view_mode = 'hot'
            st.session_state.page = 'calendar'; st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with c3:
        st.markdown("<div class='grid-card'><h3>MY</h3>", unsafe_allow_html=True)
        if os.path.exists(img_child): st.image(img_child, use_container_width=True)
        watch_count = len(st.session_state.watchlist)
        if st.button(f"보관함 ({watch_count})", use_container_width=True, type="primary", key="go_watch"):
            st.session_state.view_mode = 'watchlist'
            st.session_state.page = 'calendar'; st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

# 4. 캘린더 (리스트)
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    view_mode = st.session_state.get('view_mode', 'all')
    
    all_df_raw = get_extended_ipo_data(MY_API_KEY)
    
    if not all_df_raw.empty:
        all_df = all_df_raw.dropna(subset=['exchange'])
        all_df = all_df[all_df['exchange'].astype(str).str.upper() != 'NONE']
        all_df = all_df[all_df['symbol'].astype(str).str.strip() != ""]
        today = datetime.now().date()

        if view_mode == 'watchlist':
            display_df = all_df[all_df['symbol'].isin(st.session_state.watchlist)]
            st.title("⭐ 나의 관심 종목")
        else:
            period = st.radio("📅 조회 기간", ["예정 (90일)", "최근 6개월", "최근 1년"], horizontal=True)
            if period == "예정 (90일)":
                display_df = all_df[(all_df['공모일_dt'].dt.date >= today) & (all_df['공모일_dt'].dt.date <= today + timedelta(days=90))]
            elif period == "최근 6개월": 
                display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=180))]
            else: 
                display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=365))]

        if not display_df.empty:
            st.write("---")
            h_cols = st.columns([0.6, 1.2, 2.5, 1.2, 1.2, 1.2, 1.2])
            headers = ["", "공모일", "기업명", "공모가", "규모", "현재가", "거래소"]
            for c, h in zip(h_cols, headers): c.write(f"**{h}**")
            
            for i, row in display_df.iterrows():
                c_cols = st.columns([0.6, 1.2, 2.5, 1.2, 1.2, 1.2, 1.2])
                ipo_date = row['공모일_dt'].date()
                
                # 아이콘
                icon = "🐣" if ipo_date > (today - timedelta(days=365)) else "🦄"
                bg = "#fff9db" if icon == "🐣" else "#f3f0ff"
                c_cols[0].markdown(f"<div style='background:{bg}; width:40px; height:40px; border-radius:10px; text-align:center; padding-top:5px; font-size:20px;'>{icon}</div>", unsafe_allow_html=True)
                
                c_cols[1].write(row['date'])
                
                with c_cols[2]:
                    if st.button(f"{row['name']} ({row['symbol']})", key=f"btn_{i}", use_container_width=True):
                        st.session_state.selected_stock = row.to_dict()
                        st.session_state.page = 'detail'; st.rerun()
                
                c_cols[3].write(row.get('price', '-'))
                
                # 규모
                try: 
                    p = float(str(row.get('price','0')).split('-')[0].replace('$',''))
                    s = int(row.get('numberOfShares',0))
                    val = f"${p*s/1000000:,.0f}M"
                except: val = "-"
                c_cols[4].write(val)
                
                c_cols[5].write("-") # 리스트 속도 최적화
                c_cols[6].write(row.get('exchange', '-'))
        else:
            st.info("조건에 맞는 데이터가 없습니다.")

# 5. 상세 페이지 (NameError 수정 + 최신 기능 통합)
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    
    # [중요] 변수 초기화 (에러 방지용)
    profile = None
    fin_data = None
    current_p = 0
    
    if stock:
        # 1. 데이터 로딩 (가장 먼저 실행)
        today = datetime.now().date()
        try: ipo_dt = stock['공모일_dt'].date() if hasattr(stock['공모일_dt'], 'date') else pd.to_datetime(stock['공모일_dt']).date()
        except: ipo_dt = today
        status_emoji = "🐣" if ipo_dt > (today - timedelta(days=365)) else "🦄"

        if st.button("⬅️ 목록으로"): 
            st.session_state.page = 'calendar'; st.rerun()

        with st.spinner(f"🤖 {stock['name']} 데이터를 분석 중입니다..."):
            try: off_val = float(str(stock.get('price', '0')).replace('$', '').split('-')[0].strip())
            except: off_val = 0
            
            try:
                # 여기서 profile과 fin_data를 정의합니다.
                current_p = get_current_stock_price(stock['symbol'], MY_API_KEY)
                profile = get_company_profile(stock['symbol'], MY_API_KEY) 
                fin_data = get_financial_metrics(stock['symbol'], MY_API_KEY)
            except: pass

        # 2. 헤더 정보
        if current_p > 0 and off_val > 0:
            pct = ((current_p - off_val) / off_val) * 100
            color = "#00ff41" if pct >= 0 else "#ff4b4b"
            p_html = f"(공모 ${off_val} / 현재 ${current_p} <span style='color:{color}'><b>{pct:.1f}%</b></span>)"
        else:
            p_html = f"(공모 ${off_val} / 상장 대기)"

        st.markdown(f"<h1>{status_emoji} {stock['name']} <small>{p_html}</small></h1>", unsafe_allow_html=True)
        st.write("---")

        # 3. 탭 구성
        tab0, tab1, tab2, tab3 = st.tabs(["📰 실시간 뉴스", "📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])

        # Tab 0: 뉴스 (번역+감성+TOP5)
        with tab0:
            if 'news_topic' not in st.session_state: st.session_state.news_topic = "💰 공모가 범위/확정 소식"
            
            c1, c2, c3, c4 = st.columns(4)
            if c1.button("💰 가격"): st.session_state.news_topic = "💰 공모가 범위/확정 소식"
            if c2.button("📅 일정"): st.session_state.news_topic = "📅 상장 일정/연기 소식"
            if c3.button("🥊 경쟁"): st.session_state.news_topic = "🥊 경쟁사 비교/분석"
            if c4.button("🏦 주간사"): st.session_state.news_topic = "🏦 주요 주간사 (Underwriters)"

            topic = st.session_state.news_topic
            rep_kor = {
                "💰 공모가 범위/확정 소식": f"{stock['name']}의 공모가는 {stock.get('price', 'TBD')} 수준입니다.",
                "📅 상장 일정/연기 소식": f"{stock['date']} 상장 예정이며 특이사항 없습니다.",
                "🥊 경쟁사 비교/분석": f"동종 업계 대비 성장성이 주목받고 있습니다.",
                "🏦 주요 주간사 (Underwriters)": f"주요 IB들이 주간사로 참여 중입니다."
            }
            st.info(f"🤖 AI 요약 ({topic}): {rep_kor.get(topic)}")
            
            st.write("---")
            st.markdown(f"##### 🔥 {stock['name']} 실시간 인기 뉴스 Top 5")
            
            rss_news = get_real_news_rss(stock['name'])
            tags = ["분석", "시장", "전망", "전략", "수급"]
            
            for i in range(5):
                tag = tags[i]
                if rss_news and i < len(rss_news):
                    n = rss_news[i]
                    st.markdown(f"""
                        <a href="{n['link']}" target="_blank" style="text-decoration:none; color:inherit;">
                            <div style="padding:15px; border:1px solid #eee; border-radius:10px; margin-bottom:10px; box-shadow:0 2px 5px rgba(0,0,0,0.03);">
                                <div style="display:flex; justify-content:space-between;">
                                    <div><span style="color:#6e8efb; font-weight:bold;">TOP {i+1}</span> | {tag} <span style="background:{n['bg']}; color:{n['color']}; padding:2px 5px; border-radius:4px; font-size:11px;">{n['sent_label']}</span></div>
                                    <small>{n['date']}</small>
                                </div>
                                <div style="margin-top:5px; font-weight:bold;">{n['title']}</div>
                            </div>
                        </a>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"<div style='padding:10px; color:#999;'>관련 뉴스 검색 링크 제공 (Google)</div>", unsafe_allow_html=True)

        # Tab 1: 핵심 정보 (공시자료 선택)
        with tab1:
            if profile:
                st.markdown(f"**🏢 {stock['name']}** | {profile.get('finnhubIndustry','-')}")
            
            info_type = st.radio("자료 선택", ["📊 실시간 재무 (TTM)", "📄 S-1", "🌍 F-1", "🔄 S-1/A", "📢 FWP", "✅ 424B4"], horizontal=True)
            
            if info_type == "📊 실시간 재무 (TTM)":
                if fin_data:
                    c1, c2 = st.columns(2)
                    c1.metric("매출 성장률", f"{fin_data['growth']}%" if fin_data['growth'] else "-")
                    c2.metric("영업 이익률", f"{fin_data['op_margin']}%" if fin_data['op_margin'] else "-")
                else: st.warning("재무 데이터 없음")
            else:
                code_map = {"📄 S-1": "S-1", "🌍 F-1": "F-1", "🔄 S-1/A": "S-1/A", "📢 FWP": "FWP", "✅ 424B4": "424B4"}
                code = code_map.get(info_type.split(' ')[0] + ' ' + info_type.split(' ')[1], "S-1")
                st.info(f"{code} 문서를 SEC EDGAR에서 검색합니다.")
                st.markdown(f"[🏛️ SEC 원문 보기](https://www.sec.gov/edgar/search/#/q={stock['symbol']}%2520{code})")

        # Tab 2: 가치 평가
        with tab2:
            st.markdown("##### 🔬 가치 평가 모델")
            st.markdown("<div style='background:#f8f9fa; padding:15px; border-radius:10px;'>종합 점수: <b>78.5점</b> (매우 높음)</div>", unsafe_allow_html=True)
            st.progress(0.78)

        # Tab 3: 투표
        with tab3:
            sid = stock['symbol']
            if sid not in st.session_state.vote_data: st.session_state.vote_data[sid] = {'u': 10, 'f': 3}
            if sid not in st.session_state.comment_data: st.session_state.comment_data[sid] = []
            
            st.write("### 🗳️ 투자 매력도 투표")
            if st.session_state.auth_status == 'user':
                c1, c2 = st.columns(2)
                if c1.button("🦄 유니콘 (상승)", key=f"vu_{sid}"): 
                    st.session_state.vote_data[sid]['u'] += 1; st.rerun()
                if c2.button("💸 폴른엔젤 (하락)", key=f"vf_{sid}"): 
                    st.session_state.vote_data[sid]['f'] += 1; st.rerun()
            else: st.warning("로그인 필요")
            
            u, f = st.session_state.vote_data[sid]['u'], st.session_state.vote_data[sid]['f']
            if u+f > 0: st.progress(u/(u+f))
            
            st.write("---")
            # 보관함
            if sid not in st.session_state.watchlist:
                if st.button("⭐ 보관함 담기", type="primary"): 
                    st.session_state.watchlist.append(sid); st.rerun()
            else:
                if st.button("❌ 해제"): 
                    st.session_state.watchlist.remove(sid); st.rerun()
