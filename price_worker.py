import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import pytz
import time
import logging

# 🚨 불필요한 스팸 로그(상장폐지 등)만 살짝 끄고, 진짜 에러는 다 출력되게 설정
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

# [1] 환경 설정
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip('/')
if "/rest/v1" in SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.split("/rest/v1")[0]
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ 에러: 환경변수 누락", flush=True); exit(1)

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
    except Exception as e:
        print(f"❌ DB 전송 에러: {e}", flush=True)
        return False

def fetch_and_update_prices():
    print(f"🚀 15분 주기 주가 업데이트 시작 (KST: {datetime.now(pytz.timezone('Asia/Seoul')).strftime('%H:%M')})", flush=True)
    
    try:
        get_url = f"{SUPABASE_URL}/rest/v1/stock_cache?select=symbol"
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        resp = requests.get(get_url, headers=headers, timeout=15)
        tickers = [item['symbol'] for item in resp.json()]
    except Exception as e:
        print(f"❌ 티커 로드 실패: {e}", flush=True); return

    if not tickers: return
    print(f"📦 대상: {len(tickers)}개 주가 다운로드 시작...", flush=True)

    now_iso = datetime.now(pytz.timezone('Asia/Seoul')).isoformat()
    upsert_list = []
    
    # 🚨 [해결책] 다운로드도 50개 단위로 쪼개서 진행 상태를 중계합니다!
    chunk_size = 50
    for i in range(0, len(tickers), chunk_size):
        chunk_tickers = tickers[i : i + chunk_size]
        print(f"⏳ 야후 파이낸스 다운로드 중... ({i+1} ~ {min(i+chunk_size, len(tickers))}/{len(tickers)})", flush=True)
        
        try:
            # 에러 숨김 없이 정상적으로 데이터 요청
            data = yf.download(chunk_tickers, period="1d", group_by='ticker', threads=True, progress=False)
            
            for symbol in chunk_tickers:
                try:
                    target = data[symbol] if len(chunk_tickers) > 1 else data
                    if 'Close' in target:
                        valid = target['Close'].dropna()
                        if not valid.empty and float(valid.iloc[-1]) > 0:
                            upsert_list.append({
                                "ticker": str(symbol),
                                "price": float(valid.iloc[-1]),
                                "updated_at": now_iso
                            })
                except: continue
        except Exception as e:
            print(f"🚨 다운로드 에러 발생 ({i+1}~구간): {e}", flush=True)
            
        # 야후 서버 차단 방지 (1.5초 휴식)
        time.sleep(1.5)

    # 4. 50개 단위 청크 DB 업로드
    if upsert_list:
        print(f"\n📊 {len(upsert_list)}개 데이터 추출 완료. DB 전송 시작...", flush=True)
        for i in range(0, len(upsert_list), chunk_size):
            chunk = upsert_list[i : i + chunk_size]
            if batch_upsert_raw("price_cache", chunk, on_conflict="ticker"):
                print(f"  -> DB 전송 {min(i+chunk_size, len(upsert_list))}/{len(upsert_list)}개 성공", flush=True)
            time.sleep(0.5)

        batch_upsert_raw("analysis_cache", [{"cache_key": "WORKER_LAST_RUN", "content": "alive", "updated_at": now_iso}], on_conflict="cache_key")
        print(f"✅ 워커 작업 완료", flush=True)
    else:
        print("⚠️ 업데이트할 가격 데이터가 없습니다.", flush=True)

if __name__ == "__main__":
    fetch_and_update_prices()
