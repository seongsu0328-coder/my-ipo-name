import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 세션 초기화 (접속 유지 및 필터용) ---
if 'page' not in st.session_state: st.session_state.page = 'intro'
if 'auth_status' not in st.session_state: st.session_state.auth_status = None
if 'vote_data' not in st.session_state: st.session_state.vote_data = {}
if 'comment_data' not in st.session_state: st.session_state.comment_data = {}
if 'selected_stock' not in st.session_state: st.session_state.selected_stock = None

# --- CSS 스타일 ---
st.markdown("""
    <style>
    /* 생략된 스타일은 이전과 동일 */
    .filter-container {
        background-color: #f0f2f6; padding: 15px; border-radius: 15px;
        margin-bottom: 25px; border: 1px solid #dfe3e6;
    }
    .upcoming-header {
        color: #4f46e5; border-left: 5px solid #4f46e5; padding-left: 15px; margin-bottom: 20px;
    }
    .sector-tag { background-color: #eef2ff; color: #4f46e5; padding: 2px 8px; border-radius: 5px; font-size: 12px; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 로직 ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

@st.cache_data(ttl=600)
def get_extended_ipo_data(api_key):
    # 최대 18개월치 데이터를 한 번에 가져와서 캐싱
    start_date = (datetime.now() - timedelta(days=18*30)).strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=60)).strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/calendar/ipo?from={start_date}&to={end_date}&token={api_key}"
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

# ==========================================
# 🚀 화면 제어 로직
# ==========================================

# 1. 인트로 & 2. 로그인 (이전 코드와 동일하므로 생략 - 로직은 유지됨)
if st.session_state.page == 'intro':
    # ... (인트로 코드 생략)
    st.session_state.page = 'stats' # 흐름상 예시

elif st.session_state.page == 'stats':
    # ... (시장 분석 코드 생략)
    if st.button("탐험하기"): st.session_state.page = 'calendar'; st.rerun()

# 4. 캘린더 페이지 (필터링 적용 버전)
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    st.header("🚀 IPO 리서치 센터")
    
    all_df = get_extended_ipo_data(MY_API_KEY)
    
    if not all_df.empty:
        today = datetime.now().date()
        
        # --- [1] 상단 기간 선택 필터 ---
        st.markdown("<div class='filter-container'>", unsafe_allow_html=True)
        col_f1, col_f2 = st.columns([1, 3])
        with col_f1:
            st.write("🗓️ **조회 기간 설정**")
        with col_f2:
            period = st.radio(
                "기간 선택",
                ["60일 내 상장예정", "최근 6개월", "최근 12개월", "전체 (18개월)"],
                horizontal=True, label_visibility="collapsed"
            )
        st.markdown("</div>", unsafe_allow_html=True)
        
        # --- [2] 데이터 필터링 로직 ---
        if period == "60일 내 상장예정":
            # 오늘 이후 상장 예정인 기업들
            display_df = all_df[all_df['공모일_dt'].dt.date >= today].sort_values(by='공모일_dt')
            st.markdown("<h3 class='upcoming-header'>🔔 상장 예정 기업 (Upcoming)</h3>", unsafe_allow_html=True)
        else:
            # 과거 데이터 필터링
            months = 6 if "6개월" in period else (12 if "12개월" in period else 18)
            cutoff = today - timedelta(days=months * 30)
            display_df = all_df[(all_df['공모일_dt'].dt.date < today) & 
                                (all_df['공모일_dt'].dt.date >= cutoff)].sort_values(by='공모일_dt', ascending=False)
            st.subheader(f"📊 과거 {months}개월 히스토리")

        # --- [3] 리스트 렌더링 ---
        if display_df.empty:
            st.info("해당 기간에 조회된 기업이 없습니다.")
        else:
            st.write("---")
            h1, h2, h3, h4, h5 = st.columns([1.2, 3.5, 1.2, 1.5, 1.2])
            h1.write("**공모일**"); h2.write("**기업명**"); h3.write("**공모가**"); h4.write("**공모규모**"); h5.write("**현재가**")
            st.write("---")
            
            for i, row in display_df.iterrows():
                col1, col2, col3, col4, col5 = st.columns([1.2, 3.5, 1.2, 1.5, 1.2])
                is_past = row['공모일_dt'].date() <= today
                
                col1.markdown(f"<span style='color:{'#888' if is_past else '#4f46e5'};'>{row['date']}</span>", unsafe_allow_html=True)
                
                if col2.button(row['name'], key=f"n_{row['symbol']}_{i}", use_container_width=True):
                    st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()
                
                p = pd.to_numeric(row['price'], errors='coerce') or 0
                s = pd.to_numeric(row['numberOfShares'], errors='coerce') or 0
                col3.write(f"${p:,.2f}" if p > 0 else "미정")
                col4.write(f"${(p*s):,.0f}" if p*s > 0 else "대기")
                
                if is_past:
                    cp = get_current_stock_price(row['symbol'], MY_API_KEY)
                    col5.markdown(f"<span style='color:{'#28a745' if cp >= p else '#dc3545'}; font-weight:bold;'>${cp:,.2f}</span>" if cp > 0 else "-", unsafe_allow_html=True)
                else:
                    col5.write("대기")

# 5. 상세 페이지 (이전 코드 유지)
elif st.session_state.page == 'detail':
    # ... (투표, 댓글 기능이 포함된 상세 페이지 로직)
    if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
    st.title(f"🚀 {st.session_state.selected_stock['name']} 상세 리서치")
    # (상세 내용 생략...)
