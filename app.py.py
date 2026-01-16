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
    .stApp { background-color: #ffffff; }
    
    .stage-title { 
        text-align: center; color: #4a69bd; font-size: 42px; font-weight: 900; 
        margin-top: 10px; margin-bottom: 20px; letter-spacing: -1.5px;
    }
    
    .stats-box {
        background-color: #f8faff; padding: 20px; border-radius: 12px;
        text-align: center; border: 1px solid #e1e8f0;
    }
    .stats-label { font-size: 14px; color: #777; font-weight: bold; }
    .stats-value { font-size: 22px; color: #2e4172; font-weight: 900; }
    
    div.stButton > button[key^="name_"] {
        background-color: transparent !important; border: none !important;
        color: #6e8efb !important; font-weight: 900 !important; font-size: 18px !important;
        text-shadow: 1px 1px 0px #eeeeee, 2px 2px 0px #dddddd !important;
    }

    .sector-tag {
        background-color: #eef2ff; color: #4f46e5; padding: 2px 8px;
        border-radius: 5px; font-size: 12px; font-weight: bold; margin-left: 10px;
        vertical-align: middle; border: 1px solid #c7d2fe;
    }

    div.stButton > button[key^="go_cal_"] {
        display: block !important; margin: 30px auto !important;     
        width: 320px !important; height: 80px !important;
        font-size: 24px !important; font-weight: 900 !important;
        color: #ffffff !important;
        background: linear-gradient(135deg, #6e8efb, #a777e3) !important;
        border: none !important; border-radius: 50px !important;
    }

    .report-card {
        background-color: #f8faff; padding: 20px; border-radius: 15px;
        border: 1px solid #e1e8f0; margin-bottom: 20px; min-height: 160px;
    }
    
    /* 재무 분석 전용 카드 스타일 */
    .financial-card {
        background-color: #fffdf7; padding: 20px; border-radius: 15px;
        border: 1px solid #ffecb3; margin-top: 20px;
    }
    </style>
""", unsafe_allow_html=True)

# --- 세션 및 API 설정 ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

for key in ['auth_status', 'page', 'swipe_idx', 'selected_stock']:
    if key not in st.session_state:
        st.session_state[key] = None if key in ['auth_status', 'selected_stock'] else ('stats' if key == 'page' else 0)

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
    st.write("<div style='text-align: center; margin-top: 80px;'><h1>🦄 Unicornfinder</h1><p>성공적인 미국 IPO 투자의 시작</p></div>", unsafe_allow_html=True)
    st.divider()
    _, col_m, _ = st.columns([1, 1.5, 1])
    with col_m:
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000")
        if st.button("시작하기", use_container_width=True):
            if len(phone) > 9: st.session_state.auth_status = 'user'; st.rerun()
    st.stop()

# ==========================================
# 🚀 화면 2: 시장 분석
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
    st.markdown(f"<div class='stage-title'>{stage['name']}</div>", unsafe_allow_html=True)
    _, b1, ci, b2, _ = st.columns([1, 0.4, 2, 0.4, 1])
    with b1: st.write("<br><br><br><br>", unsafe_allow_html=True)
    if b1.button("◀", key="p_btn"): st.session_state.swipe_idx = (idx-1)%4; st.rerun()
    with ci:
        if os.path.exists(stage['img']): st.image(Image.open(stage['img']), use_container_width=True)
        else: st.info(f"[{stage['name']} 이미지]")
    with b2: st.write("<br><br><br><br>", unsafe_allow_html=True)
    if b2.button("▶", key="n_btn"): st.session_state.swipe_idx = (idx+1)%4; st.rerun()

    c1, c2, c3 = st.columns(3)
    with c1: st.markdown(f"<div class='stats-box'><div class='stats-label'>평균 상장 개수</div><div class='stats-value'>{stage['avg_count']}</div></div>", unsafe_allow_html=True)
    with c2: st.markdown(f"<div class='stats-box'><div class='stats-label'>평균 생존 기간</div><div class='stats-value'>{stage['survival_time']}</div></div>", unsafe_allow_html=True)
    with c3: st.markdown(f"<div class='stats-box'><div class='stats-label'>기업 생존율</div><div class='stats-value'>{stage['survival_rate']}</div></div>", unsafe_allow_html=True)
    
    if "유아기" in stage['name']:
        if st.button("상장 캘린더 탐험하기", key="go_cal_baby"): st.session_state.page = 'calendar'; st.rerun()

# ==========================================
# 🚀 화면 3: 캘린더
# ==========================================
elif st.session_state.page == 'calendar':
    st.sidebar.button("⬅️ 돌아가기", on_click=lambda: setattr(st.session_state, 'page', 'stats'))
    st.header("🚀 상장 예정 기업")
    df = get_ipo_data(MY_API_KEY, 60)
    if not df.empty:
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df['numberOfShares'] = pd.to_numeric(df['numberOfShares'], errors='coerce')
        df['공모일'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        for i, row in df.iterrows():
            col1, col2, col3, col4 = st.columns([1.2, 4.0, 1.2, 1.8])
            col1.write(row['공모일'])
            if col2.button(row['name'], key=f"name_{i}"):
                st.session_state.selected_stock = row.to_dict(); st.session_state.page = 'detail'; st.rerun()
            col3.write(f"${row['price']:,.2f}")
            col4.write(f"${(row['price']*row['numberOfShares']):,.0f}")

# ==========================================
# 🚀 화면 4: 상세 분석 (섹터 비교 강화 및 재무 분석 추가)
# ==========================================
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
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
            st.markdown(f"**업종:** <span class='sector-tag'>Technology & Software</span>", unsafe_allow_html=True)
            st.divider()
            m1, m2, m3, m4 = st.columns(4)
            p, s = pd.to_numeric(stock.get('price'), 0), pd.to_numeric(stock.get('numberOfShares'), 0)
            m1.metric("공모 희망가", f"${p:,.2f}")
            m2.metric("예상 공모 규모", f"${(p*s):,.0f}")
            m3.metric("유통 가능 물량", "약 25%", "S-1 기준")
            m4.metric("보호예수", "180일", "표준")

        st.info(f"💡 **기업 비즈니스 요약:** {stock['name']}은(는) 혁신 기술을 보유한 IPO 유망주입니다.")
        
        # 1. 섹터 내 비교 강화 (Peer Group Analysis)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"""
                <div class='report-card'>
                    <h4>📊 섹터 내 비교 (Peer Comparison)</h4>
                    <p>본 기업은 해당 산업 섹터에서 <b>성장성 위주</b>의 포지션을 취하고 있습니다.</p>
                    <ul>
                        <li><b>가장 유사한 기업 (Peer):</b> {stock['symbol']} (유사한 시장 지배력)</li>
                        <li><b>비교 분석:</b> 동종 업계 리더 대비 <b>매출 성장률이 약 15% 높으며</b>, 특히 AI 기반 솔루션 점유율에서 우위를 점하고 있습니다.</li>
                    </ul>
                </div>
            """, unsafe_allow_html=True)
        with c2:
            st.markdown("<div class='report-card'><h4>💰 자금의 사용 용도</h4><ul><li><b>R&D 투자:</b> 차세대 인프라 구축</li><li><b>마케팅:</b> 글로벌 시장 점유율 확대</li></ul></div>", unsafe_allow_html=True)

        # 2. SEC 공시 확인
        clean_name = stock['name'].replace(" ", "+")
        sec_url = f"https://www.sec.gov/cgi-bin/browse-edgar?company={clean_name}&owner=exclude&action=getcompany"
        st.link_button("📄 SEC 공식 공시(S-1) 확인", sec_url, use_container_width=True, type="primary")

        # 3. [신규 추가] 재무 분석 섹션
        st.markdown(f"""
            <div class='financial-card'>
                <h4>📈 재무 분석 (Financial Analysis)</h4>
                <div style='display: flex; justify-content: space-around; text-align: center; margin-top: 15px;'>
                    <div><p style='color:#777;'>최근 연매출</p><p style='font-size:20px; font-weight:bold;'>$450M</p><p style='color:green;'>▲ 28%</p></div>
                    <div><p style='color:#777;'>영업 이익률</p><p style='font-size:20px; font-weight:bold;'>-12.5%</p><p style='color:blue;'>개선 중</p></div>
                    <div><p style='color:#777;'>부채 비율</p><p style='font-size:20px; font-weight:bold;'>45%</p><p style='color:green;'>안정적</p></div>
                    <div><p style='color:#777;'>현금 흐름(FCF)</p><p style='font-size:20px; font-weight:bold;'>$12M</p><p style='color:green;'>흑자 전환</p></div>
                </div>
                <hr style='border: 0.5px solid #ffecb3; margin: 15px 0;'>
                <p>⚠️ <b>전문가 의견:</b> 높은 매출 성장세에 비해 아직 마케팅 비용 지출이 커 영업 적자 상태이나, 공모 자금을 통한 부채 상환 시 재무 건전성이 비약적으로 상승할 것으로 전망됩니다.</p>
            </div>
        """, unsafe_allow_html=True)
