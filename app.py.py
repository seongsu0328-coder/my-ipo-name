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
        padding: 25px; background-color: #fdfdfd; border-radius: 15px;
        border: 1px dashed #6e8efb; margin-top: 30px;
    }
    .my-choice { color: #4f46e5; font-size: 12px; font-weight: bold; margin-bottom: 5px; }
    </style>
""", unsafe_allow_html=True)

# 세션 상태 초기화
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"
for key in ['auth_status', 'page', 'swipe_idx', 'selected_stock', 'vote_data', 'user_votes']:
    if key not in st.session_state:
        if key == 'vote_data': st.session_state[key] = {} # 전역 투표 데이터
        elif key == 'user_votes': st.session_state[key] = {} # {symbol: 'unicorn' or 'fallen'}
        else: st.session_state[key] = None if key in ['auth_status', 'selected_stock'] else ('stats' if key == 'page' else 0)

# 데이터 호출 함수 (생략 없이 유지)
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

# --- 화면 1, 2, 3 로직은 이전과 동일하게 유지 ---
if st.session_state.auth_status is None:
    # (로그인 화면 생략 - 기존 코드와 동일)
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
    st.stop()

if st.session_state.page == 'stats':
    # (시장 분석 화면 생략 - 기존 코드와 동일)
    st.title("🦄 Unicornfinder 분석")
    stages = [
        {"name": "유아기", "img": "baby_unicorn.png", "avg_count": "연평균 180개", "survival_time": "약 1.5년", "survival_rate": "45%", "desc": "상장 0~2년차의 폭발적 성장기 기업"},
        {"name": "아동기", "img": "child_unicorn.png", "avg_count": "연평균 120개", "survival_time": "약 4년", "survival_rate": "65%", "desc": "상장 3~5년차의 시장 안착기 기업"},
        {"name": "성인기", "img": "adult_unicorn.png", "avg_count": "연평균 85개", "survival_time": "약 12년", "survival_rate": "88%", "desc": "안정적인 수익 구조를 갖춘 중견 기업"},
        {"name": "노년기", "img": "old_unicorn.png", "avg_count": "연평균 40개", "survival_time": "25년 이상", "survival_rate": "95%", "desc": "S&P 500에 근접한 전통 대기업"}
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
    if stage['name'] == "유아기":
        if st.button("상장 캘린더 탐험", key="go_cal_baby"): st.session_state.page = 'calendar'; st.rerun()
    elif stage['name'] == "아동기":
        if st.button("성장 지표 탐험", key="go_cal_child"): st.session_state.page = 'growth_stats'; st.rerun()

elif st.session_state.page == 'calendar':
    # (캘린더 화면 생략 - 기존 코드와 동일)
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    days_ahead = st.sidebar.slider("조회 기간 설정", 1, 60, 60)
    st.header(f"🚀 향후 {days_ahead}일 상장 예정 기업")
    df = get_ipo_data(MY_API_KEY, days_ahead)
    if not df.empty:
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
                    st.session_state.selected_stock = row.to_dict()
                    st.session_state.page = 'detail'; st.rerun()
                tag_col.markdown(f"<span class='sector-tag'>Tech & Services</span>", unsafe_allow_html=True)
            p, s = pd.to_numeric(row['price'], errors='coerce') or 0, pd.to_numeric(row['numberOfShares'], errors='coerce') or 0
            col3.write(f"${p:,.2f}" if p > 0 else "미정")
            col4.write(f"${(p*s):,.0f}" if p*s > 0 else "미정")

# ==========================================
# 🚀 화면 4: 상세 분석 (수정 가능한 투표 시스템)
# ==========================================
elif st.session_state.page == 'detail':
    stock = st.session_state.get('selected_stock')
    if stock is None:
        st.error("기업 정보를 불러오지 못했습니다.")
        if st.button("목록으로 돌아가기"): st.session_state.page = 'calendar'; st.rerun()
    else:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()

        st.title(f"🚀 {stock['name']} 상세 리서치")
        # 기업 기본 정보 로직 (로고, 메트릭 등 생략 없이 포함)
        cl, cr = st.columns([1, 4])
        with cl:
            logo_url = f"https://logo.clearbit.com/{stock['symbol']}.com"
            try: st.image(logo_url, width=150)
            except: st.info("로고 준비 중")
        with cr:
            st.subheader(f"{stock['name']} ({stock['symbol']})")
            st.markdown(f"**업종:** <span class='sector-tag'>Technology & Software</span>", unsafe_allow_html=True)
            st.divider()
            m1, m2, m3, m4 = st.columns(4)
            p = pd.to_numeric(stock.get('price'), errors='coerce') or 0
            s = pd.to_numeric(stock.get('numberOfShares'), errors='coerce') or 0
            m1.metric("공모 희망가", f"${p:,.2f}" if p > 0 else "미정")
            m2.metric("예상 공모 규모", f"${(p*s):,.0f}" if p*s > 0 else "미정")
            m3.metric("유통 가능 물량", "분석 중", "S-1 참조")
            m4.metric("보호예수 기간", "180일", "표준")

        # 🗳️ Investor Expectation (수정 가능 로직)
        st.markdown("<div class='vote-container'>", unsafe_allow_html=True)
        st.subheader("🗳️ Investor Expectation: Unicorn vs Fallen Angel")
        
        s_id = stock['symbol']
        # 유저의 기존 선택 확인
        current_choice = st.session_state.user_votes.get(s_id)
        
        if s_id not in st.session_state.vote_data:
            st.session_state.vote_data[s_id] = {'unicorn': 12, 'fallen': 8}

        v_col1, v_col2 = st.columns(2)
        
        # 🦄 Unicorn 투표 버튼
        with v_col1:
            if current_choice == 'unicorn': st.markdown("<p class='my-choice'>✅ 당신의 선택</p>", unsafe_allow_html=True)
            if st.button("🦄 Unicorn (성장 기대)", use_container_width=True, key=f"v_u_{s_id}"):
                if current_choice == 'fallen': # 마음이 바뀐 경우
                    st.session_state.vote_data[s_id]['fallen'] -= 1
                    st.session_state.vote_data[s_id]['unicorn'] += 1
                elif current_choice is None: # 처음 투표하는 경우
                    st.session_state.vote_data[s_id]['unicorn'] += 1
                
                if current_choice != 'unicorn':
                    st.session_state.user_votes[s_id] = 'unicorn'
                    st.toast("의견이 유니콘으로 업데이트되었습니다!", icon="🦄")
                    st.rerun()

        # 💸 Fallen Angel 투표 버튼
        with v_col2:
            if current_choice == 'fallen': st.markdown("<p class='my-choice'>✅ 당신의 선택</p>", unsafe_allow_html=True)
            if st.button("💸 Fallen Angel (하락 우려)", use_container_width=True, key=f"v_f_{s_id}"):
                if current_choice == 'unicorn': # 마음이 바뀐 경우
                    st.session_state.vote_data[s_id]['unicorn'] -= 1
                    st.session_state.vote_data[s_id]['fallen'] += 1
                elif current_choice is None: # 처음 투표하는 경우
                    st.session_state.vote_data[s_id]['fallen'] += 1
                
                if current_choice != 'fallen':
                    st.session_state.user_votes[s_id] = 'fallen'
                    st.toast("의견이 하락 우려로 업데이트되었습니다.", icon="💸")
                    st.rerun()

        # 실시간 결과 시각화
        u_v = st.session_state.vote_data[s_id]['unicorn']
        f_v = st.session_state.vote_data[s_id]['fallen']
        total_v = u_v + f_v
        u_ratio = u_v / total_v if total_v > 0 else 0.5

        st.write(f"**현재 참여 현황: {total_v}명**")
        st.progress(u_ratio) 
        
        r1, r2 = st.columns(2)
        r1.markdown(f"**🦄 Unicorn Expectation:** {int(u_ratio*100)}% ({u_v}표)")
        r2.markdown(f"**💸 Fallen Angel Risk:** {int((1-u_ratio)*100)}% ({f_v}표)")
        st.markdown("</div>", unsafe_allow_html=True)
