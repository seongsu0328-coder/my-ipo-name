import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import random
import smtplib
from email.mime.text import MIMEText

# ==========================================
# [설정] 구글 드라이브 폴더 ID (필수 입력)
# ==========================================
DRIVE_FOLDER_ID = "14_M1_9RMJBcPe1dTkpWfihMwC2-DZlBo"

st.set_page_config(page_title="로그인 테스트", layout="centered")

# ==========================================
# [기능 1] 구글 클라이언트 연결
# ==========================================
@st.cache_resource
def get_gcp_clients():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        # secrets.toml에서 정보 가져오기
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gspread_client = gspread.authorize(creds)
        drive_service = build('drive', 'v3', credentials=creds)
        return gspread_client, drive_service
    except Exception as e:
        st.error(f"구글 연결 실패: secrets 설정을 확인하세요. ({e})")
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

def add_user(data):
    client, _ = get_gcp_clients()
    if client:
        sh = client.open("unicorn_users").sheet1
        row = [
            data['id'], data['pw'], data['email'], data['phone'],
            'user', 'pending',
            data['univ'], data['job'], data['asset'],
            ", ".join(data['interests']),
            datetime.now().strftime("%Y-%m-%d"),
            data['link_univ'], data['link_job'], data['link_asset']
        ]
        sh.append_row(row)

def upload_photo_to_drive(file_obj, filename_prefix):
    if file_obj is None: return "미제출"
    _, drive_service = get_gcp_clients()
    file_metadata = {'name': f"{filename_prefix}_{file_obj.name}", 'parents': [DRIVE_FOLDER_ID]}
    media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
    file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
    return file.get('webViewLink')

# ==========================================
# [기능 2] 실제 인증번호 발송 로직 (수정됨)
# ==========================================
def send_email_code(to_email, code):
    try:
        # 현재 인식된 키 이름('email_address', 'app_password')으로 수정했습니다.
        sender_email = st.secrets["email_address"]
        sender_pw = st.secrets["app_password"]

        subject = "[Unicorn Finder] 본인 인증번호 안내"
        body = f"안녕하세요. 요청하신 인증번호는 [{code}] 입니다."
        
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = to_email

        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(sender_email, sender_pw)
            s.sendmail(sender_email, to_email, msg.as_string())
            
        st.toast(f"📧 {to_email}로 실제 인증 메일을 발송했습니다!", icon="✅")
        return True
    except Exception as e:
        st.error(f"❌ 이메일 전송 중 오류 발생: {e}")
        return False

def send_sms_code(phone, code):
    # SMS는 비용 문제로 가상 모드 유지 (필요 시 Twilio/CoolSMS 등 API 연동 필요)
    st.toast(f"📱 [가상 SMS] {phone} 번호로 인증번호 [{code}]가 도착했습니다!", icon="📩")
    return True

# ==========================================
# [화면] UI 제어 로직
# ==========================================
if 'page' not in st.session_state: st.session_state.page = 'login'
if 'login_step' not in st.session_state: st.session_state.login_step = 'choice'

if 'signup_stage' not in st.session_state: st.session_state.signup_stage = 1
if 'temp_user_data' not in st.session_state: st.session_state.temp_user_data = {}
if 'auth_code' not in st.session_state: st.session_state.auth_code = ""
if 'auth_method' not in st.session_state: st.session_state.auth_method = ""

if st.session_state.page == 'login':
    st.markdown("<h2 style='text-align: center;'>🦄 Unicorn Finder</h2>", unsafe_allow_html=True)

    # ----------------------------------------------------
    # [메인 선택 화면]
    # ----------------------------------------------------
    if st.session_state.login_step == 'choice':
        col1, col2 = st.columns(2)
        if col1.button("🔑 기존 회원 로그인", use_container_width=True, type="primary"):
            st.session_state.login_step = 'login_input'
            st.rerun()
        if col2.button("📝 신규 가입 신청", use_container_width=True):
            st.session_state.login_step = 'signup_input'
            st.session_state.signup_stage = 1 
            st.rerun()

    # ----------------------------------------------------
    # [로그인 화면]
    # ----------------------------------------------------
    elif st.session_state.login_step == 'login_input':
        st.subheader("로그인")
        login_id = st.text_input("아이디")
        login_pw = st.text_input("비밀번호", type="password")
        
        c1, c2 = st.columns(2)
        if c1.button("로그인", use_container_width=True, type="primary"):
            users = load_users()
            user = next((u for u in users if str(u.get("id")) == login_id), None)
            
            if user and str(user['pw']) == login_pw:
                if user['status'] == 'approved' or user['role'] == 'admin':
                    st.session_state.page = 'main_app'
                    st.session_state.user_email = user['email']
                    st.rerun()
                else:
                    st.warning("⏳ 관리자 승인 대기 중입니다. (구글 시트에서 승인 필요)")
            else:
                st.error("아이디 또는 비밀번호가 일치하지 않습니다.")
        if c2.button("뒤로", use_container_width=True):
            st.session_state.login_step = 'choice'
            st.rerun()

    # ----------------------------------------------------
    # [회원가입 흐름 (3단계)]
    # ----------------------------------------------------
    elif st.session_state.login_step == 'signup_input':
        
        # 🟢 [1단계: 기본 정보 입력 및 인증 수단 선택]
        if st.session_state.signup_stage == 1:
            st.subheader("1단계: 기본 정보 입력")
            with st.form("stage1_form"):
                new_id = st.text_input("아이디 (영문/숫자)")
                new_pw = st.text_input("비밀번호", type="password")
                new_phone = st.text_input("연락처 ('-' 제외 숫자만)", placeholder="01012345678")
                new_email = st.text_input("이메일 주소")
                
                st.markdown("---")
                # ✨ 사용자에게 인증 수단 선택권 부여
                auth_choice = st.radio("본인 인증 수단을 선택하세요", ["휴대폰 번호로 인증 (가상)", "이메일로 인증 (실제)"], horizontal=True)
                
                if st.form_submit_button("인증번호 받기", use_container_width=True, type="primary"):
                    if not (new_id and new_pw and new_phone and new_email):
                        st.error("모든 칸을 입력해주세요.")
                    else:
                        users = load_users()
                        if any(str(u.get('id')) == new_id for u in users):
                            st.error("이미 사용 중인 아이디입니다.")
                        else:
                            # 6자리 랜덤 인증번호 1개 생성
                            code = str(random.randint(100000, 999999))
                            st.session_state.auth_code = code
                            
                            is_sent = False
                            
                            # 선택한 수단에 따라 처리
                            if "휴대폰" in auth_choice:
                                st.session_state.auth_method = "phone"
                                is_sent = send_sms_code(new_phone, code)
                            else:
                                st.session_state.auth_method = "email"
                                # 여기서 실제 메일 전송 함수 호출
                                with st.spinner("이메일 전송 중..."):
                                    is_sent = send_email_code(new_email, code)
                            
                            if is_sent:
                                st.session_state.temp_user_data = {
                                    "id": new_id, "pw": new_pw, "phone": new_phone, "email": new_email
                                }
                                st.session_state.signup_stage = 2
                                st.rerun()
            
            if st.button("처음으로"):
                st.session_state.login_step = 'choice'
                st.rerun()

        # 🟢 [2단계: 선택한 수단으로 인증번호 확인]
        elif st.session_state.signup_stage == 2:
            st.subheader("2단계: 본인 인증")
            
            # 선택한 수단에 맞는 텍스트 동적 출력
            method_text = "연락처" if st.session_state.auth_method == "phone" else "이메일"
            icon = "📱" if st.session_state.auth_method == "phone" else "📧"
            
            msg_guide = "**(우측 알림을 확인하세요!)**" if st.session_state.auth_method == "phone" else "**(메일함을 확인하세요!)**"

            st.info(f"선택하신 {method_text}로 발송된 인증번호를 입력해주세요.\n{msg_guide}")
            
            with st.form("stage2_form"):
                input_code = st.text_input(f"{icon} {method_text} 인증번호 6자리")
                
                if st.form_submit_button("인증 완료 및 다음 단계", use_container_width=True, type="primary"):
                    if input_code == st.session_state.auth_code:
                        st.success("본인 인증이 완료되었습니다!")
                        st.session_state.signup_stage = 3
                        st.rerun()
                    else:
                        st.error("인증번호가 일치하지 않습니다. 다시 확인해주세요.")
            
            if st.button("이전 단계로 돌아가기 (다시 받기)"):
                st.session_state.signup_stage = 1
                st.rerun()

        # 🟢 [3단계: 서류 업로드 및 최종 가입]
        elif st.session_state.signup_stage == 3:
            st.subheader("3단계: 자격 증빙 서류 업로드")
            st.caption("정식 회원으로 승인받기 위한 필수 서류입니다.")
            
            with st.form("stage3_form"):
                in_univ = st.text_input("출신 대학/학과")
                file_univ = st.file_uploader("🎓 학생증 업로드", type=['jpg', 'png'])
                
                in_job = st.text_input("직장명")
                file_job = st.file_uploader("💼 명함 업로드", type=['jpg', 'png'])
                
                in_asset = st.selectbox("자산 규모", ["10억 미만", "10억~30억", "30억~80억", "80억 이상"])
                file_asset = st.file_uploader("💰 잔고증명 업로드", type=['jpg', 'png'])
                
                interests = st.multiselect("관심 분야", ["주식", "부동산", "코인", "스타트업", "기타"])
                
                if st.form_submit_button("최종 가입 신청", type="primary", use_container_width=True):
                    if not (in_univ and in_job):
                        st.error("텍스트 칸을 모두 채워주세요.")
                    elif not (file_univ and file_job and file_asset):
                        st.error("3개의 사진 파일을 모두 업로드해야 합니다.")
                    else:
                        with st.spinner("서류를 업로드하고 가입을 마무리하는 중입니다... (약 15초 소요)"):
                            td = st.session_state.temp_user_data
                            
                            l_univ = upload_photo_to_drive(file_univ, f"{td['id']}_univ")
                            l_job = upload_photo_to_drive(file_job, f"{td['id']}_job")
                            l_asset = upload_photo_to_drive(file_asset, f"{td['id']}_asset")
                            
                            final_user_data = {
                                "id": td['id'], "pw": td['pw'], "email": td['email'], "phone": td['phone'],
                                "univ": in_univ, "job": in_job, "asset": in_asset, "interests": interests,
                                "link_univ": l_univ, "link_job": l_job, "link_asset": l_asset
                            }
                            add_user(final_user_data)
                            
                            st.success("✅ 가입 신청이 완료되었습니다! 관리자 승인 후 이용 가능합니다.")
                            
                            st.session_state.signup_stage = 1
                            st.session_state.temp_user_data = {}
                            st.session_state.login_step = 'choice'
                            
            if st.button("가입 취소 (처음으로)"):
                st.session_state.signup_stage = 1
                st.session_state.temp_user_data = {}
                st.session_state.login_step = 'choice'
                st.rerun()

# ==========================================
# [가상 메인 앱]
# ==========================================
elif st.session_state.page == 'main_app':
    st.balloons()
    st.success(f"🎉 환영합니다, {st.session_state.user_email} 계정님! 성공적으로 로그인되었습니다.")
    if st.button("로그아웃"):
        st.session_state.page = 'login'
        st.session_state.login_step = 'choice'
        st.rerun()
