import os
import yfinance as yf
import pandas as pd
from datetime import datetime, time
import pytz # 타임존 처리를 위해 필요
from supabase import create_client

# 1. 환경 변수 설정
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")

if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    print("❌ Supabase 환경변수 누락")
    exit()

# 2. 미국 시장 운영 시간 체크 함수 (핵심 로직)
def is_market_open():
    """
    현재 시간이 미국 주식 시장 운영 시간(Pre/Regular/After 포함 넉넉하게)인지 확인
    범위: 미국 동부시간(ET) 기준 04:00 ~ 20:00 (Pre-market ~ After-market 전체 커버)
    또는 정규장만 원한다면 09:30 ~ 16:00 으로 설정 가능
    여기서는 데이터 변화가 있는 '09:00 ~ 17:00' 정도로 넉넉히 설정하여 안전하게 수집
    """
    utc_now = datetime.now(pytz.utc)
    # 미국 동부 시간으로 변환
    est_tz = pytz.timezone('US/Eastern')
    est_now = utc_now.astimezone(est_tz)
    
    # 1) 주말 체크 (토=5, 일=6)
    if est_now.weekday() >= 5:
        print(f"😴 오늘은 주말({est_now.strftime('%A')})입니다. 수집을 건너뜁니다.")
        return False

    # 2) 시간 체크 (09:00 ~ 17:00 ET)
    # 장 시작 전후의 변동성도 일부 캐싱하기 위해 앞뒤로 조금 여유를 둡니다.
    market_start = time(9, 0) 
    market_end = time(17, 0)
    current_time = est_now.time()

    if market_start <= current_time <= market_end:
        return True
    else:
        print(f"😴 장 운영 시간이 아닙니다. (현재 ET: {current_time.strftime('%H:%M')})")
        return False

# 3. 타겟 종목 리스트 가져오기 (DB 또는 Finnhub)
def get_target_tickers():
    # worker.py가 이미 만들어둔 'stock_cache' 테이블에서 심볼만 싹 긁어오는게 제일 빠름
    try:
        # DB에서 심볼만 조회 (최대 1000개까지)
        res = supabase.table("stock_cache").select("symbol").execute()
        if res.data:
            return [item['symbol'] for item in res.data]
    except Exception as e:
        print(f"DB Read Error: {e}")
    
    return []

# 4. 메인 실행 로직
def fetch_and_update_prices():
    # [Step 1] 시장 시간 체크
    #if not is_market_open():
    #    return # 장 닫혔으면 여기서 즉시 종료 (자원 절약)

    print("🚀 실시간 주가 수집 시작 (15분 주기)...")
    
    # [Step 2] 대상 종목 가져오기
    tickers = get_target_tickers()
    if not tickers:
        print("대상 종목이 없습니다.")
        return

    # [Step 3] yfinance Batch Download (한방에 가져오기)
    # 100개 종목도 1초면 가져옵니다.
    tickers_str = " ".join(tickers)
    print(f"대상 종목: {len(tickers)}개")
    
    try:
        # period='1d'만 해도 최신가는 나옵니다.
        data = yf.download(tickers_str, period="1d", interval="1m", group_by='ticker', threads=True, progress=False)
        
        # [Step 4] DB 업데이트
        upsert_list = []
        now_iso = datetime.now().isoformat()
        
        for symbol in tickers:
            try:
                # 데이터 프레임 구조에 따라 처리 (단일 종목 vs 다중 종목)
                if len(tickers) > 1:
                    if symbol not in data.columns.levels[0]: continue
                    closes = data[symbol]['Close']
                else:
                    closes = data['Close']
                
                # 최신가 추출 (NaN 제외)
                last_price = closes.dropna().iloc[-1] if not closes.dropna().empty else 0
                
                if last_price > 0:
                    upsert_list.append({
                        "ticker": symbol,
                        "price": float(last_price),
                        "updated_at": now_iso
                    })
            except:
                continue
        
        # [Step 5] Supabase에 한 번에 저장 (Batch Insert)
        if upsert_list:
            supabase.table("price_cache").upsert(upsert_list).execute()
            print(f"✅ {len(upsert_list)}개 종목 가격 업데이트 완료!")
            
    except Exception as e:
        print(f"❌ Batch Update Failed: {e}")

if __name__ == "__main__":
    fetch_and_update_prices()
