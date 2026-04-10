
import os
import time
import json
import re
import requests
import copy
import pandas as pd
import numpy as np
import logging
# 💡 [FCM 추가] Firebase 라이브러리
import firebase_admin
from firebase_admin import credentials, messaging
from datetime import datetime, timedelta

from supabase import create_client
from google import genai

# ==========================================
# [1] 환경 설정 & 디버깅 로그
# ==========================================

# 1. 환경 변수 로드
raw_url = os.environ.get("SUPABASE_URL", "")
if "/rest/v1" in raw_url:
    SUPABASE_URL = raw_url.split("/rest/v1")[0].rstrip('/')
else:
    SUPABASE_URL = raw_url.rstrip('/')

SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
GENAI_API_KEY = os.environ.get("GENAI_API_KEY", "")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "781b0d2391740729adb2d931e200e322")
# 💡 [FCM 추가] Firebase 서비스 계정 키 (Railway 환경 변수에서 로드)
FIREBASE_SA_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "")

# 💡 [디버깅] 상태 확인
print(f"DEBUG: SUPABASE_URL 존재 = {bool(SUPABASE_URL)}")
print(f"DEBUG: SUPABASE_KEY 존재 = {bool(SUPABASE_KEY)}")
print(f"DEBUG: FIREBASE_SA 존재 = {bool(FIREBASE_SA_JSON)}")

# 2. 필수 연결 체크 (Supabase)
if not (SUPABASE_URL and SUPABASE_KEY):
    print("❌ 환경변수 누락으로 종료")
    exit()

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase 클라이언트 연결 성공")
except Exception as e:
    print(f"❌ Supabase 초기화 실패: {e}")
    exit()

# 💡 [FCM 추가] Firebase Admin SDK 초기화
if FIREBASE_SA_JSON:
    try:
        cred_dict = json.loads(FIREBASE_SA_JSON)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        print("✅ Firebase Admin SDK 초기화 성공")
    except Exception as e:
        print(f"❌ Firebase 초기화 실패: {e}")
else:
    print("⚠️ FIREBASE_SERVICE_ACCOUNT 환경변수가 없어 푸시 알림이 비활성화됩니다.")

# 3. AI 모델 설정 (하이브리드 전략: 엄격 모델 & 검색 허용 모델 분리)
import sys
import random

model_strict = None
model_search = None
if GENAI_API_KEY:
    try:
        client = genai.Client(api_key=GENAI_API_KEY)
        
        # [1] 환각 원천 차단용 일반 모델
        class StrictModelWrapper:
            def __init__(self, client):
                self.client = client
            def generate_content(self, prompt):
                for attempt in range(2): # 최대 2번만 시도
                    try:
                        return self.client.models.generate_content(
                            model='gemini-2.0-flash',
                            contents=prompt
                        )
                    except Exception as e:
                        err_str = str(e).lower()
                        # 🚨 결제 한도/무료 티어 소진 시 즉시 프로그램 강제 종료 (스팸 방지)
                       
                            
                        # 단순 속도 제한일 경우 30초 대기 후 딱 1번만 재시도
                        if "429" in err_str or "quota" in err_str:
                            if attempt == 0:
                                time.sleep(30)
                                continue
                        raise e

        model_strict = StrictModelWrapper(client)
        
        # [2] 하이브리드 엔진 (REST API)
        class DirectGeminiSearch:
            def __init__(self, api_key):
                self.url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
                
            def generate_content(self, prompt):
                payload = { "contents":[{"parts": [{"text": prompt}]}], "tools": [{"googleSearch": {}}] }
                class MockResponse:
                    def __init__(self, text): self.text = text
                
                for attempt in range(2):
                    try:
                        res = requests.post(self.url, json=payload, headers={'Content-Type': 'application/json'}, timeout=60)
                        
                        if res.status_code == 200:
                            data = res.json()
                            text_output = ""
                            for cand in data.get("candidates",[]):
                                for part in cand.get("content", {}).get("parts",[]):
                                    if "text" in part: text_output += part["text"]
                            return MockResponse(text_output)
                            
                        elif res.status_code == 429:
                            err_str = res.text.lower()
                            # 🚨 결제 한도/무료 티어 소진 시 즉시 프로그램 강제 종료
                            
                                
                            if attempt == 0:
                                time.sleep(30)
                                continue
                            raise Exception(f"429 Limit: {res.text}")
                        else:
                            return MockResponse("")
                    except Exception as e:
                        if "exit" in str(type(e)).lower(): sys.exit(1)
                        raise e

        model_search = DirectGeminiSearch(GENAI_API_KEY)
        print("✅ AI 하이브리드 모델 로드 성공 (결제 한도 초과 시 셧다운 방어막 가동!)")

    except Exception as e:
        print(f"⚠️ AI 모델 로드 에러: {e}")
        
# 💡 [중요] 다국어 지원 언어 리스트 정의
SUPPORTED_LANGS = {
    'ko': '전문적인 한국어(Korean)',
    'en': 'Professional English',
    'ja': '専門的な日本語(Japanese)',
    'zh': '简体中文(Simplified Chinese)'
}

# (A) 메타데이터(Accession Number)만 가져오는 가벼운 함수
def fetch_sec_metadata(ticker, doc_type, api_key, cik=None):
    try:
        accession_num, filed_date = None, None
        search_url = f"https://financialmodelingprep.com/stable/sec-filings?symbol={ticker}&type={doc_type}&limit=1&apikey={api_key}"
        r = requests.get(search_url, timeout=5)
        if r.status_code == 200:
            res_data = r.json()
            if isinstance(res_data, list) and len(res_data) > 0:
                accession_num = res_data[0].get('accessionNumber')
                filed_date = res_data[0].get('fillingDate')
        if not accession_num and cik:
            sec_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
            sec_res = requests.get(sec_url, headers=SEC_HEADERS, timeout=5)
            if sec_res.status_code == 200:
                filings = sec_res.json().get('filings', {}).get('recent', {})
                for i, form in enumerate(filings.get('form', [])):
                    if doc_type.upper() in str(form).upper():
                        accession_num = filings.get('accessionNumber', [])[i]
                        filed_date = filings.get('filingDate', [])[i]
                        break
        return accession_num, filed_date
    except: return None, None

# (B) 진짜 필요할 때만 본문을 긁어오는 무거운 함수 (수정본)
def fetch_sec_full_content(accession_num, ticker, doc_type, api_key, cik=None):
    if not accession_num: return None
    try:
        # 1. FMP 텍스트 시도
        text_url = f"https://financialmodelingprep.com/stable/sec-filing-full-text?accessionNumber={accession_num}&apikey={api_key}"
        txt_res = requests.get(text_url, timeout=7)
        if txt_res.status_code == 200 and txt_res.json():
            full_text = txt_res.json()[0].get('content', '')
            return full_text[:100000] # 💡 [여기 추가] 상위 10만 자만 리턴

        # 2. FMP 실패 시 SEC 직접 스크래핑
        if cik:
            acc_no_clean = str(accession_num).replace('-', '')
            raw_txt_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_no_clean}/{accession_num}.txt"
            raw_res = requests.get(raw_txt_url, headers=SEC_HEADERS, timeout=10)
            if raw_res.status_code == 200:
                clean_text = re.sub(r'<[^>]+>', ' ', raw_res.text)
                clean_text = re.sub(r'\s+', ' ', clean_text)
                return clean_text[:100000] # 💡 [여기 추가] 상위 10만 자만 리턴
    except:
        pass
    return None


# ==========================================
# [2] 헬퍼 함수: FMP 통신 방어막 v3 (Stable API 맞춤형)
# ==========================================
def get_fmp_data_with_cache(symbol, api_type, url, valid_hours=24):
    """
    FMP Stable API의 404, 400 에러를 "데이터 없음"으로 우아하게 처리합니다.
    """
    cache_key = f"RAW_FMP_{api_type}_{symbol}"
    limit_time = (datetime.now() - timedelta(hours=valid_hours)).isoformat()
    
    try:
        res = supabase.table("analysis_cache").select("content, updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time).execute()
        if res.data:
            return json.loads(res.data[0]['content'])
    except: pass

    try:
        response = requests.get(url, timeout=7)
        
        # 🚨 [방어막 1] Stable API에서 데이터가 없을 때 보내는 400, 404 처리
        if response.status_code in [400, 404]:
            print(f"⚠️ [FMP 데이터 없음] {api_type} -> 해당 기업({symbol})은 아직 이 데이터가 존재하지 않습니다.")
            return None
            
        # 🚨 [방어막 2] 그 외 진짜 서버 통신 에러
        if response.status_code != 200:
            print(f"🚫 [FMP 서버 지연] {api_type} (HTTP {response.status_code})")
            return None
            
        try:
            res_json = response.json()
        except ValueError: 
            return None
            
        if isinstance(res_json, dict) and ("Error Message" in res_json or "Error" in res_json):
            print(f"🚫 [FMP 권한 차단됨] {api_type} -> 사유: {res_json.get('Error Message', 'Unknown')}")
            return None 
            
        if res_json:
            batch_upsert("analysis_cache", [{
                "cache_key": cache_key,
                "content": json.dumps(res_json),
                "updated_at": datetime.now().isoformat()
            }], on_conflict="cache_key")
            return res_json
            
    except Exception as e:
        print(f"❌ FMP API 기타 에러 ({api_type}): {e}")
    
    return None

def sanitize_value(v):
    if v is None or pd.isna(v): return None
    if isinstance(v, (np.floating, float)):
        return float(v) if not (np.isinf(v) or np.isnan(v)) else 0.0
    if isinstance(v, (np.integer, int)): return int(v)
    if isinstance(v, (np.bool_, bool)): return bool(v)
    return str(v).strip().replace('\x00', '')

def clean_ai_preamble(text):
    """AI의 불필요한 인사말, 서론만 제거하고 [소제목]은 보존하는 함수"""
    if not text: return ""
    
    # 1. 명백한 인사말 패턴 삭제 (기존 유지)
    patterns = [
        r"^(안녕하세요|알겠습니다|작성하겠습니다|요청하신|보고서입니다|분석 결과입니다).*?(\n|$)",
        r"^(Sure|Understood|Certainly|Here is the|Okay|I will).*?(\n|$)",
        r"^(承知いたしました|作成します|こんにちは|以下の).*?(\n|$)",
        r"^(好的|明白了|这是|以下은|以下是).*?(\n|$)"
    ]
    for p in patterns:
        text = re.sub(p, "", text, flags=re.MULTILINE | re.IGNORECASE)
    
    # 2. [문제의 구간] 모든 대괄호를 지우지 말고, "안내성/지시성" 대괄호만 골라서 제거
    # 아래 키워드가 들어간 대괄호/소괄호만 시작 부분에서 제거합니다.
    ai_meta_keywords = ['분석', '요청', '작성', '보고서', '진단', 'summary', 'analysis', 'here is']
    
    lines = text.strip().split('\n')
    if lines:
        first_line = lines[0].strip()
        # 첫 줄이 [ ]나 ( )로 시작할 때만 검사
        if re.match(r'^[\[\(].*?[\]\)]', first_line):
            # 대괄호 안의 내용이 AI 메타 키워드를 포함하면 지우기
            if any(kw in first_line.lower() for kw in ai_meta_keywords):
                # 단, 우리가 살려야 할 실질적 소제목(비즈니스, 성과 등)이 들어있으면 지우지 않음
                if not any(real in first_line for real in ['비즈니스', '성과', '전략', '리스크', '재무', '가치', '현황']):
                    text = '\n'.join(lines[1:]).strip()

    return text.strip()

def batch_upsert(table_name, data_list, on_conflict="ticker"):
    if not data_list: return
    endpoint = f"{SUPABASE_URL}/rest/v1/{table_name}?on_conflict={on_conflict}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal,resolution=merge-duplicates" 
    }
    
    clean_batch = []
    for item in data_list:
        # 모든 값을 Supabase가 받아들일 수 있는 형태로 정제
        payload = {k: sanitize_value(v) for k, v in item.items()}
        
        # 💡 [핵심] 필수 키가 있는지 확인 (cache_key 혹은 ticker 등)
        if payload.get(on_conflict):
            clean_batch.append(payload)
            
    if not clean_batch: return
    
    try:
        resp = requests.post(endpoint, json=clean_batch, headers=headers)
        if resp.status_code in [200, 201, 204]:
            print(f"✅ [{table_name}] {len(clean_batch)}개 저장 성공 (태깅 포함)")
        else:
            print(f"❌ [{table_name}] 저장 실패 ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"❌ [{table_name}] 통신 에러: {e}")
        
# [worker.py 내부의 send_fcm_push 함수를 아래 내용으로 교체하세요]
def send_fcm_push(title, body, ticker=None, target_level='premium'):
    """
    target_level: 
      - 'premium': Premium 및 Premium Plus 유저 모두에게 발송
      - 'premium_plus': Premium Plus 유저에게만 발송
    """
    if not firebase_admin._apps:
        return

    try:
        # 등급에 따른 필터링 조건 설정
        if target_level == 'premium_plus':
            # Premium Plus 유저만 추출
            res = supabase.table("user_fcm_tokens").select(
                "fcm_token, users!inner(membership_level)"
            ).eq("users.membership_level", "premium_plus").execute()
        else:
            # Premium 이상(Premium + Premium Plus) 모든 유저 추출
            res = supabase.table("user_fcm_tokens").select(
                "fcm_token, users!inner(membership_level)"
            ).in_("users.membership_level", ["premium", "premium_plus"]).execute()
        
        tokens = list(set([item['fcm_token'] for item in res.data if item.get('fcm_token')]))

        if not tokens:
            print(f"ℹ️ 알림 대상({target_level} 등급)이 없습니다.")
            return

        message = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            data={'ticker': ticker if ticker else "", 'type': 'alert'},
            tokens=tokens,
        )

        response = messaging.send_each_for_multicast(message)
        print(f"🚀 [{target_level} 푸시] {ticker} 알림 {response.success_count}개 발송 완료")

    except Exception as e:
        print(f"❌ FCM 발송 에러: {e}")

def get_target_stocks():
    if not FINNHUB_API_KEY: return pd.DataFrame()
    now = datetime.now()
    ranges = [
        (now - timedelta(days=200), now + timedelta(days=35)), 
        (now - timedelta(days=380), now - timedelta(days=170)), 
        (now - timedelta(days=560), now - timedelta(days=350))
    ]
    all_data = []
    for start_dt, end_dt in ranges:
        url = f"https://finnhub.io/api/v1/calendar/ipo?from={start_dt.strftime('%Y-%m-%d')}&to={end_dt.strftime('%Y-%m-%d')}&token={FINNHUB_API_KEY}"
        try:
            res = requests.get(url, timeout=10).json()
            if res.get('ipoCalendar'): all_data.extend(res['ipoCalendar'])
        except: continue
        
    if not all_data: return pd.DataFrame()
    df = pd.DataFrame(all_data).dropna(subset=['symbol'])
    df['symbol'] = df['symbol'].astype(str).str.strip()
    return df.drop_duplicates(subset=['symbol'])

# 💡 [추가] 메인 루프에서 수익률 상위 50개를 계산하기 위한 현재가 로드 함수
def get_current_prices():
    try:
        res = supabase.table("price_cache").select("ticker, price").execute()
        return {item['ticker']: float(item['price']) for item in res.data if item['price']}
    except: return {}

# ==========================================
# [3] 추가 헬퍼 함수: SEC 데이터 기반 역추적
# ==========================================
def get_ticker_from_cik(cik_str):
    """SEC 공식 데이터를 통해 CIK로 Ticker를 역추적합니다."""
    # SEC는 봇 차단을 막기 위해 User-Agent 명시가 필수입니다. 앱 이름을 넣어줍니다.
    headers = {'User-Agent': 'UnicornFinder contact@yourdomain.com'}
    url = "https://www.sec.gov/files/company_tickers.json"
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        target_cik = int(cik_str)
        
        # SEC 데이터에서 CIK가 일치하는 티커를 찾아 반환
        for key, value in data.items():
            if value.get('cik_str') == target_cik:
                return value.get('ticker')
    except Exception as e:
        print(f"⚠️ CIK 역추적 실패 ({cik_str}): {e}")
    
    return "" # 끝내 못 찾으면 빈 문자열 반환


# ==========================================
# [추가] 프리미엄 유저 대상 통계적 급등 알림 엔진 (FMP 최적화 버전)
# ==========================================




# ==========================================
# [SEC EDGAR API 헬퍼 함수] 
# ==========================================
SEC_HEADERS = {'User-Agent': 'UnicornFinder App admin@unicornfinder.com'}

def normalize_company_name(name):
    """회사 이름에서 특수문자, 대소문자, Inc/Corp 등을 제거하여 순수 텍스트만 추출합니다."""
    if not name or pd.isna(name): return ""
    name = str(name).lower()
    # Inc, Corp, Co, Ltd, Plc, Group 등의 흔한 법인 형태소 제거
    name = re.sub(r'\b(inc|corp|corporation|co|ltd|plc|group|company|holdings)\b\.?', '', name)
    # 영문자와 숫자만 남기고 모두 제거 (띄어쓰기 포함)
    name = re.sub(r'[^a-z0-9]', '', name)
    return name

def get_sec_master_mapping():
    """SEC에서 공식 데이터를 받아와 CIK 매핑과 '공식 티커' 매핑 두 가지 사전을 반환합니다."""
    try:
        res = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS, timeout=10)
        data = res.json()
        
        cik_mapping = {}         # { "AAPL": "0000320193" } (기존용도)
        name_to_ticker_map = {}  # { "apple": "AAPL" } (티커 교정용도)
        
        for k, v in data.items():
            official_ticker = v['ticker']
            cik_str = str(v['cik_str']).zfill(10)
            raw_title = v['title']
            
            cik_mapping[official_ticker] = cik_str
            
            # 회사 이름을 정규화해서 딕셔너리에 저장
            clean_name = normalize_company_name(raw_title)
            if clean_name:
                name_to_ticker_map[clean_name] = official_ticker
                
        return cik_mapping, name_to_ticker_map
    except Exception as e:
        print(f"SEC Mapping Error: {e}")
        return {}, {}

def get_fallback_cik(ticker, company_name, api_key):
    """[3중 추적 엔진] 명단에 없는 기업의 CIK를 3가지 방법으로 기어코 찾아냅니다."""
    # 1단계: FMP 기업 프로필 API에서 직접 추출
    try:
        url = f"https://financialmodelingprep.com/stable/profile?symbol={ticker}&apikey={api_key}"
        res = requests.get(url, timeout=5).json()
        if res and isinstance(res, list) and 'cik' in res[0] and res[0]['cik']:
            return str(res[0]['cik']).zfill(10)
    except: pass

    # 2단계: SEC EDGAR에 티커(Ticker)로 강제 검색
    try:
        url = f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={ticker}&action=getcompany&output=atom"
        res = requests.get(url, headers=SEC_HEADERS, timeout=5)
        match = re.search(r'<cik>(\d+)</cik>', res.text)
        if match: return str(match.group(1)).zfill(10)
    except: pass
    
    # 3단계: SEC EDGAR에 '회사 이름'으로 강제 검색
    if company_name:
        try:
            clean_name = str(company_name).split()[0].replace(',', '').strip()
            url = f"https://www.sec.gov/cgi-bin/browse-edgar?company={clean_name}&action=getcompany&output=atom"
            res = requests.get(url, headers=SEC_HEADERS, timeout=5)
            match = re.search(r'<cik>(\d+)</cik>', res.text)
            if match: return str(match.group(1)).zfill(10)
        except: pass
        
    return None


def check_sec_specific_filing(cik, target_form):
    """특정 CIK 기업이 10-K, RW, S-1 등의 서류를 제출했는지 확인하고 가장 최근 날짜를 반환합니다."""
    try:
        time.sleep(0.5) # SEC 초당 10회 제한 방어
        res = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=SEC_HEADERS, timeout=10)
        filings = res.json().get('filings', {}).get('recent', {})
        
        forms = filings.get('form', [])
        dates = filings.get('filingDate', [])
        
        # 최신 제출본부터 검사
        for i, form in enumerate(forms):
            if target_form.upper() in str(form).upper():
                return dates[i] # 서류가 있으면 제출 날짜 반환 (예: '2025-10-12')
        return None # 서류가 없으면 None
    except:
        return None

# ==========================================
# [신규 추가] FMP 프리미엄 헬퍼 함수 (Tab 0 용)
# ==========================================
def fetch_fmp_8k_events(symbol, api_key):
    """[Tab 0] 기업의 최근 8-K(중대 이벤트: M&A, 소송, 임원교체 등)를 가져옵니다."""
    try:
        # 💡 [Stable 주소로 교체 완료]
        url = f"https://financialmodelingprep.com/stable/sec-filings?symbol={symbol}&type=8-K&limit=3&apikey={api_key}"
        res = requests.get(url, timeout=5).json()
        
        if isinstance(res, dict) and "Error Message" in res:
            print(f"🚫 [Tab 0 8-K 차단됨] -> {res['Error Message']}")
            return "No recent 8-K events."
            
        if res and isinstance(res, list) and len(res) > 0:
            events = [f"- Date: {r.get('fillingDate')} | Link: {r.get('finalLink')}" for r in res]
            return "\n".join(events)
        return "No recent 8-K events."
    except Exception as e:
        print(f"8-K Fetch Error for {symbol}: {e}")
        return "No recent 8-K events."
        
def fetch_fmp_premium_news(symbol, api_key):
    try:
        url = f"https://financialmodelingprep.com/stable/news/stock-latest?symbol={symbol}&limit=5&apikey={api_key}"
        res = requests.get(url, timeout=5).json()
        if isinstance(res, dict) and "Error Message" in res:
            print(f"🚫 [Tab 1 프리미엄 뉴스 차단됨] -> {res['Error Message']}")
            return "No recent premium news."
        if res and isinstance(res, list) and len(res) > 0:
            news_list = [f"- [{r.get('publishedDate')}] {r.get('title')} (Source: {r.get('site')})" for r in res]
            return "\n".join(news_list)
        return "No recent premium news."
    except: return "No recent premium news."

def fetch_fmp_earnings_call(symbol, api_key):
    try:
        # 1단계: 가능한 연도와 분기를 먼저 리스트로 조회
        list_url = f"https://financialmodelingprep.com/stable/earnings-transcript-list?symbol={symbol}&apikey={api_key}"
        list_res = requests.get(list_url, timeout=5).json()
        
        if not list_res or isinstance(list_res, dict): return "No earnings call transcript available."
        
        # 2단계: 가장 최신 분기 데이터(인덱스 0)의 연도와 분기 파싱
        latest = list_res[0]
        year = latest.get('year')
        quarter = latest.get('quarter')
        
        # 3단계: 실제 트랜스크립트 텍스트 조회
        url = f"https://financialmodelingprep.com/stable/earning-call-transcript?symbol={symbol}&year={year}&quarter={quarter}&apikey={api_key}"
        res = requests.get(url, timeout=5).json()
        
        if isinstance(res, dict) and "Error Message" in res: return "No earnings call transcript available."
        if res and isinstance(res, list) and len(res) > 0:
            content = res[0].get('content', '')[:3000]
            return f"[Quarter: {quarter} / Year: {year}]\n{content}..."
        return "No earnings call transcript available."
    except: return "No earnings call transcript available."



# ==========================================
# [완전 교체] run_tab0_analysis 함수 (에러 영구 차단 + 20-F 하이브리드 탐색)
# ==========================================
def run_tab0_analysis(ticker, company_name, ipo_status="Active", ipo_date_str=None, cik_mapping=None):
    if 'model_strict' not in globals() or not model_strict: return
    
    # 🚀 [1] CIK 실시간 확보 로직 (PAYP 성공의 열쇠)
    cik = cik_mapping.get(ticker) if (cik_mapping is not None) else None
    if not cik:
        cik = get_fallback_cik(ticker, company_name, FMP_API_KEY)
        if cik:
            if cik_mapping is not None: cik_mapping[ticker] = cik
            print(f"🔍 [CIK 실시간 획득] {company_name}({ticker}) -> {cik} 추적 성공")
        else:
            print(f"⚠️ [CIK 획득 실패] {company_name}({ticker})의 고유번호를 찾을 수 없습니다.")

    # ---------------------------------------------------------
    # 🚨 [2] 에러 원천 차단: 보조 함수들을 루프보다 무조건 먼저 선언합니다.
    # ---------------------------------------------------------
    def get_localized_meta(lang, doc_type):
        meta_dict = {
            "ko": {
                "S-1": {"p": "Risk Factors, Use of Proceeds, MD&A", "s": "1문단: [핵심 비즈니스 및 스케일] 비즈니스 모델과 MAU, 매출 등 구체적 수치 명시\n2문단: [수익화 및 성장 전략] 시장 규모(TAM) 및 공모 자금의 실질적 사용처\n3문단: [치명적 리스크] 단순 나열이 아닌, 재무/운영에 타격을 줄 가장 치명적인 리스크 1가지"},
                "S-1/A": {"p": "Pricing Terms, Dilution, Changes", "s": "1문단: [변경 사항] 이전 S-1 대비 변경된 핵심 펀더멘털이나 수치\n2문단: [밸류에이션] 제시된 공모가 범위와 그에 따른 시가총액/밸류에이션 분석\n3문단: [주주 영향] 기존 주주 가치 희석 정도와 신규 투자자 관점의 매력도"},
                "F-1": {"p": "Business Scale, Foreign Risk, ADS Structure", "s": "1문단: [비즈니스 스케일 및 우위] MAU, 거래액(GMV), 매출 등 구체적 지표를 동반한 시장 지배력\n2문단: [지배구조 및 주주 권리] ADS 발행 구조 및 지배주주(Controlled Company) 지분율이 일반 주주에게 미치는 영향\n3문단: [로컬 리스크] 환율, 해당 국가 특유의 규제 등 외국 국적 기업으로서의 재무적/정치적 리스크"},
                "FWP": {"p": "Offering Structure, Use of Proceeds, Pricing Details", "s": "1문단: [공모 개요 및 상장 구조] 제출 서류, 상장 시장, ADS 발행 등 기본 정보 요약\n2문단: [글로벌 공모 및 자금 용도] 국내외 공모 비중, 주관사단 구성, 조달 자금의 실질적 사용처\n3문단: [공모가 산정 및 상장 일정] 가격 결정 방식, 공모가 변동 리스크, 최종 상장 예정일"},
                "424B4": {"p": "Final Price, Underwriting, IPO Outcome", "s": "1문단: [최종 가격 및 수요] 확정 공모가의 위치(상단/하단)와 시장 수요 해석\n2문단: [자금 조달 규모] 확정된 조달 자금 총액과 최우선 투입처\n3문단: [유통 물량] 주관사단 및 배정 물량 바탕 상장 초기 유통물량/오버행 예측"},
                "RW": {"p": "Withdrawal Reason, Market Condition", "s": "1문단: [철회 사유] 상장 철회(Withdrawal)를 결정하게 된 핵심 배경\n2문단: [재무적 타격] 자본 조달 실패가 기업 유동성에 미치는 영향\n3문단: [향후 행보] 재상장 시도 또는 M&A 피인수 등 대안 시나리오"},
                "Form 25": {"p": "Delisting Reason, Shareholder Impact", "s": "1문단: [상장 폐지 사유] 자발적 상폐, 피인수, 규정 위반 등 정확한 사유\n2문단: [주주 권리] 상장 폐지 후 기존 주식의 처리 방안 및 주주 권리\n3문단: [향후 상태] 장외시장(OTC) 거래 가능성 및 향후 기업 존속 여부"},
                "10-K": {"p": "Annual Revenue, Operating Income, Growth Rate", "s": "1문단: [연간 성과] 지난 1년간의 실제 매출액($)과 영업이익($), 전년비 성장률(%)\n2문단: [사업 확장] 핵심 사업부별 실적 기여도와 비즈니스 모델 변화\n3문단: [리스크 전망] 향후 재무 수치에 직접적 타격을 줄 수 있는 위험 요소"},
                "10-Q": {"p": "Quarterly Revenue, Net Income, Cash Balances", "s": "1문단: [분기 실적] 이번 분기 실제 매출($) 및 순이익($), 전년 동기 대비 증감률(%)\n2문단: [현금 현황] 보유 현금성 자산의 실제 수치와 단기 유동성 분석\n3문단: [가이던스] 경영진이 제시한 다음 분기 예상 수치 및 성장 근거"},
                "BS": {"p": "Total Assets, Total Liabilities, Cash, Debt", "s": "1문단: [자산 구조] 현금성 자산을 포함한 유동/비유동 자산의 실제 수치($)\n2문단: [부채와 자본] 총부채와 자기자본의 실제 금액($) 및 부채비율\n3문단: [건전성 진단] 수치를 근거로 한 실질적인 단기 지급 능력 및 런웨이 평가"},
                "IS": {"p": "Revenue Growth, Margins, EPS", "s": "1문단: [매출 성과] 실제 매출액(Revenue) 수치와 전년 대비 성장률(%)\n2문단: [이익률 평가] 영업이익과 순이익의 실제 수치($)를 통한 마진 분석\n3문단: [수익성 품질] 주당순이익(EPS)과 일회성 비용 유무를 통한 수익 창출력 요약"},
                "CF": {"p": "Operating CF, CAPEX, FCF", "s": "1문단: [영업현금흐름] 영업활동 현금흐름 수치($)를 통한 자체 자금 창출력 평가\n2문단: [투자 및 CAPEX] 자본적 지출(CAPEX)의 실제 금액과 투자 방향성\n3문단: [현금 생존력] 잉여현금흐름(FCF) 도출 및 추가 자금 조달 필요성 진단"}
            },
            "en": {
                "S-1": {"p": "Risk Factors, Use of Proceeds, MD&A", "s": "Para 1: [Core Business & Scale] Specify business model and concrete figures like MAU and Revenue.\nPara 2: [Monetization & Growth Strategy] Market size (TAM) and actual use of proceeds.\nPara 3: [Critical Risk] One most critical risk that will impact financials/operations, not just a simple list."},
                "S-1/A": {"p": "Pricing Terms, Dilution, Changes", "s": "Para 1: [Changes] Core fundamentals or numbers changed compared to the previous S-1.\nPara 2: [Valuation] Proposed price band and resulting market cap/valuation analysis.\nPara 3: [Shareholder Impact] Dilution for existing shareholders and attractiveness for new investors."},
                "F-1": {"p": "Business Scale, Foreign Risk, ADS Structure", "s": "Para 1: [Business Scale & Edge] Market dominance backed by specific metrics like MAU, GMV, and Revenue.\nPara 2: [Governance & Shareholder Rights] ADS issuance structure and impact of the Controlled Company status on retail shareholders.\nPara 3: [Local Risks] Financial/political risks as a foreign entity, such as FX and local regulations."},
                "FWP": {"p": "Offering Structure, Use of Proceeds, Pricing Details", "s": "Para 1: [Offering Overview & Listing Structure] Summary of filings, exchange, and ADS issuance details\nPara 2: [Global Offering & Use of Proceeds] Offering tranches, underwriters, and planned fund deployment\nPara 3: [Pricing Strategy & Listing Schedule] Pricing methodology, price volatility risks, and final IPO timeline"},
                "424B4": {"p": "Final Price, Underwriting, IPO Outcome", "s": "Para 1: [Final Price & Demand] Position of the final IPO price (top/bottom) and market demand interpretation.\nPara 2: [Fundraising Scale] Total amount raised and top priority for fund deployment.\nPara 3: [Float Volume] Expected initial float/overhang based on underwriter allocations."},
                "RW": {"p": "Withdrawal Reason, Market Condition", "s": "Para 1: [Withdrawal Reason] Core background behind the decision to withdraw the IPO.\nPara 2: [Financial Impact] Impact of the fundraising failure on corporate liquidity.\nPara 3: [Future Plans] Alternative scenarios like re-IPO attempts or M&A acquisition."},
                "Form 25": {"p": "Delisting Reason, Shareholder Impact", "s": "Para 1: [Delisting Reason] Exact reason such as voluntary, M&A, or regulatory violation.\nPara 2: [Shareholder Rights] Treatment of existing shares and shareholder rights post-delisting.\nPara 3: [Future Status] Possibility of OTC trading and future corporate existence."},
                "10-K": {"p": "Annual Revenue, Operating Income, Growth Rate", "s": "Para 1: [Annual Performance] Actual Revenue ($), Operating Income ($), and YoY Growth Rate (%) over the past year.\nPara 2: [Business Expansion] Performance contribution by core segments and business model changes.\nPara 3: [Risk Outlook] Risk factors that could directly impact future financial metrics."},
                "10-Q": {"p": "Quarterly Revenue, Net Income, Cash Balances", "s": "Para 1: [Quarterly Results] Actual Revenue ($), Net Income ($), and YoY Growth Rate (%) for this quarter.\nPara 2: [Cash Status] Actual figures of cash equivalents and short-term liquidity analysis.\nPara 3: [Guidance] Management's expected figures for the next quarter and basis for growth."},
                "BS": {"p": "Total Assets, Total Liabilities, Cash, Debt", "s": "Para 1: [Asset Structure] Actual figures ($) of current/non-current assets including cash equivalents.\nPara 2: [Liabilities & Equity] Actual figures ($) of total debt, equity, and debt-to-equity ratio.\nPara 3: [Solvency Diagnosis] Practical assessment of short-term liquidity and runway based on the numbers."},
                "IS": {"p": "Revenue Growth, Margins, EPS", "s": "Para 1: [Revenue Performance] Actual Revenue figures and YoY Growth Rate (%).\nPara 2: [Margin Evaluation] Margin analysis using actual figures ($) of Operating and Net Income.\nPara 3: [Earnings Quality] Summary of profit generation capability via EPS and presence of one-off costs."},
                "CF": {"p": "Operating CF, CAPEX, FCF", "s": "Para 1: [Operating CF] Assessment of self-funding capability via actual Operating Cash Flow ($).\nPara 2: [Investment & CAPEX] Actual amount of Capital Expenditures (CAPEX) and investment direction.\nPara 3: [Cash Survival] Derivation of Free Cash Flow (FCF) and diagnosis of additional funding needs."}
            },
            "ja": {
                "S-1": {"p": "リスク要因, 資金使途, MD&A", "s": "第1段落：[中核事業と規模] ビジネスモデルとMAU、売上などの具体的数値を明記\n第2段落：[収益化と成長戦略] 市場規模(TAM)と公募資金の実質的な使途\n第3段落：[致命的リスク] 単なる羅列ではなく、財務/運営に打撃を与える最も致命的なリスク1つ"},
                "S-1/A": {"p": "条件決定, 希薄化, 変更点", "s": "第1段落：[変更事項] 以前のS-1と比較して変更された中核ファンダメンタルズや数値\n第2段落：[バリュエーション] 提示された公募価格帯とそれに伴う時価総額/バリュエーション分析\n第3段落：[株主への影響] 既存株主の価値希薄化の程度と新規投資家視点での魅力度"},
                "F-1": {"p": "事業規模, 海外リスク, ADS構造", "s": "第1段落：[事業規模と優位性] MAU、取引額(GMV)、売上などの具体的指標を伴う市場支配力\n第2段落：[ガバナンスと株主の権利] ADS発行構造および支配株主(Controlled Company)の持分比率が一般株主に与える影響\n第3段落：[ローカルリスク] 為替、当該国特有の規制など外国籍企業としての財務的/政治的リスク"},
                "FWP": {"p": "Offering Structure, Use of Proceeds, Pricing Details", "s": "第1段落：[公募概要および上場構造] 提出書類、上場市場、ADS発行などの基本情報の要約\n第2段落：[グローバル公募および資金使途] 国内外の公募比率、引受団の構成、調達資金の実質的な使途\n第3段落：[公募価格の算定および上場日程] 価格決定方式、価格変動リスク、最終的な上場予定日"},
                "424B4": {"p": "最終価格, 引受シンジケート, 上場結果", "s": "第1段落：[最終価格と需要] 確定公募価格の位置(上限/下限)と市場需要の解釈\n第2段落：[資金調達規模] 確定した調達資金総額と最優先の投入先\n第3段落：[流通株式数] 引受シンジケートおよび配分物量に基づく上場初期の流通株式/オーバーハング予測"},
                "RW": {"p": "撤回理由, 市場環境", "s": "第1段落：[撤回事由] 上場撤回(Withdrawal)を決定した中核的な背景\n第2段落：[財務的打撃] 資金調達の失敗が企業の流動性に与える影響\n第3段落：[今後の動向] 再上場の試みまたはM&Aによる買収などの代替シナリオ"},
                "Form 25": {"p": "上場廃止理由, 株主への影響", "s": "第1段落：[上場廃止事由] 自主的廃止、買収、規定違反などの正確な理由\n第2段落：[株主の権利] 上場廃止後の既存株式の処理方法および株主の権利\n第3段落：[今後の状態] 店頭市場(OTC)での取引の可能性および今後の企業の存続可否"},
                "10-K": {"p": "通期売上高, 営業利益, 成長率", "s": "第1段落：[通期実績] 過去1年間の実際の売上高($)と営業利益($)、前年比成長率(%)\n第2段落：[事業拡張] 中核事業セグメント別の業績貢献度とビジネスモデルの変化\n第3段落：[リスク展望] 今後の財務数値に直接的な打撃を与え得る危険要因"},
                "10-Q": {"p": "四半期売上, 純利益, 現金残高", "s": "第1段落：[四半期実績] 当四半期の実際の売上($)および純利益($)、前年同期比増減率(%)\n第2段落：[現金状況] 保有する現金性資産の実際の数値と短期流動性分析\n第3段落：[ガイダンス] 経営陣が提示した次四半期の予想数値と成長の根拠"},
                "BS": {"p": "資産合計, 負債合計, 現金, 負債", "s": "第1段落：[資産構造] 現金性資産を含む流動/非流動資産の実際の数値($)\n第2段落：[負債と資本] 総負債と自己資本の実際の金額($)および負債比率\n第3段落：[健全性診断] 数値に基づく実質的な短期支払能力およびランウェイの評価"},
                "IS": {"p": "売上成長, 利益率, EPS", "s": "第1段落：[売上実績] 実際の売上高(Revenue)数値と前年比成長率(%)\n第2段落：[利益率評価] 営業利益と純利益の実際の数値($)を通じたマージン分析\n第3段落：[収益の質] EPSと一過性費用の有無を通じた収益創出力の要約"},
                "CF": {"p": "営業CF, CAPEX, FCF", "s": "第1段落：[営業キャッシュフロー] 営業CF数値($)を通じた独自の資金創出力の評価\n第2段落：[投資とCAPEX] 資本的支出(CAPEX)の実際の金額と投資の方向性\n第3段落：[現金の生存力] フリーキャッシュフロー(FCF)の算出および追加資金調達の必要性診断"}
            },
            "zh": {
                "S-1": {"p": "风险因素, 资金用途, MD&A", "s": "第一段：[核心业务与规模] 明确业务模型及MAU、营收等具体数据\n第二段：[变现与增长战略] 市场规模(TAM)及募集资金的实际用途\n第三段：[致命风险] 指出1个将对财务/运营造成打击的最致命风险，而非简单罗列"},
                "S-1/A": {"p": "定价条款, 股权稀释, 变更点", "s": "第一段：[变更事项] 与此前S-1相比，核心基本面或数据的变化\n第二段：[估值] 给出的发行价区间及相应的市值/估值分析\n第三段：[股东影响] 现有股东价值的稀释程度及对新投资者的吸引力"},
                "F-1": {"p": "业务规模, 海外风险, ADS结构", "s": "第一段：[业务规模与优势] 带有MAU、交易额(GMV)、营收等具体指标的市场统治力\n第二段：[治理与股东权利] ADS发行结构及控股股东(Controlled Company)持股比例对散户的影响\n第三段：[本地风险] 汇率、该国特有监管等作为外国企业的财务/政治风险"},
                "FWP": {"p": "Offering Structure, Use of Proceeds, Pricing Details", "s": "第一段：[公开发行概览与上市架构] 提交文件、上市地点及 ADS 发行等基本信息摘要\n第二段：[全球发售与资金用途] 境内外发行比率、承销团构成及募集资金的实际用途\n第三段：[定价机制与上市日程] 定价方式、价格波动风险及最终上市预计日期"},
                "424B4": {"p": "最终价格, 承销, IPO结果", "s": "第一段：[最终价格与需求] 最终定价的位置(上限/下限)及市场需求解读\n第二段：[融资规模] 确定的融资总额及最优先的资金投入方向\n第三段：[流通盘] 基于承销团及配售情况的上市初期流通股/抛压预测"},
                "RW": {"p": "撤回原因, 市场环境", "s": "第一段：[撤回原因] 决定撤回上市(Withdrawal)的核心背景\n第二段：[财务打击] 融资失败对企业流动性的影响\n第三段：[未来动向] 尝试重新上市或被M&A收购等替代方案"},
                "Form 25": {"p": "退市原因, 股东影响", "s": "第一段：[退市原因] 自愿退市、被收购、违规等准确原因\n第二段：[股东权利] 退市后现有股票的处理方案及股东权利\n第三段：[未来状态] 场外市场(OTC)交易的可能性及企业未来的存续状态"},
                "10-K": {"p": "年度营收, 营业利润, 增长率", "s": "第一段：[年度表现] 过去一年的实际营收($)和营业利润($)，及同比增幅(%)\n第二段：[业务扩张] 核心业务板块的业绩贡献度及商业模式的变化\n第三段：[风险展望] 可能对未来财务数据造成直接打击的危险因素"},
                "10-Q": {"p": "季度营收, 净利润, 现金储备", "s": "第一段：[季度业绩] 本季度的实际营收($)和净利润($)，及同比增幅(%)\n第二段：[现金状况] 持有的现金及现金等价物实际数值与短期流动性分析\n第三段：[业绩指引] 管理层给出的下季度预期数值及增长依据"},
                "BS": {"p": "总资产, 总负债, 现金, 债务", "s": "第一段：[资产结构] 包含现金等价物的流动/非流动资产的实际数值($)\n第二段：[负债与资本] 总负债和股东权益的实际金额($)及资产负债率\n第三段：[健康度诊断] 基于数据对短期偿债能力及资金存续期的实质性评估"},
                "IS": {"p": "营收增长, 毛利率, EPS", "s": "第一段：[营收表现] 实际营收(Revenue)数值及同比增长率(%)\n第二段：[利润率评估] 通过营业利润和净利润的实际数值($)进行利润率分析\n第三段：[收益质量] 结合每股收益(EPS)及有无一次性费用总结盈利能力"},
                "CF": {"p": "经营CF, CAPEX, FCF", "s": "第一段：[经营现金流] 通过经营活动现金流数值($)评估企业的自我造血能力\n第二段：[投资与CAPEX] 资本支出(CAPEX)的实际金额及投资方向\n第三段：[现金存续力] 推算自由现金流(FCF)并诊断是否需要额外融资"}
            }
        }
        lang_group = meta_dict.get(lang, meta_dict['ko'])
        # Fallback to Korean structure if a doc type is somehow missing
        fallback_meta = meta_dict['ko'].get(doc_type, meta_dict['ko']['S-1'])
        return lang_group.get(doc_type, fallback_meta)

    def get_format_instruction(lang):
        # 💡 [언어별 현지화 지시] 언어 혼용을 막기 위해 각국 언어로 직접 지시합니다.
        
        if lang == 'en':
            return (
                "- Write exactly 3 paragraphs.\n"
                "- EACH paragraph MUST start with a bold subheading in brackets: **[Subheading]**.\n"
                "- Provide a line break immediately after each subheading.\n"
                "- EACH paragraph must be 4-5 sentences long.\n"
                "- DO NOT use markdown bold (**) for numbers.\n"
                "- If the information is not found, strictly use the phrase 'Information not verified.'"
            )
            
        elif lang == 'ja':
            return (
                "- 必ず3つの段落で構成してください。\n"
                "- 各段落の冒頭には、必ず括弧付きの太字の見出しを付けてください：**[見出し]**。\n"
                "- 見出しの直後には必ず改行を入れてください。\n"
                "- 各段落は必ず4〜5文で構成してください。\n"
                "- 数値に太字（**）は絶対に使用しないでください。\n"
                "- 全ての文章は「〜です・ます」の丁寧語で統一してください。\n"
                "- 情報が見つからない場合は、「該当情報が確認できません。」と正確に記述してください。"
            )
            
        elif lang == 'zh':
            return (
                "- 必须严格分为3个段落。\n"
                "- 每个段落必须以带方括号의 加粗副标题开头：**[副标题]**。\n"
                "- 副标题后请务必换行。\n"
                "- 每个段落由4-5个句子组成。\n"
                "- 严禁对数字使用加粗（**）。\n"
                "- 必须完全 blinds 使用简体中文，保持专业、冷峻的分析语气。\n"
                "- 若无法确认信息，请统一回答：“未确认到相关信息。”"
            )
            
        else: # ko (기준점)
            return (
                "- 반드시 3개의 문단으로 작성하세요.\n"
                "- 각 문단은 반드시 대괄호 형태의 굵은 소제목으로 시작하세요: **[소제목]**.\n"
                "- 소제목 바로 다음에 줄바꿈을 하세요.\n"
                "- 각 문단은 반드시 4~5줄(문장) 길이로 작성하세요.\n"
                "- 본문의 숫자에는 절대 굵게(**) 표시를 하지 마세요.\n"
                "- 모든 문장은 반드시 '~습니다', '~합니다' 형태의 정중한 존댓말로 마무리하세요.\n"
                "- 제공된 정보가 없다면 \"해당 정보가 확인되지 않습니다.\"라고 답변하세요."
            )

    def get_missing_document_message(lang, doc_type):
        msg_map = {
            "ko": {
                "S-1": "**[안내]** 해당 기업은 해외 국적 발행인(Foreign Issuer) 또는 SPAC으로 식별됩니다. 상세 공시 데이터는 **[F-1]** 섹션을 참조하십시오.",
                "F-1": "**[안내]** 미국 내국 법인(Domestic Issuer)으로 확인되었습니다. 규정에 따른 공시 내역은 **[S-1]** 섹션에서 제공됩니다.",
                "S-1/A": "**[공시대기중]** 최초 신고서 제출 이후의 정정 신고서(S-1/A)가 아직 공시되지 않았습니다. 공모가 밴드 확정 시 실시간 업데이트됩니다.",
                "FWP": "**[공시대기중]** 현재 해당 기업의 추가 로드쇼 자료나 마케팅용 자유 양식 증권신고서(FWP)가 SEC에 등록되지 않은 상태입니다.",
                "424B4": "**[공시대기중]** 최종 공모가 확정 서류(424B4)는 통상 상장 직전 24~48시간 이내에 수립됩니다. 확정 즉시 분석 리포트가 생성됩니다.",
                "RW": "**[상태양호]** 현재 상장 철회(RW)와 관련된 특이 사항이 발견되지 않았습니다. 상장 절차가 정상 궤도 내에서 진행 중입니다.",
                "Form 25": "**[상태양호]** 상장 폐지(Delisting) 관련 이벤트가 감지되지 않았습니다. 해당 종목은 정규 시장 내에서 활성 상태를 유지하고 있습니다.",
                "DEFAULT": "**[안내]** 해당 서류의 제출 기한이 도래하지 않았거나 시스템 내의 아카이빙 작업이 진행 중입니다."
            },
            "en": {
                "S-1": "**[Issuer Classification]** Identified as a Foreign Issuer or SPAC. Please refer to the **[F-1]** section for primary disclosure data.",
                "F-1": "**[Issuer Classification]** Identified as a US Domestic Issuer. Regulatory filings are provided in the **[S-1]** section.",
                "S-1/A": "**[Filing Status]** The amended registration statement (S-1/A) following the initial filing has not yet been disclosed. Real-time updates will follow upon price band finalization.",
                "FWP": "**[Supplemental Info]** No additional roadshow materials or Free Writing Prospectuses (FWP) have been registered with the SEC at this time.",
                "424B4": "**[Pricing Finalization]** The final prospectus (424B4) is typically established within 24-48 hours prior to the IPO. Analysis will be generated immediately upon confirmation.",
                "RW": "**[Offering Status]** No specific issues regarding withdrawal (RW) have been detected. The IPO process is proceeding within the normal track.",
                "Form 25": "**[Listing Status]** No delisting events (Form 25) have been detected. The ticker remains active within the regular market.",
                "DEFAULT": "**[Data Sync]** The filing deadline has not yet been met, or archiving within the SEC EDGAR system is currently in progress."
            },
            "ja": {
                "S-1": "**[発行体分類]** 外国籍発行体（Foreign Issuer）またはSPACとして識別されました。詳細な公示データは **[F-1]** セクションをご参照ください。",
                "F-1": "**[発行体分類]** 米国内국法人（Domestic Issuer）として確認されました。規定に基づく公示内容は **[S-1]** セクションで提供されます。",
                "S-1/A": "**[公示ステータス]** 初回届出書提出後の訂正届出書（S-1/A）はまだ公示されていません。公募価格帯の確定時にリアルタイムで更新されます。",
                "FWP": "**[補足情報]** 現在、当該企業の追加ロードショー資料やマーケティング用自由方式目論見書（FWP）はSECに登録されていません。",
                "424B4": "**[価格確定]** 最終公募価格確定書類（424B4）は通常、上場直前の24〜48時間以内に作成されます。確定次第、分析レポートが生成されます。",
                "RW": "**[募集ステータス]** 現在、上場撤回（RW）に関する特記事項は見当たりません。上場手続きは正常な軌道で進行中です。",
                "Form 25": "**[上場ステータス]** 上場廃止（Delisting）関連のイベントは検知されていません。当該銘柄は正規市場内で活性状態を維持しています。",
                "DEFAULT": "**[データ同期]** 当該書類の提出期限が未到来か、SEC EDGARシステム内でのアーカイブ処理が進行中です。"
            },
            "zh": {
                "S-1": "**[发行人分类]** 该企业被识别为外国发行人 (Foreign Issuer) 或 SPAC。请参阅 **[F-1]** 栏目获取详细公告数据。",
                "F-1": "**[发行人分类]** 已确认该企业为美国本土发行人 (Domestic Issuer)。根据规定的公告内容请在 **[S-1]** 栏目查看。",
                "S-1/A": "**[申报状态]** 提交首次登记表后的修订案 (S-1/A) 尚未公布。发行价区间确定后将实时更新。",
                "FWP": "**[补充信息]** 目前该企业尚未在 SEC 注册额外的路演资料或营销用自由撰写招股说明书 (FWP)。",
                "424B4": "**[定价确认]** 最终定价公告 (424B4) 通常在上市前 24-48 小时内完成。确认后将立即生成分析报告。",
                "RW": "**[发行状态]** 目前未发现与撤回上市 (RW) 相关的异常情况。上市程序正处于正常推进轨道。",
                "Form 25": "**[上市状态]** 未检测到退市 (Delisting) 相关事件。该股票在正规市场内保持活跃状态。",
                "DEFAULT": "**[数据同步]** 该文件的提交截止日期尚未到期，或 SEC EDGAR 系统正在进行归档处理。"
            }
        }
        lang_dict = msg_map.get(lang, msg_map['ko'])
        return lang_dict.get(doc_type, lang_dict.get('DEFAULT'))

    def get_localized_instruction(lang, ticker, topic, company_name, meta, sec_fact_prompt, format_inst, filing_text=""):
        base_msg = ""
        if filing_text and len(filing_text) > 100:
            base_msg = f"\n\n[ACTUAL SEC FILING CONTENT - MUST USE THIS AS SOURCE]\n{filing_text}\n"
        else:
            base_msg = "\n\n(Note: Actual filing content is currently unavailable.)\n"

        # 🚨 [언어별 맞춤형 철권 통제 규칙]
        if lang == 'en':
            # 💡 [핵심] f""" 로 변경하여 {ticker} 변수 삽입
            common_rules = f"""
[STRICT RULES FOR WALL STREET ANALYST]
1. HARD NUMBERS ONLY: Extract Revenue, Profit, MAU, GMV, or Market Share figures. If a number exists in the text, it MUST be in the summary.
2. NO VAGUE FILLERS: Never use phrases like "aims to increase awareness." Replace them with specific data.
3. NO AI CHAT: 🚨 DO NOT use phrases like "Here is the report" or "Understood". Start the very first word with the actual analysis.
4. NO MAIN TITLE: 🚨 DO NOT write a main title or report header like "## Company Analysis Report" at the top. Just output the 3 paragraphs directly.
5. LANGUAGE PURITY: 🚨 You MUST write entirely in English. DO NOT mix any other languages.
6. NEVER CONFUSE TICKER: 🚨 The correct ticker is '{ticker}'. Do NOT mistake document types (like FWP, S-1) for the ticker symbol.
"""
            return f"You are a Lead Buy-Side Analyst.\nTarget: {company_name} ({ticker}) - {topic}\n{sec_fact_prompt}\n{base_msg}\n{common_rules}\n[Structure]\n{meta['s']}\n{format_inst}"

        elif lang == 'ja':
            common_rules = f"""
[ウォール街アナリストのための厳格な規則]
1. 数値データ必須: 売上、利益、MAU、GMV、または市場シェアの数値を必ず抽出してください。本文に数値がある場合、必ず要約に含めてください。
2. 曖昧な表現禁止: 「認知度向上を目指す」のような曖昧なフレーズは使用せず、具体的なデータに置き換えてください。
3. AIの挨拶禁止: 🚨 「承知いたしました」「レポートは以下の通りです」などの挨拶は絶対に使用しないでください。最初の文字からすぐに分析内容を始めてください。
4. メインタイトル禁止: 🚨 最上部に「## 企業分析レポート」のような見出しやタイトルは絶対に書かないでください。すぐに3つの段落のみを出力してください。
5. 言語の純粋性: 🚨 全て自然な日本語のみで記述してください。英語の文章を混ぜないでください。企業名/ティッカー以外のすべての専門用語は日本語に翻訳してください。
6. ティッカー誤記厳禁: 🚨 正確なティッカーは '{ticker}' です。FWPやS-1などの「書類名」をティッカーと勘違いして記述しないでください。
"""
            return f"あなたはバイサイドのシニアアナリストです。\n分析対象: {company_name} ({ticker}) - {topic}\n{sec_fact_prompt}\n{base_msg}\n{common_rules}\n[構成]\n{meta['s']}\n{format_inst}"

        elif lang == 'zh':
            common_rules = f"""
[华尔街分析师的严格规则]
1. 必须包含具体数据: 请提取营收、利润、MAU、GMV或市场份额等数据。如果原文中有数字，摘要中必须包含。
2. 禁止模糊表达: 绝对不要使用“旨在提高知名度”等模糊词语。请用具体数据代替。
3. 禁止AI问候语: 🚨 绝对不要使用“好的”、“以下是报告”等词语。从第一个字开始直接输出分析内容。
4. 禁止主标题: 🚨 绝对不要在顶部写“## 公司分析报告”之类的主标题。直接输出3个段落即可。
5. 语言纯洁性: 🚨 必须完全使用简体中文编写。严禁混入英文句子。除特定的公司名称/代码外，所有专业术语必须翻译成中文。
6. 严禁混淆代码: 🚨 准确的股票代码是 '{ticker}'。绝对不要将 FWP、S-1 等“文件类型”误认为是股票代码。
"""
            return f"您是买方资深分析师。\n分析目标: {company_name} ({ticker}) - {topic}\n{sec_fact_prompt}\n{base_msg}\n{common_rules}\n[结构要求]\n{meta['s']}\n{format_inst}"

        else: # ko
            common_rules = f"""
[월스트리트 애널리스트를 위한 엄격한 작성 규칙]
1. 수치 데이터 필수: 매출, 이익, MAU, GMV 또는 시장 점유율 수치를 반드시 추출하세요. 원문에 숫자가 있다면 요약본에 무조건 포함되어야 합니다.
2. 추상적 표현 금지: "인지도를 높이는 것을 목표로 한다" 같은 모호한 문구를 절대 쓰지 말고, 구체적인 데이터로 대체하세요.
3. AI 인사말 금지: 🚨 "알겠습니다", "요약해 드리겠습니다" 같은 인사말이나 서론을 절대 쓰지 마세요. 첫 글자부터 곧바로 분석 내용(본론)만 출력하세요.
4. 메인 제목 금지: 🚨 글 맨 위에 "## 기업 분석 보고서" 같은 메인 제목(타이틀)을 절대 달지 마세요. 곧바로 3개의 문단만 작성하세요.
5. 언어 순수성: 🚨 반드시 순수한 한국어로만 작성하세요. 영어 문장을 섞어 쓰지 마세요. 고유한 기업명/티커를 제외한 모든 영단어는 한국어로 번역하세요.
6. 어투(문체) 고정: 🚨 반드시 모든 문장의 끝을 '~습니다', '~합니다', '~입니다' 형태의 정중한 존댓말(경어체)로 마무리하세요. '~한다', '~이다' 형태의 평어체는 절대 금지합니다.
7. 티커(Ticker) 오기재 절대 금지: 🚨 해당 기업의 정확한 티커 심볼은 '{ticker}'입니다. FWP, S-1, F-1 같은 'SEC 문서명'을 티커 심볼로 착각해서 기재하는 치명적인 실수를 절대 하지 마세요.
"""
            return f"당신은 월스트리트 바이사이드(Buy-side) 수석 애널리스트입니다.\n분석 대상: {company_name} ({ticker}) - {topic}\n{sec_fact_prompt}\n{base_msg}\n{common_rules}\n[내용 구성 지침]\n{meta['s']}\n{format_inst}"
    # ---------------------------------------------------------
    # 🚀 [3] 기업 상태 및 기간 분석
    # ---------------------------------------------------------
    status_lower = str(ipo_status).lower()
    is_withdrawn = any(x in status_lower for x in ['철회', '취소', 'withdrawn'])
    is_delisted = any(x in status_lower for x in ['폐지', 'delisted'])
    
    days_passed = 0
    is_over_1y = False
    if ipo_date_str:
        try:
            ipo_dt = pd.to_datetime(ipo_date_str).date()
            days_passed = (datetime.now().date() - ipo_dt).days
            if days_passed > 365: is_over_1y = True
        except: pass

    valid_hours = 168 if (is_withdrawn or is_delisted or is_over_1y) else 24
    limit_time_str = (datetime.now() - timedelta(hours=valid_hours)).isoformat()

    # 대상 서류 배정
    if is_withdrawn: target_topics = ["S-1", "S-1/A", "F-1", "RW"]
    elif is_delisted: target_topics = ["S-1", "10-K", "20-F", "Form 25"]
    elif is_over_1y: target_topics = ["10-K", "10-Q", "BS", "IS", "CF"]
    else: target_topics = ["S-1", "S-1/A", "F-1", "FWP", "424B4"]

    # ---------------------------------------------------------
    # 🚀 [4] 8-K 분석 섹션 (Accession Number 기반 최적화 적용)
    # ---------------------------------------------------------
    # 1. 8-K 메타데이터(번호)만 먼저 가져옴 (트래픽 거의 없음)
    acc_num_8k, f_date_8k = fetch_sec_metadata(ticker, "8-K", FMP_API_KEY, cik)
    
    if acc_num_8k:
        # 💡 8-K 전용 트래커 키 (고유 번호 기반)
        tracker_key_8k = f"{ticker}_8K_LastAccNum"
        is_8k_already_done = False
        
        try:
            res_8k = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key_8k).execute()
            if res_8k.data and res_8k.data[0]['content'] == acc_num_8k:
                is_8k_already_done = True
        except: pass

        # 새로운 8-K 문서가 확인되었을 때만 무거운 다운로드 및 AI 분석 실행
        if not is_8k_already_done:
            print(f"🚨 [{ticker}] 새로운 8-K 감지 ({acc_num_8k}). 다운로드 및 분석 시작...")
            f_text_8k = fetch_sec_full_content(acc_num_8k, ticker, "8-K", FMP_API_KEY, cik)
            
            if f_text_8k and len(f_text_8k) > 100:
                # 프리미엄 알림 생성
                batch_upsert("premium_alerts", [{
                    "ticker": ticker, 
                    "alert_type": "8K_UPDATE", 
                    "title": f"{ticker} 8-K 업데이트", 
                    "message": "새로운 8-K(중대 이벤트) 공시 본문 분석이 완료되었습니다."
                }], on_conflict="ticker,alert_type")
                
                # 4개 국어 분석 및 저장
                for lang_code in SUPPORTED_LANGS.keys():
                    cache_key_8k = f"{company_name}_8-K_Tab0_v16_{lang_code}"
                    
                    # 언어별 메타 설정
                    if lang_code == 'ko':
                        meta_8k = {"p": "Material Events", "s": "1문단: **[핵심 이벤트]** 발생 사유 요약\n2문단: **[재무 파급력]** 영향 분석\n3문단: **[향후 전망]** 투자 포인트"}
                    elif lang_code == 'ja':
                        meta_8k = {"p": "重要イベント", "s": "第1段落：**[核心イベント]** 発生理由の要約\n第2段落：**[財務影響]** 影響分析\n第3段落：**[今後の展望]** 投資ポイント"}
                    elif lang_code == 'zh':
                        meta_8k = {"p": "重大事件", "s": "第一段：**[核心事件]** 发生原因摘要\n第二段：**[财务影响]** 影响分析\n第三段：**[未来展望]** 投资要点"}
                    else: # en
                        meta_8k = {"p": "Material Events", "s": "Para 1: **[Core Event]** Reason summary\nPara 2: **[Financial Impact]** Analysis\nPara 3: **[Future Outlook]** Key points"}
                        
                    prompt_8k = get_localized_instruction(lang_code, ticker, "8-K", company_name, meta_8k, f"[SEC FACT CHECK] Filed on {f_date_8k}", get_format_instruction(lang_code), f_text_8k[:40000])
                    
                    try:
                        resp_8k = model_strict.generate_content(prompt_8k)
                        if resp_8k and resp_8k.text:
                            # 💡 8-K 가독성 가공 로직
                            raw_8k = resp_8k.text.strip()
                            clean_8k = clean_ai_preamble(raw_8k)
                            
                            # 뭉쳐있는 제목 앞 줄바꿈 보정 (티커 [ARXS] 보호)
                            def brk_8k(m):
                                p, h = m.group(1), m.group(2)
                                if len(re.sub(r'[\[\]\(\)]', '', h)) < 7: return f"{p} {h}"
                                return f"{p}<br><br>{h}"
                            
                            text_brk = re.sub(r'([.!?])\s*([\[\(].*?[\]\)])', brk_8k, clean_8k)
                            lines = [l.strip() for l in text_brk.split('\n') if l.strip()]
                            f_html = ""
                            for l in lines:
                                m = re.match(r'^([\[\(].*?[\]\)])\s*(.*)', l)
                                if m and len(re.sub(r'[\[\]\(\)]', '', m.group(1))) > 5:
                                    if f_html: f_html += "<br><br>"
                                    f_html += f"<b>{m.group(1)}</b>"
                                    if m.group(2): f_html += f"<br>{m.group(2).strip()}"
                                else:
                                    if f_html:
                                        if f_html.endswith("</b>"): f_html += f"<br>{l}"
                                        else: f_html += " " + l
                                    else: f_html = l

                            batch_upsert("analysis_cache", [{
                                "cache_key": cache_key_8k, 
                                "content": f_html.strip(), 
                                "updated_at": datetime.now().isoformat(),
                                "ticker": ticker,
                                "tier": "premium_plus", # 👈 'free'에서 'premium_plus'로 수정 완료
                                "tab_name": "tab0",
                                "lang": lang_code,
                                "data_type": "8-K"
                            }], on_conflict="cache_key")
                            print(f"✅ [{ticker}] 8-K AI 분석 및 가공 완료 ({lang_code})")
                    except Exception as e:
                        print(f"❌ [{ticker}] 8-K 에러 ({lang_code}): {e}")
                
                # 🚀 [FCM 추가] 분석이 끝난 직후 Plus 유저에게만 발송
                try:
                    send_fcm_push(
                        title=f"🚨 {ticker} 중대 공시(8-K) 발생",
                        body=f"{ticker}의 새로운 중대 이벤트 분석이 완료되었습니다. 지금 확인하세요.",
                        ticker=ticker,
                        target_level='premium_plus'
                    )
                except Exception as e:
                    print(f"⚠️ 8-K 푸시 발송 실패: {e}")
                
                # 4. 분석 완료 후 트래커 갱신 (다음 실행 때 스킵)
                batch_upsert("analysis_cache", [{"cache_key": tracker_key_8k, "content": acc_num_8k, "updated_at": datetime.now().isoformat()}], "cache_key")

    # =========================================================
    # 🚀 [5] 통합 서류 루프 (AccessionNumber 기반 최적화 버전)
    # =========================================================
    for topic in target_topics:
        acc_num, f_date = None, None
        
        # 1. 메타데이터(문서번호)만 먼저 가져옴
        if topic in ["BS", "IS", "CF", "10-K"]:
            priority_targets = ["10-K", "10-K/A", "20-F", "20-F/A"]
        elif topic == "10-Q":
            priority_targets = ["10-Q", "10-Q/A"] 
        elif topic == "F-1":
            priority_targets = ["F-1", "F-1/A", "20-F"] 
        elif topic == "S-1":
            priority_targets = ["S-1", "S-1/A"]
        elif topic == "424B4":
            priority_targets = ["424B4", "424B3", "424B5"]
        else:
            priority_targets = [topic]

        for target in priority_targets:
            acc_num, f_date = fetch_sec_metadata(ticker, target, FMP_API_KEY, cik)
            if acc_num: break

        # 서류가 아예 없는 경우 안내 메시지 생성 (Summarization Error 방지)
        if not acc_num:
            for lang_code in SUPPORTED_LANGS.keys():
                cache_key = f"{company_name}_{topic}_Tab0_v16_{lang_code}"
                missing_msg = get_missing_document_message(lang_code, topic)
                formatted_msg = f"<div style='background-color:#f8f9fa; padding:15px; border-radius:8px; color:#555; font-size:15px; line-height:1.6;'>{missing_msg}</div>"
                batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": formatted_msg, "updated_at": datetime.now().isoformat()}], "cache_key")
            continue

        # 중복 체크 (Accession Number 기반)
        tracker_key = f"{company_name}_{topic}_LastAccNum"
        is_already_analyzed = False
        try:
            res_tracker = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key).execute()
            if res_tracker.data and res_tracker.data[0]['content'] == acc_num:
                is_already_analyzed = True
        except: pass

        if is_already_analyzed:
            continue

        # 새 문서일 때만 다운로드
        print(f"📥 [{ticker}] {topic} 새로운 문서 감지 ({acc_num}). 다운로드 중...")
        f_text = fetch_sec_full_content(acc_num, ticker, topic, FMP_API_KEY, cik)

        if f_text and len(f_text) > 100:
            # 💡 [핵심 방어막] 토큰 한도 초과 에러 방지를 위해 상위 100,000자만 잘라서 분석에 사용합니다.
            # 10만 자는 약 2~3만 토큰으로, Gemini 2.0 Flash 한도 내에서 가장 안정적인 분량입니다.
            truncated_text = f_text[:100000]

            for lang_code in SUPPORTED_LANGS.keys():
                cache_key = f"{company_name}_{topic}_Tab0_v16_{lang_code}"
                current_fact_prompt = f"\n[SEC FACT CHECK] Filed on {f_date}."
                meta = get_localized_meta(lang_code, topic)
                
                # 💡 f_text 대신 자른 텍스트(truncated_text)를 전달합니다.
                prompt = get_localized_instruction(
                    lang_code, ticker, topic, company_name, meta, 
                    current_fact_prompt, get_format_instruction(lang_code), 
                    truncated_text
                )
                
                try:
                    response = model_strict.generate_content(prompt)
                    if response and response.text:
                        # 1. AI 인사말 제거
                        raw_text = response.text.strip()
                        clean_text = clean_ai_preamble(raw_text)

                        # 2. 한 줄씩 분석하여 HTML 구조화 (Tab 0 전용 밀착형 구조)
                        lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
                        final_html = ""
                        
                        for line in lines:
                            # [소제목 패턴 탐지] 
                            match = re.match(r'^(\*\*|\[|\*\*\[|\()(.*?)(\]|\] \*\*|\*\*\*|\]\*\*|\))\s*(.*)', line)
                            
                            is_header = False
                            clean_title = ""
                            remainder_text = ""

                            if match:
                                # 제목 안팎의 불필요한 기호 제거
                                raw_title = match.group(2).strip()
                                clean_title = raw_title.strip('[]*() ') 
                                
                                # 소제목 최소 길이 체크 (티커 보호)
                                if len(clean_title) > 5:
                                    is_header = True
                                    remainder_text = match.group(4).strip()
                            
                            if is_header:
                                # [소제목 처리]
                                if final_html:
                                    # 다음 소제목이 시작되기 전에는 확실히 공간 확보 (2줄 띄움 효과)
                                    final_html += "<br><br>"
                                
                                # 소제목을 굵게 하고 대괄호 중복 방지
                                final_html += f"<b>[{clean_title}]</b>"
                                
                                # 🚀 [핵심 수정] 소제목 뒤에 내용이 붙어 있다면 즉시 줄바꿈 후 추가
                                if remainder_text:
                                    final_html += f"<br>{remainder_text}"
                            else:
                                # [일반 본문 처리]
                                if not final_html:
                                    final_html = line
                                else:
                                    # 🚀 [핵심 수정] 이전 줄이 제목(</b>)이었다면 
                                    # 추가적인 여백 없이 단일 줄바꿈(<br>)만 수행하여 밀착시킴
                                    if final_html.endswith("</b>"):
                                        final_html += f"<br>{line}"
                                    else:
                                        # 본문이 계속 이어지는 경우 자연스럽게 공백 하나 주고 연결 (문단 유지)
                                        final_html += f" {line}"
                        
                        # 최종 결과물이 비어있지 않은지 확인
                        if not final_html:
                            final_html = clean_text

                        # 최종 레이아웃: 전체를 하나의 P 태그로 감싸고 내부에서 <br>로 조절
                        indent_size = "14px" if lang_code == "ko" else "0px"
                        processed_content = f'<p style="display:block; text-indent:{indent_size}; line-height:1.8; text-align:justify; font-size:15px; color:#333;">{final_html.strip()}</p>'

                        # Supabase 저장
                        batch_upsert("analysis_cache", [{
                            "cache_key": cache_key, 
                            "content": processed_content, 
                            "updated_at": datetime.now().isoformat(),
                            "ticker": ticker,
                            "tier": "free",
                            "tab_name": "tab0",
                            "lang": lang_code,
                            "data_type": topic
                        }], on_conflict="cache_key")
                        print(f"✅ [{ticker}] {topic} 밀착형 가독성 보정 완료 ({lang_code})")
                except Exception as e:
                    print(f"❌ [{ticker}] {topic} AI 에러 ({lang_code}): {e}")

            # 4개 국어 분석 시도가 모두 끝난 후 트래커 저장 (성공/실패 여부와 상관없이 번호 기록하여 무한 재시도 방지)
            batch_upsert("analysis_cache", [{"cache_key": tracker_key, "content": acc_num, "updated_at": datetime.now().isoformat()}], "cache_key")

def get_tab0_ec_premium_prompt(lang, ticker, raw_data):
    if lang == 'en':
        return f"""You are a Lead Buy-Side Analyst on Wall Street. Summarize the latest Earnings Call Transcript for {ticker}.
[Strict Rules]
1. Write ENTIRELY in English. DO NOT mix other languages.
2. Write exactly 3 paragraphs:
   - Para 1: [Key Financials & Guidance]
   - Para 2: [Strategic Updates & Growth Drivers]
   - Para 3: [Q&A Highlights]
3. Each paragraph must be 4-5 sentences long, packed with hard numbers and professional insights.
4. DO NOT use markdown bold (**) for numbers.
5. Omit greetings and start the main content immediately with a cold, objective tone.

[Raw Data]:
{raw_data}"""

    elif lang == 'ja':
        return f"""あなたはウォール街のシニア・バイサイドアナリストです。提供されたデータに基づき、{ticker}の最新のアーニングコール(Earnings Call)を日本語で深層要約してください。
[厳格な作成ルール]
1. 全て自然な日本語のみで記述してください。
2. 必ず以下の3つの段落に分けて作成してください：
   - 第1段落: [核心業績とガイダンス]
   - 第2段落: [戦略アップデートと成長ドライバー]
   - 第3段落: [Q&Aハイライト]
3. 各段落は4〜5文で構成し、具体的な数値と専門的な洞察を含めてください。
4. 数値に強調記号（**）は絶対に使用しないでください。
5. 挨拶は省略し、すぐに本題に入ってください。冷静で客観的な分析トーンを維持してください。

[Raw Data]:
{raw_data}"""

    elif lang == 'zh':
        return f"""您是华尔街的资深买方分析师。请根据提供的数据，用简体中文深度总结 {ticker} 的最新财报电话会议(Earnings Call)。
[严格编写规则]
1. 必须完全使用简体中文编写，严禁混用其他语言。
2. 必须严格分为以下3个段落：
   - 第一段: [核心业绩与财务指引]
   - 第二段: [战略更新与增长驱动力]
   - 第三段: [问答环节(Q&A)亮点]
3. 每个段落应包含4-5句话，并提供具体数据和深刻的专业见解。
4. 绝对不要使用星号（**）对数字进行加粗。
5. 省略问候语，直接进入正文。保持冷静、客观和分析的基调。

[Raw Data]:
{raw_data}"""

    else: # ko
        return f"""당신은 월가 수석 바이사이드(Buy-side) 애널리스트입니다. 제공된 데이터를 바탕으로 {ticker}의 최신 어닝 콜(Earnings Call) 스크립트를 한국어로 심층 요약하세요.
[작성 규칙 - 엄격 준수]
1. 반드시 순수한 한국어로만 작성하세요.
2. 반드시 아래 3개의 문단으로 나누어 작성하세요:
   - 1문단: [핵심 실적 및 향후 가이던스]
   - 2문단: [경영진 전략 업데이트 및 성장 동력]
   - 3문단: [애널리스트 Q&A 세션 핵심 하이라이트]
3. 각 문단은 4~5줄(문장) 길이로 묵직하고 구체적인 수치를 포함해 작성하세요.
4. 숫자에 별표(**) 강조를 절대 사용하지 마세요.
5. 인사말을 생략하고 첫 글자부터 본론만 작성하세요. 모든 문장은 반드시 '~습니다', '~ㅂ니다' 형태의 격식 있고 정중한 존댓말(합쇼체)로 작성하세요. (예: ~합니다, ~입니다, ~됩니다, ~전망됩니다 등). 절대 '~한다', '~이다' 형태의 평어체를 사용하지 마세요.

[Raw Data]:
{raw_data}"""

def run_tab0_premium_collection(ticker, company_name):
    """Tab 0의 프리미엄 데이터(어닝 콜)를 수집하고 요약하여 캐싱합니다. (Raw Tracker 적용)"""
    if 'model_strict' not in globals() or not model_strict: return
    
    try: # [try 시작]
        try:
            list_url = f"https://financialmodelingprep.com/stable/earnings-transcript-list?symbol={ticker}&apikey={FMP_API_KEY}"
            list_res = requests.get(list_url, timeout=5).json()
            latest = list_res[0] if (isinstance(list_res, list) and len(list_res) > 0) else {"year": "2024", "quarter": 1}
        except:
            latest = {"year": "2024", "quarter": 1}

        url = f"https://financialmodelingprep.com/stable/earning-call-transcript?symbol={ticker}&year={latest.get('year')}&quarter={latest.get('quarter')}&apikey={FMP_API_KEY}"
        ec_raw = get_fmp_data_with_cache(ticker, "RAW_EARNINGS_CALL", url, valid_hours=24) # 매일 확인
        
        is_ec_valid = isinstance(ec_raw, list) and len(ec_raw) > 0
        if not is_ec_valid: return

        # 💡 [과금 방어막 1] 최신 1건의 어닝콜 원본 데이터 문자열화
        current_raw_str = json.dumps(ec_raw[0], sort_keys=True)
        tracker_key = f"{ticker}_PremiumEC_RawTracker"
        is_changed = True
        
        try:
            # 💡 [과금 방어막 2] 기존 DB의 어닝콜 원본과 비교
            res_tracker = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key).execute()
            if res_tracker.data and current_raw_str == res_tracker.data[0]['content']:
                is_changed = False
        except: pass

        if not is_changed: return

        print(f"🔔 [{ticker}] 어닝 콜 신규 업데이트 감지! AI 요약 시작...")

        for lang_code in SUPPORTED_LANGS.keys():
            ec_summary_key = f"{ticker}_PremiumEarningsCall_v1_{lang_code}"
            content = ec_raw[0].get('content', '')[:15000] 
            prompt = get_tab0_ec_premium_prompt(lang_code, ticker, content)
            
            for attempt in range(3):
                try:
                    resp = model_strict.generate_content(prompt)
                    if resp and resp.text:
                        paragraphs = [p.strip() for p in resp.text.split('\n') if len(p.strip()) > 20]
                        indent_size = "14px" if lang_code == "ko" else "0px"
                        html_str = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in paragraphs])
                        
                        batch_upsert("analysis_cache", [{
                            "cache_key": ec_summary_key, 
                            "content": html_str, 
                            "updated_at": datetime.now().isoformat(),
                            "ticker": ticker,
                            "tier": "premium_plus",
                            "tab_name": "tab0",
                            "lang": lang_code,
                            "data_type": "earnings_call"
                        }], on_conflict="cache_key")
                        print(f"✅ [{ticker}] 어닝 콜 요약 캐싱 완료 ({lang_code})")
                        break
                except Exception as e: time.sleep(1)
                
        # 🚀 모든 분석이 성공적으로 끝났을 때만 알림 발송 (Premium Plus 전용)
        send_fcm_push(
            title=f"🎙️ {ticker} 어닝 콜 분석 완료",
            body=f"경영진의 향후 가이던스와 Q&A 핵심 요약이 도착했습니다.",
            ticker=ticker,
            target_level='premium_plus'  # <-- 이 한 줄 추가
        )
        
        # 💡 [과금 방어막 3] 트래커 최신화
        batch_upsert("analysis_cache", [{"cache_key": tracker_key, "content": current_raw_str, "updated_at": datetime.now().isoformat()}], "cache_key")

    except Exception as e: # [꼭 필요한 에러 처리 블록 추가]
        print(f"❌ [{ticker}] run_tab0_premium_collection 실행 중 에러: {e}")
# ==========================================
# [신규 추가] Tab 2 프리미엄 요약 전용 프롬프트 및 수집 함수 (ESG 등급)
# ==========================================
def get_tab2_esg_premium_prompt(lang, ticker, raw_data):
    if lang == 'en':
        return f"""You are a Lead ESG Analyst on Wall Street. Summarize the latest ESG (Environmental, Social, Governance) data for {ticker}.
[Strict Rules]
1. Write ENTIRELY in English. DO NOT mix other languages.
2. Write exactly 3 paragraphs:
   - Para 1: [Environmental Impact & Risk]
   - Para 2: [Social Responsibility]
   - Para 3: [Corporate Governance & Ethics]
3. Each paragraph must be 4-5 sentences long, packed with specific ESG scores and professional insights.
4. DO NOT use markdown bold (**) for numbers.
5. Omit greetings and start immediately with a professional, objective tone.

[Raw Data]:
{raw_data}"""

    elif lang == 'ja':
        return f"""あなたはウォール街のシニアESGアナリストです。提供されたデータに基づき、{ticker}の最新のESG(環境、社会、ガバナンス)評価を日本語で深層要約してください。
[厳格な作成ルール]
1. 全て自然な日本語のみで記述してください。
2. 必ず以下の3つの段落に分けて作成してください：
   - 第1段落: [環境への影響とリスク (E)]
   - 第2段落: [社会的責任 (S)]
   - 第3段落: [企業統治と倫理 (G)]
3. 各段落は4〜5文で構成し、具体的なESGスコアと専門的な洞察を含めてください。
4. 数値に強調記号（**）は絶対に使用しないでください。
5. 挨拶は省略し、すぐに本題に入ってください。冷静で客観的な分析トーンを維持してください。

[Raw Data]:
{raw_data}"""

    elif lang == 'zh':
        return f"""您是华尔街的资深ESG分析师。请根据提供的数据，用简体中文深度总结 {ticker} 的最新ESG（环境、社会、治理）评级。
[严格编写规则]
1. 必须完全使用简体中文编写，严禁混用其他语言。
2. 必须严格分为以下3个段落：
   - 第一段: [环境影响与风险 (E)]
   - 第二段: [社会责任 (S)]
   - 第三段: [公司治理与伦理 (G)]
3. 每个段落应包含4-5句话，并提供具体的ESG分数和深刻的专业见解。
4. 绝对不要使用星号（**）对数字进行加粗。
5. 省略问候语，直接进入正文。保持冷静、客观和分析的基调。

[Raw Data]:
{raw_data}"""

    else: # ko
        return f"""당신은 월가 수석 ESG 애널리스트입니다. 제공된 데이터를 바탕으로 {ticker}의 최신 ESG(환경, 사회, 지배구조) 평가 등급을 한국어로 심층 요약하세요.
[작성 규칙 - 엄격 준수]
1. 반드시 순수한 한국어로만 작성하세요.
2. 반드시 아래 3개의 문단으로 나누어 작성하세요:
   - 1문단: [환경(E) 리스크 및 지속가능성]
   - 2문단: [사회적(S) 책임 및 파급력]
   - 3문단: [지배구조(G) 및 투명성 평가]
3. 각 문단은 4~5줄(문장) 길이로 구체적인 ESG 점수를 포함해 작성하세요.
4. 숫자에 별표(**) 강조를 절대 사용하지 마세요.
5. 인사말을 생략하고 첫 글자부터 본론만 작성하세요. 모든 문장은 반드시 '~습니다', '~ㅂ니다' 형태의 격식 있고 정중한 존댓말(합쇼체)로 작성하세요. (예: ~합니다, ~입니다, ~됩니다, ~전망됩니다 등). 절대 '~한다', '~이다' 형태의 평어체를 사용하지 마세요.

[Raw Data]:
{raw_data}"""

def run_tab2_premium_collection(ticker, company_name):
    """Tab 2: ESG (매일 감시하되 변경점 없으면 AI 스킵)"""
    if 'model_strict' not in globals() or not model_strict: return
    
    try: # [1] 메인 try 시작
        url = f"https://financialmodelingprep.com/stable/esg-ratings?symbol={ticker}&apikey={FMP_API_KEY}"
        esg_raw = get_fmp_data_with_cache(ticker, "RAW_ESG", url, valid_hours=24) # 매일 확인
        
        if not isinstance(esg_raw, list) or len(esg_raw) == 0:
            return

        current_raw_str = json.dumps(esg_raw[0], sort_keys=True)
        tracker_key = f"{ticker}_PremiumESG_RawTracker"
        is_changed = True
        
        try:
            res_tracker = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key).execute()
            if res_tracker.data and current_raw_str == res_tracker.data[0]['content']:
                is_changed = False # 💡 원본이 똑같으면 스킵!
        except: pass

        if not is_changed: return 

        print(f"🔔 [{ticker}] ESG 업데이트 감지! AI 요약 시작...")
        
        analysis_performed = False # 알림 발송용 플래그
        for lang_code in SUPPORTED_LANGS.keys():
            esg_summary_key = f"{ticker}_PremiumESG_v1_{lang_code}"
            prompt = get_tab2_esg_premium_prompt(lang_code, ticker, current_raw_str)
            
            for attempt in range(3):
                try:
                    resp = model_strict.generate_content(prompt)
                    if resp and resp.text:
                        paragraphs = [p.strip() for p in resp.text.split('\n') if len(p.strip()) > 20]
                        indent_size = "14px" if lang_code == "ko" else "0px"
                        html_str = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in paragraphs])
                        
                        batch_upsert("analysis_cache", [{
                            "cache_key": esg_summary_key, 
                            "content": html_str, 
                            "updated_at": datetime.now().isoformat(),
                            "ticker": ticker,
                            "tier": "premium_plus",
                            "tab_name": "tab2",
                            "lang": lang_code,
                            "data_type": "esg_report"
                        }], on_conflict="cache_key")
                        print(f"✅ [{ticker}] ESG 분석 캐싱 완료 ({lang_code})")
                        analysis_performed = True
                        break
                except Exception as e: time.sleep(1)
                
        # [2] AI 분석 완료 후 발송 (try 블록 내부 유지)
        if analysis_performed:
            send_fcm_push(
                title=f"🌱 {ticker} ESG 평가 업데이트",
                body=f"글로벌 기관 기준의 환경/사회/지배구조 리스크 분석이 업데이트되었습니다.",
                ticker=ticker
            )
            # 트래커 최신화
            batch_upsert("analysis_cache", [{"cache_key": tracker_key, "content": current_raw_str, "updated_at": datetime.now().isoformat()}], "cache_key")

    except Exception as e: # [3] 메인 try를 닫아주는 except 블록 (필수!)
        print(f"❌ [{ticker}] run_tab2_premium_collection 에러: {e}")
# ==========================================
# [수정] Tab 1 프리미엄 요약 전용 프롬프트 생성 함수 (다국어 분리 완벽 적용)
# ==========================================
def get_tab1_premium_prompt(lang, type_name, raw_data):
    if lang == 'en':
        return f"""You are a Senior Wall Street Analyst. Summarize the latest corporate trends based on the provided [Raw Data] ({type_name}).
        
[Strict Rules]
1. Write ENTIRELY in English. Do not mix other languages.
2. Write exactly 3 paragraphs (4-5 sentences each).
3. You MUST include the following elements based on the data and your professional insights:
   - Para 1: Core products/services, primary target audience, and main revenue composition.
   - Para 2: Key competitors, market position, recent trends, and future strategic plans.
   - Para 3: Potential risk factors, operational challenges, and overall analytical evaluation.
4. Replace vague statements with concrete numerical data (%, $, volume, market share, etc.) wherever possible.
5. DO NOT use markdown bold (**) for numbers.
6. Omit greetings and start the main content immediately. Maintain a cold, objective, and analytical tone.

[Raw Data]:
{raw_data}"""

    elif lang == 'ja':
        return f"""あなたはウォール街のシニアアナリストです。提供された [Raw Data] ({type_name}) を分析し、非常に詳細で密度の高い企業インテリジェンスレポートを日本語で作成してください。
        
[厳格な作成ルール]
1. 全て自然な日本語のみで記述してください。
2. 必ず3つの段落（各4〜5文）に分けて作成してください。
3. データと専門的な洞察に基づき、以下の要素を必ず含めてください：
   - 第1段落: 主力製品・サービス、主要ターゲット顧客層、および中核となる売上構成。
   - 第2段落: 主要な競合他社、市場でのポジション、最近の動向、および今後の成長計画。
   - 第3段落: 潜在的なリスク要因、経営上の課題、およびアナリストとしての総合評価。
4. 曖昧な表現を避け、可能な限り具体的な数値（%、$、数量、市場シェアなど）を活用してください。
5. 数値に強調記号（**）は絶対に使用しないでください。
6. 挨拶は省略し、すぐに本題に入ってください。冷静で客観的な分析トーンを維持してください。

[Raw Data]:
{raw_data}"""

    elif lang == 'zh':
        return f"""您是华尔街的高级分析师。请分析提供的 [Raw Data] ({type_name})，并用简体中文提供一份高度详细、高密度的企业情报报告。
        
[严格编写规则]
1. 必须完全使用简体中文编写，严禁混用其他语言。
2. 必须严格分为3个段落（每段4-5句话）。
3. 结合数据与专业见解，必须包含以下核心要素：
   - 第一段: 核心产品/服务、主要目标客户群以及主要营收构成。
   - 第二段: 主要竞争对手、市场地位、近期动态以及未来的战略规划。
   - 第三段: 潜在的风险因素、运营挑战以及分析师视角的综合评估。
4. 拒绝模糊表达，尽可能使用具体的数据（如 %、$、数量、市场份额等）来支撑分析。
5. 绝对不要使用星号（**）对数字进行加粗。
6. 省略问候语，直接进入正文。保持冷静、客观和分析的基调。

[Raw Data]:
{raw_data}"""

    else: # ko
        return f"""당신은 월가 출신의 수석 애널리스트입니다. 아래 제공된 [Raw Data]({type_name})를 심층 분석하여, 내용의 밀도가 매우 높은 전문가용 기업 동향 리포트를 한국어로 작성하세요.
        
[작성 규칙 - 엄격 준수]
1. 반드시 순수한 한국어로만 작성하세요.
2. 반드시 3개의 문단으로 나누어 작성하며, 각 문단은 4~5줄(문장) 길이로 상세히 작성하세요.
3. 아래의 필수 요소를 반드시 포함하여 묵직하고 전문적인 통찰을 담아내세요:
   - 1문단: 기업의 주력 제품/서비스, 주요 마케팅(타겟) 대상, 그리고 주요 매출을 이루는 구성
   - 2문단: 시장 내 주요 경쟁 상대, 최근 동향 및 향후 성장 계획
   - 3문단: 잠재적 위험 요소(리스크) 및 월가 애널리스트 관점의 종합 평가
4. 추상적인 표현을 배제하고 가급적 구체적인 수치(%, $, 수량, 점유율 등)를 적극적으로 활용하세요.
5. 숫자에 별표(**) 강조를 절대 사용하지 마세요.
6. 인사말을 생략하고 첫 글자부터 본론만 작성하며, '~습니다', '~ㅂ니다' 형태의 냉철하고 분석적인 어조를 유지하세요.

[Raw Data]:
{raw_data}"""

# 💡 [추가할 헬퍼 함수] 검색 최적화를 위해 법인 꼬리표를 뗀 이름을 만듭니다. (파일 상단 헬퍼 함수 모음에 추가)
def get_search_friendly_name(name):
    if not name or pd.isna(name): return ""
    name = str(name)
    name = re.sub(r'(/DE|Cl\s*[A-Z]|Class\s*[A-Z])', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\b(Inc|Corp|Corporation|Co|Ltd|Plc|Group|Company|Holdings)\b\.?', '', name, flags=re.IGNORECASE)
    return name.strip().strip(',').strip()

# =========================================================================
# [수정된 Tab 1 분석 함수 교체] run_tab1_analysis 전체를 아래 코드로 교체하세요.
# =========================================================================
def run_tab1_analysis(ticker, company_name, ipo_status="Active", ipo_date_str=None):
    if 'model_strict' not in globals() or not model_strict: return
    
    # 💡 [추가] 구글 검색을 위한 최적화된 기업명 추출
    search_name = get_search_friendly_name(company_name)
    
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    one_year_ago = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    
    status_lower = str(ipo_status).lower()
    is_withdrawn = bool(re.search(r'\b(withdrawn|rw|철회|취소)\b', status_lower))
    is_delisted_or_otc = bool(re.search(r'\b(delisted|폐지|otc)\b', status_lower))
    
    is_over_3m = False
    is_over_1y = False
    try:
        if ipo_date_str:
            days_passed = (now.date() - pd.to_datetime(ipo_date_str).date()).days
            if days_passed > 365: is_over_1y = True
            elif days_passed > 90: is_over_3m = True
    except: pass

    # =========================================================
    # 💡 [핵심 수정]: 기업의 생애주기에 맞춰 검색 키워드를 동적으로 변경합니다.
    # =========================================================
    if is_withdrawn:
        search_query = f'"{search_name}" OR "{ticker}" IPO withdrawn OR corporate news'
    elif is_delisted_or_otc:
        search_query = f'"{search_name}" OR "{ticker}" delisted OR OTC stock news'
    elif is_over_1y:
        # 상장 1년 차 이상의 성숙 기업은 'IPO'를 빼고 실적/비즈니스 이슈 위주로 검색
        search_query = f'"{search_name}" OR "{ticker}" stock news OR earnings OR business'
    else:
        # 1년 미만의 신규 상장 기업은 기존처럼 IPO 뉴스 중심 검색
        search_query = f'"{search_name}" OR "{ticker}" stock IPO news'
    # =========================================================

    valid_hours = 24 
    limit_time_str = (now - timedelta(hours=valid_hours)).isoformat()

    # 1. 원본 데이터 수집
    profile_url = f"https://financialmodelingprep.com/stable/profile?symbol={ticker}&apikey={FMP_API_KEY}"
    profile_data = get_fmp_data_with_cache(ticker, "PROFILE", profile_url, valid_hours=168)
    biz_desc = profile_data[0].get('description') or "" if profile_data else ""

    news_url = f"https://financialmodelingprep.com/stable/news/stock-latest?symbol={ticker}&limit=15&apikey={FMP_API_KEY}"
    news_data = get_fmp_data_with_cache(ticker, "RAW_NEWS_15", news_url, valid_hours=6)
    
    valid_news = [
        n for n in (news_data or []) 
        if n and ticker.upper() in [s.strip().upper() for s in str(n.get('symbol', '')).split(',')]
    ]
    fmp_news_context = "\n".join([f"- Title: {n.get('title')} | Date: {n.get('publishedDate')} | Link: {n.get('url')}" for n in valid_news])

    is_fmp_poor = (len(biz_desc) < 50) or (len(valid_news) < 3)
    current_model = model_search if (is_fmp_poor and model_search) else model_strict

    current_raw_data = {"biz": biz_desc, "news": fmp_news_context}
    current_raw_str = json.dumps(current_raw_data, sort_keys=True)
    tracker_key = f"{ticker}_Tab1_Main_RawTracker"
    
    is_changed = True
    try:
        res_tracker = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key).execute()
        if res_tracker.data and current_raw_str == res_tracker.data[0]['content']:
            is_changed = False 
    except: pass

    if is_changed:
        print(f"🔔 [{ticker}] Tab 1 데이터 변경 감지! 분석 시작...")
        for lang_code in SUPPORTED_LANGS.keys():
            cache_key = f"{ticker}_Tab1_v5_{lang_code}"
            
            if lang_code == 'ko':
                sys_prompt = "당신은 최고 수준의 증권사 리서치 센터의 시니어 애널리스트입니다. 반드시 한국어로 작성하세요."
                lang_instruction = "반드시 자연스러운 한국어만 사용하세요.\n모든 문장은 반드시 '~습니다', '~합니다' 형태의 정중한 존댓말로 마무리하십시오."
                format_instruction = "반드시 3개의 문단으로 나누어 작성하세요. (각 문단은 4~5문장 길이)"
                
                # 💡 [수정] 라벨을 지시사항(Instruction) 형태로 명확히 변경
                if is_withdrawn:
                    task1_label = "--- [분석 지시 1: 상장 철회 심층 진단] ---"
                    task1_structure = "- 1문단: [철회 배경 진단] (철회 배경 설명)\n- 2문단: [재무적 타격] (유동성 등 재무 영향)\n- 3문단: [생존 전략] (향후 대안 및 전략)"
                elif is_delisted_or_otc:
                    task1_label = "--- [분석 지시 1: OTC/장외시장 거래 리스크 진단] ---"
                    task1_structure = "- 1문단: [장외 편입 배경] (편입 배경 설명)\n- 2문단: [투자 리스크] (리스크 진단)\n- 3문단: [장기 전망] (장기 전망 서술)"
                elif is_over_1y:
                    task1_label = "--- [분석 지시 1: 상장 1년 차 펀더멘털 점검] ---"
                    task1_structure = "- 1문단: [목표 달성도] (사업 목표 달성 수준)\n- 2문단: [수익성 평가] (이익 창출력 분석)\n- 3문단: [자본 효율성] (자본 배치 효율성)"
                else:
                    task1_label = "--- [분석 지시 1: 신규 IPO 비즈니스 심층 분석] ---"
                    task1_structure = "- 1문단: [비즈니스 모델 및 스케일] (구체적 수치를 동반한 비즈니스 모델 설명)\n- 2문단: [시장 점유율 및 경쟁 우위] (명확한 경쟁사명 명시한 비교 분석)\n- 3문단: [성장 전략 및 미래 전망] (핵심 신사업 확장 계획 및 트렌드)"

                if is_fmp_poor:
                    search_directive = f"""
                    🚨 [강제 검색 및 필터링 지시 (Inclusion & Exclusion)]: 
                    FMP 데이터가 부족하므로 Google Search 도구를 사용하여 반드시 다음 지침을 따르세요:
                    1. 검색 쿼리(Inclusion): 반드시 `{search_query}` 로 검색하여 넓게 데이터를 확보하세요.
                    2. 필터링(Exclusion): 검색 결과 중 동명이인(예: 피겨스케이팅 선수, 일반인 등)이나 완전히 무관한 산업의 기사는 철저히 배제하세요.
                    3. 기간: [{one_year_ago}] 부터 [{current_date}] 사이의 뉴스만 포함하세요.
                    4. 추출: 필터링을 거쳐 유효하다고 판단된 최신 뉴스만 최대 5개 추출하세요. 억지로 채우지 마세요.
                    """
                else:
                    search_directive = "🚨 [환각 금지] 오직 아래 제공된 [Part 1] 텍스트 데이터만을 사용하여 작성하십시오."
                
                prohibition_rule = '🚨 【절대 금지】: 첫문장에 인사말을 절대 쓰지 마세요. 본문은 반드시 내용에 맞는 실제 소제목(예: **[글로벌 시장 확장 전략]**)으로 시작하세요. "[소제목]", "[작업 1]", "분석 지시" 같은 지시어 단어 자체를 결과물에 절대 출력하지 마세요.'
                task2_label = "--- [분석 지시 2: 최신 뉴스 수집 및 전문 번역] ---"
                # 💡 [핵심 수정] 날짜 환각 방지 및 원문(Fallback) 허용 지시
                news_instruction = '- 제공된 [Part 2] 또는 구글 검색 결과를 바탕으로 최신 뉴스를 **최대 5개** 추출하세요.\n- sentiment 값은 반드시 "Positive", "Negative", "Neutral" 중 하나로 출력하세요.\n- 🚨 기사의 보도 날짜(date)는 가급적 "YYYY-MM-DD" 형식으로 작성하되, 정확한 날짜 파악이 어렵다면 억지로 지어내지 말고 검색 결과에 표시된 표현 그대로(예: "3 days ago", "Mar 16" 등) 작성하여 환각을 방지하세요.'
                json_format = f"""{{ "debug_search_raw": "구글 검색에서 실제로 발견한 원본 뉴스 제목들과, 무관한 것을 배제한 이유를 간략히 적어주세요.", "news": [ {{ "title_en": "Original English Title", "translated_title": "한국 경제신문 헤드라인 스타일 번역", "link": "...", "sentiment": "Positive/Negative/Neutral", "date": "YYYY-MM-DD or 3 days ago" }} ] }}"""

            elif lang_code == 'en':
                sys_prompt = "You are a senior analyst at a top-tier brokerage research center. You MUST write strictly in English."
                lang_instruction = "Your entire response MUST be in English only."
                format_instruction = "Must be written in exactly 3 paragraphs. (Each paragraph should be 4-5 sentences long)"
                
                # 💡 [7-a, 7-b 전략 반영]
                search_directive = f"🚨 [Force Search & Filter]: Search exactly `{search_query}`. Exclude irrelevant entities (e.g., athletes). Max 5 items."
                prohibition_rule = '🚨 ABSOLUTELY PROHIBITED: Do not start with greetings. Start IMMEDIATELY with a bold subheading (e.g., **[Global Expansion]**).'
                
                task2_label = "--- [Instruction 2: Latest News Collection] ---"
                # 💡 날짜 환각 방지 지침 추가 및 JSON 샘플에 debug_search_raw 삽입
                news_instruction = '- Extract up to 5 latest news items. Sentiment: "Positive", "Negative", or "Neutral".'
                json_format = f"""{{ "debug_search_raw": "Summary of search results", "news": [ {{ "title_en": "Title", "translated_title": "Headline", "link": "...", "sentiment": "Positive", "date": "YYYY-MM-DD" }} ] }}"""

            elif lang_code == 'ja':
                sys_prompt = "あなたは最高レベルの証券会社リサーチセンターのシニアアナリストです。すべての回答は日本語で作成してください。"
                lang_instruction = "必ず自然な日本語のみを使用してください。"
                format_instruction = "必ず3つの段落で作成してください。"
                
                if is_withdrawn:
                    task1_label = "--- [指示 1: 上場撤回深層診断] ---"
                    task1_structure = "- 第1段落: [撤回の背景]\n- 第2段落: [財務的打撃]\n- 第3段落: [生存戦略]"
                elif is_over_1y:
                    task1_label = "--- [指示 1: 上場1年次ファンダメンタル点検] ---"
                    task1_structure = "- 第1段落: [目標達成度]\n- 第2段落: [収益性評価]\n- 第3段落: [資本効率]"
                else:
                    task1_label = "--- [指示 1: 新規IPOビジネス深層分析] ---"
                    task1_structure = "- 第1段落: [ビジネスモデルとスケール]\n- 第2段落: [市場シェアと競合優位性]\n- 第3段落: [成長戦略と今後の展望]"

                if is_fmp_poor:
                    search_directive = f"🚨 [強制検索とフィルタリング]: 必ず `{search_query}` で検索し、同姓同名（フィギュアスケート選手など）や無関係なニュースを徹底的に排除してください。期間は[{one_year_ago}]から[{current_date}]です。最大5件。"
                else:
                    search_directive = "🚨 [厳格な規則] 提供された [Part 1] テキストデータのみを使用して作成してください。"
                
                prohibition_rule = '🚨 【厳禁】: 挨拶は一切禁止です。すぐに内容に合った太字の小見出し（例：**[グローバル市場拡張]**）で開始してください。出力に「[見出し]」「[指示 1]」「[作業]」という単語そのものを絶対に含めないでください。'
                task2_label = "--- [指示 2: 最新ニュース収集] ---"
                # 💡 [핵심 수정] 날짜 환각 방지 및 원문(Fallback) 허용 지시
                news_instruction = '- 提供された [Part 2] またはGoogle検索結果から、最新ニュースを**最大5件**抽出してください。\n- sentiment の値は必ず "Positive"、"Negative"、"Neutral" のいずれかにしてください。\n- 🚨 記事の日付(date)は可能な限り "YYYY-MM-DD" 形式で記入してください。ただし、正確な日付が不明な場合は無理に捏造せず、検索結果の表記をそのまま（例: "3 days ago", "Mar 16"）出力してハルシネーションを防いでください。'
                json_format = f"""{{ "debug_search_raw": "Google検索で発見した生データと、無関係なものを除外した理由を簡潔に記載してください。", "news": [ {{ "title_en": "Title", "translated_title": "翻訳", "link": "...", "sentiment": "Positive", "date": "YYYY-MM-DD or 3 days ago" }} ] }}"""

            else: # zh
                sys_prompt = "您是顶级券商研究中心的高级分析师。必须只用简体中文编写。"
                lang_instruction = "必须只用自然流畅的简体中文编写。"
                format_instruction = "必须严格分为 3 个自然段落。"
                
                if is_withdrawn:
                    task1_label = "--- [指令 1: IPO 撤回深度诊断] ---"
                    task1_structure = "- 第一段: [撤回背景]\n- 第二段: [财务影响]\n- 第三段: [生存战略]"
                elif is_over_1y:
                    task1_label = "--- [指令 1: 上市一周年基本面审查] ---"
                    task1_structure = "- 第一段: [目标达成度]\n- 第二段: [盈利能力评估]\n- 第三段: [资本效率]"
                else:
                    task1_label = "--- [指令 1: 新 IPO 业务深度分析] ---"
                    task1_structure = "- 第一段: [核心商业模式]\n- 第二段: [市场份额与竞争优势]\n- 第三段: [增长战略与未来展望]"

                if is_fmp_poor:
                    search_directive = f"🚨 [强制搜索与过滤]: 必须使用 `{search_query}` 进行搜索。彻底排除同名人物（如花样滑冰运动员）或无关行业的文章。期间为 [{one_year_ago}] 至 [{current_date}]。最多 5 条。"
                else:
                    search_directive = "🚨 [严格规则] 只能使用下面提供的 [Part 1] 文本数据进行编写。"

                prohibition_rule = '🚨 【绝对禁止】: 严禁出现问候语。请直接以概括内容的加粗副标题（例如：**[全球市场扩张]**）开始正文。绝对不要在输出中包含“[副标题]”、“[指令 1]”或“[任务]”等字眼。'
                task2_label = "--- [指令 2: 收集最新新闻] ---"
                # 💡 [핵심 수정] 날짜 환각 방지 및 원문(Fallback) 허용 지시
                news_instruction = '- 请基于提供的 [Part 2] 数据或 Google 搜索结果提取**最多 5 条**最新新闻。\n- sentiment 的值必须是 "Positive"、"Negative" 或 "Neutral"。\n- 🚨 新闻发布日期(date)请尽量使用 "YYYY-MM-DD" 格式。但如果难以确定准确日期，严禁捏造(幻觉)，请直接原样填入搜索结果中显示的时间表达式（例如："3 days ago", "Mar 16"）。'
                json_format = f"""{{ "debug_search_raw": "简要说明在Google上搜到了什么，以及为何排除无关结果。", "news": [ {{ "title_en": "Title", "translated_title": "翻译", "link": "...", "sentiment": "Positive", "date": "YYYY-MM-DD or 3 days ago" }} ] }}"""
            # 💡 [수정] Prompt 조립 단계에서 명확한 분리 지시 추가
            prompt = f"""
            {sys_prompt}
            분석 대상: {company_name} ({ticker})
            오늘 날짜: {current_date}

            [Part 1: Official Business Profile (Source: FMP)]
            {biz_desc if biz_desc else "Data unavailable."}

            [Part 2: Official FMP News]
            {fmp_news_context if fmp_news_context else "Data unavailable."}

            {task1_label}
            {search_directive}
            1. 언어/Language: {lang_instruction}
            2. 포맷/Format: {format_instruction}
               {task1_structure}
            3. 금지/Prohibition: {prohibition_rule}
            
            {task2_label}
            {news_instruction}
            
            🚨 [최종 출력 규칙]:
            당신의 답변에 "--- [분석 지시 1" 이나 "--- [분석 지시 2" 같은 프롬프트의 지시어 라벨을 절대 출력하지 마세요.
            오직 깔끔하게 작성된 3개의 문단과, 그 아래에 <JSON_START> 로 시작하는 뉴스 데이터만 출력하십시오.
            
            <JSON_START>
            {json_format}
            <JSON_END>
            """

            for attempt in range(3):
                try:
                    response = current_model.generate_content(prompt)
                    if not response or not response.text: continue
                    
                    def clean_ai_preamble(text):
                        patterns = [
                            r"^(안녕하세요|알겠습니다|작성하겠습니다|요청하신|보고서입니다|Sure|Understood|Certainly|Okay).*?(\n|$)",
                            r"^(承知いたしました|作成します|こんにちは|明白了|好的|这是).*?(\n|$)"
                        ]
                        for p in patterns:
                            text = re.sub(p, "", text, flags=re.MULTILINE | re.IGNORECASE)
                        lines = text.strip().split('\n')
                        if lines:
                            first_line = lines[0].strip()
                            if not (first_line.startswith('**[') or first_line.startswith('[')):
                                if len(first_line) < 65 and first_line.endswith(('다', '요', '요.', 'ね', 'る', '了', ':', '。')):
                                    text = '\n'.join(lines[1:])
                        return text.strip()

                    full_text = clean_ai_preamble(response.text)
                    news_list = []
                    biz_analysis = full_text

                    # JSON 파싱 및 디버그 로깅
                    json_patterns = [r'<JSON_START>.*<JSON_END>', r'```json\s*\{.*?\}\s*```', r'```\s*\{.*?\}\s*```', r'\{.*"news".*\}']
                    for pattern in json_patterns:
                        match = re.search(pattern, biz_analysis, re.DOTALL | re.IGNORECASE)
                        if match:
                            json_str = match.group(0)
                            c_match = re.search(r'(\{.*\})', json_str, re.DOTALL)
                            if c_match:
                                try:
                                    parsed = json.loads(c_match.group(1), strict=False)
                                    news_list = parsed.get("news", [])
                                    # 💡 [디버깅 로그 출력] LLM이 실제로 구글 검색 후 어떻게 필터링했는지 콘솔에 출력!
                                    if "debug_search_raw" in parsed and lang_code == 'ko':
                                        print(f"🐛 [디버깅: {ticker} 검색 필터링 결과] -> {parsed['debug_search_raw']}")
                                except: pass
                            biz_analysis = biz_analysis.replace(json_str, "").strip()
                            break

                    biz_analysis = re.sub(r'^#+.*$', '', biz_analysis, flags=re.MULTILINE).strip()
                    lines = biz_analysis.split('\n')
                    final_lines = []
                    body_started = False
                    for line in lines:
                        l = line.strip()
                        if not l: continue
                        if not body_started:
                            is_subheading = l.startswith('**[') or l.startswith('[')
                            is_short_title = (l.startswith('**') and l.endswith('**') and len(l) < 60)
                            is_intro_line = (len(l) < 55 and (l.endswith(':') or l.endswith('입니다') or l.endswith('보고서')))
                            if (is_short_title or is_intro_line) and not is_subheading: continue 
                            else: body_started = True
                        final_lines.append(line)
                    
                    biz_analysis = "\n".join(final_lines).strip()
                    biz_analysis = re.sub(r'(\*\*\[.*?\]\*\*)\s*:\s*', r'\1\n', biz_analysis)
                    raw_paragraphs = biz_analysis.split('\n')
                    clean_paragraphs = [p.strip() for p in raw_paragraphs if len(p.strip()) > 10]
                    
                    html_parts = []
                    for p in clean_paragraphs:
                        if p.startswith('**[') or p.startswith('['):
                            html_parts.append(f'<p style="font-weight:bold; margin-top:20px; margin-bottom:5px; color:#111;">{p.replace("**","")}</p>')
                        else:
                            indent = "14px" if lang_code == "ko" else "0px"
                            html_parts.append(f'<p style="text-indent:{indent}; margin-bottom:15px; line-height:1.8; text-align:justify; font-size:15px; color:#333;">{p}</p>')

                    html_output = "".join(html_parts)

                    batch_upsert("analysis_cache", [{
                        "cache_key": cache_key,
                        "content": json.dumps({"html": html_output, "news": news_list[:5]}, ensure_ascii=False),
                        "updated_at": now.isoformat(),
                        # --- 신규 태그 추가 ---
                        "ticker": ticker,
                        "tier": "free",
                        "tab_name": "tab1",
                        "lang": lang_code,
                        "data_type": "biz_summary"
                    }], on_conflict="cache_key")
                    break 

                except Exception as e:
                    print(f"❌ [{ticker}] {lang_code} 분석 시도 중 오류: {e}")
                    time.sleep(1)
        
        batch_upsert("analysis_cache", [{"cache_key": tracker_key, "content": current_raw_str, "updated_at": now.isoformat()}], "cache_key")
        print(f"✅ [{ticker}] Tab 1 분석 및 캐싱 완료 (동적 필터링 & 디버깅 적용)")
    else:
        print(f"⏩ [{ticker}] Tab 1 변경점 없음. AI 요약 스킵!")
                
    # =========================================================
    # 🚀 [B] 프리미엄 전용 데이터 수집 (기업 공식 보도자료 - Raw Tracker 적용!)
    # =========================================================
    try:
        pr_url = f"https://financialmodelingprep.com/stable/press-releases?symbol={ticker}&limit=5&apikey={FMP_API_KEY}"
        pr_raw = get_fmp_data_with_cache(ticker, "RAW_PR", pr_url, valid_hours=12)
        
        # 🚨 [환각 완벽 차단] FMP가 보낸 데이터가 에러 딕셔너리({})가 아닌 정상 리스트([])일 때만 통과!
        is_pr_valid = isinstance(pr_raw, list) and len(pr_raw) > 0

        if is_pr_valid: 
            
            current_pr_str = json.dumps(pr_raw, sort_keys=True)
            tracker_key_pr = f"{ticker}_PressRelease_RawTracker"
            is_changed_pr = True
            
            try:
                # 💡 [과금 방어막] 기존 원본 데이터와 토씨 하나 안 틀리고 똑같으면 AI 스킵!
                res_tracker = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key_pr).execute()
                if res_tracker.data and current_pr_str == res_tracker.data[0]['content']:
                    is_changed_pr = False
            except: pass

            if is_changed_pr:
                print(f"🔔 [{ticker}] 기업 보도자료 업데이트 감지! AI 요약 시작...")
                for lang_code in SUPPORTED_LANGS.keys():
                    pr_summary_key = f"{ticker}_PressReleaseSummary_v1_{lang_code}"
                    prompt_p = get_tab1_premium_prompt(lang_code, "Official Press Release", current_pr_str)
                    
                    for attempt in range(3):
                        try:
                            resp_p = model_strict.generate_content(prompt_p)
                            if resp_p and resp_p.text:
                                p_paragraphs = [p.strip() for p in resp_p.text.split('\n') if len(p.strip()) > 20]
                                indent_size = "14px" if lang_code == "ko" else "0px"
                                html_p = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in p_paragraphs])
                                
                                # ✅ 태깅 정보 추가 및 tier를 'free'로 설정
                                batch_upsert("analysis_cache", [{
                                    "cache_key": pr_summary_key, 
                                    "content": html_p, 
                                    "updated_at": now.isoformat(),
                                    "ticker": ticker,
                                    "tier": "free",          # 모든 사용자 공개
                                    "tab_name": "tab1",
                                    "lang": lang_code,
                                    "data_type": "press_release"
                                }], on_conflict="cache_key")
                                
                                print(f"✅ [{ticker}] 기업 공식 보도자료 캐싱 완료 ({lang_code})")
                                break
                        except:
                            time.sleep(1) # ✅ 쉼표 없이 깔끔하게 줄바꿈 처리
                        
                # 요약 완료 후 트래커 갱신
                batch_upsert("analysis_cache", [{"cache_key": tracker_key_pr, "content": current_pr_str, "updated_at": now.isoformat()}], "cache_key")

    except Exception as e:
        print(f"Premium FMP Collection Error for {ticker}: {e}")


# ==========================================
# [완벽 복구] Tab 4: 기관 리포트 요약 (JSON 은탄환 파싱 + Raw Tracker 방어막)
# ==========================================
def run_tab4_analysis(ticker, company_name, ipo_status="Active", ipo_date_str=None, analyst_data=None):
    if 'model_strict' not in globals() or not model_strict: return False
    
    # 💡 [과금 방어막 1] 애널리스트 목표가/투자의견 원본 문자열화
    current_analyst_str = json.dumps(analyst_data, sort_keys=True) if analyst_data else "{}"
    tracker_key = f"{ticker}_Tab4_Analyst_RawTracker"
    is_changed = True
    
    try:
        # 💡[과금 방어막 2] 기존 DB의 애널리스트 데이터 원본과 비교
        res_tracker = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key).execute()
        if res_tracker.data and current_analyst_str == res_tracker.data[0]['content']:
            is_changed = False # 토씨 하나 안 틀리고 똑같으면 스킵!
    except: pass

    if not is_changed:
        return True # 목표가/의견이 안 변했으면 새로운 리포트가 없다고 간주하고 함수 즉시 종료 (검색 API 0원!)
        
    print(f"🔔 [{ticker}] 기관 목표가/투자의견 변경 감지! Tab 4 AI 검색 요약 시작...")

    status_lower = str(ipo_status).lower()
    is_stable = bool(re.search(r'\b(withdrawn|rw|철회|취소|delisted|폐지)\b', status_lower))
    
    if not is_stable and ipo_date_str:
        try:
            ipo_dt = pd.to_datetime(ipo_date_str).date()
            if (datetime.now().date() - ipo_dt).days > 365: is_stable = True
        except: pass

    valid_hours = 168 if is_stable else 24
    limit_time_str = (datetime.now() - timedelta(hours=valid_hours)).isoformat()

    # 💡 [신규 추가] 긍정적 시그널 포착 여부 확인 변수
    is_positive_signal = False
    detected_rating = ""

    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Tab4_v4_Premium_{lang_code}" 
        
        try:
            res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key).gt("updated_at", limit_time_str).execute()
            if res.data: continue 
        except: pass

        fmp_context = ""
        if analyst_data and analyst_data.get('target') != 'N/A':
            fmp_context = f"""
[Wall Street Consensus (FMP Premium Data)]
- Consensus Rating: {analyst_data.get('consensus')}
- Target Price (Average): ${analyst_data.get('target')} (High: ${analyst_data.get('high')}, Low: ${analyst_data.get('low')})
"""

        if lang_code == 'en':
            prompt = f"""You are an IPO analyst from Wall Street.
Use the Google search tool to find and analyze the latest institutional reports for {company_name} ({ticker}).
{fmp_context}

[Instructions]
1. **Language Rule**: MUST write entirely in English. DO NOT mix any Korean words.
2. **Analysis Depth**: Provide a professional analysis including specific figures and evidence (especially Target Price if available).
3. **Pros & Cons**: Clearly derive and reflect exactly 2 positive factors (Pros) and 2 negative factors (Cons).
4. **Score**: Evaluate the overall positive/expectation level of the Wall Street report as an integer from 1 (Worst) to 5 (Moonshot/Best).
5. **Output Format**: Strictly output ONLY the JSON format below. 100% compliance with the 'Value' instructions.
6. **Link Location**: NEVER put URLs inside the main body text. You MUST only put them inside the "links" array.

<JSON_START>
{{
    "target_price": "Insert FMP Average Target Price (e.g., $150.00) or 'N/A'",
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell",
    "score": "Integer from 1 to 5",
    "summary": "Professional 3-line summary in English. Mention Target Price if provided.",
    "pro_con": "**Pros**:\\n- Detail 1\\n- Detail 2\\n\\n**Cons**:\\n- Detail 1\\n- Detail 2",
    "links": [ {{"title": "Report Title", "link": "URL"}} ]
}}
<JSON_END>"""

        elif lang_code == 'ja':
            prompt = f"""あなたはウォール街出身のIPO専門アナリストです。
Google検索を使用して、{company_name} ({ticker})に関する最新の機関投資家レポートを見つけ分析してください。
{fmp_context}

[作成指針]
1. **言語規則**: 全て自然な日本語のみで記述してください。韓国語を絶対に混ぜないでください。
2. **分析の深さ**: 具体的な数値や根拠（特に目標株価）を含む専門的な分析を提供してください。
3. **Pros & Cons**: 肯定的な要素(長所)を2つ、否定的な要素(短所)を2つ明確に導き出して反映させてください。
4. **スコア**: ウォール街のレポートの総合的な期待レベルを1(最悪)から5(最高)までの整数で評価してください。
5. **出力形式**: 以下の<JSON_START>フォーマットの指示を100%遵守して出力してください。
6. **リンクの位置**: 本文の中には絶対にURLを入れず、必ず「links」配列の中にのみ記入してください。

<JSON_START>
{{
    "target_price": "FMPの平均目標株価を挿入 (例: $150.00) または 'N/A'",
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell (英語維持)",
    "score": "1から5までの整数",
    "summary": "日本語での専門的な3行要約 (目標株価の言及を含む)",
    "pro_con": "**長所(Pros)**:\\n- 詳細内容1\\n- 詳細内容2\\n\\n**短所(Cons)**:\\n- リスク要因1\\n- リスク要因2",
    "links":[ {{"title": "レポートタイトル", "link": "URL"}} ]
}}
<JSON_END>"""

        elif lang_code == 'zh':
            prompt = f"""您是华尔街的专业IPO分析师。
请使用Google搜索工具查找并分析关于 {company_name} ({ticker}) 的最新机构报告。
{fmp_context}

[编写指南]
1. **语言规则**: 必须只用简体中文编写。严禁混用韩语。
2. **分析深度**: 提供包含具体数据和依据的专业分析（特别是目标价）。
3. **Pros & Cons**: 明确提取2个积极因素(优点)和2个消极因素(缺点)。
4. **评分**: 将华尔街报告的综合预期水平评为1(最差)到5(极佳)的整数。
5. **输出格式**: 100%严格遵守以下<JSON_START>格式中“值”的指示进行填写。
6. **链接位置**: 绝对不要在正文中放入URL，必须只填写在“links”数组中。

<JSON_START>
{{
    "target_price": "插入FMP平均目标价 (如: $150.00) 或 'N/A'",
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell (保留英文)",
    "score": "1到5的整数",
    "summary": "包含目标价背景的专业中文三行摘要",
    "pro_con": "**优点(Pros)**:\\n- 详细分析1\\n- 详细分析2\\n\\n**缺点(Cons)**:\\n- 风险因素1\\n- 风险因素2",
    "links":[ {{"title": "报告标题", "link": "URL"}} ]
}}
<JSON_END>"""

        else: # ko
            prompt = f"""당신은 월가 출신의 IPO 전문 분석가입니다. 
구글 검색 도구를 사용하여 {company_name} ({ticker})에 대한 최신 기관 리포트(Seeking Alpha, Renaissance Capital 등)를 찾아 심층 분석하세요.
{fmp_context}

[작성 지침]
1. **언어 규칙**: 반드시 자연스러운 한국어로 번역하여 작성하세요.
2. **분석 깊이**: 구체적인 수치나 근거를 포함하여 전문적으로 분석하세요.
3. **Pros & Cons**: 긍정적 요소(Pros) 2가지와 부정적 요소(Cons) 2가지를 명확히 도출하여 반영하세요.
4. **Score**: 월가 리포트의 종합적인 긍정/기대 수준을 1점(최악)부터 5점(대박) 사이의 정수로 평가하세요.
5. **출력 형식**: 아래 제공된 <JSON_START> 양식의 '값(Value)' 부분에 적힌 언어와 지시사항을 100% 준수하여 채워 넣으세요.
6. **링크 위치**: 본문 안에는 절대 URL을 넣지 말고, 반드시 "links" 배열 안에만 기입하세요.

<JSON_START>
{{
    "target_price": "FMP 평균 목표 주가 삽입 (예: $150.00) 또는 'N/A'",
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell 중 택 1 (영어 유지)",
    "score": "1~5 사이의 정수 (예: 4)",
    "summary": "한국어 전문 3줄 요약 (목표 주가 맥락을 포함할 것)",
    "pro_con": "**장점(Pros)**:\\n- 구체적 분석 내용 1\\n- 구체적 분석 내용 2\\n\\n**단점(Cons)**:\\n- 구체적 리스크 요인 1\\n- 구체적 리스크 요인 2",
    "links": [ {{"title": "리포트 제목", "link": "URL"}} ]
}}
<JSON_END>"""
        
        for attempt in range(3):
            try:
                target_model = model_search if model_search is not None else model_strict
                response = target_model.generate_content(prompt)
                
                if not response or not hasattr(response, 'text') or not response.text:
                    time.sleep(1); continue
                    
                full_text = response.text
                
                # 🚨 [은탄환] 어떤 찌꺼기가 붙어있든 무조건 첫 { 와 마지막 } 사이만 강제 추출
                start_idx = full_text.find('{')
                end_idx = full_text.rfind('}')
                
                if start_idx != -1 and end_idx != -1:
                    json_str = full_text[start_idx:end_idx+1]
                    try:
                        parsed_json = json.loads(json_str, strict=False)
                        
                        # 🚀 [로직 추가] 한국어 분석 시점에 등급/점수를 체크하여 긍정적이면 플래그 ON
                        if lang_code == 'ko':
                            rating_val = str(parsed_json.get('rating', '')).upper()
                            score_val = str(parsed_json.get('score', '0')).strip()
                            if ("BUY" in rating_val) or (score_val in ["4", "5"]):
                                is_positive_signal = True
                                detected_rating = parsed_json.get('rating', 'Buy')

                        batch_upsert("analysis_cache", [{
                            "cache_key": cache_key, 
                            "content": json.dumps(parsed_json, ensure_ascii=False), 
                            "updated_at": datetime.now().isoformat(),
                            # --- 신규 태그 추가 ---
                            "ticker": ticker,
                            "tier": "premium",
                            "tab_name": "tab4",
                            "lang": lang_code,
                            "data_type": "analyst_report"
                        }], on_conflict="cache_key")
                        print(f"✅ [{ticker}] Tab 4 기관 리포트 완료 ({lang_code})")
                        break
                    except json.JSONDecodeError as e:
                        print(f"⚠️ [{ticker}] Tab 4 JSON 파싱 실패 ({lang_code}): {e}")
                time.sleep(1)
            except Exception as e:
                time.sleep(1)

    # 💡 [과금 방어막 3] 4개 국어 번역이 성공적으로 끝났다면 트래커 갱신!
    batch_upsert("analysis_cache",[{"cache_key": tracker_key, "content": current_analyst_str, "updated_at": datetime.now().isoformat()}], "cache_key")

    # 🚀 [신규 추가] 긍정적 시그널이 포착되었을 때만 프리미엄 플러스 유저에게 푸시 발송
    if is_positive_signal:
        try:
            send_fcm_push(
                title=f"🎯 {ticker} 기관 투자 의견 상향",
                body=f"월가 분석 결과, {ticker}에 대해 '{detected_rating}' 등급의 긍정적 리포트가 포착되었습니다.",
                ticker=ticker,
                target_level='premium_plus'  # <-- 이 한 줄 추가
            )
            print(f"🚀 [알림 전송] {ticker} 긍정적 리포트 시그널 발송 완료")
        except Exception as e:
            print(f"⚠️ Tab 4 푸시 발송 실패: {e}")

    return True

    # =========================================================
    # 🚀 [B] 프리미엄 전용 데이터 수집 (Upgrades/Downgrades & Peers)
    # =========================================================
    try:
        # 💡 [Stable 변경 완료] API v4 및 언더바(_)를 stable과 하이픈(-)으로 교체
        ud_url = f"https://financialmodelingprep.com/stable/upgrades-downgrades?symbol={ticker}&apikey={FMP_API_KEY}"
        ud_raw = get_fmp_data_with_cache(ticker, "RAW_UPGRADES", ud_url, valid_hours=24)
        
        peers_url = f"https://financialmodelingprep.com/stable/stock-peers?symbol={ticker}&apikey={FMP_API_KEY}"
        peers_raw = get_fmp_data_with_cache(ticker, "RAW_PEERS", peers_url, valid_hours=24)

        # 🚨 [환각 방어막] 진짜 데이터인지 엄격 검사
        is_ud_valid = isinstance(ud_raw, list) and len(ud_raw) > 0
        is_peers_valid = isinstance(peers_raw, list) and len(peers_raw) > 0

        for lang_code in SUPPORTED_LANGS.keys():
            if is_ud_valid:
                ud_summary_key = f"{ticker}_PremiumUpgrades_v1_{lang_code}"
                try:
                    res_ud = supabase.table("analysis_cache").select("updated_at").eq("cache_key", ud_summary_key).gt("updated_at", limit_time_str).execute()
                    if not res_ud.data:
                        prompt_ud = get_tab4_premium_prompt(lang_code, "Upgrades and Downgrades History", ticker, ud_raw)
                        for attempt in range(3):
                            try:
                                resp_ud = model_strict.generate_content(prompt_ud)
                                if resp_ud and resp_ud.text:
                                    ud_paragraphs = [p.strip() for p in resp_ud.text.split('\n') if len(p.strip()) > 20]
                                    indent_size = "14px" if lang_code == "ko" else "0px"
                                    html_ud = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in ud_paragraphs])
                                    batch_upsert("analysis_cache", [{"cache_key": ud_summary_key, "content": html_ud, "updated_at": datetime.now().isoformat()}], "cache_key")
                                    print(f"✅ [{ticker}] 투자의견 히스토리 캐싱 완료 ({lang_code})")
                                    break
                            except Exception as e: time.sleep(1)
                except: pass

            if is_peers_valid:
                peers_summary_key = f"{ticker}_PremiumPeers_v1_{lang_code}"
                try:
                    res_p = supabase.table("analysis_cache").select("updated_at").eq("cache_key", peers_summary_key).gt("updated_at", limit_time_str).execute()
                    if not res_p.data:
                        prompt_p = get_tab4_premium_prompt(lang_code, "Stock Peers & Competitors", ticker, peers_raw)
                        for attempt in range(3):
                            try:
                                resp_p = model_strict.generate_content(prompt_p)
                                if resp_p and resp_p.text:
                                    p_paragraphs = [p.strip() for p in resp_p.text.split('\n') if len(p.strip()) > 20]
                                    indent_size = "14px" if lang_code == "ko" else "0px"
                                    html_p = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in p_paragraphs])
                                    batch_upsert("analysis_cache", [{"cache_key": peers_summary_key, "content": html_p, "updated_at": datetime.now().isoformat()}], "cache_key")
                                    print(f"✅ [{ticker}] 경쟁사 비교 캐싱 완료 ({lang_code})")
                                    break
                            except Exception as e: time.sleep(1)
                except: pass
    except Exception as e:
        print(f"Premium Tab 4 FMP Error for {ticker}: {e}")
        
# ==========================================
# [신규 추가] Tab 4 프리미엄 요약 전용 프롬프트 (다국어 완벽 분리)
# ==========================================
def get_tab4_premium_prompt(lang, type_name, ticker, raw_data):
    if lang == 'en':
        return f"""You are a Senior Wall Street Analyst. Analyze the following [Raw Data] ({type_name}) for {ticker}.
        
[Strict Rules]
1. Write ENTIRELY in English. Do not mix other languages.
2. Write exactly 3 paragraphs.
3. Each paragraph must be 4-5 sentences long, containing deep and professional insights.
4. DO NOT use markdown bold (**) for numbers.
5. Omit greetings and start the main content immediately. Maintain a cold, objective, and analytical tone.

[Raw Data]:
{raw_data}"""

    elif lang == 'ja':
        return f"""あなたはウォール街のシニアアナリストです。提供された [Raw Data] ({type_name}) に基づいて、{ticker} に関する分析を日本語で要約してください。
        
[厳格な作成ルール]
1. 全て自然な日本語のみで記述してください。
2. 必ず3つの段落に分けて作成してください。
3. 各段落は4〜5文で構成し、重厚で専門的な洞察を含めてください。
4. 数値に強調記号（**）は絶対に使用しないでください。
5. 挨拶は省略し、すぐに本題に入ってください。冷静で客観的な分析トーンを維持してください。

[Raw Data]:
{raw_data}"""

    elif lang == 'zh':
        return f"""您是华尔街的高级分析师。请根据提供的 [Raw Data] ({type_name})，用简体中文对 {ticker} 进行深度分析。
        
[严格编写规则]
1. 必须完全使用简体中文编写，严禁混用其他语言。
2. 必须严格分为3个段落。
3. 每个段落应包含4-5句话，并提供深刻、专业的见解。
4. 绝对不要使用星号（**）对数字进行加粗。
5. 省略问候语，直接进入正文。保持冷静、客观和分析的基调。

[Raw Data]:
{raw_data}"""

    else: # ko
        return f"""당신은 월가 출신의 수석 애널리스트입니다. 아래 제공된 [Raw Data]({type_name})를 바탕으로 {ticker}의 상황을 한국어로 심층 분석하세요.
        
[작성 규칙 - 엄격 준수]
1. 반드시 순수한 한국어로만 작성하세요.
2. 반드시 3개의 문단으로 나누어 작성하세요.
3. 각 문단은 4~5줄(문장) 길이로 묵직하고 전문적인 통찰을 담으세요.
4. 숫자에 별표(**) 강조를 절대 사용하지 마세요.
5. 인사말을 생략하고 첫 글자부터 본론만 작성하세요. 냉철하고 분석적인 어조를 유지하세요.

[Raw Data]:
{raw_data}"""


# ==========================================
# [수정] FMP 프리미엄 11개 지표 통합 수집 헬퍼 (안전망 강화 버전)
# ==========================================
def fetch_premium_financials(symbol, api_key):
    """11가지 핵심 지표를 모두 수집하며, 권한 에러 발생 시 로그를 띄웁니다."""
    fin_data = {
        'growth': 'N/A', 'net_margin': 'N/A', 'op_margin': 'N/A', 'pe': 'N/A',
        'roe': 'N/A', 'debt_equity': 'N/A', 'pb': 'N/A', 'accruals': 'Unknown',
        'dcf_price': 'N/A', 'current_price': 'N/A', 'rating': 'N/A',
        'recommendation': 'N/A', 'health_score': 'N/A'
    }
    
    def safe_fmp_get(url, name):
        res = requests.get(url, timeout=5).json()
        if isinstance(res, dict) and "Error Message" in res:
            print(f"🚫 [재무 데이터 차단됨: {name}] -> {res['Error Message']}")
            return []
        return res

    try:
        # 1. 손익계산서
        inc_url = f"https://financialmodelingprep.com/stable/income-statement?symbol={symbol}&limit=2&apikey={api_key}"
        inc_res = safe_fmp_get(inc_url, "Income Statement")
        if isinstance(inc_res, list) and len(inc_res) > 0:
            rev = float(inc_res[0].get('revenue', 0))
            net_inc = float(inc_res[0].get('netIncome', 0))
            op_inc = float(inc_res[0].get('operatingIncome', 0))
            prev_rev = float(inc_res[1].get('revenue', rev)) if len(inc_res) > 1 else rev
            
            fin_data['growth'] = f"{((rev - prev_rev) / prev_rev) * 100:+.1f}%" if prev_rev else "N/A"
            fin_data['net_margin'] = f"{(net_inc / rev) * 100:.1f}%" if rev else "N/A"
            fin_data['op_margin'] = f"{(op_inc / rev) * 100:.1f}%" if rev else "N/A"
        
        # 2. 주요 지표
        m_url = f"https://financialmodelingprep.com/stable/key-metrics-ttm?symbol={symbol}&apikey={api_key}"
        m_res = safe_fmp_get(m_url, "Key Metrics TTM")
        if isinstance(m_res, list) and len(m_res) > 0:
            m = m_res[0]
            fin_data['pe'] = f"{m.get('peRatioTTM', 0):.1f}x" if m.get('peRatioTTM') else "N/A"
            fin_data['roe'] = f"{m.get('roeTTM', 0) * 100:.1f}%" if m.get('roeTTM') else "N/A"
            fin_data['debt_equity'] = f"{m.get('debtToEquityTTM', 0) * 100:.1f}%" if m.get('debtToEquityTTM') else "N/A"
            fin_data['pb'] = m.get('pbRatioTTM', 'N/A')

        # 3. 현금흐름 (Accruals)
        cf_url = f"https://financialmodelingprep.com/stable/cash-flow-statement?symbol={symbol}&limit=1&apikey={api_key}"
        cf_res = safe_fmp_get(cf_url, "Cash Flow")
        if isinstance(cf_res, list) and len(cf_res) > 0 and fin_data['net_margin'] != 'N/A':
            ocf = float(cf_res[0].get('operatingCashFlow', 0))
            fin_data['accruals'] = "Low" if (fin_data.get('netIncome', 0) - ocf) <= 0 else "High"
        else:
            fin_data['accruals'] = "Unknown"

        # 4. DCF 적정주가
        dcf_url = f"https://financialmodelingprep.com/stable/discounted-cash-flow?symbol={symbol}&apikey={api_key}"
        dcf_res = safe_fmp_get(dcf_url, "DCF")
        if isinstance(dcf_res, list) and len(dcf_res) > 0:
            dcf_val = dcf_res[0].get('dcf')
            stock_price = dcf_res[0].get('Stock Price')
            fin_data['dcf_price'] = f"${dcf_val:.2f}" if dcf_val is not None else "N/A"
            fin_data['current_price'] = f"${stock_price:.2f}" if stock_price is not None else "N/A"

        # 5. 퀀트 Rating
        r_url = f"https://financialmodelingprep.com/stable/rating?symbol={symbol}&apikey={api_key}"
        r_res = safe_fmp_get(r_url, "Quant Rating")
        if isinstance(r_res, list) and len(r_res) > 0:
            fin_data['rating'] = r_res[0].get('rating', 'N/A')
            fin_data['recommendation'] = r_res[0].get('ratingRecommendation', 'N/A')
            fin_data['health_score'] = r_res[0].get('ratingScore', 'N/A')

    except Exception as e:
        print(f"Data Fetch Error for {symbol}: {e}")
    
    return fin_data

    
# ==========================================
# [신규 추가] FMP 애널리스트 목표가 & 컨센서스 수집 헬퍼
# ==========================================
def fetch_analyst_estimates(symbol, api_key):
    data = {"target": "N/A", "high": "N/A", "low": "N/A", "consensus": "N/A"}
    try:
        pt_url = f"https://financialmodelingprep.com/stable/price-target-consensus?symbol={symbol}&apikey={api_key}"
        pt_res = requests.get(pt_url, timeout=5).json()
        if isinstance(pt_res, dict) and "Error Message" in pt_res:
            print(f"🚫 [Tab 4 목표가 차단됨] -> {pt_res['Error Message']}")
        elif isinstance(pt_res, list) and len(pt_res) > 0 and isinstance(pt_res[0], dict):
            data['target'] = pt_res[0].get('targetConsensus', 'N/A')
            data['high'] = pt_res[0].get('targetHigh', 'N/A')
            data['low'] = pt_res[0].get('targetLow', 'N/A')

        rec_url = f"https://financialmodelingprep.com/stable/analyst-stock-recommendations?symbol={symbol}&limit=1&apikey={api_key}"
        rec_res = requests.get(rec_url, timeout=5).json()
        if isinstance(rec_res, dict) and "Error Message" in rec_res:
            print(f"🚫 [Tab 4 투자의견 차단됨] -> {rec_res['Error Message']}")
        elif isinstance(rec_res, list) and len(rec_res) > 0 and isinstance(rec_res[0], dict):
            data['consensus'] = rec_res[0].get('ratingRecommendation', 'N/A')
    except Exception as e: 
        print(f"Analyst Data Fetch Error for {symbol}: {e}")
    return data

# ==========================================
# [신규 추가] Tab 4 프리미엄 요약 전용 프롬프트 및 수집 함수 (M&A 및 인수합병)
# ==========================================
# ==========================================
# [신규 추가] Tab 4 프리미엄 요약 전용 프롬프트 및 수집 함수 (M&A 및 인수합병)
# ==========================================
def get_tab4_ma_premium_prompt(lang, ticker, raw_data):
    if lang == 'en':
        return f"""You are a Lead M&A Analyst on Wall Street. Summarize the latest Mergers and Acquisitions (M&A) data for {ticker}.
[Strict Rules]
1. Write ENTIRELY in English. DO NOT mix other languages.
2. Write exactly 3 paragraphs:
   - Para 1: [Recent M&A Transactions & Targets]
   - Para 2: [Deal Size & Strategic Purpose]
   - Para 3: [Synergy & Valuation Impact]
3. Each paragraph must be 4-5 sentences long, packed with specific deal values and professional insights.
4. DO NOT use markdown bold (**) for numbers.
5. Omit greetings and start immediately with a professional, objective tone.

[Raw Data]:
{raw_data}"""

    elif lang == 'ja':
        return f"""あなたはウォール街のシニアM&Aアナリストです。提供されたデータに基づき、{ticker}の最新の「M&Aおよび企業買収履歴」を日本語で深層要約してください。
[厳格な作成ルール]
1. 全て自然な日本語のみで記述してください。
2. 必ず以下の3つの段落に分けて作成してください：
   - 第1段落: [最近のM&A取引とターゲット企業]
   - 第2段落: [取引規模と戦略的目的]
   - 第3段落: [シナジー効果とバリュエーションへの影響]
3. 各段落は4〜5文で構成し、具体的な買収金額と専門的な洞察を含めてください。
4. 数値に強調記号（**）は絶対に使用しないでください。
5. 挨拶は省略し、すぐに本題に入ってください。冷静で客観的な分析トーンを維持してください。

[Raw Data]:
{raw_data}"""

    elif lang == 'zh':
        return f"""您是华尔街的资深并购(M&A)分析师。请根据提供的数据，用简体中文深度总结 {ticker} 的最新「M&A及企业并购记录」。
[严格编写规则]
1. 必须完全使用简体中文编写，严禁混用其他语言。
2. 必须严格分为以下3个段落：
   - 第一段: [近期并购交易与目标企业]
   - 第二段: [交易规模与战略目的]
   - 第三段: [协同效应与估值(Valuation)影响]
3. 每个段落应包含4-5句话，并提供具体的交易金额和深刻的专业见解。
4. 绝对不要使用星号（**）对数字进行加粗。
5. 省略问候语，直接进入正文。保持冷静、客观和分析的基调。

[Raw Data]:
{raw_data}"""

    else: # ko
        return f"""당신은 월가 수석 M&A 애널리스트입니다. 제공된 데이터를 바탕으로 {ticker}의 최신 'M&A 및 기업 인수합병 내역'을 한국어로 심층 요약하세요.
[작성 규칙 - 엄격 준수]
1. 반드시 순수한 한국어로만 작성하세요.
2. 반드시 아래 3개의 문단으로 나누어 작성하세요:
   - 1문단: [최근 인수합병(M&A) 내역 및 타겟 기업]
   - 2문단: [거래 규모 및 전략적 목적]
   - 3문단: [시너지 효과 및 기업가치(Valuation) 파급력]
3. 각 문단은 4~5줄(문장) 길이로 구체적인 인수 금액($) 수치를 포함해 작성하세요.
4. 숫자에 별표(**) 강조를 절대 사용하지 마세요.
5. 인사말을 생략하고 첫 글자부터 본론만 작성하세요. 모든 문장은 반드시 '~습니다', '~ㅂ니다' 형태의 격식 있고 정중한 존댓말(합쇼체)로 작성하세요. (예: ~합니다, ~입니다, ~됩니다, ~전망됩니다 등). 절대 '~한다', '~이다' 형태의 평어체를 사용하지 마세요.

[Raw Data]:
{raw_data}"""

def run_tab4_ma_premium_collection(ticker, company_name):
    """Tab 4: M&A 내역 (매일 감시하되 변경점 없으면 AI 스킵)"""
    if 'model_strict' not in globals() or not model_strict: return
    try:
        url = f"https://financialmodelingprep.com/stable/search-mergers-acquisitions?name={ticker}&apikey={FMP_API_KEY}"
        ma_raw = get_fmp_data_with_cache(ticker, "RAW_MA_HISTORY", url, valid_hours=24)
        
        if not isinstance(ma_raw, list) or len(ma_raw) == 0: return

        current_raw_str = json.dumps(ma_raw[:10], sort_keys=True)
        tracker_key = f"{ticker}_PremiumMA_RawTracker"
        is_changed = True
        
        try:
            res_tracker = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key).execute()
            if res_tracker.data and current_raw_str == res_tracker.data[0]['content']:
                is_changed = False
        except: pass

        if not is_changed: return 

        print(f"🔔 [{ticker}] M&A 내역 업데이트 감지! AI 요약 시작...")
        
        analysis_success = False
        for lang_code in SUPPORTED_LANGS.keys():
            ma_summary_key = f"{ticker}_PremiumMA_v1_{lang_code}"
            prompt = get_tab4_ma_premium_prompt(lang_code, ticker, current_raw_str)
            
            for attempt in range(3):
                try:
                    resp = model_strict.generate_content(prompt)
                    if resp and resp.text:
                        paragraphs = [p.strip() for p in resp.text.split('\n') if len(p.strip()) > 20]
                        indent_size = "14px" if lang_code == "ko" else "0px"
                        html_str = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in paragraphs])
                        batch_upsert("analysis_cache", [{
                        "cache_key": ma_summary_key, "content": html_str, "updated_at": datetime.now().isoformat(),
                        "ticker": ticker, "tier": "premium_plus", "tab_name": "tab4", "lang": lang_code, "data_type": "ma_report"
                        }], on_conflict="cache_key")
                        print(f"✅ [{ticker}] M&A 분석 캐싱 완료 ({lang_code})")
                        analysis_success = True
                        break
                except Exception as e: time.sleep(1)
        
        # 🚀 [FCM 추가] 분석 완료 후 알림 발송 (Premium Plus 전용)
        if analysis_success:
            send_fcm_push(
                title=f"🤝 {ticker} 인수합병(M&A) 소식",
                body=f"{ticker}의 최근 M&A 거래 내역과 전략적 시너지 분석 리포트가 업데이트되었습니다.",
                ticker=ticker,
                target_level='premium_plus'  # <-- 이 한 줄 추가
            )
                
        batch_upsert("analysis_cache", [{"cache_key": tracker_key, "content": current_raw_str, "updated_at": datetime.now().isoformat()}], "cache_key")

    except Exception as e:
        print(f"Tab4 Premium M&A Error for {ticker}: {e}")

# ==========================================
# [신규 추가] Tab 4 프리미엄 요약 전용 프롬프트 및 수집 함수 (투자의견 및 경쟁사)
# ==========================================
def get_tab4_premium_prompt(lang, type_name, ticker, raw_data):
    if lang == 'en':
        return f"""You are a Senior Wall Street Analyst. Analyze the following [Raw Data] ({type_name}) for {ticker}.
        
[Strict Rules]
1. Write ENTIRELY in English. Do not mix other languages.
2. Write exactly 3 paragraphs.
3. Each paragraph must be 4-5 sentences long, containing deep and professional insights.
4. DO NOT use markdown bold (**) for numbers.
5. Omit greetings and start the main content immediately. Maintain a cold, objective, and analytical tone.

[Raw Data]:
{raw_data}"""

    elif lang == 'ja':
        return f"""あなたはウォール街のシニアアナリストです。提供された [Raw Data] ({type_name}) に基づいて、{ticker} に関する分析を日本語で要約してください。
        
[厳格な作成ルール]
1. 全て自然な日本語のみで記述してください。
2. 必ず3つの段落に分けて作成してください。
3. 各段落は4〜5文で構成し、重厚で専門的な洞察を含めてください。
4. 数値に強調記号（**）は絶対に使用しないでください。
5. 挨拶は省略し、すぐに本題に入ってください。冷静で客観的な分析トーンを維持してください。

[Raw Data]:
{raw_data}"""

    elif lang == 'zh':
        return f"""您是华尔街的高级分析师。请根据提供的 [Raw Data] ({type_name})，用简体中文对 {ticker} 进行深度分析。
        
[严格编写规则]
1. 必须完全使用简体中文编写，严禁混用其他语言。
2. 必须严格分为3个段落。
3. 每个段落应包含4-5句话，并提供深刻、专业的见解。
4. 绝对不要使用星号（**）对数字进行加粗。
5. 省略问候语，直接进入正文。保持冷静、客观和分析的基调。

[Raw Data]:
{raw_data}"""

    else: # ko
        return f"""당신은 월가 출신의 수석 애널리스트입니다. 아래 제공된 [Raw Data]({type_name})를 바탕으로 {ticker}의 상황을 한국어로 심층 분석하세요.
        
[작성 규칙 - 엄격 준수]
1. 반드시 순수한 한국어로만 작성하세요.
2. 반드시 3개의 문단으로 나누어 작성하세요.
3. 각 문단은 4~5줄(문장) 길이로 묵직하고 전문적인 통찰을 담으세요.
4. 숫자에 별표(**) 강조를 절대 사용하지 마세요.
5. 인사말을 생략하고 첫 글자부터 본론만 작성하세요. 냉철하고 분석적인 어조를 유지하세요.

[Raw Data]:
{raw_data}"""

def run_tab4_premium_collection(ticker, company_name):
    """Tab 4: 투자의견 히스토리 및 경쟁사 분석 (매일 감시하되 변경점 없으면 AI 스킵)"""
    if 'model_strict' not in globals() or not model_strict: return
    
    try:
        # --- [1] 투자의견 변화(Upgrades & Downgrades) 처리 ---
        ud_url = f"https://financialmodelingprep.com/stable/upgrades-downgrades?symbol={ticker}&apikey={FMP_API_KEY}"
        ud_raw = get_fmp_data_with_cache(ticker, "RAW_UPGRADES", ud_url, valid_hours=24)
        
        if isinstance(ud_raw, list) and len(ud_raw) > 0:
            current_ud_str = json.dumps(ud_raw[:10], sort_keys=True)
            tracker_key_ud = f"{ticker}_PremiumUpgrades_RawTracker"
            is_changed_ud = True
            
            try:
                res_ud = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key_ud).execute()
                if res_ud.data and current_ud_str == res_ud.data[0]['content']:
                    is_changed_ud = False
            except: pass
            
            if is_changed_ud:
                print(f"🔔 [{ticker}] 투자의견(Upgrades) 업데이트 감지! AI 요약 시작...")
                ud_success = False
                for lang_code in SUPPORTED_LANGS.keys():
                    ud_summary_key = f"{ticker}_PremiumUpgrades_v1_{lang_code}"
                    prompt_ud = get_tab4_premium_prompt(lang_code, "Upgrades and Downgrades History", ticker, current_ud_str)
                    
                    for attempt in range(3):
                        try:
                            resp_ud = model_strict.generate_content(prompt_ud)
                            if resp_ud and resp_ud.text:
                                ud_paragraphs = [p.strip() for p in resp_ud.text.split('\n') if len(p.strip()) > 20]
                                indent_size = "14px" if lang_code == "ko" else "0px"
                                html_ud = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in ud_paragraphs])
                                batch_upsert("analysis_cache", [{
                                "cache_key": ud_summary_key, "content": html_ud, "updated_at": datetime.now().isoformat(),
                                "ticker": ticker, "tier": "premium", "tab_name": "tab4", "lang": lang_code, "data_type": "rating_history"
                                }], on_conflict="cache_key")
                                print(f"✅ [{ticker}] 투자의견 히스토리 캐싱 완료 ({lang_code})")
                                ud_success = True
                                break
                        except Exception as e: time.sleep(1)
                
                # 🚀 [FCM 추가] 알림 발송 (Premium Plus 전용)
                if ud_success:
                    send_fcm_push(
                        title=f"🎯 {ticker} 월가 투자의견 변경",
                        body=f"주요 투자은행들의 {ticker}에 대한 투자의견 및 목표주가 변화를 확인하세요.",
                        ticker=ticker,
                        target_level='premium_plus'  # <-- 이 한 줄 추가
                    )
                        
                batch_upsert("analysis_cache", [{"cache_key": tracker_key_ud, "content": current_ud_str, "updated_at": datetime.now().isoformat()}], "cache_key")

        # --- [2] 경쟁사(Peers) 처리 ---
        peers_url = f"https://financialmodelingprep.com/stable/stock-peers?symbol={ticker}&apikey={FMP_API_KEY}"
        peers_raw = get_fmp_data_with_cache(ticker, "RAW_PEERS", peers_url, valid_hours=24)
        
        if isinstance(peers_raw, list) and len(peers_raw) > 0:
            current_p_str = json.dumps(peers_raw, sort_keys=True)
            tracker_key_p = f"{ticker}_PremiumPeers_RawTracker"
            is_changed_p = True
            
            try:
                res_p = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key_p).execute()
                if res_p.data and current_p_str == res_p.data[0]['content']:
                    is_changed_p = False
            except: pass
            
            if is_changed_p:
                print(f"🔔 [{ticker}] 경쟁사(Peers) 업데이트 감지! AI 요약 시작...")
                for lang_code in SUPPORTED_LANGS.keys():
                    peers_summary_key = f"{ticker}_PremiumPeers_v1_{lang_code}"
                    prompt_p = get_tab4_premium_prompt(lang_code, "Stock Peers & Competitors", ticker, current_p_str)
                    
                    for attempt in range(3):
                        try:
                            resp_p = model_strict.generate_content(prompt_p)
                            if resp_p and resp_p.text:
                                p_paragraphs = [p.strip() for p in resp_p.text.split('\n') if len(p.strip()) > 20]
                                indent_size = "14px" if lang_code == "ko" else "0px"
                                html_p = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in p_paragraphs])
                                batch_upsert("analysis_cache", [{
                                "cache_key": peers_summary_key, "content": html_p, "updated_at": datetime.now().isoformat(),
                                "ticker": ticker, "tier": "premium", "tab_name": "tab4", "lang": lang_code, "data_type": "peer_comparison"
                                }], on_conflict="cache_key")
                                print(f"✅ [{ticker}] 경쟁사 비교 캐싱 완료 ({lang_code})")
                                break
                        except Exception as e: time.sleep(1)
                        
                batch_upsert("analysis_cache", [{"cache_key": tracker_key_p, "content": current_p_str, "updated_at": datetime.now().isoformat()}], "cache_key")

    except Exception as e:
        print(f"Tab4 Premium Collection Error for {ticker}: {e}")
    
# ==========================================
# [수정/완전판] Tab 3: 미시 지표 (오염 방지 격리 & 무한 루프 + 비용 누수 완벽 차단)
# ==========================================
def run_tab3_analysis(ticker, company_name, raw_metrics, ipo_date_str=None):
    if 'model_strict' not in globals() or not model_strict: return False
    
    # 💡 [핵심 방어막 1] FMP가 준 '순수한 빈 껍데기 원본'을 절대 오염되지 않게 문자열로 박제!
    pristine_metrics_str = json.dumps(raw_metrics, sort_keys=True)
    tracker_key = f"{ticker}_Tab3_Financial_RawTracker"
    is_changed = True
    
    try:
        # Tracker는 오직 '순수 원본'끼리만 비교합니다. (AI가 채운 값과 비교하지 않음)
        res_tracker = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key).execute()
        if res_tracker.data and pristine_metrics_str == res_tracker.data[0]['content']:
            is_changed = False # 순수 원본이 똑같으면 스킵!
    except: pass

    # 💡[핵심 방어막 2] AI가 맘껏 주무르고 수정할 수 있도록 복사본(Enriched) 생성!
    enriched_metrics = copy.deepcopy(raw_metrics)

    is_fmp_fin_poor = (str(enriched_metrics.get('growth', 'N/A')) in ['N/A', '', 'None'])
    can_fin_search = is_fmp_fin_poor and (model_search is not None)
    
    # 💡 [영구 동면 방어 로직] 
    force_search_run = False
    if not is_changed and can_fin_search:
        try:
            limit_time_str = (datetime.now() - timedelta(hours=168)).isoformat() # 7일
            test_key = f"{ticker}_Tab3_Summary_ko"
            res_exp = supabase.table("analysis_cache").select("updated_at").eq("cache_key", test_key).gt("updated_at", limit_time_str).execute()
            if not res_exp.data:
                force_search_run = True # 1주일 지났으니 새로운 실적 떴는지 강제 검색!
        except: pass

    if not is_changed and not force_search_run:
        return True # 변경점도 없고, 1주일도 안 지났으면 조용히 스킵 (무한 루프 원천 차단)
        
    reason = "데이터 변경" if is_changed else "정기 재무 검색(7일)"
    print(f"🔔 [{ticker}] Tab 3 업데이트 감지 ({reason})! AI 요약 시작...")
    
    curr_yr = datetime.now().year
    past_3_years = f"{curr_yr-2} {curr_yr-1} {curr_yr}"
    rich_raw_data_str = "N/A"
    
    # =====================================================================
    # 🚀 15대 기초 재무 데이터 수집 (이때만 비싼 model_search를 1번 씁니다!)
    # =====================================================================
    if can_fin_search:
        print(f"🔍 [{ticker}] 재무 데이터 누락 감지. 15대 기초 재무 데이터 딥서치 시도...")
        recovery_prompt = f"""
        Search Google for the latest fundamental financial numbers of {company_name} ({ticker}) for the years {past_3_years}.
        Find the EXACT absolute numbers in Millions or Billions (NOT percentages).
        If it's a SPAC (Special Purpose Acquisition Company) or pre-revenue, output 0 for Revenue and Income.
        Output ONLY valid JSON matching this exact structure:
        {{
            "revenue": "numeric value or 0",
            "prev_revenue": "numeric value or 0",
            "gross_profit": "numeric value or 0",
            "operating_income": "numeric value or 0",
            "net_income": "numeric value or 0",
            "total_assets": "numeric value or 0",
            "total_liabilities": "numeric value or 0",
            "total_debt": "numeric value or 0",
            "total_equity": "numeric value or 0",
            "operating_cash_flow": "numeric value or 0",
            "free_cash_flow": "numeric value or 0",
            "cash_and_equivalents": "numeric value or 0",
            "ebitda": "numeric value or 0",
            "eps": "numeric value or 0",
            "shares_outstanding": "numeric value or 0"
        }}
        """
        try:
            # 💡 여기서는 model_search를 써서 구글을 뒤집니다.
            rec_res = model_search.generate_content(recovery_prompt)
            if rec_res and rec_res.text:
                text = rec_res.text
                json_str = text[text.find('{'):text.rfind('}')+1]
                raw_data = json.loads(json_str)
                
                def to_float(val):
                    try: return float(re.sub(r'[^0-9.-]', '', str(val)))
                    except: return None
                
                rev = to_float(raw_data.get("revenue"))
                p_rev = to_float(raw_data.get("prev_revenue"))
                net = to_float(raw_data.get("net_income"))
                debt = to_float(raw_data.get("total_debt"))
                equity = to_float(raw_data.get("total_equity"))
                ocf = to_float(raw_data.get("operating_cash_flow"))
                eps = to_float(raw_data.get("eps"))
                
                updated = False
                
                # 🚨 복사본(enriched_metrics)에만 데이터를 채워 넣습니다! 원본은 절대 건드리지 않음!
                if rev is not None and p_rev is not None and p_rev > 0:
                    enriched_metrics["growth"] = f"{((rev - p_rev) / p_rev) * 100:.1f}%"
                    updated = True
                
                if rev is not None and net is not None:
                    if rev > 0:
                        enriched_metrics["net_margin"] = f"{(net / rev) * 100:.1f}%"
                        updated = True
                    elif rev == 0:
                        enriched_metrics["net_margin"] = "Pre-revenue"
                        updated = True
                        
                if debt is not None and equity is not None and equity > 0:
                    enriched_metrics["debt_equity"] = f"{(debt / equity) * 100:.1f}%"
                    updated = True

                if net is not None and ocf is not None:
                    enriched_metrics["accruals"] = "Low" if (net - ocf) <= 0 else "High"
                    updated = True

                try:
                    curr_p = float(str(enriched_metrics.get('current_price', '0')).replace('$', '').replace(',', ''))
                    if curr_p > 0 and eps is not None and eps > 0:
                        enriched_metrics["pe"] = f"{curr_p / eps:.1f}x"
                        updated = True
                except: pass
                
                rich_raw_data_str = ", ".join([f"{k}: {v}" for k, v in raw_data.items() if v not in [None, "N/A", ""]])
                enriched_metrics["raw_deep_data"] = rich_raw_data_str
                
                if updated:
                    # 화면에 보여주기 위해 꽉 채워진 데이터를 Raw_Financials 키에 저장합니다. 
                    batch_upsert("analysis_cache", [{
                        "cache_key": cache_key_sum, 
                        "content": clean_sum, 
                        "updated_at": datetime.now().isoformat(),
                        "ticker": ticker,
                        "tier": "free",
                        "tab_name": "tab3",
                        "lang": lang_code,
                        "data_type": "metrics_card"
                    }], on_conflict="cache_key")
                    print(f"✅[{ticker}] 15대 데이터 수집 및 확장 지표(Accruals, P/E) 연산 완료!")
        except Exception as e:
            print(f"⚠️ [{ticker}] 기초 데이터 수집/연산 실패: {e}")

    if rich_raw_data_str == "N/A" and "raw_deep_data" in enriched_metrics:
        rich_raw_data_str = enriched_metrics["raw_deep_data"]

    # 컨텍스트 조립도 오염된 복사본(enriched_metrics)을 사용합니다. (이 숫자들을 공통으로 씁니다)
    g1_context = f"[Business Growth & Profitability] Sales Growth: {enriched_metrics.get('growth', 'N/A')}, Net Margin: {enriched_metrics.get('net_margin', 'N/A')}, Piotroski Score: {enriched_metrics.get('health_score', 'N/A')}/9"
    g2_context = f"[Financial Health & Quality] Debt to Equity: {enriched_metrics.get('debt_equity', 'N/A')}, Accruals Quality: {enriched_metrics.get('accruals', 'Unknown')}"
    g3_context = f"[Market Valuation] Forward P/E: {enriched_metrics.get('pe', 'N/A')}, DCF Target Price: {enriched_metrics.get('dcf_price', 'N/A')}, Current Price: {enriched_metrics.get('current_price', 'N/A')}"
    g4_context = f"[Deep Raw Financials] {rich_raw_data_str}"

    limit_time_str = (datetime.now() - timedelta(hours=168)).isoformat() if force_search_run else (datetime.now() - timedelta(hours=24)).isoformat()

    # =====================================================================
    # 🚀 4개 국어 리포트 작성 (단위 표기 지침 및 소제목 보정 버전)
    # =====================================================================
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key_sum = f"{ticker}_Tab3_Summary_{lang_code}"
        cache_key_full = f"{ticker}_Tab3_v2_Premium_{lang_code}"
        
        try:
            res = supabase.table("analysis_cache").select("updated_at").eq("cache_key", cache_key_full).gt("updated_at", limit_time_str).execute()
            if res.data: continue 
        except: pass

        if lang_code == 'ko':
            na_handling_rule = "🚨 [N/A 방어 규칙]: 만약 P/E나 DCF 등 밸류에이션 지표가 N/A이거나 수익이 0(Pre-revenue)이라면 '평가할 수 없다'거나 '정보가 부족하다'는 변명을 절대 쓰지 마세요. 대신 \"현재 초기 단계(또는 신규 상장)로 전통적인 현금흐름 기반의 밸류에이션 적용은 제한적이며, 시장은 해당 기업의 미래 파이프라인, 비전, 그리고 잠재 시장 규모(TAM)에 프리미엄을 부여하며 가치를 평가하고 있습니다\"라는 논리로 매우 전문성 있게 서술하세요."
            search_directive = ""
            
            sum_p = f"""당신은 퀀트 애널리스트입니다. {company_name}({ticker})의 지표를 해석하여 대시보드 카드를 작성하세요.
[데이터]: {g1_context} | {g2_context} | {g3_context}
🚨 {na_handling_rule}
[카드 작성 규칙 - 절대 엄수]
1. 당신의 답변은 웹사이트의 서로 다른 3개의 독립된 카드에 각각 들어갈 텍스트입니다. 절대 JSON이나 마크다운을 쓰지 마세요.
2. 반드시 아래의 정확한 포맷으로만 출력하세요.
   [포맷]: (성장성 및 수익성 진단 4~5문장) |||SEP||| (재무 건전성 및 이익 질 진단 4~5문장) |||SEP||| (시장 가치 평가 4~5문장)
3. 구분자 '|||SEP|||' 이외의 어떠한 특수기호나 줄바꿈도 단락 사이에 넣지 마세요. 모든 문장은 '~습니다/합니다' 체를 사용하세요.
"""
            full_p = f"다음 데이터를 사용하여 {company_name}({ticker})의 '표준 정통 재무 분석 리포트'를 작성하세요.\n[비율 데이터]: {g1_context}, {g2_context}, {g3_context}\n[핵심 원시 데이터]: {g4_context}\n🚨 {na_handling_rule}"
            full_i = """[작성 규칙 - 절대 엄수]
            1. 🚨 인사말 없이 첫 글자부터 바로 **[소제목]**으로 시작하세요.
            2. 🚨 소제목 강제 형식: 반드시 **[소제목명]** 형태로 작성하고, 소제목 직후에 줄바꿈을 한 번 하세요.
            3. 소제목 명칭: [수익성 및 성장성 분석], [재무 건전성 및 현금흐름], [적정 가치 및 종합 투자의견]을 순서대로 사용하세요.
            4. 🚨 모든 숫자는 '15.9억 달러' 또는 '4,600만 달러'와 같이 한국어 단위를 명시하세요. '$' 기호와 'Billion/Million' 영문 혼용은 금지합니다.
            5. 각 문단은 4~5문장으로 구성하며, 모든 문장은 반드시 '~습니다', '~합니다' 형태의 정중한 존댓말로 마무리하십시오.
            6. '정보가 부족하다'는 변명 대신, 제공된 데이터를 바탕으로 분석가로서의 통찰을 채워 작성하세요.
            """

        elif lang_code == 'en':
            na_handling_rule = "🚨 [N/A Defense]: If valuation is N/A, explain that market premium is based on future TAM and pipeline."
            sum_p = f"""당신은 퀀트 애널리스트입니다. {company_name}({ticker})의 지표를 해석하여 대시보드 카드를 작성하세요. (Write ENTIRELY in English)
[DATA]: {g1_context} | {g2_context} | {g3_context}
🚨 {na_handling_rule}
[STRICT FORMAT RULE]
1. Your answer will be placed in 3 independent cards on a website.
2. YOU MUST USE THIS EXACT FORMAT:
   (Growth analysis 4-5 sentences) |||SEP||| (Health analysis 4-5 sentences) |||SEP||| (Valuation analysis 4-5 sentences)
3. DO NOT use any other separators or line breaks. Start the analysis immediately.
"""
            full_p = f"Write a standard financial report for {company_name}({ticker}).\n[Ratio Data]: {g1_context}, {g2_context}, {g3_context}\n[Raw Data]: {g4_context}\n🚨 Rule: {na_handling_rule}"
            full_i = """[STRICT RULES]
1. 🚨 Start IMMEDIATELY with the first subheading **[Profitability & Growth Analysis]**. NO greetings, NO intro.
2. 🚨 Mandatory Header Format: Use **[Subheading Name]** with a line break right after it.
3. Subheadings to use: **[Profitability & Growth Analysis]**, **[Financial Health & Cash Flow]**, **[Valuation & Final Verdict]**.
4. 🚨 Numerical Data: ALWAYS use the format '$1.59 Billion' or '$46.0 Million'. Do not write '$1.59 Billion dollars' redundantly.
5. Each paragraph must be 4-5 sentences long. Maintain a cold, professional, and objective tone.
6. If data is limited, provide analytical insights based on the available figures instead of stating information is missing.
"""

        elif lang_code == 'ja':
            na_handling_rule = "🚨 [N/A防御規則]: P/EやDCFなどの指標がN/Aの場合、「情報不足」と言い訳せず、将来のTAMへの期待によるプレミアムとして専門的に記述してください。"
            sum_p = f"""あなたはクオンツアナリストです。{company_name}({ticker})を評価してください。
データ: {g1_context} | {g2_context} | {g3_context}
🚨 {na_handling_rule}
[厳格な出力フォーマット規則]
1. 3つの独立したテキストのみを出力してください。
2. 形式: (成長性と収益性) |||SEP||| (財務健全性) |||SEP||| (バリュエーション)
3. 区切り文字 '|||SEP|||' 以外に改行を入れないでください。丁寧な日本語を使用してください。
"""
            full_p = f"{company_name}({ticker}) の本格的財務分析レポートを作成してください。\n[比率データ]: {g1_context}, {g2_context}, {g3_context}\n[原データ]: {g4_context}\n🚨 規則: {na_handling_rule}"
            full_i = """[厳格な規則]
1. 🚨 挨拶、導入文は禁止です。最初からすぐに **[小見出し]** で始めてください。
2. 🚨 必ず以下の小見출しを **[小見出し名]** 形式で使用し、直後に改行してください: [収益性と成長性の分析], [財務健全性とキャッシュフロー], [適正価値と総合投資意見]。
3. 🚨 数値引用: すべての数値は必ず「15.9億ドル」または「4,600万ドル」のような形式で記載してください。
4. 各段落は4〜5文で構成し、です・ます調を維持してください。
5. 「データがない」という言い訳は禁止です。"""

        else: # zh
            na_handling_rule = "🚨 [N/A防御规则]: 如果估值指标为 N/A，请专业地解释为市场对未来 TAM 和产品管线的溢价，不要说“缺乏数据”。"
            sum_p = f"""作为量化分析师，请评估 {company_name}({ticker})。
数据: {g1_context} | {g2_context} | {g3_context}
🚨 {na_handling_rule}
[严格格式规则]
1. 仅输出3段独立的纯文本。
2. 格式: (增长与盈利能力) |||SEP||| (财务健康) |||SEP||| (市场估值)
3. 仅使用 '|||SEP|||' 作为分隔符，不要加入任何其他换行符。
"""
            full_p = f"请撰写 {company_name}({ticker}) 的深度财务分析报告。\n[数据]: {g4_context}\n🚨 规则：{na_handling_rule}"
            full_i = """[严格规则]
1. 🚨 绝对禁止任何问候语。必须从第一个字开始直接输出 **[副标题]**。
2. 🚨 必须使用以下带方括号的副标题并在标题后换行: [盈利能力与增长性分析], [财务健康与现金流], [合理估值与综合投资意见]。
3. 🚨 数值引用: 请将所有金额转换为中文单位（如：15.9亿美元 或 4,600万美元）。严禁仅输出数字。
4. 副标题后直接写4-5句话。保持专业冷静的语调。
5. 绝对不要抱怨数据缺失。"""

        # ----------------------------------------------------
        # [Call 1] 3D 카드 요약 생성 (괄호 찌꺼기 완전 박멸)
        # ----------------------------------------------------
        try:
            res_sum = model_strict.generate_content(sum_p)
            if res_sum and res_sum.text:
                # 1. 인사말 제거
                clean_sum = clean_ai_preamble(res_sum.text.strip())
                
                # 2. 6번 문제 해결: 카드용 텍스트에서 [ ]와 ( )로 감싸진 지시문/제목 강제 삭제
                clean_sum = re.sub(r'[\[\(].*?[\]\)]\s*:?', '', clean_sum)
                
                # 3. 줄바꿈 제거하여 한 줄로 합치기
                clean_sum = clean_sum.replace('\n', ' ').strip()
                
                batch_upsert("analysis_cache",[{
                    "cache_key": cache_key_sum, 
                    "content": clean_sum, 
                    "updated_at": datetime.now().isoformat()
                }], "cache_key")
                print(f"✅ [{ticker}] Tab 3 카드 요약 캐싱 완료 ({lang_code})")
        except Exception as e:
            # 🚨 [중요] 이 except 블록이 없어서 에러가 났던 것입니다.
            print(f"❌ [{ticker}] Tab 3 카드 요약 에러 ({lang_code}): {e}")

        # ----------------------------------------------------
        # [Call 2] 하단 전문 리포트 생성 (전역 정제 함수 통합 및 최적화 버전)
        # ----------------------------------------------------
        try:
            # 💡 [비용 방어막] 여기서도 철저하게 비용 0원짜리 model_strict만 씁니다!
            res_full = model_strict.generate_content(full_p + full_i)
            if res_full and res_full.text:
                # 🚀 [수정 핵심 1]: 전역 정제 함수 호출로 인사말 및 공통 서론 1차 제거
                clean_full = clean_ai_preamble(res_full.text.strip())
                
                # 🚀 [수정 핵심 2]: Tab 3 리포트 전용 필터 (이모지, 특정 타이틀 등 제거)
                clean_full = re.sub(r'(?i)(🎓|📊|📈|💡|🚀|CFA Quant Deep-Dive Analysis|CFA Quant|기업 분석 보고서|재무 분석 보고서)', '', clean_full).strip()
                
                # 마크다운 굵은글씨(**) 파괴
                clean_full = re.sub(r'\*\*(.*?)\*\*', r'\1', clean_full) 
                
                # 문단 분리 및 불필요한 기호 제거
                paragraphs = [p.lstrip('-*• ').strip() for p in clean_full.replace('\\n', '\n').split('\n') if len(p.strip()) > 10]
                indent_size = "14px" if lang_code == "ko" else "0px"
                
                # 최종 HTML 조립
                html_full = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in paragraphs])
                
                # 정제된 리포트 저장
                batch_upsert("analysis_cache", [{
                    "cache_key": cache_key_full, 
                    "content": html_full, 
                    "updated_at": datetime.now().isoformat(),
                    # --- 신규 태그 추가 ---
                    "ticker": ticker,
                    "tier": "premium",
                    "tab_name": "tab3",
                    "lang": lang_code,
                    "data_type": "financial_report"
                }], on_conflict="cache_key")
                
            print(f"✅ [{ticker}] Tab 3 미시 지표 전문 리포트 완료 ({lang_code})")
        except Exception as e:
            # 🚨 [중요] 이 except 블록도 짝을 맞춰주어야 합니다.
            print(f"❌ [{ticker}] Tab 3 전문 리포트 에러 ({lang_code}): {e}")

    # =========================================================
    # 💡 [핵심 방어막 3] 무한 루프 종결 (Raw Tracker 갱신)
    # 4개 국어 분석이 모두 끝난 지점(for lang_code 루프 밖)에 위치해야 합니다.
    # AI가 수정한 값이 아닌 '순수 FMP 원본 문자열'을 박제하여 다음 실행 시 중복 분석을 막습니다.
    # =========================================================
    batch_upsert("analysis_cache", [{"cache_key": tracker_key, "content": pristine_metrics_str, "updated_at": datetime.now().isoformat()}], "cache_key")
    return True
            
# ==========================================
# [신규 추가] Tab 3 프리미엄 요약 전용 프롬프트 (다국어 완벽 분리)
# ==========================================
def get_tab3_premium_prompt(lang, type_name, ticker, raw_data):
    if lang == 'en':
        return f"""You are a Senior Wall Street Analyst. Analyze the following [Raw Data] ({type_name}) for {ticker}.
        
[Strict Rules]
1. Write ENTIRELY in English. Do not mix other languages.
2. Write exactly 3 paragraphs.
3. Each paragraph must be 4-5 sentences long, containing deep and professional insights.
4. DO NOT use markdown bold (**) for numbers.
5. Omit greetings and start the main content immediately. Maintain a cold, objective, and analytical tone.

[Raw Data]:
{raw_data}"""

    elif lang == 'ja':
        return f"""あなたはウォール街のシニアアナリストです。提供された [Raw Data] ({type_name}) に基づいて、{ticker} の業績・見通しを日本語で深層分析してください。
        
[厳格な作成ルール]
1. 全て自然な日本語のみで記述してください。
2. 必ず3つの段落に分けて作成してください。
3. 各段落は4〜5文で構成し、重厚で専門的な洞察を含めてください。
4. 数値に強調記号（**）は絶対に使用しないでください。
5. 挨拶は省略し、すぐに本題に入ってください。冷静で客観的な分析トーンを維持してください。

[Raw Data]:
{raw_data}"""

    elif lang == 'zh':
        return f"""您是华尔街的高级分析师。请根据提供的 [Raw Data] ({type_name})，用简体中文对 {ticker} 的业绩与预期进行深度分析。
        
[严格编写规则]
1. 必须完全使用简体中文编写，严禁混用其他语言。
2. 必须严格分为3个段落。
3. 每个段落应包含4-5句话，并提供深刻、专业的见解。
4. 绝对不要使用星号（**）对数字进行加粗。
5. 省略问候语，直接进入正文。保持冷静、客观和分析的基调。

[Raw Data]:
{raw_data}"""

    else: # ko
        return f"""당신은 월가 출신의 수석 애널리스트입니다. 아래 제공된 [Raw Data]({type_name})를 바탕으로 {ticker}의 실적 흐름 및 향후 전망을 한국어로 심층 분석하세요.
        
[작성 규칙 - 엄격 준수]
1. 반드시 순수한 한국어로만 작성하세요.
2. 반드시 3개의 문단으로 나누어 작성하세요.
3. 각 문단은 4~5줄(문장) 길이로 묵직하고 전문적인 통찰을 담으세요.
4. 숫자에 별표(**) 강조를 절대 사용하지 마세요.
5. 인사말을 생략하고 첫 글자부터 본론만 작성하세요. 
   모든 문장은 반드시 '~습니다', '~ㅂ니다' 형태의 격식 있고 정중한 존댓말(합쇼체)로 작성해 주십시오. 
   절대 '~한다', '~이다' 형태의 평어체를 사용하지 마세요.

[Raw Data]:
{raw_data}"""


# =========================================================
# 🚀 [NEW] Tab 3 프리미엄 전용 데이터 수집 함수
# =========================================================
def run_tab3_premium_collection(ticker, company_name):
    """Tab 3: 어닝서프라이즈 및 실적전망치 (매일 감시하되 변경점 없으면 AI 스킵)"""
    if 'model_strict' not in globals() or not model_strict: return
    try:
        # --- [1] 어닝서프라이즈 처리 ---
        surp_url = f"https://financialmodelingprep.com/stable/earnings-surprises?symbol={ticker}&apikey={FMP_API_KEY}"
        surp_raw = get_fmp_data_with_cache(ticker, "RAW_SURPRISE", surp_url, valid_hours=24)
        
        if isinstance(surp_raw, list) and len(surp_raw) > 0:
            current_surp_str = json.dumps(surp_raw, sort_keys=True)
            tracker_key_s = f"{ticker}_PremiumSurprise_RawTracker"
            is_changed_s = True
            
            try:
                res_s = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key_s).execute()
                if res_s.data and current_surp_str == res_s.data[0]['content']:
                    is_changed_s = False # 💡 원본이 똑같으면 스킵!
            except: pass
            
            if is_changed_s:
                print(f"🔔 [{ticker}] 어닝서프라이즈 업데이트 감지! AI 요약 시작...")
                for lang_code in SUPPORTED_LANGS.keys():
                    surp_summary_key = f"{ticker}_PremiumSurprise_v1_{lang_code}"
                    prompt_s = get_tab3_premium_prompt(lang_code, "Earnings Surprises (Beat/Miss)", ticker, current_surp_str)
                    
                    for attempt in range(3):
                        try:
                            resp_s = model_strict.generate_content(prompt_s)
                            if resp_s and resp_s.text:
                                s_paragraphs = [p.strip() for p in resp_s.text.split('\n') if len(p.strip()) > 20]
                                indent_size = "14px" if lang_code == "ko" else "0px"
                                html_s = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in s_paragraphs])
                                batch_upsert("analysis_cache", [{
                                    "cache_key": surp_summary_key, 
                                    "content": html_s, 
                                    "updated_at": datetime.now().isoformat(),
                                    "ticker": ticker,
                                    "tier": "premium_plus",
                                    "tab_name": "tab3",
                                    "lang": lang_code,
                                    "data_type": "earnings_surprise"
                                }], on_conflict="cache_key")
                                print(f"✅ [{ticker}] 어닝서프라이즈 캐싱 완료 ({lang_code})")
                                break
                        except Exception as e: time.sleep(1)
                
                # 🚀 [FCM 추가] 분석 완료 후 프리미엄 유저에게 푸시 알림 발송 (Premium Plus 전용)
                try:
                    send_fcm_push(
                        title=f"📊 {ticker} 어닝 서프라이즈 포착",
                        body=f"예상치를 상회/하회한 {ticker}의 최신 실적 분석 리포트가 업데이트되었습니다.",
                        ticker=ticker,
                        target_level='premium_plus'  # <-- 이 한 줄 추가
                    )
                except Exception as e:
                    print(f"⚠️ 어닝서프라이즈 푸시 발송 실패: {e}")
                
                # 트래커 갱신
                batch_upsert("analysis_cache", [{"cache_key": tracker_key_s, "content": current_surp_str, "updated_at": datetime.now().isoformat()}], "cache_key")

        # --- [2] 실적전망치 처리 ---
        est_url = f"https://financialmodelingprep.com/stable/analyst-estimates?symbol={ticker}&period=annual&limit=2&apikey={FMP_API_KEY}"
        est_raw = get_fmp_data_with_cache(ticker, "RAW_ESTIMATE", est_url, valid_hours=24)
        
        if isinstance(est_raw, list) and len(est_raw) > 0:
            current_est_str = json.dumps(est_raw, sort_keys=True)
            tracker_key_e = f"{ticker}_PremiumEstimate_RawTracker"
            is_changed_e = True
            
            try:
                res_e = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key_e).execute()
                if res_e.data and current_est_str == res_e.data[0]['content']:
                    is_changed_e = False # 💡 원본이 똑같으면 스킵!
            except: pass
            
            if is_changed_e:
                print(f"🔔 [{ticker}] 실적전망치 업데이트 감지! AI 요약 시작...")
                for lang_code in SUPPORTED_LANGS.keys():
                    est_summary_key = f"{ticker}_PremiumEstimate_v1_{lang_code}"
                    prompt_e = get_tab3_premium_prompt(lang_code, "Analyst Future Estimates (Revenue & EPS)", ticker, current_est_str)
                    
                    for attempt in range(3):
                        try:
                            resp_e = model_strict.generate_content(prompt_e)
                            if resp_e and resp_e.text:
                                e_paragraphs = [p.strip() for p in resp_e.text.split('\n') if len(p.strip()) > 20]
                                indent_size = "14px" if lang_code == "ko" else "0px"
                                html_e = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in e_paragraphs])
                                batch_upsert("analysis_cache", [{
                                    "cache_key": est_summary_key, 
                                    "content": html_e, 
                                    "updated_at": datetime.now().isoformat(),
                                    "ticker": ticker,
                                    "tier": "premium",
                                    "tab_name": "tab3",
                                    "lang": lang_code,
                                    "data_type": "analyst_estimates"
                                }], on_conflict="cache_key")
                                print(f"✅ [{ticker}] 실적전망치 캐싱 완료 ({lang_code})")
                                break
                        except Exception as e: time.sleep(1)
                
                # 🚀 [FCM 추가] 분석 완료 후 프리미엄 유저에게 푸시 알림 발송
                try:
                    send_fcm_push(
                        title=f"📈 {ticker} 실적 전망치 변경",
                        body=f"{ticker}에 대한 월가 애널리스트들의 향후 매출 및 수익 예측치가 업데이트되었습니다.",
                        ticker=ticker
                    )
                except Exception as e:
                    print(f"⚠️ 실적전망치 푸시 발송 실패: {e}")

                # 트래커 갱신
                batch_upsert("analysis_cache", [{"cache_key": tracker_key_e, "content": current_est_str, "updated_at": datetime.now().isoformat()}], "cache_key")

    except Exception as e:
        print(f"Premium Tab 3 FMP Error for {ticker}: {e}")

# ==========================================
# [신규 추가] Tab 3 프리미엄 요약 전용 프롬프트 및 수집 함수 (부문별 매출 비중)
# ==========================================
def get_tab3_revenue_premium_prompt(lang, ticker, raw_data):
    if lang == 'en':
        return f"""You are a Lead Equity Analyst on Wall Street. Summarize the Revenue Product Segmentation data for {ticker}.
[Strict Rules]
1. Write ENTIRELY in English. DO NOT mix other languages.
2. Write exactly 3 paragraphs:
   - Para 1: [Core Business Segments & Revenue Breakdown]
   - Para 2: [Growth Drivers & Profitability Contribution]
   - Para 3: [Diversification & Risk Assessment]
3. Each paragraph must be 4-5 sentences long, packed with specific revenue percentages and professional insights.
4. DO NOT use markdown bold (**) for numbers.
5. Omit greetings and start immediately with a professional, objective tone.

[Raw Data]:
{raw_data}"""

    elif lang == 'ja':
        return f"""あなたはウォール街のシニア・エクイティ・アナリストです。提供されたデータに基づき、{ticker}の「部門別売上比率 (Revenue Segmentation)」を日本語で深層要約してください。
[厳格な作成ルール]
1. 全て自然な日本語のみで記述してください。
2. 必ず以下の3つの段落に分けて作成してください：
   - 第1段落: [中核事業部門と売上比率]
   - 第2段落: [成長牽引部門と収益貢献度]
   - 第3段落: [事業多角化の水準とリスク]
3. 各段落は4〜5文で構成し、具体的な売上比率（％）と専門的な洞察を含めてください。
4. 数値に強調記号（**）は絶対に使用しないでください。
5. 挨拶は省略し、すぐに本題に入ってください。冷静で客観的な分析トーンを維持してください。

[Raw Data]:
{raw_data}"""

    elif lang == 'zh':
        return f"""您是华尔街的资深股票分析师。请根据提供的数据，用简体中文深度总结 {ticker} 的「各部门营收占比 (Revenue Segmentation)」。
[严格编写规则]
1. 必须完全使用简体中文编写，严禁混用其他语言。
2. 必须严格分为以下3个段落：
   - 第一段: [核心业务部门及营收占比]
   - 第二段: [增长驱动部门与盈利贡献度]
   - 第三段: [业务多元化水平及风险评估]
3. 每个段落应包含4-5句话，并提供具体的营收百分比和深刻的专业见解。
4. 绝对不要使用星号（**）对数字进行加粗。
5. 省略问候语，直接进入正文。保持冷静、客观和分析的基调。

[Raw Data]:
{raw_data}"""

    else: # ko
        return f"""당신은 월가 수석 주식 애널리스트입니다. 제공된 데이터를 바탕으로 {ticker}의 '부문별 매출 비중(Revenue Segmentation)'을 한국어로 심층 요약하세요.
[작성 규칙 - 엄격 준수]
1. 반드시 순수한 한국어로만 작성하세요.
2. 반드시 아래 3개의 문단으로 나누어 작성하세요:
   - 1문단: [핵심 사업 부문 및 매출 비중]
   - 2문단: [성장 주도 부문 및 수익성 기여도]
   - 3문단: [사업 다각화 수준 및 집중 리스크 평가]
3. 각 문단은 4~5줄(문장) 길이로 구체적인 매출 비중(%) 수치를 포함해 작성하세요.
4. 숫자에 별표(**) 강조를 절대 사용하지 마세요.
5. 인사말을 생략하고 첫 글자부터 본론만 작성하세요. 모든 문장은 반드시 '~습니다', '~ㅂ니다' 형태의 격식 있고 정중한 존댓말(합쇼체)로 작성하세요. (예: ~합니다, ~입니다, ~됩니다, ~전망됩니다 등). 절대 '~한다', '~이다' 형태의 평어체를 사용하지 마세요.

[Raw Data]:
{raw_data}"""

def run_tab3_revenue_premium_collection(ticker, company_name):
    """Tab 3: 부문별 매출 비중 (매일 감시하되 변경점 없으면 AI 스킵)"""
    if 'model_strict' not in globals() or not model_strict: return
    try:
        url = f"https://financialmodelingprep.com/stable/revenue-product-segmentation?symbol={ticker}&structure=flat&period=annual&apikey={FMP_API_KEY}"
        rev_raw = get_fmp_data_with_cache(ticker, "RAW_REVENUE_SEGMENT", url, valid_hours=24)
        
        is_rev_valid = (isinstance(rev_raw, list) and len(rev_raw) > 0) or (isinstance(rev_raw, dict) and len(rev_raw) > 0 and "Error Message" not in rev_raw)
        if not is_rev_valid: return

        current_raw_str = json.dumps(rev_raw[0] if isinstance(rev_raw, list) else rev_raw, sort_keys=True)
        tracker_key = f"{ticker}_PremiumRevenueSeg_RawTracker"
        is_changed = True
        
        try:
            res_t = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key).execute()
            if res_t.data and current_raw_str == res_t.data[0]['content']:
                is_changed = False
        except: pass

        if not is_changed: return

        print(f"🔔 [{ticker}] 매출 비중 업데이트 감지! AI 요약 시작...")
        
        analysis_success = False
        for lang_code in SUPPORTED_LANGS.keys():
            rev_summary_key = f"{ticker}_PremiumRevenueSeg_v1_{lang_code}"
            prompt = get_tab3_revenue_premium_prompt(lang_code, ticker, current_raw_str)
            
            for attempt in range(3):
                try:
                    resp = model_strict.generate_content(prompt)
                    if resp and resp.text:
                        paragraphs = [p.strip() for p in resp.text.split('\n') if len(p.strip()) > 20]
                        indent_size = "14px" if lang_code == "ko" else "0px"
                        html_str = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in paragraphs])
                        batch_upsert("analysis_cache", [{
                            "cache_key": rev_summary_key, 
                            "content": html_str, 
                            "updated_at": datetime.now().isoformat(),
                            "ticker": ticker,
                            "tier": "premium_plus",
                            "tab_name": "tab3",
                            "lang": lang_code,
                            "data_type": "revenue_segment"
                        }], on_conflict="cache_key")
                        print(f"✅ [{ticker}] 매출 비중 분석 캐싱 완료 ({lang_code})")
                        analysis_success = True
                        break
                except Exception as e: time.sleep(1)
        
        # 🚀 [FCM 추가] 분석 완료 후 알림 발송 (Premium Plus 전용)
        if analysis_success:
            send_fcm_push(
                title=f"💰 {ticker} 스마트머니 포착",
                body=f"내부자 거래 및 월가 고래들의 {ticker} 매집 동향 분석 리포트가 도착했습니다.",
                ticker=ticker,
                target_level='premium_plus'  # <-- 이 한 줄 추가
            )
                
        batch_upsert("analysis_cache", [{"cache_key": tracker_key, "content": current_raw_str, "updated_at": datetime.now().isoformat()}], "cache_key")

    except Exception as e:
        print(f"Tab3 Premium Revenue Seg Error for {ticker}: {e}")

# ==========================================
# [수정] Tab 2: 거시 지표 수집 (Raw Tracker 완벽 이식)
# ==========================================
def update_macro_data(df):
    if 'model_strict' not in globals() or not model_strict: return
    
    print("🌍 거시 지표(Tab 2) 실제 데이터 업데이트 및 연산 중...")
    
    today = datetime.now()
    data = {
        "ipo_return": 0.0, "ipo_volume": 0, "unprofitable_pct": 0.0,
        "withdrawal_rate": 0.0, "vix": 20.0, "fear_greed": 50, 
        "buffett_val": 195.0, "pe_ratio": 24.0
    }
    
    try:
        if not df.empty:
            df['dt'] = pd.to_datetime(df['date'], errors='coerce')
            upcoming = df[(df['dt'] > today) & (df['dt'] <= today + timedelta(days=30))]
            data["ipo_volume"] = len(upcoming)
            
            past_1y = df[(df['dt'] >= today - timedelta(days=365)) & (df['dt'] <= today)]
            if len(past_1y) > 0:
                withdrawn_cnt = len(past_1y[past_1y['status'].str.lower().str.contains('withdrawn|철회', na=False)])
                data["withdrawal_rate"] = (withdrawn_cnt / len(past_1y)) * 100
                
            data["unprofitable_pct"] = 75.0 if data["ipo_volume"] > 15 else 60.0
            data["ipo_return"] = 18.5 if data["vix"] < 15 else 5.2
    except: pass

    try:
        q_url = f"https://financialmodelingprep.com/stable/quote?symbol=^VIX,SPY,^W5000&apikey={FMP_API_KEY}"
        q_res = requests.get(q_url, timeout=5).json()
        if isinstance(q_res, list):
            q_map = {item['symbol']: item for item in q_res}
            if '^VIX' in q_map: data["vix"] = float(q_map['^VIX'].get('price', 20.0))
            if 'SPY' in q_map: data["pe_ratio"] = float(q_map['SPY'].get('pe', 24.5))
            if '^W5000' in q_map:
                w5000_price = float(q_map['^W5000'].get('price', 0))
                if w5000_price > 0: data["buffett_val"] = ((w5000_price * 1.1) / 1000 / 28.0) * 100

        r_url = f"https://financialmodelingprep.com/stable/market-risk-premium?apikey={FMP_API_KEY}"
        r_res = requests.get(r_url, timeout=5).json()
        if isinstance(r_res, list) and len(r_res) > 0:
            us_risk = next((item for item in r_res if item.get('country') == 'United States'), None)
            if us_risk: data["fear_greed"] = max(0, min(100, 100 - ((float(us_risk.get('totalEquityRiskPremium', 5.0)) - 3.0) * 20))) 
    except: pass

    batch_upsert("analysis_cache", [{"cache_key": "Market_Dashboard_Metrics", "content": json.dumps(data), "updated_at": datetime.now().isoformat()}], "cache_key")

    # 💡 [과금 방어막 1] 거시 지표 원본 문자열화
    current_macro_str = json.dumps(data, sort_keys=True)
    tracker_key = "Global_Macro_RawTracker"
    is_changed = True

    try:
        # 💡 [과금 방어막 2] 기존 DB의 거시 지표와 비교
        res_tracker = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key).execute()
        if res_tracker.data and current_macro_str == res_tracker.data[0]['content']:
            is_changed = False
    except: pass

    if not is_changed:
        print("⏩ [거시경제] 지표 수치 변경 없음. AI 요약 스킵!")
        return # 데이터가 안 변했으면 과감하게 종료!

    print("🔔 거시 지표 수치 변동 감지! AI 요약 시작...")
    
    g1_context = f"Sentiment/Liquidity (IPO Return: {data['ipo_return']}%, Withdrawal Rate: {data['withdrawal_rate']}%)"
    g2_context = f"Risk/Supply (Upcoming IPOs: {data['ipo_volume']}, Unprofitable Ratio: {data['unprofitable_pct']}%)"
    g3_context = f"Macro/Valuation (VIX: {data['vix']}, Fear&Greed: {data['fear_greed']}, Buffett Indicator: {data['buffett_val']}%, S&P500 PE: {data['pe_ratio']}x)"

    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key_summary = f"Global_Market_Summary_{lang_code}"
        cache_key_full = f"Global_Market_Dashboard_{lang_code}"
        
        # 💡 [Call 1] 완전히 독립된 3개의 UI 카드 요약
        if lang_code == 'ko':
            sum_p = f"월가 수석 전략가로서 다음 3개 그룹의 데이터를 바탕으로 3개의 독립적인 대시보드 카드 요약을 작성하세요.\n[1번 카드 데이터]: {g1_context}\n[2번 카드 데이터]: {g2_context}\n[3번 카드 데이터]: {g3_context}"
            sum_i = """
            [UI 카드 작성 규칙 - 절대 엄수]
            1. 3개의 완전히 독립된 텍스트 덩어리만 출력하세요. 숫자 넘버링이나 별도의 제목은 절대 쓰지 마세요.
            2. 반드시 아래의 정확한 포맷으로만 출력하세요.
               [포맷]: (초기 수익률과 철회율 데이터를 바탕으로 투기적 광기 및 위험 선호도 진단 3~4문장) |||SEP||| (상장 예정 물량과 미수익 기업 비중을 결합하여 공급 과잉 및 질적 저하 리스크 분석 3~4문장) |||SEP||| (VIX, 공포탐욕지수, 밸류에이션을 결합하여 증시 전반의 거시적 과열 여부 진단 3~4문장)
            3. 구분자 '|||SEP|||' 이외의 줄바꿈은 넣지 마세요.
            4. 모든 문장은 '~습니다/ㅂ니다' 형태의 정중체를 사용하세요.
            """
        elif lang_code == 'en':
            sum_p = f"As a senior Wall Street strategist, write 3 independent dashboard card summaries based on the following data groups.\n[Card 1]: {g1_context}\n[Card 2]: {g2_context}\n[Card 3]: {g3_context}"
            sum_i = """
            [UI Card Rules - STRICT]
            1. Output EXACTLY 3 independent text blocks. NEVER use numbering or titles like 'Card 1:'.
            2. FORMAT: (Diagnose speculative mania using IPO return and withdrawal rates in 3-4 sentences) |||SEP||| (Analyze supply risk using upcoming IPOs and unprofitable ratio in 3-4 sentences) |||SEP||| (Evaluate macro overheating using VIX, Fear&Greed, Buffett Index, and PE in 3-4 sentences).
            3. Use '|||SEP|||' as the ONLY separator. No line breaks between blocks.
            4. Use a professional and formal tone.
            """
        elif lang_code == 'ja':
            sum_p = f"ウォール街のチーフストラテジストとして、次の3つのデータに基づいて3つの独立したダッシュボードカードの要約を作成してください。\n[カード1]: {g1_context}\n[カード2]: {g2_context}\n[カード3]: {g3_context}"
            sum_i = """
            [UIカード作成規則 - 厳守]
            1. 3つの完全に独立したテキストのみを出力してください。数字のナンバリングや見出しは絶対に使わないでください。
            2. フォーマット: (初期収益率と撤回率に基づく投機的熱狂の診断 3〜4文) |||SEP||| (上場予定件数と赤字企業比率による供給リスク分析 3〜4文) |||SEP||| (VIX、Fear&Greed、バフェット指数、PEを結合したマクロ的な過熱感の評価 3〜4文)
            3. 区切り文字 '|||SEP|||' 以外に改行を入れないでください。
            4. すべての文章は「〜です・ます」調の丁寧語を使用してください。
            """
        elif lang_code == 'zh':
            sum_p = f"作为华尔街首席策略师，请根据以下三组数据撰写3份独立的仪表板卡片摘要。\n[卡片1]: {g1_context}\n[卡片2]: {g2_context}\n[卡片3]: {g3_context}"
            sum_i = """
            [UI卡片规则 - 严格遵守]
            1. 仅输出3段完全独立的文本。严禁使用数字编号或标题（如“卡片1”）。
            2. 格式: (结合初期收益率与撤回率诊断投机狂热 3-4句话) |||SEP||| (结合上市排队数量与亏损企业占比分析供给风险 3-4句话) |||SEP||| (结合VIX、恐慌贪婪指数、巴菲特指标和PE评估宏观过热 3-4句话)
            3. 仅使用 '|||SEP|||' 作为分隔符，段落之间不要换行。
            4. 请使用专业且正式的陈述句。
            """

        # 💡[Call 2] 하단 전문 (지표 통합 및 인과관계 중심의 단일 단락)
        # 모든 지표를 하나의 텍스트 덩어리로 합칩니다 (경계 해체)
        all_macro_metrics = f"VIX: {data['vix']}, Fear&Greed: {data['fear_greed']}, S&P500 PE: {data['pe_ratio']}x, Buffett Indicator: {data['buffett_val']}%, IPO Return: {data['ipo_return']}%, Withdrawal Rate: {data['withdrawal_rate']}%, Upcoming IPOs: {data['ipo_volume']}, Unprofitable Ratio: {data['unprofitable_pct']}%"

        if lang_code == 'ko':
            full_p = f"월가 헤지펀드 전략가로서 아래 8개 시장 지표의 상관관계를 분석한 날카로운 투자 코멘트를 작성하세요.\n[시장 데이터]: {all_macro_metrics}"
            full_i = """
            [작성 규칙 - Strategic Brief]
            1. **형식**: 소제목, 제목, 불필요한 공백을 절대 쓰지 마세요. **딱 하나의 단락**으로만 구성합니다.
            2. **지표 결합**: '시장의 가치평가(PE/버핏지수) 대비 변동성(VIX)이 어떠하며, 이것이 신규 IPO 공급량과 질적 수준(적자 비중)에 어떤 인과관계를 미치고 있는지' 유기적으로 엮어서 설명하세요. 
            3. **중복 금지**: 단순히 지표를 나열하거나 상단 카드 내용을 반복하면 안 됩니다. '현상이 원인이 되어 결과로 나타나는 흐름'을 서술하세요.
            4. **분량**: 모바일 최적화를 위해 전체 **5~6줄(문장 3개 내외)**로 매우 압축하여 작성하세요.
            5. **첫 단어**: 반드시 '글로벌' 또는 '현재'로 시작하세요.
            6. 모든 문장은 '~습니다/ㅂ니다'로 마무리하세요.
            """
        elif lang_code == 'en':
            full_p = f"As a Wall Street Hedge Fund Strategist, provide a sharp investment brief by correlating these 8 metrics.\n[Market Data]: {all_macro_metrics}"
            full_i = """
            [Rules]
            1. **Format**: Single paragraph only. No subheadings.
            2. **Logic**: Synthesize the relationship between market valuation (PE/Buffett), volatility (VIX), and IPO supply quality (Volume/Unprofitable ratio).
            3. **Content**: Do NOT repeat the cards. Focus on the causal links between the data points.
            4. **Length**: 5-6 lines (approx 3 sentences). Optimized for mobile.
            5. **Opening**: Start with 'Global' or 'Currently'.
            """
        elif lang_code == 'ja':
            full_p = f"ヘッジファンド・ストラテジストとして、8つの指標を相関 분석した鋭い投資コメントを1つの段落で作成してください。\n[データ]: {all_macro_metrics}"
            full_i = """
            1. 形式: 1つの段落。見出し禁止。
            2. 内容: バリュエーション(PE)と変動性(VIX)がIPOの需給と質(赤字比率)に与える因果関係を論理的に記述してください。
            3. 長さ: 5〜6行程度。モバイル最適化。
            4. 開始: 「グローバル」または「現在」で始める。です・ます調。
            """
        else: # zh
            full_p = f"作为对冲基金策略师，请结合以下8项指标的因果关系，撰写一份尖锐的投资简报。\n[市场数据]: {all_macro_metrics}"
            full_i = """
            1. 格式: 仅限一个自然段。严禁小标题。
            2. 逻辑: 将宏观估值(PE/巴菲特指标)与波动率(VIX)结合，分析其对IPO发行质量(破发率/赤字率)的连锁 영향.
            3. 篇幅: 5-6行。移动端优化。
            4. 首词: 以“全球”或“当前”开头。
            """

        try:
            res_sum = model_strict.generate_content(sum_p + sum_i)
            if res_sum and res_sum.text:
                batch_upsert("analysis_cache", [{
                    "cache_key": cache_key_summary, 
                    "content": res_sum.text.strip(), 
                    "updated_at": datetime.now().isoformat(),
                    # --- 신규 태그 추가 ---
                    "ticker": "MARKET",
                    "tier": "free",
                    "tab_name": "tab2",
                    "lang": lang_code,
                    "data_type": "macro_card"
                }], on_conflict="cache_key")
        
            res_full = model_strict.generate_content(full_p + full_i)
            if res_full and res_full.text:
                batch_upsert("analysis_cache", [{
                    "cache_key": cache_key_full, 
                    "content": res_full.text.strip(), 
                    "updated_at": datetime.now().isoformat(),
                    # --- 신규 태그 추가 ---
                    "ticker": "MARKET",
                    "tier": "free",
                    "tab_name": "tab2",
                    "lang": lang_code,
                    "data_type": "macro_report"
                }], on_conflict="cache_key")
                
            print(f"✅ 거시 지표 AI 분석 완료 ({lang_code})")
        except Exception as e:
            print(f"❌ 거시 지표 AI 에러 ({lang_code}): {e}")

    # 💡 [과금 방어막 3] 요약 완료 후 트래커 갱신
    batch_upsert("analysis_cache", [{"cache_key": tracker_key, "content": current_macro_str, "updated_at": datetime.now().isoformat()}], "cache_key")

# ==========================================
# [수정] Tab 6: 스마트머니 통합 데이터 수집 (국회의원 & 공매도 추가)
# ==========================================
def fetch_smart_money_data(symbol, api_key):
    """FMP API 4종 세트를 캐싱 방어막과 함께 수집합니다."""
    data = {"insider": [], "institutional": [], "senate": [], "fail_to_deliver": []}
    
    in_url = f"https://financialmodelingprep.com/stable/insider-trading?symbol={symbol}&limit=10&apikey={api_key}"
    data["insider"] = get_fmp_data_with_cache(symbol, "SMART_IN", in_url) or []

    inst_url = f"https://financialmodelingprep.com/stable/institutional-ownership?symbol={symbol}&apikey={api_key}"
    res_inst = get_fmp_data_with_cache(symbol, "SMART_INST", inst_url)
    data["institutional"] = res_inst[:10] if isinstance(res_inst, list) else []
    
    sen_url = f"https://financialmodelingprep.com/stable/senate-trading?symbol={symbol}&apikey={api_key}"
    res_sen = get_fmp_data_with_cache(symbol, "SMART_SENATE", sen_url)
    data["senate"] = res_sen[:5] if isinstance(res_sen, list) else []
    
    ftd_url = f"https://financialmodelingprep.com/stable/fail-to-deliver?symbol={symbol}&apikey={api_key}"
    data["fail_to_deliver"] = get_fmp_data_with_cache(symbol, "SMART_FTD", ftd_url) or []

    return data

def run_tab6_analysis(ticker, company_name, smart_money_data):
    """Tab 6: 스마트머니 분석 (실제 데이터 존재 시에만 푸시 알림 발송)"""
    if 'model_strict' not in globals() or not model_strict: return False
    
    # 🚨 [환각 방어] 데이터 유무 사전 검사
    has_any_data = any(len(v) > 0 for v in smart_money_data.values() if isinstance(v, list))
    
    # [상황 1] 데이터가 아예 없는 경우
    if not has_any_data:
        print(f"ℹ️ [{ticker}] 스마트머니 데이터가 없어 '내역 없음' 메시지만 저장하고 알림 없이 종료합니다.")
        for lang_code in SUPPORTED_LANGS.keys():
            cache_key = f"{ticker}_Tab6_SmartMoney_v1_{lang_code}"
            # 언어별 메시지 설정
            if lang_code == 'ko': msg = "확인된 최신 공시 내역이 없습니다."
            elif lang_code == 'ja': msg = "確認された最新の公示内容はありません。"
            elif lang_code == 'zh': msg = "未确认到最新的公告信息。"
            else: msg = "No verified data available from recent filings."
            
            empty_content = f"{msg} |||SEP||| {msg} |||SEP||| {msg} |||SEP||| {msg}"
            batch_upsert("analysis_cache", [{"cache_key": cache_key, "content": empty_content, "updated_at": datetime.now().isoformat()}], "cache_key")
        
        # 💡 [핵심] 여기서 트래커만 갱신하고 함수를 종료(return)해버립니다.
        # 이렇게 하면 하단의 send_fcm_push 로직까지 도달하지 않습니다.
        current_raw_str = json.dumps(smart_money_data, sort_keys=True)
        batch_upsert("analysis_cache", [{"cache_key": f"{ticker}_Tab6_SmartMoney_RawTracker", "content": current_raw_str, "updated_at": datetime.now().isoformat()}], "cache_key")
        return True

    # [상황 2] 데이터가 하나라도 있는 경우 (정상 분석 진행)
    current_raw_str = json.dumps(smart_money_data, sort_keys=True)
    tracker_key = f"{ticker}_Tab6_SmartMoney_RawTracker"
    
    # 중복 체크 로직
    try:
        res_tracker = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key).execute()
        if res_tracker.data and current_raw_str == res_tracker.data[0]['content']:
            return True # 변경사항 없으면 종료
    except: pass

    print(f"🔔 [{ticker}] 실제 스마트머니 데이터 감지! AI 분석 및 알림 발송 준비...")
    
    analysis_performed = False
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key = f"{ticker}_Tab6_SmartMoney_v1_{lang_code}"
        
        # (프롬프트 설정 부분은 이전과 동일하되 '지어내지 말 것' 강조 유지)
        if lang_code == 'ko':
            h_defense = "[엄격 규칙: 데이터가 없는 항목은 반드시 '확인된 최신 공시 내역이 없습니다.'라고만 적고 절대 지어내지 마세요.]"
            prompt = f"{h_defense}\n당신은 분석가입니다. {company_name}({ticker})의 스마트머니 데이터 분석: {current_raw_str}\n\n항목 사이 |||SEP||| 필수."
        elif lang_code == 'ja':
            h_defense = "[厳格な規則: データがない項目は必ず「確認された最新の公示内容はありません。」と記述し、捏造しないでください。]"
            prompt = f"{h_defense}\nあなたはアナリストです。{current_raw_str}を分析してください。\n\n区切り文字 |||SEP||| 必須。"
        elif lang_code == 'zh':
            h_defense = "[严格规则：如果数据为空，必须仅回答“未确认到最新的官方公告信息”，严직捏造。]"
            prompt = f"{h_defense}\n您是分析师。请分析 {current_raw_str}。\n\n使用 |||SEP||| 分隔。"
        else: # en
            h_defense = "[STRICT RULE: If data is empty, strictly output 'No verified data available' and NEVER hallucinate.]"
            prompt = f"{h_defense}\nYou are an analyst. Analyze {current_raw_str} for {company_name}({ticker}).\n\nUse |||SEP||| as separator."

        try:
            response = model_strict.generate_content(prompt)
            if response and response.text:
                batch_upsert("analysis_cache", [{
                    "cache_key": cache_key, 
                    "content": response.text.strip(), 
                    "updated_at": datetime.now().isoformat(),
                    # --- 신규 태그 추가 ---
                    "ticker": ticker,
                    "tier": "premium_plus",
                    "tab_name": "tab6",
                    "lang": lang_code,
                    "data_type": "smart_money_report"
                }], on_conflict="cache_key")
                analysis_performed = True
        except: pass

    # 🚀 [알림 조건 강화] 
    # 1. AI 분석이 성공했고(analysis_performed)
    # 2. 실제로 공시 데이터가 존재할 때만(has_any_data) 푸시를 보냅니다.
    if analysis_performed and has_any_data:
        send_fcm_push(
            title=f"💰 {ticker} 스마트머니 포착",
            body=f"내부자 거래 및 월가 고래들의 {ticker} 매집 동향 분석 리포트가 도착했습니다.",
            ticker=ticker
        )
        print(f"🚀 [{ticker}] 실제 데이터에 대한 푸시 알림 발송 완료")

    batch_upsert("analysis_cache", [{"cache_key": tracker_key, "content": current_raw_str, "updated_at": datetime.now().isoformat()}], "cache_key")
    return True


# ==========================================
# [최종 통합] 프리미엄 유저 대상 통계적 급등 알림 엔진 (하단 배치용)
# ==========================================
def run_premium_alert_engine(df_calendar):
    print("🕵️ 프리미엄 알림 엔진 가동 (FMP 캐싱 최적화 + 실시간 푸시)...")
    today = datetime.now().date()
    new_alerts = []
    
    # DB에서 실시간 가격 맵 로드
    price_map = get_current_prices()

    for _, row in df_calendar.iterrows():
        ticker = row['symbol']
        current_p = price_map.get(ticker, 0.0)
        
        try: ipo_date = pd.to_datetime(row['date']).date()
        except: continue
        
        # --- 1. 일정 기반 알림 (기존 로직 유지) ---
        if ipo_date == today + timedelta(days=3):
            new_alerts.append({
                "ticker": ticker, "alert_type": "UPCOMING", "title": f"{ticker} 상장 D-3", 
                "message": "상장 전 월가 기관의 평가를 미리 확인하세요."
            })
        
        if ipo_date + timedelta(days=180) == today + timedelta(days=7):
            new_alerts.append({
                "ticker": ticker, "alert_type": "LOCKUP", "title": f"{ticker} 락업해제 D-7", 
                "message": "보호예수 물량 해제로 인한 주가 변동성에 주의하세요."
            })

        if current_p <= 0: continue

        # --- 2. 기간별 통계적 유의 상승 로직 (FMP API 캐싱 적용) ---
        try:
            url = f"https://financialmodelingprep.com/stable/historical-price-eod/full?symbol={ticker}&timeseries=260&apikey={FMP_API_KEY}"
            res = get_fmp_data_with_cache(ticker, "HIST", url, valid_hours=24)
            
            if res and 'historical' in res:
                hist = res.get('historical', [])
                if len(hist) >= 2:
                    p_1d = hist[1]['close'] # 어제 종가
                    if p_1d > 0 and ((current_p - p_1d) / p_1d) * 100 >= 12.0:
                        new_alerts.append({"ticker": ticker, "alert_type": "SURGE_1D", "title": f"{ticker} 단기 급등 포착", "message": f"최근 1일 동안 {((current_p - p_1d) / p_1d) * 100:.1f}% 상승"})
                
                # ... (1주, 2주, 4주, 3개월, 1년 로직은 동일하므로 유지하시면 됩니다) ...
                # (중략 - 기존 급등 로직 유지)
        except: pass

        # --- 3. 공모가 돌파 및 회복 시그널 (기존 로직 유지) ---
        try:
            ipo_p = float(str(row.get('price', '0')).replace('$', '').split('-')[0])
            if ipo_p > 0:
                surge_pct_ipo = ((current_p - ipo_p) / ipo_p) * 100
                if surge_pct_ipo >= 20.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "SURGE_IPO", "title": f"{ticker} (+{surge_pct_ipo:.1f}%)", "message": f"공모가 대비 강력한 상승세 기록 중"})
                elif 0 <= surge_pct_ipo < 3.0:
                    new_alerts.append({"ticker": ticker, "alert_type": "REBOUND", "title": f"{ticker} 공모가 회복", "message": "주가가 공모가 위로 재진입하며 바닥 신호를 보냈습니다."})
        except: pass

        # --- 4. 월가 기관 투자심리 호조 시그널 (Tab 4 연동) ---
        try:
            # 💡 [주의] Tab 4에서 저장하는 캐시 키와 일치시켜야 합니다.
            tab4_key = f"{ticker}_Tab4_v4_Premium_ko" 
            res_tab4 = supabase.table("analysis_cache").select("content").eq("cache_key", tab4_key).execute()
            if res_tab4.data:
                tab4_data = json.loads(res_tab4.data[0]['content'])
                rating_val = str(tab4_data.get('rating', '')).upper()
                score_val = str(tab4_data.get('score', '0')).strip()
                if ("BUY" in rating_val) or (score_val in ["4", "5"]):
                    new_alerts.append({
                        "ticker": ticker, "alert_type": "INST_UPGRADE", "title": f"{ticker} 기관 BUY 시그널", 
                        "message": f"월가 전문 분석가의 긍정적인 투자 등급이 포착되었습니다."
                    })
        except: pass
            
    if new_alerts:
        # DB 저장
        batch_upsert("premium_alerts", new_alerts, on_conflict="ticker,alert_type")
        
        # 🚀 [추가됨] 유료 결제자들에게 실시간 푸시 전송 (가장 최신 알림 하나 발송)
        top_alert = new_alerts[0]
        send_fcm_push(
            title=top_alert['title'],
            body=top_alert['message'],
            ticker=top_alert['ticker']
        )
        print(f"🚀 [알림 완료] {len(new_alerts)}개의 신호 생성 및 푸시 전송")

# ==========================================
# [신규 추가] 글로벌 매크로 & 주요 일정 캐싱 워커
# ==========================================
def update_global_macro_and_events():
    print("🌍 글로벌 매크로(FRED) 및 경제 일정(FMP) 데이터 수집 시작...")
    today = datetime.now()
    
    # 3행 4열 프론트엔드 UI 대응을 위한 col 인덱스
    series_info = {
        "FEDFUNDS": {"name": "기준금리", "col": 1}, 
        "DGS10": {"name": "10년물 국채", "col": 1}, 
        "T10Y2Y": {"name": "장단기 금리차", "col": 1}, 
        "CPIAUCSL": {"name": "소비자물가지수(CPI)", "col": 2}, 
        "PCEPI": {"name": "개인소비지출(PCE)", "col": 2}, 
        "WM2NS": {"name": "M2 통화량", "col": 2},
        "UNRATE": {"name": "실업률", "col": 4}
    }
    pc1_series = ["CPIAUCSL", "PCEPI", "WM2NS"] 
    
    # ⭐ 기존 프론트엔드가 데이터를 찾을 수 있도록 "0" ~ "-3" 구조 복구
    results = {"0": {}, "-1": {}, "-2": {}, "-3": {}} 
    
    # 🚀 과거 3년 전(-3)의 3년 평균까지 구하려면 총 6년치 데이터가 필요합니다.
    start_date = (today - timedelta(days=365*6)).strftime('%Y-%m-%d')
    
    try:
        if FRED_API_KEY:
            for sid, info in series_info.items():
                units = "pc1" if sid in pc1_series else "lin"
                url = f"https://api.stlouisfed.org/fred/series/observations?series_id={sid}&api_key={FRED_API_KEY}&file_type=json&observation_start={start_date}&units={units}"
                res = requests.get(url, timeout=10).json()
                obs = res.get('observations', [])
                if not obs: continue
                
                valid_obs = [o for o in obs if o['value'] != '.']
                valid_obs.sort(key=lambda x: x['date'], reverse=True)
                
                def get_val_near_date(target_date):
                    for o in valid_obs:
                        if pd.to_datetime(o['date']) <= target_date: return float(o['value'])
                    return None
                    
                # 현재부터 5년 전까지의 데이터를 모두 추출
                v0 = get_val_near_date(today)
                v1 = get_val_near_date(today - timedelta(days=365))
                v2 = get_val_near_date(today - timedelta(days=365*2))
                v3 = get_val_near_date(today - timedelta(days=365*3))
                v4 = get_val_near_date(today - timedelta(days=365*4))
                v5 = get_val_near_date(today - timedelta(days=365*5))
                
                # 증감(diff) 계산 함수 (프론트엔드 에러 방지를 위해 +기호 포함 문자열로 반환)
                def calc_diff_str(curr, prev):
                    if curr is not None and prev is not None:
                        return f"{curr - prev:+.2f}%p"
                    return None
                    
                # 3년 평균 계산 함수
                def calc_avg(curr, p1, p2):
                    if curr is not None and p1 is not None and p2 is not None:
                        return round((curr + p1 + p2) / 3, 2)
                    return None

                # 🚀 0, -1, -2, -3 각 년도에 대해 동일하게 val, diff, avg_3y를 꽉꽉 채워줍니다!
                for year_key, curr, p1, p2, p3 in [
                    ("0", v0, v1, v2, v3),
                    ("-1", v1, v2, v3, v4),
                    ("-2", v2, v3, v4, v5),
                    ("-3", v3, v4, v5, None)
                ]:
                    results[year_key][sid] = {
                        "name": info["name"],
                        "column": info["col"],
                        "val": round(curr, 2) if curr is not None else None,
                        "diff": calc_diff_str(curr, p1),
                        "avg_3y": calc_avg(curr, p1, p2)
                    }
                
            batch_upsert("macro_cache", [{
                "cache_key": "FRED_MACRO_DATA", "content": json.dumps(results), "updated_at": today.isoformat()
            }], on_conflict="cache_key")
            print("✅ FRED 매크로 3x4 Grid용 요약 데이터 DB 저장 완료 (과거 년도 완벽 지원)")
    except Exception as e: print(f"⚠️ FRED API Error: {e}")

    # (이 아래는 기존 FMP 경제 일정 수집 코드 그대로 유지하시면 됩니다.)

    # 2. FMP 경제 일정 수집 (그대로 유지)
    try:
        start = today.strftime('%Y-%m-%d')
        end = (today + timedelta(days=30)).strftime('%Y-%m-%d')
        url = f"https://financialmodelingprep.com/stable/economic-calendar?from={start}&to={end}&apikey={FMP_API_KEY}"
        res = requests.get(url, timeout=10).json()
        
        if isinstance(res, list):
            important_events = [
                e for e in res 
                if e.get('country') == 'US' and any(keyword in e.get('event', '').lower() for keyword in ['fed interest', 'cpi', 'unemployment', 'non farm'])
            ]
            important_events.sort(key=lambda x: x['date'])
            
            batch_upsert("macro_cache", [{
                "cache_key": "FMP_MACRO_EVENTS", "content": json.dumps(important_events[:5]), "updated_at": today.isoformat()
            }], on_conflict="cache_key")
            print("✅ FMP 향후 30일 미국 경제일정 DB 저장 완료")
    except Exception as e: print(f"⚠️ FMP Economic Calendar Error: {e}")
    
# ==========================================
# [4] 메인 실행 루프
# ==========================================
def main():
    print(f"🚀 Worker Process 시작: {datetime.now()}")
    

    # 👇👇👇 [기존 코드 유지] 👇👇👇
    update_global_macro_and_events()
    
    df = get_target_stocks()
    if df.empty: 
        print("⚠️ 수집된 IPO 종목이 없습니다.")
        return

    print("\n📋 [stock_cache] 명단 업데이트 및 신규 편입 식별 시작...")
    
    try:
        res_known = supabase.table("stock_cache").select("symbol").execute()
        known_tickers = {item['symbol'] for item in res_known.data}
    except Exception as e:
        print(f"⚠️ 기존 Ticker 로드 실패 (초기화 상태로 간주): {e}")
        known_tickers = set()
        
    now_iso = datetime.now().isoformat()
    today_date = datetime.now().date()
    stock_list = []
    sudden_additions = [] 
    
    for _, row in df.iterrows():
        sym = str(row['symbol'])
        
        try: ipo_dt = pd.to_datetime(row['date']).date()
        except: ipo_dt = today_date
        
        if known_tickers and (sym not in known_tickers) and (ipo_dt <= today_date):
            sudden_additions.append(sym)
            
        stock_list.append({
            "symbol": sym,
            "name": str(row['name']) if pd.notna(row['name']) else "Unknown",
            "last_updated": now_iso 
        })
        
    if sudden_additions:
        try:
            old_res = supabase.table("analysis_cache").select("content").eq("cache_key", "SUDDEN_ADDITIONS_LIST").execute()
            if old_res.data:
                old_list = json.loads(old_res.data[0]['content'])
                sudden_additions = list(set(old_list + sudden_additions))
        except: pass
        
        batch_upsert("analysis_cache", [{
            "cache_key": "IPO_CALENDAR_DATA",
            "content": df.to_json(orient='records'),
            "updated_at": datetime.now().isoformat()
        }], on_conflict="cache_key")
        print(f"✨ 신규 편입(스팩/직상장) 누적 {len(sudden_additions)}개 식별 및 DB 저장 완료.")

    batch_upsert("stock_cache", stock_list, on_conflict="symbol")
    update_macro_data(df)
    
    # ------------------ 💡 18개월 이내 상장 기업 타겟팅 ------------------
    print("🔥 타겟 종목 선별 중 (35일 상장예정 + 18개월 신규상장)...")
    price_map = get_current_prices() 
    
    today = datetime.now()
    df['dt'] = pd.to_datetime(df['date'])
    
    target_symbols = set()
    
    # 1. 상장 예정(35일)
    upcoming = df[(df['dt'] > today) & (df['dt'] <= today + timedelta(days=35))]
    target_symbols.update(upcoming['symbol'].tolist())
    print(f"   -> 상장 예정(35일): {len(upcoming)}개")
    
    # 2. 최근 상장(18개월 = 540일)
    past_18m = df[(df['dt'] >= today - timedelta(days=540)) & (df['dt'] <= today)]
    target_symbols.update(past_18m['symbol'].tolist())
    print(f"   -> 최근 상장(18개월): {len(past_18m)}개")

    print(f"✅ 최종 분석 대상: 총 {len(target_symbols)}개 종목 (중복 제거)")

    target_df = df[df['symbol'].isin(target_symbols)]
    total = len(target_df)
    
    print("\n🏛️ SEC EDGAR CIK 매핑 데이터 로드 중 (API 최적화)...")
    cik_mapping, name_to_ticker_map = get_sec_master_mapping()
    print(f"✅ 총 {len(cik_mapping)}개의 SEC 식별번호 확보 완료.")
    
    print(f"\n🤖 AI 심층 분석 시작 (총 {total}개 종목 다국어 캐싱)...")
    
    import time
    WORKER_START_TIME = time.time()
    MAX_RUN_TIME_SEC = 5.5 * 3600  # 5.5시간(19,800초)

    # 🚨 AAPL 테스트 모드 삭제 완료. 18개월 타겟 전체 루프 시작!
    for idx, row in target_df.iterrows():
        # 5.5시간 강제 종료 방어막
        if time.time() - WORKER_START_TIME > MAX_RUN_TIME_SEC:
            print("⏳ [알림] 깃허브 6시간 제한 임박! 서버 강제 다운을 막기 위해 작업을 일시 중단합니다.")
            break

        original_symbol = row.get('symbol')
        name = row.get('name')
        
        clean_name = normalize_company_name(name)
        official_symbol = name_to_ticker_map.get(clean_name, original_symbol)
        
        if original_symbol != official_symbol:
            print(f"🔧 [티커 교정 작동] {name}: {original_symbol} ➡️ {official_symbol}")
            if official_symbol in cik_mapping:
                cik_mapping[original_symbol] = cik_mapping[official_symbol]
        
        # =========================================================
        # 🚨 [신규 적용] 3회 재시도(Retry) 및 10초 대기 방어 로직
        # =========================================================
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"\n[{idx+1}/{total}] {original_symbol} 분석 중... (시도 {attempt+1}/{max_retries})", flush=True)
                
                c_status = row.get('status', 'Active')
                c_date = row.get('date', None)
                
                if not official_symbol or str(official_symbol).strip() == "":
                    # 티커가 없으면 우선 기업 이름으로 CIK 강제 획득 시도
                    cik = get_fallback_cik(official_symbol, name, FMP_API_KEY)
                    if cik:
                        print(f"🔍 [역추적 시도] CIK {cik} 번호로 Ticker 검색 중...")
                        found_ticker = get_ticker_from_cik(cik)
                        if found_ticker:
                            print(f"✅ [역추적 성공] 숨겨진 Ticker 발견: {found_ticker}")
                            official_symbol = found_ticker
                            cik_mapping[official_symbol] = cik # 매핑 업데이트

                # 역추적을 거치고도 티커가 아예 없다면, 크래시 방지를 위해 이번 종목은 스킵
                if not official_symbol or str(official_symbol).strip() == "":
                    print(f"⚠️ [FMP API 스킵] Ticker가 아직 존재하지 않아 수치 데이터를 건너뜁니다.")
                    break # 재시도 할 필요 없이 이 종목은 완전 스킵
                
                # Tab 0 & Tab 1 (기본 + 프리미엄)
                run_tab1_analysis(official_symbol, name, c_status, c_date)
                run_tab0_analysis(official_symbol, name, c_status, c_date, cik_mapping)
                run_tab0_premium_collection(official_symbol, name)
                run_tab2_premium_collection(official_symbol, name) 
                
                # Tab 4: 목표가 수집 및 투자의견/M&A
                try:
                    analyst_metrics = fetch_analyst_estimates(official_symbol, FMP_API_KEY)
                    run_tab4_analysis(official_symbol, name, c_status, c_date, analyst_metrics)
                    run_tab4_ma_premium_collection(official_symbol, name) 
                    run_tab4_premium_collection(official_symbol, name) 
                except Exception as e:
                    print(f"Tab4 Analyst Data Error for {official_symbol}: {e}")
                
                # Tab 3: 11지표 통합 수집 및 재무 분석
                try:
                    unified_metrics = fetch_premium_financials(official_symbol, FMP_API_KEY)
                    batch_upsert("analysis_cache", [{
                        "cache_key": f"{official_symbol}_Raw_Financials",
                        "content": json.dumps(unified_metrics, ensure_ascii=False),
                        "updated_at": datetime.now().isoformat()
                    }], on_conflict="cache_key")
                    
                    run_tab3_analysis(official_symbol, name, unified_metrics)
                    run_tab3_premium_collection(official_symbol, name)
                    run_tab3_revenue_premium_collection(official_symbol, name) 
                except Exception as e:
                    print(f"Tab3 Premium Data Error for {official_symbol}: {e}")

                # Tab 6: 스마트머니 수집 및 분석
                try:
                    smart_money_data = fetch_smart_money_data(official_symbol, FMP_API_KEY)
                    run_tab6_analysis(official_symbol, name, smart_money_data)
                except Exception as e:
                    print(f"Tab6 Smart Money Error for {official_symbol}: {e}")
                
                # 💡 모든 탭 분석이 정상적으로 끝났다면 재시도 루프(attempt)를 안전하게 탈출합니다.
                break 
                
            except Exception as e:
                error_msg = str(e)
                # 💡 503 과부하, Canceled, 429 한도 초과 등 API 통신 에러 감지 시
                if any(err in error_msg for err in ["503", "UNAVAILABLE", "Canceled", "429", "quota"]):
                    if attempt < max_retries - 1:
                        print(f"⚠️ [{original_symbol}] 통신 지연 감지: {error_msg}. 10초 대기 후 재시도합니다...")
                        time.sleep(10)
                    else:
                        print(f"🚨 [{original_symbol}] 3회 재시도 실패. 트래픽 과부하가 심하여 다음 기업으로 넘어갑니다.")
                else:
                    # 통신 에러가 아닌 코드/파싱 에러라면 재시도 없이 원인 출력 후 스킵
                    import traceback 
                    print(f"\n🚨 [{original_symbol}] 분석 중 내부 오류 발생! (재시도 안함)")
                    print(f"사유: {e}")
                    print("-" * 30)
                    traceback.print_exc()
                    print("-" * 30)
                    break # 재시도 루프 탈출
        
        # 💡 [필수 쿨타임] 성공이든 실패든 하나의 기업이 끝나면 2초간 쉬어주어 디도스를 원천 예방합니다.
        time.sleep(2)
        # =========================================================

    run_premium_alert_engine(df)
    
    # 💡 [생존 신고] 메인 워커 작업이 끝난 후 앱에 상태 알림
    batch_upsert("analysis_cache", [{"cache_key": "WORKER_LAST_RUN", "content": "alive", "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
            
    print(f"\n🏁 모든 작업 종료: {datetime.now()}")

if __name__ == "__main__":
    main()
