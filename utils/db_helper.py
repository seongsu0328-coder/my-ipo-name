import streamlit as st
import os
import json
import pandas as pd
from supabase import create_client
from datetime import datetime, timedelta

@st.cache_resource
def init_supabase():
    url = os.environ.get("SUPABASE_URL") or st.secrets["supabase"]["url"]
    key = os.environ.get("SUPABASE_KEY") or st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = init_supabase()

def get_daily_signal_counts():
    """오늘 발생한 모든 시그널과 AI 리포트의 개수를 집계합니다."""
    counts = {}
    time_limit = (datetime.now() - timedelta(hours=24)).isoformat()

    try:
        # [1] 주가 시그널 집계
        res_alerts = supabase.table("premium_alerts").select("alert_type").gte("created_at", time_limit).execute()
        for item in res_alerts.data:
            a_type = item['alert_type']
            counts[a_type] = counts.get(a_type, 0) + 1

        # [2] AI 리포트 집계
        res_cache = supabase.table("analysis_cache").select("cache_key").gte("updated_at", time_limit).execute()
        ai_types = {
            "8K_UPDATE": "8K_UPDATE",
            "PremiumEarningsCall": "EarningsCall",
            "PremiumSurprise": "EarningsSurprise",
            "PremiumEstimate": "AnalystEstimates",
            "PremiumESG": "ESGRating",
            "PremiumUpgrades": "Upgrades",
            "PremiumMA": "MAReport",
            "Tab6_SmartMoney": "SmartMoney"
        }
        seen_reports = set() 
        for item in res_cache.data:
            key = item['cache_key']
            for keyword, internal_name in ai_types.items():
                if keyword in key:
                    unique_id = key.split('_v1')[0].split('_Tab6')[0] 
                    if unique_id not in seen_reports:
                        counts[internal_name] = counts.get(internal_name, 0) + 1
                        seen_reports.add(unique_id)
        return counts
    except: return {}

def get_upcoming_ipo_teaser():
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", "IPO_CALENDAR_DATA").execute()
        if res.data:
            df = pd.DataFrame(json.loads(res.data[0]['content']))
            df['dt'] = pd.to_datetime(df['date'], errors='coerce')
            return df[df['dt'] >= datetime.now()].sort_values('dt').head(5)
    except: return pd.DataFrame()

def get_worker_health():
    try:
        res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", "WORKER_LAST_RUN").execute()
        if res.data: return pd.to_datetime(res.data[0]['updated_at'])
    except: return None
