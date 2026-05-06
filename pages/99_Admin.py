import streamlit as st
import pandas as pd
from utils.db_helper import get_worker_health, supabase
from datetime import datetime

st.set_page_config(page_title="UF Admin Center", layout="wide")

# [1] 세션 상태에서 로그인 유저 정보 가져오기
user_info = st.session_state.get('user_info')

# [2] 관리자 권한 실시간 검증 함수
def check_admin_permission():
    if not user_info or not user_info.get('id'):
        return False
    
    try:
        # DB에서 해당 유저의 role을 다시 한 번 확인 (보안 강화)
        res = supabase.table("users").select("role").eq("id", user_info['id']).execute()
        if res.data and res.data[0].get('role') == 'admin':
            return True
    except Exception as e:
        print(f"Admin check error: {e}")
    return False

# [3] 권한 체크 후 화면 렌더링
if check_admin_permission():
    st.title("🛡️ Unicornfinder System Control")
    st.write(f"Welcome, Admin **{user_info['id']}**")
    
    # --- Section 1: Backend Health ---
    st.subheader("⚙️ Worker Monitoring")
    last_run = get_worker_health()
    
    if last_run:
        diff = datetime.now() - last_run.replace(tzinfo=None)
        status_color = "green" if diff.total_seconds() < 3600 else "red"
        st.markdown(f"**Last Heartbeat:** <span style='color:{status_color};'>{last_run.strftime('%Y-%m-%d %H:%M:%S')}</span> ({int(diff.total_seconds() // 60)} min ago)", unsafe_allow_html=True)
    else:
        st.error("Worker signal missing from Database.")

    st.divider()

    # --- Section 2: Real-time Alert Log ---
    st.subheader("📡 Recent Alerts (Last 50)")
    res_alerts = supabase.table("premium_alerts").select("*").order("created_at", desc=True).limit(50).execute()
    if res_alerts.data:
        df_log = pd.DataFrame(res_alerts.data)
        st.dataframe(df_log[['created_at', 'ticker', 'alert_type', 'title']], use_container_width=True)
    else:
        st.info("No alerts generated today yet.")

    st.divider()

    # --- Section 3: User Approval Center ---
    st.subheader("👤 User Verification Request")
    
    res_users = supabase.table("users").select("*").eq("status", "pending").order("created_at", desc=True).execute()
    
    if res_users.data:
        for user in res_users.data:
            with st.expander(f"REQ: {user['id']} | {user.get('display_name', 'No Name')}"):
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"**Email:** {user['email']}")
                    st.write(f"**Job/Univ:** {user.get('job', 'N/A')} / {user.get('univ', 'N/A')}")
                    st.write(f"**Assets:** {user.get('asset', 'N/A')}")
                with c2:
                    if user.get('link_job') and user['link_job'] != "미제출":
                        st.link_button("View Job Proof", user['link_job'])
                    if user.get('link_asset') and user['link_asset'] != "미제출":
                        st.link_button("View Asset Proof", user['link_asset'])
                
                btn_app, btn_rej = st.columns(2)
                if btn_app.button("✅ Approve", key=f"app_{user['id']}", use_container_width=True):
                    supabase.table("users").update({"status": "approved", "role": "user"}).eq("id", user['id']).execute()
                    st.success(f"User {user['id']} approved!")
                    st.rerun()
                if btn_rej.button("❌ Reject", key=f"rej_{user['id']}", use_container_width=True):
                    supabase.table("users").update({"status": "rejected"}).eq("id", user['id']).execute()
                    st.warning(f"User {user['id']} rejected.")
                    st.rerun()
    else:
        st.write("No pending verification requests.")

else:
    # 관리자가 아닐 경우 보여줄 화면
    st.error("🚫 Access Denied")
    st.write("You do not have permission to access this page. Please log in with an Administrator account.")
    
    if not user_info:
        if st.button("Go to Login"):
            st.switch_page("app.py")
