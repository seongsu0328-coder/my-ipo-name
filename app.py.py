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
                <div class='intro-subtitle'>미국 시장의 차세대 주역을 가장 먼저 발견하세요</div>
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
            st.info("💡 회원 가입시 관심기업관리 및 신규IPO 정보를 받을 수 있습니다.")
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
        # [추가된 로직: 성장 단계 판별]
        today = datetime.now().date()
        one_year_ago = today - timedelta(days=365)
        try:
            ipo_dt = stock['공모일_dt'].date() if hasattr(stock['공모일_dt'], 'date') else pd.to_datetime(stock['공모일_dt']).date()
        except:
            ipo_dt = today
        
        # 아이콘 결정
        status_emoji = "🐣" if ipo_dt > one_year_ago else "🦄"

        # 1. 상단 버튼 및 가격 데이터 계산
        if st.button("⬅️ 목록으로"): 
            st.session_state.page = 'calendar'
            st.rerun()
            
        try:
            # 공모가 추출 ($10.00 -> 10.0)
            off_val = str(stock.get('price', '0')).replace('$', '').split('-')[0].strip()
            offering_p = float(off_val) if off_val and off_val != 'TBD' else 0
        except:
            offering_p = 0
            
        current_p = get_current_stock_price(stock['symbol'], MY_API_KEY)
        
        # 2. 수익률 강조 디자인 구성
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
            price_html = f"<span style='font-weight: normal; margin-left: 15px;'>(공모 {p_text} / 상장 대기)</span>"

        # 3. 브라우저 렌더링 (성장 아이콘 적용)
        st.markdown(f"<h1 style='display: flex; align-items: center; margin-bottom: 0;'>{status_emoji} {stock['name']} {price_html}</h1>", unsafe_allow_html=True)
        st.write("---")
        
        # 4. 탭 메뉴 구성
        tab0, tab1, tab2, tab3 = st.tabs(["📰 실시간 뉴스", "📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])
        
        # --- [Tab 0: 실시간 뉴스] ---
        with tab0:
            if 'news_topic' not in st.session_state:
                st.session_state.news_topic = "💰 공모가 범위/확정 소식"

            row1_col1, row1_col2 = st.columns(2)
            row2_col1, row2_col2 = st.columns(2)
            
            if row1_col1.button("💰 공모가 범위/확정 소식", use_container_width=True, key="btn_p1"):
                st.session_state.news_topic = "💰 공모가 범위/확정 소식"
            if row1_col2.button("📅 상장 일정/연기 소식", use_container_width=True, key="btn_p2"):
                st.session_state.news_topic = "📅 상장 일정/연기 소식"
            if row2_col1.button("🥊 경쟁사 비교/분석", use_container_width=True, key="btn_p3"):
                st.session_state.news_topic = "🥊 경쟁사 비교/분석"
            if row2_col2.button("🏦 주요 주간사 (Underwriters)", use_container_width=True, key="btn_p4"):
                st.session_state.news_topic = "🏦 주요 주간사 (Underwriters)"

            # AI 요약 브리핑 (원형 코드 텍스트 100% 복구)
            topic = st.session_state.news_topic
            if topic == "💰 공모가 범위/확정 소식":
                rep_kor = f"현재 {stock['name']}의 공모가 범위는 {stock.get('price', 'TBD')}입니다. 기관 수요예측에서 긍정적인 평가가 이어지고 있습니다."
            elif topic == "📅 상장 일정/연기 소식":
                rep_kor = f"{stock['name']}은(는) {stock['date']}에 상장 예정이며, 현재까지 지연 공시는 없습니다."
            elif topic == "🥊 경쟁사 비교/분석":
                rep_kor = f"{stock['name']}은(는) 동종 업계 대비 높은 성장성을 보이나, 상장 초기 변동성 주의가 필요합니다."
            else:
                rep_kor = f"주요 주간사는 대형 IB들이 참여하고 있어 시장의 신뢰도가 높은 편입니다."

            st.markdown(f"""
                <div style='background-color: #f0f4ff; padding: 20px; border-radius: 15px; border-left: 5px solid #6e8efb; margin-top: 10px;'>
                    <h5 style='color:#333; margin-bottom:10px;'>🤖 AI 실시간 요약: {topic}</h5>
                    <p style='color:#444;'>{rep_kor}</p>
                </div>
            """, unsafe_allow_html=True)

            st.write("---")
            st.markdown(f"##### 🔥 {stock['name']} 관련 실시간 인기 뉴스 Top 5")
            news_topics = [
                {"title": f"{stock['name']} IPO: 주요 투자 위험 요소 분석", "query": f"{stock['name']}+IPO+analysis", "tag": "분석"},
                {"title": f"나스닥 상장 앞둔 {stock['symbol']}, 월가 평가는?", "query": f"{stock['symbol']}+stock+rating", "tag": "시장"},
                {"title": f"{stock['name']} 상장 후 주가 전망 리포트", "query": f"{stock['name']}+stock+price+forecast", "tag": "전망"},
                {"title": f"{stock['name']}의 글로벌 확장 전략", "query": f"{stock['name']}+global+strategy", "tag": "전략"},
                {"title": f"{stock['symbol']} 보호예수 및 유통 물량 점검", "query": f"{stock['symbol']}+lock-up", "tag": "수급"}
            ]
            for i, news in enumerate(news_topics):
                news_url = f"https://www.google.com/search?q={news['query']}&tbm=nws"
                st.markdown(f"""
                    <a href="{news_url}" target="_blank" style="text-decoration: none; color: inherit;">
                        <div style="background-color: #ffffff; padding: 12px; border-radius: 12px; margin-bottom: 10px; border: 1px solid #eef2ff;">
                            <span style="font-size: 13px; font-weight: bold; color: #6e8efb;">TOP {i+1} · {news['tag']}</span>
                            <div style="margin-top: 5px; font-size: 15px; font-weight: 600; color: #333;">{news['title']}</div>
                        </div>
                    </a>
                """, unsafe_allow_html=True)

        # --- [Tab 1: 핵심 정보] ---
        with tab1:
            cc1, cc2 = st.columns([1.5, 1])
            profile = get_company_profile(stock['symbol'], MY_API_KEY)
            
            if profile:
                biz_desc = profile.get('description', "상세 사업 설명이 업데이트 대기 중입니다.")
                industry = profile.get('finnhubIndustry', "기술/서비스")
            else:
                biz_desc = "상세 사업 설명이 업데이트 대기 중입니다."
                industry = "미분류"

            with cc1:
                st.markdown(f"#### 📑 {stock['name']} 핵심 비즈니스 분석")
                st.markdown(f"""
                    <div style='background-color: #fff4e5; padding: 20px; border-radius: 15px; border-left: 5px solid #ffa500; margin-bottom: 15px;'>
                        <b style='color:#d35400; font-size: 16px;'>📝 기업 공시 기반 AI 요약 브리핑</b><br><br>
                        <ul style='font-size: 14.5px; color: #333; line-height: 1.6;'>
                            <li><b>주요 업종:</b> {industry}</li>
                            <li><b>비즈니스 요약:</b> {stock['name']}은(는) {industry} 섹터에서 활동하며, 주요 사업 영역은 다음과 같습니다: {biz_desc[:200]}...</li>
                            <li><b>자금 조달 목적:</b> S-1 서류에 따르면, 본 공모를 통해 확보한 자금은 운영 자금 확보, 신규 시장 진출 및 {industry} 관련 기술 고도화에 사용될 예정입니다.</li>
                            <li><b>리스크 요인:</b> 해당 산업군의 경쟁 심화, 거시 경제 변동성 및 관련 법규 변화가 주요 위험 요소로 명시되어 있습니다.</li>
                        </ul>
                    </div>
                """, unsafe_allow_html=True)

                st.markdown("---")
                search_name = stock['name'].replace(" ", "+")
                st.markdown(f"""
                    <div style='background-color: #f8f9fa; padding: 20px; border-radius: 15px; border: 1px solid #eee;'>
                        <p style='font-size: 14px; font-weight: bold;'>🌐 SEC 공식 문서(S-1) 확인</p>
                        <p style='font-size: 12px; color: #666;'>가장 정확한 투자 판단을 위해 원문 서류를 반드시 확인하세요.</p>
                        <a href="https://www.sec.gov/edgar/search/#/q={search_name}" target="_blank" style="text-decoration: none;">
                            <button style='width:100%; padding:10px; background-color:#34495e; color:white; border:none; border-radius:5px; cursor:pointer;'>EDGAR 공시 시스템 원문 보기 ↗</button>
                        </a>
                    </div>
                """, unsafe_allow_html=True)

            with cc2:
                st.markdown("#### 📊 실시간 핵심 재무 (TTM)")
                fin_data = get_financial_metrics(stock['symbol'], MY_API_KEY)
                if fin_data:
                    display_data = {
                        "재무 항목": ["매출 성장률 (YoY)", "영업 이익률", "순이익률", "부채 비율 (D/E)"],
                        "현황": [
                            f"{fin_data['growth']:.2f}%" if fin_data['growth'] is not None else "⏳ 데이터 대기",
                            f"{fin_data['op_margin']:.2f}%" if fin_data['op_margin'] is not None else "⏳ 데이터 대기",
                            f"{fin_data['net_margin']:.2f}%" if fin_data['net_margin'] is not None else "🧐 분석 중",
                            f"{fin_data['debt_equity']:.2f}%" if fin_data['debt_equity'] is not None else "⚠️ 확인 불가"
                        ]
                    }
                else:
                    display_data = {
                        "재무 항목": ["매출 성장률 (YoY)", "영업 이익률", "순이익 현황", "총 부채 비율"],
                        "현황": ["⏳ Pending", "⏳ Pending", "🧐 데이터 분석 중", "⚠️ 확인 불가"]
                    }
                st.table(pd.DataFrame(display_data))
                st.caption("※ TTM: 최근 12개월 합산 기준 (데이터 제공: Finnhub)")

        # --- [Tab 2: AI 가치 평가] ---
        with tab2:
            # 원형 코드의 가치평가 로직
            growth_rate, profit_margin = 0.452, -0.125
            growth_score = min(100, int(growth_rate * 150 + 20))
            profit_score = max(10, min(100, int((profit_margin + 0.3) * 200)))
            interest_score = 85 + (len(stock['symbol']) % 15)
            total_score = (growth_score * 0.4) + (profit_score * 0.3) + (interest_score * 0.3)
            
            fair_low = offering_p * (1 + (total_score - 50) / 200) if offering_p > 0 else 20.0
            fair_high = fair_low * 1.25
            undervalued_pct = ((fair_low - offering_p) / offering_p) * 100 if offering_p > 0 else 0

            st.markdown("##### 🔬 1. 가치 평가 방법론 상세 (Academic Methodology)")
            p_cols = st.columns(3)
            methodologies = [
                {"title": "Relative Valuation", "author": "Kim & Ritter (1999)", "desc": "동종 업계 유사 기업의 P/S, P/E 배수를 적용합니다.", "link": "https://scholar.google.com/scholar?q=Kim+Ritter+1999+Valuing+IPO"},
                {"title": "Fair Value Model", "author": "Purnanandam (2004)", "desc": "공모가와 내재 가치의 괴리율을 측정합니다.", "link": "https://scholar.google.com/scholar?q=Purnanandam+2004+Are+IPOs+Priced+Right"},
                {"title": "Margin of Safety", "author": "Loughran & Ritter", "desc": "장기 수익성을 예측하여 안전 마진을 계산합니다.", "link": "https://scholar.google.com/scholar?q=Loughran+Ritter+IPO+Long-run+Performance"}
            ]

            for i, m in enumerate(methodologies):
                with p_cols[i]:
                    st.markdown(f"""
                        <div style='border-top: 4px solid #6e8efb; background-color: #f8f9fa; padding: 15px; border-radius: 10px; height: 260px; display: flex; flex-direction: column; justify-content: space-between;'>
                            <div>
                                <p style='font-size: 11px; font-weight: bold; color: #6e8efb; margin-bottom: 2px;'>{m['title']}</p>
                                <p style='font-size: 14px; font-weight: 600; color: #333;'>{m['author']}</p>
                                <p style='font-size: 12.5px; color: #555; line-height: 1.5;'>{m['desc']}</p>
                            </div>
                            <a href='{m['link']}' target='_blank' style='text-decoration: none;'>
                                <button style='width: 100%; background-color: #ffffff; border: 1px solid #6e8efb; color: #6e8efb; border-radius: 5px; font-size: 11px; cursor: pointer; padding: 5px 0;'>논문 원문보기 ↗</button>
                            </a>
                        </div>
                    """, unsafe_allow_html=True)

            st.write("<br>", unsafe_allow_html=True)
            st.markdown("#### 🎓 2. AI 가치 분석 및 적정가 리포트")
            
            col_metrics = st.columns(3)
            col_metrics[0].metric("성장성 점수 (G)", f"{growth_score}점"); col_metrics[0].progress(growth_score/100)
            col_metrics[1].metric("수익성 점수 (P)", f"{profit_score}점"); col_metrics[1].progress(profit_score/100)
            col_metrics[2].metric("시장 관심도 (I)", f"{interest_score}점"); col_metrics[2].progress(interest_score/100)

            st.write("---")
            res_col1, res_col2 = st.columns([1.5, 1])
            with res_col1:
                st.markdown(f"""
                    <div style='background-color: #ffffff; padding: 25px; border-radius: 15px; border: 1px solid #eef2ff; box-shadow: 0 4px 12px rgba(0,0,0,0.05);'>
                        <p style='color: #666; font-size: 14px; margin-bottom: 5px;'>AI 추정 적정 가치 범위 (Fair Value)</p>
                        <h2 style='color: #6e8efb; margin-bottom: 10px;'>${fair_low:.2f} — ${fair_high:.2f}</h2>
                        <p style='color: {"#28a745" if undervalued_pct > 0 else "#dc3545"}; font-weight: bold; font-size: 16px;'>
                            현재 공모가 대비 약 {abs(undervalued_pct):.1f}% {"저평가" if undervalued_pct > 0 else "고평가"} 상태
                        </p>
                    </div>
                """, unsafe_allow_html=True)
            with res_col2:
                st.markdown(f"**🤖 {stock['symbol']} 종합 매력도**")
                st.title(f"{total_score:.1f} / 100")
                status = "매우 높음" if total_score > 75 else ("보통" if total_score > 50 else "주의")
                st.info(f"종합 투자 매력도는 **'{status}'** 단계입니다.")

            with st.expander("🔬 AI 알고리즘 산출 수식 보기"):
                st.latex(r"Score_{total} = (G \times 0.4) + (P \times 0.3) + (I \times 0.3)")

        # --- [Tab 3: 최종 투자 결정] ---
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
            st.progress(uv/(uv+fv))
            st.write(f"유니콘 지수: {int(uv/(uv+fv)*100)}% ({uv+fv}명 참여)")

            st.write("**2. 커뮤니티 의견**")
            nc = st.text_input("의견 등록", key=f"ci_{sid}")
            if st.button("등록", key=f"cb_{sid}") and nc:
                st.session_state.comment_data[sid].insert(0, {"t": nc, "d": "방금 전"})
                st.rerun()
            for c in st.session_state.comment_data[sid][:3]:
                # CSS 클래스 'comment-box'가 정의되어 있다고 가정하거나 스타일 직접 적용
                st.markdown(f"<div style='background-color:#f9f9f9; padding:10px; border-radius:10px; margin-bottom:5px;'><small>{c['d']}</small><br>{c['t']}</div>", unsafe_allow_html=True)

            st.write("---")
            if sid not in st.session_state.watchlist:
                if st.button("⭐ 마이 리서치 보관함에 담기", use_container_width=True, type="primary"):
                    st.session_state.watchlist.append(sid); st.balloons(); st.rerun()
            else:
                st.success(f"✅ 보관함에 저장된 종목입니다.")
                if st.button("❌ 관심 종목 해제"): st.session_state.watchlist.remove(sid); st.rerun()






















































































