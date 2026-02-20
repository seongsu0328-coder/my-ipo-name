import os
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
    print("❌ Supabase 환경변수 누락", flush=True)
    exit()

# [2] 표준 엔진
def sanitize_value(v):
    if v is None or pd.isna(v): return None
    if isinstance(v, (np.floating, float)):
        return float(v) if not (np.isinf(v) or np.isnan(v)) else 0.0
    if isinstance(v, (np.integer, int)): return int(v)
    return str(v).strip().replace('\x00', '')

# 🚨 [수정 1] 불안정한 requests.post 대신 Supabase 공식 라이브러리로 전면 교체
def batch_upsert(table_name, data_list, on_conflict="ticker"):
    if not data_list: return False
    
    clean_batch = []
    for item in data_list:
        payload = {k: sanitize_value(v) for k, v in item.items()}
        if payload.get(on_conflict): clean_batch.append(payload)

    if not clean_batch: return False
    
    try:
        # 공식 라이브러리가 알아서 안전하게 전송 및 재시도를 처리해줍니다.
        supabase.table(table_name).upsert(clean_batch).execute()
        return True
    except Exception as e: 
        print(f"❌ [{table_name}] DB 전송 에러: {e}", flush=True)
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
        print("대상 종목 없음", flush=True)
        return

    print(f"대상 종목: {len(tickers)}개 -> 다운로드 시작", flush=True)
    
    try:
        # 🚨 [수정 2 핵심] 메모리 폭발의 원인이었던 interval="1m" 삭제!
        # period="1d"만 써도 당일 최신 현재가를 가져오며, 데이터 크기가 1/100로 줄어듭니다.
        data = yf.download(tickers, period="1d", group_by='ticker', threads=True, progress=False)
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
            
            # float로 명시적 변환하여 JSON 에러 방지
            last_price = float(valid_closes.iloc[-1])
            
            if last_price > 0:
                upsert_list.append({
                    "ticker": str(symbol), 
                    "price": last_price, 
                    "updated_at": now_iso
                })
        except Exception as e: 
            continue 
    
    if upsert_list:
        print(f"📊 {len(upsert_list)}개 종목 데이터 확보. DB 저장 시도...", flush=True)
        
        chunk_size = 50
        success_count = 0
        
        # 50개씩 청크 분할하여 업로드
        for i in range(0, len(upsert_list), chunk_size):
            chunk = upsert_list[i : i + chunk_size]
            try:
                is_success = batch_upsert("price_cache", chunk, on_conflict="ticker")
                if is_success:
                    success_count += len(chunk)
                    print(f"  -> {success_count}/{len(upsert_list)}개 저장 완료...", flush=True)
                time.sleep(0.5) 
            except Exception as e:
                print(f"❌ 청크 저장 중 에러: {e}", flush=True)
            
        print("✅ 주가 캐싱 전송 완료!", flush=True)
        
        # 메인 앱(대시보드)에 생존 신고 기록
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
