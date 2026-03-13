import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import time
import re

# [1] 환경 설정
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip('/')
if "/rest/v1" in SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.split("/rest/v1")[0]
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
FMP_API_KEY = os.environ.get("FMP_API_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ 에러: Supabase 환경변수 누락", flush=True); exit(1)
if not FMP_API_KEY:
    print("❌ 에러: FMP_API_KEY 환경변수 누락", flush=True); exit(1)

def batch_upsert_raw(table_name, data_list, on_conflict="ticker"):
    if not data_list: return False
    endpoint = f"{SUPABASE_URL}/rest/v1/{table_name}?on_conflict={on_conflict}"
    headers = {
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json", "Prefer": "return=minimal,resolution=merge-duplicates"
    }
    try:
        resp = requests.post(endpoint, json=data_list, headers=headers, timeout=20)
        return resp.status_code in [200, 201, 204]
    except Exception as e:
        print(f"❌ DB 전송 에러: {e}", flush=True)
        return False

# 💡 대표님이 만드신 SEC 이중 검증 시스템 완벽 유지
def get_sec_ticker_mapping():
    try:
        headers = {'User-Agent': 'UnicornFinder App admin@unicornfinder.com'}
        res = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=10)
        mapping = {}
        for k, v in res.json().items():
            name = str(v['title']).lower()
            name = re.sub(r'\b(inc|corp|corporation|co|ltd|plc|group|company|holdings)\b\.?', '', name)
            if name: mapping[re.sub(r'[^a-z0-9]', '', name)] = v['ticker']
        return mapping
    except: return {}

def normalize_name(name):
    if not name or pd.isna(name): return ""
    name = str(name).lower()
    name = re.sub(r'\b(inc|corp|corporation|co|ltd|plc|group|company|holdings)\b\.?', '', name)
    return re.sub(r'[^a-z0-9]', '', name)

def fetch_otc_price_premium(ticker): return 0.0

def fetch_and_update_prices():
    now_est = datetime.now(pytz.timezone('US/Eastern'))
    print(f"🚀 실시간 주가 업데이트 시작 (EST: {now_est.strftime('%H:%M')})", flush=True)

    try:
        get_url = f"{SUPABASE_URL}/rest/v1/stock_cache?select=symbol,name"
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        stock_data = requests.get(get_url, headers=headers, timeout=15).json()
    except Exception as e:
        print(f"❌ 데이터 로드 실패: {e}", flush=True); return

    if not stock_data: return

    # 💡 SEC 교차 검증을 통해 최신 공식 티커 도출
    sec_map = get_sec_ticker_mapping()
    query_map = {sec_map.get(normalize_name(item.get('name', '')), item['symbol']): item['symbol'] for item in stock_data}
    official_tickers = list(query_map.keys())
    print(f"📦 대상: {len(official_tickers)}개 FMP API로 주가 다운로드 시작...", flush=True)

    now_iso = datetime.now(pytz.timezone('Asia/Seoul')).isoformat()
    us_today_str = now_est.strftime('%Y-%m-%d')
    upsert_list, history_list = [], []

    chunk_size = 50
    for i in range(0, len(official_tickers), chunk_size):
        chunk = official_tickers[i : i + chunk_size]
        
        # 🚨 [가장 중요한 수정] URL 문법 오류 해결! 
        # ?symbol= 이 아니라 경로 자체에 콤마로 연결된 티커를 바로 박아넣습니다.
        url = f"https://financialmodelingprep.com/stable/quote/{','.join(chunk)}?apikey={FMP_API_KEY}"

        try:
            res = requests.get(url, timeout=15)
            data = res.json()
            
            # API 응답이 정상적으로 리스트 형태로 왔을 때
            if isinstance(data, list) and len(data) > 0:
                fmp_prices = {item.get("symbol"): float(item.get("price", 0.0)) for item in data if item.get("symbol")}
                
                for official_sym in chunk:
                    current_p = fmp_prices.get(official_sym, 0.0)
                    if current_p <= 0: current_p = fetch_otc_price_premium(official_sym)
                    
                    if current_p > 0:
                        # 💡 앱이 원래 알던 티커(query_map 매칭)로 DB에 돌려줘야 앱이 인식합니다.
                        db_original_sym = query_map.get(official_sym, official_sym)
                        
                        upsert_list.append({"ticker": str(db_original_sym), "price": current_p, "updated_at": now_iso, "status": "Active"})
                        history_list.append({"ticker": str(db_original_sym), "target_date": us_today_str, "close_price": current_p})
            
            elif isinstance(data, dict) and "Error Message" in data:
                print(f"⚠️ FMP API 에러: {data['Error Message']}", flush=True)
            else:
                # 데이터가 없는 경우 조용히 패스
                pass
                
        except Exception as e:
            print(f"🚨 FMP 다운로드 에러 ({i+1}~구간): {e}", flush=True)
        time.sleep(0.3)

    if upsert_list:
        print(f"\n📊 {len(upsert_list)}개 가격 데이터 DB 전송 시작...", flush=True)
        for i in range(0, len(upsert_list), chunk_size): batch_upsert_raw("price_cache", upsert_list[i : i+chunk_size], on_conflict="ticker")
        for i in range(0, len(history_list), chunk_size): batch_upsert_raw("price_history", history_list[i : i+chunk_size], on_conflict="ticker,target_date")
        print(f"✅ {len(upsert_list)}개 종목 실시간 주가 갱신 완벽 종료", flush=True)
    else:
        print("⚠️ 이번 루프에서 업데이트할 수 있는 가격 데이터가 없습니다.", flush=True)

    # 앱 생존 신고 완벽 연동
    batch_upsert_raw("analysis_cache", [{"cache_key": "PRICE_WORKER_LAST_RUN", "content": "alive", "updated_at": now_iso}], on_conflict="cache_key")
    print(f"🏁 워커 실행 종료", flush=True)

if __name__ == "__main__":
    print("🤖 FMP 실시간 주가 수집 워커를 실행합니다.", flush=True)
    fetch_and_update_prices()
