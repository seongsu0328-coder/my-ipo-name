import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os

# 1. 페이지 설정 및 CSS (기존 디자인 유지)
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

st.markdown("""
    <style>
    div.stButton > button[key="go_cal_baby"] {
        display: block !important; margin: 20px auto !important;     
        width: 260px !important; height: 85px !important;
        font-size: 32px !important; font-weight: 900 !important;
        color: #ffffff !important;
        background: linear-gradient(145deg, #6e8efb, #a777e3) !important;
        border: none !important; border-radius: 20px !important;
        text-shadow: 2px 2px 0px #4a69bd !important;
        box-shadow: 0px 8px 0px #3c569b, 0px 15px 20px rgba(0,0,0,0.3) !important;
    }
    div.stButton > button[key^="p_"], div.stButton > button[key^="n_"] {
        font-size: 50px !important; font-weight: 900 !important;
        padding: 0px !important; border-radius: 12px !important;
        width: 100% !important; height: 85px !important;
        background-color: #ffffff !important; border: 3px solid #6e8efb !important;
        color: #6e8efb !important; box-shadow: 0px 5px 0px #6e8efb !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
    }
    .card-text {
        text-align: center; font-size: 1.3rem; padding: 25px;
        background-color: #f8f9fa; border-radius: 20px;
        margin-top: 15px; color: #333; border: 1px solid #eee;
    }
    </style>
""", unsafe_allow_html=True)

MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"
if 'auth_status' not in st.session_state: st.session_state.auth_status = None
if 'page' not in st.session_state: st.session_state.page = 'stats'
if 'swipe_idx' not in st.session_state: st.session_state.swipe_idx = 0

@st.cache_data(ttl=600)
def get_ipo_data(api_key, days_ahead):
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    params = {'from': datetime.now().strftime('%Y-%m-%d'), 
              'to': (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d'), 
              'token': api_key}
    try:
        response = requests.get(base_url, params=params).json()
        return pd.DataFrame(response['ipoCalendar']) if 'ipoCalendar' in response else pd.DataFrame()
    except: return pd.DataFrame()

# (화면 1, 2 로직 생략 - 기존과 동일)
if st.session_state.auth_status is None:
    # 로그인 화면...
    st.stop()

if st.session_state.page == 'stats':
    # 시장분석/유니콘 카드 화면...
    st.title("🦄 Unicornfinder 분석")
    # ... (기존 코드 생략) ...
    if st.button("탐험", key="go_cal_baby"):
        st.session_state.page = 'calendar'
        st.rerun()

# ==========================================
# 화면 3: 캘린더 (개선된 가격 표시 로직)
# ==========================================
elif st.session_state.page == 'calendar':
    if st.sidebar.button("⬅️ 돌아가기"):
        st.session_state.page = 'stats'
        st.rerun()
    
    st.header("🚀 실시간 유아기 유니콘 캘린더")
    df = get_ipo_data(MY_API_KEY, 30)

    if not df.empty:
        # 1. 수치형 변환 및 결측치 처리
        df['price'] = pd.to_numeric(df['price'], errors='coerce').fillna(0)
        df['numberOfShares'] = pd.to_numeric(df['numberOfShares'], errors='coerce').fillna(0)
        
        # 2. 가격 표시 로직 (0일 경우 '미정'으로 표시)
        # 데이터 편집기에서 텍스트로 보여주기 위해 새로운 컬럼 생성
        def format_price(p):
            return f"${p:,.2f}" if p > 0 else "공시 확인(미정)"
        
        df['희망가/공모가'] = df['price'].apply(format_price)
        
        # 3. 공모규모 계산 및 표시 로직
        df['공모규모_val'] = df['price'] * df['numberOfShares']
        def format_deal_size(val):
            return f"${val:,.0f}" if val > 0 else "계산 불가(미정)"
        
        df['공모규모($)'] = df['공모규모_val'].apply(format_deal_size)
        
        # 4. 기타 정보
        df['자금용도'] = "공시(S-1) 참조"
        df['보호예수'] = "180일(통상)"
        df['언더라이터'] = "주관사 확인" 
        df['📄 공시'] = df['symbol'].apply(lambda x: f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={x}")
        df['📊 재무'] = df['symbol'].apply(lambda x: f"https://finance.yahoo.com/quote/{x}/financials")
        
        # 5. 컬럼 재배치
        result_df = df[['name', 'symbol', '희망가/공모가', 'numberOfShares', '공모규모($)', '자금용도', '보호예수', '언더라이터', 'exchange', '📄 공시', '📊 재무']]
        result_df.columns = ['기업명', '티커', '희망가/공모가', '주식수', '공모규모($)', '자금용도', '보호예수', '언더라이터', '거래소', '공시', '재무']

        # 6. 데이터 출력 (텍스트 기반 컬럼으로 변경)
        st.data_editor(
            result_df,
            column_config={
                "주식수": st.column_config.NumberColumn(format="%d"),
                "공시": st.column_config.LinkColumn(display_text="SEC 확인"),
                "재무": st.column_config.LinkColumn(display_text="재무 지표"),
            },
            hide_index=True,
            use_container_width=True
        )
        st.info("💡 '미정'으로 표시된 항목은 상장 직전 SEC 공시를 통해 확정됩니다. 정확한 범위는 '공시' 링크 내 S-1 서류를 확인하세요.")
    else:
        st.warning("현재 예정된 IPO 데이터가 없습니다.")
