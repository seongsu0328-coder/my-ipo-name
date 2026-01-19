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

@st.cache_data(ttl=43200)
def get_daily_quote():
    """로그인 화면의 오늘의 명언을 가져옵니다."""
    try:
        res = requests.get("https://api.quotable.io/random?tags=business", timeout=3).json()
        trans = requests.get(f"https://api.mymemory.translated.net/get?q={res['content']}&langpair=en|ko", timeout=3).json()
        return {"eng": res['content'], "kor": trans['responseData']['translatedText'], "author": res['author']}
    except:
        return {"eng": "Opportunities don't happen. You create them.", "kor": "기회는 일어나는 것이 아니라 만드는 것이다.", "author": "Chris Grosser"}

@st.cache_data(ttl=86400)
def get_financial_metrics(symbol, api_key):
    """특정 기업의 실제 재무 지표(성장률, 이익률 등)를 가져옵니다."""
    try:
        # Finnhub Basic Financials 엔드포인트
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
    except:
        return None

@st.cache_data(ttl=86400)
def get_company_profile(symbol, api_key):
    """기업의 실제 프로필(업종, 사업 요약, 로고 등)을 가져옵니다."""
    try:
        url = f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={api_key}"
        res = requests.get(url, timeout=5).json()
        # 데이터가 있고, 정상적인 응답인지 확인
        return res if res and 'name' in res else None
    except:
        return None

@st.cache_data(ttl=600)
def get_extended_ipo_data(api_key):
    """IPO 캘린더 데이터를 가져옵니다."""
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
    """현재 주가를 실시간으로 조회합니다."""
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
        return requests.get(url, timeout=2).json().get('c', 0)
    except: return 0

# --- 화면 제어 시작 ---

# 1. 인트로
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 10, 1])
    with col_center:
        st.markdown("""
            <div class='intro-card'>
                <div class='intro-title'>Unicornfinder</div>
                <div class='feature-grid'>
                    <div class='feature-item'><div style='font-size:28px;'>📅</div><div style='font-size:14px; font-weight:600;'>IPO 스케줄<br>트래킹</div></div>
                    <div class='feature-item'><div style='font-size:28px;'>📊</div><div style='font-size:14px; font-weight:600;'>AI기반 분석<br>가격 예측</div></div>
                    <div class='feature-item'><div style='font-size:28px;'>🗳️</div><div style='font-size:14px; font-weight:600;'>집단 지성<br>성공 예측</div></div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        if st.button("시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()

# 2. 로그인 화면 (하얀색 버튼 및 미니멀 버전)
elif st.session_state.page == 'login':
    st.write("<br>" * 5, unsafe_allow_html=True) 
    _, col_m, _ = st.columns([1, 1.2, 1])
    
    with col_m:
        if 'login_step' not in st.session_state:
            st.session_state.login_step = 'choice'

        # 1단계: 메인 선택 (모든 버튼을 하얀색으로 통일)
        if st.session_state.login_step == 'choice':
            # type="primary"를 제거하여 하얀색 바탕으로 변경
            if st.button("📱 회원으로 시작하기", use_container_width=True):
                st.session_state.login_step = 'ask_signup'
                st.rerun()
            
            if st.button("👀 비회원으로 시작하기", use_container_width=True):
                st.session_state.auth_status = 'guest'
                st.session_state.page = 'stats'
                st.rerun()

        # 2단계: 가입 의사 확인
        elif st.session_state.login_step == 'ask_signup':
            st.info("관심기업관리 및 신규IPO 정보를 받을 수 있습니다.")
            c1, c2 = st.columns(2)
            if c1.button("✅ 진행하기", use_container_width=True): # 여기도 하얀색으로 통일
                st.session_state.login_step = 'input_phone'
                st.rerun()
            if c2.button("❌ 돌아가기", use_container_width=True):
                st.session_state.login_step = 'choice'
                st.rerun()

        # 3단계: 휴대폰 번호 입력
        elif st.session_state.login_step == 'input_phone':
            st.markdown("### 📱 가입 정보 입력")
            phone = st.text_input("알림을 받을 휴대폰 번호", placeholder="010-0000-0000")
            
            cc1, cc2 = st.columns([2, 1])
            if cc1.button("진행하기", use_container_width=True): # 하얀색 버튼
                if len(phone) >= 10:
                    st.success("가입이 완료되었습니다!")
                    st.session_state.auth_status = 'user'
                    st.session_state.page = 'stats'
                    st.session_state.login_step = 'choice'
                    st.rerun()
                else:
                    st.error("정확한 번호를 입력해주세요.")
            if cc2.button("돌아가기"):
                st.session_state.login_step = 'choice'
                st.rerun()

    # 하단 명언 (유지)
    st.write("<br>" * 2, unsafe_allow_html=True)
    q = get_daily_quote()
    st.markdown(f"<div class='quote-card'><small>TODAY'S INSIGHT</small><br><b>\"{q['eng']}\"</b><br><small>({q['kor']})</small><br><br><small>- {q['author']} -</small></div>", unsafe_allow_html=True)

# 3. 성장 단계 분석 (Hot 유니콘 추가 버전)
elif st.session_state.page == 'stats':
    # 상단 여백
    st.write("<br>", unsafe_allow_html=True)
    
    # 이미지 파일명 정의
    img_baby = "baby_unicorn.png.png"
    img_adult = "adult_unicorn.png.png"  # Hot 유니콘 이미지
    img_child = "child_unicorn.png.png"
    
    # 3개의 컬럼으로 구성 (New, Hot, My)
    c1, c2, c3 = st.columns(3)
    
    # --- [1. NEW ] ---
    with c1:
        st.markdown("<div class='grid-card'><h3>NEW </h3>", unsafe_allow_html=True)
        if os.path.exists(img_baby):
            st.image(img_baby, use_container_width=True)
        else: 
            st.warning("baby_unicorn.png.png 파일을 찾을 수 없습니다.")
        
        if st.button("진행하기", use_container_width=True, key="go_all"):
            st.session_state.view_mode = 'all'
            st.session_state.page = 'calendar'
            st.rerun()
            
        #
        st.markdown("</div>", unsafe_allow_html=True)

    # --- [2. HOT 유니콘 (추가)] ---
    with c2:
        st.markdown("<div class='grid-card'><h3>HOT </h3>", unsafe_allow_html=True)
        if os.path.exists(img_adult):
            st.image(img_adult, use_container_width=True)
        else: 
            st.warning("adult_unicorn.png.png 파일을 찾을 수 없습니다.")
        
        # Hot 유니콘 클릭 시 필터링 로직 (예: 상장 3년 이상 종목만 보기 등)
        if st.button("진행하기", use_container_width=True, key="go_hot"):
            st.session_state.view_mode = 'hot' # 필터링 모드 설정
            st.session_state.page = 'calendar'
            st.rerun()
            
        #
        st.markdown("</div>", unsafe_allow_html=True)

    # --- [3. MY ] ---
    with c3:
        st.markdown("<div class='grid-card'><h3>MY </h3>", unsafe_allow_html=True)
        if os.path.exists(img_child):
            st.image(img_child, use_container_width=True)
        else: 
            st.warning("child_unicorn.png.png 파일을 찾을 수 없습니다.")
            
        watch_count = len(st.session_state.watchlist)
        if st.button(f"진행하기 ({watch_count}개 보관 중)", use_container_width=True, type="primary", key="go_watch"):
            if watch_count > 0:
                st.session_state.view_mode = 'watchlist'
                st.session_state.page = 'calendar'
                st.rerun()
            else:
                st.warning("아직 보관함에 담긴 기업이 없습니다.")
                
        #
        st.markdown("</div>", unsafe_allow_html=True)

# 4. 캘린더 (상장 기간별 이모지 구분 버전)
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    view_mode = st.session_state.get('view_mode', 'all')
    
    # [1. 원본 데이터 로드]
    all_df_raw = get_extended_ipo_data(MY_API_KEY)
    
    if not all_df_raw.empty:
        # [2. 유령 종목 및 비정상 데이터 필터링]
        all_df = all_df_raw.dropna(subset=['exchange'])
        all_df = all_df[all_df['exchange'].astype(str).str.upper() != 'NONE']
        all_df = all_df[all_df['symbol'].astype(str).str.strip() != ""]
        today = datetime.now().date()

        @st.cache_data(ttl=600)
        def filter_invalid_stocks(df):
            valid_indices = []
            for idx, row in df.iterrows():
                ipo_dt = row['공모일_dt'].date()
                if ipo_dt > today:
                    valid_indices.append(idx)
                else:
                    cp = get_current_stock_price(row['symbol'], MY_API_KEY)
                    if cp > 0: valid_indices.append(idx)
            return df.loc[valid_indices]

        all_df = filter_invalid_stocks(all_df)

        # [3. 필터 및 정렬 레이아웃]
        # (기존 필터 로직 동일 유지...)
        if view_mode == 'watchlist':
            display_df = all_df[all_df['symbol'].isin(st.session_state.watchlist)]
        else:
            col_f1, col_f2 = st.columns([2, 1])
            with col_f1:
                period = st.radio("📅 조회 기간 설정", ["상장 예정 (90일 내)", "최근 6개월", "최근 12개월", "최근 18개월"], horizontal=True)
            with col_f2:
                sort_option = st.selectbox("🎯 리스트 정렬", ["최신순", "수익률 높은순", "매출 성장률순(AI)"])

            if period == "상장 예정 (90일 내)":
                future_limit = today + timedelta(days=90)
                display_df = all_df[(all_df['공모일_dt'].dt.date >= today) & (all_df['공모일_dt'].dt.date <= future_limit)]
            elif period == "최근 6개월": 
                display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=180))]
            elif period == "최근 12개월": 
                display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=365))]
            elif period == "최근 18개월": 
                display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=540))]

        # [5. 리스트 렌더링 (이모지 구분 적용)]
        if not display_df.empty:
            st.write("---")
            h_logo, h_date, h_name, h_price, h_size, h_curr, h_exch = st.columns([0.6, 1.2, 2.5, 1.2, 1.2, 1.2, 1.2])
            h_logo.write(""); h_date.write("**공모일**"); h_name.write("**기업 정보**"); h_price.write("**공모가**"); h_size.write("**규모**"); h_curr.write("**현재가**"); h_exch.write("**거래소**")
            
            one_year_ago = today - timedelta(days=365)

            for i, row in display_df.iterrows():
                col_logo, col_date, col_name, col_price, col_size, col_curr, col_exch = st.columns([0.6, 1.2, 2.5, 1.2, 1.2, 1.2, 1.2])
                ipo_date = row['공모일_dt'].date()
                
                # (1) 이모지 표시 로직: 상장일 기준 1년 여부 판단
                with col_logo:
                    if ipo_date > one_year_ago:
                        # 상장 예정 포함 1년 미만인 기업: 🐣
                        emoji = "🐣"
                        bg_color = "#fff9db" # 연노랑
                        border_color = "#ffe066"
                    else:
                        # 상장한 지 1년 이상된 기업: 🦄
                        emoji = "🦄"
                        bg_color = "#f3f0ff" # 연보라
                        border_color = "#d0bfff"
                    
                    st.markdown(f"""
                        <div style="display: flex; align-items: center; justify-content: center; 
                                    width: 40px; height: 40px; background-color: {bg_color}; 
                                    border-radius: 10px; border: 1px solid {border_color}; font-size: 20px;">
                            {emoji}
                        </div>
                    """, unsafe_allow_html=True)
                
                # (2) 공모일 (상장 예정일이 오늘 이후면 파란색 강조)
                is_future = ipo_date > today
                col_date.markdown(f"<div style='padding-top:10px; color:{'#4f46e5' if is_future else '#888888'};'>{row['date']}</div>", unsafe_allow_html=True)
                
                # (3) 기업 정보
                with col_name:
                    st.markdown(f"<small style='color:#888;'>{row['symbol']}</small>", unsafe_allow_html=True)
                    if st.button(row['name'], key=f"n_{row['symbol']}_{i}", use_container_width=True):
                        st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()
                
                # (4) 공모가 / (5) 규모 / (6) 현재가 / (7) 거래소 (기존 로직 유지)
                # ... [중략: 이전 코드와 동일] ...
                p_raw = row.get('price', '')
                p_num = pd.to_numeric(str(p_raw).replace('$', '').split('-')[0], errors='coerce')
                col_price.markdown(f"<div style='padding-top:10px;'>${p_num:,.2f}</div>" if pd.notnull(p_num) and p_num > 0 else f"<div style='padding-top:10px;'>{p_raw if p_raw else 'TBD'}</div>", unsafe_allow_html=True)
                
                s_raw = row.get('numberOfShares', '')
                s_num = pd.to_numeric(s_raw, errors='coerce')
                if pd.notnull(p_num) and pd.notnull(s_num) and p_num * s_num > 0:
                    col_size.markdown(f"<div style='padding-top:10px;'>${(p_num * s_num / 1000000):,.1f}M</div>", unsafe_allow_html=True)
                else: col_size.markdown("<div style='padding-top:10px;'>Pending</div>", unsafe_allow_html=True)

                if ipo_date <= today:
                    cp = get_current_stock_price(row['symbol'], MY_API_KEY)
                    try: p_ref = float(str(row.get('price', '0')).replace('$', '').split('-')[0])
                    except: p_ref = 0
                    if cp > 0 and p_ref > 0:
                        chg_pct = ((cp - p_ref) / p_ref) * 100
                        color = "#28a745" if chg_pct >= 0 else "#dc3545"
                        icon = "▲" if chg_pct >= 0 else "▼"
                        col_curr.markdown(f"<div style='padding-top:5px; line-height:1.2;'><b style='color:{color};'>${cp:,.2f}</b><br><small style='color:{color}; font-size:10px;'>{icon}{abs(chg_pct):.1f}%</small></div>", unsafe_allow_html=True)
                    else: col_curr.markdown(f"<div style='padding-top:10px;'>${cp:,.2f}</div>" if cp > 0 else "<div style='padding-top:10px;'>-</div>", unsafe_allow_html=True)
                else: col_curr.markdown("<div style='padding-top:10px; color:#666;'>대기</div>", unsafe_allow_html=True)

                exch_raw = row.get('exchange', 'TBD')
                exch_str = str(exch_raw).upper()
                display_exch = "NASDAQ" if "NASDAQ" in exch_str else ("NYSE" if "NYSE" in exch_str or "NEW YORK" in exch_str else exch_raw)
                col_exch.markdown(f"<div style='padding-top:10px;'>🏛️ {display_exch}</div>", unsafe_allow_html=True)
                
                st.write("") 
        else:
            st.warning("조건에 맞는 유효한 기업 데이터가 없습니다.")

# 5. 상세 페이지
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        # [성장 단계 판별]
        today = datetime.now().date()
        one_year_ago = today - timedelta(days=365)
        try:
            ipo_dt = stock['공모일_dt'].date() if hasattr(stock['공모일_dt'], 'date') else pd.to_datetime(stock['공모일_dt']).date()
        except:
            ipo_dt = today
        
        status_emoji = "🐣" if ipo_dt > one_year_ago else "🦄"

        # 1. 상단 버튼
        if st.button("⬅️ 목록으로"): 
            st.session_state.page = 'calendar'
            st.rerun()

        # ---------------------------------------------------------
        # [데이터 로딩 및 예외 처리 - 복구된 부분]
        # ---------------------------------------------------------
        with st.spinner(f"🤖 {stock['name']}의 실시간 데이터를 AI가 분석 중입니다..."):
            # 공모가 정제
            try:
                off_val = str(stock.get('price', '0')).replace('$', '').split('-')[0].strip()
                offering_p = float(off_val) if off_val and off_val != 'TBD' else 0
            except:
                offering_p = 0
                
            # API 데이터 호출 및 예외 처리
            try:
                current_p = get_current_stock_price(stock['symbol'], MY_API_KEY)
                profile = get_company_profile(stock['symbol'], MY_API_KEY)
                fin_data = get_financial_metrics(stock['symbol'], MY_API_KEY)
            except Exception as e:
                st.error(f"⚠️ 데이터 로드 중 오류 발생: {e}")
                current_p, profile, fin_data = 0, None, None
        
        # 2. 수익률 디자인 (HTML/CSS 보강)
        if current_p > 0 and offering_p > 0:
            change_pct = ((current_p - offering_p) / offering_p) * 100
            pct_color = "#00ff41" if change_pct >= 0 else "#ff4b4b" 
            icon = "▲" if change_pct >= 0 else "▼"
            price_html = f"""
                <span style='font-weight: normal; margin-left: 15px;'>
                    (공모 ${offering_p:,.2f} / 현재 ${current_p:,.2f} 
                    <span style='color: {pct_color}; font-weight: 900; background-color: #1a1a1a; padding: 2px 10px; border-radius: 8px; border: 1px solid {pct_color}33;'>
                        {icon} {abs(change_pct):.1f}%
                    </span>)
                </span>
            """
        else:
            p_text = f"${offering_p:,.2f}" if offering_p > 0 else "TBD"
            price_html = f"<span style='font-weight: normal; margin-left:15px;'>(공모 {p_text} / 상장 대기)</span>"

        st.markdown(f"<h1 style='display:flex; align-items:center;'>{status_emoji} {stock['name']} {price_html}</h1>", unsafe_allow_html=True)
        st.write("---")
        
        # 3. 탭 구성
        tab0, tab1, tab2, tab3 = st.tabs(["📰 실시간 뉴스", "📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])
        
        # --- [Tab 0: 뉴스 요약 (인터랙션 복구)] ---
        with tab0:
            if 'news_topic' not in st.session_state:
                st.session_state.news_topic = "💰 공모가 범위/확정 소식"

            r1c1, r1c2 = st.columns(2)
            r2c1, r2c2 = st.columns(2)
            if r1c1.button("💰 공모가 범위/확정 소식", use_container_width=True, key="n1"): st.session_state.news_topic = "💰 공모가 범위/확정 소식"
            if r1c2.button("📅 상장 일정/연기 소식", use_container_width=True, key="n2"): st.session_state.news_topic = "📅 상장 일정/연기 소식"
            if r2c1.button("🥊 경쟁사 비교/분석", use_container_width=True, key="n3"): st.session_state.news_topic = "🥊 경쟁사 비교/분석"
            if r2c2.button("🏦 주요 주간사 (Underwriters)", use_container_width=True, key="n4"): st.session_state.news_topic = "🏦 주요 주간사 (Underwriters)"

            topic = st.session_state.news_topic
            reps = {
                "💰 공모가 범위/확정 소식": f"현재 {stock['name']}의 공모가 범위는 {stock.get('price', 'TBD')}입니다. 수요예측 결과가 긍정적입니다.",
                "📅 상장 일정/연기 소식": f"{stock['name']}은 {stock['date']} 상장 예정이며, 일정 변동 가능성을 모니터링 중입니다.",
                "🥊 경쟁사 비교/분석": f"{stock['name']}은 동종 섹터 대비 기술적 우위에 있으나 마케팅 비용 증가가 리스크입니다.",
                "🏦 주요 주간사 (Underwriters)": f"골드만삭스 등 대형 IB가 참여하여 상장 초기 주가 방어력이 기대됩니다."
            }
            st.markdown(f"""
                <div style='background-color: #f0f4ff; padding: 20px; border-radius: 15px; border-left: 5px solid #6e8efb; margin-top: 10px;'>
                    <h5 style='color:#333; margin-bottom:10px;'>🤖 AI 실시간 요약: {topic}</h5>
                    <p style='color:#444;'>{reps.get(topic)}</p>
                </div>
            """, unsafe_allow_html=True)
            
            st.write("---")
            st.markdown(f"##### 🔥 {stock['name']} 관련 인기 뉴스")
            news_topics = [
                {"title": "IPO 주요 투자 위험 요소 분석", "tag": "분석"},
                {"title": "월가 전문가 실시간 평가", "tag": "시장"},
                {"title": "상장 후 주가 전망 리포트", "tag": "전망"}
            ]
            for i, news in enumerate(news_topics):
                url = f"https://www.google.com/search?q={stock['name']}+{news['tag']}&tbm=nws"
                st.markdown(f"• TOP {i+1} [{news['title']}]({url})")

        # --- [Tab 1: 핵심 정보] ---
        with tab1:
            cc1, cc2 = st.columns([1.5, 1])
            with cc1:
                st.markdown(f"#### 📑 {stock['name']} 비즈니스 요약")
                biz = profile.get('description', "데이터 확인 중") if profile else "☕ API 호출 제한으로 정보를 불러오지 못했습니다."
                st.markdown(f"<div style='background:#fdf6e3; padding:15px; border-radius:10px; border-left:5px solid #ffa500;'>{biz[:400]}...</div>", unsafe_allow_html=True)
                st.markdown(f"[SEC EDGAR 공시 원문 보기](https://www.sec.gov/edgar/search/#/q={stock['name'].replace(' ','%20')})")
            with cc2:
                st.markdown("#### 📊 재무 현황 (TTM)")
                if fin_data:
                    df_fin = pd.DataFrame({"항목": ["성장률", "영업이익률", "순이익률"], 
                                         "수치": [f"{fin_data['growth']}%", f"{fin_data['op_margin']}%", f"{fin_data['net_margin']}%"]})
                    st.table(df_fin)
                else:
                    st.warning("☕ 재무 데이터를 가져올 수 없습니다.")

        # --- [Tab 2: AI 가치 평가 (로직 복구)] ---
        with tab2:
            # 학술적 방법론 디자인 복구
            st.markdown("##### 🔬 가치 평가 방법론 (Academic Methodology)")
            m_cols = st.columns(3)
            with m_cols[0]: st.caption("Relative Valuation\n(Kim & Ritter, 1999)")
            with m_cols[1]: st.caption("Fair Value Model\n(Purnanandam, 2004)")
            with m_cols[2]: st.caption("Margin of Safety\n(Loughran & Ritter)")

            # 점수 산출 및 프로그레스 바
            g_score, p_score, i_score = 75, 60, 85
            total_score = (g_score * 0.4) + (p_score * 0.3) + (i_score * 0.3)
            
            st.markdown(f"### 종합 매력도: {total_score:.1f} / 100")
            c_met = st.columns(3)
            c_met[0].metric("성장성", f"{g_score}점"); c_met[0].progress(g_score/100)
            c_met[1].metric("수익성", f"{p_score}점"); c_met[1].progress(p_score/100)
            c_met[2].metric("관심도", f"{i_score}점"); c_met[2].progress(i_score/100)
            
            fair_low = offering_p * 1.1 if offering_p > 0 else 25.0
            st.success(f"🤖 AI 추정 적정가 범위: ${fair_low:.2f} ~ ${fair_low*1.3:.2f}")

        # --- [Tab 3: 최종 투자 결정 (커뮤니티/보관함)] ---
        with tab3:
            sid = stock['symbol']
            if sid not in st.session_state.vote_data: st.session_state.vote_data[sid] = {'u': 10, 'f': 3}
            if sid not in st.session_state.comment_data: st.session_state.comment_data[sid] = []
            if 'user_votes' not in st.session_state: st.session_state.user_votes = {}

            # 투표 기능 (중복 방지 포함)
            st.markdown("### 🗳️ 투표")
            if st.session_state.auth_status == 'user':
                if sid not in st.session_state.user_votes:
                    v1, v2 = st.columns(2)
                    if v1.button("🦄 Unicorn", use_container_width=True, key=f"u_{sid}"): 
                        st.session_state.vote_data[sid]['u'] += 1
                        st.session_state.user_votes[sid] = 'u'; st.rerun()
                    if v2.button("💸 Fallen Angel", use_container_width=True, key=f"f_{sid}"): 
                        st.session_state.vote_data[sid]['f'] += 1
                        st.session_state.user_votes[sid] = 'f'; st.rerun()
                else:
                    st.info(f"✅ 참여 완료 ({'유니콘' if st.session_state.user_votes[sid]=='u' else '폴른엔젤'})")
            
            # 보관함 로직
            st.write("---")
            if sid not in st.session_state.watchlist:
                if st.button("⭐ 보관함 담기", use_container_width=True, type="primary"):
                    st.session_state.watchlist.append(sid); st.balloons(); st.rerun()
            else:
                if st.button("❌ 보관함 해제", use_container_width=True):
                    st.session_state.watchlist.remove(sid); st.rerun()


























































































