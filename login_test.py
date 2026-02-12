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
# 1. 설정 및 구글 드라이브 ID
# ==========================================
DRIVE_FOLDER_ID = "1WwjsnOljLTdjpuxiscRyar9xk1W4hSn2"

st.set_page_config(page_title="Unicorn Finder", layout="centered", page_icon="🦄")

# ==========================================
# 2. 백엔드 기능 (구글, 이메일, 업로드)
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
        except: return []
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
        user_id = data['id']
        masked_id = user_id[:3] + "*" * (len(user_id) - 3) if len(user_id) > 3 else user_id + "***"
        
        display_parts = []
        auth_count = 0
        if data['univ'] and data['link_univ'] != "미제출":
            display_parts.append(data['univ']); auth_count += 1
        if data['job'] and data['link_job'] != "미제출":
            display_parts.append(data['job']); auth_count += 1
        if data['asset'] and data['link_asset'] != "미제출":
            grade = get_asset_grade(data['asset'])
            display_parts.append(grade); auth_count += 1
            
        display_name = " ".join(display_parts + [masked_id])
        role = "user" if auth_count > 0 else "restricted"
        
        row = [
            data['id'], data['pw'], data['email'], data['phone'],
            role, data['status'], 
            data['univ'], data['job'], data['asset'], display_name,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data['link_univ'], data['link_job'], data['link_asset'],
            "True,True,True"
        ]
        sh.append_row(row)
        return True
    return False

def update_user_visibility(user_id, visibility_data):
    client, _ = get_gcp_clients()
    if client:
        try:
            sh = client.open("unicorn_users").sheet1
            cell = sh.find(str(user_id), in_column=1) 
            if cell:
                visibility_str = ",".join([str(v) for v in visibility_data])
                sh.update_cell(cell.row, 15, visibility_str)
                return True
        except Exception as e: st.error(f"시트 통신 오류: {e}")
    return False

def upload_photo_to_drive(file_obj, filename_prefix):
    if file_obj is None: return "미제출"
    try:
        _, drive_service = get_gcp_clients()
        file_obj.seek(0)
        file_metadata = {'name': f"{filename_prefix}_{file_obj.name}", 'parents': [DRIVE_FOLDER_ID]}
        # Broken Pie 방지: 청크 사이즈 5MB로 상향
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type, resumable=True, chunksize=5 * 1024 * 1024)
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        drive_service.permissions().create(fileId=file.get('id'), body={'type': 'anyone', 'role': 'reader'}, supportsAllDrives=True).execute()
        return file.get('webViewLink')
    except Exception as e: 
        print(f"Upload Error: {e}")
        return "업로드 실패"

def send_email_code(to_email, code):
    try:
        sender_email = st.secrets["smtp"]["email_address"]
        sender_pw = st.secrets["smtp"]["app_password"]
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
    except: return False

def send_approval_email(to_email, user_id):
    try:
        sender_email = st.secrets["smtp"]["email_address"]
        sender_pw = st.secrets["smtp"]["app_password"]
        msg = MIMEText(f"안녕하세요, {user_id}님!\nUnicorn Finder 가입이 승인되었습니다.")
        msg['Subject'] = "[Unicorn Finder] 가입 승인 안내"
        msg['From'] = sender_email
        msg['To'] = to_email
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(sender_email, sender_pw)
            s.sendmail(sender_email, to_email, msg.as_string())
        return True
    except: return False

def send_rejection_email(to_email, user_id, reason):
    try:
        sender_email = st.secrets["smtp"]["email_address"]
        sender_pw = st.secrets["smtp"]["app_password"]
        msg = MIMEText(f"안녕하세요, {user_id}님.\n가입 승인이 보류되었습니다.\n사유: {reason}")
        msg['Subject'] = "[Unicorn Finder] 가입 승인 보류 안내"
        msg['From'] = sender_email
        msg['To'] = to_email
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(sender_email, sender_pw)
            s.sendmail(sender_email, to_email, msg.as_string())
        return True
    except: return False

def save_user_to_sheets(user_data):
    return add_user(user_data) 

# ==========================================
# [UI] 블랙 스타일 네비게이션바 (메인, 관심, 게시판)
# ==========================================
def render_navbar():
    # 스타일 정의
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

    is_logged_in = st.session_state.auth_status == 'user'
    login_text = "로그아웃" if is_logged_in else "로그인"
    main_text = "메인"
    watch_text = f"관심 ({len(st.session_state.get('watchlist', []))})"
    board_text = "게시판"
    
    menu_options = [login_text, main_text, watch_text, board_text]
    
    # 기본 선택값 로직
    default_sel = None 
    if st.session_state.page == 'calendar':
        default_sel = watch_text if st.session_state.view_mode == 'watchlist' else main_text
    elif st.session_state.page == 'board':
        default_sel = board_text
        
    selected_menu = st.pills(
        label="내비게이션",
        options=menu_options,
        selection_mode="single",
        default=default_sel,
        key=f"nav_{st.session_state.page}", 
        label_visibility="collapsed"
    )

    # 페이지 이동 로직
    if selected_menu == login_text:
        if is_logged_in: st.session_state.clear()
        st.session_state.page = 'login'
        st.rerun()
    elif selected_menu == main_text:
        st.session_state.page = 'calendar'
        st.session_state.view_mode = 'all'
        st.rerun()
    elif selected_menu == watch_text:
        st.session_state.page = 'calendar'
        st.session_state.view_mode = 'watchlist'
        st.rerun()
    elif selected_menu == board_text:
        st.session_state.page = 'board'
        st.rerun()
    st.write("")

# ==========================================
# [초기화] 세션 상태
# ==========================================
session_keys = {
    'page': 'login', 'login_step': 'choice', 'signup_stage': 1,
    'auth_status': None, 'user_info': {}, 'watchlist': [], 'view_mode': 'all',
    'temp_user_data': {}, 'auth_code': None
}
for k, v in session_keys.items():
    if k not in st.session_state: st.session_state[k] = v

# ==========================================
# [PAGE 1] 로그인 & 회원가입
# ==========================================
if st.session_state.page == 'login':
    st.markdown("<h1 style='text-align: center;'>🦄 Unicorn Finder</h1>", unsafe_allow_html=True)
    st.write("<br>", unsafe_allow_html=True)

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
        if st.button("👀 로그인 없이 구경하기", use_container_width=True):
            st.session_state.auth_status = 'guest'
            st.session_state.user_info = {'id': 'Guest', 'role': 'guest'}
            st.session_state.page = 'calendar' # 구경하기는 바로 캘린더로
            st.rerun()

    elif st.session_state.login_step == 'login_input':
        st.subheader("로그인")
        l_id = st.text_input("아이디", key="lid")
        l_pw = st.text_input("비밀번호", type="password", key="lpw")
        
        c1, c2 = st.columns(2)
        with c1:
            if st.button("접속하기", use_container_width=True, type="primary"):
                with st.spinner("확인 중..."):
                    users = load_users()
                    user = next((u for u in users if str(u.get("id")) == l_id), None)
                    if user and str(user['pw']) == l_pw:
                        st.session_state.auth_status = 'user'
                        st.session_state.user_info = user
                        st.session_state.page = 'main_app'
                        st.rerun()
                    else: st.error("정보 불일치")
        with c2:
            if st.button("뒤로"):
                st.session_state.login_step = 'choice'
                st.rerun()

    elif st.session_state.login_step == 'signup_input':
        # [3-1단계]
        if st.session_state.signup_stage == 1:
            st.subheader("1단계: 정보 입력")
            with st.form("s1"):
                new_id = st.text_input("아이디")
                new_pw = st.text_input("비밀번호", type="password")
                new_phone = st.text_input("연락처")
                new_email = st.text_input("이메일")
                auth_choice = st.radio("인증", ["휴대폰(가상)", "이메일(실제)"], horizontal=True)
                if st.form_submit_button("인증번호 받기"):
                    if not (new_id and new_pw and new_email):
                        st.error("입력 누락")
                    else:
                        code = str(random.randint(100000, 999999))
                        st.session_state.auth_code = code
                        st.session_state.temp_user_data = {"id":new_id, "pw":new_pw, "phone":new_phone, "email":new_email}
                        if "이메일" in auth_choice: send_email_code(new_email, code)
                        else: st.toast(f"인증번호: {code}", icon="✅")
                        st.session_state.signup_stage = 2
                        st.rerun()

        # [3-2단계]
        elif st.session_state.signup_stage == 2:
            st.subheader("2단계: 인증 확인")
            in_code = st.text_input("인증번호 입력")
            c1, c2 = st.columns(2)
            if c1.button("확인", type="primary", use_container_width=True):
                if in_code == st.session_state.auth_code:
                    st.session_state.signup_stage = 3
                    st.rerun()
                else: st.error("불일치")
            if c2.button("뒤로", use_container_width=True):
                st.session_state.signup_stage = 1
                st.rerun()

        # [3-3단계]
        elif st.session_state.signup_stage == 3:
            st.subheader("3단계: 선택적 자격 증빙")
            st.info("💡 서류를 제출하면 '글쓰기' 권한을 신청합니다. (미제출 시 '관심종목'만 가능)")
            with st.form("s3"):
                u_name = st.text_input("출신 대학 (선택)")
                u_file = st.file_uploader("🎓 학생증", type=['jpg','png','pdf'])
                j_name = st.text_input("직장 (선택)")
                j_file = st.file_uploader("💼 명함", type=['jpg','png','pdf'])
                a_val = st.selectbox("자산 규모", ["선택 안 함", "10억 미만", "10억~30억", "30억~80억", "80억 이상"])
                a_file = st.file_uploader("💰 잔고증명", type=['jpg','png','pdf'])
                submitted = st.form_submit_button("가입 신청 완료")

            if submitted:
                with st.spinner("처리 중..."):
                    td = st.session_state.temp_user_data
                    l_u = upload_photo_to_drive(u_file, f"{td['id']}_univ") if u_file else "미제출"
                    l_j = upload_photo_to_drive(j_file, f"{td['id']}_job") if j_file else "미제출"
                    l_a = upload_photo_to_drive(a_file, f"{td['id']}_asset") if a_file else "미제출"
                    
                    has_cert = any([u_file, j_file, a_file])
                    role = "user" if has_cert else "restricted"
                    status = "pending" if has_cert else "approved"
                    
                    final_data = {
                        **td, "univ": u_name, "job": j_name, 
                        "asset": a_val if a_val != "선택 안 함" else "",
                        "link_univ": l_u, "link_job": l_j, "link_asset": l_a,
                        "role": role, "status": status,
                        "display_name": f"{role} | {td['id'][:3]}***"
                    }
                    
                    if save_user_to_sheets(final_data):
                        st.session_state.auth_status = 'user'
                        st.session_state.user_info = final_data
                        st.session_state.page = 'main_app'
                        
                        if role == "user": st.success("신청 완료! (승인 대기)")
                        else: st.success("가입 완료! (Basic 모드)")
                        
                        st.caption("이동하지 않으면 버튼을 누르세요.")
                        if st.button("🚀 입장하기"): st.rerun()
                        time.sleep(1); st.rerun()

# ==========================================
# [PAGE 2] 메인 앱 (설정 & 회원관리) - [수정됨]
# ==========================================
elif st.session_state.page == 'main_app':
    render_navbar() # 👈 네비게이션 바 적용
    
    user = st.session_state.user_info
    # (타이틀 제거됨)

    if user:
        user_id = str(user.get('id', ''))
        masked_id = "*" * len(user_id)
        
        # 1. 노출 설정
        st.subheader("⚙️ 내 정보 노출 및 권한 설정")
        st.caption("하나 이상의 정보를 노출해야 '글쓰기/투표' 권한이 활성화됩니다.")
        
        vis = str(user.get('visibility', 'True,True,True')).split(',')
        v_u = vis[0] == 'True' if len(vis) > 0 else True
        v_j = vis[1] == 'True' if len(vis) > 1 else True
        v_a = vis[2] == 'True' if len(vis) > 2 else True
        
        c1, c2, c3 = st.columns(3)
        show_univ = c1.checkbox("🎓 대학 정보", value=v_u)
        show_job = c2.checkbox("💼 직업 정보", value=v_j)
        show_asset = c3.checkbox("💰 자산 등급", value=v_a)
        
        # 2. 상태 표시
        is_public = any([show_univ, show_job, show_asset])
        info_parts = []
        if show_univ: info_parts.append(user.get('univ', ''))
        if show_job: info_parts.append(user.get('job', '') or user.get('job_title', ''))
        if show_asset: info_parts.append(get_asset_grade(user.get('asset', '')))
        
        prefix = " ".join([p for p in info_parts if p])
        final_nick = f"{prefix} {masked_id}" if prefix else masked_id
        
        st.divider()
        c_info, c_stat = st.columns([2,1])
        c_info.markdown(f"**닉네임 미리보기**: `{final_nick}`")
        
        role, status = user.get('role'), user.get('status')
        if role == 'restricted': c_stat.error("🔒 Basic (미인증)")
        elif status == 'pending': c_stat.warning("⏳ 승인 대기")
        elif status == 'approved' and is_public: c_stat.success("✅ 인증 회원")
        else: c_stat.info("🔒 익명 모드")

        if st.button("설정 저장", type="primary", use_container_width=True):
            if update_user_visibility(user['id'], [show_univ, show_job, show_asset]):
                st.session_state.user_info['visibility'] = f"{show_univ},{show_job},{show_asset}"
                st.toast("✅ 저장 완료!")
                time.sleep(0.5); st.rerun()
            else: st.error("저장 실패")

    # 3. [복구됨] 멤버 리스트 섹션
    st.divider()
    st.subheader("👥 유니콘 멤버 리스트")
    
    if st.button("멤버 목록 불러오기", use_container_width=True):
        with st.spinner("로딩 중..."):
            all_users = load_users()
            if not all_users:
                st.info("멤버가 없습니다.")
            else:
                for u in all_users:
                    if str(u.get('id')) == str(user.get('id')): continue
                    
                    # 상대방 정보 마스킹 및 노출 확인
                    raw_vis = u.get('visibility', 'True,True,True')
                    if not raw_vis: raw_vis = 'True,True,True'
                    vis_parts = str(raw_vis).split(',')
                    
                    v_univ = vis_parts[0] == 'True' if len(vis_parts) > 0 else True
                    v_job = vis_parts[1] == 'True' if len(vis_parts) > 1 else True
                    v_asset = vis_parts[2] == 'True' if len(vis_parts) > 2 else True
                    
                    u_info = []
                    if v_univ: u_info.append(u.get('univ', ''))
                    if v_job: u_info.append(u.get('job', '') or u.get('job_title', ''))
                    if v_asset: u_info.append(get_asset_grade(u.get('asset', '')))
                    
                    u_prefix = " ".join([p for p in u_info if p])
                    target_id = str(u.get('id', ''))
                    m_id = "*" * len(target_id)
                    u_display = f"{u_prefix}{m_id}" if u_prefix else m_id
                    
                    with st.expander(f"✨ {u_display}"):
                        c1, c2 = st.columns(2)
                        with c1:
                            st.write(f"🎓 {u.get('univ') if v_univ else '(비공개)'}")
                            st.write(f"💼 {u.get('job_title') if v_job else '(비공개)'}")
                        with c2:
                            tier = get_asset_grade(u.get('asset', ''))
                            st.write(f"💰 {tier if v_asset else '(비공개)'}")
                            st.write(f"✅ {u.get('status', 'pending')}")

    # 4. 관리자 승인 메뉴 (하단)
    if user.get('role') == 'admin':
        st.divider()
        st.subheader("🛠️ 관리자 승인")
        if st.button("새로고침"):
            all_u = load_users()
            pendings = [u for u in all_u if u.get('status') == 'pending']
            if not pendings: st.info("대기 없음")
            for p in pendings:
                with st.expander(f"신청: {p['id']}"):
                    st.write(f"Email: {p['email']}")
                    c1, c2, c3 = st.columns(3)
                    if p['link_univ'] != "미제출": c1.link_button("대학", p['link_univ'])
                    if p['link_job'] != "미제출": c2.link_button("직업", p['link_job'])
                    if p['link_asset'] != "미제출": c3.link_button("자산", p['link_asset'])
                    
                    if st.button(f"승인 {p['id']}", key=f"ok_{p['id']}"):
                        cl, _ = get_gcp_clients()
                        sh = cl.open("unicorn_users").sheet1
                        cell = sh.find(str(p['id']), in_column=1)
                        sh.update_cell(cell.row, 6, "approved")
                        send_approval_email(p['email'], p['id'])
                        st.success("승인 완료"); st.rerun()

# ==========================================
# [PAGE 3] 캘린더 (추후 통합)
# ==========================================
elif st.session_state.page == 'calendar':
    render_navbar()
    st.title("📅 IPO Calendar")
    st.info("여기에 원형 서버의 캘린더 코드가 들어갑니다.")

# ==========================================
# [PAGE 4] 게시판
# ==========================================
elif st.session_state.page == 'board':
    render_navbar()
    st.title("💬 통합 게시판")
    st.info("준비 중입니다.")
