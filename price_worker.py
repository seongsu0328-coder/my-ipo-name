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

# 💡 [수정] on_conflict가 여러 컬럼(ticker, target_date)일 경우를 위해 파라미터 유연성 확보
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
    # 💡 [핵심] 미국 증시 기준 오늘의 '날짜' 추출 (예: 2026-02-22)
    us_today_str = datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d')
    
    upsert_list = []
    history_list = [] # 💡 과거 기록을 저장할 새로운 리스트
    
    chunk_size = 50
    for i in range(0, len(tickers), chunk_size):
        chunk_tickers = tickers[i : i + chunk_size]
        print(f"⏳ 야후 파이낸스 다운로드 중... ({i+1} ~ {min(i+chunk_size, len(tickers))}/{len(tickers)})", flush=True)
        
        try:
            data = yf.download(chunk_tickers, period="1d", group_by='ticker', threads=True, progress=False)
            
            for symbol in chunk_tickers:
                try:
                    target = data[symbol] if len(chunk_tickers) > 1 else data
                    if 'Close' in target:
                        valid = target['Close'].dropna()
                        if not valid.empty and float(valid.iloc[-1]) > 0:
                            current_p = float(valid.iloc[-1])
                            
                            # 1. 실시간 가격 캐시용 데이터
                            upsert_list.append({
                                "ticker": str(symbol),
                                "price": current_p,
                                "updated_at": now_iso
                            })
                            
                            # 2. 💡 영구 저장 히스토리용 데이터
                            history_list.append({
                                "ticker": str(symbol),
                                "target_date": us_today_str,
                                "close_price": current_p
                            })
                except: continue
        except Exception as e:
            print(f"🚨 다운로드 에러 발생 ({i+1}~구간): {e}", flush=True)
            
        time.sleep(1.5)

    # DB 전송 로직
    if upsert_list:
        print(f"\n📊 {len(upsert_list)}개 데이터 추출 완료. DB 전송 시작...", flush=True)
        
        # 1. 기존 price_cache (실시간 가격) 덮어쓰기
        for i in range(0, len(upsert_list), chunk_size):
            chunk = upsert_list[i : i + chunk_size]
            batch_upsert_raw("price_cache", chunk, on_conflict="ticker")
            time.sleep(0.5)
            
        # 2. 💡 신규 price_history (과거 기록용 종가) 덮어쓰기
        # target_date가 동일하면 계속 덮어쓰다가 장이 마감되면 최종 가격으로 고정됩니다.
        print(f"📚 히스토리 DB 누적 저장 진행 중...", flush=True)
        for i in range(0, len(history_list), chunk_size):
            chunk = history_list[i : i + chunk_size]
            # on_conflict를 'ticker,target_date' 복합키로 설정
            batch_upsert_raw("price_history", chunk, on_conflict="ticker,target_date")
            time.sleep(0.5)

        batch_upsert_raw("analysis_cache", [{"cache_key": "WORKER_LAST_RUN", "content": "alive", "updated_at": now_iso}], on_conflict="cache_key")
        print(f"✅ 워커 작업 완료", flush=True)
    else:
        print("⚠️ 업데이트할 가격 데이터가 없습니다.", flush=True)

if __name__ == "__main__":
    fetch_and_update_prices()

def run_premium_alert_engine(supabase, df_calendar):
    """
    백그라운드에서 실행되며 DB 가격과 캘린더를 대조해 프리미엄 알림을 생성합니다.
    """
    today = datetime.now().date()
    new_alerts = []

    # [Step 1] 워커가 방금 업데이트한 최신 주가 정보 DB에서 싹 긁어오기 (API 호출 0건)
    res = supabase.table("price_cache").select("ticker, price").execute()
    db_prices = {row['ticker']: float(row['price']) for row in res.data if row['price']}

    # [Step 2] 캘린더 데이터를 전수 조사하며 알림 조건 체크
    for _, row in df_calendar.iterrows():
        ticker = row['symbol']
        name = row['name']
        
        # 날짜 정제
        try: ipo_date = pd.to_datetime(row['date']).date()
        except: continue

        # --- 알고리즘 1: 상장 임박 알림 (D-3) ---
        if ipo_date == today + timedelta(days=3):
            new_alerts.append({
                "ticker": ticker, "alert_type": "UPCOMING",
                "title": f"🚀 상장 D-3 알림: {name}",
                "message": f"{ticker} 종목이 3일 뒤 상장 예정입니다. 상세 리포트를 확인하세요."
            })

        # --- 알고리즘 2: 락업 해제 경보 (상장 후 180일 되는 날의 7일 전) ---
        lockup_date = ipo_date + timedelta(days=180)
        if lockup_date == today + timedelta(days=7):
            new_alerts.append({
                "ticker": ticker, "alert_type": "LOCKUP",
                "title": f"🚨 락업 해제 주의보: {ticker}",
                "message": f"7일 뒤 보호예수(Lock-up)가 해제됩니다. 물량 출회에 따른 변동성에 유의하세요."
            })

        # --- 알고리즘 3: 조용한 기간 종료 (상장 후 25일 되는 날의 3일 전) ---
        quiet_period_end = ipo_date + timedelta(days=25)
        if quiet_period_end == today + timedelta(days=3):
            new_alerts.append({
                "ticker": ticker, "alert_type": "QUIET_PERIOD",
                "title": f"🤐 Quiet Period 종료 임박: {ticker}",
                "message": f"3일 뒤 주관사 애널리스트들의 리포트 발행이 시작됩니다. 주가 변동을 주시하세요."
            })

        # --- 알고리즘 4: 공모가 재돌파 (Golden Cross) ---
        current_p = db_prices.get(ticker, 0.0)
        try: ipo_p = float(str(row.get('price', '0')).replace('$', '').split('-')[0])
        except: ipo_p = 0.0

        if ipo_p > 0 and current_p > 0:
            # 워커에 기록된 바로 직전 가격을 가져올 수 있다면 더 정교하겠지만, 
            # 단순하게 '오늘 공모가 돌파' 조건으로 먼저 구현합니다.
            if current_p >= ipo_p and (current_p - ipo_p) / ipo_p < 0.02: # 돌파 직후 2% 이내일 때
                new_alerts.append({
                    "ticker": ticker, "alert_type": "REBOUND",
                    "title": f"🔥 공모가 회복: {ticker}",
                    "message": f"{ticker}의 현재 주가(${current_p})가 침체를 깨고 다시 공모가 위로 올라왔습니다."
                })

            # --- 알고리즘 5: 통계적 유의 범위 급등 (공모가 대비 25% 이상) ---
            surge_pct = ((current_p - ipo_p) / ipo_p) * 100
            if surge_pct >= 25.0:
                new_alerts.append({
                    "ticker": ticker, "alert_type": "SURGE",
                    "title": f"📈 강력 모멘텀 포착: {ticker}",
                    "message": f"현재 주가가 공모가 대비 +{surge_pct:.1f}% 상승하며 통계적 유의 범위를 상회 중입니다."
                })

    # [Step 3] 중복 알림 방지 및 DB 저장
    # (같은 날 동일한 종목에 동일한 알림이 쌓이지 않도록 처리)
    if new_alerts:
        for alert in new_alerts:
            # 오늘 이미 똑같은 알림을 보냈는지 확인
            exist = supabase.table("premium_alerts")\
                .select("id")\
                .eq("ticker", alert['ticker'])\
                .eq("alert_type", alert['alert_type'])\
                .gte("created_at", today.isoformat())\
                .execute()
            
            if not exist.data:
                supabase.table("premium_alerts").insert(alert).execute()
        
        print(f"✅ {datetime.now()}: {len(new_alerts)}개의 프리미엄 신호 분석 완료.")
