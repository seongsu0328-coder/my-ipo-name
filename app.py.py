import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import plotly.graph_objects as go

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 세션 초기화 ---
for key in ['page', 'auth_status', 'vote_data', 'comment_data', 'selected_stock', 'watchlist', 'view_mode', 'news_topic', 'show_summary']:
    if key not in st.session_state:
        if key == 'page': st.session_state[key] = 'intro'
        elif key == 'watchlist': st.session_state[key] = []
        elif key in ['vote_data', 'comment_data']: st.session_state[key] = {}
        elif key == 'view_mode': st.session_state[key] = 'all'
        elif key == 'news_topic': st.session_state[key] = "💰 공모가 범위/확정 소식"
        elif key == 'show_summary': st.session_state[key] = False
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
        if not df.empty: 
            df['공모일_dt'] = pd.to_datetime(df['date'])
        return df
    except: return pd.DataFrame()

def get_current_stock_price(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
        return requests.get(url, timeout=2).json().get('c', 0)
    except: return 0

# --- 화면 제어 ---

# 1. 인트로 페이지
if st.session_state.page == 'intro':
    st.markdown("<h1 style='text-align: center; color: #6e8efb;'>🦄 UNICORN FINDER</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>미국 주식 IPO 실시간 알리미 및 심층 분석 리포트</p>", unsafe_allow_html=True)
    if st.button("탐험 시작하기", use_container_width=True, type="primary"):
        st.session_state.page = 'calendar'; st.rerun()

# 2. 캘린더 페이지 (거래소 정보 포함)
elif st.session_state.page == 'calendar':
    st.header("🚀 IPO 리서치 센터")
    all_df = get_extended_ipo_data(MY_API_KEY)
    
    if not all_df.empty:
        display_df = all_df.sort_values(by='공모일_dt', ascending=False)
        
        st.write("---")
        h1, h2, h3, h4, h5, h6 = st.columns([1.2, 3.0, 1.2, 1.2, 1.2, 1.2])
        h1.write("**공모일**"); h2.write("**기업명**"); h3.write("**공모가**"); h4.write("**규모**"); h5.write("**현재가**"); h6.write("**거래소**")
        
        for i, row in display_df.iterrows():
            col1, col2, col3, col4, col5, col6 = st.columns([1.2, 3.0, 1.2, 1.2, 1.2, 1.2])
            
            # 기업명 버튼
            if col2.button(row['name'], key=f"n_{row['symbol']}_{i}", use_container_width=True):
                st.session_state.selected_stock = row.to_dict()
                st.session_state.page = 'detail'
                st.rerun()
            
            # 기타 정보
            col1.write(row['date'])
            col3.write(row.get('price', 'TBD'))
            
            p_n = pd.to_numeric(row.get('price'), errors='coerce') or 0
            s_n = pd.to_numeric(row.get('numberOfShares'), errors='coerce') or 0
            if p_n * s_n > 0: col4.write(f"${(p_n*s_n/1000000):,.1f}M")
            else: col4.write("-")
            
            col5.write("-") # 현재가는 로딩 속도를 위해 상세 페이지에서 주로 확인
            
            exch = row.get('exchange', 'TBD')
            display_exch = "NASDAQ" if "NASDAQ" in exch.upper() else ("NYSE" if "NYSE" in exch.upper() else exch)
            col6.write(f"🏛️ {display_exch}")

# 3. 상세 분석 페이지
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        st.title(f"🚀 {stock['name']} ({stock['symbol']}) 심층 분석")
        
        tab0, tab1, tab2, tab3 = st.tabs(["📰 실시간 뉴스", "📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 최종 투자 결정"])
        
        with tab0:
            st.subheader("📰 투자 인사이트 브리핑")
            # 2x2 뉴스 버튼 레이아웃
            r1c1, r1c2 = st.columns(2)
            r2c1, r2c2 = st.columns(2)
            if r1c1.button("💰 공모가 범위/확정 소식", use_container_width=True): st.session_state.news_topic = "💰 공모가 범위/확정 소식"
            if r1c2.button("📅 상장 일정/연기 소식", use_container_width=True): st.session_state.news_topic = "📅 상장 일정/연기 소식"
            if r2c1.button("🥊 경쟁사 비교/분석", use_container_width=True): st.session_state.news_topic = "🥊 경쟁사 비교/분석"
            if r2c2.button("🏦 주요 주간사 (Underwriters)", use_container_width=True): st.session_state.news_topic = "🏦 주요 주간사"

            st.markdown(f"<div style='background-color: #f0f4ff; padding: 15px; border-radius: 10px; border-left: 5px solid #6e8efb;'><b>🤖 AI 실시간 요약:</b> {st.session_state.news_topic}에 대한 최신 리포트를 분석 중입니다...</div>", unsafe_allow_html=True)
            
            st.write("---")
            st.markdown(f"##### 🔥 {stock['name']} 관련 실시간 인기 뉴스")
            # 뉴스 Top 5 리스트 (사용자님 코드 복구)
            news_topics = [{"title": f"{stock['name']} IPO: 주요 투자 위험 요소", "tag": "분석"}, {"title": "나스닥 상장 앞둔 시장의 평가", "tag": "시장"}]
            for news in news_topics:
                st.markdown(f"<div style='padding: 10px; border-bottom: 1px solid #eee;'><b>[{news['tag']}]</b> {news['title']}</div>", unsafe_allow_html=True)

        with tab1:
            st.subheader("📋 핵심 기업 정보")
            cc1, cc2 = st.columns(2)
            with cc1:
                st.markdown("#### 📑 주요 기업 공시 (SEC)")
                if st.button("🔍 S-1 투자 설명서 한글 요약", use_container_width=True, type="primary"):
                    st.session_state.show_summary = not st.session_state.show_summary
                
                if st.session_state.show_summary:
                    st.success("📝 [한글 요약] 본 기업은 혁신적인 기술력을 바탕으로 시장 점유율을 확대하고 있으며, 공모 자금은 글로벌 확장 및 R&D에 사용될 계획입니다.")
                
                st.markdown(f"""
                    <a href="https://www.sec.gov/edgar/search/#/q={stock['name'].replace(' ','+')}" target="_blank">
                        <button style='width:100%; padding:10px; background-color:#34495e; color:white; border:none; border-radius:5px;'>Edgar 공시 시스템 바로가기 ↗</button>
                    </a>
                """, unsafe_allow_html=True)
            
            with cc2:
                st.markdown("#### 📊 연도별 핵심 재무 추이")
                # Plotly 그래프 (사용자님 요청 버전)
                years = ['2023', '2024', '2025(E)']
                fig = go.Figure()
                fig.add_trace(go.Bar(x=years, y=[120, 185, 260], name='매출액($M)', marker_color='#6e8efb'))
                fig.add_trace(go.Scatter(x=years, y=[-15, -4, 25], name='영업이익($M)', line=dict(color='#ff6b6b', width=4)))
                fig.update_layout(height=300, margin=dict(l=0,r=0,t=30,b=0), legend=dict(orientation="h", y=1.1))
                st.plotly_chart(fig, use_container_width=True)
                st.warning("⚠️ 데이터가 불충분해 추정된 시뮬레이션 그래프입니다.")

        with tab2:
            st.subheader("⚖️ AI 가치 평가")
            st.metric("AI 추정 적정가 범위", f"$24.50 ~ $31.20")
            st.progress(70)
            st.write("시장 평균 대비 **약 15% 저평가** 상태로 분석됩니다.")

        with tab3:
            st.subheader("🎯 최종 투자 결정")
            sid = stock['symbol']
            if sid not in st.session_state.vote_data: st.session_state.vote_data[sid] = {'u': 10, 'f': 3}
            
            v1, v2 = st.columns(2)
            if v1.button("🦄 Unicorn (매수 추천)", use_container_width=True): st.session_state.vote_data[sid]['u'] += 1
            if v2.button("💸 Fallen Angel (관망)", use_container_width=True): st.session_state.vote_data[sid]['f'] += 1
            
            uv, fv = st.session_state.vote_data[sid]['u'], st.session_state.vote_data[sid]['f']
            st.write(f"현재 투표 현황: 유니콘 {uv}표 | 낙오 {fv}표")
            
            if st.button("⭐ 마이 리서치 보관함에 담기", use_container_width=True):
                if sid not in st.session_state.watchlist: st.session_state.watchlist.append(sid)
                st.success("보관함에 저장되었습니다!")
