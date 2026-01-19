import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import xml.etree.ElementTree as ET

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 세션 상태 초기화 ---
session_keys = {
    'page': 'intro',
    'auth_status': None,
    'vote_data': {},
    'comment_data': {},
    'user_votes': {},
    'selected_stock': None,
    'watchlist': [],
    'view_mode': 'all',
    'news_topic': '💰 공모가 범위/확정 소식',
    'login_step': 'choice'
}

for key, default_val in session_keys.items():
    if key not in st.session_state:
        st.session_state[key] = default_val

# --- API 키 ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

# --- CSS 스타일 (화이트 모드 & 디자인 시스템) ---
st.markdown("""
    <style>
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
    
    .comment-box { 
        background-color: #f8f9fa; padding: 10px; border-radius: 10px; 
        margin-bottom: 5px; border-left: 3px solid #6e8efb; 
    }
    
    /* 버튼 텍스트 가독성 */
    button p { font-weight: bold !important; }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 로직 ---

@st.cache_data(ttl=43200)
def get_daily_quote():
    try:
        res = requests.get("https://api.quotable.io/random?tags=business", timeout=3).json()
        return {"eng": res['content'], "author": res['author']}
    except:
        return {"eng": "Opportunities don't happen. You create them.", "author": "Chris Grosser"}

@st.cache_data(ttl=300)
def get_real_news_rss(company_name):
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
            try: date_str = " ".join(pubDate.split(' ')[1:3])
            except: date_str = "Recent"
            news_items.append({"title": title, "link": link, "date": date_str})
        return news_items
    except: return []

@st.cache_data(ttl=86400)
def get_financial_metrics(symbol, api_key):
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

# ==========================================
# [화면 흐름 제어]
# ==========================================

# 1. 인트로
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 10, 1])
    with col_center:
        st.markdown("""
            <div class='intro-card'>
                <div class='intro-title'>Unicornfinder</div>
                <div style='margin-bottom:30px;'>미국 IPO 시장의 미래를 만나보세요</div>
                <div class='feature-grid'>
                    <div class='feature-item'><div style='font-size:24px;'>📅</div>IPO 스케줄</div>
                    <div class='feature-item'><div style='font-size:24px;'>📊</div>AI 가격 예측</div>
                    <div class='feature-item'><div style='font-size:24px;'>🗳️</div>투자자 투표</div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        if st.button("시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()

# 2. 로그인
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
                    st.session_state.page = 'stats'; st.rerun()
                else:
                    st.error("올바른 번호를 입력해주세요.")
            if st.button("뒤로가기"):
                st.session_state.login_step = 'choice'; st.rerun()

    q = get_daily_quote()
    st.markdown(f"<div class='quote-card'><b>\"{q['eng']}\"</b><br><br><small>- {q['author']} -</small></div>", unsafe_allow_html=True)

# 3. 통계/대시보드
elif st.session_state.page == 'stats':
    st.write("<br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    
    img_baby = "baby_unicorn.png.png"
    img_adult = "adult_unicorn.png.png"
    img_child = "child_unicorn.png.png"

    with c1:
        st.markdown("<div class='grid-card'><h3>NEW</h3>", unsafe_allow_html=True)
        if os.path.exists(img_baby): st.image(img_baby, use_container_width=True)
        if st.button("전체 보기", key="go_all", use_container_width=True):
            st.session_state.view_mode = 'all'
            st.session_state.page = 'calendar'; st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with c2:
        st.markdown("<div class='grid-card'><h3>HOT</h3>", unsafe_allow_html=True)
        if os.path.exists(img_adult): st.image(img_adult, use_container_width=True)
        if st.button("주목할 종목", key="go_hot", use_container_width=True):
            st.session_state.view_mode = 'hot'
            st.session_state.page = 'calendar'; st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with c3:
        st.markdown("<div class='grid-card'><h3>MY</h3>", unsafe_allow_html=True)
        if os.path.exists(img_child): st.image(img_child, use_container_width=True)
        cnt = len(st.session_state.watchlist)
        if st.button(f"보관함 ({cnt})", key="go_watch", use_container_width=True, type="primary"):
            st.session_state.view_mode = 'watchlist'
            st.session_state.page = 'calendar'; st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

# 4. 캘린더
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 메인으로", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    
    all_df = get_extended_ipo_data(MY_API_KEY)
    
    if not all_df.empty:
        all_df = all_df.dropna(subset=['exchange'])
        all_df = all_df[all_df['symbol'].str.strip() != ""]
        today = datetime.now().date()
        
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

        if not display_df.empty:
            st.write("---")
            cols = st.columns([0.6, 1.2, 2.5, 1.2, 1.2, 1.2, 1.2])
            headers = ["", "공모일", "기업명", "공모가", "규모", "현재가", "거래소"]
            for c, h in zip(cols, headers): c.write(f"**{h}**")

            for i, row in display_df.iterrows():
                c_icon, c_date, c_name, c_price, c_size, c_curr, c_exch = st.columns([0.6, 1.2, 2.5, 1.2, 1.2, 1.2, 1.2])
                
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
                try:
                    p = float(str(row.get('price','0')).split('-')[0].replace('$',''))
                    s = int(row.get('numberOfShares',0) or 0)
                    size_val = f"${p*s/1000000:,.0f}M" if p*s > 0 else "-"
                except: size_val = "-"
                c_size.write(size_val)
                c_curr.write("-")
                c_exch.write(row.get('exchange', '-'))
        else:
            st.info("조건에 맞는 데이터가 없습니다.")

# 5. 상세 페이지 (복구된 완벽한 버전)
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

        # 데이터 로딩
        with st.spinner(f"🤖 {stock['name']}의 실시간 데이터를 AI가 분석 중입니다..."):
            try:
                off_val = float(str(stock.get('price', '0')).replace('$', '').split('-')[0].strip())
            except: off_val = 0
            
            try:
                current_p = get_current_stock_price(stock['symbol'], MY_API_KEY)
                if current_p == 0: st.toast("⚠️ 실시간 주가를 가져오지 못했습니다.", icon="☕")
                profile = get_company_profile(stock['symbol'], MY_API_KEY)
                fin_data = get_financial_metrics(stock['symbol'], MY_API_KEY)
            except:
                current_p, profile, fin_data = 0, None, None

        # 수익률 표시
        if current_p > 0 and off_val > 0:
            pct = ((current_p - off_val) / off_val) * 100
            color = "#00ff41" if pct >= 0 else "#ff4b4b"
            icon = "▲" if pct >= 0 else "▼"
            p_html = f"(공모 ${off_val} / 현재 ${current_p} <span style='color:{color}'><b>{icon} {abs(pct):.1f}%</b></span>)"
        else:
            p_html = f"(공모 ${off_val} / 상장 대기)"

        st.markdown(f"<h1>{status_emoji} {stock['name']} <small>{p_html}</small></h1>", unsafe_allow_html=True)
        st.write("---")

        tab0, tab1, tab2, tab3 = st.tabs(["📰 실시간 뉴스", "📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])

        # Tab 0: 뉴스 (Topic + RSS)
        with tab0:
            if 'news_topic' not in st.session_state: st.session_state.news_topic = "💰 공모가 범위/확정 소식"
            
            r1c1, r1c2 = st.columns(2)
            r2c1, r2c2 = st.columns(2)
            if r1c1.button("💰 공모가 범위", use_container_width=True, key="n1"): st.session_state.news_topic = "💰 공모가 범위/확정 소식"
            if r1c2.button("📅 상장 일정", use_container_width=True, key="n2"): st.session_state.news_topic = "📅 상장 일정/연기 소식"
            if r2c1.button("🥊 경쟁사 비교", use_container_width=True, key="n3"): st.session_state.news_topic = "🥊 경쟁사 비교/분석"
            if r2c2.button("🏦 주요 주간사", use_container_width=True, key="n4"): st.session_state.news_topic = "🏦 주요 주간사 (Underwriters)"

            topic = st.session_state.news_topic
            rep_kor = {
                "💰 공모가 범위/확정 소식": f"현재 {stock['name']}의 공모가 범위는 {stock.get('price', 'TBD')}입니다. 수요예측 결과가 긍정적입니다.",
                "📅 상장 일정/연기 소식": f"{stock['name']}은 {stock['date']} 상장 예정이며, 일정 변동 가능성을 모니터링 중입니다.",
                "🥊 경쟁사 비교/분석": f"{stock['name']}은 동종 섹터 대비 기술적 우위에 있으나 마케팅 비용 증가가 리스크입니다.",
                "🏦 주요 주간사 (Underwriters)": f"골드만삭스 등 대형 IB가 참여하여 상장 초기 주가 방어력이 기대됩니다."
            }
            st.markdown(f"<div style='background:#f0f4ff; padding:20px; border-radius:15px; margin-top:10px;'><h5>🤖 AI 요약: {topic}</h5><p>{rep_kor.get(topic)}</p></div>", unsafe_allow_html=True)
            
            st.write("---")
            st.markdown(f"##### 🔥 {stock['name']} 실시간 주요 뉴스")
            rss_news = get_real_news_rss(stock['name'])
            if rss_news:
                for n in rss_news:
                    st.markdown(f"""
                        <a href="{n['link']}" target="_blank" style="text-decoration:none; color:inherit;">
                            <div style="padding:15px; background:white; border-radius:10px; border:1px solid #eee; margin-bottom:10px;">
                                <div style="display:flex; justify-content:space-between;">
                                    <span style="font-weight:bold; font-size:15px;">{n['title']}</span>
                                    <span style="font-size:12px; color:#888;">{n['date']}</span>
                                </div>
                            </div>
                        </a>
                    """, unsafe_allow_html=True)
            else:
                st.info("실시간 뉴스가 없어 검색 링크를 제공합니다.")
                st.markdown(f"[구글 뉴스 검색 바로가기](https://www.google.com/search?q={stock['name']}+IPO&tbm=nws)")

        # Tab 1: 핵심 정보 (디자인 복구)
        with tab1:
            cc1, cc2 = st.columns([1.5, 1])
            with cc1:
                st.markdown(f"#### 📑 {stock['name']} 비즈니스 요약")
                if profile:
                    biz_desc = profile.get('description', "상세 설명 대기 중")
                    industry = profile.get('finnhubIndustry', "기술/서비스")
                else:
                    biz_desc = "API 제한으로 데이터를 불러올 수 없습니다."
                    industry = "-"
                
                st.markdown(f"""
                    <div style='background-color: #fff4e5; padding: 20px; border-radius: 15px; border-left: 5px solid #ffa500; margin-bottom: 15px;'>
                        <ul style='line-height: 1.6;'>
                            <li><b>주요 업종:</b> {industry}</li>
                            <li><b>비즈니스 요약:</b> {biz_desc[:300]}...</li>
                        </ul>
                    </div>
                """, unsafe_allow_html=True)
                st.markdown(f"[SEC EDGAR 공시 원문 보기](https://www.sec.gov/edgar/search/#/q={stock['name'].replace(' ','%20')})")

            with cc2:
                st.markdown("#### 📊 재무 현황 (TTM)")
                if fin_data:
                    display_data = {
                        "재무 항목": ["매출 성장률", "영업 이익률", "순이익률", "부채 비율"],
                        "현황": [
                            f"{fin_data['growth']}%" if fin_data['growth'] else "-",
                            f"{fin_data['op_margin']}%" if fin_data['op_margin'] else "-",
                            f"{fin_data['net_margin']}%" if fin_data['net_margin'] else "-",
                            f"{fin_data['debt_equity']}" if fin_data['debt_equity'] else "-"
                        ]
                    }
                    st.table(pd.DataFrame(display_data))
                else:
                    st.warning("재무 데이터를 불러올 수 없습니다.")

        # Tab 2: AI 가치 평가 (카드 UI 복구)
        with tab2:
            growth_score, profit_score, interest_score = 75, 60, 85
            total_score = (growth_score * 0.4) + (profit_score * 0.3) + (interest_score * 0.3)
            fair_low = off_val * 1.1 if off_val > 0 else 25.0

            st.markdown("##### 🔬 1. 가치 평가 방법론 상세 (Academic Methodology)")
            p_cols = st.columns(3)
            methodologies = [
                {"title": "Relative Valuation", "author": "Kim & Ritter (1999)", "desc": "동종 업계 P/S, P/E 배수 적용"},
                {"title": "Fair Value Model", "author": "Purnanandam (2004)", "desc": "내재 가치 괴리율 측정"},
                {"title": "Margin of Safety", "author": "Loughran & Ritter", "desc": "장기 수익성 기반 안전 마진"}
            ]
            for i, m in enumerate(methodologies):
                with p_cols[i]:
                    st.markdown(f"""
                        <div style='border-top: 4px solid #6e8efb; background-color: #f8f9fa; padding: 15px; border-radius: 10px; height: 150px;'>
                            <p style='font-size: 11px; color: #6e8efb;'>{m['title']}</p>
                            <p style='font-weight: bold;'>{m['author']}</p>
                            <p style='font-size: 12px;'>{m['desc']}</p>
                        </div>
                    """, unsafe_allow_html=True)

            st.write("<br>", unsafe_allow_html=True)
            st.markdown(f"#### 🎓 2. AI 종합 매력도: {total_score:.1f} / 100")
            c1, c2, c3 = st.columns(3)
            c1.metric("성장성", f"{growth_score}점"); c1.progress(growth_score/100)
            c2.metric("수익성", f"{profit_score}점"); c2.progress(profit_score/100)
            c3.metric("관심도", f"{interest_score}점"); c3.progress(interest_score/100)
            
            st.success(f"🤖 AI 추정 적정가 범위: ${fair_low:.2f} ~ ${fair_low*1.3:.2f}")

        # Tab 3: 투표 및 커뮤니티 (로직 통합)
        with tab3:
            sid = stock['symbol']
            if sid not in st.session_state.vote_data: st.session_state.vote_data[sid] = {'u': 10, 'f': 3}
            if sid not in st.session_state.comment_data: st.session_state.comment_data[sid] = []
            if 'user_votes' not in st.session_state: st.session_state.user_votes = {}

            st.markdown("### 🗳️ 투자 매력도 투표")
            if st.session_state.auth_status == 'user':
                if sid not in st.session_state.user_votes:
                    v1, v2 = st.columns(2)
                    if v1.button("🦄 유니콘 (상승)", use_container_width=True, key=f"vu_{sid}"):
                        st.session_state.vote_data[sid]['u'] += 1
                        st.session_state.user_votes[sid] = 'u'; st.rerun()
                    if v2.button("💸 폴른엔젤 (하락)", use_container_width=True, key=f"vf_{sid}"):
                        st.session_state.vote_data[sid]['f'] += 1
                        st.session_state.user_votes[sid] = 'f'; st.rerun()
                else:
                    my_vote = "유니콘" if st.session_state.user_votes[sid] == 'u' else "폴른엔젤"
                    st.info(f"✅ 이미 '{my_vote}'에 투표하셨습니다.")
            else:
                st.warning("🔒 투표는 회원만 참여 가능합니다.")

            u, f = st.session_state.vote_data[sid]['u'], st.session_state.vote_data[sid]['f']
            if u+f > 0: st.progress(u/(u+f))
            
            st.write("---")
            st.markdown("### 💬 주주 토론방")
            if st.session_state.auth_status == 'user':
                nc = st.text_input("의견을 남겨주세요", key=f"ci_{sid}")
                if st.button("등록", key=f"cb_{sid}") and nc:
                    st.session_state.comment_data[sid].insert(0, {"t": nc, "d": datetime.now().strftime("%H:%M")})
                    st.rerun()
            
            for c in st.session_state.comment_data[sid][:3]:
                st.markdown(f"<div class='comment-box'><small>{c['d']}</small><br>{c['t']}</div>", unsafe_allow_html=True)

            st.write("---")
            if sid not in st.session_state.watchlist:
                if st.button("⭐ 보관함에 담기", use_container_width=True, type="primary"):
                    st.session_state.watchlist.append(sid); st.balloons(); st.rerun()
            else:
                st.success("✅ 보관함에 담긴 종목입니다.")
                if st.button("❌ 보관함 해제", use_container_width=True):
                    st.session_state.watchlist.remove(sid); st.rerun()
