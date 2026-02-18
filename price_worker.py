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

# 2. 미국 시장 운영 시간 체크 함수 (수정됨: 무조건 실행)
def is_market_open():
    """
    현재 시간이 미국 주식 시장 운영 시간인지 확인하는 함수였으나,
    초기 데이터 구축을 위해 '무조건 True'를 반환하도록 수정됨.
    """
    utc_now = datetime.now(pytz.utc)
    # 미국 동부 시간으로 변환
    est_tz = pytz.timezone('US/Eastern')
    est_now = utc_now.astimezone(est_tz)
    current_time = est_now.time()
    
    # 1) 주말 체크 로직 (주석 처리됨 - 강제 실행을 위해)
    # if est_now.weekday() >= 5:
    #     print(f"😴 오늘은 주말({est_now.strftime('%A')})입니다. 수집을 건너뜁니다.")
    #     return False

    # 2) 시간 체크 로직 (주석 처리됨 - 강제 실행을 위해)
    # market_start = time(9, 0) 
    # market_end = time(17, 0)
    # if market_start <= current_time <= market_end:
    #     return True
    # else:
    #     print(f"😴 장 운영 시간이 아닙니다. (현재 ET: {current_time.strftime('%H:%M')})")
    #     return False
    
    # ▼▼▼▼▼ [강제 실행 모드] ▼▼▼▼▼
    print(f"🚀 [강제 실행] 장 운영 시간/요일 무관하게 주가 수집을 시작합니다. (현재 ET: {current_time.strftime('%H:%M')})")
    return True

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
    # [Step 1] 시장 시간 체크 (무조건 통과됨)
    if not is_market_open():
        return 

    print("🚀 실시간 주가 수집 시작 (Batch Mode)...")
    
    # [Step 2] 대상 종목 가져오기
    tickers = get_target_tickers()
    if not tickers:
        print("대상 종목이 없습니다.")
        return

    # [Step 3] yfinance Batch Download (한방에 가져오기)
    tickers_str = " ".join(tickers)
    print(f"대상 종목: {len(tickers)}개 -> 다운로드 시작")
    
    try:
        # period='1d'로 최신 종가 수집
        data = yf.download(tickers_str, period="1d", interval="1m", group_by='ticker', threads=True, progress=False)
        
        # [Step 4] DB 업데이트 데이터 준비
        upsert_list = []
        
        # 한국 시간 기준 타임스탬프 생성
        kst = pytz.timezone('Asia/Seoul')
        now_iso = datetime.now(kst).isoformat() 
        
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
            # 1000개씩 끊어서 업로드 (안전장치)
            chunk_size = 1000
            for i in range(0, len(upsert_list), chunk_size):
                chunk = upsert_list[i:i+chunk_size]
                supabase.table("price_cache").upsert(chunk).execute()
                print(f"✅ {len(chunk)}개 종목 가격 업데이트 완료! (Chunk {i//chunk_size + 1})")
            
    except Exception as e:
        print(f"❌ Batch Update Failed: {e}")

if __name__ == "__main__":
    fetch_and_update_prices()
