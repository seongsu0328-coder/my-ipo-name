import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import pytz 

# [1] 환경 설정 및 디버깅 로그
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip('/')
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ 에러: 환경변수 누락"); exit(1)

def sanitize_value(v):
    if v is None or pd.isna(v): return 0.0
    try: return float(v)
    except: return 0.0

def single_upsert(table_name, payload):
    """단일 데이터를 즉시 전송 (메모리 보호)"""
    endpoint = f"{SUPABASE_URL}/rest/v1/{table_name}?on_conflict=ticker"
    if "analysis_cache" in table_name: endpoint = f"{SUPABASE_URL}/rest/v1/{table_name}?on_conflict=cache_key"
    
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
    try:
        requests.post(endpoint, json=[payload], headers=headers, timeout=10)
    except: pass

def fetch_and_update_prices():
    print(f"🚀 실시간 주가 스트리밍 시작", flush=True)
    
    # 1. 티커 목록 가져오기
    try:
        get_url = f"{SUPABASE_URL}/rest/v1/stock_cache?select=symbol"
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        resp = requests.get(get_url, headers=headers, timeout=15)
        tickers = [item['symbol'] for item in resp.json()]
    except Exception as e:
        print(f"❌ 목록 로드 실패: {e}"); return

    if not tickers: return

    # 2. 다운로드 (threads=False로 메모리 부하 원천 차단)
    print(f"📦 대상: {len(tickers)}개 다운로드 중...", flush=True)
    data = yf.download(tickers, period="1d", group_by='ticker', threads=False, progress=False)

    now_iso = datetime.now(pytz.timezone('Asia/Seoul')).isoformat()
    success_count = 0

    # 3. 🚨 스트리밍 업로드 (하나씩 즉시 전송)
    for symbol in tickers:
        try:
            target = data[symbol] if len(tickers) > 1 else data
            if 'Close' in target:
                valid = target['Close'].dropna()
                if not valid.empty:
                    last_p = sanitize_value(valid.iloc[-1])
                    if last_p > 0:
                        # 즉시 DB 전송
                        single_upsert("price_cache", {
                            "ticker": str(symbol),
                            "price": last_p,
                            "updated_at": now_iso
                        })
                        success_count += 1
                        if success_count % 10 == 0:
                            print(f"  -> {success_count}개 완료...", flush=True)
        except: continue

    # 4. 생존 신고
    single_upsert("analysis_cache", {
        "cache_key": "WORKER_LAST_RUN",
        "content": "alive",
        "updated_at": now_iso
    })
    
    print(f"✅ 최종 완료: {success_count}개 업데이트 성공", flush=True)

if __name__ == "__main__":
    fetch_and_update_prices()
