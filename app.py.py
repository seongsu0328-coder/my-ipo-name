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
    /* 인트로 및 카드 디자인 생략 (이전과 동일) */
    .vote-container {
        background-color: #f8faff; padding: 30px; border-radius: 20px;
        border: 1px solid #eef2ff; margin-top: 30px;
    }
    .comment-box {
        background: white; padding: 15px; border-radius: 12px;
        border-left: 5px solid #6e8efb; margin-bottom: 10px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    .sector-tag { background-color: #eef2ff; color: #4f46e5; padding: 2px 8px; border-radius: 5px; font-size: 12px; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 및 API 로직 ---
@st.cache_data(ttl=600)
def get_extended_ipo_data(api_key):
    start_date = (datetime.now() - timedelta(days=18*30)).strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=60)).strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/calendar/ipo?from={start_date}&to={end_date}&token={api_key}"
    try:
        res = requests.get(url).json()
        return pd.DataFrame(res.get('ipoCalendar', []))
    except: return pd.DataFrame()

def get_current_stock_price(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
        return requests.get(url).json().get('c', 0)
    except: return 0

# 세션 초기화 (투표 및 댓글 데이터 구조 추가)
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"
if 'vote_data' not in st.session_state: st.session_state.vote_data = {}
if 'comment_data' not in st.session_state: st.session_state.comment_data = {}
if 'page' not in st.session_state: st.session_state.page = 'intro'
if 'auth_status' not in st.session_state: st.session_state.auth_status = None

# ==========================================
# 🚀 화면 제어 로직
# ==========================================

# (1~4번 화면: 인트로, 로그인, 시장분석, 캘린더 로직은 이전과 동일하므로 상세페이지 위주로 서술)
if st.session_state.page == 'intro':
    # 인트로 생략...
    st.session_state.page = 'stats' # 테스트용 이동

elif st.session_state.page == 'detail':
    stock = st.session_state.get('selected_stock')
    if stock:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        
        st.title(f"🚀 {stock['name']} 상세 리서치")
        
        # 상단 기업 정보 섹션
        cl, cr = st.columns([1, 4])
        with cl:
            st.image(f"https://logo.clearbit.com/{stock['symbol']}.com", width=150)
        with cr:
            st.subheader(f"{stock['name']} ({stock['symbol']})")
            st.markdown(f"**업종:** <span class='sector-tag'>Technology & Infrastructure</span>", unsafe_allow_html=True)
            st.divider()
            m1, m2, m3, m4 = st.columns(4)
            p = pd.to_numeric(stock.get('price'), errors='coerce') or 0
            m1.metric("공모가", f"${p:,.2f}")
            m2.metric("예상 규모", "분석 중")
            m3.metric("현재가", f"${get_current_stock_price(stock['symbol'], MY_API_KEY):,.2f}")
            m4.metric("보호예수", "180일")

        # --- [추가] 투표 및 의견 남기기 섹션 ---
        st.write("---")
        st.subheader("🗳️ Investor Sentiment & Community")
        
        s_id = stock['symbol']
        # 데이터 초기화
        if s_id not in st.session_state.vote_data: st.session_state.vote_data[s_id] = {'unicorn': 15, 'fallen': 5}
        if s_id not in st.session_state.comment_data: st.session_state.comment_data[s_id] = []

        v_col, c_col = st.columns([1, 1.2])

        with v_col:
            st.markdown("<div class='vote-container'>", unsafe_allow_html=True)
            st.write("**이 기업은 차세대 유니콘이 될까요?**")
            v1, v2 = st.columns(2)
            if v1.button("🦄 유니콘이다", use_container_width=True, key=f"u_{s_id}"):
                st.session_state.vote_data[s_id]['unicorn'] += 1; st.rerun()
            if v2.button("💸 거품이다", use_container_width=True, key=f"f_{s_id}"):
                st.session_state.vote_data[s_id]['fallen'] += 1; st.rerun()
            
            # 투표 결과 표시
            u_v, f_v = st.session_state.vote_data[s_id]['unicorn'], st.session_state.vote_data[s_id]['fallen']
            total = u_v + f_v
            u_percent = int(u_v / total * 100)
            st.write(f"현재 참여: {total}명")
            st.progress(u_v / total)
            st.write(f"유니콘 지수: **{u_percent}%**")
            st.markdown("</div>", unsafe_allow_html=True)

        with c_col:
            st.write("**📝 투자 의견 공유**")
            new_comment = st.text_input("의견을 남겨주세요", placeholder="예: 비즈니스 모델이 탄탄해 보이네요!", key=f"input_{s_id}")
            if st.button("의견 올리기", use_container_width=True):
                if new_comment:
                    timestamp = datetime.now().strftime("%H:%M")
                    st.session_state.comment_data[s_id].insert(0, {"text": new_comment, "time": timestamp})
                    st.rerun()
            
            # 의견 리스트 표시
            st.write("---")
            if not st.session_state.comment_data[s_id]:
                st.caption("첫 번째 의견을 남겨보세요!")
            for comment in st.session_state.comment_data[s_id][:5]: # 최근 5개만
                st.markdown(f"""
                    <div class='comment-box'>
                        <small style='color:#888;'>{comment['time']}</small><br>
                        {comment['text']}
                    </div>
                """, unsafe_allow_html=True)

        # 링크 버튼
        st.write("---")
        l1, l2 = st.columns(2)
        l1.link_button("📄 SEC 공시 자료", f"https://www.sec.gov/cgi-bin/browse-edgar?company={stock['name'].replace(' ', '+')}", use_container_width=True)
        l2.link_button("📈 Yahoo Finance", f"https://finance.yahoo.com/quote/{stock['symbol']}", use_container_width=True)

# (필요 시 나머지 페이지 로직 추가 가능)
