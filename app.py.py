import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import os
import random

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# --- CSS 스타일 ---
st.markdown("""
    <style>
    .stats-header { text-align: center; color: #6e8efb; margin-bottom: 20px; }
    .stats-box {
        background-color: #f0f4ff; padding: 15px; border-radius: 10px;
        text-align: center; border: 1px solid #d1d9ff;
    }
    .stats-label { font-size: 13px; color: #555; font-weight: bold; }
    .stats-value { font-size: 19px; color: #4a69bd; font-weight: 900; }
    
    div.stButton > button[key^="name_"] {
        background-color: transparent !important; border: none !important;
        color: #6e8efb !important; font-weight: 900 !important; font-size: 18px !important;
        text-shadow: 1px 1px 0px #eeeeee, 2px 2px 0px #dddddd, 3px 3px 2px rgba(0,0,0,0.15) !important;
    }

    .sector-tag {
        background-color: #eef2ff; color: #4f46e5; padding: 2px 8px;
        border-radius: 5px; font-size: 12px; font-weight: bold; margin-left: 10px;
        vertical-align: middle; border: 1px solid #c7d2fe;
    }

    div.stButton > button[key^="go_cal_"] {
        display: block !important; margin: 20px auto !important;      
        width: 280px !important; height: 85px !important;
        font-size: 28px !important; font-weight: 900 !important;
        color: #ffffff !important;
        background: linear-gradient(145deg, #6e8efb, #a777e3) !important;
        border: none !important; border-radius: 20px !important;
        text-shadow: 2px 2px 0px #4a69bd !important;
        box-shadow: 0px 8px 0px #3c569b, 0px 15px 20px rgba(0,0,0,0.3) !important;
    }
    
    .vote-container {
        padding: 20px; background-color: #fdfdfd; border-radius: 15px;
        border: 1px dashed #d1d9ff; margin-top: 30px;
    }

    /* ✨ 로그인 화면 명언 카드 스타일 */
    .quote-card {
        background: linear-gradient(145deg, #ffffff, #f9faff);
        padding: 25px; border-radius: 15px; border-top: 4px solid #6e8efb;
        box-shadow: 0 10px 30px rgba(0,0,0,0.08); 
        margin-top: 80px; text-align: center;
        max-width: 600px; margin-left: auto; margin-right: auto;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 📚 일일 고정 명언 로직 (확장형)
# ==========================================
@st.cache_data
def get_daily_quote():
    # 명언 리스트 (여기에 1,000개까지 계속 추가할 수 있습니다)
    quotes = [
        {"text": "위대한 일을 해내는 유일한 방법은 당신이 하는 일을 사랑하는 것입니다.", "author": "Steve Jobs"},
        {"text": "투자에서 가장 위험한 것은 아무것도 하지 않는 것이다.", "author": "Warren Buffett"},
        {"text": "미래를 예측하는 가장 좋은 방법은 미래를 창조하는 것이다.", "author": "Peter Drucker"},
        {"text": "기회는 준비된 자에게만 찾아온다.", "author": "Louis Pasteur"},
        {"text": "시장이 비관적일 때 투자하고, 낙관적일 때 매도하라.", "author": "John Templeton"},
        {"text": "위험은 자신이 무엇을 하는지 모르는 데서 온다.", "author": "Warren Buffett"},
        {"text": "혁신은 리더와 추종자를 구분하는 잣대입니다.", "author": "Steve Jobs"},
        {"text": "지식에 투자하는 것이 가장 높은 이자를 지불한다.", "author": "Benjamin Franklin"},
        {"text": "실패는 더 똑똑하게 다시 시작할 수 있는 기회일 뿐이다.", "author": "Henry Ford"},
        {"text": "나무를 심기에 가장 좋은 시기는 20년 전이었다. 두 번째로 좋은 시기는 지금이다.", "author": "Proverb"}
        # ... 리스트를 1,000개까지 확장 가능
    ]
    
    # 🗓️ 날짜를 시드값으로 사용하여 하루 동안은 동일한 결과가 나오도록 설정
    today_seed = int(datetime.now().strftime('%Y%m%d'))
    random.seed(today_seed)
    return random.choice(quotes)

# 세션 상태 초기화
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"
for key in ['auth_status', 'page', 'swipe_idx', 'selected_stock', 'vote_data']:
    if key not in st.session_state:
        if key == 'vote_data': st.session_state[key] = {}
        else: st.session_state[key] = None if key in ['auth_status', 'selected_stock'] else ('stats' if key == 'page' else 0)

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

# ==========================================
# 🚀 화면 1: 로그인 (일일 고정 명언 노출)
# ==========================================
if st.session_state.auth_status is None:
    st.write("<div style='text-align: center; margin-top: 50px;'><h1>🦄 Unicornfinder</h1><h3>당신의 다음 유니콘을 찾아보세요</h3></div>", unsafe_allow_html=True)
    st.divider()
    _, col_m, _ = st.columns([1, 2, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000", key="login_phone")
        c1, c2 = st.columns(2)
        if c1.button("회원 로그인", use_container_width=True): 
            if len(phone) > 9: st.session_state.auth_status = 'user'; st.rerun()
        if c2.button("비회원 시작", use_container_width=True): 
            st.session_state.auth_status = 'guest'; st.rerun()
    
    # 하단 일일 고정 명언 섹션
    st.write("<br>" * 3, unsafe_allow_html=True)
    daily_q = get_daily_quote()
    st.markdown(f"""
        <div class='quote-card'>
            <div style='font-size: 13px; color: #6e8efb; font-weight: bold; margin-bottom: 8px; letter-spacing: 1px;'>TODAY'S MOTIVATION</div>
            <div style='font-style: italic; font-size: 18px; color: #444;'>“{daily_q['text']}”</div>
            <div style='color: #888; margin-top: 10px; font-weight: 500;'>- {daily_q['author']} -</div>
        </div>
    """, unsafe_allow_html=True)
    st.stop()

# ==========================================
# 🚀 화면 2: 시장 분석
# ==========================================
if st.session_state.page == 'stats':
    st.title("🦄 Unicornfinder 분석")
    stages = [
        {"name": "유아기", "img": "baby_unicorn.png", "avg_count": "연평균 180개", "survival_time": "약 1.5년", "survival_rate": "45%"},
        {"name": "아동기", "img": "child_unicorn.png", "avg_count": "연평균 120개", "survival_time": "약 4년", "survival_rate": "65%"},
        {"name": "성인기", "img": "adult_unicorn.png", "avg_count": "연평균 85개", "survival_time": "약 12년", "survival_rate": "88%"},
        {"name": "노년기", "img": "old_unicorn.png", "avg_count": "연평균 40개", "survival_time": "25년 이상", "survival_rate": "95%"}
    ]
    idx = st.session_state.swipe_idx
    stage = stages[idx]
    
    st.markdown(f"<h2 class='stats-header'>{stage['name']} 유니콘</h2>", unsafe_allow_html=True)
    _, b1, ci, b2, _ = st.columns([1, 0.5, 2, 0.5, 1])
    with b1: st.write("<br><br><br>", unsafe_allow_html=True); n1 = st.button("◀", key="p_btn")
    with ci:
        if os.path.exists(stage['img']): st.image(Image.open(stage['img']), use_container_width=True)
        else: st.info(f"[{stage['name']} 이미지]")
    with b2: st.write("<br><br><br>", unsafe_allow_html=True); n2 = st.button("▶", key="n_btn")
    
    if n1: st.session_state.swipe_idx = (idx-1)%4; st.rerun()
    if n2: st.session_state.swipe_idx = (idx+1)%4; st.rerun()

    c1, c2, c3 = st.columns(3)
    with c1: st.markdown(f"<div class='stats-box'><div class='stats-label'>평균 IPO 개수</div><div class='stats-value'>{stage['avg_count']}</div></div>", unsafe_allow_html=True)
    with c2: st.markdown(f"<div class='stats-box'><div class='stats-label'>평균 생존 기간</div><div class='stats-value'>{stage['survival_time']}</div></div>", unsafe_allow_html=True)
    with c3: st.markdown(f"<div class='stats-box'><div class='stats-label'>기업 생존율</div><div class='stats-value'>{stage['survival_rate']}</div></div>", unsafe_allow_html=True)
    
    if st.button("상장 캘린더 탐험", key="go_cal_baby"): st.session_state.page = 'calendar'; st.rerun()

# ==========================================
# 🚀 화면 3: 캘린더
# ==========================================
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    days_ahead = st.sidebar.slider("조회 기간 설정", 1, 60, 60)
    st.header(f"🚀 향후 {days_ahead}일 상장 예정 기업")
    df = get_ipo_data(MY_API_KEY, days_ahead)

    if not df.empty:
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df['numberOfShares'] = pd.to_numeric(df['numberOfShares'], errors='coerce')
        df['공모일'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        result_df = df.sort_values(by='공모일').reset_index(drop=True)

        for i, row in result_df.iterrows():
            col1, col2, col3, col4 = st.columns([1.2, 4.0, 1.2, 1.8])
            col1.write(row['공모일'])
            with col2:
                if st.button(row['name'], key=f"name_{row['symbol']}_{i}"):
                    st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()
            p, s = row['price'], row['numberOfShares']
            col3.write(f"${p:,.2f}" if p > 0 else "미정")
            col4.write(f"${(p*s):,.0f}" if p > 0 and s > 0 else "공시대기")

# ==========================================
# 🚀 화면 4: 상세 분석 & 투표
# ==========================================
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
    st.title(f"🚀 {stock['name']} 상세 리서치")
    cl, cr = st.columns([1, 4])
    with cl:
        logo_url = f"https://logo.clearbit.com/{stock['symbol']}.com"
        try: st.image(logo_url, width=150)
        except: st.info("로고 준비 중")
    with cr:
        st.subheader(f"{stock['name']} ({stock['symbol']})")
        m1, m2, m3, m4 = st.columns(4)
        p = pd.to_numeric(stock.get('price'), errors='coerce') or 0
        s = pd.to_numeric(stock.get('numberOfShares'), errors='coerce') or 0
        m1.metric("공모 희망가", f"${p:,.2f}" if p > 0 else "미정")
        m2.metric("예상 규모", f"${(p*s):,.0f}" if p*s > 0 else "미정")
        m3.metric("유통물량", "분석 중")
        m4.metric("보호예수", "180일")

    st.markdown("<div class='vote-container'>", unsafe_allow_html=True)
    st.subheader("🗳️ Investor Sentiment")
    s_id = stock['symbol']
    if s_id not in st.session_state.vote_data: st.session_state.vote_data[s_id] = {'unicorn': 10, 'fallen': 10}
    v1, v2 = st.columns(2)
    if v1.button("🦄 Unicorn", use_container_width=True, key=f"v_u_{s_id}"): st.session_state.vote_data[s_id]['unicorn'] += 1; st.rerun()
    if v2.button("💸 Fallen Angel", use_container_width=True, key=f"v_f_{s_id}"): st.session_state.vote_data[s_id]['fallen'] += 1; st.rerun()
    
    u_v = st.session_state.vote_data[s_id]['unicorn']
    f_v = st.session_state.vote_data[s_id]['fallen']
    st.progress(u_v / (u_v + f_v))
    st.write(f"현재 참여: {u_v + f_v}명")
    st.markdown("</div>", unsafe_allow_html=True)
