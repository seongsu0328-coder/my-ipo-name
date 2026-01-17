import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- 세션 초기화 ---
for key in ['page', 'auth_status', 'vote_data', 'comment_data', 'selected_stock']:
    if key not in st.session_state:
        st.session_state[key] = 'intro' if key == 'page' else ({} if 'data' in key else None)

# --- CSS 스타일 (모바일 가독성 강화) ---
st.markdown("""
    <style>
    /* 인트로 카드 */
    .intro-card {
        background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%);
        padding: 40px 20px; border-radius: 30px; color: white;
        text-align: center; margin-top: 10px;
        box-shadow: 0 20px 40px rgba(110,142,251,0.3);
    }
    
    /* 명언 카드 (글자색 검정 고정) */
    .quote-card {
        background: #ffffff;
        padding: 25px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.05); text-align: center;
        max-width: 600px; margin: 30px auto;
        color: #333333 !important; /* 글자색 강제 고정 */
    }
    .quote-text { color: #333333 !important; font-size: 16px; font-weight: 600; }
    .quote-sub { color: #666666 !important; font-size: 13px; }

    /* 상세페이지 5대 지표 (글자색 검정 고정) */
    .info-box { 
        background-color: #f0f4ff; 
        padding: 15px; border-radius: 12px; 
        border-left: 5px solid #6e8efb; 
        margin-bottom: 10px;
        color: #1a1a1a !important; /* 진한 검정색으로 고정 */
        font-weight: 500;
    }
    .info-box b { color: #4f46e5 !important; } /* 강조 텍스트 색상 */

    /* 버튼 스타일 */
    div.stButton > button[key="start_app"] {
        background-color: #ffffff !important; color: #6e8efb !important;
        font-weight: 900 !important; font-size: 20px !important;
        padding: 10px 40px !important; border-radius: 50px !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 로직 ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

@st.cache_data(ttl=86400)
def get_daily_quote():
    try:
        res = requests.get("https://api.quotable.io/random?tags=business", timeout=3).json()
        trans = requests.get(f"https://api.mymemory.translated.net/get?q={res['content']}&langpair=en|ko", timeout=3).json()
        return {"eng": res['content'], "kor": trans['responseData']['translatedText'], "author": res['author']}
    except: return {"eng": "Believe you can and you're halfway there.", "kor": "할 수 있다고 믿으면 이미 절반은 온 것이다.", "author": "Theodore Roosevelt"}

# ... (기존 get_extended_ipo_data 및 get_current_stock_price 로직 동일)

# 2. 로그인 페이지 (명언 가독성 개선)
if st.session_state.page == 'login' and st.session_state.auth_status is None:
    st.write("<br>" * 4, unsafe_allow_html=True)
    _, col_m, _ = st.columns([1, 2, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000", label_visibility="collapsed")
        c1, c2 = st.columns(2)
        if c1.button("회원 로그인", use_container_width=True):
            st.session_state.auth_status = 'user'; st.session_state.page = 'stats'; st.rerun()
        if c2.button("비회원 시작", use_container_width=True):
            st.session_state.auth_status = 'guest'; st.session_state.page = 'stats'; st.rerun()
    
    q = get_daily_quote()
    st.markdown(f"""
        <div class='quote-card'>
            <div style='font-size: 11px; color: #6e8efb; font-weight: bold; margin-bottom: 8px;'>TODAY'S INSIGHT</div>
            <div class='quote-text'>"{q['eng']}"</div>
            <div class='quote-sub'>({q['kor']})</div>
            <div style='color: #888888; font-size: 11px; margin-top: 12px;'>- {q['author']} -</div>
        </div>
    """, unsafe_allow_html=True)

# 5. 상세 리서치 (5대 지표 가독성 개선)
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        st.title(f"🚀 {stock['name']} 분석")
        
        tab1, tab2, tab3 = st.tabs(["📋 핵심 정보", "⚖️ AI 가치 평가", "🎯 투자 결정"])

        with tab1:
            st.subheader("🔍 투자자 검색 상위 5대 지표")
            p, s = pd.to_numeric(stock.get('price'), errors='coerce') or 0, pd.to_numeric(stock.get('numberOfShares'), errors='coerce') or 0
            
            # 모바일 최적화: 이미지와 텍스트를 위아래로 배치하거나 적절히 조절
            st.image(f"https://logo.clearbit.com/{stock['symbol']}.com", width=100)
            
            # 글자색이 무조건 보이도록 class='info-box' 적용
            st.markdown(f"<div class='info-box'><b>1. 예상 공모가:</b> ${p:,.2f}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='info-box'><b>2. 공모 규모:</b> ${(p*s/1000000):,.1f}M USD</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='info-box'><b>3. 상장 거래소:</b> {stock.get('exchange', 'NYSE/NASDAQ')}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='info-box'><b>4. 주요 주간사:</b> Goldman Sachs, MS 등</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='info-box'><b>5. 보호예수:</b> 상장 후 180일</div>", unsafe_allow_html=True)

        # ... (tab2, tab3 로직은 이전과 동일하게 유지)
