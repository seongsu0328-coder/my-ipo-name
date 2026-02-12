import streamlit as st
import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import xml.etree.ElementTree as ET
import os
import time
import uuid
import random
import math
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
import smtplib
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# --- [AI 및 검색 라이브러리 통합] ---
from openai import OpenAI             # ✅ Groq(뉴스 요약)용
import google.generativeai as genai   # ✅ Gemini(메인 종목 분석)용 - 지우면 안 됨!
from tavily import TavilyClient       # ✅ Tavily(뉴스 검색)용
from duckduckgo_search import DDGS

# ==========================================
# [설정] 구글 드라이브 폴더 ID (필수 입력)
# ==========================================
DRIVE_FOLDER_ID = "1WwjsnOljLTdjpuxiscRyar9xk1W4hSn2"

st.set_page_config(page_title="Unicorn Finder", layout="centered")

# ==========================================
# [추가] 본서버 UI 연동을 위한 핵심 백엔드 함수
# ==========================================

# 1. Finnhub API KEY 설정 (사용자 요청 반영)
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

# 2. 실시간 주가 조회 함수 (NameError 방지)
@st.cache_data(ttl=900)
def get_current_stock_price(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
        res = requests.get(url, timeout=2).json()
        return res.get('c', 0)
    except:
        return 0

# 3. 기업 프로필 조회 함수 (로고, 산업군 등)
@st.cache_data(ttl=86400)
def get_company_profile(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={api_key}"
        res = requests.get(url, timeout=3).json()
        return res if res and 'name' in res else None
    except:
        return None

# 4. 재무 지표 조회 함수 (성장률, 이익률 등)
@st.cache_data(ttl=43200)
def get_financial_metrics(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/stock/metric?symbol={symbol}&metric=all&token={api_key}"
        res = requests.get(url, timeout=3).json()
        metrics = res.get('metric', {})
        if metrics:
            return {
                "growth": metrics.get('salesGrowthYoy', None),
                "op_margin": metrics.get('operatingMarginTTM', None),
                "net_margin": metrics.get('netProfitMarginTTM', None),
                "debt_equity": metrics.get('totalDebt/totalEquityQuarterly', None)
            }
        return None
    except:
        return None

# 5. 확장 IPO 데이터 수집 함수 (과거 데이터 누락 방지용)
@st.cache_data(ttl=14400)
def get_extended_ipo_data(api_key):
    now = datetime.now()
    # 과거 18개월 ~ 미래 3개월 범위를 커버하여 데이터 유실 방지
    ranges = [
        (now - timedelta(days=540), now + timedelta(days=90))
    ]
    all_data = []
    for start, end in ranges:
        url = f"https://finnhub.io/api/v1/calendar/ipo?from={start.strftime('%Y-%m-%d')}&to={end.strftime('%Y-%m-%d')}&token={api_key}"
        try:
            res = requests.get(url, timeout=5).json()
            if 'ipoCalendar' in res:
                all_data.extend(res['ipoCalendar'])
        except:
            continue
    
    if not all_data: return pd.DataFrame()
    df = pd.DataFrame(all_data)
    df = df.drop_duplicates(subset=['symbol', 'date'])
    df['공모일_dt'] = pd.to_datetime(df['date'], errors='coerce').dt.normalize()
    return df.dropna(subset=['공모일_dt'])

# ==========================================
# [기능] 구글 연결 및 유저 관리
# ==========================================
@st.cache_resource
def get_gcp_clients():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gspread_client = gspread.authorize(creds)
        drive_service = build('drive', 'v3', credentials=creds)
        return gspread_client, drive_service
    except Exception as e:
        st.error(f"구글 연결 실패: {e}")
        return None, None

def load_users():
    client, _ = get_gcp_clients()
    if client:
        try:
            sh = client.open("unicorn_users").sheet1
            return sh.get_all_records()
        except:
            return []
    return []

def get_asset_grade(asset_text):
    if asset_text == "10억 미만": return "Bronze"
    elif asset_text == "10억~30억": return "Silver"
    elif asset_text == "30억~80억": return "Gold"
    elif asset_text == "80억 이상": return "Diamond"
    return ""

def add_user(data):
    client, _ = get_gcp_clients()
    if client:
        sh = client.open("unicorn_users").sheet1
        
        # 1. 아이디 익명화 (닉네임 생성용)
        user_id = data['id']
        masked_id = user_id[:3] + "*" * (len(user_id) - 3) if len(user_id) > 3 else user_id + "***"
        
        # 2. 인증 항목 결합
        display_parts = []
        auth_count = 0
        
        if data['univ'] and data['link_univ'] != "미제출":
            display_parts.append(data['univ'])
            auth_count += 1
        if data['job'] and data['link_job'] != "미제출":
            display_parts.append(data['job'])
            auth_count += 1
        if data['asset'] and data['link_asset'] != "미제출":
            grade = get_asset_grade(data['asset'])
            display_parts.append(grade)
            auth_count += 1
            
        display_name = " ".join(display_parts + [masked_id])
        role = "user" if auth_count > 0 else "restricted"
        
        # 3. [수정됨] 15번째 열(visibility) 기본값 추가
        row = [
            data['id'], data['pw'], data['email'], data['phone'],
            role, 'pending', 
            data['univ'], data['job'], data['asset'], display_name,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data['link_univ'], data['link_job'], data['link_asset'],
            "True,True,True"  # <--- 이 부분이 15번째 열에 들어갑니다.
        ]
        sh.append_row(row)

def update_user_visibility(user_id, visibility_data):
    client, _ = get_gcp_clients()
    if client:
        try:
            sh = client.open("unicorn_users").sheet1
            # 1열(A열)에서 유저 아이디와 정확히 일치는 셀 찾기
            cell = sh.find(str(user_id), in_column=1) 
            
            if cell:
                # 리스트를 "True,False,True" 형태의 문자열로 변환
                visibility_str = ",".join([str(v) for v in visibility_data])
                # 15번째 열(O열) 업데이트
                sh.update_cell(cell.row, 15, visibility_str)
                return True
        except Exception as e:
            st.error(f"시트 통신 오류: {e}")
    return False

def upload_photo_to_drive(file_obj, filename_prefix):
    if file_obj is None: return "미제출"
    try:
        _, drive_service = get_gcp_clients()
        file_obj.seek(0)
        
        file_metadata = {
            'name': f"{filename_prefix}_{file_obj.name}", 
            'parents': [DRIVE_FOLDER_ID]
        }
        
        # 100*1024 대신 구글 규격에 맞는 256*1024로 변경
        media = MediaIoBaseUpload(
            file_obj, 
            mimetype=file_obj.type, 
            resumable=True, 
            chunksize=256*1024  # 256KB 단위로 전송
        )
        
        file = drive_service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink',
            supportsAllDrives=True
        ).execute()

        drive_service.permissions().create(
            fileId=file.get('id'),
            body={'type': 'anyone', 'role': 'reader'},
            supportsAllDrives=True
        ).execute()
        
        return file.get('webViewLink')
    except Exception as e:
        # 에러 발생 시 재시도 안내 출력
        st.error(f"📂 업로드 실패 (네트워크 확인 필요): {e}")
        return "업로드 실패"
        
def send_email_code(to_email, code):
    try:
        if "smtp" in st.secrets:
            sender_email = st.secrets["smtp"]["email_address"]
            sender_pw = st.secrets["smtp"]["app_password"]
        else:
            sender_email = st.secrets["email_address"]
            sender_pw = st.secrets["app_password"]
        msg = MIMEText(f"안녕하세요. 인증번호는 [{code}] 입니다.")
        msg['Subject'] = "[Unicorn Finder] 본인 인증번호"
        msg['From'] = sender_email
        msg['To'] = to_email
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(sender_email, sender_pw)
            s.sendmail(sender_email, to_email, msg.as_string())
        st.toast(f"📧 {to_email}로 인증 메일을 보냈습니다!", icon="✅")
        return True
    except Exception as e:
        st.error(f"❌ 이메일 전송 실패: {e}")
        return False

# 📍 승인 알림 메일 함수 추가
def send_approval_email(to_email, user_id):
    try:
        # secrets에서 설정 가져오기 (기존 이메일 설정 활용)
        if "smtp" in st.secrets:
            sender_email = st.secrets["smtp"]["email_address"]
            sender_pw = st.secrets["smtp"]["app_password"]
        else:
            sender_email = st.secrets["email_address"]
            sender_pw = st.secrets["app_password"]
            
        subject = "[Unicorn Finder] 가입 승인 안내"
        body = f"""
        안녕하세요, {user_id}님!
        
        축하합니다! Unicorn Finder의 회원 가입이 승인되었습니다.
        이제 로그인하여 모든 서비스를 정상적으로 이용하실 수 있습니다.
        
        유니콘이 되신 것을 환영합니다! 🦄
        """
        
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = to_email
        
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(sender_email, sender_pw)
            s.sendmail(sender_email, to_email, msg.as_string())
        return True
    except Exception as e:
        st.error(f"📧 승인 메일 전송 실패: {e}")
        return False

def save_user_to_sheets(user_data):
    """회원가입 정보를 구글 시트에 최종 기록하는 함수"""
    # 1. 구글 클라이언트 가져오기 (이 함수도 정의되어 있어야 합니다)
    client, _ = get_gcp_clients()
    
    if client:
        try:
            # 2. 시트 열기 (시트 이름: unicorn_users)
            sh = client.open("unicorn_users").sheet1
            
            # 3. 15개 열 데이터 매핑 (A열 ~ O열)
            # ID, PW, Email, Phone, Role, Status, Univ, Job, Asset, Display, Date, Link_U, Link_J, Link_A, Visibility
            row = [
                user_data.get('id'),
                user_data.get('pw'),
                user_data.get('email'),
                user_data.get('phone'),
                user_data.get('role', 'restricted'), # 기본값 restricted
                user_data.get('status', 'pending'),  # 기본값 pending
                user_data.get('univ', ''),
                user_data.get('job', ''),   # job 또는 job_title
                user_data.get('asset', ''),
                user_data.get('display_name', ''),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), # 가입일
                user_data.get('link_univ', '미제출'),
                user_data.get('link_job', '미제출'),
                user_data.get('link_asset', '미제출'),
                "True,True,True" # 기본 노출 설정 (모두 공개)
            ]
            
            # 4. 행 추가
            sh.append_row(row)
            return True
            
        except Exception as e:
            st.error(f"구글 시트 저장 중 오류 발생: {str(e)}")
            return False
    
    return False

def send_rejection_email(to_email, user_id, reason):
    try:
        if "smtp" in st.secrets:
            sender_email = st.secrets["smtp"]["email_address"]
            sender_pw = st.secrets["smtp"]["app_password"]
        else:
            sender_email = st.secrets["email_address"]
            sender_pw = st.secrets["app_password"]
            
        subject = "[Unicorn Finder] 가입 승인 보류 안내"
        body = f"""
        안녕하세요, {user_id}님. 
        Unicorn Finder 운영팀입니다.
        
        제출해주신 증빙 서류에 보완이 필요하여 승인이 잠시 보류되었습니다.
        
        [보류 사유]
        {reason}
        
        위 사유를 확인하신 후 다시 신청해주시면 신속히 재검토하겠습니다.
        감사합니다.
        """
        
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = to_email
        
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(sender_email, sender_pw)
            s.sendmail(sender_email, to_email, msg.as_string())
        return True
    except Exception as e:
        st.error(f"📧 보류 메일 전송 실패: {e}")
        return False

# --- [신규 추가: 권한 관리 로직] ---
def check_permission(action):
    """
    권한 체크 로직 (노출 설정 반영 버전)
    """
    auth_status = st.session_state.get('auth_status')
    user_info = st.session_state.get('user_info', {})
    user_role = user_info.get('role', 'restricted')
    user_status = user_info.get('status', 'pending')
    
    # [신규] 유저의 노출 설정 확인
    vis_str = str(user_info.get('visibility', 'True,True,True'))
    is_public_mode = 'True' in vis_str # 하나라도 True가 있으면 공개 모드

    if action == 'view':
        return True
    
    if action == 'watchlist':
        return auth_status == 'user'
    
    if action == 'write':
        # 1. 로그인 했는가?
        if auth_status == 'user':
            # 2. 관리자면 무조건 통과
            if user_info.get('role') == 'admin': return True
            
            # 3. 일반 유저 조건: (서류제출함) AND (관리자 승인됨) AND (정보 공개 중임)
            if (user_role == 'user') and (user_status == 'approved') and is_public_mode:
                return True
                
        return False
        
    return False

# ==========================================
# [추가됨] 상단 네비게이션 메뉴 (블랙 스타일)
# ==========================================
def render_navbar():
    # 1. CSS 스타일 정의 (블랙 & 화이트)
    st.markdown("""
        <style>
        div[data-testid="stPills"] div[role="radiogroup"] button {
            border: none !important;
            outline: none !important;
            background-color: #000000 !important;
            color: #ffffff !important;
            border-radius: 20px !important;
            padding: 6px 15px !important;
            margin-right: 5px !important;
            box-shadow: none !important;
        }
        div[data-testid="stPills"] button[aria-selected="true"] {
            background-color: #444444 !important;
            color: #ffffff !important;
            font-weight: 800 !important;
        }
        div[data-testid="stPills"] div[data-baseweb="pill"] {
            border: none !important;
            background: transparent !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # 2. 메뉴 구성
    is_logged_in = st.session_state.get('auth_status') == 'user'
    login_text = "로그아웃" if is_logged_in else "로그인"
    main_text = "메인"
    watch_text = f"관심 ({len(st.session_state.get('watchlist', []))})"
    board_text = "게시판"
    
    menu_options = [login_text, main_text, watch_text, board_text]

    # 3. 현재 페이지에 따른 기본 선택값 설정
    default_sel = None
    if st.session_state.get('page') == 'calendar':
        default_sel = watch_text if st.session_state.get('view_mode') == 'watchlist' else main_text
    elif st.session_state.get('page') == 'board':
        default_sel = board_text
    # main_app(설정) 페이지에서는 선택 안 함(None)

    # 4. 메뉴 출력
    selected_menu = st.pills(
        label="내비게이션",
        options=menu_options,
        selection_mode="single",
        default=default_sel,
        key=f"nav_{st.session_state.get('page')}", 
        label_visibility="collapsed"
    )

    # 5. 이동 로직
    if selected_menu == login_text:
        if is_logged_in:
            st.session_state.clear()
        st.session_state.page = 'login'
        st.rerun()
    elif selected_menu == main_text:
        st.session_state.page = 'calendar' # 캘린더로 이동
        st.session_state.view_mode = 'all'
        st.rerun()
    elif selected_menu == watch_text:
        st.session_state.page = 'calendar'
        st.session_state.view_mode = 'watchlist'
        st.rerun()
    elif selected_menu == board_text:
        st.session_state.page = 'board'
        st.rerun()
    
    st.write("") # 하단 여백
    
# ==========================================
# [화면] UI 제어 로직 (로그인 / 회원가입 / 구경하기 분할)
# ==========================================
# --- [세션 상태 초기화] ---
# 변수가 없어서 발생하는 AttributeError를 방지하기 위해 모든 필수 변수를 등록합니다.

if 'page' not in st.session_state:
    st.session_state.page = 'login'

if 'login_step' not in st.session_state:
    st.session_state.login_step = 'choice'

if 'signup_stage' not in st.session_state:
    st.session_state.signup_stage = 1

if 'auth_status' not in st.session_state:
    st.session_state.auth_status = None

if 'user_info' not in st.session_state:
    st.session_state.user_info = {}

# 👈 [추가됨] 에러 방지를 위한 핵심 변수
if 'watchlist' not in st.session_state:
    st.session_state.watchlist = []

if 'view_mode' not in st.session_state:
    st.session_state.view_mode = 'all'

# --- [UI 시작] ---
if st.session_state.page == 'login':
    st.markdown("<h1 style='text-align: center;'>🦄 Unicorn Finder</h1>", unsafe_allow_html=True)
    st.write("<br>", unsafe_allow_html=True)

    # [Step 1] 선택 화면
    if st.session_state.login_step == 'choice':
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔑 로그인", use_container_width=True, type="primary"):
                st.session_state.login_step = 'login_input'
                st.rerun()
        with col2:
            if st.button("📝 신규 회원가입", use_container_width=True):
                st.session_state.login_step = 'signup_input'
                st.session_state.signup_stage = 1
                st.rerun()
        
        st.write("<br>", unsafe_allow_html=True)
        st.divider()
        # [수정됨] 구경하기 -> 캘린더 페이지로 바로 이동
        if st.button("👀 로그인 없이 구경하기", use_container_width=True):
            st.session_state.auth_status = 'guest'
            st.session_state.user_info = {'id': 'Guest', 'role': 'guest'}
            st.session_state.page = 'calendar' # 여기가 바뀜!
            st.rerun()

    # [Step 2] 로그인 입력창
    elif st.session_state.login_step == 'login_input':
        st.subheader("로그인")
        l_id = st.text_input("아이디", key="login_id")
        l_pw = st.text_input("비밀번호", type="password", key="login_pw")
        
        c1, c2 = st.columns(2)
        with c1:
            if st.button("접속하기", use_container_width=True, type="primary"):
                with st.spinner("회원 정보 확인 중..."):
                    users = load_users()
                    user = next((u for u in users if str(u.get("id")) == l_id), None)
                    if user and str(user['pw']) == l_pw:
                        st.session_state.auth_status = 'user'
                        st.session_state.user_info = user
                        st.session_state.page = 'main_app'
                        st.rerun()
                    else:
                        st.error("아이디 또는 비밀번호가 틀립니다.")
        with c2:
            if st.button("뒤로 가기", use_container_width=True):
                st.session_state.login_step = 'choice'
                st.rerun()

    # [Step 3] 회원가입 로직 (1, 2, 3단계 통합 수정본)
    elif st.session_state.login_step == 'signup_input':
        
        # -----------------------------------------------------
        # [3-1단계] 정보 입력 및 인증 번호 발송
        # -----------------------------------------------------
        if st.session_state.signup_stage == 1:
            st.subheader("1단계: 정보 입력")
            with st.form("signup_1"):
                new_id = st.text_input("아이디")
                new_pw = st.text_input("비밀번호", type="password")
                new_phone = st.text_input("연락처 (예: 010-1234-5678)")
                new_email = st.text_input("이메일")
                auth_choice = st.radio("인증 수단", ["휴대폰(가상)", "이메일(실제)"], horizontal=True)
                
                if st.form_submit_button("인증번호 받기"):
                    # 필수 입력값 체크
                    if not (new_id and new_pw and new_email):
                        st.error("모든 정보를 입력해주세요.")
                    else:
                        code = str(random.randint(100000, 999999))
                        st.session_state.auth_code = code
                        # 다음 단계를 위해 임시 저장
                        st.session_state.temp_user_data = {
                            "id": new_id, "pw": new_pw, 
                            "phone": new_phone, "email": new_email
                        }
                        
                        if "이메일" in auth_choice:
                            # 함수 호출 (import 문제 해결됨)
                            send_email_code(new_email, code)
                        else:
                            st.toast(f"📱 [테스트용] 인증번호: {code}", icon="✅")
                        
                        # 단계 이동 및 리런
                        st.session_state.signup_stage = 2
                        st.rerun()

        # -----------------------------------------------------
        # [3-2단계] 인증 번호 확인
        # -----------------------------------------------------
        elif st.session_state.signup_stage == 2:
            st.subheader("2단계: 인증 확인")
            st.info(f"입력하신 {st.session_state.temp_user_data.get('email', '이메일')}로 번호를 보냈습니다.")
            
            in_code = st.text_input("인증번호 6자리 입력")
            
            c1, c2 = st.columns(2)
            with c1:
                if st.button("확인", use_container_width=True, type="primary"):
                    if in_code == st.session_state.auth_code:
                        st.success("인증 성공!")
                        st.session_state.signup_stage = 3
                        st.rerun()
                    else:
                        st.error("인증번호가 일치하지 않습니다.")
            with c2:
                if st.button("뒤로 가기", use_container_width=True):
                    st.session_state.signup_stage = 1
                    st.rerun()

        # -----------------------------------------------------
        # [3-3단계] 서류 제출 (대학, 직장, 자산)
        # -----------------------------------------------------
        elif st.session_state.signup_stage == 3:
            st.subheader("3단계: 선택적 자격 증빙")
            st.info("💡 서류를 하나라도 제출하면 '글쓰기/투표' 권한이 신청됩니다. (미제출 시 '관심종목' 기능만 사용 가능)")
            
            with st.form("signup_3"):
                u_name = st.text_input("출신 대학 (선택)")
                u_file = st.file_uploader("🎓 학생증/졸업증명서", type=['jpg','png','pdf'])
                
                j_name = st.text_input("직장/직업 (선택)")
                j_file = st.file_uploader("💼 명함/재직증명서", type=['jpg','png','pdf'])
                
                a_val = st.selectbox("자산 규모 (선택)", ["선택 안 함", "10억 미만", "10억~30억", "30억~80억", "80억 이상"])
                a_file = st.file_uploader("💰 잔고증명서", type=['jpg','png','pdf'])
                
                if st.form_submit_button("가입 신청 완료"):
                    with st.spinner("서류 업로드 및 회원가입 처리 중..."):
                        td = st.session_state.temp_user_data
                        
                        # 1. 파일 업로드 실행
                        l_u = upload_photo_to_drive(u_file, f"{td['id']}_univ") if u_file else "미제출"
                        l_j = upload_photo_to_drive(j_file, f"{td['id']}_job") if j_file else "미제출"
                        l_a = upload_photo_to_drive(a_file, f"{td['id']}_asset") if a_file else "미제출"
                        
                        # 2. 권한 및 승인 상태 판별 (수정된 로직)
                        has_cert = any([u_file, j_file, a_file])
                        
                        if has_cert:
                            # 서류를 하나라도 냈으면 -> 'Full 회원' 후보 -> 관리자 승인 필수 (pending)
                            role = "user"
                            status = "pending" 
                        else:
                            # 서류를 안 냈으면 -> 'Basic 회원' -> 즉시 활동 가능하지만 기능 제한
                            role = "restricted"
                            status = "approved" 
                        
                        final_data = {
                            **td, "univ": u_name, "job": j_name, 
                            "asset": a_val if a_val != "선택 안 함" else "",
                            "link_univ": l_u, "link_job": l_j, "link_asset": l_a,
                            "role": role, "status": status,
                            "display_name": f"{role} | {td['id'][:3]}***"
                        }
                        
                        # 3. 구글 시트 저장 및 이동
                        if save_user_to_sheets(final_data):
                            # [중요] 세션 상태를 먼저 확실하게 박아줍니다.
                            st.session_state.auth_status = 'user'
                            st.session_state.user_info = final_data
                            st.session_state.page = 'main_app'
                            
                            # 토스트 메시지
                            if role == "user":
                                st.success("✅ 신청 완료! 관리자 승인 대기 상태로 시작합니다.")
                            else:
                                st.success("✅ 가입 완료! 익명(Basic) 모드로 시작합니다.")
                            
                            # [핵심] sleep 없이 즉시 rerun을 시도하거나, 
                            # 만약 rerun이 안 먹힐 경우를 대비해 버튼을 하나 둡니다.
                            
                            time.sleep(0.5) # 대기 시간을 줄입니다.
                            st.rerun()

# [수정됨] 메인 앱 (설정 페이지) - 타이틀 제거, 네비게이션 적용
elif st.session_state.page == 'main_app':
    render_navbar() # 👈 네비게이션 바 실행
    
    user = st.session_state.user_info
    # st.title("🦄 Unicorn Finder") <- 제거됨
    if user:
        # [기본 정보]
        user_id = str(user.get('id', ''))
        masked_id = "*" * len(user_id)
        
        # -----------------------------------------------------------
        # 1. 내 정보 노출 설정 (체크박스)
        # -----------------------------------------------------------
        st.divider()
        st.subheader("⚙️ 내 정보 노출 및 권한 설정")
        st.caption("하나 이상의 정보를 노출해야 '글쓰기/투표' 권한이 활성화됩니다.")

        # 저장된 설정값 불러오기 (없으면 True가 기본)
        saved_vis = user.get('visibility', 'True,True,True').split(',')
        def_univ = saved_vis[0] == 'True' if len(saved_vis) > 0 else True
        def_job = saved_vis[1] == 'True' if len(saved_vis) > 1 else True
        def_asset = saved_vis[2] == 'True' if len(saved_vis) > 2 else True

        c1, c2, c3 = st.columns(3)
        show_univ = c1.checkbox("🎓 대학 정보", value=def_univ)
        show_job = c2.checkbox("💼 직업 정보", value=def_job)
        show_asset = c3.checkbox("💰 자산 등급", value=def_asset)

        # -----------------------------------------------------------
        # 2. [핵심] 실시간 권한 및 닉네임 시뮬레이션
        # -----------------------------------------------------------
        # (1) 노출 여부 판단: 하나라도 체크했는가?
        is_public_mode = any([show_univ, show_job, show_asset])
        
        # (2) 닉네임 조합
        info_parts = []
        if show_univ: info_parts.append(user.get('univ', ''))
        if show_job: info_parts.append(user.get('job_title', '')) # 혹은 'job'
        if show_asset: info_parts.append(get_asset_grade(user.get('asset', '')))
        
        prefix = " ".join([p for p in info_parts if p])
        final_nickname = f"{prefix} {masked_id}" if prefix else masked_id

        # (3) 현재 나의 상태 판단 (실제 DB 권한 vs 노출 설정)
        db_role = user.get('role', 'restricted')
        db_status = user.get('status', 'pending')
        
        st.divider()
        c_info, c_status = st.columns([2, 1])
        
        with c_info:
            st.write(f"👤 **아이디**: {masked_id}")
            st.markdown(f"📛 **활동 닉네임**: <span style='font-size:1.1em; font-weight:bold; color:#5c6bc0;'>{final_nickname}</span>", unsafe_allow_html=True)
        
        with c_status:
            # 상태 메시지 로직
            if db_role == 'restricted':
                st.error("🔒 **Basic 회원** (서류 미제출)")
                st.caption("권한: 관심종목 O / 글쓰기 X")
            elif db_status == 'pending':
                st.warning("⏳ **승인 대기 중**")
                st.caption("관리자 승인 후 글쓰기 가능")
            elif db_status == 'approved':
                # 승인된 회원이지만, 노출을 다 껐을 경우
                if is_public_mode:
                    st.success("✅ **인증 회원 (활동 중)**")
                    st.caption("권한: 모든 기능 사용 가능")
                else:
                    st.info("aaa **익명 모드 (비공개)**")
                    st.caption("모든 정보를 가려 **글쓰기가 제한**됩니다.")

        # -----------------------------------------------------------
        # 3. 설정 저장 버튼
        # -----------------------------------------------------------
        if st.button("설정 저장 및 적용", type="primary", use_container_width=True):
            with st.spinner("프로필 업데이트 중..."):
                current_settings = [show_univ, show_job, show_asset]
                
                # 구글 시트에 업데이트
                if update_user_visibility(user.get('id'), current_settings):
                    # [중요] 세션 정보도 즉시 업데이트해야 다른 페이지(캘린더 등)에서 반영됨
                    st.session_state.user_info['visibility'] = ",".join([str(v) for v in current_settings])
                    
                    # 익명 모드로 저장하면, 세션 상의 권한을 잠시 낮추는 효과를 줄 수도 있음 (선택사항)
                    # 여기서는 visibility 값을 저장하는 것에 집중
                    
                    st.toast("✅ 설정이 저장되었습니다!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("저장 실패. 네트워크를 확인하세요.")

    # --- 로그아웃 및 네비게이션 ---
    st.divider()
    if st.button("로그아웃"):
        st.session_state.clear()
        st.rerun()
    # ==========================================
    # 📍 여기(6번과 7번 사이)에 추가됩니다!
    # ==========================================
    if user.get('role') == 'admin':
        st.divider()
        st.subheader("🛠️ 관리자 전용: 가입 승인 관리")
        
        # 승인 처리 함수 정의
        def approve_user_status(user_id_to_approve):
            client, _ = get_gcp_clients()
            if client:
                try:
                    sh = client.open("unicorn_users").sheet1
                    cell = sh.find(str(user_id_to_approve), in_column=1)
                    if cell:
                        sh.update_cell(cell.row, 6, "approved") # 6번째 열이 status
                        return True
                except Exception as e:
                    st.error(f"승인 오류: {e}")
            return False

        if st.button("🔄 승인 대기 목록 불러오기"):
            all_users = load_users()
            pending_users = [u for u in all_users if u.get('status') == 'pending']
            
            if not pending_users:
                st.info("현재 승인 대기 중인 유저가 없습니다.")
            else:
                for pu in pending_users:
                    with st.expander(f"📝 신청자: {pu.get('id')} ({pu.get('univ') or '대학미기재'})"):
                        st.write(f"**이메일**: {pu.get('email')} | **연락처**: {pu.get('phone')}")
                        
                        # 증빙 링크 버튼
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            if pu.get('link_univ') != "미제출": st.link_button("🎓 대학 증빙", pu.get('link_univ'))
                        with c2:
                            if pu.get('link_job') != "미제출": st.link_button("💼 직업 증빙", pu.get('link_job'))
                        with c3:
                            if pu.get('link_asset') != "미제출": st.link_button("💰 자산 증빙", pu.get('link_asset'))
                        
                        st.divider()

                        # --- [관리자 승인/보류 섹션] ---
                        # 1. 보류 사유 입력 칸
                        rej_reason = st.text_input("보류 사유 (메일 발송용)", placeholder="예: 서류가 흐릿합니다. 다시 업로드해주세요.", key=f"rej_input_{pu.get('id')}")
                        
                        col_btn1, col_btn2 = st.columns(2)
                        
                        with col_btn1:
                            # [승인 버튼]
                            if st.button(f"✅ {pu.get('id')} 승인하기", key=f"admin_app_{pu.get('id')}"):
                                with st.spinner("승인 처리 중..."):
                                    if approve_user_status(pu.get('id')):
                                        target_email = pu.get('email')
                                        if target_email:
                                            send_approval_email(target_email, pu.get('id'))
                                            st.success("승인 및 알림 발송 완료!")
                                        st.rerun()

                        with col_btn2:
                            # [보류 버튼]
                            if st.button(f"❌ {pu.get('id')} 보류하기", key=f"admin_rej_{pu.get('id')}"):
                                if not rej_reason:
                                    st.warning("보류 사유를 입력해야 메일을 보낼 수 있습니다.")
                                else:
                                    with st.spinner("보류 알림 발송 중..."):
                                        target_email = pu.get('email')
                                        if target_email:
                                            # 보류 메일 발송
                                            if send_rejection_email(target_email, pu.get('id'), rej_reason):
                                                st.info(f"알림 발송 완료. 해당 유저는 시트에서 수동으로 관리하거나 삭제할 수 있습니다.")
                                            else:
                                                st.error("메일 발송 실패")
                                        else:
                                            st.warning("이메일 정보가 없습니다.")
                                    
                                    # 4. 목록 갱신을 위해 재실행
                                    st.rerun()
                                    
    # --- 7. 멤버 리스트 (타인 노출 설정 반영 버전) ---
    st.divider()
    st.subheader("👥 유니콘 멤버 리스트")
    
    if st.button("멤버 목록 불러오기", use_container_width=True):
        with st.spinner("최신 멤버 정보를 동기화 중..."):
            all_users = load_users()
            
            if not all_users:
                st.info("아직 가입된 멤버가 없습니다.")
            else:
                # 목록 출력 시작
                for u in all_users:
                    # 1. 자기 자신은 목록에서 제외
                    if str(u.get('id')) == str(user.get('id')):
                        continue
                    
                    # 2. 아이디 전체 마스킹
                    target_id = str(u.get('id', ''))
                    m_id = "*" * len(target_id)
                    
                    # 3. 해당 유저의 노출 설정(15열) 해석
                    raw_vis = u.get('visibility', 'True,True,True')
                    if not raw_vis: raw_vis = 'True,True,True'
                    
                    vis_parts = str(raw_vis).split(',')
                    v_univ = vis_parts[0] == 'True' if len(vis_parts) > 0 else True
                    v_job = vis_parts[1] == 'True' if len(vis_parts) > 1 else True
                    v_asset = vis_parts[2] == 'True' if len(vis_parts) > 2 else True
                    
                    # 4. 상대방 설정에 따른 실시간 닉네임 조합
                    u_info_parts = []
                    if v_univ: 
                        u_info_parts.append(u.get('univ', ''))
                    if v_job: 
                        # 요청하신대로 job_title을 사용합니다.
                        u_info_parts.append(u.get('job_title', ''))
                    if v_asset: 
                        u_tier = get_asset_grade(u.get('asset', ''))
                        u_info_parts.append(u_tier)
                    
                    u_prefix = " ".join([p for p in u_info_parts if p])
                    
                    # 최종 닉네임 (아이디와 공백 없이 결합)
                    u_display = f"{u_prefix}{m_id}" if u_prefix else m_id
                    
                    # 5. 멤버 카드 디자인
                    with st.expander(f"✨ {u_display}"):
                        c1, c2 = st.columns(2)
                        with c1:
                            st.write(f"🎓 **대학**: {u.get('univ') if v_univ else '(비공개)'}")
                            st.write(f"💼 **직업**: {u.get('job_title') if v_job else '(비공개)'}")
                        with c2:
                            current_tier = get_asset_grade(u.get('asset', ''))
                            st.write(f"💰 **등급**: {current_tier if v_asset else '(비공개)'}")
                            st.write(f"✅ **상태**: {u.get('status', 'pending')}")

# ==========================================
# [추가됨] 캘린더 & 게시판 페이지 (빈 껍데기)
# ==========================================
# 3. 캘린더 페이지 (메인 통합: 상단 메뉴 + 리스트)
elif st.session_state.page == 'calendar':
    # [CSS] 스타일 정의 (기존 스타일 100% 유지 + 상단 메뉴 스타일 추가)
    st.markdown("""
        <style>
        /* 1. 기본 설정 */
        * { box-sizing: border-box !important; }
        body { color: #333333; }
        
        /* 2. 상단 여백 확보 (메인 페이지라 여백을 조금 줄임) */
        .block-container { 
            padding-top: 2rem !important; 
            padding-left: 0.5rem !important; 
            padding-right: 0.5rem !important; 
            max-width: 100% !important; 
        }

        /* [NEW] 상단 메뉴 버튼 스타일 (둥글고 크게) */
        div[data-testid="column"] button {
            border-radius: 12px !important;
            height: 50px !important;
            font-weight: bold !important;
        }

        /* 3. 버튼 스타일 (리스트용 타이트한 스타일) */
        .stButton button {
            background-color: transparent !important;
            border: none !important;
            padding: 0 !important;
            margin: 0 !important;
            color: #333 !important;
            text-align: left !important;
            box-shadow: none !important;
            width: 100% !important;
            display: block !important;
            overflow: hidden !important;
            white-space: nowrap !important;
            text-overflow: ellipsis !important;
            height: auto !important;
            line-height: 1.1 !important;
        }
        .stButton button p { font-weight: bold; font-size: 14px; margin-bottom: 0px; }

        /* 4. [모바일 레이아웃 핵심] */
        @media (max-width: 640px) {
            
            /* (A) 상단 필터: 줄바꿈 허용 */
            div[data-testid="stHorizontalBlock"]:nth-of-type(1) {
                flex-wrap: wrap !important;
                gap: 10px !important;
                padding-bottom: 5px !important;
            }
            div[data-testid="stHorizontalBlock"]:nth-of-type(1) > div {
                min-width: 100% !important;
                max-width: 100% !important;
                flex: 1 1 100% !important;
            }

            /* (B) 리스트 구역: 가로 고정 & 수직 중앙 정렬 */
            div[data-testid="stHorizontalBlock"]:not(:nth-of-type(1)) {
                flex-direction: row !important;
                flex-wrap: nowrap !important;
                gap: 0px !important;
                width: 100% !important;
                align-items: center !important; 
            }

            /* (C) 컬럼 내부 정렬 강제 */
            div[data-testid="column"] {
                display: flex !important;
                flex-direction: column !important;
                justify-content: center !important; 
                min-width: 0px !important;
                padding: 0px 2px !important;
            }

            /* (D) 리스트 컬럼 비율 (7:3) */
            div[data-testid="stHorizontalBlock"]:not(:nth-of-type(1)) > div[data-testid="column"]:nth-of-type(1) {
                flex: 0 0 70% !important;
                max-width: 70% !important;
                overflow: hidden !important;
            }
            div[data-testid="stHorizontalBlock"]:not(:nth-of-type(1)) > div[data-testid="column"]:nth-of-type(2) {
                flex: 0 0 30% !important;
                max-width: 30% !important;
            }

            /* (E) 폰트 및 간격 미세 조정 */
            .mobile-sub { font-size: 10px !important; color: #888 !important; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: -2px; line-height: 1.1; }
            .price-main { font-size: 13px !important; font-weight: bold; white-space: nowrap; line-height: 1.1; }
            .price-sub { font-size: 10px !important; color: #666 !important; white-space: nowrap; line-height: 1.1; }
            .date-text { font-size: 10px !important; color: #888 !important; margin-top: 1px; line-height: 1.1; }
            .header-text { font-size: 12px !important; line-height: 1.0; }
        }
        </style>
    """, unsafe_allow_html=True)

    # ---------------------------------------------------------
    # [ANDROID-FIX] 안드로이드 셀렉트박스 닫힘 강제 패치
    # ---------------------------------------------------------
    st.markdown("""
        <style>
        /* 1. 선택 후 파란색 테두리(포커스) 제거 */
        .stSelectbox div[data-baseweb="select"]:focus-within {
            border-color: transparent !important;
            box-shadow: none !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # 2. 자바스크립트를 이용해 현재 활성화된(Focus) 입력창을 강제로 닫음
    # 화면이 로드될 때마다 실행되어 모바일 키보드나 드롭다운을 숨깁니다.
    st.components.v1.html("""
        <script>
            var mainDoc = window.parent.document;
            var activeEl = mainDoc.activeElement;
            if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.getAttribute('role') === 'combobox')) {
                activeEl.blur();
            }
        </script>
    """, height=0)
     

    # ---------------------------------------------------------
    # 1. [STYLE] 블랙 배경 + 화이트 글씨 (테두리 없음)
    # ---------------------------------------------------------
    st.markdown("""
        <style>
        /* 기본 버튼: 검정 배경 / 흰 글씨 */
        div[data-testid="stPills"] div[role="radiogroup"] button {
            border: none !important;
            outline: none !important;
            background-color: #000000 !important;
            color: #ffffff !important;
            border-radius: 20px !important;
            padding: 6px 15px !important;
            margin-right: 5px !important;
            box-shadow: none !important;
        }

        /* 선택된 버튼: 진한 회색 배경 (구분용) */
        div[data-testid="stPills"] button[aria-selected="true"] {
            background-color: #444444 !important;
            color: #ffffff !important;
            font-weight: 800 !important;
        }

        /* 스트림릿 기본 테두리 제거 */
        div[data-testid="stPills"] div[data-baseweb="pill"] {
            border: none !important;
            background: transparent !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # ---------------------------------------------------------
    # 2. 메뉴 텍스트 및 현재 상태 정의 (명칭 및 순서 변경)
    # ---------------------------------------------------------
    is_logged_in = st.session_state.auth_status == 'user'
    login_text = "로그아웃" if is_logged_in else "로그인"
    main_text = "메인"  # '홈'에서 '메인'으로 변경
    watch_text = f"관심 ({len(st.session_state.watchlist)})"
    board_text = "게시판"
    
    # 순서 조정: 로그인 -> 메인 -> 관심 -> 게시판
    menu_options = [login_text, main_text, watch_text, board_text]

    # 현재 어떤 페이지에 있는지 계산하여 기본 선택값(Default) 설정
    default_sel = main_text
    if st.session_state.get('page') == 'login': 
        default_sel = login_text
    elif st.session_state.get('view_mode') == 'watchlist': 
        default_sel = watch_text
    elif st.session_state.get('page') == 'board': 
        default_sel = board_text

    # ---------------------------------------------------------
    # 3. 메뉴 표시 (st.pills)
    # ---------------------------------------------------------
    selected_menu = st.pills(
        label="내비게이션",
        options=menu_options,
        selection_mode="single",
        default=default_sel,
        key="top_nav_pills_v10", # 키값 갱신
        label_visibility="collapsed"
    )

    # ---------------------------------------------------------
    # 4. 클릭 감지 및 페이지 이동 로직 (보정 완료)
    # ---------------------------------------------------------
    if selected_menu and selected_menu != default_sel:
        if selected_menu == login_text:
            if is_logged_in: 
                st.session_state.auth_status = None # 로그아웃 처리
            st.session_state.page = 'login'
            
        elif selected_menu == main_text:
            st.session_state.view_mode = 'all'
            # 메인 목록 페이지 이름이 'calendar'라면 'calendar'로, 'main'이라면 'main'으로 맞춰주세요.
            st.session_state.page = 'calendar' 
            
        elif selected_menu == watch_text:
            st.session_state.view_mode = 'watchlist'
            st.session_state.page = 'calendar' 
            
        elif selected_menu == board_text:
            st.session_state.page = 'board'
        
        # 설정 변경 후 화면 즉시 갱신
        st.rerun()

    
    # ---------------------------------------------------------
    # [기존 데이터 로직] - 과거 데이터 누락 방지 수정본
    # ---------------------------------------------------------
    all_df_raw = get_extended_ipo_data(MY_API_KEY)
    
    # 데이터 수집 범위 확인
    if not all_df_raw.empty:
        min_date = all_df_raw['date'].min()
        max_date = all_df_raw['date'].max()
        st.sidebar.info(f"📊 수집된 데이터 범위:\n{min_date} ~ {max_date}")
        
    view_mode = st.session_state.get('view_mode', 'all')
    
    if not all_df_raw.empty:
        # 🔥 [수정] exchange가 없어도 삭제하지 않고 '-'로 채워서 유지합니다.
        all_df = all_df_raw.copy()
        all_df['exchange'] = all_df['exchange'].fillna('-')
        
        # 유효한 심볼이 있는 데이터만 유지
        all_df = all_df[all_df['symbol'].astype(str).str.strip() != ""]
        
        # 날짜 형식 통일 (normalize로 시간 제거)
        all_df['공모일_dt'] = pd.to_datetime(all_df['date'], errors='coerce').dt.normalize()
        all_df = all_df.dropna(subset=['공모일_dt'])
        
        today_dt = pd.to_datetime(datetime.now().date())
        
        # 2. 필터 로직
        if view_mode == 'watchlist':
            st.markdown("### ⭐ 내가 찜한 유니콘")
            if st.button("🔄 전체 목록 보기", use_container_width=True):
                st.session_state.view_mode = 'all'
                st.rerun()
                
            display_df = all_df[all_df['symbol'].isin(st.session_state.watchlist)]
            
            if display_df.empty:
                st.info("아직 관심 종목에 담은 기업이 없습니다.")
        else:
            # 일반 캘린더 모드
            col_f1, col_f2 = st.columns([1, 1]) 
            with col_f1:
                period = st.selectbox(
                    label="조회 기간", 
                    options=["상장 예정 (30일)", "지난 6개월", "지난 12개월", "지난 18개월"],
                    key="filter_period",
                    label_visibility="collapsed"
                )
            with col_f2:
                sort_option = st.selectbox(
                    label="정렬 순서", 
                    options=["최신순", "수익률"],
                    key="filter_sort",
                    label_visibility="collapsed"
                )
            
            # [수정본] 기간별 데이터 필터링 로직
            if period == "상장 예정 (30일)":
                # 오늘 포함 미래 30일까지 (공모가 미확정 종목 포함 가능성 대비)
                display_df = all_df[(all_df['공모일_dt'] >= today_dt) & (all_df['공모일_dt'] <= today_dt + timedelta(days=30))]
            else:
                # '지난 X개월' 선택 시: 오늘 이전(과거) 데이터 중 해당 기간 내 것만 필터링
                if period == "지난 6개월":
                    start_date = today_dt - timedelta(days=180)
                elif period == "지난 12개월":
                    start_date = today_dt - timedelta(days=365)
                elif period == "지난 18개월":
                    start_date = today_dt - timedelta(days=540)
                
                # 🔥 핵심 수정: 오늘(today_dt)을 기준으로 '과거' 데이터 전체를 긁어오도록 범위 명확화
                display_df = all_df[(all_df['공모일_dt'] < today_dt) & (all_df['공모일_dt'] >= start_date)]

                # [추가 검증] 만약 6개월 데이터가 여전히 부족하다면?
                # API가 반환하는 전체 데이터셋(all_df_raw)에 해당 날짜가 있는지 확인하는 디버깅용 메시지
                if display_df.empty and not all_df_raw.empty:
                    st.sidebar.warning(f"⚠️ {period} 범위에 해당하는 데이터가 API 응답에 없습니다.")

        # [정렬 로직]
        if 'live_price' not in display_df.columns:
            display_df['live_price'] = 0.0

        if not display_df.empty:
            if sort_option == "최신순": 
                display_df = display_df.sort_values(by='공모일_dt', ascending=False)
                
            elif sort_option == "수익률":
                with st.spinner("🔄 실시간 시세 조회 중..."):
                    returns = []
                    prices = []
                    for idx, row in display_df.iterrows():
                        try:
                            p_raw = str(row.get('price','0')).replace('$','').split('-')[0]
                            p_ipo = float(p_raw) if p_raw else 0
                            p_curr = get_current_stock_price(row['symbol'], MY_API_KEY)
                            
                            if p_ipo > 0 and p_curr > 0:
                                ret = ((p_curr - p_ipo) / p_ipo) * 100
                            else:
                                ret = -9999
                        except: 
                            ret = -9999
                            p_curr = 0
                        returns.append(ret)
                        prices.append(p_curr)
                    
                    display_df['temp_return'] = returns
                    display_df['live_price'] = prices
                    display_df = display_df.sort_values(by='temp_return', ascending=False)

        # ----------------------------------------------------------------
        # [핵심] 리스트 레이아웃 (7 : 3 비율) - 기존 디자인 유지
        # ----------------------------------------------------------------
        if not display_df.empty:
            for i, row in display_df.iterrows():
                p_val = pd.to_numeric(str(row.get('price','')).replace('$','').split('-')[0], errors='coerce')
                p_val = p_val if p_val and p_val > 0 else 0
                
                # 가격 HTML
                live_p = row.get('live_price', 0)
                if live_p > 0:
                    pct = ((live_p - p_val) / p_val) * 100 if p_val > 0 else 0
                    if pct > 0:
                        change_color = "#e61919" 
                        arrow = "▲"
                    elif pct < 0:
                        change_color = "#1919e6" 
                        arrow = "▼"
                    else:
                        change_color = "#333333" 
                        arrow = ""

                    price_html = f"""
                        <div class='price-main' style='color:{change_color} !important;'>
                            ${live_p:,.2f} ({arrow}{pct:+.1f}%)
                        </div>
                        <div class='price-sub' style='color:#666666 !important;'>IPO: ${p_val:,.2f}</div>
                    """
                else:
                    price_html = f"""
                        <div class='price-main' style='color:#333333 !important;'>${p_val:,.2f}</div>
                        <div class='price-sub' style='color:#666666 !important;'>공모가</div>
                    """
                
                date_html = f"<div class='date-text'>{row['date']}</div>"

                c1, c2 = st.columns([7, 3])
                
                with c1:
                    # 기업명 버튼
                    if st.button(f"{row['name']}", key=f"btn_list_{i}"):
                        st.session_state.selected_stock = row.to_dict()
                        st.session_state.page = 'detail'
                        st.rerun()
                    
                    try: s_val = int(row.get('numberOfShares',0)) * p_val / 1000000
                    except: s_val = 0
                    size_str = f" | ${s_val:,.0f}M" if s_val > 0 else ""
                    
                    st.markdown(f"<div class='mobile-sub' style='margin-top:-2px; padding-left:2px;'>{row['symbol']} | {row.get('exchange','-')}{size_str}</div>", unsafe_allow_html=True)

                with c2:
                    st.markdown(f"<div style='text-align:right;'>{price_html}{date_html}</div>", unsafe_allow_html=True)
                
                st.markdown("<div style='border-bottom:1px solid #f0f2f6; margin: 4px 0;'></div>", unsafe_allow_html=True)

        else:
            st.info("조건에 맞는 종목이 없습니다.")

        

# 5. 상세 페이지 (이동 로직 보정 + 디자인 + NameError 방지 통합본)
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    
    # [1] 변수 초기화
    profile = None
    fin_data = None
    current_p = 0
    off_val = 0

    if stock:
        # -------------------------------------------------------------------------
        # [2] 상단 메뉴바 (블랙 스타일 & 이동 로직 보정)
        # -------------------------------------------------------------------------
        st.markdown("""
            <style>
            div[data-testid="stPills"] div[role="radiogroup"] button {
                border: none !important;
                background-color: #000000 !important;
                color: #ffffff !important;
                border-radius: 20px !important;
                padding: 6px 15px !important;
                margin-right: 5px !important;
                box-shadow: none !important;
            }
            div[data-testid="stPills"] button[aria-selected="true"] {
                background-color: #444444 !important;
                font-weight: 800 !important;
            }
            </style>
        """, unsafe_allow_html=True)

        is_logged_in = st.session_state.auth_status == 'user'
        login_text = "로그아웃" if is_logged_in else "로그인"
        main_text = "메인"
        watch_text = f"관심 ({len(st.session_state.watchlist)})"
        board_text = "게시판"
        
        menu_options = [login_text, main_text, watch_text, board_text]
        
        # 상세 페이지에서는 선택된 메뉴가 없도록 index를 None에 가깝게 유지하거나 새로운 키 사용
        selected_menu = st.pills(
            label="nav", 
            options=menu_options, 
            selection_mode="single", 
            key="detail_nav_final_v7", 
            label_visibility="collapsed"
        )

        if selected_menu:
            if selected_menu == login_text:
                if is_logged_in: st.session_state.auth_status = None
                st.session_state.page = 'login'
            
            elif selected_menu == main_text:
                st.session_state.view_mode = 'all'
                # [중요] 하얀 화면 방지: 메인 목록 페이지 이름이 'calendar'라면 여기를 'calendar'로 유지
                st.session_state.page = 'calendar' 
            
            elif selected_menu == watch_text:
                st.session_state.view_mode = 'watchlist'
                st.session_state.page = 'calendar' # 위와 동일하게 설정
            
            elif selected_menu == board_text:
                st.session_state.page = 'board'
            
            st.rerun()


        # -------------------------------------------------------------------------
        # [3] 사용자 판단 로직 (함수 정의)
        # -------------------------------------------------------------------------
        if 'user_decisions' not in st.session_state:
            st.session_state.user_decisions = {}
        
        sid = stock['symbol']
        if sid not in st.session_state.user_decisions:
            st.session_state.user_decisions[sid] = {"news": None, "filing": None, "macro": None, "company": None}

        def draw_decision_box(step_key, title, options):
            st.write("---")
            st.markdown(f"##### {title}")
            current_val = st.session_state.user_decisions[sid].get(step_key)
            choice = st.radio(
                label=f"판단_{step_key}",
                options=options,
                index=options.index(current_val) if current_val in options else None,
                key=f"dec_{sid}_{step_key}",
                horizontal=True,
                label_visibility="collapsed"
            )
            if choice:
                st.session_state.user_decisions[sid][step_key] = choice

        # -------------------------------------------------------------------------
        # [4] 데이터 로딩 및 헤더 구성 (폰트 크기 최적화 버전)
        # -------------------------------------------------------------------------
        today = datetime.now().date()
        try: 
            ipo_dt = stock['공모일_dt'].date() if hasattr(stock['공모일_dt'], 'date') else pd.to_datetime(stock['공모일_dt']).date()
        except: 
            ipo_dt = today
        
        status_emoji = "🐣" if ipo_dt > (today - timedelta(days=365)) else "🦄"
        date_str = ipo_dt.strftime('%Y-%m-%d')

        with st.spinner(f"🤖 {stock['name']} 분석 중..."):
            try: off_val = float(str(stock.get('price', '0')).replace('$', '').split('-')[0].strip())
            except: off_val = 0
            try:
                current_p = get_current_stock_price(stock['symbol'], MY_API_KEY)
                profile = get_company_profile(stock['symbol'], MY_API_KEY) 
                fin_data = get_financial_metrics(stock['symbol'], MY_API_KEY)
            except: pass

        # 수익률 계산 및 HTML 구성 (오타 수정 버전)
        if current_p > 0 and off_val > 0:
            pct = ((current_p - off_val) / off_val) * 100
            color = "#00ff41" if pct >= 0 else "#ff4b4b"
            icon = "▲" if pct >= 0 else "▼"
            # 폰트 크기를 탭 메뉴와 맞추기 위해 스타일 조정
            p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / 공모 ${off_val} / 현재 ${current_p} <span style='color:{color}; font-weight:bold;'>{icon} {abs(pct):.1f}%</span>)</span>"
        else:
            # 여기 시작 부분에 f" 를 정확히 넣었습니다.
            p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / 공모 ${off_val} / 상장 대기)</span>"

        # 기업명 출력 (h3 급 크기로 줄여서 탭 메뉴와 조화롭게 변경)
        st.markdown(f"""
            <div style='margin-bottom: -10px;'>
                <span style='font-size: 1.2rem; font-weight: 700;'>{status_emoji} {stock['name']}</span> 
                {p_info}
            </div>
        """, unsafe_allow_html=True)
        
        st.write("") # 미세 여백

        # -------------------------------------------------------------------------
        # [CSS 추가] 탭 텍스트 색상 검정색으로 강제 고정 (모바일 가독성 해결)
        # -------------------------------------------------------------------------
        st.markdown("""
        <style>
            /* 1. 탭 버튼 내부의 텍스트 색상 지정 */
            .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
                color: #333333 !important; /* 검은색 강제 적용 */
                font-weight: bold !important; /* 굵게 표시 */
            }
            
            /* 2. 탭 마우스 오버 시 색상 (선택 사항) */
            .stTabs [data-baseweb="tab-list"] button:hover [data-testid="stMarkdownContainer"] p {
                color: #004e92 !important; /* 마우스 올렸을 때 파란색 */
            }
        </style>
        """, unsafe_allow_html=True)
