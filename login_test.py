import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import random
import smtplib
import time
from email.mime.text import MIMEText

# ==========================================
# [설정] 구글 드라이브 폴더 ID (필수 입력)
# ==========================================
DRIVE_FOLDER_ID = "1WwjsnOljLTdjpuxiscRyar9xk1W4hSn2"

st.set_page_config(page_title="Unicorn Finder", layout="centered")

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
    action: 'view' (조회), 'watchlist' (관심등록), 'write' (글쓰기/투표)
    유저 상태에 따라 실행 가능 여부를 True/False로 반환합니다.
    """
    auth_status = st.session_state.get('auth_status') # 'user', 'guest', None
    user_info = st.session_state.get('user_info', {})
    user_role = user_info.get('role', 'restricted') # 'user', 'restricted', 'admin'
    user_status = user_info.get('status', 'pending') # 'approved', 'pending'

    # 1. 단순 조회: 누구나 가능
    if action == 'view':
        return True
    
    # 2. 관심 종목 등록: 로그인한 회원(미인증 포함)만 가능
    if action == 'watchlist':
        return auth_status == 'user'
    
    # 3. 글쓰기 및 투표: 인증 완료된 회원 또는 관리자만 가능
    if action == 'write':
        if auth_status == 'user':
            # 관리자이거나, 일반유저 중 승인이 완료된 경우
            if user_info.get('role') == 'admin' or (user_role == 'user' and user_status == 'approved'):
                return True
        return False
        
    return False

# ==========================================
# [화면] UI 제어 로직 (로그인 / 회원가입 / 구경하기 분할)
# ==========================================
# --- [세션 상태 초기화] ---
# 앱이 처음 실행될 때 필요한 변수들을 미리 만들어둡니다.
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
        # [핵심] 구경하기 버튼: 계정 없이 메인으로 진입
        if st.button("👀 로그인 없이 구경하기", use_container_width=True):
            st.session_state.auth_status = 'guest'
            st.session_state.user_info = {'id': 'Guest', 'role': 'guest'}
            st.session_state.page = 'main_app'
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
                            # 로그인 세션에 정보 심어주기
                            st.session_state.auth_status = 'user'
                            st.session_state.user_info = final_data
                            st.session_state.page = 'main_app'
                            
                            if role == "user":
                                st.toast("✅ 신청 완료! 관리자 승인 대기 상태로 시작합니다.")
                            else:
                                st.toast("✅ 가입 완료! 익명(Basic) 모드로 시작합니다.")
                            
                            time.sleep(1)
                            st.rerun()

elif st.session_state.page == 'main_app':
    user = st.session_state.user_info
    st.title("🦄 Unicorn Finder")

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
