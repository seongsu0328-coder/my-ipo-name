import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ==========================================
# [설정] 구글 드라이브 폴더 ID (필수 입력)
# ==========================================
DRIVE_FOLDER_ID = "여기에_구글드라이브_폴더ID를_붙여넣으세요"

# 페이지 설정 (라이트 테마 강제)
st.set_page_config(page_title="로그인 테스트", layout="centered")
st.markdown("""
    <style>
    .stApp { background-color: #ffffff; color: #333333; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# [기능 1] 구글 클라이언트 연결 (시트 + 드라이브)
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
        st.error(f"❌ 구글 연결 실패: {e}\nSecrets 설정을 확인하세요.")
        return None, None

# ==========================================
# [기능 2] 파일 드라이브 업로드 함수
# ==========================================
def upload_photo_to_drive(file_obj, filename_prefix):
    if file_obj is None: return "미제출"
    
    _, drive_service = get_gcp_clients()
    if not drive_service: return "오류"

    try:
        file_metadata = {
            'name': f"{filename_prefix}_{file_obj.name}",
            'parents': [DRIVE_FOLDER_ID]
        }
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        file = drive_service.files().create(
            body=file_metadata, media_body=media, fields='id, webViewLink'
        ).execute()
        return file.get('webViewLink')
    except Exception as e:
        return f"업로드실패: {str(e)}"

# ==========================================
# [기능 3] 유저 데이터 DB(시트) 조작
# ==========================================
def load_users():
    client, _ = get_gcp_clients()
    if client:
        try:
            sh = client.open("unicorn_users").sheet1
            return sh.get_all_records()
        except Exception as e:
            st.error(f"시트 읽기 오류: {e}")
            return []
    return []

def add_user(data):
    client, _ = get_gcp_clients()
    if client:
        sh = client.open("unicorn_users").sheet1
        row = [
            data['id'], data['pw'], data['name'], data['phone'],
            'user', 'pending', # 기본 권한/상태
            data['univ'], data['job'], data['asset'],
            ", ".join(data['interests']),
            datetime.now().strftime("%Y-%m-%d"),
            data['link_univ'], data['link_job'], data['link_asset']
        ]
        sh.append_row(row)

# ==========================================
# [화면] UI 제어 로직
# ==========================================
if 'page' not in st.session_state: st.session_state.page = 'login'
if 'login_step' not in st.session_state: st.session_state.login_step = 'choice'

if st.session_state.page == 'login':
    st.markdown("<h2 style='text-align: center;'>🔐 회원가입 및 승인 테스트</h2>", unsafe_allow_html=True)
    st.write("<br>", unsafe_allow_html=True)

    # [단계 1] 선택 화면
    if st.session_state.login_step == 'choice':
        col1, col2 = st.columns(2)
        if col1.button("🔑 기존 회원 로그인", use_container_width=True, type="primary"):
            st.session_state.login_step = 'login_input'
            st.rerun()
        if col2.button("📝 신규 가입 신청", use_container_width=True):
            st.session_state.login_step = 'signup_input'
            st.rerun()

    # [단계 2] 로그인 처리
    elif st.session_state.login_step == 'login_input':
        st.subheader("로그인")
        login_id = st.text_input("아이디")
        login_pw = st.text_input("비밀번호", type="password")
        
        c1, c2 = st.columns(2)
        if c1.button("로그인", use_container_width=True, type="primary"):
            with st.spinner("구글 시트에서 회원 정보 대조 중..."):
                users = load_users()
                user = next((u for u in users if str(u["id"]) == login_id), None)
                
                if user and str(user['pw']) == login_pw:
                    if user['status'] == 'approved' or user['role'] == 'admin':
                        st.session_state.page = 'main_app' # 성공 시 메인으로
                        st.session_state.user_name = user['name']
                        st.rerun()
                    else:
                        st.warning("⏳ 관리자 승인 대기 중입니다. (구글 시트에서 status를 'approved'로 변경해주세요)")
                else:
                    st.error("아이디 또는 비밀번호가 일치하지 않습니다.")
        
        if c2.button("뒤로", use_container_width=True):
            st.session_state.login_step = 'choice'
            st.rerun()

    # [단계 3] 회원가입 (사진 업로드)
    elif st.session_state.login_step == 'signup_input':
        st.subheader("가입 신청서 및 증빙 서류 업로드")
        
        with st.form("signup_form"):
            st.markdown("**기본 정보**")
            new_id = st.text_input("아이디 (영문/숫자)")
            new_pw = st.text_input("비밀번호", type="password")
            new_name = st.text_input("이름")
            new_phone = st.text_input("연락처")
            
            st.markdown("---")
            st.markdown("**증빙 서류 (3장 모두 필수)**")
            in_univ = st.text_input("출신 대학/학과")
            file_univ = st.file_uploader("🎓 학생증 업로드", type=['jpg', 'png'])
            
            in_job = st.text_input("직장명")
            file_job = st.file_uploader("💼 명함 업로드", type=['jpg', 'png'])
            
            in_asset = st.selectbox("자산 규모", ["10억 미만", "10억~30억", "30억~80억", "80억 이상"])
            file_asset = st.file_uploader("💰 잔고증명 업로드", type=['jpg', 'png'])
            
            interests = st.multiselect("관심 분야", ["주식", "부동산", "코인"])
            
            submit_btn = st.form_submit_button("신청서 제출", type="primary", use_container_width=True)
            
            if submit_btn:
                if not (new_id and new_pw and new_name and in_univ and in_job):
                    st.error("텍스트 칸을 모두 채워주세요.")
                elif not (file_univ and file_job and file_asset):
                    st.error("3개의 사진 파일을 모두 업로드해야 합니다.")
                else:
                    with st.spinner("사진을 구글 드라이브에 올리고 시트에 기록 중입니다... (약 10~20초 소요)"):
                        # 중복 검사
                        users = load_users()
                        if any(str(u['id']) == new_id for u in users):
                            st.error("이미 사용 중인 아이디입니다.")
                        else:
                            # 1. 사진 3장 업로드
                            l_univ = upload_photo_to_drive(file_univ, f"{new_id}_univ")
                            l_job = upload_photo_to_drive(file_job, f"{new_id}_job")
                            l_asset = upload_photo_to_drive(file_asset, f"{new_id}_asset")
                            
                            # 2. 시트에 저장
                            user_data = {
                                "id": new_id, "pw": new_pw, "name": new_name, "phone": new_phone,
                                "univ": in_univ, "job": in_job, "asset": in_asset, "interests": interests,
                                "link_univ": l_univ, "link_job": l_job, "link_asset": l_asset
                            }
                            add_user(user_data)
                            st.success("✅ 제출 완료! 관리자 승인을 기다려주세요.")
                            st.session_state.login_step = 'choice'
        
        if st.button("취소", use_container_width=True):
            st.session_state.login_step = 'choice'
            st.rerun()

# ==========================================
# [가상 메인 앱] 로그인 성공 시 보여질 화면
# ==========================================
elif st.session_state.page == 'main_app':
    st.balloons()
    st.success(f"🎉 환영합니다, {st.session_state.user_name}님! 성공적으로 로그인되었습니다.")
    st.info("이 화면이 보인다면 DB 연동과 승인 시스템이 완벽하게 작동하는 것입니다.")
    
    if st.button("로그아웃"):
        st.session_state.page = 'login'
        st.session_state.login_step = 'choice'
        st.rerun()
