import streamlit as st
import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import time
import uuid
import random
import html
import re
import urllib.parse
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText

# --- [Google & AI Libraries] ---
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from openai import OpenAI
import google.generativeai as genai
from tavily import TavilyClient
import yfinance as yf

# ==========================================
# 1. 기본 설정 및 Secrets 관리
# ==========================================
st.set_page_config(page_title="UnicornFinder", layout="wide", page_icon="🦄")

# 📍 [필수] 구글 드라이브 폴더 ID & API 키
DRIVE_FOLDER_ID = "1WwjsnOljLTdjpuxiscRyar9xk1W4hSn2"
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20" # Finnhub

# 📍 Gemini 모델 설정 (1.5-flash 고정)
try:
    genai_key = st.secrets.get("GENAI_API_KEY")
    if genai_key:
        genai.configure(api_key=genai_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
    else: model = None
except: model = None

# ==========================================
# 2. 세션 상태 초기화 (권한 및 데이터 유지)
# ==========================================
session_defaults = {
    'page': 'login', 'login_step': 'choice', 'auth_status': None, 'user_role': None,
    'user_id': None, 'user_info': {}, 'watchlist': [], 'posts': [], 
    'vote_data': {}, 'selected_stock': None, 'view_mode': 'all',
    'file_school': None, 'file_job': None, 'file_asset': None, # 파일 임시 저장
    'temp_signup_data': {}, 'cert_data': {}, 'auth_code_sent': False, 'real_code': None
}

for k, v in session_defaults.items():
    if k not in st.session_state: st.session_state[k] = v

# ---------------------------------------------------------
# [필수 함수] 주가 조회 함수 (NameError 방지용 최상단 배치)
# ---------------------------------------------------------
@st.cache_data(ttl=900)
def get_current_stock_price(symbol, api_key):
    try:
        import requests
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
        res = requests.get(url, timeout=2).json()
        return res.get('c', 0)
    except:
        return 0

# ==========================================
# 3. 백엔드 함수 (Google Drive/Sheets/Auth)
# ==========================================
@st.cache_resource
def get_gcp_clients():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = st.secrets.get("gcp_service_account") or st.secrets.get("gspread")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds), build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"구글 연결 오류: {e}"); return None, None

def upload_photo_to_drive(file_obj, filename_prefix):
    if not file_obj: return "미제출"
    try:
        _, drive = get_gcp_clients()
        file_obj.seek(0)
        meta = {'name': f"{filename_prefix}_{file_obj.name}", 'parents': [DRIVE_FOLDER_ID]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type, resumable=True, chunksize=256*1024)
        f = drive.files().create(body=meta, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        drive.permissions().create(fileId=f.get('id'), body={'type': 'anyone', 'role': 'reader'}, supportsAllDrives=True).execute()
        return f.get('webViewLink')
    except: return "업로드 실패"

def load_users():
    client, _ = get_gcp_clients()
    if client:
        try:
            return client.open("unicorn_users").sheet1.get_all_records()
        except: return []
    return []

def save_user_to_sheets(user_data):
    client, _ = get_gcp_clients()
    if client:
        try:
            sh = client.open("unicorn_users").sheet1
            row = [
                user_data['id'], user_data['pw'], user_data['email'], user_data['phone'],
                user_data['role'], user_data['status'], # role, status
                user_data.get('univ',''), user_data.get('job_title',''), user_data.get('asset',''),
                user_data.get('display_name',''), datetime.now().strftime("%Y-%m-%d"),
                user_data.get('link_univ',''), user_data.get('link_job',''), user_data.get('link_asset',''),
                "True,True,True"
            ]
            sh.append_row(row)
            return True
        except Exception as e: st.error(str(e))
    return False

# --- [권한 체크 도우미 함수] ---
def check_permission(action):
    """
    action: 'view', 'watchlist', 'write'
    Return: True/False
    """
    status = st.session_state.auth_status # 'user', 'guest', None
    role = st.session_state.get('user_info', {}).get('role', 'restricted') # 'user', 'restricted', 'admin'
    
    if action == 'view': return True # 모두 가능
    
    if action == 'watchlist':
        # Guest는 불가, Basic(Restricted) 이상 가능
        return status == 'user' 
        
    if action == 'write':
        # Full Member(User) 또는 Admin만 가능
        return status == 'user' and role in ['user', 'admin']
        
    return False

# ==========================================
# 4. 데이터/AI 함수 (원형 서버 기능 이식)
# ==========================================
@st.cache_data(ttl=14400)
def get_extended_ipo_data(api_key):
    # (원형 서버의 IPO 데이터 수집 로직)
    now = datetime.now()
    ranges = [(now - timedelta(days=200), now + timedelta(days=120))] # 범위 축소 예시
    all_data = []
    for start, end in ranges:
        url = f"https://finnhub.io/api/v1/calendar/ipo?from={start.strftime('%Y-%m-%d')}&to={end.strftime('%Y-%m-%d')}&token={api_key}"
        try:
            res = requests.get(url, timeout=3).json()
            if 'ipoCalendar' in res: all_data.extend(res['ipoCalendar'])
        except: continue
    
    if not all_data: return pd.DataFrame()
    df = pd.DataFrame(all_data)
    df = df.drop_duplicates(subset=['symbol', 'date'])
    df['공모일_dt'] = pd.to_datetime(df['date'], errors='coerce').dt.normalize()
    return df.dropna(subset=['공모일_dt'])

@st.cache_data(ttl=86400)
def get_financial_metrics(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/stock/metric?symbol={symbol}&metric=all&token={api_key}"
        return requests.get(url, timeout=3).json().get('metric', {})
    except: return None

@st.cache_data(show_spinner=False, ttl=86400)
def get_ai_summary_final(query):
    # (원형 서버의 AI 요약 로직 - Groq/Tavily)
    tavily_key = st.secrets.get("TAVILY_API_KEY")
    groq_key = st.secrets.get("GROQ_API_KEY")
    if not (tavily_key and groq_key): return "API Key 설정 필요"
    
    try:
        tavily = TavilyClient(api_key=tavily_key)
        context = "\n".join([r['content'] for r in tavily.search(query=query, max_results=3).get('results', [])])
        
        client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_key)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "한국어로 3문단 요약하세요."},
                {"role": "user", "content": f"Context: {context}\nQuery: {query}"}
            ], temperature=0.1
        )
        return resp.choices[0].message.content
    except: return "분석 서비스 연결 지연"

# ==========================================
# 5. 메인 앱 UI 구조
# ==========================================

# [CSS 스타일링]
st.markdown("""
    <style>
    .stApp { background-color: #FFFFFF; color: #333; }
    div[data-testid="stPills"] button { background-color: #000 !important; color: #fff !important; border-radius: 20px; }
    .auth-card { padding: 30px; border-radius: 15px; border: 1px solid #eee; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 화면 1: 로그인 & 회원가입 (Test Server Logic)
# ---------------------------------------------------------
if st.session_state.page == 'login':
    st.markdown("<h1 style='text-align:center;'>🦄 Unicorn Finder</h1>", unsafe_allow_html=True)
    st.write("")

    if st.session_state.login_step == 'choice':
        c1, c2, c3 = st.columns([1, 1, 1])
        with c2:
            # 1. 로그인
            if st.button("🔑 로그인", use_container_width=True, type="primary"):
                st.session_state.login_step = 'login_input'
                st.rerun()
            
            # 2. 회원가입 (Basic / Full 통합)
            if st.button("📝 회원가입", use_container_width=True):
                st.session_state.login_step = 'signup_input'
                st.rerun()
            
            # 3. 구경하기 (Guest)
            st.divider()
            if st.button("👀 구경하기 (Guest Mode)", use_container_width=True):
                st.session_state.auth_status = 'guest'
                st.session_state.user_role = 'guest'
                st.session_state.user_id = 'Guest'
                st.session_state.page = 'calendar'
                st.rerun()

    elif st.session_state.login_step == 'login_input':
        # (로그인 입력 UI - 생략 없이 구현)
        st.markdown("<div class='auth-card'><h5>로그인</h5>", unsafe_allow_html=True)
        lid = st.text_input("아이디")
        lpw = st.text_input("비밀번호", type="password")
        
        if st.button("접속하기", type="primary", use_container_width=True):
            users = load_users()
            user = next((u for u in users if str(u['id']) == lid), None)
            
            if user and str(user['pw']) == lpw:
                # 권한 할당 로직
                st.session_state.auth_status = 'user'
                st.session_state.user_id = lid
                st.session_state.user_info = user 
                
                # Role Check (Full vs Restricted)
                if user['role'] == 'admin': st.session_state.user_role = 'admin'
                elif user['role'] == 'user' and user['status'] == 'approved':
                    st.session_state.user_role = 'user' # Full Member
                else:
                    # status가 pending이거나 role이 restricted인 경우
                    st.session_state.user_role = 'restricted' # Basic Member
                
                st.success(f"환영합니다! ({st.session_state.user_role} 모드)")
                time.sleep(0.5)
                st.session_state.page = 'calendar'
                st.rerun()
            else:
                st.error("정보가 일치하지 않습니다.")
        
        if st.button("취소", use_container_width=True):
            st.session_state.login_step = 'choice'
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    elif st.session_state.login_step == 'signup_input':
        # (회원가입 1단계: ID/PW/Email) - 간소화
        st.markdown("<div class='auth-card'><h5>회원가입 (기본정보)</h5>", unsafe_allow_html=True)
        new_id = st.text_input("아이디")
        new_pw = st.text_input("비밀번호", type="password")
        new_email = st.text_input("이메일")
        
        if st.button("다음 (인증 선택)", type="primary"):
            st.session_state.temp_signup_data = {'id': new_id, 'pw': new_pw, 'email': new_email, 'phone': '000'}
            st.session_state.login_step = 'signup_step_2'
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    elif st.session_state.login_step == 'signup_step_2':
        # (회원가입 2단계: 서류 제출 - 여기가 핵심 분기점)
        st.markdown("<div class='auth-card'><h5>추가 인증 (선택사항)</h5>", unsafe_allow_html=True)
        st.info("💡 서류를 제출하면 **'글쓰기/투표'** 권한이 부여됩니다.\n제출하지 않으면 **'관심종목'** 기능만 사용 가능합니다.")
        
        # 파일 업로더
        f_school = st.file_uploader("🎓 학력 증빙", key="fu_school")
        f_job = st.file_uploader("💼 재직 증빙", key="fu_job")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("건너뛰기 (Basic 회원)", use_container_width=True):
                # 서류 없이 가입 -> Role: Restricted
                final_data = {
                    **st.session_state.temp_signup_data,
                    "role": "restricted", "status": "active", # 즉시 활동 가능하지만 제한됨
                    "display_name": f"Basic | {st.session_state.temp_signup_data['id']}"
                }
                if save_user_to_sheets(final_data):
                    st.success("가입 완료! (Basic 등급)")
                    st.session_state.login_step = 'choice'
                    time.sleep(1)
                    st.rerun()
        
        with col2:
            if st.button("제출 및 승인요청 (Full 회원)", type="primary", use_container_width=True):
                if not (f_school or f_job):
                    st.error("최소 1개의 파일을 업로드해야 승인 요청이 가능합니다.")
                else:
                    # 파일 업로드 진행
                    with st.spinner("업로드 중..."):
                        l_s = upload_photo_to_drive(f_school, f"{st.session_state.temp_signup_data['id']}_school")
                        l_j = upload_photo_to_drive(f_job, f"{st.session_state.temp_signup_data['id']}_job")
                        
                        final_data = {
                            **st.session_state.temp_signup_data,
                            "role": "user", "status": "pending", # 승인 대기
                            "display_name": f"Pending | {st.session_state.temp_signup_data['id']}",
                            "link_univ": l_s, "link_job": l_j
                        }
                        if save_user_to_sheets(final_data):
                            st.success("승인 요청 완료! 관리자 검토 후 풀액세스 권한이 부여됩니다.")
                            st.session_state.login_step = 'choice'
                            time.sleep(2)
                            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------
# 화면 2: 메인 앱 (Calendar + Detail + Board)
# ---------------------------------------------------------
elif st.session_state.page in ['calendar', 'detail', 'board']:
    
    # [1] 상단 네비게이션
    nav_opts = ["로그아웃", "메인", "관심종목", "게시판"]
    sel = st.pills("Nav", nav_opts, default="메인", label_visibility="collapsed")
    
    if sel == "로그아웃":
        st.session_state.clear()
        st.rerun()
    elif sel == "메인":
        st.session_state.page = 'calendar'
        st.session_state.view_mode = 'all'
    elif sel == "관심종목":
        # 권한 체크: Guest는 불가
        if check_permission('watchlist'):
            st.session_state.page = 'calendar'
            st.session_state.view_mode = 'watchlist'
        else:
            st.toast("🚫 Guest는 관심종목 기능을 사용할 수 없습니다. 로그인해주세요.")
    elif sel == "게시판":
        st.session_state.page = 'board'

    # [2] 페이지별 내용
    if st.session_state.page == 'calendar':
        # ---------------------------------------------------------
        # [캘린더 화면] 원형의 디자인(CSS) + 권한 기능(Permission) 완벽 통합
        # ---------------------------------------------------------
        
        # [CSS 복원] 모바일 최적화 및 리스트 스타일
        st.markdown("""
            <style>
            .price-main { font-size: 14px !important; font-weight: bold; white-space: nowrap; }
            .price-sub { font-size: 11px !important; color: #666 !important; }
            .mobile-sub { font-size: 11px !important; color: #888 !important; margin-top: -2px; }
            div[data-testid="column"] { display: flex; flex-direction: column; justify-content: center; }
            </style>
        """, unsafe_allow_html=True)

        st.subheader("📅 IPO Calendar")
        
        # 1. 상단 필터 (원형 스타일)
        col_f1, col_f2 = st.columns([1, 1])
        with col_f1:
            period = st.selectbox("조회 기간", ["상장 예정 (30일)", "지난 6개월", "지난 12개월", "지난 18개월"], label_visibility="collapsed")
        with col_f2:
            sort_option = st.selectbox("정렬 순서", ["최신순", "수익률"], label_visibility="collapsed")
        
        # 2. 데이터 로드
        all_df_raw = get_extended_ipo_data(MY_API_KEY)
        
        # 3. 데이터 필터링 및 가공
        if not all_df_raw.empty:
            df = all_df_raw.copy()
            today_dt = pd.to_datetime(datetime.now().date())
            
            # 기간 필터링
            if period == "상장 예정 (30일)":
                df = df[(df['공모일_dt'] >= today_dt) & (df['공모일_dt'] <= today_dt + timedelta(days=30))]
            elif period == "지난 6개월":
                df = df[(df['공모일_dt'] < today_dt) & (df['공모일_dt'] >= today_dt - timedelta(days=180))]
            elif period == "지난 12개월":
                df = df[(df['공모일_dt'] < today_dt) & (df['공모일_dt'] >= today_dt - timedelta(days=365))]
            else:
                df = df[(df['공모일_dt'] < today_dt) & (df['공모일_dt'] >= today_dt - timedelta(days=540))]
            
            # 관심 종목 모드
            if st.session_state.view_mode == 'watchlist':
                df = df[df['symbol'].isin(st.session_state.watchlist)]
                st.info(f"⭐ 나의 관심 종목: {len(df)}개")

            # 정렬 로직 (수익률 계산 포함)
            if 'live_price' not in df.columns: df['live_price'] = 0.0
            
            if sort_option == "수익률" and not df.empty:
                with st.spinner("수익률 계산 중..."):
                    returns = []
                    prices = []
                    for _, row in df.iterrows():
                        try:
                            p_curr = get_current_stock_price(row['symbol'], MY_API_KEY)
                            p_ipo = float(str(row.get('price','0')).replace('$','').split('-')[0])
                            ret = ((p_curr - p_ipo)/p_ipo)*100 if p_ipo > 0 and p_curr > 0 else -999
                            returns.append(ret)
                            prices.append(p_curr)
                        except: 
                            returns.append(-999); prices.append(0)
                    df['temp_return'] = returns
                    df['live_price'] = prices
                    df = df.sort_values(by='temp_return', ascending=False)
            else:
                df = df.sort_values(by='공모일_dt', ascending=False)
            
            # 4. 리스트 출력 (원형 디자인 + 권한 체크)
            if not df.empty:
                for idx, row in df.iterrows():
                    with st.container():
                        # 레이아웃 비율 (원형 코드의 0.5 : 3.5 : 1 유지)
                        c1, c2, c3 = st.columns([0.7, 3.3, 1])
                        
                        # [A] 관심종목 버튼 (권한 체크 적용)
                        with c1:
                            if check_permission('watchlist'):
                                is_watched = row['symbol'] in st.session_state.watchlist
                                if st.button("★" if is_watched else "☆", key=f"star_{idx}"):
                                    if is_watched: st.session_state.watchlist.remove(row['symbol'])
                                    else: st.session_state.watchlist.append(row['symbol'])
                                    st.rerun()
                            else:
                                st.write("🔒") # Guest

                        # [B] 종목 정보 (클릭 시 상세 이동)
                        with c2:
                            if st.button(f"{row['name']}", key=f"main_{idx}"):
                                st.session_state.selected_stock = row.to_dict()
                                st.session_state.page = 'detail'
                                st.rerun()
                            
                            # 서브 정보 표시
                            try: 
                                p_val = float(str(row.get('price','0')).replace('$','').split('-')[0])
                                s_val = int(row.get('numberOfShares',0)) * p_val / 1000000
                                size_str = f" | ${s_val:,.0f}M" if s_val > 0 else ""
                            except: size_str = ""
                            
                            st.markdown(f"<div class='mobile-sub'>{row['symbol']} | {row.get('exchange','-')}{size_str}</div>", unsafe_allow_html=True)

                        # [C] 가격/수익률 정보 (원형의 색상 로직 복원)
                        with c3:
                            p_raw = str(row.get('price','0')).replace('$','').split('-')[0]
                            try: p_val = float(p_raw)
                            except: p_val = 0
                            
                            # 실시간 가격이 있으면 수익률 색상 적용
                            curr = row.get('live_price', 0)
                            if curr == 0: curr = get_current_stock_price(row['symbol'], MY_API_KEY) # 데이터 없으면 즉시 조회
                            
                            if curr > 0 and p_val > 0:
                                pct = ((curr - p_val) / p_val) * 100
                                color = "#e61919" if pct > 0 else "#1919e6" if pct < 0 else "#333"
                                arrow = "▲" if pct > 0 else "▼" if pct < 0 else ""
                                price_html = f"<div class='price-main' style='color:{color};'>${curr:,.2f} ({arrow}{abs(pct):.0f}%)</div>"
                            else:
                                price_html = f"<div class='price-main'>${p_val:,.2f}</div>"
                            
                            st.markdown(f"<div style='text-align:right;'>{price_html}<div class='price-sub'>{row['date']}</div></div>", unsafe_allow_html=True)
                        
                        st.divider()
            else:
                st.warning("조건에 맞는 종목이 없습니다.")
        else:
            st.error("데이터를 불러오지 못했습니다.")
    
