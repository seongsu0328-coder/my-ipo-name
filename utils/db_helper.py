import streamlit as st
import os
import json
import pandas as pd
from supabase import create_client
from datetime import datetime, timedelta, time

@st.cache_resource
def init_supabase():
    url = os.environ.get("SUPABASE_URL") or st.secrets["supabase"]["url"]
    key = os.environ.get("SUPABASE_KEY") or st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = init_supabase()

# 💡 숫자가 너무 자주 바뀌지 않게 10분간 결과를 메모리에 저장(TTL)
@st.cache_data(ttl=600)
def get_daily_signal_counts():
    """오늘 날짜(00:00:00) 이후에 발생한 시그널만 집계하여 일관성을 유지합니다."""
    counts = {}
    
    # [핵심 변경] 슬라이딩 24시간이 아닌, '오늘의 시작' 시간을 구합니다.
    today_start = datetime.combine(datetime.now().date(), time.min).isoformat()

    try:
        # [1] 주가 시그널 집계 (오늘 자정 이후 데이터만)
        res_alerts = supabase.table("premium_alerts").select("alert_type").gte("created_at", today_start).execute()
        for item in res_alerts.data:
            a_type = item['alert_type']
            counts[a_type] = counts.get(a_type, 0) + 1

        # [2] AI 리포트 집계 (오늘 자정 이후 업데이트된 것만)
        res_cache = supabase.table("analysis_cache").select("cache_key").gte("updated_at", today_start).execute()
        
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
                    # 언어(ko, en 등)와 상관없이 '종목+분석종류'가 같으면 하나로 카운트
                    # 예: AAPL_PremiumESG_v1_ko 와 AAPL_PremiumESG_v1_en을 동일 취급
                    base_key = key.rsplit('_', 1)[0] # 마지막 언어 코드 제거
                    if base_key not in seen_reports:
                        counts[internal_name] = counts.get(internal_name, 0) + 1
                        seen_reports.add(base_key)
        
        return counts
    except:
        return {}

def get_upcoming_ipo_teaser():
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", "IPO_CALENDAR_DATA").execute()
        if res.data:
            df = pd.DataFrame(json.loads(res.data[0]['content']))
            df['dt'] = pd.to_datetime(df['date'], errors='coerce')
            # 아직 상장 전이거나 오늘 상장하는 기업 5개
            today = datetime.now().date()
            return df[df['dt'].dt.date >= today].sort_values('dt').head(5)
    except: return pd.DataFrame()

def get_worker_health():
    try:
        res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", "WORKER_LAST_RUN").execute()
        if res.data: return pd.to_datetime(res.data[0]['updated_at'])
    except: return None
