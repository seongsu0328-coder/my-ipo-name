import os
import json
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import time  
import pytz 

# [1] 환경 설정
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip('/')
# URL 보정 (https://xyz.supabase.co 형태여야 함)
if "/rest/v1" in SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.split("/rest/v1")[0]

SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Supabase 환경변수 누락"); exit()

# [2] 데이터 정제 함수
def sanitize_value(v):
    if v is None or pd.isna(v): return None
    if isinstance(v, (np.floating, float)):
        return float(v) if not (np.isinf(v) or np.isnan(v)) else 0.0
    if isinstance(v, (np.integer, int)): return int(v)
    return str(v).strip().replace('\x00', '')

# [3] 🚀 [핵심 수정] 가장 가벼운 requests 방식으로 DB 전송
def batch_upsert_raw(table_name, data_list, on_conflict="ticker"):
    if not data_list: return False
    
    # Supabase REST API 엔드포인트
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
        if payload.get(on_conflict):
            clean_batch.append(payload)

    if not clean_batch: return False
    
    try:
        # 🚨 timeout을 15초로 설정하여 무한 대기 현상 완전 차단
        resp = requests.post(endpoint, json=clean_batch, headers=headers, timeout=15)
        if resp.status_code in [200, 201, 204]:
            return True
        else:
            print(f"❌ DB 전송 실패 ({resp.status_code}): {resp.text[:100]}", flush=True)
            return False
    except Exception as e: 
        print(f"❌ 통신 에러: {e}", flush=True)
        return False

# [4] 티커 목록 가져오기 (requests 방식)
def get_target_tickers():
    endpoint = f"{SUPABASE_URL}/rest/v1/stock_cache?select=symbol"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    try:
        resp = requests.get(endpoint, headers=headers, timeout=10)
        if resp.status_code == 200:
            return [item['symbol'] for item in resp.json()]
        return []
    except:
        return []

def fetch_and_update_prices():
    print(f"🚀 주가 수집 시작 (KST: {datetime.now(pytz.timezone('Asia/Seoul')).strftime('%H:%M')})", flush=True)
    tickers = get_target_tickers()
    if not tickers: 
        print("대상 종목 없음", flush=True); return

    print(f"대상 종목: {len(tickers)}개 -> 다운로드 시작", flush=True)
    
    try:
        # 🚨 interval 삭제 유지
        data = yf.download(tickers, period="1d", group_by='ticker', threads=True, progress=False)
    except Exception as e:
        print(f"⚠️ 다운로드 중 에러 발생: {e}", flush=True); return

    upsert_list = []
    now_iso = datetime.now(pytz.timezone('Asia/Seoul')).isoformat() 
    is_multi = len(tickers) > 1
    
    for symbol in tickers:
        try:
            closes = data[symbol]['Close'] if is_multi else data['Close']
            valid_closes = closes.dropna()
            if not valid_closes.empty and float(valid_closes.iloc[-1]) > 0:
                upsert_list.append({
                    "ticker": str(symbol), 
                    "price": float(valid_closes.iloc[-1]), 
                    "updated_at": now_iso
                })
        except: continue 
    
    if upsert_list:
        print(f"📊 {len(upsert_list)}개 종목 데이터 확보. DB 저장 시도...", flush=True)
        
        chunk_size = 50
        success_count = 0
        
        for i in range(0, len(upsert_list), chunk_size):
            chunk = upsert_list[i : i + chunk_size]
            if batch_upsert_raw("price_cache", chunk, on_conflict="ticker"):
                success_count += len(chunk)
                print(f"  -> {success_count}/{len(upsert_list)}개 저장 완료...", flush=True)
            time.sleep(1.0) # 안전을 위해 1초 휴식
            
        print("✅ 주가 캐싱 전송 완료!", flush=True)
        
        # 📡 메인 앱 생존 신고
        heartbeat = [{
            "cache_key": "WORKER_LAST_RUN",
            "content": "alive",
            "updated_at": now_iso
        }]
        batch_upsert_raw("analysis_cache", heartbeat, on_conflict="cache_key")
        print(f"📡 생존 신고 완료: {now_iso}", flush=True)
            
    else:
        print("⚠️ 저장할 데이터가 없습니다.", flush=True)

if __name__ == "__main__":
    fetch_and_update_prices()
