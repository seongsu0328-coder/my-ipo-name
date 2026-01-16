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
    /* 전체 배경 및 폰트 */
    .stApp { background-color: #ffffff; }
    
    /* [화면 2] 단계 제목 스타일 (상단 이모지/제목 대체) */
    .stage-title { 
        text-align: center; 
        color: #4a69bd; 
        font-size: 42px; 
        font-weight: 900; 
        margin-top: 10px; 
        margin-bottom: 20px;
        letter-spacing: -1.5px;
    }
    
    .stats-box {
        background-color: #f8faff; padding: 20px; border-radius: 12px;
        text-align: center; border: 1px solid #e1e8f0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.02);
    }
    .stats-label { font-size: 14px; color: #777; font-weight: bold; margin-bottom: 5px; }
    .stats-value { font-size: 22px; color: #2e4172; font-weight: 900; }
    
    /* 기업명 3D 버튼 스타일 */
    div.stButton > button[key^="name_"] {
        background-color: transparent !important; border: none !important;
        color: #6e8efb !important; font-weight: 900 !important; font-size: 18px !important;
        text-shadow: 1px 1px 0px #eeeeee, 2px 2px 0px #dddddd !important;
    }

    /* 업종 태그 스타일 */
    .sector-tag {
        background-color: #eef2ff; color: #4f46e5; padding: 2px 8px;
        border-radius: 5px; font-size: 12px; font-weight: bold; margin-left: 10px;
        vertical-align: middle; border: 1px solid #c7d2fe;
    }

    /* 하단 탐험 버튼 */
    div.stButton > button[key^="go_cal_"] {
        display: block !important; margin: 30px auto !important;     
        width: 320px !important; height: 80px !important;
        font-size: 24px !important; font-weight: 900 !important;
        color: #ffffff !important;
        background: linear-gradient(135deg, #6e8efb, #a777e3) !important;
        border: none !important; border-radius: 50px !important;
        box-shadow: 0px 10px 20px rgba(110, 142, 251, 0.4) !important;
    }

    .report-card {
        background-color: #f8faff; padding: 20px; border-radius: 15px;
        border: 1px solid #e1e8f0; margin-bottom: 20px; min-height: 160px;
    }
    .status-pending { color: #ff4b4b; font-weight: bold; font-size: 14px; }
    </style>
""", unsafe_allow_html=True)

# --- 세션 상태 초기화 ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

if 'auth_status' not in st.session_state:
    st.session_state.auth_status = None
if 'page' not in st.session_state:
    st.session_state.page = 'stats'
if 'swipe_idx' not in st.session_state:
    st.session_state.swipe_idx = 0
if 'selected_stock' not in st.session_state:
    st.session_state.selected_stock = None

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
# 🚀 화면 1: 로그인 (복구 완료)
# ==========================================
if st.session_state.auth_status is None:
    st.write("<div style='text-align: center; margin-top: 80px;'><h1>🦄 Unicornfinder</h1><p style='font-size: 20px; color: #666;'>당신의 다음 유니콘을 찾아보세요</p></div>", unsafe_allow_html=True)
    st.divider()
    _, col_m, _ = st.columns([1, 1.5, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000", key="login_input")
        c1, c2 = st.columns(2)
        if c1.button("회원 로그인", use_container_width=True):
            if len(phone) > 9: 
                st.session_state.auth_status = 'user'
                st.rerun()
        if c2.button("비회원 시작", use_container_width=True):
            st.session_state.auth_status = 'guest'
            st.rerun()
    st.stop() # 로그인 전까지 아래 코드 실행 방지

# ==========================================
# 🚀 화면 2: 시장 분석 (디자인 최적화 버전)
# ==========================================
if st.session_state.page == 'stats':
    stages = [
        {"name": "유아기 유니콘", "img": "baby_unicorn.png", "avg_count": "연평균 180개", "survival_time": "약 1.5년", "survival_rate": "45%", "desc": "상장 0~2년차: 폭발적인 잠재력과 변동성이 공존하는 시기"},
        {"name": "아동기 유니콘", "img": "child_unicorn.png", "avg_count": "연평균 120개", "survival_time": "약 4년", "survival_rate": "65%", "desc": "상장 3~5년차: 비즈니스 모델이 시장에 안착하는 시기"},
        {"name": "성인기 유니콘", "img": "adult_unicorn.png", "avg_count": "연평균 85개", "survival_time": "약 12년", "survival_rate": "88%", "desc": "상장 6~15년차: 안정적인 이익 구조와 배당을 고민하는 시기"},
        {"name": "노년기 유니콘", "img": "old_unicorn.png", "avg_count": "연평균 40개", "survival_time": "25년 이상", "survival_rate": "95%", "desc": "상장 20년 이상: S&P 500을 이끄는 시장의 거인들"}
    ]
    idx = st.session_state.swipe_idx
    stage = stages[idx]
    
    # 상단 이모지/제목 제거 후 단계 제목만 크게
    st.markdown(f"<div class='stage-title'>{stage['name']}</div>", unsafe_allow_html=True)
    
    _, b1, ci, b2, _ = st.columns([1, 0.4, 2, 0.4, 1])
    with b1: st.write("<br><br><br><br>", unsafe_allow_html=True)
    if b1.button("◀", key="prev_stage"):
        st.session_state.swipe_idx = (idx - 1) % 4
        st.rerun()
    with ci:
        if os.path.exists(stage['img']): st.image(Image.open(stage['img']), use_container_width=True)
        else: st.info(f"[{stage['name']} 캐릭터 이미지]")
    with b2: st.write("<br><br><br><br>", unsafe_allow_html=True)
    if b2.button("▶", key="next_stage"):
        st.session_state.swipe_idx = (idx + 1) % 4
        st.rerun()

    c1, c2, c3 = st.columns(3)
    with c1: st.markdown(f"<div class='stats-box'><div class='stats-label'>평균 상장 개수</div><div class='stats-value'>{stage['avg_count']}</div></div>", unsafe_allow_html=True)
    with c2: st.markdown(f"<div class='stats-box'><div class='stats-label'>평균 생존 기간</div><div class='stats-value'>{stage['survival_time']}</div></div>", unsafe_allow_html=True)
    with c3: st.markdown(f"<div class='stats-box'><div class='stats-label'>기업 생존율</div><div class='stats-value'>{stage['survival_rate']}</div></div>", unsafe_allow_html=True)
    
    st.markdown(f"<p style='text-align: center; margin-top: 25px; font-size: 18px; color: #555;'>{stage['desc']}</p>", unsafe_allow_html=True)

    if "유아기" in stage['name']:
        if st.button("상장 캘린더 탐험하기", key="go_cal_baby"): 
            st.session_state.page = 'calendar'
            st.rerun()
    elif "아동기" in stage['name']:
        if st.button("성장 지표 분석하기", key="go_cal_child"): 
            st.session_state.page = 'growth_stats'
            st.rerun()

# ==========================================
# 🚀 화면 3: 캘린더 (업종 태그 포함)
# ==========================================
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    st.header("🚀 상장 예정 기업")
    df = get_ipo_data(MY_API_KEY, 60)

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
                    st.session_state.selected_stock = row.to_dict()
                    st.session_state.page = 'detail'
                    st.rerun()
                tag_col.markdown(f"<span class='sector-tag'>Tech & Services</span>", unsafe_allow_html=True)
            p, s = row['price'], row['numberOfShares']
            col3.write(f"${p:,.2f}" if p > 0 else "미정")
            if p > 0 and s > 0: col4.write(f"${(p*s):,.0f}")
            else: col4.markdown("<span class='status-pending'>⚠️ 공시대기</span>", unsafe_allow_html=True)

# ==========================================
# 🚀 화면 4: 상세 분석 (모든 정보 복구)
# ==========================================
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    if stock:
        if st.button("⬅️ 목록으로"): 
            st.session_state.page = 'calendar'
            st.rerun()
        
        st.title(f"🚀 {stock['name']} 상세 리서치")
        cl, cr = st.columns([1, 4])
        with cl:
            logo_url = f"https://logo.clearbit.com/{stock['symbol']}.com"
            try: st.image(logo_url, width=150)
            except: st.info("로고 준비 중")
        with cr:
            st.subheader(f"{stock['name']} ({stock['symbol']})")
            st.markdown(f"**업종:** <span class='sector-tag'>Technology & Software</span>", unsafe_allow_html=True)
            st.write(f"📅 **상장 예정일:** {stock.get('공모일', '정보 없음')} | 🏦 **거래소:** {stock.get('exchange', '정보 없음')}")
            st.divider()
            
            m1, m2, m3, m4 = st.columns(4)
            p = pd.to_numeric(stock.get('price'), errors='coerce')
            s = pd.to_numeric(stock.get('numberOfShares'), errors='coerce')
            m1.metric("공모 희망가", f"${p:,.2f}" if p > 0 else "미정")
            m2.metric("예상 공모 규모", f"${(p*s):,.0f}" if p and s and p*s > 0 else "계산 불가")
            m3.metric("유통 가능 물량", "분석 중", "S-1 참조")
            m4.metric("보호예수 기간", "180일", "표준")

        st.info(f"💡 **기업 비즈니스 요약:** {stock['name']}은(는) 혁신적인 기술을 바탕으로 시장을 선도하는 기업입니다.")
        st.divider()
        
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("<div class='report-card'><h4>📊 섹터 내 비교</h4><p>성장성 위주의 포지션입니다.</p></div>", unsafe_allow_html=True)
        with c2:
            st.markdown("<div class='report-card'><h4>💰 자금의 사용 용도</h4><p>R&D 및 시장 확장에 투자 예정입니다.</p></div>", unsafe_allow_html=True)
        
        clean_name = stock['name'].replace(" ", "+")
        sec_url = f"https://www.sec.gov/cgi-bin/browse-edgar?company={clean_name}&owner=exclude&action=getcompany"
        st.link_button("📄 SEC 공식 공시(S-1) 확인", sec_url, use_container_width=True, type="primary")
