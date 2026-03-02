import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import time
import re

# 💡 [수정] yfinance 라이브러리 및 로깅 설정 완전 삭제

# [1] 환경 설정
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip('/')
if "/rest/v1" in SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.split("/rest/v1")[0]
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

# 💡 [신규] FMP API 키 로드
FMP_API_KEY = os.environ.get("FMP_API_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ 에러: Supabase 환경변수 누락", flush=True); exit(1)

if not FMP_API_KEY:
    print("❌ 에러: FMP_API_KEY 환경변수 누락 (GitHub Secrets 확인 필요)", flush=True); exit(1)

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

# =====================================================================
# [SEC 티커 교정 헬퍼 (app.py와 완벽 동기화)]
# =====================================================================
def get_sec_ticker_mapping():
    try:
        headers = {'User-Agent': 'UnicornFinder App admin@unicornfinder.com'}
        res = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=10)
        data = res.json()
        mapping = {}
        for k, v in data.items():
            name = str(v['title']).lower()
            name = re.sub(r'\b(inc|corp|corporation|co|ltd|plc|group|company|holdings)\b\.?', '', name)
            name = re.sub(r'[^a-z0-9]', '', name)
            if name: mapping[name] = v['ticker']
        return mapping
    except:
        return {}

def normalize_name(name):
    if not name or pd.isna(name): return ""
    name = str(name).lower()
    name = re.sub(r'\b(inc|corp|corporation|co|ltd|plc|group|company|holdings)\b\.?', '', name)
    return re.sub(r'[^a-z0-9]', '', name) 

def fetch_otc_price_premium(ticker):
    """향후 Polygon.io API 연동 예비 공간"""
    return 0.0

def fetch_and_update_prices():
    # 💡 [핵심 최적화] 미국 증시 운영 시간 체크 (API 낭비 및 밴 방지)
    # 미국 동부시간 기준 (장전/장후 포함) 월~금 04:00 ~ 20:00 에만 수집
    now_est = datetime.now(pytz.timezone('US/Eastern'))
    if now_est.weekday() >= 5: # 토(5), 일(6)
        print(f"💤 주말 휴식 중 (미국장 닫힘) - {now_est.strftime('%Y-%m-%d %H:%M')}", flush=True)
        return
    if not (4 <= now_est.hour <= 20):
        print(f"💤 야간 휴식 중 (미국장 닫힘) - {now_est.strftime('%Y-%m-%d %H:%M')}", flush=True)
        return

    print(f"🚀 15분 주기 실시간 주가 업데이트 시작 (EST: {now_est.strftime('%H:%M')})", flush=True)
    
    try:
        # DB에서 심볼과 '이름'을 함께 가져옴 (티커 교정을 위해)
        get_url = f"{SUPABASE_URL}/rest/v1/stock_cache?select=symbol,name"
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        resp = requests.get(get_url, headers=headers, timeout=15)
        stock_data = resp.json()
    except Exception as e:
        print(f"❌ 데이터 로드 실패: {e}", flush=True); return

    if not stock_data: return

    # 💡 [핵심 파이프라인] SEC 공식 티커 매핑 적용
    sec_map = get_sec_ticker_mapping()
    query_map = {} # { "공식티커": "원래티커(DB용)" }
    
    for item in stock_data:
        orig_sym = item['symbol']
        clean_n = normalize_name(item.get('name', ''))
        official_sym = sec_map.get(clean_n, orig_sym)
        query_map[official_sym] = orig_sym # 조회는 official로, DB 저장은 orig로 매핑

    official_tickers = list(query_map.keys())
    print(f"📦 대상: {len(official_tickers)}개 FMP API로 주가 다운로드 시작 (SEC 동기화 완료)...", flush=True)

    now_iso = datetime.now(pytz.timezone('Asia/Seoul')).isoformat()
    us_today_str = now_est.strftime('%Y-%m-%d')
    
    upsert_list = []
    history_list = [] 
    
    # 💡 [핵심 수정] FMP 다중 주가 조회 방식 (쉼표로 구분하여 한 번에 대량 호출)
    chunk_size = 50
    for i in range(0, len(official_tickers), chunk_size):
        chunk = official_tickers[i : i + chunk_size]
        tickers_str = ",".join(chunk)
        
        url = f"https://financialmodelingprep.com/api/v3/quote/{tickers_str}?apikey={FMP_API_KEY}"
        
        try:
                res = requests.get(url, timeout=15)
                data = res.json()
                
                fmp_prices = {}
                if isinstance(data, list):
                    fmp_prices = {item.get("symbol"): float(item.get("price", 0.0)) for item in data if item.get("symbol")}
                else:
                    # 💡 [신규 추가] 왜 데이터를 못 가져오는지 이유를 터미널에 찍어줍니다.
                    print(f"⚠️ FMP API 응답 에러 (유료 결제 전 한도 초과 추정): {data}", flush=True)
            
                for official_sym in chunk:
                    # 1. FMP에서 가격 확인
                    current_p = fmp_prices.get(official_sym, 0.0)
                    
                    # 2. 가격이 0원이면 예비 OTC 함수 찔러보기
                    if current_p <= 0:
                        current_p = fetch_otc_price_premium(official_sym)

                    if current_p > 0:
                        upsert_list.append({
                            "ticker": str(official_sym), "price": current_p, "updated_at": now_iso
                        })
                        history_list.append({
                            "ticker": str(official_sym), "target_date": us_today_str, "close_price": current_p
                        })
            except Exception as e:
                print(f"🚨 FMP 다운로드 에러 발생 ({i+1}~구간): {e}", flush=True)
                
            time.sleep(0.5) # API 속도 제한(Rate Limit) 방어

    # DB 전송 로직
    if upsert_list:
        print(f"\n📊 {len(upsert_list)}개 데이터 추출 완료. DB 전송 시작...", flush=True)
        for i in range(0, len(upsert_list), chunk_size):
            batch_upsert_raw("price_cache", upsert_list[i : i + chunk_size], on_conflict="ticker")
            time.sleep(0.5)
            
        for i in range(0, len(history_list), chunk_size):
            batch_upsert_raw("price_history", history_list[i : i + chunk_size], on_conflict="ticker,target_date")
            time.sleep(0.5)
    else:
        print("⚠️ 업데이트할 가격 데이터가 없습니다. (FMP 한도 초과 또는 장 마감)", flush=True)

    # 💡 [핵심 수정] 주가 업데이트 성공 여부와 상관없이 무조건 생존 신고를 보냅니다!
    batch_upsert_raw("analysis_cache", [{"cache_key": "WORKER_LAST_RUN", "content": "alive", "updated_at": now_iso}], on_conflict="cache_key")
    print(f"✅ 주가 업데이트 워커 1회차 작업 완벽 종료", flush=True)

# =====================================================================
# 🚀 메인 실행부 (무한 루프 제거! 깃허브 액션 맞춤형)
# =====================================================================
if __name__ == "__main__":
    # 💡 깃허브 액션이 15분마다 이 파일을 1번씩만 깔끔하게 실행하고 종료하도록 수정!
    print("🤖 FMP 실시간 주가 수집 워커를 1회 실행합니다.", flush=True)
    try:
        fetch_and_update_prices()
    except Exception as e:
        print(f"🚨 워커 실행 중 에러 발생: {e}", flush=True)
