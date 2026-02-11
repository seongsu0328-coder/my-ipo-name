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
        
        # 1. 아이디 익명화 (앞 3글자 제외 나머지 *)
        user_id = data['id']
        masked_id = user_id[:3] + "*" * (len(user_id) - 3) if len(user_id) > 3 else user_id + "***"
        
        # 2. 인증 항목 결합 (대학, 직장, 자산등급)
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
            
        # 최종 표시용 닉네임 (예: 서울대 의사 Silver abc***)
        display_name = " ".join(display_parts + [masked_id])
        
        # 3. 권한 설정 (하나도 인증 안 했으면 restricted)
        role = "user" if auth_count > 0 else "restricted"
        
        row = [
            data['id'], data['pw'], data['email'], data['phone'],
            role, 'pending', # role(글쓰기제한용), status
            data['univ'], data['job'], data['asset'], display_name,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data['link_univ'], data['link_job'], data['link_asset']
        ]
        sh.append_row(row)

def upload_photo_to_drive(file_obj, filename_prefix):
    if file_obj is None: return "미제출"
    try:
        _, drive_service = get_gcp_clients()
        file_obj.seek(0)
        
        file_metadata = {
            'name': f"{filename_prefix}_{file_obj.name}", 
            'parents': [DRIVE_FOLDER_ID]
        }
        
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        
        # supportsAllDrives=True 옵션을 추가하여 서비스 계정의 쿼터 제한을 우회합니다.
        file = drive_service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink',
            supportsAllDrives=True  # 이 부분이 누락되면 연결이 끊길 수 있습니다.
        ).execute()
        
        return file.get('webViewLink')
    except Exception as e:
        st.error(f"📂 업로드 에러 상세: {e}")
        return f"업로드 실패: {e}"
        
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

# ==========================================
# [화면] UI 제어 로직
# ==========================================
if 'page' not in st.session_state: st.session_state.page = 'login'
if 'login_step' not in st.session_state: st.session_state.login_step = 'choice'
if 'signup_stage' not in st.session_state: st.session_state.signup_stage = 1
if 'temp_user_data' not in st.session_state: st.session_state.temp_user_data = {}

if st.session_state.page == 'login':
    st.markdown("<h2 style='text-align: center;'>🦄 Unicorn Finder</h2>", unsafe_allow_html=True)

    if st.session_state.login_step == 'choice':
        col1, col2 = st.columns(2)
        if col1.button("🔑 로그인", use_container_width=True, type="primary"):
            st.session_state.login_step = 'login_input'
            st.rerun()
        if col2.button("📝 신규 가입", use_container_width=True):
            st.session_state.login_step = 'signup_input'
            st.session_state.signup_stage = 1
            st.rerun()

    elif st.session_state.login_step == 'login_input':
        st.subheader("로그인")
        l_id = st.text_input("아이디")
        l_pw = st.text_input("비밀번호", type="password")
        if st.button("로그인 완료", use_container_width=True, type="primary"):
            users = load_users()
            user = next((u for u in users if str(u.get("id")) == l_id), None)
            if user and str(user['pw']) == l_pw:
                if user['status'] == 'approved' or user['role'] == 'admin':
                    st.session_state.page = 'main_app'
                    st.session_state.user_info = user
                    st.rerun()
                else: st.warning("⏳ 승인 대기 중입니다.")
            else: st.error("정보가 일치하지 않습니다.")
        if st.button("뒤로"):
            st.session_state.login_step = 'choice'
            st.rerun()

    elif st.session_state.login_step == 'signup_input':
        if st.session_state.signup_stage == 1:
            st.subheader("1단계: 정보 입력")
            with st.form("signup_1"):
                new_id = st.text_input("아이디")
                new_pw = st.text_input("비밀번호", type="password")
                new_phone = st.text_input("연락처")
                new_email = st.text_input("이메일")
                auth_choice = st.radio("인증 수단", ["휴대폰(가상)", "이메일(실제)"], horizontal=True)
                if st.form_submit_button("인증번호 받기"):
                    code = str(random.randint(100000, 999999))
                    st.session_state.auth_code = code
                    st.session_state.temp_user_data = {"id":new_id, "pw":new_pw, "phone":new_phone, "email":new_email}
                    if "이메일" in auth_choice: send_email_code(new_email, code)
                    else: st.toast(f"📱 인증번호: {code}")
                    st.session_state.signup_stage = 2
                    st.rerun()

        elif st.session_state.signup_stage == 2:
            st.subheader("2단계: 인증 확인")
            in_code = st.text_input("인증번호 입력")
            if st.button("확인"):
                if in_code == st.session_state.auth_code:
                    st.session_state.signup_stage = 3
                    st.rerun()
                else: st.error("번호가 틀렸습니다.")

        elif st.session_state.signup_stage == 3:
            st.subheader("3단계: 선택적 자격 증빙")
            st.info("💡 원하는 항목만 업로드하세요. 인증이 하나도 없으면 글쓰기가 제한됩니다.")
            
            with st.form("signup_3"):
                u_name = st.text_input("출신 대학 (선택)")
                u_file = st.file_uploader("🎓 학생증/졸업증명서", type=['jpg','png'])
                
                j_name = st.text_input("직장/직업 (선택)")
                j_file = st.file_uploader("💼 명함/재직증명서", type=['jpg','png'])
                
                a_val = st.selectbox("자산 규모 (선택)", ["선택 안 함", "10억 미만", "10억~30억", "30억~80억", "80억 이상"])
                a_file = st.file_uploader("💰 잔고증명서", type=['jpg','png'])
                
                if st.form_submit_button("가입 신청 완료"):
                    with st.spinner("처리 중..."):
                        td = st.session_state.temp_user_data
                        # 파일 업로드 (파일이 있을 때만 진행)
                        l_u = upload_photo_to_drive(u_file, f"{td['id']}_univ") if u_file else "미제출"
                        l_j = upload_photo_to_drive(j_file, f"{td['id']}_job") if j_file else "미제출"
                        l_a = upload_photo_to_drive(a_file, f"{td['id']}_asset") if a_file else "미제출"
                        
                        final_data = {
                            **td, "univ": u_name, "job": j_name, 
                            "asset": a_val if a_val != "선택 안 함" else "",
                            "link_univ": l_u, "link_job": l_j, "link_asset": l_a
                        }
                        add_user(final_data)
                        st.success("신청 완료! 관리자 승인 후 이용 가능합니다.")
                        st.session_state.login_step = 'choice'
                        st.rerun()

elif st.session_state.page == 'main_app':
    user = st.session_state.user_info
    st.title("Main App")
    st.write(f"접속 중인 닉네임: **{user['display_name']}**")
    
    if user['role'] == 'restricted':
        st.error("🚫 인증된 정보가 없어 글쓰기 기능이 제한된 계정입니다.")
    else:
        st.success("✅ 인증 회원입니다. 모든 기능을 이용할 수 있습니다.")
        
    if st.button("로그아웃"):
        st.session_state.page = 'login'
        st.rerun()
