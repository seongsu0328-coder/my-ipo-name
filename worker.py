# worker.py
import os
import requests
import pandas as pd
import time
from datetime import datetime, timedelta
from supabase import create_client

# 1. 환경 변수 및 클라이언트 설정
# 로컬 테스트 시에는 직접 입력, 배포 시에는 GitHub Secrets 사용
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY") # Finnhub 키 추가 필요

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_worker_target_ipo_data(api_key):
    """새벽에 실행되어 상장예정(30일) + 지난 18개월치 종목 리스트를 반환함"""
    now = datetime.now()
    # 18개월(약 540일) + 상장예정(35일) 구간 설정 (중복 방지용 오버랩 포함)
    ranges = [
        (now - timedelta(days=200), now + timedelta(days=35)),  
        (now - timedelta(days=380), now - timedelta(days=170)), 
        (now - timedelta(days=560), now - timedelta(days=350))  
    ]
    
    all_data = []
    for start_dt, end_dt in ranges:
        start_str = start_dt.strftime('%Y-%m-%d')
        end_str = end_dt.strftime('%Y-%m-%d')
        url = f"https://finnhub.io/api/v1/calendar/ipo?from={start_str}&to={end_str}&token={api_key}"
        
        try:
            time.sleep(0.3) # Rate Limit 방지
            res = requests.get(url, timeout=10).json()
            ipo_list = res.get('ipoCalendar', [])
            if ipo_list:
                all_data.extend(ipo_list)
        except Exception as e:
            print(f"[{start_str}] 리스트 호출 중단: {e}")
            continue
    
    if not all_data:
        return pd.DataFrame()

    df = pd.DataFrame(all_data)
    # 중복 제거 및 심볼 없는 데이터 필터링
    df = df.drop_duplicates(subset=['symbol', 'date'])
    df = df[df['symbol'].astype(str).str.strip() != ""]
    
    return df

def fetch_and_cache_all():
    print(f"[{datetime.now()}] 🚀 데이터 수집 및 Pre-caching 시작...")
    
    # 2. 대상 종목 리스트 확보 (상장예정 + 18개월)
    ipo_df = get_worker_target_ipo_data(FINNHUB_API_KEY)
    
    if ipo_df.empty:
        print("❌ 수집할 대상 종목이 없습니다.")
        return

    total = len(ipo_df)
    print(f"📊 총 {total}개 종목을 대상으로 작업을 시작합니다.")

    # 3. 종목별 루프 실행
    for idx, row in ipo_df.iterrows():
        symbol = row['symbol']
        try:
            print(f"[{idx+1}/{total}] {symbol} 처리 중...")
            
            # [기초 정보 패키징] - 캘린더 페이지용
            base_info = {
                "name": row.get('name'),
                "date": row.get('date'),
                "exchange": row.get('exchange'),
                "price": row.get('price'),
                "numberOfShares": row.get('numberOfShares'),
                "marketCap": row.get('marketCap')
            }

            # [상세 데이터 수집 공간] 
            # 나중에 Tap 0, 1, 2, 3, 4 관련 함수를 여기에 추가하게 됩니다.
            # 예: tap0_data = get_notices_api(symbol)
            
            payload = {
                "symbol": symbol,
                "base_info": base_info,
                "tap_0_notices": {},    # 추후 업데이트 예정
                "tap_1_news": {},       # 추후 업데이트 예정
                "tap_2_macro": {},      # 추후 업데이트 예정
                "tap_3_micro": {},      # 추후 업데이트 예정
                "tap_4_institutions": {}, # 추후 업데이트 예정
                "last_updated": datetime.now().isoformat()
            }
            
            # 4. Supabase Upsert (있으면 수정, 없으면 삽입)
            supabase.table("stock_cache").upsert(payload).execute()
            
        except Exception as e:
            print(f"⚠️ {symbol} 수집 실패: {e}")

if __name__ == "__main__":
    # 환경변수 체크
    if not SUPABASE_URL or not FINNHUB_API_KEY:
        print("❌ 에러: 환경변수(URL 또는 API KEY)가 설정되지 않았습니다.")
    else:
        fetch_and_cache_all()
        print(f"[{datetime.now()}] ✅ 모든 캐싱 작업 완료.")
