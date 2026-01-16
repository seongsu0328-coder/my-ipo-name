import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- CSS 스타일 (디자인 강화) ---
st.markdown("""
    <style>
    /* 3D 텍스트 기업명 (기존 유지) */
    div.stButton > button[key^="name_"] {
        background-color: transparent !important; border: none !important;
        color: #6e8efb !important; font-weight: 900 !important; font-size: 18px !important;
        text-shadow: 1px 1px 0px #eeeeee, 2px 2px 0px #dddddd, 3px 3px 2px rgba(0,0,0,0.15) !important;
    }
    /* 상세페이지 카드 스타일 */
    .report-card {
        background-color: #ffffff; padding: 20px; border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1); border: 1px solid #f0f2f6; margin-bottom: 20px;
    }
    .metric-label { font-size: 14px; color: #666; margin-bottom: 5px; }
    .metric-value { font-size: 22px; font-weight: bold; color: #1f77b4; }
    </style>
""", unsafe_allow_html=True)

# API 키 및 세션 설정 (생략 방지용 유지)
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"
for key in ['auth_status', 'page', 'swipe_idx', 'selected_stock']:
    if key not in st.session_state:
        st.session_state[key] = None if key in ['auth_status', 'selected_stock'] else ('stats' if key == 'page' else 0)

# 데이터 호출 함수
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

# --- 화면 1, 2, 3 로직 (필터링 적용 상태 유지) ---
if st.session_state.auth_status is None:
    # [로그인 화면 생략 - 기존과 동일]
    st.write("<div style='text-align: center; margin-top: 50px;'><h1>🦄 Unicornfinder</h1><h3>당신의 다음 유니콘을 찾아보세요</h3></div>", unsafe_allow_html=True)
    st.divider()
    _, col_m, _ = st.columns([1, 2, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", key="login_phone")
        if st.button("비회원 시작", use_container_width=True): st.session_state.auth_status = 'guest'; st.rerun()
    st.stop()

if st.session_state.page == 'stats':
    # [시장 분석 카드 생략 - 기존과 동일]
    st.title("🦄 Unicornfinder 분석")
    if st.button("탐험", key="go_cal_baby"): st.session_state.page = 'calendar'; st.rerun()

elif st.session_state.page == 'calendar':
    # [캘린더 목록 생략 - 기존 필터링 유지]
    st.header("🚀 상장 예정 유니콘 캘린더")
    df = get_ipo_data(MY_API_KEY, 60)
    if not df.empty:
        df['공모일'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        result_df = df.sort_values(by='공모일').reset_index(drop=True)
        for i, row in result_df.iterrows():
            c1, c2, c3 = st.columns([1, 3, 1])
            c1.write(row['공모일'])
            if c2.button(row['name'], key=f"name_{row['symbol']}_{i}"):
                st.session_state.selected_stock = row
                st.session_state.page = 'detail'
                st.rerun()
            c3.write(row['symbol'])

# ==========================================
# 🚀 화면 4: 개선된 상세 분석 리포트
# ==========================================
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    
    # 상단 네비게이션
    col_back, col_title = st.columns([1, 5])
    if col_back.button("⬅️ 목록으로"):
        st.session_state.page = 'calendar'; st.rerun()
    
    st.markdown(f"## 📊 {stock['name']} 투자 리포트")
    st.write(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    # 섹션 1: 기업 기본 정보 카드
    with st.container():
        c1, c2 = st.columns([1, 3])
        with c1:
            logo_url = f"https://logo.clearbit.com/{stock['symbol']}.com"
            try: st.image(logo_url, width=150)
            except: st.info("로고 준비 중")
        with c2:
            st.subheader(f"{stock['name']} ({stock['symbol']})")
            st.markdown(f"**상장 거래소:** `{stock.get('exchange', '공시 참조')}`")
            st.markdown(f"**예정 상장일:** `{stock['date']}`")
            
    st.divider()

    # 섹션 2: 주요 공모 지표 (메트릭 강화)
    st.markdown("### 💰 IPO 주요 지표")
    m1, m2, m3, m4 = st.columns(4)
    
    price = pd.to_numeric(stock.get('price'), errors='coerce')
    shares = pd.to_numeric(stock.get('numberOfShares'), errors='coerce')
    total = (price * shares) if (pd.notna(price) and pd.notna(shares)) else 0

    m1.metric("공모가(예정)", f"${price:,.2f}" if price > 0 else "미정")
    m2.metric("발행 주식 수", f"{shares:,.0f}" if shares > 0 else "미정")
    m3.metric("공모 규모", f"${total:,.0f}" if total > 0 else "계산 불가")
    m4.metric("시장 상태", "상장 예정" if total > 0 else "보류/대기")

    # 섹션 3: 심층 분석 및 재무 정보 (누락된 정보 보강)
    st.divider()
    st.markdown("### 🔍 기업 심층 정보")
    
    col_info_1, col_info_2 = st.columns(2)
    
    with col_info_1:
        st.markdown("""
            <div class='report-card'>
                <h4>🏦 언더라이터 (주관사)</h4>
                <p style='color: #555;'>미국 IPO의 경우 <b>Goldman Sachs, Morgan Stanley, J.P. Morgan</b> 등이 주요 주관사로 참여합니다. 
                최종 주관사 리스트는 아래 SEC 공시(S-1) 문서의 'Underwriting' 섹션에서 가장 정확하게 확인하실 수 있습니다.</p>
            </div>
        """, unsafe_allow_html=True)
        
    with col_info_2:
        st.markdown(f"""
            <div class='report-card'>
                <h4>📈 재무 및 실적 데이터</h4>
                <p style='color: #555;'>상장 전 기업은 야후 파이낸스에서 티커 <b>{stock['symbol']}</b> 검색 시 실시간 시세와 
                간이 재무제표가 상장 직후 활성화됩니다. 상세 재무는 S-1 공시 내 'Financial Statements'를 참조하세요.</p>
            </div>
        """, unsafe_allow_html=True)

    # 섹션 4: 외부 링크 버튼 (재무/공시 바로가기)
    st.markdown("### 🔗 외부 리서치 링크")
    l1, l2, l3 = st.columns(3)
    
    # 1. SEC 공시 (가장 정확한 언더라이터/재무 정보 소스)
    sec_url = f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={stock['symbol']}&owner=exclude&action=getcompany"
    l1.link_button("📄 SEC 공식 공시(S-1) 확인", sec_url, use_container_width=True, help="주관사 및 상세 재무 확인 가능")
    
    # 2. 야후 파이낸스 (상장 후 재무지표 확인 소스)
    yahoo_url = f"https://finance.yahoo.com/quote/{stock['symbol']}"
    l2.link_button("📊 Yahoo Finance 재무 정보", yahoo_url, use_container_width=True)
    
    # 3. 구글 파이낸스 (뉴스 및 시세)
    google_url = f"https://www.google.com/finance/quote/{stock['symbol']}:NASDAQ"
    l3.link_button("📰 Google Finance 뉴스", google_url, use_container_width=True)

    st.write("")
    st.warning("⚠️ **투자 유의사항**: 본 정보는 Finnhub 데이터를 기반으로 제공되며, 실제 공모가 및 일정은 시장 상황에 따라 상장 직전까지 변동될 수 있습니다.")
