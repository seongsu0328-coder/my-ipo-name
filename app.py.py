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
    div.stButton > button[key^="name_"] {
        background-color: transparent !important; border: none !important;
        color: #6e8efb !important; font-weight: 900 !important; font-size: 18px !important;
        text-shadow: 1px 1px 0px #eeeeee, 2px 2px 0px #dddddd, 3px 3px 2px rgba(0,0,0,0.15) !important;
    }
    .report-card {
        background-color: #f8faff; padding: 20px; border-radius: 15px;
        border: 1px solid #e1e8f0; margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)

# API 키 및 세션 설정
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"
for key in ['auth_status', 'page', 'swipe_idx', 'selected_stock']:
    if key not in st.session_state:
        st.session_state[key] = None if key in ['auth_status', 'selected_stock'] else ('stats' if key == 'page' else 0)

# 데이터 호출
@st.cache_data(ttl=600)
def get_ipo_data(api_key, days_ahead):
    today_str = datetime.now().strftime('%Y-%m-%d')
    future_limit_str = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    params = {'from': today_str, 'to': future_limit_str, 'token': api_key}
    try:
        response = requests.get(base_url, params=params).json()
        if 'ipoCalendar' in response:
            df = pd.DataFrame(response['ipoCalendar'])
            return df[df['name'].notna() & (df['name'] != '')]
        return pd.DataFrame()
    except: return pd.DataFrame()

# 화면 로직 (로그인 및 캘린더 생략 - 기존 유지)
if st.session_state.auth_status is None:
    st.write("<div style='text-align: center; margin-top: 50px;'><h1>🦄 Unicornfinder</h1></div>", unsafe_allow_html=True)
    if st.button("비회원 시작", use_container_width=True): st.session_state.auth_status = 'guest'; st.rerun()
    st.stop()

if st.session_state.page == 'stats':
    if st.button("탐험", key="go_cal_baby"): st.session_state.page = 'calendar'; st.rerun()

elif st.session_state.page == 'calendar':
    df = get_ipo_data(MY_API_KEY, 60)
    if not df.empty:
        df['공모일'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        for i, row in df.iterrows():
            if st.button(row['name'], key=f"name_{row['symbol']}_{i}"):
                st.session_state.selected_stock = row
                st.session_state.page = 'detail'; st.rerun()

# --- 화면 4: SEC 검색 오류 해결 버전 ---
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()

    st.title(f"🚀 {stock['name']} 상세 분석")
    
    # [수정] SEC 검색용 기업명 정제 (공백을 +로 변환)
    clean_name = stock['name'].replace(" ", "+")
    # 티커 대신 기업명(companyName)으로 검색하도록 링크 변경
    sec_search_url = f"https://www.sec.gov/cgi-bin/browse-edgar?company={clean_name}&owner=exclude&action=getcompany"
    
    col_l, col_r = st.columns([1, 3])
    with col_l:
        logo_url = f"https://logo.clearbit.com/{stock['symbol']}.com"
        try: st.image(logo_url, width=150)
        except: st.info("로고 준비 중")
    with col_r:
        st.subheader(f"{stock['name']} ({stock['symbol']})")
        st.write(f"**상장일:** {stock.get('date')} | **거래소:** {stock.get('exchange', '공시 참조')}")
        st.divider()
        m1, m2 = st.columns(2)
        p, s = pd.to_numeric(stock['price'], errors='coerce'), pd.to_numeric(stock['numberOfShares'], errors='coerce')
        m1.metric("희망가", f"${p:,.2f}" if p > 0 else "미정")
        m2.metric("공모 규모", f"${(p*s):,.0f}" if p*s > 0 else "계산 불가")

    st.divider()
    st.markdown("### 🔍 투자 심층 분석")
    inf1, inf2 = st.columns(2)
    with inf1:
        st.markdown(f"""<div class='report-card'><h4>🏦 언더라이터 정보</h4>
        <p>SEC 공시 문서(S-1) 내 <b>'Underwriting'</b> 섹션에서 주관사 명단을 확인하세요.</p></div>""", unsafe_allow_html=True)
    with inf2:
        st.markdown(f"""<div class='report-card'><h4>📊 재무 정보 가이드</h4>
        <p>상장 전 상세 재무는 S-1 내 <b>'Financial Statements'</b> 섹션에 포함되어 있습니다.</p></div>""", unsafe_allow_html=True)

    # 링크 버튼 섹션
    l1, l2 = st.columns(2)
    # [중요] 수정된 SEC 검색 링크 적용
    l1.link_button("📄 SEC 공식 공시(S-1) 확인", sec_search_url, use_container_width=True, type="primary")
    l2.link_button("📈 Yahoo Finance 재무 (상장 후 활성)", f"https://finance.yahoo.com/quote/{stock['symbol']}", use_container_width=True)
