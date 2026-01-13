import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

# 앱 제목 설정
st.set_page_config(page_title="미국 주식 IPO 알리미", layout="wide")
st.title("🚀 미국 주식 상장 예정(IPO) 캘린더")

def get_ipo_data(api_key, days):
    base_url = "https://finnhub.io/api/v1/calendar/ipo"
    today = datetime.now().strftime('%Y-%m-%d')
    future = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
    
    params = {'from': today, 'to': future, 'token': api_key}
    
    try:
        response = requests.get(base_url, params=params)
        data = response.json()
        if 'ipoCalendar' in data and data['ipoCalendar']:
            return pd.DataFrame(data['ipoCalendar'])
        return pd.DataFrame()
    except:
        return pd.DataFrame()

# --- 사이드바 설정 (기능 추가) ---
st.sidebar.header("⚙️ 앱 설정")
days = st.sidebar.slider("조회 기간(일)", 7, 60, 30)
exclude_spac = st.sidebar.checkbox("SPAC 기업 제외", value=True)
search_query = st.sidebar.text_input("기업명 검색", "")

# 데이터 가져오기
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"
df = get_ipo_data(MY_API_KEY, days)

if not df.empty:
    # 1. SPAC 필터링
    if exclude_spac:
        spac_pattern = 'SPAC|Acquisition|Unit|Corp II|Corp III|Blank Check'
        df = df[~df['name'].str.contains(spac_pattern, case=False, na=False)]

    # 2. 검색 기능
    if search_query:
        df = df[df['name'].str.contains(search_query, case=False) | df['symbol'].str.contains(search_query, case=False)]

    # 3. 데이터 정리 및 출력
    df = df[['date', 'symbol', 'name', 'price', 'numberOfShares', 'exchange']].sort_values('date')
    
    st.write(f"### 📅 향후 {days}일간 상장 예정 기업 ({len(df)}건)")
    st.dataframe(df, use_container_width=True) # 깔끔한 표 출력

    # 4. 엑셀 다운로드 기능
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 결과 엑셀(CSV) 다운로드",
        data=csv,
        file_name=f"IPO_Schedule_{datetime.now().strftime('%Y%m%d')}.csv",
        mime='text/csv',
    )
else:
    st.warning("조회된 IPO 데이터가 없습니다. 기간을 늘려보세요.")