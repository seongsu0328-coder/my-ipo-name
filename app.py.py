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
    .intro-card {
        background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%);
        padding: 60px 40px; border-radius: 30px; color: white;
        text-align: center; margin-top: 20px;
        box-shadow: 0 20px 40px rgba(110, 142, 251, 0.3);
    }
    .intro-title { font-size: 45px; font-weight: 900; margin-bottom: 15px; letter-spacing: -1px; }
    .intro-subtitle { font-size: 19px; opacity: 0.9; margin-bottom: 40px; }
    .feature-grid { display: flex; justify-content: space-around; gap: 20px; }
    .feature-item {
        background: rgba(255, 255, 255, 0.15);
        padding: 25px 15px; border-radius: 20px; flex: 1;
        backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.2);
    }
    .feature-icon { font-size: 32px; margin-bottom: 12px; }
    .feature-text { font-size: 15px; font-weight: 600; line-height: 1.4; }
    div.stButton > button[key="start_app"] {
        background-color: #ffffff !important; color: #6e8efb !important;
        font-weight: 900 !important; font-size: 22px !important;
        padding: 12px 60px !important; border-radius: 50px !important;
        border: none !important; box-shadow: 0 10px 25px rgba(0,0,0,0.15) !important;
        margin-top: 40px !important;
    }
    .quote-card {
        background: linear-gradient(145deg, #ffffff, #f9faff);
        padding: 30px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.1); 
        margin-top: 20px; text-align: center;
        max-width: 650px; margin-left: auto; margin-right: auto;
    }
    .stats-header { text-align: center; color: #6e8efb; margin-bottom: 20px; }
    .stats-box {
        background-color: #f0f4ff; padding: 15px; border-radius: 10px; text-align: center; border: 1px solid #d1d9ff;
    }
    .stats-label { font-size: 13px; color: #555; font-weight: bold; }
    .stats-value { font-size: 19px; color: #4a69bd; font-weight: 900; }
    div.stButton > button[key^="name_"] {
        background-color: transparent !important; border: none !important; color: #6e8efb !important; font-weight: 900 !important; font-size: 18px !important;
    }
    .sector-tag { background-color: #eef2ff; color: #4f46e5; padding: 2px 8px; border-radius: 5px; font-size: 12px; font-weight: bold; border: 1px solid #c7d2fe; }
    .vote-container { padding: 20px; background-color: #fdfdfd; border-radius: 15px; border: 1px dashed #d1d9ff; margin-top: 30px; }
    </style>
""", unsafe_allow_html=True)

# --- 데이터 및 API 로직 ---
@st.cache_data(ttl=86400)
def get_daily_quote():
    try:
        res = requests.get("https://api.quotable.io/random?tags=business|wisdom", timeout=5)
        if res.status_code == 200:
            data = res.json()
            eng_text, author = data['content'], data['author']
            trans_res = requests.get(f"https://api.mymemory.translated.net/get?q={eng_text}&langpair=en|ko", timeout=5)
            kor_text = trans_res.json()['responseData']['translatedText']
            return {"eng": eng_text, "kor": kor_text, "author": author}
    except:
        return {"eng": "The best way to predict the future is to create it.", "kor": "미래를 예측하는 가장 좋은 방법은 미래를 직접 만드는 것이다.", "author": "Peter Drucker"}

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

# 세션 초기화
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"
for key in ['auth_status', 'page', 'swipe_idx', 'selected_stock', 'vote_data']:
    if key not in st.session_state:
        if key == 'vote_data': st.session_state[key] = {}
        else: st.session_state[key] = None if key in ['auth_status', 'selected_stock'] else ('intro' if key == 'page' else 0)

# --- 화면 0: 인트로 ---
if st.session_state.page == 'intro':
    _, col_center, _ = st.columns([1, 8, 1])
    with col_center:
        st.markdown("<div class='intro-card'><div class='intro-title'>UNICORN FINDER</div><div class='intro-subtitle'>미국 시장의 차세대 주역을 가장 먼저 발견하세요</div><div class='feature-grid'><div class='feature-item'><div class='feature-icon'>📅</div><div class='feature-text'><b>IPO 스케줄</b><br>상장 예정 기업 실시간 트래킹</div></div><div class='feature-item'><div class='feature-icon'>📊</div><div class='feature-text'><b>데이터 리서치</b><br>공시 자료 기반 심층 분석</div></div><div class='feature-item'><div class='feature-icon'>🗳️</div><div class='feature-text'><b>집단 지성</b><br>글로벌 투자자 심리 투표</div></div></div></div>", unsafe_allow_html=True)
        if st.button("탐험 시작하기", key="start_app", use_container_width=True):
            st.session_state.page = 'login'; st.rerun()
    st.stop()

# --- 화면 1: 로그인 ---
if st.session_state.page == 'login' and st.session_state.auth_status is None:
    st.write("<br>" * 3, unsafe_allow_html=True)
    q = get_daily_quote()
    st.markdown(f"<div class='quote-card'><div style='font-size: 12px; color: #6e8efb; font-weight: bold; margin-bottom: 10px; letter-spacing: 1px;'>TODAY'S INSIGHT</div><div style='font-size: 17px; color: #333; font-weight: 600; line-height: 1.5;'>\"{q['eng']}\"</div><div style='font-size: 14px; color: #666; margin-top: 8px;'>({q['kor']})</div><div style='color: #aaa; font-size: 12px; margin-top: 15px;'>- {q['author']} -</div></div>", unsafe_allow_html=True)
    st.write("<br>", unsafe_allow_html=True)
    _, col_m, _ = st.columns([1, 1.5, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000", key="login_phone", label_visibility="collapsed")
        c1, c2 = st.columns(2)
        if c1.button("회원 로그인", use_container_width=True): 
            if len(phone) > 9: st.session_state.auth_status = 'user'; st.session_state.page = 'stats'; st.rerun()
        if c2.button("비회원 시작", use_container_width=True): 
            st.session_state.auth_status = 'guest'; st.session_state.page = 'stats'; st.rerun()
    st.stop()

# --- 화면 2: 시장 분석 ---
if st.session_state.page == 'stats':
    st.title("🦄 Unicornfinder 분석")
    stages = [{"name": "유아기", "img": "baby_unicorn.png", "avg_count": "연평균 180개", "survival_time": "약 1.5년", "survival_rate": "45%"},{"name": "아동기", "img": "child_unicorn.png", "avg_count": "연평균 120개", "survival_time": "약 4년", "survival_rate": "65%"},{"name": "성인기", "img": "adult_unicorn.png", "avg_count": "연평균 85개", "survival_time": "약 12년", "survival_rate": "88%"},{"name": "노년기", "img": "old_unicorn.png", "avg_count": "연평균 40개", "survival_time": "25년 이상", "survival_rate": "95%"}]
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
    st.write("<br>", unsafe_allow_html=True)
    if st.button("🚀 상장 예정 기업 리스트 탐험", key="go_cal_main", use_container_width=True): st.session_state.page = 'calendar'; st.rerun()

# --- 화면 3: 캘린더 ---
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
        st.write("---")
        h1, h2, h3, h4 = st.columns([1.2, 4.0, 1.2, 1.8])
        h1.write("**공모일**"); h2.write("**기업명 & 업종**"); h3.write("**희망가**"); h4.write("**공모규모**")
        st.write("---")
        for i, row in result_df.iterrows():
            col1, col2, col3, col4 = st.columns([1.2, 4.0, 1.2, 1.8])
            col1.write(row['공모일'])
            with col2:
                btn_col, tag_col = st.columns([0.7, 0.3])
                if btn_col.button(row['name'], key=f"name_{row['symbol']}_{i}"):
                    st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()
                tag_col.markdown(f"<span class='sector-tag'>Tech</span>", unsafe_allow_html=True)
            p, s = row['price'], row['numberOfShares']
            col3.write(f"${p:,.2f}" if p > 0 else "미정")
            if p > 0 and s > 0: col4.write(f"${(p*s):,.0f}")
            else: col4.markdown("<span style='color:#ff4b4b;font-weight:bold;'>공시대기</span>", unsafe_allow_html=True)

# --- 화면 4: 상세 리서치 (에러 수정 완료) ---
elif st.session_state.page == 'detail':
    stock = st.session_state.get('selected_stock')
    if stock:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        st.title(f"🚀 {stock['name']} 상세 리서치")
        cl, cr = st.columns([1, 4])
        with cl:
            logo_url = f"https://logo.clearbit.com/{stock['symbol']}.com"
            try: st.image(logo_url, width=150)
            except: st.info("로고 준비 중")
        with cr:
            st.subheader(f"{stock['name']} ({stock['symbol']})")
            st.divider()
            m1, m2, m3, m4 = st.columns(4)
            # ✨ 에러 수정 지점: errors='coerce' 사용
            p = pd.to_numeric(stock.get('price'), errors='coerce')
            s = pd.to_numeric(stock.get('numberOfShares'), errors='coerce')
            p = 0 if pd.isna(p) else p
            s = 0 if pd.isna(s) else s
            
            m1.metric("공모 희망가", f"${p:,.2f}" if p > 0 else "미정")
            m2.metric("예상 규모", f"${(p*s):,.0f}" if p*s > 0 else "미정")
            m3.metric("유통물량", "분석 중")
            m4.metric("보호예수", "180일")
        l1, l2 = st.columns(2)
        l1.link_button("📄 SEC 공식 공시(S-1) 확인", f"https://www.sec.gov/cgi-bin/browse-edgar?company={stock['name'].replace(' ', '+')}", use_container_width=True, type="primary")
        l2.link_button("📈 Yahoo Finance 데이터", f"https://finance.yahoo.com/quote/{stock['symbol']}", use_container_width=True)
        st.markdown("<div class='vote-container'>", unsafe_allow_html=True)
        st.subheader("🗳️ Investor Sentiment")
        s_id = stock['symbol']
        if s_id not in st.session_state.vote_data: st.session_state.vote_data[s_id] = {'unicorn': 10, 'fallen': 10}
        v1, v2 = st.columns(2)
        if v1.button("🦄 Unicorn", use_container_width=True, key=f"v_u_{s_id}"): st.session_state.vote_data[s_id]['unicorn'] += 1; st.rerun()
        if v2.button("💸 Fallen Angel", use_container_width=True, key=f"v_f_{s_id}"): st.session_state.vote_data[s_id]['fallen'] += 1; st.rerun()
        u_v, f_v = st.session_state.vote_data[s_id]['unicorn'], st.session_state.vote_data[s_id]['fallen']
        st.progress(u_v / (u_v + f_v))
        st.write(f"현재 참여: {u_v + f_v}명 (유니콘 지수: {int(u_v/(u_v+f_v)*100)}%)")
        st.markdown("</div>", unsafe_allow_html=True)
