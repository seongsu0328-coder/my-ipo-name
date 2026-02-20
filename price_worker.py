import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import pytz
import time
import sys

# [1] 환경 설정
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip('/')
if "/rest/v1" in SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.split("/rest/v1")[0]
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ 에러: 환경변수 누락"); sys.exit(1)

# [2] DB 전송 함수 (어제 성공했던 Header 방식)
def batch_upsert_raw(table_name, data_list, on_conflict="ticker"):
    if not data_list: return False
    endpoint = f"{SUPABASE_URL}/rest/v1/{table_name}?on_conflict={on_conflict}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal,resolution=merge-duplicates"
    }
    try:
        resp = requests.post(endpoint, json=data_list, headers=headers, timeout=20)
        return resp.status_code in [200, 201, 204]
    except:
        return False

def fetch_and_update_prices():
    # 🚨 불필요한 표준 에러 출력을 차단하여 로그 폭발 방지
    sys.stderr = open(os.devnull, 'w')
    
    print(f"🚀 워커 가동 (KST: {datetime.now(pytz.timezone('Asia/Seoul')).strftime('%H:%M')})", flush=True)
    
    try:
        get_url = f"{SUPABASE_URL}/rest/v1/stock_cache?select=symbol"
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        resp = requests.get(get_url, headers=get_headers if 'get_headers' in locals() else headers, timeout=15)
        tickers = [item['symbol'] for item in resp.json()]
    except:
        print("❌ 티커 로드 실패"); return

    if not tickers: return
    print(f"📦 대상: {len(tickers)}개 주가 다운로드 중...", flush=True)

    # 🚨 threads=False와 progress=False로 가장 조용하고 안전하게 실행
    data = yf.download(tickers, period="1d", group_by='ticker', threads=False, progress=False)
    
    now_iso = datetime.now(pytz.timezone('Asia/Seoul')).isoformat()
    upsert_list = []
    
    for symbol in tickers:
        try:
            target = data[symbol] if len(tickers) > 1 else data
            if 'Close' in target:
                valid = target['Close'].dropna()
                if not valid.empty and float(valid.iloc[-1]) > 0:
                    upsert_list.append({
                        "ticker": str(symbol),
                        "price": float(valid.iloc[-1]),
                        "updated_at": now_iso
                    })
        except: continue

    # 🚨 표준 에러 복구
    sys.stderr = sys.__stderr__

    if upsert_list:
        print(f"📊 {len(upsert_list)}개 데이터 DB 전송 시작...", flush=True)
        chunk_size = 50
        for i in range(0, len(upsert_list), chunk_size):
            chunk = upsert_list[i : i + chunk_size]
            if batch_upsert_raw("price_cache", chunk, on_conflict="ticker"):
                print(f"  -> {min(i+chunk_size, len(upsert_list))}개 성공", flush=True)
            time.sleep(0.8)

        batch_upsert_raw("analysis_cache", [{"cache_key": "WORKER_LAST_RUN", "content": "alive", "updated_at": now_iso}], on_conflict="cache_key")
        print(f"✅ 워커 작업 완료", flush=True)
    else:
        print("⚠️ 업데이트할 가격 데이터가 없습니다.")

if __name__ == "__main__":
    fetch_and_update_prices()
