import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

# 1. 환경 설정 및 API 키
st.set_page_config(page_title="미국 주식 IPO 알리미", layout="wide")
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

# 2. 제목 섹션
st.title("🚀 미국 주식 상장 예정(IPO) 캘린더")
st.markdown("스마트폰에서도 실시간으로 공시와 토론 내용을 확인할 수 있습니다.")

# 3. 데이터 로드 함수
@st.cache_data(ttl=600) # 10분마다 데이터 갱신
def get_ipo_data(api_key, days_ahead):
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    start_date = datetime.now().strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
    params = {'from': start_date, 'to': end_date, 'token': api_key}
    try:
        response = requests.get(base_url, params=params)
        data = response.json()
        return pd.DataFrame(data['ipoCalendar']) if 'ipoCalendar' in data else pd.DataFrame()
    except:
        return pd.DataFrame()

# 4. 사이드바 및 필터
days = st.sidebar.slider("조회 기간(일)", 7, 90, 30)
exclude_spac = st.sidebar.checkbox("SPAC 기업 제외", value=True)

# 5. 거래소 로고 매핑
def add_exchange_logo(exchange):
    ex = str(exchange).upper()
    if 'NASDAQ' in ex: return "🔵 NASDAQ"
    if 'NYSE' in ex: return "🏛️ NYSE"
    return f"❓ {exchange}"

# 6. 메인 실행
df = get_ipo_data(MY_API_KEY, days)

if not df.empty:
    if exclude_spac:
        df = df[~df['name'].str.contains('SPAC|Acquisition|Unit|Blank Check', case=False, na=False)]
    
    # 데이터 가공 및 링크 생성
    display_df = df[['date', 'symbol', 'name', 'price', 'numberOfShares', 'exchange']].copy()
    display_df['📄 공시'] = display_df['symbol'].apply(lambda x: f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={x}")
    display_df['📊 재무'] = display_df['symbol'].apply(lambda x: f"https://finance.yahoo.com/quote/{x}/financials")
    display_df['💬 토론'] = display_df['symbol'].apply(lambda x: f"https://finance.yahoo.com/quote/{x}/community")
    display_df['exchange'] = display_df['exchange'].apply(add_exchange_logo)
    
    display_df.columns = ['상장일', '티커', '기업명', '공모가($)', '주식수', '거래소', '공시', '재무', '토론']

    # 표 출력
    st.data_editor(
        display_df,
        column_config={
            "공시": st.column_config.LinkColumn(display_text="보기"),
            "재무": st.column_config.LinkColumn(display_text="보기"),
            "토론": st.column_config.LinkColumn(display_text="참여"),
        },
        hide_index=True, use_container_width=True, disabled=True
    )

    # --- 게시판 기능 (Stocktwits 실시간 피드) ---
    st.divider()
    st.subheader("💬 실시간 주주 의견 (Stocktwits)")
    selected_stock = st.selectbox("실시간 의견을 볼 종목을 선택하세요", display_df['기업명'].tolist())
    if selected_stock:
        ticker = display_df[display_df['기업명'] == selected_stock]['티커'].values[0]
        st.components.v1.iframe(f"https://stocktwits.com/symbol/{ticker}", height=500, scrolling=True)

else:
    st.warning("데이터가 없습니다.")
