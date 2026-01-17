import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os
import random

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 세션 초기화 ---
for key in ['page', 'auth_status', 'vote_data', 'comment_data', 'selected_stock', 'watchlist']:
    if key not in st.session_state:
        if key == 'page': st.session_state[key] = 'intro'
        elif key == 'watchlist': st.session_state[key] = []
        elif key in ['vote_data', 'comment_data']: st.session_state[key] = {}
        else: st.session_state[key] = None

# --- CSS 스타일 ---
st.markdown("""
    <style>
    .intro-card {
        background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%);
        padding: 60px 40px; border-radius: 30px; color: white;
        text-align: center; margin-top: 20px; box-shadow: 0 20px 40px rgba(110, 142, 251, 0.3);
    }
    .intro-title { font-size: 45px; font-weight: 900; margin-bottom: 15px; letter-spacing: -1px; }
    .intro-subtitle { font-size: 19px; opacity: 0.9; margin-bottom: 40px; }
    .feature-grid { display: flex; justify-content: space-around; gap: 20px; margin-bottom: 30px; }
    .feature-item {
        background: rgba(255, 255, 255, 0.15);
        padding: 25px 15px; border-radius: 20px; flex: 1;
        backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.2);
    }
    .feature-icon { font-size: 30px; margin-bottom: 10px; }
    .feature-text { font-size: 15px; font-weight: 600; }
    .quote-card {
        background: linear-gradient(145deg, #ffffff, #f9faff);
        padding: 25px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.05); text-align: center;
        max-width: 650px; margin: 40px auto; color: #333333 !important;
    }
    .grid-card { background-color: #ffffff; padding: 25px; border-radius: 20px; border: 1px solid #eef2ff; box-shadow: 0 10px 20px rgba(0,0,0,0.05); text-align: center; color: #333; }
    .vote-container { background-color: #f8faff; padding: 25px; border-radius: 20px; border: 1px solid #eef2ff; margin-bottom: 20px; color: #333; }
    .comment-box { background: white; padding: 12px; border-radius: 10px; border-left: 4px solid #6e8efb; margin-bottom: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); color: #333; }
    .info-box { background-color: #f0f4ff; padding: 15px; border-radius: 12px; border-left: 5px solid #6e8efb; margin-bottom: 10px; color: #333; }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 로직 ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

@st.cache_data(ttl=600)
def get_extended_ipo_data(api_key):
    # 18개월 전부터 상장 예정 2개월 후까지 데이터를 가져옴
    start = (datetime.now() - timedelta(days=540)).strftime('%Y-%m-%d')
    end = (datetime.now() + timedelta(days=60)).strftime('%Y-%m-%d')
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

# --- 화면 제어 (인트로/로그인/성장단계 생략 - 이전과 동일) ---
if st.session_state.page == 'intro':
    # (인트로 코드 유지)
    _, col_center, _ = st.columns([1, 8, 1])
    with col_center:
        st.markdown("<div class='intro-card'><div class='intro-title'>UNICORN FINDER</div><div class='intro-subtitle'>미국 시장의 차세대 주역을 가장 먼저 발견하세요</div><div class='feature-grid'><div class='feature-item'><div class='feature-icon'>📅</div><div class='feature-text'>IPO 스케줄</div></div><div class='feature-item'><div class='feature-icon'>📊</div><div class='feature-text'>AI 분석</div></div><div class='feature-item'><div class='feature-icon'>🗳️</div><div class='feature-text'>집단 지성</div></div></div></div>", unsafe_allow_html=True)
        if st.button("탐험 시작하기", use_container_width=True): st.session_state.page = 'login'; st.rerun()

elif st.session_state.page == 'login':
    # (로그인 코드 유지)
    st.session_state.page = 'stats'; st.rerun()

elif st.session_state.page == 'stats':
    # (유아/아동 2단계 유지)
    st.title("🦄 유니콘 성장 단계 분석")
    c1, c2 = st.columns(2)
    if c1.button("🔎 유아기 유니콘 탐험", use_container_width=True): st.session_state.page = 'calendar'; st.rerun()
    if c2.button("🔎 아동기 유니콘 탐험", use_container_width=True): st.session_state.page = 'calendar'; st.rerun()

# 4. 캘린더 (필터 복구 핵심 부분)
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    st.header("🚀 IPO 리서치 센터")
    
    all_df = get_extended_ipo_data(MY_API_KEY)
    
    if not all_df.empty:
        today = datetime.now().date()
        
        # 필터링 옵션 복구: 6개월, 12개월, 18개월
        period = st.radio(
            "데이터 조회 범위 선택", 
            ["상장 예정", "최근 6개월", "최근 12개월", "최근 18개월", "전체"], 
            horizontal=True
        )
        
        # 필터 로직 적용
        if period == "상장 예정":
            display_df = all_df[all_df['공모일_dt'].dt.date >= today].sort_values(by='공모일_dt')
        elif period == "최근 6개월":
            display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=180))].sort_values(by='공모일_dt', ascending=False)
        elif period == "최근 12개월":
            display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=365))].sort_values(by='공모일_dt', ascending=False)
        elif period == "최근 18개월":
            display_df = all_df[(all_df['공모일_dt'].dt.date < today) & (all_df['공모일_dt'].dt.date >= today - timedelta(days=540))].sort_values(by='공모일_dt', ascending=False)
        else:
            display_df = all_df.sort_values(by='공모일_dt', ascending=False)
        
        st.write(f"📊 검색 결과: **{len(display_df)}** 개의 기업이 발견되었습니다.")
        st.write("---")
        
        # 리스트 출력부
        h1, h2, h3, h4, h5 = st.columns([1.2, 3.5, 1.2, 1.5, 1.2])
        h1.write("**공모일**"); h2.write("**기업명**"); h3.write("**공모가**"); h4.write("**규모**"); h5.write("**현재가**")
        
        for i, row in display_df.iterrows():
            col1, col2, col3, col4, col5 = st.columns([1.2, 3.5, 1.2, 1.5, 1.2])
            is_past = row['공모일_dt'].date() <= today
            col1.markdown(f"<span style='color:{'#888' if is_past else '#4f46e5'};'>{row['date']}</span>", unsafe_allow_html=True)
            if col2.button(row['name'], key=f"n_{row['symbol']}_{i}", use_container_width=True):
                st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()
            
            p = pd.to_numeric(row['price'], errors='coerce') or 0
            s = pd.to_numeric(row['numberOfShares'], errors='coerce') or 0
            col3.write(f"${p:,.2f}" if p > 0 else "-")
            col4.write(f"${(p*s/1000000):,.1f}M" if p*s > 0 else "-")
            
            if is_past:
                cp = get_current_stock_price(row['symbol'], MY_API_KEY)
                col5.markdown(f"<span style='color:{'#28a745' if cp >= p else '#dc3545'}; font-weight:bold;'>${cp:,.2f}</span>" if cp > 0 else "-", unsafe_allow_html=True)
            else: col5.write("대기")

# (이후 상세 페이지 로직은 동일하게 유지...)
elif st.session_state.page == 'detail':
    # (이전 수정본의 상세 페이지 코드 유지)
    st.session_state.page = 'calendar'; st.rerun() # 예시용
