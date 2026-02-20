import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import pytz
import time

# [1] 환경 설정
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip('/')
if "/rest/v1" in SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.split("/rest/v1")[0]
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ 에러: 환경변수 누락"); exit(1)

# [2] 어제 성공했던 방식의 Upsert 함수 (Prefer 헤더 추가)
def batch_upsert_raw(table_name, data_list, on_conflict="ticker"):
    if not data_list: return False
    endpoint = f"{SUPABASE_URL}/rest/v1/{table_name}?on_conflict={on_conflict}"
    
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        # 🚨 [핵심] 어제 성공의 비결: 중복 시 덮어쓰기 허용 헤더
        "Prefer": "return=minimal,resolution=merge-duplicates"
    }
    
    try:
        # 데이터 전송 (50개 단위 청크는 함수 밖에서 처리)
        resp = requests.post(endpoint, json=data_list, headers=headers, timeout=15)
        if resp.status_code in [200, 201, 204]:
            return True
        else:
            print(f"❌ DB 실패 ({resp.status_code}): {resp.text[:100]}", flush=True)
            return False
    except Exception as e:
        print(f"❌ 통신 에러: {e}", flush=True)
        return False

def fetch_and_update_prices():
    print(f"🚀 주가 업데이트 워커 시작", flush=True)
    
    # 1. 티커 목록 가져오기 (requests)
    try:
        get_url = f"{SUPABASE_URL}/rest/v1/stock_cache?select=symbol"
        get_headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        resp = requests.get(get_url, headers=get_headers, timeout=15)
        tickers = [item['symbol'] for item in resp.json()]
    except Exception as e:
        print(f"❌ 목록 로드 실패: {e}"); return

    if not tickers: return
    print(f"📦 대상: {len(tickers)}개 다운로드 중...", flush=True)

    # 2. 다운로드 (안전한 설정)
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

    # 3. 🚨 50개씩 쪼개서 전송 (어제 성공한 batch_upsert 방식 활용)
    if upsert_list:
        print(f"📊 {len(upsert_list)}개 저장 시작...", flush=True)
        chunk_size = 50
        for i in range(0, len(upsert_list), chunk_size):
            chunk = upsert_list[i : i + chunk_size]
            if batch_upsert_raw("price_cache", chunk, on_conflict="ticker"):
                print(f"  -> {min(i+chunk_size, len(upsert_list))}개 완료...", flush=True)
            time.sleep(0.5)

        # 4. 생존 신고 (analysis_cache)
        batch_upsert_raw("analysis_cache", [{
            "cache_key": "WORKER_LAST_RUN",
            "content": "alive",
            "updated_at": now_iso
        }], on_conflict="cache_key")
        
        print(f"✅ 최종 완료: {len(upsert_list)}개 업데이트 성공", flush=True)
    else:
        print("⚠️ 저장할 가격 데이터 없음", flush=True)

if __name__ == "__main__":
    fetch_and_update_prices()
