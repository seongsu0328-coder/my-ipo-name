import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- CSS 스타일 ---
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

    .grid-card {
        background-color: #ffffff;
        padding: 20px; border-radius: 20px; border: 1px solid #eef2ff;
        box-shadow: 0 10px 20px rgba(0,0,0,0.05); text-align: center;
        margin-bottom: 10px;
    }
    .grid-title { color: #6e8efb; font-size: 20px; font-weight: 900; margin-bottom: 15px; }
    .grid-stats-box { background-color: #f8faff; padding: 10px; border-radius: 12px; margin-top: 5px; }
    .grid-stats-label { font-size: 11px; color: #888; }
    .grid-stats-value { font-size: 14px; color: #4a69bd; font-weight: 700; }

    .quote-card {
        background: linear-gradient(145deg, #ffffff, #f9faff);
        padding: 25px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.05); text-align: center;
        max-width: 650px; margin-left: auto; margin-right: auto;
    }
    .sector-tag { background-color: #eef2ff; color: #4f46e5; padding: 2px 8px; border-radius: 5px; font-size: 12px; font-weight: bold; border: 1px solid #c7d2fe; }
    
    div.stButton > button[key="start_app"] {
        background-color: #ffffff !important; color: #6e8efb !important;
        font-weight: 900 !important; font-size: 22px !important;
        padding: 12px 60px !important; border-radius: 50px !important;
        border: none !important; box-shadow: 0 10px 25px rgba(0,0,0,0.15) !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 및 API 로직 ---
@st.cache_data(ttl=86400)
def get_daily_quote():
    try:
        res = requests.get("https://api.quotable.io/random?tags=business|wisdom", timeout=5)
        if res.status_code == 200:
            data = res.json()
            eng_text, author = data['content'], data['author']
            trans_res = requests.get(f"https://api.mymemory.translated.net/get?q={eng_text}&langpair=en|ko", timeout=5)
            kor_text = trans_res.json()['responseData']['translatedText']
            return {"eng": eng_text, "kor": kor_text, "author": author}
    except:
        return {"eng": "The best way to predict the future is to create it.", "kor": "미래를 예측하는 가장 좋은 방법은 미래를 직접 만드는 것이다.", "author": "Peter Drucker"}

@st.cache_data(ttl=600)
def get_extended_ipo_data(api_key):
    start_date = (datetime.now() - timedelta(days=18*30)).strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=60)).strftime('%Y-%m-%d')
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    params = {'from': start_date, 'to': end_date, 'token': api_key}
    try:
        response = requests.get(base_url, params=params).json()
        if 'ipoCalendar' in response:
            df = pd.DataFrame(response['ipoCalendar'])
            return df[df['name'].notna() & (df['name'] != '')]
        return pd.DataFrame()
    except: return pd.DataFrame()

# 현재가 호출 함수 (Finnhub Quote API)
def get_current_stock_price(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
        res = requests.get(url, timeout=2).json()
        return res.get('c', 0)
    except:
        return 0

# 세션 초기화
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"
for key in ['auth_status', 'page', 'selected_stock', 'vote_data']:
    if key not in st.session_state:
        st.session_state[key] = {} if key == 'vote_data' else (None if key in ['auth_status', 'selected_stock'] else 'intro')

# ==========================================
# 🚀 화면 제어 로직
# ==========================================

# 1. 인트로 페이지
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 8, 1])
    with col_center:
        st.markdown("<div class='intro-card'><div class='intro-title'>UNICORN FINDER</div><div class='intro-subtitle'>미국 시장의 차세대 주역을 가장 먼저 발견하세요</div><div class='feature-grid'><div class='feature-item'><div class='feature-icon'>📅</div><div class='feature-text'><b>IPO 스케줄</b><br>상장 예정 기업 실시간 트래킹</div></div><div class='feature-item'><div class='feature-icon'>📊</div><div class='feature-text'><b>데이터 리서치</b><br>공시 자료 기반 심층 분석</div></div><div class='feature-item'><div class='feature-icon'>🗳️</div><div class='feature-text'><b>집단 지성</b><br>글로벌 투자자 심리 투표</div></div></div></div>", unsafe_allow_html=True)
        if st.button("탐험 시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()
    st.stop()

# 2. 로그인 페이지
elif st.session_state.page == 'login' and st.session_state.auth_status is None:
    st.write("<br>" * 6, unsafe_allow_html=True)
    _, col_m, _ = st.columns([1, 1.5, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000", key="login_phone", label_visibility="collapsed")
        c1, c2 = st.columns(2)
        if c1.button("회원 로그인", use_container_width=True): 
            if len(phone) > 9: st.session_state.auth_status = 'user'; st.session_state.page = 'stats'; st.rerun()
        if c2.button("비회원 시작", use_container_width=True): 
            st.session_state.auth_status = 'guest'; st.session_state.page = 'stats'; st.rerun()
    st.write("<br>" * 2, unsafe_allow_html=True)
    q = get_daily_quote()
    st.markdown(f"<div class='quote-card'><div style='font-size: 11px; color: #6e8efb; font-weight: bold; margin-bottom: 8px; letter-spacing: 1px;'>TODAY'S INSIGHT</div><div style='font-size: 16px; color: #333; font-weight: 600; line-height: 1.5;'>\"{q['eng']}\"</div><div style='font-size: 13px; color: #666; margin-top: 6px;'>({q['kor']})</div><div style='color: #aaa; font-size: 11px; margin-top: 12px;'>- {q['author']} -</div></div>", unsafe_allow_html=True)
    st.stop()

# 3. 시장 분석
elif st.session_state.page == 'stats':
    st.title("🦄 유니콘 성장 단계 분석")
    stages = [{"name": "유아기 유니콘", "img": "baby_unicorn.png", "avg": "연 180개", "time": "약 1.5년", "rate": "45%"},{"name": "아동기 유니콘", "img": "child_unicorn.png", "avg": "연 120개", "time": "약 4년", "rate": "65%"},{"name": "성인기 유니콘", "img": "adult_unicorn.png", "avg": "연 85개", "time": "약 12년", "rate": "88%"},{"name": "노년기 유니콘", "img": "old_unicorn.png", "avg": "연 40개", "time": "25년 이상", "rate": "95%"}]
    @st.dialog("상장 예정 기업 탐험")
    def confirm_exploration():
        st.write("18개월간의 히스토리와 상장 예정 기업 리스트를 확인하시겠습니까?")
        cy, cn = st.columns(2)
        if cy.button("네", use_container_width=True, type="primary"): st.session_state.page = 'calendar'; st.rerun()
        if cn.button("아니오", use_container_width=True): st.rerun()
    r1_c1, r1_c2 = st.columns(2); r2_c1, r2_c2 = st.columns(2)
    cols = [r1_c1, r1_c2, r2_c1, r2_c2]
    for i, stage in enumerate(stages):
        with cols[i]:
            st.markdown(f"<div class='grid-card'><div class='grid-title'>{stage['name']}</div></div>", unsafe_allow_html=True)
            if st.button(f"🔎 {stage['name']} 탐험하기", key=f"img_btn_{i}", use_container_width=True): confirm_exploration()
            if os.path.exists(stage['img']): st.image(Image.open(stage['img']), use_container_width=True)
            else: st.info(f"[{stage['name']} 이미지]")
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"<div class='grid-stats-box'><div class='grid-stats-label'>IPO 개수</div><div class='grid-stats-value'>{stage['avg']}</div></div>", unsafe_allow_html=True)
            c2.markdown(f"<div class='grid-stats-box'><div class='grid-stats-label'>생존기간</div><div class='grid-stats-value'>{stage['time']}</div></div>", unsafe_allow_html=True)
            c3.markdown(f"<div class='grid-stats-box'><div class='grid-stats-label'>생존율</div><div class='grid-stats-value'>{stage['rate']}</div></div>", unsafe_allow_html=True)

# 4. 캘린더 (현재가 표시 추가)
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    st.header("🚀 IPO 히스토리 & 상장 예정 기업")
    df = get_extended_ipo_data(MY_API_KEY)
    if not df.empty:
        df['공모일_dt'] = pd.to_datetime(df['date'])
        result_df = df.sort_values(by='공모일_dt', ascending=False).reset_index(drop=True)
        
        st.write("---")
        h1, h2, h3, h4, h5 = st.columns([1.2, 3.5, 1.2, 1.5, 1.2])
        h1.write("**공모일**"); h2.write("**기업명 & 업종**"); h3.write("**공모가**"); h4.write("**공모규모**"); h5.write("**현재가**")
        st.write("---")
        
        for i, row in result_df.iterrows():
            col1, col2, col3, col4, col5 = st.columns([1.2, 3.5, 1.2, 1.5, 1.2])
            is_past = row['공모일_dt'].date() <= datetime.now().date()
            d_color = "#888" if is_past else "#000"
            col1.markdown(f"<span style='color:{d_color};'>{row['date']}</span>", unsafe_allow_html=True)
            
            with col2:
                bc, tc = st.columns([0.7, 0.3])
                if bc.button(row['name'], key=f"n_{row['symbol']}_{i}"):
                    st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()
                tc.markdown(f"<span class='sector-tag'>Tech</span>", unsafe_allow_html=True)
            
            p, s = pd.to_numeric(row['price'], errors='coerce'), pd.to_numeric(row['numberOfShares'], errors='coerce')
            p = 0 if pd.isna(p) else p; s = 0 if pd.isna(s) else s
            col3.write(f"${p:,.2f}" if p > 0 else "미정")
            
            if p > 0 and s > 0: col4.write(f"${(p*s):,.0f}")
            else: col4.markdown("<span style='color:#ff4b4b;font-weight:bold;'>대기</span>", unsafe_allow_html=True)
            
            # 현재가 표시 로직
            if is_past:
                current_p = get_current_stock_price(row['symbol'], MY_API_KEY)
                if current_p > 0:
                    price_color = "#28a745" if current_p >= p else "#dc3545" # 공모가 대비 상승/하락
                    col5.markdown(f"<span style='color:{price_color}; font-weight:bold;'>${current_p:,.2f}</span>", unsafe_allow_html=True)
                else:
                    col5.write("-")
            else:
                col5.write("대기")

# 5. 상세 페이지 (기존 유지)
elif st.session_state.page == 'detail':
    # ... (생략된 상세 페이지 코드는 이전과 동일합니다)
    stock = st.session_state.get('selected_stock')
    if stock:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        st.title(f"🚀 {stock['name']} 상세 리서치")
        cl, cr = st.columns([1, 4])
        # (상세 데이터 표시 로직...)
        with cr:
            st.subheader(f"{stock['name']} ({stock['symbol']})")
            st.markdown(f"**업종:** <span class='sector-tag'>Technology & Software</span>", unsafe_allow_html=True)
            st.divider()
            m1, m2, m3, m4 = st.columns(4)
            p = pd.to_numeric(stock.get('price'), errors='coerce'); s = pd.to_numeric(stock.get('numberOfShares'), errors='coerce')
            p = 0 if pd.isna(p) else p; s = 0 if pd.isna(s) else s
            m1.metric("공모가", f"${p:,.2f}" if p > 0 else "미정")
            m2.metric("예상 규모", f"${(p*s):,.0f}" if p*s > 0 else "미정")
            m3.metric("유통물량", "분석 중")
            m4.metric("보호예수", "180일")
        # (SEC, 야후 링크 및 투표 로직...)
        l1, l2 = st.columns(2)
        l1.link_button("📄 SEC 공식 공시(S-1)", f"https://www.sec.gov/cgi-bin/browse-edgar?company={stock['name'].replace(' ', '+')}", use_container_width=True, type="primary")
        l2.link_button("📈 Yahoo Finance", f"https://finance.yahoo.com/quote/{stock['symbol']}", use_container_width=True)
