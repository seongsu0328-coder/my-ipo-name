# emergency_worker.py (최종 완결본)
import sys
import argparse
from datetime import datetime
from worker import (
    supabase, FMP_API_KEY, 
    run_tab0_analysis, run_tab1_analysis, run_tab3_analysis, 
    run_tab4_analysis, run_tab6_analysis, run_tab2_premium_collection,
    fetch_analyst_estimates, fetch_premium_financials, fetch_smart_money_data
)

def run_emergency_fix(ticker, tab_name):
    print(f"🚨 [긴급 복구] {ticker} - {tab_name} 분석 시작: {datetime.now()}")
    
    # 1. 기업 이름 확인
    res = supabase.table("stock_cache").select("name").eq("symbol", ticker).execute()
    if not res.data:
        print(f"❌ 에러: {ticker}는 DB에 존재하지 않는 종목입니다.")
        return
    company_name = res.data[0]['name']

    # 2. 탭별 정밀 분석 실행
    try:
        if tab_name == 'tab0':
            run_tab0_analysis(ticker, company_name, cik_mapping={})
        elif tab_name == 'tab1':
            run_tab1_analysis(ticker, company_name)
        elif tab_name == 'tab2': # ESG 리포트 복구
            run_tab2_premium_collection(ticker, company_name)
        elif tab_name == 'tab3':
            unified_metrics = fetch_premium_financials(ticker, FMP_API_KEY)
            run_tab3_analysis(ticker, company_name, unified_metrics)
        elif tab_name == 'tab4':
            analyst_metrics = fetch_analyst_estimates(ticker, FMP_API_KEY)
            run_tab4_analysis(ticker, company_name, analyst_data=analyst_metrics)
        elif tab_name == 'tab6':
            smart_money = fetch_smart_money_data(ticker, FMP_API_KEY)
            run_tab6_analysis(ticker, company_name, smart_money)
        else:
            print(f"⚠️ {tab_name}은 AI 분석이 필요 없는 탭이거나 잘못된 이름입니다.")
            return

        print(f"✅ [복구 완료] {ticker} - {tab_name} 복구 성공!")

    except Exception as e:
        print(f"❌ 복구 실패 ({ticker}): {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UnicornFinder 데이터 복구 엔진")
    parser.add_argument("--ticker", required=True, help="종목 티커 (예: AAPL)")
    parser.add_argument("--tab", required=True, help="탭 (tab0, tab1, tab2, tab3, tab4, tab6)") # tab2 추가
    
    args = parser.parse_args()
    run_emergency_fix(args.ticker.upper(), args.tab.lower())
