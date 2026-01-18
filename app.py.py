import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import plotly.graph_objects as go

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

# --- 데이터 로직 ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

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

# --- 화면 제어 ---

# 1. 인트로/로그인/성장단계 분석 (생략 - 기존 코드 유지)
# [사용자님의 기존 인트로 및 로그인 로직이 들어가는 부분입니다]

if st.session_state.page == 'intro':
    st.title("🦄 UNICORN FINDER")
    if st.button("탐험 시작하기"): st.session_state.page = 'calendar'; st.rerun()

# 4. 캘린더 (상장 거래소 추가 버전)
elif st.session_state.page == 'calendar':
    st.header("🚀 IPO 리서치 센터")
    all_df = get_extended_ipo_data(MY_API_KEY)
    if not all_df.empty:
        # 정렬 및 필터링 로직 (생략 - 기존 유지)
        display_df = all_df.sort_values(by='공모일_dt', ascending=False)
        
        h1, h2, h3, h4, h5, h6 = st.columns([1.2, 3.0, 1.2, 1.2, 1.2, 1.2])
        h1.write("**공모일**"); h2.write("**기업명**"); h3.write("**공모가**"); h4.write("**규모**"); h5.write("**현재가**"); h6.write("**거래소**")
        
        for i, row in display_df.iterrows():
            col1, col2, col3, col4, col5, col6 = st.columns([1.2, 3.0, 1.2, 1.2, 1.2, 1.2])
            if col2.button(row['name'], key=f"n_{row['symbol']}_{i}", use_container_width=True):
                st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()
            col1.write(row['date'])
            col3.write(row.get('price', 'TBD'))
            col6.write(f"🏛️ {row.get('exchange', 'TBD')}")

# 5. 상세 페이지 (뉴스/공시/재무 통합본)
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        st.title(f"🚀 {stock['name']} 심층 분석")
        
        tab0, tab1, tab2, tab3 = st.tabs(["📰 실시간 뉴스", "📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 투자 결정"])
        
        with tab0:
            st.subheader("📰 투자 인사이트 브리핑")
            c1, c2, c3, c4 = st.columns(4)
            if c1.button("💰 공모가 소식"): st.session_state.news_topic = "공모가"
            if c2.button("📅 일정/연기"): st.session_state.news_topic = "일정"
            if c3.button("🥊 경쟁사 분석"): st.session_state.news_topic = "경쟁사"
            if c4.button("🏦 주요 주간사"): st.session_state.news_topic = "주간사"
            st.info(f"선택된 토픽: {st.session_state.get('news_topic', '공모가')}")

        with tab1:
            st.subheader("📋 핵심 기업 정보")
            cc1, cc2 = st.columns(2)
            with cc1:
                st.markdown("#### 📑 주요 기업 공시 (SEC)")
                if st.button("🔍 S-1 투자 설명서 한글 요약", use_container_width=True):
                    st.success("✅ 비즈니스 모델: AI 솔루션 기반 고성장세 유지 중...")
                st.markdown(f"[Edgar 시스템 바로가기 ↗](https://www.sec.gov/edgar/search/#/q={stock['name'].replace(' ','+')})")
            
            with cc2:
                st.markdown("#### 📊 연도별 핵심 재무 추이")
                # 샘플 데이터와 Plotly 그래프
                years = ['2023', '2024', '2025(E)']
                fig = go.Figure()
                fig.add_trace(go.Bar(x=years, y=[100, 150, 220], name='매출액', marker_color='#6e8efb'))
                fig.add_trace(go.Scatter(x=years, y=[-10, 5, 30], name='영업이익', line=dict(color='#ff6b6b', width=3)))
                fig.update_layout(height=300, margin=dict(l=0,r=0,t=0,b=0), legend=dict(orientation="h"))
                st.plotly_chart(fig, use_container_width=True)
                st.warning("⚠️ 데이터 불충분: 추정된 시뮬레이션 그래프입니다.")

        # 나머지 탭 생략 (기존 로직 유지)
