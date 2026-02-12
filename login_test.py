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
    st.title("🦄 Unicorn Finder")

    if user:
        # --- 1. 아이디 전체 마스킹 ---
        user_id = str(user.get('id', ''))
        masked_id = "*" * len(user_id)
        
        # --- 2. 내 정보 노출 설정 ---
        st.divider()
        st.subheader("⚙️ 내 정보 노출 설정")
        
        show_univ = st.checkbox("대학 정보 노출", value=True, key="chk_univ")
        show_job = st.checkbox("직업 정보 노출", value=True, key="chk_job")
        show_asset = st.checkbox("자산 등급 노출", value=True, key="chk_asset")

        # --- 3. 실시간 닉네임 조합 로직 (공백 제거 버전) ---
        # 텍스트들만 모으기
        info_parts = []
        if show_univ:
            info_parts.append(user.get('univ', ''))
        if show_job:
            info_parts.append(user.get('job_title', ''))
        if show_asset:
            tier = get_asset_grade(user.get('asset', ''))
            info_parts.append(tier)
            
        # 텍스트들끼리는 공백으로 잇되, 마지막 아이디(***)는 공백 없이 붙임
        prefix = " ".join([p for p in info_parts if p])
        
        # prefix가 있으면 뒤에 바로 아이디를 붙이고, 없으면 아이디만 표시
        if prefix:
            final_nickname = f"{prefix}{masked_id}"
        else:
            final_nickname = masked_id

        # --- 4. 화면 출력 ---
        st.divider()
        st.write(f"👤 접속 중인 아이디: **{masked_id}**")
        st.markdown(f"📛 표시될 닉네임: <span style='font-size:1.2rem; font-weight:bold;'>{final_nickname}</span>", unsafe_allow_html=True)
        
        st.write(f"💼 상세 직업명: **{user.get('job_title', '정보 없음')}**")

    # --- 5. 상태 메시지 및 관리 ---
    if user.get('role') == 'restricted':
        st.error("🚫 인증된 정보가 없어 일부 기능이 제한됩니다.")
    else:
        st.success("✅ 인증 회원입니다. 모든 기능을 이용할 수 있습니다.")

    # [수정된 부분] 설정 저장 버튼 클릭 시 실제 시트 업데이트 수행
    if st.button("설정 저장", type="primary"):
        with st.spinner("시트 업데이트 중..."):
            # 체크박스의 실시간 값(True/False)을 리스트로 묶음
            current_settings = [show_univ, show_job, show_asset]
            
            # 함수 실행
            success = update_user_visibility(user.get('id'), current_settings)
            
            if success:
                st.success("✅ 시트 저장 성공!")
                # 세션 상태도 동기화 (이게 빠지면 화면만 바뀌고 데이터는 옛날 것임)
                st.session_state.user_info['visibility'] = ",".join([str(v) for v in current_settings])
            else:
                st.error("❌ 시트 저장 실패!")

    # --- 6. 로그아웃 버튼 ---
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
