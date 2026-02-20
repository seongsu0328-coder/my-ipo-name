import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import pytz
import time
import sys

# ==========================================
# [1] 환경 설정
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip('/')
if "/rest/v1" in SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.split("/rest/v1")[0]
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ 에러: 환경변수 누락"); sys.exit(1)

# ==========================================
# [2] DB 전송 함수 (어제 성공했던 Header 완벽 이식)
# ==========================================
def batch_upsert_raw(table_name, data_list, on_conflict="ticker"):
    if not data_list: return False
    endpoint = f"{SUPABASE_URL}/rest/v1/{table_name}?on_conflict={on_conflict}"
    
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        # 🚨 [가장 중요] 중복 시 에러 내지 말고 덮어쓰라는 명령
        "Prefer": "return=minimal,resolution=merge-duplicates"
    }
    
    try:
        resp = requests.post(endpoint, json=data_list, headers=headers, timeout=20)
        return resp.status_code in [200, 201, 204]
    except Exception as e:
        print(f"❌ 전송 에러: {e}", flush=True)
        return False

# ==========================================
# [3] 핵심 로직: 조용하고 가벼운 주가 업데이트
# ==========================================
def fetch_and_update_prices():
    print(f"🚀 15분 주기 주가 업데이트 시작 (KST: {datetime.now(pytz.timezone('Asia/Seoul')).strftime('%H:%M')})", flush=True)
    
    # 1. 티커 목록 가져오기
    try:
        get_url = f"{SUPABASE_URL}/rest/v1/stock_cache?select=symbol"
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        resp = requests.get(get_url, headers=headers, timeout=15)
        tickers = [item['symbol'] for item in resp.json()]
    except:
        print("❌ 티커 로드 실패", flush=True); return

    if not tickers: return
    print(f"📦 대상: {len(tickers)}개 주가 다운로드 중... (불필요한 에러 로그 숨김 처리됨)", flush=True)

    # 2. 다운로드 (🚨 로그 폭발 방지 및 메모리 최적화)
    original_stderr = sys.stderr
    sys.stderr = open(os.devnull, 'w') # yfinance의 쓸데없는 빨간줄 경고를 휴지통으로 보냄
    
    try:
        # threads=False 로 설정하여 작은 서버에서도 안전하게 동작
        data = yf.download(tickers, period="1d", group_by='ticker', threads=False, progress=False)
    finally:
        sys.stderr.close()
        sys.stderr = original_stderr # 작업이 끝나면 다시 정상 출력 상태로 복구

    now_iso = datetime.now(pytz.timezone('Asia/Seoul')).isoformat()
    upsert_list = []
    
    # 3. 데이터 추출 (가장 최신 가격만)
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

    # 4. 50개 단위 청크 업로드
    if upsert_list:
        print(f"📊 {len(upsert_list)}개 데이터 DB 전송 시작...", flush=True)
        chunk_size = 50
        for i in range(0, len(upsert_list), chunk_size):
            chunk = upsert_list[i : i + chunk_size]
            if batch_upsert_raw("price_cache", chunk, on_conflict="ticker"):
                print(f"  -> {min(i+chunk_size, len(upsert_list))}개 성공", flush=True)
            time.sleep(0.8) # 안전망 (API 제한 회피)

        # 5. 생존 신고 (앱 대시보드 상태 배지용)
        batch_upsert_raw("analysis_cache", [{"cache_key": "WORKER_LAST_RUN", "content": "alive", "updated_at": now_iso}], on_conflict="cache_key")
        print(f"✅ 워커 작업 완벽하게 종료됨", flush=True)
    else:
        print("⚠️ 업데이트할 가격 데이터가 없습니다.", flush=True)

if __name__ == "__main__":
    fetch_and_update_prices()
