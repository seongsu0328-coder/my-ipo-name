# UnicornFinder 긴급 데이터 복구 및 관리 가이드

이 가이드는 특정 종목의 AI 분석 데이터가 누락되었을 때, 긴급 복구 엔진(`emergency_worker.py`)을 사용하는 방법과 Supabase 데이터 상태를 확인하는 쿼리를 정리한 문서입니다.

## 긴급 복구 엔진 실행 방법 (CLI)

특정 종목의 특정 탭 데이터만 즉시 다시 생성하고 Supabase에 태그와 함께 저장합니다.

### 명령어 구조
`python emergency_worker.py --ticker [종목코드] --tab [탭번호]`

### 주요 실행 예시
* **애플(AAPL) 비즈니스 요약(Tab 1) 복구**:
  `python emergency_worker.py --ticker AAPL --tab tab1`
* **테슬라(TSLA) 재무 리포트(Tab 3) 복구**:
  `python emergency_worker.py --ticker TSLA --tab tab3`
* **엔비디아(NVDA) 기관 의견(Tab 4) 복구**:
  `python emergency_worker.py --ticker NVDA --tab tab4`
* **Tab 2(ESG), Tab 6(스마트머니) 등도 동일한 방식으로 복구 가능**

---

## Supabase 데이터 누락 확인용 쿼리 (SQL)

Supabase SQL Editor에서 실행하여 비어있는 데이터를 찾습니다.

### 특정 탭 데이터가 없는 종목 리스트 (Top 50)
```sql
SELECT s.symbol, s.name
FROM stock_cache s
LEFT JOIN analysis_cache a 
  ON s.symbol = a.ticker 
  AND a.tab_name = 'tab1' 
  AND a.lang = 'ko'
WHERE a.ticker IS NULL
ORDER BY s.symbol ASC
LIMIT 50;
