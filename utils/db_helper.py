import streamlit as st
import os
import json
import pandas as pd
from supabase import create_client
from datetime import datetime, timedelta

@st.cache_resource
def init_supabase():
    # 환경변수에서 가져오거나 st.secrets에서 가져옵니다.
    url = os.environ.get("SUPABASE_URL") or st.secrets["supabase"]["url"]
    key = os.environ.get("SUPABASE_KEY") or st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = init_supabase()

def get_alert_stats():
    try:
        # 최근 24시간 알림 수 집계 (구조에 따라 필터링 가능)
        res = supabase.table("premium_alerts").select("alert_type").execute()
        surge = sum(1 for x in res.data if "SURGE" in str(x.get('alert_type', '')))
        eight_k = sum(1 for x in res.data if "8K" in str(x.get('alert_type', '')))
        return surge, eight_k
    except:
        return 0, 0

def get_upcoming_ipo_teaser():
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", "IPO_CALENDAR_DATA").execute()
        if res.data:
            df = pd.DataFrame(json.loads(res.data[0]['content']))
            df['dt'] = pd.to_datetime(df['date'], errors='coerce')
            today = datetime.now()
            # 상장일이 오늘 이후인 기업 중 5개만 정렬해서 가져오기
            upcoming = df[df['dt'] >= today].sort_values('dt').head(5)
            return upcoming
    except:
        return pd.DataFrame()

def get_worker_health():
    try:
        res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", "WORKER_LAST_RUN").execute()
        if res.data:
            return pd.to_datetime(res.data[0]['updated_at'])
    except:
        return None
