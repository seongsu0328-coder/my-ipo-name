import os
import time
import json
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import pytz 
from supabase import create_client

# [1] 환경 설정
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip('/')
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
if not (SUPABASE_URL and SUPABASE_KEY):
    print("❌ 환경변수 누락"); exit()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# [2] 통합 엔진 (이 부분이 모든 파일에서 똑같아야 합니다)
def sanitize_value(v):
    if v is None or pd.isna(v): return None
    if isinstance(v, (np.floating, float)):
        return float(v) if not (np.isinf(v) or np.isnan(v)) else 0.0
    if isinstance(v, (np.integer, int)): return int(v)
    if isinstance(v, (np.bool_, bool)): return bool(v)
    return str(v).strip().replace('\x00', '')

def batch_upsert(table_name, data_list, on_conflict="ticker"):
    if not data_list: return
    base_url = SUPABASE_URL if "/rest/v1" in SUPABASE_URL else f"{SUPABASE_URL}/rest/v1"
    endpoint = f"{base_url}/{table_name}?on_conflict={on_conflict}"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
               "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}

    clean_batch = []
    for item in data_list:
        payload = {k: sanitize_value(v) for k, v in item.items()}
        if payload.get(on_conflict): clean_batch.append(payload)
    
    if not clean_batch: return
    try:
        # [벌크 전송] 518개를 한 번에 보냅니다.
        resp = requests.post(endpoint, json=clean_batch, headers=headers)
        if resp.status_code in [200, 201, 204]:
            print(f"✅ [{table_name}] {len(clean_batch)}개 저장 성공")
        else:
            print(f"❌ [{table_name}] 실패 ({resp.status_code}): {resp.text[:100]}")
    except Exception as e: print(f"❌ 통신 에러: {e}")

# [3] 실행 로직
def is_market_open():
    print(f"🚀 [강제 실행] 주가 수집 시작")
    return True

def get_target_tickers():
    try:
        res = supabase.table("stock_cache").select("symbol").execute()
        return [item['symbol'] for item in res.data] if res.data else []
    except: return []

def fetch_and_update_prices():
    if not is_market_open(): return 
    tickers = get_target_tickers()
    if not tickers: return

    print(f"대상 종목: {len(tickers)}개 -> yfinance 다운로드")
    try:
        data = yf.download(" ".join(tickers), period="1d", interval="1m", group_by='ticker', threads=True, progress=False)
        upsert_list = []
        now_iso = datetime.now(pytz.timezone('Asia/Seoul')).isoformat() 
        
        for symbol in tickers:
            try:
                closes = data[symbol]['Close'] if len(tickers) > 1 else data['Close']
                last_price = closes.dropna().iloc[-1] if not closes.dropna().empty else 0
                if last_price > 0:
                    upsert_list.append({"ticker": symbol, "price": float(last_price), "updated_at": now_iso})
            except: continue
        
        # 벌크 저장 호출
        batch_upsert("price_cache", upsert_list, on_conflict="ticker")
    except Exception as e: print(f"❌ 실패: {e}")

if __name__ == "__main__":
    fetch_and_update_prices()
