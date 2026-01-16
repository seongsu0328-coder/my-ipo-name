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
    .stats-label { font-size: 14px; color: #555; font-weight: bold; }
    .stats-value { font-size: 20px; color: #4a69bd; font-weight: 900; }
    
    /* 탐험 버튼 스타일 (유아기/아동기 공용) */
    div.stButton > button[key^="go_cal_"] {
        display: block !important; margin: 20px auto !important;     
        width: 280px !important; height: 80px !important;
        font-size: 28px !important; font-weight: 900 !important;
        color: #ffffff !important;
        background: linear-gradient(145deg, #6e8efb, #a777e3) !important;
        border: none !important; border-radius: 20px !important;
        text-shadow: 2px 2px 0px #4a69bd !important;
        box-shadow: 0px 8px 0px #3c569b, 0px 15px 20px rgba(0,0,0,0.3) !important;
    }
    </style>
""", unsafe_allow_html=True)

# 세션 상태 관리 (신규 페이지 'growth_stats' 추가)
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"
for key in ['auth_status', 'page', 'swipe_idx', 'selected_stock']:
    if key not in st.session_state:
        st.session_state[key] = None if key in ['auth_status', 'selected_stock'] else ('stats' if key == 'page' else 0)

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
# 🚀 화면 1: 로그인
# ==========================================
if st.session_state.auth_status is None:
    st.write("<div style='text-align: center; margin-top: 50px;'><h1>🦄 Unicornfinder</h1></div>", unsafe_allow_html=True)
    _, col_m, _ = st.columns([1, 2, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", key="login_phone")
        if st.button("비회원 시작", use_container_width=True): st.session_state.auth_status = 'guest'; st.rerun()
    st.stop()

# ==========================================
# 🚀 화면 2: 시장 분석 (유아기/아동기 각각 버튼 추가)
# ==========================================
if st.session_state.page == 'stats':
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
    
    st.markdown(f"<p style='text-align: center; margin-top: 15px; color: #666;'>{stage['desc']}</p>", unsafe_allow_html=True)

    # 유아기 버튼 -> 캘린더 페이지로
    if stage['name'] == "유아기":
        if st.button("상장 캘린더 탐험", key="go_cal_baby"): 
            st.session_state.page = 'calendar'; st.rerun()
            
    # [추가] 아동기 버튼 -> 신규 성장 지표 페이지로
    elif stage['name'] == "아동기":
        if st.button("성장 지표 탐험", key="go_cal_child"): 
            st.session_state.page = 'growth_stats'; st.rerun()

# ==========================================
# 🚀 신규 화면: 아동기 성장 지표 분석
# ==========================================
elif st.session_state.page == 'growth_stats':
    st.title("📈 아동기 유니콘 성장 지표")
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    
    st.info("상장 3~5년차 기업들의 주요 재무 성과와 시장 점유율 변화를 분석합니다.")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 📊 평균 매출 성장률")
        st.write("아동기 기업들은 평균적으로 전년 대비 **25% 이상의 매출 성장**을 기록할 때 시장의 신뢰를 얻습니다.")
        st.progress(0.75)
    with col2:
        st.markdown("### 🛡️ 시장 점유율 안정성")
        st.write("이 시기의 유니콘들은 경쟁사 대비 점유율 **15% 이상**을 확보하며 독자적 생태계를 구축합니다.")
        st.success("점유율 확장 중")
    
    st.write("---")
    st.write("💡 **아동기 투자 전략**: IPO 당시의 거품이 빠지고 실제 숫자가 증명되는 시기이므로, '실적 대비 저평가'된 기업을 찾는 것이 핵심입니다.")

# ==========================================
# 🚀 화면 3: 캘린더 (유아기 연결)
# ==========================================
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    days_ahead = st.sidebar.slider("조회 기간 설정", 1, 60, 60)
    df = get_ipo_data(MY_API_KEY, days_ahead)
    if not df.empty:
        df['공모일'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        result_df = df.sort_values(by='공모일').reset_index(drop=True)
        for i, row in result_df.iterrows():
            col1, col2, col3 = st.columns([1, 3, 1])
            col1.write(row['공모일'])
            if col2.button(row['name'], key=f"name_{row['symbol']}_{i}"):
                st.session_state.selected_stock = row
                st.session_state.page = 'detail'; st.rerun()
            col3.write(row['symbol'])
    else: st.info("상장 데이터가 없습니다.")

# ==========================================
# 🚀 화면 4: 상세 리포트
# ==========================================
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
    st.title(f"🚀 {stock['name']} 리포트")
    # ... (상세 정보 코드는 이전과 동일) ...
    clean_name = stock['name'].replace(" ", "+")
    sec_url = f"https://www.sec.gov/cgi-bin/browse-edgar?company={clean_name}&owner=exclude&action=getcompany"
    st.link_button("📄 SEC 공식 공시(S-1) 확인", sec_url, use_container_width=True)
