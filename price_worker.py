import os
import json
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import time  
import pytz 
from supabase import create_client

# [1] 환경 설정
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip('/')
# URL 보정
if "/rest/v1" in SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.split("/rest/v1")[0]

SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    print("❌ Supabase 환경변수 누락"); exit()

# [2] 표준 엔진
def sanitize_value(v):
    if v is None or pd.isna(v): return None
    if isinstance(v, (np.floating, float)):
        return float(v) if not (np.isinf(v) or np.isnan(v)) else 0.0
    if isinstance(v, (np.integer, int)): return int(v)
    return str(v).strip().replace('\x00', '')

def batch_upsert(table_name, data_list, on_conflict="ticker"):
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

    if not clean_batch: return False
    
    try:
        # 🚨 [핵심 1] timeout=10 을 추가하여 무한 대기(프리징) 현상 원천 차단!
        resp = requests.post(endpoint, json=clean_batch, headers=headers, timeout=10)
        
        if resp.status_code not in [200, 201, 204]:
            print(f"❌ [{table_name}] 실패 ({resp.status_code}): {resp.text[:200]}", flush=True) 
            return False
        return True
    except Exception as e: 
        print(f"❌ 통신 에러 (Timeout 등): {e}", flush=True)
        return False

# [3] 로직 함수
def get_target_tickers():
    try:
        res = supabase.table("stock_cache").select("symbol").execute()
        return [item['symbol'] for item in res.data] if res.data else []
    except Exception as e:
        print(f"⚠️ 티커 목록 로드 실패: {e}", flush=True)
        return []

def fetch_and_update_prices():
    print(f"🚀 주가 수집 시작 (ET: {datetime.now().strftime('%H:%M')})", flush=True)
    tickers = get_target_tickers()
    if not tickers: 
        print("대상 종목 없음", flush=True); return

    print(f"대상 종목: {len(tickers)}개 -> 다운로드 시작", flush=True)
    
    try:
        # yfinance 에러가 로그를 너무 많이 차지하는 것을 막기 위해 옵션 조정
        data = yf.download(tickers, period="1d", interval="1m", group_by='ticker', threads=True, progress=False)
    except Exception as e:
        print(f"⚠️ 다운로드 중 에러 발생: {e}", flush=True)
        return

    upsert_list = []
    now_iso = datetime.now(pytz.timezone('Asia/Seoul')).isoformat() 
    is_multi = len(tickers) > 1
    
    for symbol in tickers:
        try:
            if is_multi:
                if symbol not in data: continue
                closes = data[symbol]['Close']
            else:
                closes = data['Close']
            
            valid_closes = closes.dropna()
            if valid_closes.empty: continue
            
            last_price = valid_closes.iloc[-1]
            
            if last_price > 0:
                upsert_list.append({"ticker": symbol, "price": float(last_price), "updated_at": now_iso})
        except: continue 
    
    if upsert_list:
        # 🚨 [핵심 2] flush=True 를 넣어 GitHub Actions에서 글씨가 즉시 뜨게 만듦
        print(f"📊 {len(upsert_list)}개 종목 데이터 확보. DB 저장 시도...", flush=True)
        
        chunk_size = 50
        success_count = 0
        
        for i in range(0, len(upsert_list), chunk_size):
            chunk = upsert_list[i : i + chunk_size]
            try:
                is_success = batch_upsert("price_cache", chunk, on_conflict="ticker")
                if is_success:
                    success_count += len(chunk)
                    print(f"  -> {success_count}/{len(upsert_list)}개 저장 완료...", flush=True)
                time.sleep(1.0) # 혹시 모를 서버 부하를 막기 위해 1초 휴식
            except Exception as e:
                print(f"❌ 청크 저장 중 에러: {e}", flush=True)
            
        print("✅ 주가 캐싱 전송 완료!", flush=True)
        
        try:
            heartbeat_payload = [{
                "cache_key": "WORKER_LAST_RUN",
                "content": '{"status": "alive", "worker": "price_worker"}',
                "updated_at": now_iso
            }]
            batch_upsert("analysis_cache", heartbeat_payload, on_conflict="cache_key")
            print(f"📡 메인 앱 생존 신고 완료 (KST): {now_iso}", flush=True)
        except Exception as e:
            print(f"⚠️ 생존 신고 실패: {e}", flush=True)
            
    else:
        print("⚠️ 저장할 데이터가 없습니다.", flush=True)

if __name__ == "__main__":
    fetch_and_update_prices()
