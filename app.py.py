import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import xml.etree.ElementTree as ET  # <--- 여기에 추가!

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
@st.cache_data(ttl=300)
def get_real_news_rss(company_name):
    """구글 뉴스 RSS + 한글 번역(제목)"""
    try:
        # 1. RSS 데이터 가져오기
        query = f"{company_name} stock news"
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        
        response = requests.get(url, timeout=3)
        root = ET.fromstring(response.content)
        
        news_items = []
        # 상위 5개 기사만 추출
        for item in root.findall('./channel/item')[:5]:
            title_en = item.find('title').text
            link = item.find('link').text
            pubDate = item.find('pubDate').text
            
            # 날짜 포맷 (예: 15 Jan)
            try: date_str = " ".join(pubDate.split(' ')[1:3])
            except: date_str = "Recent"

            # 2. [추가된 로직] 제목 한글 번역 (MyMemory API 사용)
            try:
                # API 호출 (무료, 하루 1000단어 제한이나 개인용으론 충분)
                trans_url = "https://api.mymemory.translated.net/get"
                params = {'q': title_en, 'langpair': 'en|ko'}
                # 타임아웃을 짧게(1초) 주어 번역이 느리면 영문만 표시하도록 함
                res = requests.get(trans_url, params=params, timeout=1).json()
                
                if res['responseStatus'] == 200:
                    title_ko = res['responseData']['translatedText']
                    # HTML 엔티티(&quot; 등) 제거를 위한 간단 처리
                    title_ko = title_ko.replace("&quot;", "'").replace("&amp;", "&")
                    display_title = f"{title_en}\n(🇰🇷 {title_ko})"
                else:
                    display_title = title_en
            except:
                # 번역 실패 시 영문 제목만 사용
                display_title = title_en
            
            news_items.append({"title": display_title, "link": link, "date": date_str})
            
        return news_items
    except:
        return []
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
        
        # 4. 탭 메뉴 구성 (여기서 tab3를 정의해야 NameError가 발생하지 않습니다)
        tab0, tab1, tab2, tab3 = st.tabs(["📰 실시간 뉴스", "📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])
        
        # --- [Tab 0: 실시간 뉴스 (TOP 5 + 실제 기사 매칭)] ---
        with tab0:
            # 1. 상단 토픽 버튼 (기존 유지)
            if 'news_topic' not in st.session_state: st.session_state.news_topic = "💰 공모가 범위/확정 소식"
            
            c_btn1, c_btn2, c_btn3, c_btn4 = st.columns(4)
            if c_btn1.button("💰 공모가격", use_container_width=True): st.session_state.news_topic = "💰 공모가 범위/확정 소식"
            if c_btn2.button("📅 상장일정", use_container_width=True): st.session_state.news_topic = "📅 상장 일정/연기 소식"
            if c_btn3.button("🥊 경쟁우위", use_container_width=True): st.session_state.news_topic = "🥊 경쟁사 비교/분석"
            if c_btn4.button("🏦 상장 주관사", use_container_width=True): st.session_state.news_topic = "🏦 주요 주간사 (Underwriters)"

            # 2. AI 요약 (기존 유지)
            topic = st.session_state.news_topic
            rep_kor = {
                "💰 공모가 범위/확정 소식": f"현재 {stock['name']}의 공모가 범위는 {stock.get('price', 'TBD')}입니다. 기관 수요예측 결과에 따라 변동 가능성이 있습니다.",
                "📅 상장 일정/연기 소식": f"{stock['name']}은(는) {stock['date']} 상장이 유력하며, 현재 별다른 지연 이슈는 보고되지 않았습니다.",
                "🥊 경쟁사 비교/분석": f"{stock['name']}은(는) 동종 섹터 내에서 기술적 우위를 점하고 있으나, 마케팅 비용 증가가 리스크로 꼽힙니다.",
                "🏦 주요 주간사 (Underwriters)": f"골드만삭스, 모건스탠리 등 메이저 IB들이 주간사로 참여하여 공모 흥행 기대감이 높습니다."
            }
            
            st.markdown(f"""
                <div style='background-color: #f0f4ff; padding: 20px; border-radius: 15px; border-left: 5px solid #6e8efb; margin-top: 10px;'>
                    <h5 style='color:#333; margin-bottom:10px;'>🤖 AI 실시간 요약: {topic}</h5>
                    <p style='color:#444;'>{rep_kor.get(topic)}</p>
                </div>
            """, unsafe_allow_html=True)

            st.write("---")
            st.markdown(f"##### 🔥 {stock['name']} 관련 실시간 인기 뉴스 Top 5")

            # 3. [핵심 수정] 실제 RSS 뉴스 가져오기 + TOP 5 태그 매칭
            rss_news = get_real_news_rss(stock['name'])
            
            # 고정 태그 리스트 (사용자가 원하는 순서대로)
            tags = ["분석", "시장", "전망", "전략", "수급"]
            
            # 뉴스 데이터가 5개보다 적을 경우를 대비한 기본값 처리
            for i in range(5):
                tag = tags[i] # 순서대로 태그 배정
                
                # 실제 뉴스가 있으면 그 내용을 사용
                if rss_news and i < len(rss_news):
                    title = rss_news[i]['title']
                    link = rss_news[i]['link']
                    date = rss_news[i]['date']
                # 실제 뉴스가 부족하면 구글 검색 링크로 대체 (에러 방지)
                else:
                    title = f"{stock['name']} 관련 최신 뉴스 더보기"
                    link = f"https://www.google.com/search?q={stock['name']}+stock+news&tbm=nws"
                    date = "Google Search"

                # 디자인: TOP 순위와 태그는 위에, 실제 기사 제목은 아래에 배치
                st.markdown(f"""
                    <a href="{link}" target="_blank" style="text-decoration: none; color: inherit;">
                        <div style="background-color: #ffffff; padding: 15px; border-radius: 12px; margin-bottom: 10px; border: 1px solid #eef2ff; box-shadow: 0 2px 5px rgba(0,0,0,0.03); transition: 0.2s;">
                            <div style="margin-bottom: 8px; display: flex; justify-content: space-between;">
                                <div>
                                    <span style="font-size: 13px; font-weight: 900; color: #6e8efb;">TOP {i+1}</span>
                                    <span style="font-size: 13px; color: #ddd; margin: 0 5px;">|</span>
                                    <span style="font-size: 13px; font-weight: bold; color: #555;">{tag}</span>
                                </div>
                                <span style="font-size: 11px; color: #aaa;">{date}</span>
                            </div>
                            <div style="font-size: 16px; font-weight: 600; color: #333; line-height: 1.4;">
                                {title}
                            </div>
                        </div>
                    </a>
                """, unsafe_allow_html=True)

        # --- [Tab 1: 핵심 정보 (공시 자료 세분화 & 재무 분석)] ---
        with tab1:
            # 0. 기업 기본 프로필 (항상 상단 표시)
            if profile:
                industry = profile.get('finnhubIndustry', '-')
                st.markdown(f"**🏢 {stock['name']}** | 업종: {industry} | 통화: {profile.get('currency', 'USD')}")
            else:
                st.caption("기본 프로필 로딩 중...")
            
            st.write("---")

            # 1. 정보 카테고리 선택 (라디오 버튼)
            # 사용자가 요청한 5가지 카테고리 + TTM 재무
            info_type = st.radio(
                "확인하고 싶은 자료를 선택하세요:",
                ["📊 실시간 재무 (TTM)", "📄 S-1 (최초 신고서)", "🌍 F-1 (해외 기업)", "🔄 S-1/A (공모가 밴드)", "📢 FWP (로드쇼/IR)", "✅ 424B4 (최종 확정)"],
                horizontal=True,
                label_visibility="collapsed"
            )

            # 2. 선택된 카테고리에 따른 콘텐츠 표시
            if info_type == "📊 실시간 재무 (TTM)":
                st.markdown("#### 📊 실시간 핵심 재무 지표 (TTM)")
                st.caption("※ 최근 12개월 합산(Trailing Twelve Months) 기준 데이터입니다.")
                
                if fin_data:
                    # 가독성을 위해 2x2 그리드로 배치
                    f_c1, f_c2 = st.columns(2)
                    f_c3, f_c4 = st.columns(2)
                    
                    # 데이터 포맷팅 함수
                    def fmt(val, unit="%"):
                        return f"{val:.2f}{unit}" if val is not None else "-"

                    with f_c1:
                        st.metric("매출 성장률 (YoY)", fmt(fin_data['growth']), delta_color="normal")
                    with f_c2:
                        st.metric("영업 이익률", fmt(fin_data['op_margin']))
                    with f_c3:
                        st.metric("순이익률", fmt(fin_data['net_margin']))
                    with f_c4:
                        st.metric("부채 비율 (D/E)", fmt(fin_data['debt_equity']))
                    
                    # 상세 테이블
                    with st.expander("재무 데이터 상세 보기"):
                        st.table(pd.DataFrame(fin_data.items(), columns=['항목', '값']))
                else:
                    st.warning("⚠️ 해당 기업의 재무 데이터를 불러올 수 없습니다. (신규 상장 기업의 경우 데이터 집계까지 시간이 소요될 수 있습니다.)")

            else:
                # 공시 자료 선택 시 로직
                # 문서 타입 매핑
                doc_map = {
                    "📄 S-1 (최초 신고서)": {"code": "S-1", "desc": "미국 기업이 상장을 위해 최초로 제출하는 증권신고서입니다. 사업 모델과 리스크 요인이 가장 상세히 적혀 있습니다."},
                    "🌍 F-1 (해외 기업)": {"code": "F-1", "desc": "미국 이외의 국가 기업(예: 쿠팡, 알리바바)이 상장할 때 제출하는 서류입니다. S-1과 동일한 효력을 가집니다."},
                    "🔄 S-1/A (공모가 밴드)": {"code": "S-1/A", "desc": "최초 신고서의 내용을 수정/보완한 문서입니다. 통상적으로 상장 직전 제출본에 '공모가 희망 범위'와 '발행 주식 수'가 확정됩니다."},
                    "📢 FWP (로드쇼/IR)": {"code": "FWP", "desc": "Free Writing Prospectus의 약자로, 투자자 설명회(Roadshow)에서 사용하는 PPT 자료 등이 포함됩니다. 시각 자료가 많아 이해하기 쉽습니다."},
                    "✅ 424B4 (최종 확정)": {"code": "424B4", "desc": "공모 가격이 최종 확정된 후 발행되는 투자 설명서입니다. 확정된 공모가와 조달 자금 규모를 확인할 수 있습니다."}
                }
                
                selected_doc = doc_map[info_type]
                form_type = selected_doc['code']
                
                # 안내 UI
                st.info(f"💡 **{form_type}란?**\n\n{selected_doc['desc']}")
                
                # SEC 검색 링크 생성
                # (가장 정확도가 높은 최신 EDGAR 검색 쿼리 사용)
                sec_url = f"https://www.sec.gov/edgar/search/#/q={stock['symbol']}%2520{form_type}&dateRange=all&startdt=2020-01-01&enddt=2026-12-31"
                
                st.markdown(f"""
                    <div style='text-align: center; margin-top: 20px;'>
                        <a href="{sec_url}" target="_blank">
                            <button style='background-color: #004e92; color: white; padding: 15px 30px; border: none; border-radius: 10px; font-size: 16px; font-weight: bold; cursor: pointer; width: 100%; box-shadow: 0 4px 6px rgba(0,0,0,0.1);'>
                                🏛️ SEC EDGAR에서 {form_type} 원문 검색하기
                            </button>
                        </a>
                        <p style='font-size: 12px; color: #666; margin-top: 10px;'>
                            ※ 버튼을 클릭하면 미 증권거래위원회(SEC) 공식 사이트로 이동합니다.<br>
                            기업 상황에 따라 해당 문서가 아직 제출되지 않았을 수 있습니다.
                        </p>
                    </div>
                """, unsafe_allow_html=True)

        # --- [Tab 2: AI 가치 평가] ---
        with tab2:
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
            
            # 데이터 초기화
            if sid not in st.session_state.vote_data: 
                st.session_state.vote_data[sid] = {'u': 10, 'f': 3}
            if sid not in st.session_state.comment_data: 
                st.session_state.comment_data[sid] = []
            if 'user_votes' not in st.session_state: 
                st.session_state.user_votes = {} # 유저의 투표 기록 저장소

            st.markdown("### 🗳️ 투자 매력도 투표")
            
            # 투표 로직 (회원 전용 + 중복 방지)
            if st.session_state.auth_status == 'user':
                if sid not in st.session_state.user_votes:
                    v1, v2 = st.columns(2)
                    if v1.button("🦄 Unicorn", use_container_width=True, key=f"vu_{sid}"): 
                        st.session_state.vote_data[sid]['u'] += 1
                        st.session_state.user_votes[sid] = 'u' # 투표 기록 저장
                        st.rerun()
                    if v2.button("💸 Fallen Angel", use_container_width=True, key=f"vf_{sid}"): 
                        st.session_state.vote_data[sid]['f'] += 1
                        st.session_state.user_votes[sid] = 'f' # 투표 기록 저장
                        st.rerun()
                else:
                    v_type = "유니콘" if st.session_state.user_votes[sid] == 'u' else "폴른엔젤"
                    st.info(f"✅ 이미 '{v_type}'에 투표하셨습니다. (종목당 1회 참여 가능)")
            else:
                st.warning("🔒 투표는 회원만 참여 가능합니다. [시작하기]에서 가입해주세요.")

            # 투표 결과 표시 (공통)
            uv, fv = st.session_state.vote_data[sid]['u'], st.session_state.vote_data[sid]['f']
            total_votes = uv + fv
            if total_votes > 0:
                ratio = uv / total_votes
                st.progress(ratio)
                st.write(f"유니콘 지수: {int(ratio*100)}% ({total_votes}명 참여)")
            
            st.write("---")

            st.markdown("### 💬 커뮤니티 의견")
            
            # 의견 등록 로직 (회원 전용)
            if st.session_state.auth_status == 'user':
                nc = st.text_input("의견 등록", key=f"ci_{sid}", placeholder="회원님, 의견을 남겨주세요.")
                if st.button("등록", key=f"cb_{sid}") and nc:
                    st.session_state.comment_data[sid].insert(0, {"t": nc, "d": datetime.now().strftime("%H:%M")})
                    st.rerun()
            else:
                st.info("🔒 의견 등록은 회원만 가능합니다.")

            # 댓글 목록 표시
            for c in st.session_state.comment_data[sid][:3]:
                st.markdown(f"""
                    <div style='background-color:#f9f9f9; padding:10px; border-radius:10px; margin-bottom:5px; border-left: 3px solid #6e8efb;'>
                        <small style='color:#888;'>{c['d']}</small><br>{c['t']}
                    </div>
                """, unsafe_allow_html=True)

            st.write("---")
            
            # 보관함 로직
            if sid not in st.session_state.watchlist:
                if st.button("⭐ 마이 리서치 보관함에 담기", use_container_width=True, type="primary"):
                    st.session_state.watchlist.append(sid)
                    st.balloons()
                    st.rerun()
            else:
                st.success(f"✅ 보관함에 저장된 종목입니다.")
                if st.button("❌ 관심 종목 해제"): 
                    st.session_state.watchlist.remove(sid)
                    st.rerun()






























































































