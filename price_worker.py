import os
import json
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import time  
import pytz 

# [1] 환경 설정 및 디버깅 로그
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip('/')
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

print(f"DEBUG: URL 존재 여부 = {bool(SUPABASE_URL)}")
print(f"DEBUG: KEY 존재 여부 = {bool(SUPABASE_KEY)}")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ 에러: Supabase 환경변수가 비어있습니다. GitHub Secrets 설정을 확인하세요.")
    import sys
    sys.exit(1) # 강제 종료하여 로그 남김

def sanitize_value(v):
    if v is None or pd.isna(v): return None
    if isinstance(v, (np.floating, float)):
        return float(v) if not (np.isinf(v) or np.isnan(v)) else 0.0
    if isinstance(v, (np.integer, int)): return int(v)
    return str(v).strip().replace('\x00', '')

def batch_upsert_raw(table_name, data_list, on_conflict="ticker"):
    if not data_list: return False
    endpoint = f"{SUPABASE_URL}/rest/v1/{table_name}?on_conflict={on_conflict}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
    
    clean_batch = []
    for item in data_list:
        payload = {k: sanitize_value(v) for k, v in item.items()}
        if payload.get(on_conflict): clean_batch.append(payload)

    try:
        resp = requests.post(endpoint, json=clean_batch, headers=headers, timeout=20)
        if resp.status_code in [200, 201, 204]:
            return True
        else:
            print(f"❌ DB 전송 실패 ({resp.status_code}): {resp.text}", flush=True)
            return False
    except Exception as e: 
        print(f"❌ 통신 에러: {e}", flush=True)
        return False

def fetch_and_update_prices():
    try:
        print(f"🚀 주가 수집 시작 (KST: {datetime.now(pytz.timezone('Asia/Seoul')).strftime('%H:%M')})", flush=True)
        
        # 티커 목록 가져오기
        get_endpoint = f"{SUPABASE_URL}/rest/v1/stock_cache?select=symbol"
        get_headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        resp = requests.get(get_endpoint, headers=get_headers, timeout=15)
        
        if resp.status_code != 200:
            print(f"❌ 티커 로드 실패: {resp.text}", flush=True); return
            
        tickers = [item['symbol'] for item in resp.json()]
        if not tickers: print("대상 종목 없음", flush=True); return

        print(f"대상 종목: {len(tickers)}개 -> 다운로드 시작", flush=True)
        
        # 다운로드 (threads=False로 설정하여 메모리 안정성 확보)
        data = yf.download(tickers, period="1d", group_by='ticker', threads=False, progress=False)

        upsert_list = []
        now_iso = datetime.now(pytz.timezone('Asia/Seoul')).isoformat() 
        
        for symbol in tickers:
            try:
                target = data[symbol] if len(tickers) > 1 else data
                if 'Close' in target and not target['Close'].dropna().empty:
                    last_price = float(target['Close'].dropna().iloc[-1])
                    if last_price > 0:
                        upsert_list.append({"ticker": str(symbol), "price": last_price, "updated_at": now_iso})
            except: continue 
        
        if upsert_list:
            print(f"📊 {len(upsert_list)}개 종목 데이터 확보. DB 저장 시도...", flush=True)
            chunk_size = 50
            for i in range(0, len(upsert_list), chunk_size):
                chunk = upsert_list[i : i + chunk_size]
                if batch_upsert_raw("price_cache", chunk, on_conflict="ticker"):
                    print(f"  -> {i+len(chunk)}/{len(upsert_list)}개 저장 완료...", flush=True)
                time.sleep(1.0)
            
            # 생존 신고
            batch_upsert_raw("analysis_cache", [{"cache_key": "WORKER_LAST_RUN", "content": "alive", "updated_at": now_iso}], on_conflict="cache_key")
            print(f"📡 워커 완료 보고 성공", flush=True)
        else:
            print("⚠️ 저장할 데이터 없음", flush=True)

    except Exception as e:
        print(f"🚨 최상위 에러 발생: {e}", flush=True)

if __name__ == "__main__":
    fetch_and_update_prices()
