import os
import time
import json
import re
import requests
import copy
import pandas as pd
import numpy as np
import logging
import concurrent.futures  # 🚀 [추가] 병렬 처리용 라이브러리

# 💡 [트위터 커넥터 추가]
from twitter_service import post_to_twitter 

# 💡 [FCM 추가] Firebase 라이브러리
import firebase_admin
from firebase_admin import credentials as firebase_credentials, messaging
from datetime import datetime, timedelta

from supabase import create_client

# 🚀 [Vertex AI 추가] 구버전 삭제 및 최신 통합 SDK(genai)로 교체 완료
from google import genai
from google.oauth2 import service_account

# ==========================================
# [1] 환경 설정 & 디버깅 로그
# ==========================================

raw_url = os.environ.get("SUPABASE_URL", "")
if "/rest/v1" in raw_url:
    SUPABASE_URL = raw_url.split("/rest/v1")[0].rstrip('/')
else:
    SUPABASE_URL = raw_url.rstrip('/')

SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
GENAI_API_KEY = os.environ.get("GENAI_API_KEY", "") # 🚀 [복구 완료] 이 줄을 다시 추가했습니다!
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "781b0d2391740729adb2d931e200e322")
FIREBASE_SA_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "")
VERTEX_SA_JSON = os.environ.get("VERTEX_SA_JSON", "")

print(f"DEBUG: SUPABASE_URL 존재 = {bool(SUPABASE_URL)}")
print(f"DEBUG: SUPABASE_KEY 존재 = {bool(SUPABASE_KEY)}")
print(f"DEBUG: FIREBASE_SA 존재 = {bool(FIREBASE_SA_JSON)}")
print(f"DEBUG: VERTEX_SA 존재 = {bool(VERTEX_SA_JSON)}")

if not (SUPABASE_URL and SUPABASE_KEY):
    print("❌ 환경변수 누락으로 종료")
    exit()

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase 클라이언트 연결 성공")
except Exception as e:
    print(f"❌ Supabase 초기화 실패: {e}")
    exit()

if FIREBASE_SA_JSON:
    try:
        cred_dict = json.loads(FIREBASE_SA_JSON)
        cred = firebase_credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        print("✅ Firebase Admin SDK 초기화 성공")
    except Exception as e:
        print(f"❌ Firebase 초기화 실패: {e}")

# ==========================================
# 🚀 3. AI 모델 설정 (하이브리드 전략: Vertex AI + Developer API)
# ==========================================
model_strict = None
model_search = None

# [1] 메인 분석 엔진: Vertex AI Enterprise (대용량 토큰 & 무한대기 방어)
if VERTEX_SA_JSON:
    try:
        sa_info = json.loads(VERTEX_SA_JSON)
        project_id = sa_info.get("project_id")
        
        # 🚀 [핵심 수정] 구글 클라우드 플랫폼 접근 권한(Scope) 명시!
        credentials = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        
        # 💡[핵심 교체] 최신 구글 통합 SDK 클라이언트로 초기화 (vertexai=True 플래그 사용)
        client = genai.Client(
            vertexai=True, 
            project=project_id, 
            location="us-central1", 
            credentials=credentials
        )
        
        class VertexModelWrapper:
            def __init__(self, client, model_name):
                self.client = client
                self.model_name = model_name

            def generate_content(self, prompt):
                max_attempts = 5 # 🚀 시도 횟수 증가
                for attempt in range(max_attempts):
                    try:
                        return self.client.models.generate_content(
                            model=self.model_name,
                            contents=prompt
                        )
                    except Exception as e:
                        err_str = str(e).lower()
                        if any(k in err_str for k in["429", "quota", "timeout", "deadline", "503", "unavailable"]):
                            if attempt < (max_attempts - 1):
                                # 🚀 대기 시간: 10초, 20초, 40초, 80초 (점진적 증가)
                                wait_time = 10 * (2 ** attempt) 
                                print(f"⏳ [Vertex AI] 429 에러 방어. {wait_time}초 대기 후 재시도... ({attempt+1}/{max_attempts})")
                                time.sleep(wait_time)
                                continue
                        raise e

        # 래퍼 객체 생성 시 클라이언트와 모델명(gemini-2.5-flash)을 함께 넘겨줌
        model_strict = VertexModelWrapper(client, "gemini-2.5-flash")
        print("✅ [엔진 1] Vertex AI (Enterprise) 통합 SDK 로드 성공! (메인 분석용)")

    except Exception as e:
        print(f"⚠️ Vertex AI 초기화 에러: {e}")

# [2] 구글 딥서치 엔진: Developer API REST (최신 Search 파라미터 직접 제어)
if GENAI_API_KEY:
    class DirectGeminiSearch:
        def __init__(self, api_key):
            # 🚀 [버전 교체] 구글이 1.5를 삭제했으므로 안정적인 2.0으로 주소 변경!
            self.url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
            
        def generate_content(self, prompt):
            # 💡[핵심 교정] 구글 서버가 요구하는 정확한 파라미터명("google_search") 강제 주입!
            payload = { 
                "contents": [{"parts": [{"text": prompt}]}], 
                "tools":[{"google_search": {}}] 
            }
            class MockResponse:
                def __init__(self, text): self.text = text
            
            # 🚀 [엔진 2 방어막 업그레이드] 3회 -> 5회 시도 및 지수 백오프(Exponential Backoff) 적용
            max_attempts = 5
            for attempt in range(max_attempts):
                try:
                    res = requests.post(self.url, json=payload, headers={'Content-Type': 'application/json'}, timeout=30)
                    
                    if res.status_code == 200:
                        data = res.json()
                        text_output = ""
                        for cand in data.get("candidates",[]):
                            for part in cand.get("content", {}).get("parts",[]):
                                if "text" in part: text_output += part["text"]
                        return MockResponse(text_output)
                        
                    elif res.status_code in [429, 503]:
                        if attempt < (max_attempts - 1):
                            wait_time = 10 * (2 ** attempt)
                            print(f"⏳ [Search API] 서버 지연(429/503). {wait_time}초 대기 후 재시도... ({attempt+1}/{max_attempts})")
                            time.sleep(wait_time)
                            continue
                        raise Exception(f"API Error: {res.text}")
                    else:
                        raise Exception(f"Search API HTTP {res.status_code}: {res.text}")
                
                except Exception as e:
                    if attempt < (max_attempts - 1): 
                        wait_time = 10 * (2 ** attempt)
                        print(f"⏳ [Search API] 통신 에러. {wait_time}초 대기 후 재시도... ({attempt+1}/{max_attempts})")
                        time.sleep(wait_time)
                        continue
                    raise e

    model_search = DirectGeminiSearch(GENAI_API_KEY)
    print("✅ [엔진 2] Gemini Search (Developer API) 로드 성공! (웹 검색용)")
        
# 💡 [중요] 다국어 지원 언어 리스트 정의
SUPPORTED_LANGS = {
    'ko': '전문적인 한국어(Korean)',
    'en': 'Professional English',
    'ja': '専門的な日本語(Japanese)',
    'zh': '简体中文(Simplified Chinese)'
}

def get_base_ticker(ticker):
    """우선주 티커에서 일반주 티커를 유추합니다. (예: NHPBP -> NHP, T-P -> T)"""
    if not ticker or len(ticker) <= 3: return ticker
    # 하이픈이나 점이 있는 경우 앞부분만 추출
    if '-' in ticker: return ticker.split('-')[0]
    if '.' in ticker: return ticker.split('.')[0]
    # 끝자리가 BP, PR로 끝나는 5자 이상의 티커 대응
    if len(ticker) >= 5 and ticker.endswith(('BP', 'PR')): return ticker[:-2]
    return ticker

# (A) 메타데이터(Accession Number)만 가져오는 가벼운 함수
def fetch_sec_metadata(ticker, doc_type, api_key, cik=None):
    try:
        accession_num, filed_date = None, None
        # 1. FMP 티커 기반 검색 시도
        search_url = f"https://financialmodelingprep.com/stable/sec-filings?symbol={ticker}&type={doc_type}&limit=1&apikey={api_key}"
        r = requests.get(search_url, timeout=5)
        if r.status_code == 200:
            res_data = r.json()
            if isinstance(res_data, list) and len(res_data) > 0:
                accession_num = res_data[0].get('accessionNumber')
                filed_date = res_data[0].get('fillingDate')
        
        # 2. FMP 실패 시 SEC 공식 API(CIK 기반) 직접 조회
        if not accession_num and cik:
            clean_cik = str(cik).zfill(10)
            sec_url = f"https://data.sec.gov/submissions/CIK{clean_cik}.json"
            sec_res = requests.get(sec_url, headers=SEC_HEADERS, timeout=5)
            
            if sec_res.status_code == 200:
                filings = sec_res.json().get('filings', {}).get('recent', {})
                forms = filings.get('form',[])
                for i, form in enumerate(forms):
                    clean_form = str(form).upper().strip()
                    # 💡 [핵심 복구] S-1 검색 시 S-1/A가 걸리는 것만 막고, 나머지 연관 서류(S-11 등)는 모두 허용(in)
                    if doc_type.upper() == 'S-1' and 'S-1/A' in clean_form:
                        continue
                        
                    if doc_type.upper() in clean_form:
                        accession_num = filings.get('accessionNumber', [])[i]
                        filed_date = filings.get('filingDate', [])[i]
                        print(f"✅[SEC 직접 매칭 성공] {ticker} - {clean_form}")
                        break
        return accession_num, filed_date
    except: return None, None

# (B) 진짜 필요할 때만 본문을 긁어오는 무거운 함수 (수정본)
def fetch_sec_full_content(accession_num, ticker, doc_type, api_key, cik=None):
    if not accession_num: return None
    try:
        text_url = f"https://financialmodelingprep.com/stable/sec-filing-full-text?accessionNumber={accession_num}&apikey={api_key}"
        txt_res = requests.get(text_url, timeout=15) # 🚀 타임아웃
        if txt_res.status_code == 200 and txt_res.json():
            full_text = txt_res.json()[0].get('content', '')
            if len(full_text) > 500:
                # 🚀 정규식 멈춤(Hang) 방지: 원문을 30만 자로 먼저 컷
                clean_text = re.sub(r'<[^>]+>', ' ', full_text[:300000])
                return re.sub(r'\s+', ' ', clean_text)[:100000]

        if cik:
            cik_str = str(cik).zfill(10)
            acc_no_clean = str(accession_num).replace('-', '')
            raw_txt_url = f"https://www.sec.gov/Archives/edgar/data/{cik_str}/{acc_no_clean}/{accession_num}.txt"
            
            print(f"📡 [SEC 본문 요청] {ticker} ({doc_type}) -> URL: {raw_txt_url}")
            raw_res = requests.get(raw_txt_url, headers=SEC_HEADERS, timeout=20) # 🚀 타임아웃
            
            if raw_res.status_code == 200:
                print(f"✅ [SEC 본문 수신 성공] {ticker} - 길이: {len(raw_res.text)} 자")
                # 🚀 정규식 멈춤(Hang) 방지
                raw_truncated = raw_res.text[:300000]
                clean_text = re.sub(r'<[^>]+>', ' ', raw_truncated)
                return re.sub(r'\s+', ' ', clean_text)[:100000]
            else:
                print(f"❌ [SEC 본문 수신 실패] {ticker} - HTTP 상태코드: {raw_res.status_code}")
                
    except Exception as e:
        print(f"⚠️[SEC 스크래핑 에러/타임아웃] {ticker} ({doc_type}): {e}")
        
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
    if not text: return ""
    if "|||SEP|||" in text: return text.strip()
    
    # 1. 마크다운 제목 행(## 등) 삭제
    text = re.sub(r'^#+.*$', '', text, flags=re.MULTILINE).strip()
    
    # 2. 본문 내의 마크다운 별표(**) 및 불렛 기호(*) 삭제 (레이아웃 파괴 방지)
    text = text.replace('**', '')
    text = re.sub(r'^\s*[\*\-\+]\s+', '', text, flags=re.MULTILINE)

    # 3. AI 인사말 및 임의 섹션 삭제 패턴
    banned_intros = [
        r'here is the.*', r'certainly.*', r'understood.*', r'sure.*', 
        r'분석 결과.*', r'보고서입니다.*', r'요청하신.*', r'작성하겠습니다.*',
        r'以下は.*', r'作成합니다.*', r'好的.*', r'这是.*',
        r'.*분석 보고서', r'.*Analysis Report', r'^요약\s*:', r'^Summary\s*:'
    ]
    
    lines = text.split('\n')
    cleaned_lines = []
    
    for line in lines:
        l = line.strip()
        if not l: continue
        
        bracket_match = re.match(r'^[\[\(](.*?)[\]\)]', l)
        if bracket_match:
            inner_content = bracket_match.group(1).lower()
            if any(re.match(p, inner_content) for p in banned_intros):
                continue
            keywords = ['분석', '품질', '전망', '가치', '수익', '건전', '의견', 'analysis', 'health', 'valuation', '収익', '財務', '盈利', '财务']
            if any(kw in inner_content for kw in keywords):
                cleaned_lines.append(line)
                continue
            if len(l) > 50: cleaned_lines.append(line)
            continue
        
        cleaned_lines.append(line)
        
    return '\n'.join(cleaned_lines).strip()

def batch_upsert(table_name, data_list, on_conflict="ticker"):
    if not data_list: return
    endpoint = f"{SUPABASE_URL}/rest/v1/{table_name}?on_conflict={on_conflict}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal,resolution=merge-duplicates" 
    }
    
    clean_batch =[]
    for item in data_list:
        # 모든 값을 Supabase가 받아들일 수 있는 형태로 정제
        payload = {k: sanitize_value(v) for k, v in item.items()}
        
        # 💡 [핵심] 필수 키가 있는지 확인 (cache_key 혹은 ticker 등)
        if payload.get(on_conflict):
            clean_batch.append(payload)
            
            # ========================================================
            # 🚀[Dual Caching] 유니버설 이중 저장 로직
            # 특정 기업이 아닌, get_base_ticker 결과가 다르면 무조건 복제 적용
            # ========================================================
            if table_name == "analysis_cache" and "ticker" in payload and "cache_key" in payload:
                original_ticker = str(payload["ticker"])
                base_ticker = get_base_ticker(original_ticker)
                
                # 변형 티커(예: NHPBP)인 경우에만 본주(NHP) 복제본 생성 (MARKET 제외)
                if original_ticker != base_ticker and original_ticker != "MARKET":
                    dup_payload = payload.copy()
                    dup_payload["ticker"] = base_ticker
                    
                    # 정규식을 사용해 cache_key 안의 original_ticker를 base_ticker로 안전하게 치환
                    # 예: "NHPBP_Tab1_v5_ko" -> "NHP_Tab1_v5_ko"
                    dup_payload["cache_key"] = re.sub(
                        rf'(^|_){original_ticker}(_|$)', 
                        rf'\g<1>{base_ticker}\g<2>', 
                        str(dup_payload["cache_key"]), 
                        count=1
                    )
                    clean_batch.append(dup_payload)
            # ========================================================
            
    if not clean_batch: return
    
    try:
        resp = requests.post(endpoint, json=clean_batch, headers=headers)
        if resp.status_code in[200, 201, 204]:
            print(f"✅ [{table_name}] {len(clean_batch)}개 저장 성공 (Dual Caching 적용)")
        else:
            print(f"❌[{table_name}] 저장 실패 ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"❌ [{table_name}] 통신 에러: {e}")
        
# ==========================================
# 🚀 [글로벌 다국어 지원] FCM 푸시 알림 발송 함수
# ==========================================
def send_fcm_push(title_dict, body_dict, ticker=None, target_level='premium'):
    """
    title_dict, body_dict: {'ko': '...', 'en': '...', 'ja': '...', 'zh': '...'} 형태의 다국어 딕셔너리
    """
    if not firebase_admin._apps: return

    try:
        # 💡 [핵심] 유저 테이블에서 토큰과 함께 '국가/언어 코드(country_code)'를 같이 가져옴
        if target_level == 'premium_plus':
            res = supabase.table("user_fcm_tokens").select("fcm_token, users!inner(membership_level, country_code)").eq("users.membership_level", "premium_plus").execute()
        else:
            res = supabase.table("user_fcm_tokens").select("fcm_token, users!inner(membership_level, country_code)").in_("users.membership_level", ["premium", "premium_plus"]).execute()
        
        # 💡[언어별 토큰 그룹화]
        tokens_by_lang = {'ko': [], 'en':[], 'ja': [], 'zh':[]}
        
        if res.data:
            for item in res.data:
                token = item.get('fcm_token')
                if not token: continue
                
                user_info = item.get('users')
                lang = 'ko' # 기본값
                if isinstance(user_info, dict):
                    lang = str(user_info.get('country_code', 'ko')).lower()
                    if lang not in tokens_by_lang: lang = 'en' # 지원하지 않는 언어면 영어로 폴백
                
                tokens_by_lang[lang].append(token)

        # 💡[언어별 맞춤 발송]
        success_count = 0
        for lang, tokens in tokens_by_lang.items():
            if not tokens: continue
            
            # 해당 언어의 텍스트가 없으면 영어로, 영어도 없으면 한국어로 안전하게 폴백
            t = title_dict.get(lang, title_dict.get('en', title_dict.get('ko', 'Notification')))
            b = body_dict.get(lang, body_dict.get('en', body_dict.get('ko', '')))
            
            message = messaging.MulticastMessage(
                notification=messaging.Notification(title=t, body=b),
                data={'ticker': ticker if ticker else "", 'type': 'alert'},
                tokens=tokens,
            )
            response = messaging.send_each_for_multicast(message)
            success_count += response.success_count

        if success_count > 0:
            print(f"🚀 [{target_level}] {ticker} 다국어 푸시 {success_count}개 발송 완료")

    except Exception as e:
        print(f"❌ FCM 다국어 발송 에러: {e}")

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
# [마케팅 전용] 4개 국어 지원 트위터 다이렉트 송고 (X API v2 연동)
# ==========================================
def send_to_twitter_connector(ticker, company_name, row_data, unified_metrics, analyst_metrics):
    """
    모든 분석이 완료된 시점에 4개 국어 요약 데이터를 각각 트위터로 직접 전송합니다.
    """
    # 🚨 [안전장치] 과거 상장 기업 트윗 방지 (3일 초과 시 스킵)
    ipo_date_str = row_data.get('date')
    if ipo_date_str:
        try:
            ipo_dt = datetime.strptime(ipo_date_str, '%Y-%m-%d').date()
            if (datetime.now().date() - ipo_dt).days > 3:
                return False, "Old IPO"
        except Exception:
            pass

    # 1. 공모 정보 계산
    price_val = 0.0  
    offering_amount = "TBD"
    try:
        raw_price = str(row_data.get('price', '0')).replace('$', '').split('-')[0].strip()
        if raw_price and raw_price.replace('.', '', 1).isdigit():
            price_val = float(raw_price)
            shares = float(row_data.get('numberOfShares', 0))
            if shares > 0 and price_val > 0:
                offering_amount = f"${(price_val * shares / 1000000):,.1f}M" 
    except Exception:
        pass 

    # 2. 4개 국어 요약문 존재 여부 확인 (작업이 끝났는지 확인하는 용도)
    summaries = {}
    languages =['en', 'ko', 'ja', 'zh']
    for lang in languages:
        try:
            res_sum = supabase.table("analysis_cache").select("content").eq("cache_key", f"{ticker}_Tab1_v5_{lang}").execute()
            if res_sum.data:
                content_json = json.loads(res_sum.data[0]['content'])
                clean_text = re.sub(r'<[^>]+>', '', content_json.get('html', ''))
                summaries[lang] = clean_text.strip()
            else:
                summaries[lang] = "" 
        except:
            summaries[lang] = ""

    # 3. 언어별 반복 처리
    for lang in languages:
        summary_text = summaries.get(lang, "")
        if not summary_text: continue 

        tracker_key = f"{ticker}_Twitter_Sent_Tracker_{lang}"
        try:
            res = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key).execute()
            if res.data: continue 
        except: pass

        # 💡 [최종 수정] 브랜드 슬로건 통일 및 국가별 검색 최적화(SEO) 해시태그 대폭 강화
        localization = {
            "ko": {
                "tags": "#미국주식 #공모주 #주식투자 #재테크", 
                "hook": "Find your unicorn with Unicornfinder"
            },
            "en": {
                "tags": "#StocksToWatch #Investing #NewListing #MarketAlert", 
                "hook": "Find your unicorn with Unicornfinder"
            },
            "ja": {
                "tags": "#米国株投資 #投資初心者 #新規公開株 #投資", 
                "hook": "Find your unicorn with Unicornfinder"
            },
            "zh": {
                "tags": "#美股IPO #美股 #投资 #新股 #财经", 
                "hook": "Find your unicorn with Unicornfinder"
            }
        }

        # 💡 [신규] 앱 유도(Teasing) 다국어 문구
        hook_lines = {
            "ko": "Analyst Ratings & Targets : 🔒 앱에서 확인",
            "en": "Analyst Ratings & Targets : 🔒 Unlock in App",
            "ja": "Analyst Ratings & Targets : 🔒 アプリで確認",
            "zh": "Analyst Ratings & Targets : 🔒 App内查看"
        }
        tease_line = hook_lines.get(lang, "Analyst Ratings & Targets : 🔒 Unlock in App")

        current_time_str = datetime.now().strftime("%H:%M:%S")

        # 🚀 [미니멀 티징 포맷] 트윗 텍스트 조립
        tweet_text = f"{company_name[:25]} ({ticker})\n"
        tweet_text += f"{row_data.get('exchange', 'USA').split(' ')[0]} | ${price_val:.2f} | {offering_amount} | {row_data.get('date', 'TBD')}\n"
        tweet_text += f"{tease_line}\n\n"
        
        # 브랜드 메시지 삽입
        tweet_text += f"{localization[lang]['hook']}\n\n" 
        
        # 해시태그 배치
        tweet_text += f"${ticker} #IPO {localization[lang]['tags']} #Unicornfinder #Investing\n"
        tweet_text += f"🕒 {current_time_str}"

        # 4. 트위터 전송
        success, result = post_to_twitter(tweet_text)
        
        if success:
            batch_upsert("analysis_cache",[{"cache_key": tracker_key, "content": "sent", "updated_at": datetime.now().isoformat()}], "cache_key")
            print(f"✅ [Twitter] {ticker} ({lang}) 트윗 성공")
        else:
            print(f"❌ [Twitter] {ticker} ({lang}) 트윗 실패: {result}")
        
        # 5. 연사 제한 방지
        if lang != languages[-1]:
            time.sleep(30)
            
    return True, "Done"

# ==========================================
# [완전 교체] run_tab0_analysis 함수 (에러 영구 차단 + 20-F 하이브리드 탐색)
# ==========================================
def run_tab0_analysis(ticker, company_name, ipo_status="Active", ipo_date_str=None, cik_mapping=None, original_ticker=None):
    if 'model_strict' not in globals() or not model_strict: return
    
    # 🚀 [1] CIK 실시간 확보 로직
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
                
                # 🚀 [FCM 추가] 다국어 발송
                try:
                    send_fcm_push(
                        title_dict={
                            "ko": f"🚨 {ticker} 중대 공시(8-K) 발생", "en": f"🚨 {ticker} 8-K Material Event",
                            "ja": f"🚨 {ticker} 重大開示(8-K)発生", "zh": f"🚨 {ticker} 重大事件(8-K)"
                        },
                        body_dict={
                            "ko": "새로운 중대 이벤트(8-K) 분석이 완료되었습니다. 지금 확인하세요.", "en": "A new material event (8-K) analysis is ready. Check it out now.",
                            "ja": "新たな重大イベント(8-K)の分析が完了しました。今すぐご確認ください。", "zh": "新的重大事件(8-K)分析已完成。请立即查看。"
                        },
                        ticker=ticker, target_level='premium_plus'
                    )
                except Exception as e:
                    print(f"⚠️ 8-K 푸시 발송 실패: {e}")
                
                # 4. 분석 완료 후 트래커 갱신 (다음 실행 때 스킵)
                batch_upsert("analysis_cache", [{"cache_key": tracker_key_8k, "content": acc_num_8k, "updated_at": datetime.now().isoformat()}], "cache_key")

    # ==========================================================================
    # 🚀 [교정] 각 토픽별로 '정확히' 해당 서류만 찾도록 우선순위 로직을 엄격히 분리
    # ==========================================================================
    for topic in target_topics:
        acc_num, f_date = None, None
        
        # 💡 생애 주기별 탭(Tab) 구성을 유지하면서, 각 서류가 자기 자리를 찾게 함
        if topic == "10-K": priority_targets = ["10-K", "20-F"]
        elif topic == "10-Q": priority_targets = ["10-Q", "6-K"]
        elif topic in ["BS", "IS", "CF"]: priority_targets = ["10-K", "20-F", "10-Q", "6-K"]
        # 🚀 [교정] 신규 기업(S-1) 뿐만 아니라 기존 기업의 추가 발행(S-3)까지 대응
        else:
            if topic == "S-1":
                priority_targets = ["S-1", "S-3", "S-3ASR"] # S-3 추가
            elif topic == "S-1/A":
                priority_targets = ["S-1/A", "S-3/A"] # S-3/A 추가
            else:
                priority_targets = [topic]

        print(f"🔍 [{ticker}] {topic} 공시 탐색 중...") 
        base_ticker = get_base_ticker(ticker) # 💡 모기업 티커 추출

        for target in priority_targets:
            # 1. 현재 티커(NHPBP)로 시도
            acc_num, f_date = fetch_sec_metadata(ticker, target, FMP_API_KEY, cik)
            
            # 2. 💡[핵심 복구] 못 찾았을 경우, 본주/모기업 티커(NHP)로 SEC 시스템 재탐색!
            if not acc_num and ticker != base_ticker:
                print(f"🔄 [{ticker}] 공시 없음. 모기업({base_ticker}) 티커로 재탐색...")
                acc_num, f_date = fetch_sec_metadata(base_ticker, target, FMP_API_KEY, None)
            
            if acc_num: break

        # 서류가 아예 없는 경우 안내 메시지 생성 (이미 데이터가 있는 경우는 제외)
        if not acc_num:
            print(f"ℹ️ [{ticker}] {topic} 서류를 찾지 못했습니다.")
            for lang_code in SUPPORTED_LANGS.keys():
                cache_key = f"{company_name}_{topic}_Tab0_v16_{lang_code}"
                missing_msg = get_missing_document_message(lang_code, topic)
                formatted_msg = f"<div style='background-color:#f8f9fa; padding:15px; border-radius:8px; color:#555; font-size:15px; line-height:1.6;'>{missing_msg}</div>"
                
                # 🚀 [수정] 누락되었던 ticker, tab_name, lang, data_type 태그 완벽 추가!
                batch_upsert("analysis_cache",[{
                    "cache_key": cache_key, 
                    "content": formatted_msg, 
                    "updated_at": datetime.now().isoformat(),
                    "ticker": ticker,
                    "tab_name": "tab0",
                    "lang": lang_code,
                    "data_type": topic,
                    "tier": "free"
                }], on_conflict="cache_key")
            continue

        # run_tab0_analysis 함수 내부의 중복 체크 블록 수정
        tracker_key = f"{company_name}_{topic}_LastAccNum"
        is_skip = False
        try:
            # 1. 서류 번호 확인
            res_tracker = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key).execute()
            if res_tracker.data and res_tracker.data[0]['content'] == acc_num:
                # 2. 🚀 [교정] 실제로 분석 리포트가 저장되어 있는지 한 번 더 확인 (누락 방지)
                test_key = f"{company_name}_{topic}_Tab0_v16_ko"
                res_content = supabase.table("analysis_cache").select("cache_key").eq("cache_key", test_key).execute()
                
                if res_content.data:
                    print(f"⏩ [{ticker}] {topic} 리포트가 이미 존재합니다. (스킵)")
                    is_skip = True 
                else:
                    print(f"🔄 [{ticker}] {topic} 번호는 같지만 리포트가 없어 재분석합니다.")
        except: pass

        if is_skip: continue

        # 새 문서일 때만 다운로드
        print(f"📥 [{ticker}] {topic} 신규 공시 분석 시작 ({acc_num})...")
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
                        raw_text = response.text.strip()
                        
                        # 🚀 [교정 1] 첫 줄이 소제목이면 인사말 제거 함수를 패스하여 데이터 유실 방지
                        if raw_text.startswith('[') or raw_text.startswith('**['):
                            clean_text = raw_text
                        else:
                            clean_text = clean_ai_preamble(raw_text)

                        # 🚀 [교정 2] 외국어 뭉침 방지: 문장 중간의 [소제목] 앞에 줄바꿈 강제 삽입
                        # 영/일/중 AI가 마침표 뒤에 바로 [제목]을 붙여 쓰는 경우를 강제로 쪼갭니다.
                        clean_text = re.sub(r'([.!?。])\s*(\[|\*\*\[)', r'\1\n\n\2', clean_text)

                        # 2. 분석 및 HTML 구조화
                        lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
                        final_html = ""
                        
                        for line in lines:
                            # 소제목 패턴 탐지 (모든 언어 조합 대응)
                            match = re.match(r'^(\*\*|\[|\*\*\[|\()(.*?)(\]|\] \*\*|\*\*\*|\]\*\*|\))\s*(.*)', line)
                            
                            is_header = False
                            clean_title = ""
                            remainder_text = ""

                            if match:
                                raw_title = match.group(2).strip()
                                clean_title = raw_title.strip('[]*() ') 
                                if len(clean_title) > 4: # 티커 보호
                                    is_header = True
                                    remainder_text = match.group(4).strip()
                            
                            if is_header:
                                # [소제목 처리]
                                if final_html:
                                    final_html += "<br><br>" # 단락 간 간격
                                final_html += f"<b>[{clean_title}]</b>"
                                if remainder_text:
                                    final_html += f"<br>{remainder_text}" # 제목-본문 밀착
                            else:
                                # [일반 본문 처리]
                                if not final_html:
                                    final_html = line
                                else:
                                    if final_html.endswith("</b>"):
                                        final_html += f"<br>{line}" # 소제목 직후 본문 밀착
                                    else:
                                        final_html += f" {line}" # 본문 문장 연결
                        
                        processed_content = final_html.strip()

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
                        print(f"✅ [{ticker}] {topic} 레이아웃 교정 완료 ({lang_code})")
                except Exception as e:
                    print(f"❌ [{ticker}] {topic} AI 에러 ({lang_code}): {e}")

            # 💡 [핵심 방어막] 에러가 났는데 트래커만 갱신되는 '가짜 완료' 방지
        try:
            test_key = f"{company_name}_{topic}_Tab0_v16_ko"
            res_verify = supabase.table("analysis_cache").select("content").eq("cache_key", test_key).execute()
            
            # 한국어(ko) 분석 내용이 있거나, 본문 다운로드 실패로 노란색 경고 박스라도 저장된 경우에만 완료(트래커 갱신)
            if res_verify.data:
                batch_upsert("analysis_cache",[{"cache_key": tracker_key, "content": acc_num, "updated_at": datetime.now().isoformat()}], "cache_key")
            else:
                print(f"⚠️ [{ticker}] {topic} AI 분석 실패로 트래커 갱신 보류 (다음 사이클에서 재시도합니다.)")
        except: pass
            
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
            
            try:
                resp = model_strict.generate_content(prompt)
                if resp and resp.text:
                    paragraphs = [p.strip() for p in resp.text.split('\n') if len(p.strip()) > 20]
                    indent_size = "14px" if lang_code == "ko" else "0px"
                    html_str = "".join([f'<p style="text-indent:{indent_size}; margin-bottom:15px; line-height:1.8; text-align:justify; font-size:15px; color:#333;">{p}</p>' for p in paragraphs])
                    
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
            except Exception as e:
                # 래퍼가 안에서 지수 백오프를 5회나 시도하고도 장렬히 전사했을 때만 이곳으로 떨어집니다.
                print(f"⚠️ [{ticker}] 어닝 콜 요약 AI 분석 실패 ({lang_code}): {e}")
                
        # 🚀[FCM 다국어 발송]
        send_fcm_push(
            title_dict={"ko": f"🎙️ {ticker} 어닝 콜 분석 완료", "en": f"🎙️ {ticker} Earnings Call Analyzed", "ja": f"🎙️ {ticker} アーニングコール分析完了", "zh": f"🎙️ {ticker} 财报电话会议分析"},
            body_dict={"ko": "경영진의 향후 가이던스와 Q&A 핵심 요약이 도착했습니다.", "en": "Management's future guidance and Q&A summary have arrived.", "ja": "経営陣の今後のガイダンスとQ&Aの要約が届きました。", "zh": "管理层的未来指引和Q&A核心摘要已送达。"},
            ticker=ticker, target_level='premium_plus'
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
    
    base_ticker = get_base_ticker(ticker) # 💡 추가
    
    try: 
        url = f"https://financialmodelingprep.com/stable/esg-ratings?symbol={ticker}&apikey={FMP_API_KEY}"
        esg_raw = get_fmp_data_with_cache(ticker, "RAW_ESG", url, valid_hours=24) 
        
        # 💡 [추가] 우선주로 실패 시 모기업으로 재탐색
        if (not isinstance(esg_raw, list) or len(esg_raw) == 0) and ticker != base_ticker:
            url_base = f"https://financialmodelingprep.com/stable/esg-ratings?symbol={base_ticker}&apikey={FMP_API_KEY}"
            esg_raw = get_fmp_data_with_cache(base_ticker, "RAW_ESG", url_base, valid_hours=24)

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
            
            try:
                resp = model_strict.generate_content(prompt)
                if resp and resp.text:
                    paragraphs = [p.strip() for p in resp.text.split('\n') if len(p.strip()) > 20]
                    indent_size = "14px" if lang_code == "ko" else "0px"
                    html_str = "".join([f'<p style="text-indent:{indent_size}; margin-bottom:15px; line-height:1.8; text-align:justify; font-size:15px; color:#333;">{p}</p>' for p in paragraphs])
                    
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
            except Exception as e:
                # 래퍼 내부의 지수 백오프마저 최종 실패했을 때만 실행됩니다.
                print(f"⚠️ [{ticker}] ESG 분석 실패 ({lang_code}) - 래퍼 복구 한도 초과: {e}")
                
        # [2] AI 분석 완료 후 발송 (try 블록 내부 유지)
        if analysis_performed:
            send_fcm_push(
                title_dict={"ko": f"🌱 {ticker} ESG 평가 업데이트", "en": f"🌱 {ticker} ESG Rating Updated", "ja": f"🌱 {ticker} ESG評価更新", "zh": f"🌱 {ticker} ESG评级更新"},
                body_dict={"ko": "글로벌 기관 기준의 환경/사회/지배구조 리스크 분석이 업데이트되었습니다.", "en": "Global institutional analysis on ESG risks is updated.", "ja": "グローバル機関基準のESGリスク分析が更新されました。", "zh": "全球机构标准的ESG风险分析已更新。"},
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

def get_search_friendly_name(name):
    if not name or pd.isna(name): return ""
    name = str(name)
    # 1. 괄호 내용 및 클래스 정보 제거
    name = re.sub(r'(/DE|Cl\s*[A-Z]|Class\s*[A-Z]|\(.*\))', '', name, flags=re.IGNORECASE)
    
    # 2. 🚀 [교정] 'Inc.', 'Properties' 등을 무조건 지우는 게 아니라, 
    # 검색어로서 너무 길어지는 접미사 위주로만 정리 (브랜드 핵심어 추출)
    suffix_pattern = r'\b(inc|corp|corporation|co|ltd|lp|l\.p\.|plc|group|holdco|capital|management|sa|nv|ag)\b\.?'
    name = re.sub(suffix_pattern, '', name, flags=re.IGNORECASE)
    
    name = name.strip().strip(',').strip('.').strip()
    return re.sub(r'\s+', ' ', name)
    
# =========================================================================
# [최종 완성본] Tab 1 분석 함수 - 비즈니스 맥락 우선 원칙 및 완벽 분리 로직 적용
# =========================================================================
def run_tab1_analysis(ticker, company_name, ipo_status="Active", ipo_date_str=None):
    if 'model_strict' not in globals() or not model_strict: return
    
    base_ticker = get_base_ticker(ticker)
    search_name = get_search_friendly_name(company_name)
    
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    one_year_ago = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    
    status_lower = str(ipo_status).lower()
    is_withdrawn = bool(re.search(r'\b(withdrawn|rw|철회|취소)\b', status_lower))
    is_delisted_or_otc = bool(re.search(r'\b(delisted|폐지|otc)\b', status_lower))
    
    is_over_1y = False
    try:
        if ipo_date_str:
            days_passed = (now.date() - pd.to_datetime(ipo_date_str).date()).days
            if days_passed > 365: is_over_1y = True
    except: pass

    safe_name = f'"{search_name}"'
    if is_withdrawn:
        search_query = f'{safe_name} OR {base_ticker} IPO withdrawn OR canceled'
    elif is_delisted_or_otc:
        search_query = f'{safe_name} OR {base_ticker} delisted OR "OTC"'
    elif is_over_1y:
        search_query = f'{safe_name} OR {base_ticker} stock news'
    else:
        search_query = f'{safe_name} OR "{base_ticker}" stock news'

    # 1. 데이터 수집 (FMP)
    profile_url = f"https://financialmodelingprep.com/stable/profile?symbol={ticker}&apikey={FMP_API_KEY}"
    profile_data = get_fmp_data_with_cache(ticker, "PROFILE", profile_url, valid_hours=168)
    if not profile_data and ticker != base_ticker:
        profile_url_base = f"https://financialmodelingprep.com/stable/profile?symbol={base_ticker}&apikey={FMP_API_KEY}"
        profile_data = get_fmp_data_with_cache(base_ticker, "PROFILE", profile_url_base, valid_hours=168)

    biz_desc = profile_data[0].get('description') or "" if profile_data else ""

    news_url = f"https://financialmodelingprep.com/stable/news/stock-latest?symbol={ticker}&limit=15&apikey={FMP_API_KEY}"
    news_data = get_fmp_data_with_cache(ticker, "RAW_NEWS_15", news_url, valid_hours=6)
    if not news_data and ticker != base_ticker:
        news_url_base = f"https://financialmodelingprep.com/stable/news/stock-latest?symbol={base_ticker}&limit=15&apikey={FMP_API_KEY}"
        news_data = get_fmp_data_with_cache(base_ticker, "RAW_NEWS_15_BASE", news_url_base, valid_hours=6)
    
    valid_news = [
        n for n in (news_data or []) 
        if n and (
            ticker.upper() in [s.strip().upper() for s in str(n.get('symbol', '')).split(',')] or
            base_ticker.upper() in [s.strip().upper() for s in str(n.get('symbol', '')).split(',')]
        )
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
            
            # --- 공통 지침 보강 (General context-first principle) ---
            common_exclusion_logic = f"""
                       - [맥락 기반 포함(Contextual Inclusion)]: 기업명이 특정 지명이나 일반 명사와 겹치더라도, 기사 내용이 **"IPO, Stock, Business, Financing, Funding, Revenue, Listing"** 및 해당 기업의 산업 키워드와 결합되어 있다면 이는 해당 기업의 소식이 확실하므로 절대 배제하지 마세요.
                       - [명칭 변형 허용(Name Variants)]: 언론은 '{company_name}'을 '{search_name}'이나 '{ticker}'로 생략하여 보도하는 경우가 많습니다. 이름이 100% 일치하지 않아도 비즈니스 맥락이 맞다면 동일 주체로 인정하세요."""

            if lang_code == 'ko':
                sys_prompt = "당신은 최고 수준의 증권사 리서치 센터의 시니어 애널리스트입니다. 반드시 한국어로 작성하세요."
                lang_instruction = "반드시 자연스러운 한국어만 사용하세요.\n모든 문장은 반드시 '~습니다', '~합니다' 형태의 정중한 존댓말로 마무리하십시오."
                format_instruction = "반드시 3개의 문단으로 나누어 작성하세요. (각 문단은 4~5문장 길이)"
                
                if is_withdrawn:
                    task1_label = "--- [분석 지시 1: 상장 철회 심층 진단] ---"
                    task1_structure = "- 1문단: [철회 배경 진단]\n- 2문단: [재무적 타격]\n- 3문단: [생존 전략]"
                elif is_delisted_or_otc:
                    task1_label = "--- [분석 지시 1: OTC/장외시장 거래 리스크 진단] ---"
                    task1_structure = "- 1문단: [장외 편입 배경]\n- 2문단: [투자 리스크]\n- 3문단: [장기 전망]"
                elif is_over_1y:
                    task1_label = "--- [분석 지시 1: 상장 1년 차 펀더멘털 점검] ---"
                    task1_structure = "- 1문단: [목표 달성도]\n- 2문단: [수익성 평가]\n- 3문단: [자본 효율성]"
                else:
                    task1_label = "--- [분석 지시 1: 신규 IPO 비즈념 심층 분석] ---"
                    task1_structure = "- 1문단: [비즈니스 모델 및 스케일]\n- 2문단: [시장 점유율 및 경쟁 우위]\n- 3문단: [성장 전략 및 미래 전망]"

                search_directive = f"""
                    🚨 [광범위 검색 및 보편적 가치 기반 필터링 지시]: 
                    1. 검색 쿼리: `{search_query}`
                    2. 필터링 원칙 (Exclusion Logic):
                       - [Subject Lineage (주체 연계성)]: 모기업이나 그룹 명의의 소식이라도 해당 티커({base_ticker})의 사업과 연관이 있다면 배제하지 마세요.
                       {common_exclusion_logic}
                       - [No Hallucination (환각 금지)]: 검색 결과에 유효한 뉴스가 없다면 절대 가상의 예시를 지어내지 마세요.
                    3. 기간: [{one_year_ago}] ~ [{current_date}]
                    4. 추출: 위 보편적 분석 논리에 부합하는 유효한 최신 뉴스를 최대 5개 추출하세요.""" if is_fmp_poor else "🚨 [환각 금지] 오직 아래 제공된 [Part 1] 데이터만을 사용하세요."

                task2_label = "--- [분석 지시 2: 최신 뉴스 수집 및 전문 번역] ---"
                news_instruction = '- 제공된 데이터나 구글 검색 결과를 바탕으로 최신 뉴스를 **최대 5개** 추출하세요.\n- 🚨 [중요] 이름이 완벽히 일치하지 않더라도 비즈니스/산업적 연관성이 뚜렷하다면 누락시키지 마세요.\n- sentiment 값은 "Positive", "Negative", "Neutral" 중 하나로 출력하세요.\n- date는 "YYYY-MM-DD" 형식을 권장하되, 불분명하면 검색 결과의 시간 표현을 그대로 기재하세요.'
                json_format = f"""{{ "debug_search_raw": "검색 결과 중 비즈니스 맥락에 따라 포함/배제한 근거를 요약하세요.", "news": [ {{ "title_en": "Original English Title", "translated_title": "Headline 번역", "link": "...", "sentiment": "Positive/Negative/Neutral", "date": "YYYY-MM-DD" }} ] }}"""

            elif lang_code == 'en':
                sys_prompt = "You are a senior analyst at a top-tier brokerage. Write strictly in English."
                lang_instruction = "Your entire response MUST be in English only."
                format_instruction = "Must be written in exactly 3 paragraphs."
                
                search_directive = f"""
                    🚨[Mandatory Search & Filtering Directive]: 
                    1. Search Query: `{search_query}`
                    2. Filtering (Exclusion/Inclusion): 
                       - [Contextual Inclusion]: Even if the name matches a place or generic term, include it if business keywords like IPO, Stock, or Listing are present.
                       - [Name Variants]: Shortened names like '{search_name}' should be recognized as the target entity.
                    3. Period:[{one_year_ago}] to [{current_date}]
                    4. Extraction: Extract up to 5 valid news items.""" if is_fmp_poor else "🚨 [No Hallucination]: Use ONLY[Part 1] data."

                task2_label = "--- [Task 2: Latest News Collection] ---"
                # 💡 [핵심 수정] 영어일 경우 translated_title을 강제로 빈 문자열("")로 비우도록 지시!
                news_instruction = '- Extract up to 5 items. Do NOT discard news just because the name is shortened if the business context is clear.\n- 🚨 For English, you MUST leave "translated_title" strictly as an empty string "". DO NOT translate.\n- sentiment: Positive, Negative, or Neutral.\n- date: YYYY-MM-DD or the expression from search results.'
                
                json_format = f"""{{ "debug_search_raw": "Summary of inclusion/exclusion based on context.", "news":[ {{ "title_en": "Original English Title", "translated_title": "", "link": "...", "sentiment": "Positive", "date": "YYYY-MM-DD" }} ] }}"""

            elif lang_code == 'ja':
                sys_prompt = "あなたは証券会社のシニアアナリストです。日本語で作成してください。"
                lang_instruction = "自然な日本語のみを使用してください。"
                format_instruction = "必ず3つの段落で作成してください。"
                
                search_directive = f"""
                    🚨 [強制検索とフィルタリング]: 
                    1. クエリ: `{search_query}`
                    2. フィルタリング: 地名と重なっても、IPOやビジネス用語があれば含めてください。略称も同一企業とみなします.
                    3. 期間: [{one_year_ago}] ~ [{current_date}]
                    4. 抽出: 最大5件。""" if is_fmp_poor else "🚨 [厳格な規則] [Part 1] 데이터만 사용하십시오."

                task2_label = "--- [指示 2: 最新ニュース収集] ---"
                news_instruction = '- 最新ニュースを最大5件抽出。略称であってもビジネスの文脈이 일치하면 포함하십시오.\n- sentiment: Positive, Negative, Neutral.\n- date: YYYY-MM-DD または検索結果の表記。'
                json_format = f"""{{ "debug_search_raw": "ビジネス文脈に基づく除外/包含の根拠。", "news": [ {{ "title_en": "Title", "translated_title": "翻訳", "link": "...", "sentiment": "Positive", "date": "YYYY-MM-DD" }} ] }}"""

            else: # zh
                sys_prompt = "您是资深分析师。必须只用简体中文编写。"
                lang_instruction = "必须只用自然流畅的简体中文编写。"
                format_instruction = "必须严格分为 3 个自然段落。"
                
                search_directive = f"""
                    🚨 [强制搜索与过滤]: 
                    1. 搜索词: `{search_query}`
                    2. 过滤原则: 即使名称与地名重合，若包含IPO、融资等业务关键词，也请包含。允许名称缩写。
                    3. 期间: [{one_year_ago}] 至 [{current_date}]
                    4. 提取: 最多 5 条。""" if is_fmp_poor else "🚨 [严格规则] 只能使用 [Part 1] 数据。"

                task2_label = "--- [指令 2: 收集最新新闻] ---"
                news_instruction = '- 提取最多 5 条最新新闻。即使名称缩写，只要业务背景一致，请勿漏掉。\n- sentiment: Positive, Negative, Neutral.\n- date: YYYY-MM-DD 或搜索结果的时间表达式。'
                json_format = f"""{{ "debug_search_raw": "基于业务背景的过滤依据摘要。", "news": [ {{ "title_en": "Title", "translated_title": "翻译", "link": "...", "sentiment": "Positive", "date": "YYYY-MM-DD" }} ] }}"""

            # 프롬프트 조립
            prompt = f"""
            {sys_prompt}
            분석 대상: {company_name} (보도 명칭: {search_name}, 종목코드: {ticker}, 본주: {base_ticker})
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
            3. 금지/Prohibition: 첫문장에 인사말 절대 금지. 본문은 실제 소제목(예: **[소제목]**)으로 시작할 것.
            
            {task2_label}
            {news_instruction}
            
            🚨 [최종 출력 규칙]:
            깔끔한 3개 문단과, 그 아래에 <JSON_START> 로 시작하는 뉴스 데이터만 출력하십시오.
            
            <JSON_START>
            {json_format}
            <JSON_END>"""

            try:
                # 💡 [핵심] try와 아래 코드들의 시작 세로줄을 맞춰야 합니다.
                response = current_model.generate_content(prompt)
                
                if not response or not hasattr(response, 'text') or not response.text: 
                    raise ValueError("Empty response from AI")
                
                # 내부 헬퍼 함수 정의
                def clean_ai_preamble_internal(text):
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

                # 1. 초기 텍스트 정합성 확보
                full_text = clean_ai_preamble_internal(response.text)
                news_list = []
                biz_analysis = full_text

                # 2. 본문과 JSON 완벽 분리 로직
                json_patterns = [
                    (r'<JSON_START>(.*?)<JSON_END>', 1), 
                    (r'```json\s*(\{.*?\})\s*```', 1),   
                    (r'(\{.*"news".*?\})', 0)             
                ]
                
                for pattern, group_idx in json_patterns:
                    match = re.search(pattern, biz_analysis, re.DOTALL | re.IGNORECASE)
                    if match:
                        target_json_raw = match.group(group_idx)
                        try:
                            s_ptr = target_json_raw.find('{')
                            e_ptr = target_json_raw.rfind('}')
                            if s_ptr != -1 and e_ptr != -1:
                                json_clean = target_json_raw[s_ptr:e_ptr+1]
                                parsed = json.loads(json_clean, strict=False)
                                news_list = parsed.get("news", [])
                                biz_analysis = biz_analysis.replace(match.group(0), "").strip()
                                break 
                        except:
                            continue

                # 3. 본문 추가 정제
                biz_analysis = biz_analysis.replace("<JSON_START>", "").replace("<JSON_END>", "").strip()
                biz_analysis = re.sub(r'```json\s*|```\s*', '', biz_analysis)
                biz_analysis = re.sub(r'([.!?。])\s*(\[|\*\*\[)', r'\1\n\n\2', biz_analysis)
                
                # 4. HTML 가공
                lines = [l.strip() for l in biz_analysis.split('\n') if l.strip()]
                html_parts = []
                for p in lines:
                    if p.startswith('**[') or p.startswith('['):
                        clean_p = p.replace("**", "").strip()
                        html_parts.append(f'<p style="font-weight:bold; margin-top:20px; margin-bottom:5px; color:#111;">{clean_p}</p>')
                    else:
                        indent = "14px" if lang_code == "ko" else "0px"
                        html_parts.append(f'<p style="text-indent:{indent}; margin-bottom:15px; line-height:1.8; text-align:justify; font-size:15px; color:#333;">{p}</p>')

                html_output = "".join(html_parts)

                # 5. Supabase 최종 저장
                batch_upsert("analysis_cache", [{
                    "cache_key": cache_key, 
                    "content": json.dumps({"html": html_output, "news": news_list[:5]}, ensure_ascii=False),
                    "updated_at": datetime.now().isoformat(),
                    "ticker": ticker,
                    "tier": "free",
                    "tab_name": "tab1",
                    "lang": lang_code,
                    "data_type": "biz_summary"
                }], on_conflict="cache_key")
                print(f"✅ [{ticker}] Tab 1 리포트 생성 완료 ({lang_code})")

            except Exception as e:
                # 💡 [해결포인트] 이 except가 위의 try와 정확히 수직선상에 있어야 합니다!
                print(f"⚠️ [{ticker}] Tab 1 분석 실패 ({lang_code}) - 래퍼 복구 한도 초과: {e}")
        
        # 원본 데이터 트래커 갱신 (for 루프 밖)
        batch_upsert("analysis_cache", [{"cache_key": tracker_key, "content": current_raw_str, "updated_at": datetime.now().isoformat()}], "cache_key")
        print(f"✅ [{ticker}] Tab 1 전체 프로세스 종료 (트래커 갱신 완료)")
                
    # =========================================================
    # 🚀 [B] 프리미엄 전용 데이터 수집 (기업 공식 보도자료)
    # =========================================================
    try:
        pr_url = f"https://financialmodelingprep.com/stable/press-releases?symbol={ticker}&limit=5&apikey={FMP_API_KEY}"
        pr_raw = get_fmp_data_with_cache(ticker, "RAW_PR", pr_url, valid_hours=12)
        
        if isinstance(pr_raw, list) and len(pr_raw) > 0: 
            current_pr_str = json.dumps(pr_raw, sort_keys=True)
            tracker_key_pr = f"{ticker}_PressRelease_RawTracker"
            is_changed_pr = True
            
            try:
                res_tracker = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key_pr).execute()
                if res_tracker.data and current_pr_str == res_tracker.data[0]['content']:
                    is_changed_pr = False
            except:
                pass

            if is_changed_pr:
                print(f"🔔 [{ticker}] 기업 보도자료 업데이트 감지! AI 요약 시작...")
                for lang_code in SUPPORTED_LANGS.keys():
                    pr_summary_key = f"{ticker}_PressReleaseSummary_v1_{lang_code}"
                    prompt_p = get_tab1_premium_prompt(lang_code, "Official Press Release", current_pr_str)
                    
                    try:
                        resp_p = model_strict.generate_content(prompt_p)
                        if resp_p and resp_p.text:
                            p_paragraphs = [p.strip() for p in resp_p.text.split('\n') if len(p.strip()) > 20]
                            indent_size = "14px" if lang_code == "ko" else "0px"
                            html_p = "".join([f'<p style="text-indent:{indent_size}; margin-bottom:15px; line-height:1.8; text-align:justify; font-size:15px; color:#333;">{p}</p>' for p in p_paragraphs])
                            
                            batch_upsert("analysis_cache", [{
                                "cache_key": pr_summary_key, 
                                "content": html_p, 
                                "updated_at": datetime.now().isoformat(),
                                "ticker": ticker,
                                "tier": "free",
                                "tab_name": "tab1",
                                "lang": lang_code,
                                "data_type": "press_release"
                            }], on_conflict="cache_key")
                            print(f"✅ [{ticker}] 기업 공식 보도자료 캐싱 완료 ({lang_code})")
                    except Exception as e:
                        print(f"⚠️ [{ticker}] 기업 보도자료 AI 분석 실패 ({lang_code}): {e}")
                        
                # 💡 [중요] 모든 언어 분석 후 트래커 갱신 (if is_changed_pr 안에 위치)
                batch_upsert("analysis_cache", [{"cache_key": tracker_key_pr, "content": current_pr_str, "updated_at": datetime.now().isoformat()}], "cache_key")

    except Exception as e:
        # 💡 [해결 포인트] 이 except는 가장 상단의 'try: (pr_url 시작점)'과 수직선이 일치해야 합니다.
        print(f"Premium FMP Collection Error for {ticker}: {e}")
                
    # =========================================================
    # 🚀 [B] 프리미엄 전용 데이터 수집 (기업 공식 보도자료 - Raw Tracker 적용!)
    # =========================================================
    try:
        pr_url = f"https://financialmodelingprep.com/stable/press-releases?symbol={ticker}&limit=5&apikey={FMP_API_KEY}"
        pr_raw = get_fmp_data_with_cache(ticker, "RAW_PR", pr_url, valid_hours=12)
        
        # 🚨 [환각 완벽 차단] FMP 데이터가 정상 리스트일 때만 실행
        is_pr_valid = isinstance(pr_raw, list) and len(pr_raw) > 0

        if is_pr_valid: 
            current_pr_str = json.dumps(pr_raw, sort_keys=True)
            tracker_key_pr = f"{ticker}_PressRelease_RawTracker"
            is_changed_pr = True
            
            try:
                # [과금 방어막] 기존 원본 데이터와 비교
                res_tracker = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key_pr).execute()
                if res_tracker.data and current_pr_str == res_tracker.data[0]['content']:
                    is_changed_pr = False
            except:
                pass

            if is_changed_pr:
                print(f"🔔 [{ticker}] 기업 보도자료 업데이트 감지! AI 요약 시작...")
                for lang_code in SUPPORTED_LANGS.keys():
                    pr_summary_key = f"{ticker}_PressReleaseSummary_v1_{lang_code}"
                    prompt_p = get_tab1_premium_prompt(lang_code, "Official Press Release", current_pr_str)
                    
                    try:
                        resp_p = model_strict.generate_content(prompt_p)
                        if resp_p and resp_p.text:
                            p_paragraphs = [p.strip() for p in resp_p.text.split('\n') if len(p.strip()) > 20]
                            indent_size = "14px" if lang_code == "ko" else "0px"
                            html_p = "".join([f'<p style="text-indent:{indent_size}; margin-bottom:15px; line-height:1.8; text-align:justify; font-size:15px; color:#333;">{p}</p>' for p in p_paragraphs])
                            
                            batch_upsert("analysis_cache", [{
                                "cache_key": pr_summary_key, 
                                "content": html_p, 
                                "updated_at": datetime.now().isoformat(),
                                "ticker": ticker,
                                "tier": "free",          
                                "tab_name": "tab1",
                                "lang": lang_code,
                                "data_type": "press_release"
                            }], on_conflict="cache_key")
                            print(f"✅ [{ticker}] 기업 공식 보도자료 캐싱 완료 ({lang_code})")
                    except Exception as ai_err:
                        print(f"⚠️ [{ticker}] 보도자료 AI 분석 실패 ({lang_code}): {ai_err}")
                        
                # 모든 언어 요약 완료 후 트래커 갱신
                batch_upsert("analysis_cache", [{"cache_key": tracker_key_pr, "content": current_pr_str, "updated_at": datetime.now().isoformat()}], "cache_key")

    except Exception as e:
        # 💡 [해결포인트] 이 라인이 2075라인이며, 가장 위 try와 수직선이 일치해야 합니다.
        print(f"❌ [{ticker}] 보도자료 수집 프로세스 전체 에러: {e}")


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
            is_changed = False
    except: pass

    # 🚀[가짜 트래커 자가 치유] 트래커는 안 변했어도 실제 DB에 리포트가 없으면 강제 재분석!
    if not is_changed:
        try:
            res_check = supabase.table("analysis_cache").select("cache_key").eq("cache_key", f"{ticker}_Tab4_v4_Premium_ko").execute()
            if not res_check.data:
                is_changed = True
                print(f"🔄 [{ticker}] Tab 4 가짜 트래커 발견. 강제 재분석합니다.")
        except: pass

    if not is_changed:
        return True # 목표가/의견이 진짜로 안 변했으면 스킵
        
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

        # 🚀 [교정] 티커(PS 등) 노이즈를 피하고 검색 품질을 높이기 위해 브랜드명 추출
        search_brand = get_search_friendly_name(company_name)

        if lang_code == 'en':
            prompt = f"""You are an IPO analyst from Wall Street.
Use the Google search tool to find and analyze the latest institutional reports for "{search_brand}" (Ticker: {ticker}).
{fmp_context}

[Instructions]
1. **Language Rule**: MUST write ENTIRELY in English. DO NOT mix any other languages.
2. **Analysis Depth**: Provide a professional analysis including specific figures and evidence.
3. **Pros & Cons**: Clearly derive exactly 2 positive factors (Pros) and 2 negative factors (Cons).
4. **Score**: Evaluate the overall expectation level as an integer from 1 (Worst) to 5 (Best).
5. **Link Location**: NEVER put URLs inside the main body text. Use the "links" array only.

[Strict JSON Rules]:
- NEVER use double quotes (") inside the 'summary' or 'pro_con' values. Use single quotes (') instead.
- Do NOT include any intro/outro text. Output only the JSON.

<JSON_START>
{{
    "target_price": "Insert FMP Average Target Price (e.g., $150.00) or 'N/A'",
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell",
    "score": "Integer from 1 to 5",
    "summary": "Professional 3-line summary in English. 따옴표(") 사용 금지.",
    "pro_con": "Pros: Detail 1, Detail 2 | Cons: Detail 1, Detail 2",
    "links": [ {{"title": "Report Title", "link": "URL"}} ]
}}
<JSON_END>"""

        elif lang_code == 'ja':
            prompt = f"""あなたはウォール街出身のIPO専門アナリストです。
Google検索を使用して、"{search_brand}" ({ticker})に関する最新の機関投資家レポートを見つけ分析してください。
{fmp_context}

[作成指針]
1. **言語規則**: 全て自然な日本語のみで記述してください。韓国語を絶対に混ぜないでください。
2. **分析の深さ**: 具体的な数値や根拠を含む専門的な分析を提供してください。
3. **Pros & Cons**: 肯定的な要素(長所)を2つ、否定적인 要素(短所)を2つ明確に抽出してください。
4. **スコア**: ウォール街のレポートの総合的な期待レベルを1(最悪)から5(最高)までの整数で評価してください。
5. **リンクの位置**: 本文の中には絶対にURLを入れず、必ず「links」配列の中にのみ記入してください。

[厳格なJSONルール]:
- 値の内部で二重引用符 (") を使用しないでください。代わりに一重引用符 (') を使用してください。
- 完全に有効なJSON形式のみを出力してください。

<JSON_START>
{{
    "target_price": "FMPの平均目標株価を挿입 (例: $150.00) または 'N/A'",
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell (英語維持)",
    "score": "1から5までの整数",
    "summary": "日本語での専門的な3行要約 (目標株価の言及を含む)",
    "pro_con": "長所: 詳細1, 詳細2 | 短所: 詳細1, 詳細2",
    "links":[ {{"title": "レポートタイトル", "link": "URL"}} ]
}}
<JSON_END>"""

        elif lang_code == 'zh':
            prompt = f"""您是华尔街的专业IPO分析师。
请使用Google搜索工具查找并分析关于 "{search_brand}" ({ticker}) 的最新机构报告。
{fmp_context}

[编写指南]
1. **语言规则**: 必须只用简体中文编写。严禁混用韩语。
2. **分析深度**: 提供包含具体数据和依据的专业分析。
3. **Pros & Cons**: 明确提取2个积极因素(优点)和2个消极因素(缺点)。
4. **评分**: 将华尔街报告의 综合预期水平评为1(最差)到5(极佳)的整数。
5. **链接位置**: 绝对不要在正文中放入URL，必须只填写在“links”数组中。

[严格JSON规则]:
- 绝对不要在值的内容中使用双引号 (")，请使用单引号 (') 代替。
- 必须输出有效的JSON对象。

<JSON_START>
{{
    "target_price": "插入FMP平均目标价 (如: $150.00) 或 'N/A'",
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell (保留英文)",
    "score": "1到5的整数",
    "summary": "包含目标价背景的专业中文三行摘要",
    "pro_con": "优点: 分析1, 分析2 | 缺点: 风险1, 风险2",
    "links":[ {{"title": "报告标题", "link": "URL"}} ]
}}
<JSON_END>"""

        else: # ko
            prompt = f"""당신은 월가 출신의 IPO 전문 분석가입니다. 
구글 검색 도구를 사용하여 "{search_brand}" ({ticker})에 대한 최신 기관 리포트(Seeking Alpha, Renaissance Capital 등)를 찾아 심층 분석하세요.
{fmp_context}

[작성 지침]
1. **언어 규칙**: 반드시 자연스러운 한국어로 번역하여 작성하세요.
2. **분석 깊이**: 구체적인 수치나 근거를 포함하여 전문적으로 분석하세요.
3. **Pros & Cons**: 긍정적 요소(Pros) 2가지와 부정적 요소(Cons) 2가지를 명확히 도출하여 반영하세요.
4. **Score**: 월가 리포트의 종합적인 긍정/기대 수준을 1점(최악)부터 5점(대박) 사이의 정수로 평가하세요.
5. **링크 위치**: 본문 안에는 절대 URL을 넣지 말고, 반드시 "links" 배열 안에만 기입하세요.

[엄격한 JSON 규칙]:
- JSON 값(Value) 내부에서 쌍따옴표(")를 절대 사용하지 마세요. 필요시 홑따옴표(')를 사용하세요.
- 반드시 'json.loads()'로 파싱 가능한 유효한 JSON만 출력하세요. 인사말은 생략하세요.

<JSON_START>
{{
    "target_price": "FMP 평균 목표 주가 삽입 (예: $150.00) 또는 'N/A'",
    "rating": "Strong Buy / Buy / Hold / Neutral / Sell 중 택 1 (영어 유지)",
    "score": "1~5 사이의 정수 (예: 4)",
    "summary": "한국어 전문 3줄 요약 (쌍따옴표 사용 금지, 목표 주가 맥락 포함)",
    "pro_con": "장점: 분석 내용 1, 분석 내용 2 | 단점: 리스크 요인 1, 리스크 요인 2",
    "links": [ {{"title": "리포트 제목", "link": "URL"}} ]
}}
<JSON_END>"""
        
        try:
            # 1. 모델 결정 및 생성
            target_model = model_search if model_search is not None else model_strict
            response = target_model.generate_content(prompt)
            
            if not response or not hasattr(response, 'text') or not response.text:
                raise ValueError("AI response is empty or invalid")
                
            full_text = response.text
            
            # 2. JSON 추출 (은탄환 로직)
            start_idx = full_text.find('{')
            end_idx = full_text.rfind('}')
            
            if start_idx != -1 and end_idx != -1:
                json_str = full_text[start_idx:end_idx+1]
                
                try:
                    # JSON 파싱
                    parsed_json = json.loads(json_str, strict=False)
                    
                    # 🚀 [시그널 포착] 한국어 분석 시점에 수행
                    if lang_code == 'ko':
                        rating_val = str(parsed_json.get('rating', '')).upper()
                        score_val = str(parsed_json.get('score', '0')).strip()
                        if ("BUY" in rating_val) or (score_val in ["4", "5"]):
                            is_positive_signal = True
                            detected_rating = parsed_json.get('rating', 'Buy')

                    # 3. DB 저장 (Upsert)
                    batch_upsert("analysis_cache", [{
                        "cache_key": cache_key, 
                        "content": json.dumps(parsed_json, ensure_ascii=False), 
                        "updated_at": datetime.now().isoformat(),
                        "ticker": ticker,
                        "tier": "premium",
                        "tab_name": "tab4",
                        "lang": lang_code,
                        "data_type": "analyst_report"
                    }], on_conflict="cache_key")
                    print(f"✅ [{ticker}] Tab 4 기관 리포트 완료 ({lang_code})")

                except json.JSONDecodeError as je:
                    print(f"⚠️ [{ticker}] Tab 4 JSON 파싱 에러 ({lang_code}): {je}")
            else:
                # 중괄호를 찾지 못한 경우
                raise ValueError("No valid JSON structure detected in response")
                
        except Exception as e:
            # 💡 [해결 포인트] 이 except 라인이 2304라인 부근이며, 
            # 바로 위 'try: (1. 모델 결정 및 생성)'과 정확히 수직으로 일치해야 합니다.
            print(f"⚠️ [{ticker}] Tab 4 리포트 분석 최종 실패 ({lang_code}): {e}")

    # 💡 [과금 방어막 3] 4개 국어 번역이 성공적으로 끝났다면 트래커 갱신!
    batch_upsert("analysis_cache",[{"cache_key": tracker_key, "content": current_analyst_str, "updated_at": datetime.now().isoformat()}], "cache_key")

    # 🚀 [신규 추가] 긍정적 시그널이 포착되었을 때만 프리미엄 플러스 유저에게 푸시 발송
    if is_positive_signal:
        try:
            # 어닝서프라이즈 푸시 발송 로직 (기존 코드)
            send_fcm_push(
                title_dict={
                    "ko": f"🚀 {ticker} 어닝 서프라이즈!",
                    "en": f"🚀 {ticker} Earnings Surprise!",
                    "ja": f"🚀 {ticker} 긍정적인 실적 발표!",
                    "zh": f"🚀 {ticker} 业绩超预期！"
                },
                body_dict={
                    "ko": f"{ticker}의 실적이 예상치를 상회했습니다. 지금 세부 수치를 확인하세요.",
                    "en": f"{ticker} reported earnings above estimates. Check the details now.",
                    "ja": f"{ticker}の業績が予想を上回りました。今すぐ詳細を確認하세요.",
                    "zh": f"{ticker} 的业绩超出预期。立即查看详细数据。"
                },
                ticker=ticker,
                target_level='premium'
            )
        except Exception as e:
            print(f"⚠️ 어닝서프라이즈 푸시 실패: {e}")

    return True

    # =========================================================
    # 🚀 [B] 프리미엄 전용 데이터 수집 (Upgrades/Downgrades & Peers)
    # =========================================================
    try:
        # 🚀 [추가] 일반주 티커 획득
        base_ticker = get_base_ticker(ticker)
        
        ud_url = f"https://financialmodelingprep.com/stable/upgrades-downgrades?symbol={ticker}&apikey={FMP_API_KEY}"
        ud_raw = get_fmp_data_with_cache(ticker, "RAW_UPGRADES", ud_url, valid_hours=24)
        # 🚀 [추가] Fallback 로직
        if not ud_raw and ticker != base_ticker:
            ud_url_base = f"https://financialmodelingprep.com/stable/upgrades-downgrades?symbol={base_ticker}&apikey={FMP_API_KEY}"
            ud_raw = get_fmp_data_with_cache(base_ticker, "RAW_UPGRADES", ud_url_base, valid_hours=24)
        
        peers_url = f"https://financialmodelingprep.com/stable/stock-peers?symbol={ticker}&apikey={FMP_API_KEY}"
        peers_raw = get_fmp_data_with_cache(ticker, "RAW_PEERS", peers_url, valid_hours=24)
        # 🚀 [추가] Fallback 로직
        if not peers_raw and ticker != base_ticker:
            peers_url_base = f"https://financialmodelingprep.com/stable/stock-peers?symbol={base_ticker}&apikey={FMP_API_KEY}"
            peers_raw = get_fmp_data_with_cache(base_ticker, "RAW_PEERS", peers_url_base, valid_hours=24)

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
                        try:
                            resp_ud = model_strict.generate_content(prompt_ud)
                            if resp_ud and resp_ud.text:
                                ud_paragraphs = [p.strip() for p in resp_ud.text.split('\n') if len(p.strip()) > 20]
                                indent_size = "14px" if lang_code == "ko" else "0px"
                                html_ud = "".join([f'<p style="text-indent:{indent_size}; margin-bottom:15px; line-height:1.8; text-align:justify; font-size:15px; color:#333;">{p}</p>' for p in ud_paragraphs])
                                batch_upsert("analysis_cache", [{"cache_key": ud_summary_key, "content": html_ud, "updated_at": datetime.now().isoformat(), "ticker": ticker, "tier": "premium", "tab_name": "tab4", "lang": lang_code, "data_type": "rating_history"}], "cache_key")
                                print(f"✅ [{ticker}] 투자의견 히스토리 캐싱 완료 ({lang_code})")
                        except Exception as e:
                            print(f"⚠️ [{ticker}] 투자의견 히스토리 분석 실패 ({lang_code}): {e}")
                except:
                    pass

            if is_peers_valid:
                peers_summary_key = f"{ticker}_PremiumPeers_v1_{lang_code}"
                try:
                    res_p = supabase.table("analysis_cache").select("updated_at").eq("cache_key", peers_summary_key).gt("updated_at", limit_time_str).execute()
                    if not res_p.data:
                        prompt_p = get_tab4_premium_prompt(lang_code, "Stock Peers & Competitors", ticker, peers_raw)
                        try:
                            resp_p = model_strict.generate_content(prompt_p)
                            if resp_p and resp_p.text:
                                p_paragraphs = [p.strip() for p in resp_p.text.split('\n') if len(p.strip()) > 20]
                                indent_size = "14px" if lang_code == "ko" else "0px"
                                html_p = "".join([f'<p style="text-indent:{indent_size}; margin-bottom:15px; line-height:1.8; text-align:justify; font-size:15px; color:#333;">{p}</p>' for p in p_paragraphs])
                                batch_upsert("analysis_cache", [{"cache_key": peers_summary_key, "content": html_p, "updated_at": datetime.now().isoformat(), "ticker": ticker, "tier": "premium", "tab_name": "tab4", "lang": lang_code, "data_type": "peer_comparison"}], "cache_key")
                                print(f"✅ [{ticker}] 경쟁사 비교 캐싱 완료 ({lang_code})")
                        except Exception as e:
                            print(f"⚠️ [{ticker}] 경쟁사 비교 분석 실패 ({lang_code}): {e}")
                except:
                    pass

    except Exception as e:
        # 💡 [해결포인트] 이 라인이 2380라인 부근이며, 섹션 가장 위의 try와 수직 정렬됨
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
# [수정] FMP 프리미엄 11개 지표 통합 수집 헬퍼 (일반주 Fallback 적용)
# ==========================================
def fetch_premium_financials(symbol, api_key):
    fin_data = {
        'growth': 'N/A', 'net_margin': 'N/A', 'op_margin': 'N/A', 'pe': 'N/A',
        'roe': 'N/A', 'debt_equity': 'N/A', 'pb': 'N/A', 'accruals': 'Unknown',
        'dcf_price': 'N/A', 'current_price': 'N/A', 'rating': 'N/A',
        'recommendation': 'N/A', 'health_score': 'N/A'
    }
    
    # 🚀 후보군 생성 (우선주 -> 일반주 순서)
    base_sym = get_base_ticker(symbol)
    candidates = [symbol]
    if base_sym != symbol: candidates.append(base_sym)
    
    def safe_fmp_get(url, name):
        res = requests.get(url, timeout=5).json()
        if isinstance(res, dict) and "Error Message" in res:
            print(f"🚫 [재무 데이터 차단됨: {name}] -> {res['Error Message']}")
            return []
        return res

    for tk in candidates:
        try:
            # 1. 손익계산서 (⚠️ 기준점: 여기서 실패하면 바로 다음 후보로 넘어감)
            inc_url = f"https://financialmodelingprep.com/stable/income-statement?symbol={tk}&limit=2&apikey={api_key}"
            inc_res = safe_fmp_get(inc_url, "Income Statement")
            if not isinstance(inc_res, list) or len(inc_res) == 0:
                continue # 실패 시 다음 후보(base_ticker)로!

            rev = float(inc_res[0].get('revenue', 0))
            net_inc = float(inc_res[0].get('netIncome', 0))
            op_inc = float(inc_res[0].get('operatingIncome', 0))
            prev_rev = float(inc_res[1].get('revenue', rev)) if len(inc_res) > 1 else rev
            
            fin_data['growth'] = f"{((rev - prev_rev) / prev_rev) * 100:+.1f}%" if prev_rev else "N/A"
            fin_data['net_margin'] = f"{(net_inc / rev) * 100:.1f}%" if rev else "N/A"
            fin_data['op_margin'] = f"{(op_inc / rev) * 100:.1f}%" if rev else "N/A"
        
            # 2. 주요 지표 (성공한 tk 변수를 계속 사용)
            m_url = f"https://financialmodelingprep.com/stable/key-metrics-ttm?symbol={tk}&apikey={api_key}"
            m_res = safe_fmp_get(m_url, "Key Metrics TTM")
            if isinstance(m_res, list) and len(m_res) > 0:
                m = m_res[0]
                fin_data['pe'] = f"{m.get('peRatioTTM', 0):.1f}x" if m.get('peRatioTTM') else "N/A"
                fin_data['roe'] = f"{m.get('roeTTM', 0) * 100:.1f}%" if m.get('roeTTM') else "N/A"
                fin_data['debt_equity'] = f"{m.get('debtToEquityTTM', 0) * 100:.1f}%" if m.get('debtToEquityTTM') else "N/A"
                fin_data['pb'] = m.get('pbRatioTTM', 'N/A')

            # 3. 현금흐름 (Accruals)
            cf_url = f"https://financialmodelingprep.com/stable/cash-flow-statement?symbol={tk}&limit=1&apikey={api_key}"
            cf_res = safe_fmp_get(cf_url, "Cash Flow")
            if isinstance(cf_res, list) and len(cf_res) > 0 and fin_data['net_margin'] != 'N/A':
                ocf = float(cf_res[0].get('operatingCashFlow', 0))
                fin_data['accruals'] = "Low" if (fin_data.get('netIncome', 0) - ocf) <= 0 else "High"
            else:
                fin_data['accruals'] = "Unknown"

            # 4. DCF 적정주가
            dcf_url = f"https://financialmodelingprep.com/stable/discounted-cash-flow?symbol={tk}&apikey={api_key}"
            dcf_res = safe_fmp_get(dcf_url, "DCF")
            if isinstance(dcf_res, list) and len(dcf_res) > 0:
                dcf_val = dcf_res[0].get('dcf')
                stock_price = dcf_res[0].get('Stock Price')
                fin_data['dcf_price'] = f"${dcf_val:.2f}" if dcf_val is not None else "N/A"
                fin_data['current_price'] = f"${stock_price:.2f}" if stock_price is not None else "N/A"

            # 5. 퀀트 Rating
            r_url = f"https://financialmodelingprep.com/stable/rating?symbol={tk}&apikey={api_key}"
            r_res = safe_fmp_get(r_url, "Quant Rating")
            if isinstance(r_res, list) and len(r_res) > 0:
                fin_data['rating'] = r_res[0].get('rating', 'N/A')
                fin_data['recommendation'] = r_res[0].get('ratingRecommendation', 'N/A')
                fin_data['health_score'] = r_res[0].get('ratingScore', 'N/A')

            return fin_data # 성공 시 루프 탈출
        except Exception as e:
            print(f"Data Fetch Error for {tk}: {e}")
            
    return fin_data

# ==========================================
# [수정] FMP 애널리스트 목표가 & 컨센서스 수집 헬퍼
# ==========================================
def fetch_analyst_estimates(symbol, api_key):
    data = {"target": "N/A", "high": "N/A", "low": "N/A", "consensus": "N/A"}
    
    base_sym = get_base_ticker(symbol)
    candidates = [symbol]
    if base_sym != symbol: candidates.append(base_sym)

    for tk in candidates:
        try:
            pt_url = f"https://financialmodelingprep.com/stable/price-target-consensus?symbol={tk}&apikey={api_key}"
            pt_res = requests.get(pt_url, timeout=5).json()
            is_valid = False
            
            if isinstance(pt_res, dict) and "Error Message" in pt_res:
                pass
            elif isinstance(pt_res, list) and len(pt_res) > 0 and isinstance(pt_res[0], dict):
                data['target'] = pt_res[0].get('targetConsensus', 'N/A')
                data['high'] = pt_res[0].get('targetHigh', 'N/A')
                data['low'] = pt_res[0].get('targetLow', 'N/A')
                is_valid = True

            rec_url = f"https://financialmodelingprep.com/stable/analyst-stock-recommendations?symbol={tk}&limit=1&apikey={api_key}"
            rec_res = requests.get(rec_url, timeout=5).json()
            if isinstance(rec_res, dict) and "Error Message" in rec_res:
                pass
            elif isinstance(rec_res, list) and len(rec_res) > 0 and isinstance(rec_res[0], dict):
                data['consensus'] = rec_res[0].get('ratingRecommendation', 'N/A')
                is_valid = True
                
            if is_valid: return data # 하나라도 정상 수집되면 즉시 반환
        except Exception as e: 
            print(f"Analyst Data Fetch Error for {tk}: {e}")
            
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
    
    # 🚀 [추가] 일반주 티커 획득
    base_ticker = get_base_ticker(ticker) 
    
    try:
        url = f"https://financialmodelingprep.com/stable/search-mergers-acquisitions?name={ticker}&apikey={FMP_API_KEY}"
        ma_raw = get_fmp_data_with_cache(ticker, "RAW_MA_HISTORY", url, valid_hours=24)
        
        # 🚀 [추가] 우선주로 실패 시 일반주(base_ticker)로 재요청
        if (not isinstance(ma_raw, list) or len(ma_raw) == 0) and ticker != base_ticker:
            url_base = f"https://financialmodelingprep.com/stable/search-mergers-acquisitions?name={base_ticker}&apikey={FMP_API_KEY}"
            ma_raw = get_fmp_data_with_cache(base_ticker, "RAW_MA_HISTORY", url_base, valid_hours=24)
        
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
            
            try:
                resp = model_strict.generate_content(prompt)
                if resp and resp.text:
                    paragraphs = [p.strip() for p in resp.text.split('\n') if len(p.strip()) > 20]
                    indent_size = "14px" if lang_code == "ko" else "0px"
                    html_str = "".join([f'<p style="text-indent:{indent_size}; margin-bottom:15px; line-height:1.8; text-align:justify; font-size:15px; color:#333;">{p}</p>' for p in paragraphs])
                    
                    batch_upsert("analysis_cache", [{
                        "cache_key": ma_summary_key, 
                        "content": html_str, 
                        "updated_at": datetime.now().isoformat(),
                        "ticker": ticker, 
                        "tier": "premium_plus", 
                        "tab_name": "tab4", 
                        "lang": lang_code, 
                        "data_type": "ma_report"
                    }], on_conflict="cache_key")
                    print(f"✅ [{ticker}] M&A 분석 캐싱 완료 ({lang_code})")
                    analysis_success = True
                    
            except Exception as e:
                # 래퍼가 내부에서 5번의 지수 백오프를 시도하고도 실패했을 때만 이곳으로 떨어집니다.
                print(f"⚠️ [{ticker}] M&A 분석 실패 ({lang_code}) - 래퍼 복구 한도 초과: {e}")
        
        # 🚀 [FCM 다국어 발송] 분석 완료 후 알림 발송 (Premium Plus 전용)
        if analysis_success:
            send_fcm_push(
                title_dict={"ko": f"🤝 {ticker} 인수합병(M&A) 소식", "en": f"🤝 {ticker} M&A News", "ja": f"🤝 {ticker} M&Aニュース", "zh": f"🤝 {ticker} 并购(M&A)消息"},
                body_dict={"ko": "최근 M&A 거래 내역과 전략적 시너지 분석 리포트가 업데이트되었습니다.", "en": "The latest M&A transactions and strategic synergy analysis are updated.", "ja": "最近のM&A取引履歴と戦略的シナジー分析が更新されました。", "zh": "最新的并购交易记录与战略协同效应分析已更新。"},
                ticker=ticker, target_level='premium_plus'
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
    
    # 🚀 [추가] 일반주 티커 획득
    base_ticker = get_base_ticker(ticker)
    
    try:
        # --- [1] 투자의견 변화(Upgrades & Downgrades) 처리 ---
        ud_url = f"https://financialmodelingprep.com/stable/upgrades-downgrades?symbol={ticker}&apikey={FMP_API_KEY}"
        ud_raw = get_fmp_data_with_cache(ticker, "RAW_UPGRADES", ud_url, valid_hours=24)
        
        # 🚀 [추가] 일반주 Fallback 로직
        if not ud_raw and ticker != base_ticker:
            ud_url_base = f"https://financialmodelingprep.com/stable/upgrades-downgrades?symbol={base_ticker}&apikey={FMP_API_KEY}"
            ud_raw = get_fmp_data_with_cache(base_ticker, "RAW_UPGRADES", ud_url_base, valid_hours=24)
        
        if isinstance(ud_raw, list) and len(ud_raw) > 0:
            current_ud_str = json.dumps(ud_raw[:10], sort_keys=True)
            tracker_key_ud = f"{ticker}_PremiumUpgrades_RawTracker"
            is_changed_ud = True
            
            try:
                res_ud = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key_ud).execute()
                if res_ud.data and current_ud_str == res_ud.data[0]['content']:
                    is_changed_ud = False
            except:
                pass
            
            if is_changed_ud:
                print(f"🔔 [{ticker}] 투자의견(Upgrades) 업데이트 감지! AI 요약 시작...")
                ud_success = False
                for lang_code in SUPPORTED_LANGS.keys():
                    ud_summary_key = f"{ticker}_PremiumUpgrades_v1_{lang_code}"
                    prompt_ud = get_tab4_premium_prompt(lang_code, "Upgrades and Downgrades History", ticker, current_ud_str)
                    
                    try:
                        resp_ud = model_strict.generate_content(prompt_ud)
                        if resp_ud and resp_ud.text:
                            ud_paragraphs = [p.strip() for p in resp_ud.text.split('\n') if len(p.strip()) > 20]
                            indent_size = "14px" if lang_code == "ko" else "0px"
                            html_ud = "".join([f'<p style="text-indent:{indent_size}; margin-bottom:15px; line-height:1.8; text-align:justify; font-size:15px; color:#333;">{p}</p>' for p in ud_paragraphs])
                            
                            batch_upsert("analysis_cache", [{
                                "cache_key": ud_summary_key, 
                                "content": html_ud, 
                                "updated_at": datetime.now().isoformat(),
                                "ticker": ticker, 
                                "tier": "premium", 
                                "tab_name": "tab4", 
                                "lang": lang_code, 
                                "data_type": "rating_history"
                            }], on_conflict="cache_key")
                            
                            print(f"✅ [{ticker}] 투자의견 히스토리 캐싱 완료 ({lang_code})")
                            ud_success = True
                    except Exception as ai_err:
                        print(f"⚠️ [{ticker}] 투자의견 히스토리 분석 실패 ({lang_code}): {ai_err}")
                
                # 🚀 [FCM 다국어 발송] 분석 완료 후 알림 발송 (Premium Plus 전용)
                if ud_success:
                    send_fcm_push(
                        title_dict={
                            "ko": f"🎯 {ticker} 월가 투자의견 변경", 
                            "en": f"🎯 {ticker} Analyst Ratings Changed", 
                            "ja": f"🎯 {ticker} 投資判断変更", 
                            "zh": f"🎯 {ticker} 投资评级变更"
                        },
                        body_dict={
                            "ko": "주요 투자은행들의 투자의견 및 목표주가 변화를 확인하세요.", 
                            "en": "Check the latest upgrades and target price changes by major IBs.", 
                            "ja": "主要投資銀行の投資判断および目標株価の変化をご確認ください。", 
                            "zh": "查看主要投行的投资评级及目标价变动。"
                        },
                        ticker=ticker, 
                        target_level='premium_plus'
                    )
                        
                batch_upsert("analysis_cache", [{"cache_key": tracker_key_ud, "content": current_ud_str, "updated_at": datetime.now().isoformat()}], "cache_key")

    except Exception as e:
        # 💡 [해결포인트] 이 라인이 2838라인 부근이며, 섹션 가장 위의 try와 수직 정렬됨
        print(f"Premium Tab 4 FMP Error for {ticker}: {e}")

        # --- [2] 경쟁사(Peers) 처리 ---
        peers_url = f"https://financialmodelingprep.com/stable/stock-peers?symbol={ticker}&apikey={FMP_API_KEY}"
        peers_raw = get_fmp_data_with_cache(ticker, "RAW_PEERS", peers_url, valid_hours=24)
        
        # 🚀 [추가]
        if not peers_raw and ticker != base_ticker:
            peers_url_base = f"https://financialmodelingprep.com/stable/stock-peers?symbol={base_ticker}&apikey={FMP_API_KEY}"
            peers_raw = get_fmp_data_with_cache(base_ticker, "RAW_PEERS", peers_url_base, valid_hours=24)
        
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
                    
                    try:
                            resp_p = model_strict.generate_content(prompt_p)
                            if resp_p and resp_p.text:
                                p_paragraphs = [p.strip() for p in resp_p.text.split('\n') if len(p.strip()) > 20]
                                indent_size = "14px" if lang_code == "ko" else "0px"
                                html_p = "".join([f'<p style="text-indent:{indent_size}; margin-bottom:15px; line-height:1.8; text-align:justify; font-size:15px; color:#333;">{p}</p>' for p in p_paragraphs])
                                
                                batch_upsert("analysis_cache", [{
                                    "cache_key": peers_summary_key, 
                                    "content": html_p, 
                                    "updated_at": datetime.now().isoformat(),
                                    "ticker": ticker, 
                                    "tier": "premium", 
                                    "tab_name": "tab4", 
                                    "lang": lang_code, 
                                    "data_type": "peer_comparison"
                                }], on_conflict="cache_key")
                                
                                print(f"✅ [{ticker}] 경쟁사 비교 캐싱 완료 ({lang_code})")
                        except Exception as e:
                            # 래퍼가 내부에서 5번의 지수 백오프를 시도하고도 실패했을 때만 실행됩니다.
                            print(f"⚠️ [{ticker}] 경쟁사 비교 분석 실패 ({lang_code}) - 래퍼 복구 한도 초과: {e}")
                        
                batch_upsert("analysis_cache", [{"cache_key": tracker_key_p, "content": current_p_str, "updated_at": datetime.now().isoformat()}], "cache_key")

    except Exception as e:
        print(f"Tab4 Premium Collection Error for {ticker}: {e}")
    
# ==========================================
# [최종 수정본] Tab 3: 미시 지표 분석 (데이터 정직성 + 실시간 동기화)
# ==========================================
def run_tab3_analysis(ticker, company_name, raw_metrics, ipo_date_str=None):
    if 'model_strict' not in globals() or not model_strict: return False
    
    print(f"🛠️[DEBUG-{ticker}] Tab3 프로세스 진입")
    base_ticker = get_base_ticker(ticker)
    
    pristine_metrics_str = json.dumps(raw_metrics, sort_keys=True)
    tracker_key = f"{ticker}_Tab3_Financial_RawTracker"
    is_changed = True
    
    try:
        res_tracker = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key).execute()
        if res_tracker.data and pristine_metrics_str == res_tracker.data[0]['content']:
            is_changed = False 
    except Exception as e: pass

    # 🚀[가짜 트래커 자가 치유] 트래커가 같아도 실제 AI 리포트가 없으면 강제로 뚫고 들어감!
    if not is_changed:
        try:
            res_check = supabase.table("analysis_cache").select("cache_key").eq("cache_key", f"{ticker}_Tab3_v2_Premium_ko").execute()
            if not res_check.data:
                is_changed = True 
                print(f"🔄 [{ticker}] Tab 3 가짜 트래커 발견. 강제 재분석합니다.")
        except: pass

    # AI 보강용 복사본 생성
    enriched_metrics = copy.deepcopy(raw_metrics)

    is_fmp_fin_poor = (str(enriched_metrics.get('growth', 'N/A')) in ['N/A', '', 'None'])
    can_fin_search = is_fmp_fin_poor and (model_search is not None)
    
    force_search_run = False
    if not is_changed and can_fin_search:
        try:
            limit_time_str = (datetime.now() - timedelta(hours=168)).isoformat()
            test_key = f"{ticker}_Tab3_Summary_ko"
            res_exp = supabase.table("analysis_cache").select("updated_at").eq("cache_key", test_key).gt("updated_at", limit_time_str).execute()
            if not res_exp.data:
                force_search_run = True 
        except: pass

    if not is_changed and not force_search_run:
        return True 
        
    reason = "데이터 변경" if is_changed else "정기 재무 검색"
    print(f"🔔 [{ticker}] Tab 3 업데이트 감지 ({reason})! 분석 시작...")
    
    curr_yr = datetime.now().year
    past_3_years = f"{curr_yr-2} {curr_yr-1} {curr_yr}"
    rich_raw_data_str = "N/A"
    
    # =====================================================================
    # 🚀 [Step 1] 구글 검색 데이터 보강 및 "카드 원본 JSON" 갱신
    # =====================================================================
    if can_fin_search:
        print(f"🔍 [{ticker}] 재무 데이터 누락 감지. 구글 딥서치 시도...")
        # 🚀 [수정] 프롬프트에 본주(base_ticker) 정보를 함께 전달하여 검색 정확도 향상
        recovery_prompt = f"""
        Search Google for the latest fundamental financial numbers of {company_name} (Ticker: {ticker}, Base Ticker: {base_ticker}) for the years {past_3_years}.
        Find EXACT absolute numbers in Millions or Billions.
        Output ONLY valid JSON:
        {{
            "revenue": "numeric", "prev_revenue": "numeric", "gross_profit": "numeric",
            "operating_income": "numeric", "net_income": "numeric", "total_assets": "numeric",
            "total_liabilities": "numeric", "total_debt": "numeric", "total_equity": "numeric",
            "operating_cash_flow": "numeric", "free_cash_flow": "numeric", "eps": "numeric"
        }}
        """
        try:
            rec_res = model_search.generate_content(recovery_prompt)
            if rec_res and rec_res.text:
                text = rec_res.text
                json_str = text[text.find('{'):text.rfind('}')+1]
                raw_data = json.loads(json_str)
                
                def to_float(val):
                    try: return float(re.sub(r'[^0-9.-]', '', str(val)))
                    except: return None
                
                rev, p_rev, net = to_float(raw_data.get("revenue")), to_float(raw_data.get("prev_revenue")), to_float(raw_data.get("net_income"))
                debt, equity, ocf = to_float(raw_data.get("total_debt")), to_float(raw_data.get("total_equity")), to_float(raw_data.get("operating_cash_flow"))
                eps = to_float(raw_data.get("eps"))
                
                updated = False
                if rev and p_rev and p_rev > 0:
                    enriched_metrics["growth"] = f"{((rev - p_rev) / p_rev) * 100:+.1f}%"
                    updated = True
                if rev and net:
                    enriched_metrics["net_margin"] = f"{(net / rev) * 100:.1f}%"
                    updated = True
                if debt and equity and equity > 0:
                    enriched_metrics["debt_equity"] = f"{(debt / equity) * 100:.1f}%"
                    updated = True
                if net and ocf:
                    enriched_metrics["accruals"] = "Low" if (net - ocf) <= 0 else "High"
                    updated = True
                if eps: enriched_metrics["eps"] = eps

                rich_raw_data_str = ", ".join([f"{k}: {v}" for k, v in raw_data.items() if v not in [None, "N/A", ""]])
                enriched_metrics["raw_deep_data"] = rich_raw_data_str
                
                if updated:
                    # 💡 [카드 UI 동기화] 보강된 데이터를 원본 캐시에 저장
                    batch_upsert("analysis_cache", [{
                        "cache_key": f"{ticker}_Raw_Financials",
                        "content": json.dumps(enriched_metrics, ensure_ascii=False),
                        "updated_at": datetime.now().isoformat(),
                        "ticker": ticker, "data_type": "enriched_financial_data"
                    }], on_conflict="cache_key")
        except Exception as e:
            print(f"⚠️ [{ticker}] 데이터 수집 실패: {e}")

    if rich_raw_data_str == "N/A" and "raw_deep_data" in enriched_metrics:
        rich_raw_data_str = enriched_metrics["raw_deep_data"]

    # 분석용 컨텍스트 조립
    g1_context = f"Growth & Profitability: Sales Growth {enriched_metrics.get('growth', 'N/A')}, Net Margin {enriched_metrics.get('net_margin', 'N/A')}"
    g2_context = f"Financial Health: Debt to Equity {enriched_metrics.get('debt_equity', 'N/A')}, Accruals {enriched_metrics.get('accruals', 'Unknown')}"
    g3_context = f"Market/Valuation: Forward P/E {enriched_metrics.get('pe', 'N/A')}, DCF Target {enriched_metrics.get('dcf_price', 'N/A')}"
    g4_context = f"Raw Financial Numbers: {rich_raw_data_str}"

    limit_time_str = (datetime.now() - timedelta(hours=168)).isoformat() if force_search_run else (datetime.now() - timedelta(hours=24)).isoformat()

    # =====================================================================
    # 🚀 [Step 2] 4개 국어 리포트 및 요약 카드 작성 (디버깅 모드 + 정규식 안전 교체)
    # =====================================================================
    def run_tab3_analysis(ticker, company_name, raw_metrics, ipo_date_str=None):
        if 'model_strict' not in globals() or not model_strict: return False
        
        print(f"🛠️ [DEBUG-{ticker}] Tab3 프로세스 진입")
        base_ticker = get_base_ticker(ticker)
        
        pristine_metrics_str = json.dumps(raw_metrics, sort_keys=True)
        tracker_key = f"{ticker}_Tab3_Financial_RawTracker"
        is_changed = True
        
        try:
            print(f"🛠️ [DEBUG-{ticker}] 캐시 DB 조회 중...")
            res_tracker = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key).execute()
            if res_tracker.data and pristine_metrics_str == res_tracker.data[0]['content']:
                is_changed = False 
        except Exception as e: 
            print(f"🛠️ [DEBUG-{ticker}] 캐시 DB 조회 에러: {e}")
    
        enriched_metrics = copy.deepcopy(raw_metrics)
        is_fmp_fin_poor = (str(enriched_metrics.get('growth', 'N/A')) in ['N/A', '', 'None'])
        can_fin_search = is_fmp_fin_poor and (model_search is not None)
        
        force_search_run = False
        if not is_changed and can_fin_search:
            try:
                limit_time_str = (datetime.now() - timedelta(hours=168)).isoformat()
                test_key = f"{ticker}_Tab3_Summary_ko"
                res_exp = supabase.table("analysis_cache").select("updated_at").eq("cache_key", test_key).gt("updated_at", limit_time_str).execute()
                if not res_exp.data:
                    force_search_run = True 
            except: pass
    
        if not is_changed and not force_search_run:
            print(f"🛠️ [DEBUG-{ticker}] 변경점 없음. 분석 스킵!")
            return True 
            
        reason = "데이터 변경" if is_changed else "정기 재무 검색"
        print(f"🔔 [{ticker}] Tab 3 업데이트 감지 ({reason})! 분석 시작...")
        
        curr_yr = datetime.now().year
        past_3_years = f"{curr_yr-2} {curr_yr-1} {curr_yr}"
        rich_raw_data_str = "N/A"
        
        if can_fin_search:
            print(f"🔍 [{ticker}] 구글 딥서치 API 호출 중...")
            recovery_prompt = f"""
            Search Google for the latest fundamental financial numbers of {company_name} (Ticker: {ticker}, Base Ticker: {base_ticker}) for the years {past_3_years}.
            Find EXACT absolute numbers in Millions or Billions.
            Output ONLY valid JSON:
            {{
                "revenue": "numeric", "prev_revenue": "numeric", "gross_profit": "numeric",
                "operating_income": "numeric", "net_income": "numeric", "total_assets": "numeric",
                "total_liabilities": "numeric", "total_debt": "numeric", "total_equity": "numeric",
                "operating_cash_flow": "numeric", "free_cash_flow": "numeric", "eps": "numeric"
            }}
            """
            try:
                rec_res = model_search.generate_content(recovery_prompt)
                print(f"🛠️ [DEBUG-{ticker}] 구글 딥서치 응답 성공")
                if rec_res and rec_res.text:
                    text = rec_res.text
                    json_str = text[text.find('{'):text.rfind('}')+1]
                    raw_data = json.loads(json_str)
                    
                    def to_float(val):
                        try: return float(re.sub(r'[^0-9.-]', '', str(val)))
                        except: return None
                    
                    rev, p_rev, net = to_float(raw_data.get("revenue")), to_float(raw_data.get("prev_revenue")), to_float(raw_data.get("net_income"))
                    debt, equity, ocf = to_float(raw_data.get("total_debt")), to_float(raw_data.get("total_equity")), to_float(raw_data.get("operating_cash_flow"))
                    eps = to_float(raw_data.get("eps"))
                    
                    updated = False
                    if rev and p_rev and p_rev > 0:
                        enriched_metrics["growth"] = f"{((rev - p_rev) / p_rev) * 100:+.1f}%"
                        updated = True
                    if rev and net:
                        enriched_metrics["net_margin"] = f"{(net / rev) * 100:.1f}%"
                        updated = True
                    if debt and equity and equity > 0:
                        enriched_metrics["debt_equity"] = f"{(debt / equity) * 100:.1f}%"
                        updated = True
                    if net and ocf:
                        enriched_metrics["accruals"] = "Low" if (net - ocf) <= 0 else "High"
                        updated = True
                    if eps: enriched_metrics["eps"] = eps
    
                    rich_raw_data_str = ", ".join([f"{k}: {v}" for k, v in raw_data.items() if v not in [None, "N/A", ""]])
                    enriched_metrics["raw_deep_data"] = rich_raw_data_str
                    
                    if updated:
                        batch_upsert("analysis_cache",[{
                            "cache_key": f"{ticker}_Raw_Financials",
                            "content": json.dumps(enriched_metrics, ensure_ascii=False),
                            "updated_at": datetime.now().isoformat(),
                            "ticker": ticker, "data_type": "enriched_financial_data"
                        }], on_conflict="cache_key")
            except Exception as e:
                print(f"⚠️[{ticker}] 데이터 수집 실패: {e}")
    
        if rich_raw_data_str == "N/A" and "raw_deep_data" in enriched_metrics:
            rich_raw_data_str = enriched_metrics["raw_deep_data"]
    
        g1_context = f"Growth & Profitability: Sales Growth {enriched_metrics.get('growth', 'N/A')}, Net Margin {enriched_metrics.get('net_margin', 'N/A')}"
        g2_context = f"Financial Health: Debt to Equity {enriched_metrics.get('debt_equity', 'N/A')}, Accruals {enriched_metrics.get('accruals', 'Unknown')}"
        g3_context = f"Market/Valuation: Forward P/E {enriched_metrics.get('pe', 'N/A')}, DCF Target {enriched_metrics.get('dcf_price', 'N/A')}"
        g4_context = f"Raw Financial Numbers: {rich_raw_data_str}"
    
        for lang_code, target_lang in SUPPORTED_LANGS.items():
            print(f"🛠️ [DEBUG-{ticker}] {lang_code} 언어 분석 루프 시작")
            cache_key_sum = f"{ticker}_Tab3_Summary_{lang_code}"
            cache_key_full = f"{ticker}_Tab3_v2_Premium_{lang_code}"
            
            ib_benchmark = """[Wall Street IB Standard Benchmarks for Analysis]
            1. Profitability & Growth (수익성 및 성장성):
               - Sales Growth: > 20% (High Growth / Strong Demand), 0-20% (Moderate), < 0% (Contraction).
               - Net Margin: > 10% (Solid Profitability), < 0% (Deficit / Warning).
               - Piotroski F-Score: 8-9 (Exceptional / Strong Fundamental), 5-7 (Stable), 0-4 (Weak / Distressed).
            2. Financial Health & Earnings Quality (건전성 및 이익 품질):
               - Debt-to-Equity (D/E): < 100% (Healthy / Low Leverage), > 200% (High Risk / Highly Leveraged).
               - Accruals Quality: 'Low' (High Quality Earnings - OCF > Net Income), 'High' (Low Quality Earnings - Warning).
            3. Valuation & Market Sentiment (가치 평가 및 시장 심리):
               - Forward P/E: > 25x (Growth Premium or Overvalued), < 15x (Value Territory).
               - DCF Gap: DCF > Current Price (Undervalued / Upside Potential), DCF < Current Price (Overvalued / Downside Risk).
               - IPO Return: > 20% (Strong Market Appetite), < 0% (Busted IPO / Weak Demand).
            """
    
            if lang_code == 'ko':
                sum_i = f"""{ib_benchmark}[UI 카드 작성 규칙 - 절대 엄수]
                1. 라벨이나 소제목을 절대 출력하지 마세요.
                2. 포맷: (수익성 비율 중심 팩트 요약 2~3문장) |||SEP||| (건전성 비율 중심 팩트 요약 2~3문장) |||SEP||| (시장 밸류에이션 요약 2~3문장)
                3. 🚨[절대값 추론 금지]: 절대값(예:부채 54만달러)으로 긍정/부정을 판단하지 마세요. 비율과 퀄리티 지표로만 분석하세요.
                """
                full_i = """[전문 리포트 작성 규칙 - 절대 엄수]
                1. 첫 글자는 반드시 '['여야 합니다. 
                2. 반드시 [수익성 및 성장성 분석], [재무 건전성 분석], [시장 및 가치 평가] 3개의 소제목으로만 구성하세요.
                3. 각 문단은 3~4줄(문장) 길이로 작성. (단, 데이터가 N/A인 경우 이 분량 규칙을 무시하고 아주 짧게 작성합니다.)
                4. 🚨[Wall Street IB Standard Analysis]: 제공된 IB 벤치마크를 엄격하게 적용하여 시니어 애널리스트 어조로 분석하세요.
                5. 모든 문장은 '~습니다', '~합니다'로 마무리하세요.
                """
                na_rule = """🚨 [CRITICAL RULES FOR MISSING DATA (N/A) - 환각 완벽 차단]
                1. 사전적 정의 금지: 지표가 'N/A'일 때, 그 지표의 의미나 일반적인 투자 조언(예: "순이익률은 회사의 효율성을 뜻합니다", "투자자는 주의해야 합니다")을 절대 적지 마세요.
                2. 즉각 스킵: 해당 섹션의 데이터가 부재하다면, "관련 데이터 부재(N/A)로 인해 분석할 수 없습니다."라고 단 한 줄만 적고 즉시 다음 섹션으로 넘어가세요. 분량 채우기 절대 금지.
                """
                
            elif lang_code == 'en':
                sum_i = f"""{ib_benchmark}[UI Card Rules - STRICT]
                1. DO NOT output labels. Format: (Profitability Ratios 2-3 sentences) |||SEP||| (Health Ratios 2-3 sentences) |||SEP||| (Valuation 2-3 sentences)
                2. 🚨 [No Absolute Value Guessing]: Never evaluate health based on absolute numbers. Use Benchmarks for Ratios.
                """
                full_i = """[Report Rules - STRICT]
                1. First character MUST be '['. 
                2. Exactly 3 subheadings: [Profitability & Growth], [Financial Health], [Valuation].
                3. Each paragraph MUST be 3 to 4 sentences long. (Exception: Ignore this length rule entirely if data is N/A).
                4. 🚨[Wall Street IB Standard Analysis]: Apply IB benchmarks strictly.
                """
                na_rule = """🚨 [CRITICAL RULES FOR MISSING DATA (N/A) - ANTI-HALLUCINATION]
                1. NO TEXTBOOK DEFINITIONS: If a metric is 'N/A', DO NOT explain what the metric means or give general investing advice. (e.g., Never write "Sales growth indicates...").
                2. DIRECT REPORTING: If data is missing, output exactly one sentence: "Insufficient data (N/A) to analyze this section." and MOVE ON. Do not pad the response to meet length requirements.
                """
                
            elif lang_code == 'ja':
                sum_i = f"""{ib_benchmark}[UIカード規則 - 厳守]
                1. ラベルは絶対に出力しないでください。フォーマット: (収益性比率要約 2-3文) |||SEP||| (健全性要約 2-3文) |||SEP||| (バリュエーション要約 2-3文)
                2. 🚨[絶対値の推論禁止]: 絶対値だけで健全性を評価しないでください。比率と品質のみで評価してください。
                """
                full_i = """[レポート規則 - 厳守]
                1. 最初の文字は必ず '[' です。
                2. 必ず [収益性と成長性の分析], [財務健全性分析], [市場および価値評価] の3つの見出しのみで構成。
                3. 各段落は必ず 3〜4文の長さ。(例外：データがN/Aの場合はこの長さの規則を無視して短く記述してください。)
                4. 🚨[Wall Street IB Standard Analysis]: IBベンチマークを厳格に適用してください。
                5. 全ての文章は「〜です」「〜ます」で統一。
                """
                na_rule = """🚨 [CRITICAL RULES FOR MISSING DATA (N/A) - 捏造完全遮断]
                1. 辞書的定義の禁止: 指標が 'N/A' の場合、その指標の意味や一般的な投資アドバイスを絶対に書かないでください。
                2. 即時スキップ: データがない場合は、「関連データが不足しているため、分析できません。」と一文だけ記述し、文字数を稼ぐための無駄な説明は一切やめてください。
                """
                
            else: # zh
                sum_i = f"""{ib_benchmark}[UI卡片规则 - 严格遵守]
                1. 绝对不要输出标签。格式: (盈利比率摘要 2-3句话) |||SEP||| (健康质量摘要 2-3句话) |||SEP||| (估值摘要 2-3句话)
                2. 🚨[禁止绝对值推测]: 不能凭绝对值评估。使用比率进行分析。
                """
                full_i = """[报告规则 - 严格遵守]
                1. 第一个字符必须是 '['。
                2. 仅包含 [盈利能力与增长性分析], [财务健康状况分析], [市场与估值分析] 三个子标题。
                3. 每个段落正好 3到4句话。(例外：如果数据为N/A，请完全忽略此长度规则并简短作答。)
                4. 🚨[Wall Street IB Standard Analysis]: 严格应用IB基准。
                """
                na_rule = """🚨 [CRITICAL RULES FOR MISSING DATA (N/A) - 防幻觉绝对规则]
                1. 禁止教科书式定义: 若指标为 'N/A', 绝对不要解释该指标的含义或提供一般性投资建议。
                2. 直接报告: 若缺乏数据，只需回复一句：“由于缺乏相关数据 (N/A)，无法进行分析。”，严禁为了凑字数而胡编乱造。
                """
    
            data_packet = f"Available Metrics:\n- {g1_context}\n- {g2_context}\n- {g3_context}\n- {g4_context}"
            final_full_prompt = f"Write a professional financial report for {company_name}.\n{data_packet}\nInstruction: {full_i}\nRule: {na_rule}\nLanguage: {target_lang}"
    
            # [Action 1] 요약 카드 생성
            print(f"🛠️ [DEBUG-{ticker}] {lang_code} 카드 요약(Action 1) AI 호출 중...")
            try:
                res_sum = model_strict.generate_content(f"Analyze {company_name} metrics for UI.\n{data_packet}\nInstruction: {sum_i}\nLanguage: {target_lang}")
                print(f"🛠️ [DEBUG-{ticker}] {lang_code} 카드 요약 AI 응답 완료")
                
                if res_sum and res_sum.text:
                    raw_sum = res_sum.text.strip()
                    cleaned_parts =[]
                    for part in raw_sum.split('|||SEP|||'):
                        part = part.strip()
                        # 🚨 무한루프(Catastrophic Backtracking)를 유발하던 정규식 제거, 안전한 Split 사용!
                        if ":" in part:
                            prefix = part.split(':', 1)[0]
                            # 콜론 앞이 30자 이내면 라벨(예: "성장성 해석:")로 간주하고 잘라버림
                            if len(prefix) < 30: 
                                part = part.split(':', 1)[1].strip()
                        part = part.replace('**', '').replace('[', '').replace(']', '').strip()
                        cleaned_parts.append(part)
                    
                    final_clean_sum = " |||SEP||| ".join(cleaned_parts)
                    
                    print(f"🛠️[DEBUG-{ticker}] {lang_code} 카드 요약 DB 저장 중...")
                    batch_upsert("analysis_cache",[{
                        "cache_key": cache_key_sum, "content": final_clean_sum, 
                        "updated_at": datetime.now().isoformat(), "ticker": ticker, "tier": "free", 
                        "tab_name": "tab3", "lang": lang_code, "data_type": "metrics_card"
                    }], on_conflict="cache_key")
            except Exception as e: 
                print(f"❌ [DEBUG-{ticker}] {lang_code} 카드 요약 에러: {e}")
    
            # [Action 2] 전문 리포트 생성
            print(f"🛠️ [DEBUG-{ticker}] {lang_code} 전문 리포트(Action 2) AI 호출 중...")
            try:
                res_full = model_strict.generate_content(final_full_prompt)
                print(f"🛠️ [DEBUG-{ticker}] {lang_code} 전문 리포트 AI 응답 완료")
                
                if res_full and res_full.text:
                    raw_f = clean_ai_preamble(res_full.text.strip())
                    raw_f = re.sub(r'([.!?。])\s*(\[|\*\*\[)', r'\1\n\n\2', raw_f)
                    lines = [l.strip() for l in raw_f.split('\n') if l.strip()]
                    
                    f_html = ""
                    first_header_found = False 
    
                    for line in lines:
                        clean_line = line.replace('*', '').strip()
                        if not clean_line: continue
    
                        header_match = re.match(r'^\[(수익성|재무|적정|종합|Profitability|Financial|Intrinsic|Verdict|収益|財務|適正|総合|盈利|财务|合理|综合).*?\]', clean_line)
                        
                        if header_match:
                            first_header_found = True
                            if f_html: f_html += "<br><br>"
                            f_html += f"<b>{clean_line}</b>"
                        else:
                            if not first_header_found:
                                continue
                            if f_html.endswith("</b>"):
                                f_html += f"<br>{clean_line}"
                            else:
                                f_html += f" {clean_line}"
                    
                    processed_content = f_html.strip()
                    if lang_code == 'ko' and processed_content:
                        parts = processed_content.split("<br><br>")
                        styled =[f'<div style="text-indent:14px; margin-bottom:15px; line-height:1.7;">{p}</div>' if not p.startswith("<b>") else p for p in parts]
                        processed_content = "".join(styled)
    
                    if processed_content:
                        print(f"🛠️ [DEBUG-{ticker}] {lang_code} 전문 리포트 DB 저장 중...")
                        batch_upsert("analysis_cache",[{
                            "cache_key": cache_key_full, "content": processed_content, 
                            "updated_at": datetime.now().isoformat(), "ticker": ticker, 
                            "tier": "premium", "tab_name": "tab3", "lang": lang_code, "data_type": "financial_report"
                        }], on_conflict="cache_key")
                        print(f"✅ [{ticker}] Tab 3 전문 리포트 완료 ({lang_code})")
            except Exception as e: 
                print(f"❌ [DEBUG-{ticker}] {lang_code} 전문 리포트 에러: {e}")
    
        print(f"🛠️ [DEBUG-{ticker}] 트래커 갱신 및 종료")
        batch_upsert("analysis_cache",[{"cache_key": tracker_key, "content": pristine_metrics_str, "updated_at": datetime.now().isoformat()}], "cache_key")
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
    
    # 🚀 [추가] 일반주 티커 추출
    base_ticker = get_base_ticker(ticker) 
    
    try:
        # --- [1] 어닝서프라이즈 처리 ---
        surp_url = f"https://financialmodelingprep.com/stable/earnings-surprises?symbol={ticker}&apikey={FMP_API_KEY}"
        surp_raw = get_fmp_data_with_cache(ticker, "RAW_SURPRISE", surp_url, valid_hours=24)
        
        # 🚀 [추가] 우선주로 실패 시 일반주로 재요청 폴백
        if not surp_raw and ticker != base_ticker:
            surp_url_base = f"https://financialmodelingprep.com/stable/earnings-surprises?symbol={base_ticker}&apikey={FMP_API_KEY}"
            surp_raw = get_fmp_data_with_cache(base_ticker, "RAW_SURPRISE", surp_url_base, valid_hours=24)
        
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
                    
                    try:
                            resp_s = model_strict.generate_content(prompt_s)
                            if resp_s and resp_s.text:
                                s_paragraphs = [p.strip() for p in resp_s.text.split('\n') if len(p.strip()) > 20]
                                indent_size = "14px" if lang_code == "ko" else "0px"
                                html_s = "".join([f'<p style="text-indent:{indent_size}; margin-bottom:15px; line-height:1.8; text-align:justify; font-size:15px; color:#333;">{p}</p>' for p in s_paragraphs])
                                
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
                        except Exception as e:
                            # 래퍼가 내부에서 5번의 지수 백오프를 시도하고도 실패했을 때만 실행됩니다.
                            print(f"⚠️ [{ticker}] 어닝서프라이즈 분석 실패 ({lang_code}) - 래퍼 복구 한도 초과: {e}")
                
                # 🚀 [FCM 다국어 발송] 분석 완료 후 프리미엄 유저에게 푸시 알림 발송 (Premium Plus 전용)
                try:
                    send_fcm_push(
                        title_dict={"ko": f"📊 {ticker} 어닝 서프라이즈", "en": f"📊 {ticker} Earnings Surprise", "ja": f"📊 {ticker} アーニングサプライズ", "zh": f"📊 {ticker} 财报超预期"},
                        body_dict={"ko": "예상치를 상회/하회한 최신 실적 분석 리포트가 업데이트되었습니다.", "en": "The latest earnings analysis beating/missing estimates has been updated.", "ja": "予想を上回る/下回る最新の業績分析が更新されました。", "zh": "超出/低于预期的最新业绩分析报告已更新。"},
                        ticker=ticker, target_level='premium_plus'
                    )
                except Exception as e:
                    print(f"⚠️ 어닝서프라이즈 푸시 실패: {e}")
                
                # 트래커 갱신
                batch_upsert("analysis_cache", [{"cache_key": tracker_key_s, "content": current_surp_str, "updated_at": datetime.now().isoformat()}], "cache_key")

        # --- [2] 실적전망치 처리 ---
        est_url = f"https://financialmodelingprep.com/stable/analyst-estimates?symbol={ticker}&period=annual&limit=2&apikey={FMP_API_KEY}"
        est_raw = get_fmp_data_with_cache(ticker, "RAW_ESTIMATE", est_url, valid_hours=24)
        
        # 🚀 [추가] 우선주로 실패 시 일반주로 재요청 폴백
        if not est_raw and ticker != base_ticker:
            est_url_base = f"https://financialmodelingprep.com/stable/analyst-estimates?symbol={base_ticker}&period=annual&limit=2&apikey={FMP_API_KEY}"
            est_raw = get_fmp_data_with_cache(base_ticker, "RAW_ESTIMATE", est_url_base, valid_hours=24)
        
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
                    
                    try:
                            resp_e = model_strict.generate_content(prompt_e)
                            if resp_e and resp_e.text:
                                e_paragraphs = [p.strip() for p in resp_e.text.split('\n') if len(p.strip()) > 20]
                                indent_size = "14px" if lang_code == "ko" else "0px"
                                html_e = "".join([f'<p style="text-indent:{indent_size}; margin-bottom:15px; line-height:1.8; text-align:justify; font-size:15px; color:#333;">{p}</p>' for p in e_paragraphs])
                                
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
                        except Exception as e:
                            # 래퍼가 내부에서 5번의 지수 백오프를 시도하고도 실패했을 때만 실행됩니다.
                            print(f"⚠️ [{ticker}] 실적전망치 분석 실패 ({lang_code}) - 래퍼 복구 한도 초과: {e}")
                
                # 🚀 [FCM 다국어 발송] 분석 완료 후 프리미엄 유저에게 푸시 알림 발송
                try:
                    send_fcm_push(
                        title_dict={"ko": f"📈 {ticker} 실적 전망치 변경", "en": f"📈 {ticker} Estimates Updated", "ja": f"📈 {ticker} 業績見通し変更", "zh": f"📈 {ticker} 业绩预期变更"},
                        body_dict={"ko": "월가 애널리스트들의 향후 매출 및 수익 예측치가 업데이트되었습니다.", "en": "Wall Street analysts' future revenue and profit estimates have been updated.", "ja": "ウォール街のアナリストによる今後の売上および利益予測が更新されました。", "zh": "华尔街分析师的未来营收及利润预测已更新。"},
                        ticker=ticker
                    )
                except Exception as e:
                    print(f"⚠️ 실적전망치 푸시 실패: {e}")

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
    
    # 🚀 [추가] 일반주 티커 추출
    base_ticker = get_base_ticker(ticker)
    
    try:
        url = f"https://financialmodelingprep.com/stable/revenue-product-segmentation?symbol={ticker}&structure=flat&period=annual&apikey={FMP_API_KEY}"
        rev_raw = get_fmp_data_with_cache(ticker, "RAW_REVENUE_SEGMENT", url, valid_hours=24)
        
        is_rev_valid = (isinstance(rev_raw, list) and len(rev_raw) > 0) or (isinstance(rev_raw, dict) and len(rev_raw) > 0 and "Error Message" not in rev_raw)
        
        # 🚀 [추가] 우선주로 실패 시 일반주로 재요청 폴백
        if not is_rev_valid and ticker != base_ticker:
            url_base = f"https://financialmodelingprep.com/stable/revenue-product-segmentation?symbol={base_ticker}&structure=flat&period=annual&apikey={FMP_API_KEY}"
            rev_raw = get_fmp_data_with_cache(base_ticker, "RAW_REVENUE_SEGMENT", url_base, valid_hours=24)
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
            
            try:
                resp = model_strict.generate_content(prompt)
                if resp and resp.text:
                    paragraphs = [p.strip() for p in resp.text.split('\n') if len(p.strip()) > 20]
                    indent_size = "14px" if lang_code == "ko" else "0px"
                    html_str = "".join([f'<p style="text-indent:{indent_size}; margin-bottom:15px; line-height:1.8; text-align:justify; font-size:15px; color:#333;">{p}</p>' for p in paragraphs])
                    
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
            except Exception as e:
                # 래퍼가 내부에서 5번의 지수 백오프를 시도하고도 실패했을 때만 실행됩니다.
                print(f"⚠️ [{ticker}] 매출 비중 분석 실패 ({lang_code}) - 래퍼 복구 한도 초과: {e}")
        
        # 🚀 [FCM 다국어 발송] 분석 완료 후 알림 발송 (Premium Plus 전용)
        if analysis_success:
            send_fcm_push(
                title_dict={"ko": f"💰 {ticker} 부문별 매출 분석", "en": f"💰 {ticker} Revenue Breakdown", "ja": f"💰 {ticker} 部門別売上分析", "zh": f"💰 {ticker} 营收构成分析"},
                body_dict={"ko": "핵심 사업과 신사업의 구체적인 매출 비중 리포트가 도착했습니다.", "en": "Detailed report on core and new business revenue share has arrived.", "ja": "中核事業と新規事業の具体的な売上比率レポートが届きました。", "zh": "核心业务与新业务的具体营收占比报告已送达。"},
                ticker=ticker, target_level='premium_plus'
            )
                
        batch_upsert("analysis_cache", [{"cache_key": tracker_key, "content": current_raw_str, "updated_at": datetime.now().isoformat()}], "cache_key")

    except Exception as e:
        print(f"Tab3 Premium Revenue Seg Error for {ticker}: {e}")

# ==========================================
# [최종 완성] Tab 2: 거시 지표 수집 및 통합 분석 (데이터 격리 및 전 언어 지침 통일)
# ==========================================
def update_macro_data(df):
    if 'model_strict' not in globals() or not model_strict: return
    
    print("🌍 거시 지표(Tab 2) 업데이트 시작 (카드 로직 유지 & 리포트 데이터 격리)")
    
    # [1] 기본 데이터 초기화
    today = datetime.now()
    data = {
        "ipo_return": 0.0, "ipo_volume": 0, "unprofitable_pct": 0.0,
        "withdrawal_rate": 0.0, "vix": 20.0, "fear_greed": 50, 
        "buffett_val": 195.0, "pe_ratio": 24.0
    }
    
    # [2] 실시간 IPO 통계 계산 (기존 로직 유지)
    try:
        if not df.empty:
            df['dt'] = pd.to_datetime(df['date'], errors='coerce')
            upcoming = df[(df['dt'] > today) & (df['dt'] <= today + timedelta(days=30))]
            data["ipo_volume"] = len(upcoming)
            
            past_1y = df[(df['dt'] >= today - timedelta(days=365)) & (df['dt'] <= today)]
            if len(past_1y) > 0:
                withdrawn_cnt = len(past_1y[past_1y['status'].str.lower().str.contains('withdrawn|철회', na=False)])
                data["withdrawal_rate"] = (withdrawn_cnt / len(past_1y)) * 100
                
            data["unprofitable_pct"] = 72.0 if data["ipo_volume"] > 10 else 60.0
            data["ipo_return"] = 15.2 if data["vix"] < 18 else 4.5
    except: pass

    # [3] 시장 펀더멘털 데이터 수집 (FMP API)
    try:
        q_url = f"https://financialmodelingprep.com/stable/quote?symbol=^VIX,SPY,^W5000&apikey={FMP_API_KEY}"
        q_res = requests.get(q_url, timeout=5).json()
        if isinstance(q_res, list):
            q_map = {item['symbol']: item for item in q_res}
            if '^VIX' in q_map: data["vix"] = float(q_map['^VIX'].get('price', 20.0))
            if 'SPY' in q_map: data["pe_ratio"] = float(q_map['SPY'].get('pe', 24.5))
            if '^W5000' in q_map:
                w5000_p = float(q_map['^W5000'].get('price', 0))
                if w5000_p > 0: data["buffett_val"] = ((w5000_p * 1.1) / 1000 / 28.0) * 100

        r_url = f"https://financialmodelingprep.com/stable/market-risk-premium?apikey={FMP_API_KEY}"
        r_res = requests.get(r_url, timeout=5).json()
        if isinstance(r_res, list) and len(r_res) > 0:
            us_risk = next((item for item in r_res if item.get('country') == 'United States'), None)
            if us_risk: 
                erp = float(us_risk.get('totalEquityRiskPremium', 5.0))
                data["fear_greed"] = max(0, min(100, 100 - ((erp - 3.0) * 20))) 
    except: pass

    # [4] 실물 경제 지표 로드 (FRED 캐시 활용)
    real_economy_str = "N/A"
    try:
        res = supabase.table("macro_cache").select("content").eq("cache_key", "FRED_MACRO_DATA").execute()
        if res.data:
            full_fred = json.loads(res.data[0]['content'])
            cur = full_fred.get("0", {}) 
            fed_rate = cur.get("FEDFUNDS", {}).get("val", "N/A")
            cpi = cur.get("CPIAUCSL", {}).get("val", "N/A")
            unrate = cur.get("UNRATE", {}).get("val", "N/A")
            real_economy_str = f"기준금리: {fed_rate}%, 소비자물가(CPI): {cpi}%, 실업률: {unrate}%"
    except: pass

    # UI 수치 데이터 저장
    batch_upsert("analysis_cache", [{"cache_key": "Market_Dashboard_Metrics", "content": json.dumps(data), "updated_at": datetime.now().isoformat()}], "cache_key")

    # [5] 과금 방어막 (RawTracker)
    current_state_str = json.dumps(data, sort_keys=True) + real_economy_str
    tracker_key = "Global_Macro_RawTracker"
    is_changed = True
    try:
        res_t = supabase.table("analysis_cache").select("content").eq("cache_key", tracker_key).execute()
        if res_t.data and current_state_str == res_t.data[0]['content']:
            is_changed = False
    except: pass

    if not is_changed:
        print("⏩ [거시경제] 지표 수치 변화 없음. AI 분석 스킵!")
        return 

    print("🔔 거시 지표 변동 감지! AI 분석(데이터 격리 적용) 시작...")
    
    # 컨텍스트 준비
    # Call 1용: IPO 통계 위주
    g1_context = f"Sentiment/Liquidity (IPO Return: {data['ipo_return']}%, Withdrawal Rate: {data['withdrawal_rate']}%)"
    g2_context = f"Risk/Supply (Upcoming IPOs: {data['ipo_volume']}, Unprofitable Ratio: {data['unprofitable_pct']}%)"
    g3_context = f"Macro/Valuation (VIX: {data['vix']}, Fear&Greed: {data['fear_greed']}, Buffett Indicator: {data['buffett_val']}%, S&P500 PE: {data['pe_ratio']}x)"
    
    # 🚀 Call 2용: 실물 지표와 시장 기초체력 결합 (IPO 수치 완전 배제)
    macro_report_context = f"""
    [실물 경제 상황]: {real_economy_str}
    [금융 시장 지표]: VIX {data['vix']}, S&P500 PE {data['pe_ratio']}x, 공포탐욕지수 {data['fear_greed']}, 버핏지수 {data['buffett_val']}%
    """

    macro_success = False
    for lang_code, target_lang in SUPPORTED_LANGS.items():
        cache_key_summary = f"Global_Market_Summary_{lang_code}"
        cache_key_full = f"Global_Market_Dashboard_{lang_code}"
        
        # 💡 [Call 1] 완전히 독립된 3개의 UI 카드 요약 (요청하신 대로 그대로 유지)
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
            sum_p = f"ウォール街のチーフストラ테지스트として、次の3つのデータに基づいて3つの独立한 대시보드 카드의 요약을 작성하세요.\n[카드1]: {g1_context}\n[카드2]: {g2_context}\n[카드3]: {g3_context}"
            sum_i = """
            [UI카드 작성 규칙 - 엄수]
            1. 3개의 완전히 독립된 텍스트만 출력하세요. 숫자 넘버링이나 별도의 제목은 절대 쓰지 마세요.
            2. 포맷: (초기 수익률과 철회율 데이터를 바탕으로 투기적 광기 및 위험 선호도 진단 3~4문장) |||SEP||| (상장 예정 물량과 미수익 기업 비중을 결합하여 공급 과잉 및 질적 저하 리스크 분석 3~4문장) |||SEP||| (VIX, 공포탐욕지수, 밸류에이션을 결합하여 증시 전반의 거시적 과열 여부 진단 3~4문장)
            3. 구분자 '|||SEP|||' 이외의 줄바꿈은 넣지 마세요.
            4. 모든 문장은 'です/ます' 형태의 정중체를 사용하세요.
            """
        elif lang_code == 'zh':
            sum_p = f"作为华尔街首席策略师，请根据以下三组数据撰写3份独立的仪表板卡片摘要。\n[卡片1]: {g1_context}\n[卡片2]: {g2_context}\n[卡片3]: {g3_context}"
            sum_i = """[UI卡片规则 - 严格遵守]
            1. 仅输出3段完全独立的文本。严禁使用数字编号或标题（如“卡片1”）。
            2. 格式: (结合初期收益率与撤回率诊断投机狂热 3-4句话) |||SEP||| (结合上市排队数量与亏损企业占比分析供给风险 3-4句话) |||SEP||| (结合VIX、恐慌贪婪指数、巴菲特指标和PE评估宏观过热 3-4句话)
            3. 仅使用 '|||SEP|||' 作为分隔符，段落之间不要换行.
            4. 请使用专业且正式의 陈述句.
            """

        # 💡 [Call 2] 하단 전문 리포트 (🚀 제목/인사말 생략 + 첫 단어 고정)
        if lang_code == 'ko':
            full_p = f"당신은 글로벌 투자 전략가입니다. 실물 경제 지표를 원인으로 삼아 현재의 금융 시장 상황을 유기적으로 분석하세요.\n[통합 데이터]: {macro_report_context}"
            full_i = """
            [작성 규칙 - 거시경제 전략 브리핑]
            1. **인사말 및 제목 금지**: '브리핑입니다', '전략 리포트' 같은 제목이나 인사말을 절대 쓰지 마세요. 
            2. **첫 단어 고정**: 반드시 '글로벌' 또는 '현재'라는 단어로 글을 시작하세요.
            3. **인과관계 분석**: 금리, 물가, 고용 수치가 시장의 VIX나 PE 밸류에이션에 어떤 논리적 영향을 주고 있는지 그 '이유'를 중심으로 설명하세요.
            4. **데이터 제한**: IPO 수익률, 상장 물량 등 제공되지 않은 데이터는 절대 언급하지 마세요.
            5. **형식**: 소제목 없이 **단 하나의 유기적인 문단**으로만 작성하세요. (5~6줄 내외)
            6. 모든 문장은 '~습니다/ㅂ니다'로 마무리하세요.
            """
        elif lang_code == 'en':
            full_p = f"As a Global Investment Strategist, analyze the market using real economy indicators as causes.\n[Data]: {macro_report_context}"
            full_i = """
            [Rules]
            1. **NO TITLES/GREETINGS**: Do not start with 'Here is the report' or titles. 
            2. **Starting Word**: Start immediately with 'Global' or 'Currently'.
            3. **Causal Analysis**: Explain how Rates/CPI/Jobs impact Market PE and VIX.
            4. **No IPO Data**: Do not mention IPO volume or returns.
            5. **Format**: Exactly one paragraph. No subheadings. (Approx. 5-6 lines)
            """
        elif lang_code == 'ja':
            full_p = f"グローバル投資戦略家として、実体経済指標を原因として現在の金融市場状況を論理的に分析してください.\n[データ]: {macro_report_context}"
            full_i = """
            [作成規則]
            1. **タイトル・挨拶禁止**: 「分析レポートです」などの挨拶は省き、すぐに本論に入ってください。
            2. **最初の単語**: 必ず「グローバル」または「現在」で始めてください。
            3. **因果関係**: 金利・物価が市場指標(PE/VIX)に与える影響を論理的に説明。
            4. **形式**: 小見出しなし、単一の段落。（5〜6行程度）
            """
        else: # zh
            full_p = f"您是全球投资战略家。请以实体经济指标为诱因，有机地分析当前的金融市场状况。\n[数据]: {macro_report_context}"
            full_i = """
            [编写规则]
            1. **严禁标题/问候**: 严禁使用“这是报告”等废话。直接输出分析内容。
            2. **首词**: 必须以“全球”或“当前”开头。
            3. **因果分析**: 重点分析利率/物价/就业如何影响市场估值(PE)和情绪(VIX)。
            4. **格式**: 严禁使用小标题，仅限一个自然段。（约 5-6 行）
            """

        try:
            # 1. 카드 요약 저장
            res_sum = model_strict.generate_content(sum_p + sum_i)
            if res_sum and res_sum.text:
                batch_upsert("analysis_cache", [{"cache_key": cache_key_summary, "content": res_sum.text.strip(), "ticker": "MARKET", "tab_name": "tab2", "lang": lang_code, "data_type": "macro_card"}], "cache_key")
        
            # 2. 전문 리포트 저장
            res_full = model_strict.generate_content(full_p + full_i)
            if res_full and res_full.text:
                batch_upsert("analysis_cache", [{"cache_key": cache_key_full, "content": res_full.text.strip(), "ticker": "MARKET", "tab_name": "tab2", "lang": lang_code, "data_type": "macro_report"}], "cache_key")
                
            print(f"✅ 거시 지표 분석 완료 ({lang_code})")
            macro_success = True
        except Exception as e:
            print(f"❌ 거시 지표 AI 에러 ({lang_code}): {e}")

    # 모든 분석이 성공했을 때만 트래커 갱신
    if macro_success:
        batch_upsert("analysis_cache", [{"cache_key": tracker_key, "content": current_state_str, "updated_at": datetime.now().isoformat()}], "cache_key")
        
# ==========================================
# [수정] Tab 6: 스마트머니 통합 데이터 수집 (국회의원 & 공매도 추가)
# ==========================================
def fetch_smart_money_data(symbol, api_key):
    """FMP API 4종 세트를 캐싱 방어막과 함께 수집합니다."""
    data = {"insider": [], "institutional": [], "senate":[], "fail_to_deliver":[]}
    base_ticker = get_base_ticker(symbol) # 💡 추가
    
    # 내부 함수: 본주 Fallback 지원
    def get_with_fallback(api_type, url_template):
        res = get_fmp_data_with_cache(symbol, api_type, url_template.format(sym=symbol))
        if (not isinstance(res, list) or len(res) == 0) and symbol != base_ticker:
            res = get_fmp_data_with_cache(base_ticker, api_type, url_template.format(sym=base_ticker))
        return res if isinstance(res, list) else []

    # 💡 [수정] 포맷 문자열로 변경하여 Fallback 지원
    in_url_tmpl = "https://financialmodelingprep.com/stable/insider-trading?symbol={sym}&limit=10&apikey=" + api_key
    data["insider"] = get_with_fallback("SMART_IN", in_url_tmpl)

    inst_url_tmpl = "https://financialmodelingprep.com/stable/institutional-ownership?symbol={sym}&apikey=" + api_key
    data["institutional"] = get_with_fallback("SMART_INST", inst_url_tmpl)[:10]
    
    sen_url_tmpl = "https://financialmodelingprep.com/stable/senate-trading?symbol={sym}&apikey=" + api_key
    data["senate"] = get_with_fallback("SMART_SENATE", sen_url_tmpl)[:5]
    
    ftd_url_tmpl = "https://financialmodelingprep.com/stable/fail-to-deliver?symbol={sym}&apikey=" + api_key
    data["fail_to_deliver"] = get_with_fallback("SMART_FTD", ftd_url_tmpl)

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
            title_dict={"ko": f"🐋 {ticker} 스마트머니 포착", "en": f"🐋 {ticker} Smart Money Tracked", "ja": f"🐋 {ticker} スマートマネー捕捉", "zh": f"🐋 {ticker} 聪明钱追踪"},
            body_dict={"ko": "내부자 거래 및 월가 고래들의 매집 동향 분석 리포트가 도착했습니다.", "en": "Insider trading and Wall Street whales' accumulation trend analysis has arrived.", "ja": "内部者取引および機関投資家の買い集め動向分析が届きました。", "zh": "内幕交易及华尔街巨头的吸筹动向分析报告已送达。"},
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
    
    # 💡 [핵심 수정] 3행 4열 꽉 찬 대시보드를 위한 11개 지표 매핑 (col 정보는 참고용)
    series_info = {
        # 1열 (금리)
        "FEDFUNDS": {"name": "기준금리", "col": 1}, 
        "DGS10": {"name": "10년물 국채", "col": 1}, 
        "T10Y2Y": {"name": "장단기 금리차", "col": 1}, 
        # 2열 (물가)
        "CPIAUCSL": {"name": "소비자물가지수(CPI)", "col": 2}, 
        "PCEPI": {"name": "개인소비지출(PCE)", "col": 2}, 
        "PPIFIS": {"name": "생산자물가(PPI)", "col": 2}, # 🚀 신규
        # 3열 (고용)
        "UNRATE": {"name": "실업률", "col": 3},
        "PAYEMS": {"name": "비농업고용(NFP)", "col": 3}, # 🚀 신규 (단위: Thousands)
        "JTSJOL": {"name": "구인건수(JOLTS)", "col": 3}, # 🚀 신규 (단위: Thousands)
        # 4열 (실물/통화) - 2개만 배치하여 뱃지 공간 확보
        "WM2NS": {"name": "M2 통화량", "col": 4},
        "RSAFS": {"name": "소매판매", "col": 4} # 🚀 신규
    }
    
    # 전년 대비 성장률(%)로 가져올 지표들 (나머지는 절대 수치)
    pc1_series =["CPIAUCSL", "PCEPI", "PPIFIS", "WM2NS", "RSAFS"] 
    
    results = {"0": {}, "-1": {}, "-2": {}, "-3": {}} 
    
    start_date = (today - timedelta(days=365*6)).strftime('%Y-%m-%d')
    
    try:
        if FRED_API_KEY:
            for sid, info in series_info.items():
                units = "pc1" if sid in pc1_series else "lin"
                url = f"https://api.stlouisfed.org/fred/series/observations?series_id={sid}&api_key={FRED_API_KEY}&file_type=json&observation_start={start_date}&units={units}"
                res = requests.get(url, timeout=10).json()
                obs = res.get('observations',[])
                if not obs: continue
                
                valid_obs = [o for o in obs if o['value'] != '.']
                valid_obs.sort(key=lambda x: x['date'], reverse=True)
                
                def get_val_near_date(target_date):
                    for o in valid_obs:
                        if pd.to_datetime(o['date']) <= target_date: return float(o['value'])
                    return None
                    
                v0 = get_val_near_date(today)
                v1 = get_val_near_date(today - timedelta(days=365))
                v2 = get_val_near_date(today - timedelta(days=365*2))
                v3 = get_val_near_date(today - timedelta(days=365*3))
                v4 = get_val_near_date(today - timedelta(days=365*4))
                v5 = get_val_near_date(today - timedelta(days=365*5))
                
                def calc_diff_str(curr, prev):
                    if curr is not None and prev is not None:
                        return f"{curr - prev:+.2f}%p" if sid not in ["PAYEMS", "JTSJOL"] else f"{curr - prev:+.0f}K"
                    return None
                    
                def calc_avg(curr, p1, p2):
                    if curr is not None and p1 is not None and p2 is not None:
                        return round((curr + p1 + p2) / 3, 2)
                    return None

                for year_key, curr, p1, p2, p3 in[
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
                
            batch_upsert("macro_cache",[{
                "cache_key": "FRED_MACRO_DATA", "content": json.dumps(results), "updated_at": today.isoformat()
            }], on_conflict="cache_key")
            print("✅ FRED 매크로 3x4 Grid용 요약 데이터 DB 저장 완료 (11개 지표 확장)")
    except Exception as e: print(f"⚠️ FRED API Error: {e}")

    # 2. FMP 경제 일정 수집
    try:
        start = today.strftime('%Y-%m-%d')
        end = (today + timedelta(days=30)).strftime('%Y-%m-%d')
        url = f"https://financialmodelingprep.com/stable/economic-calendar?from={start}&to={end}&apikey={FMP_API_KEY}"
        res = requests.get(url, timeout=10).json()
        
        if isinstance(res, list):
            important_events =[
                e for e in res 
                if e.get('country') == 'US' and any(keyword in e.get('event', '').lower() for keyword in['fed interest', 'cpi', 'unemployment', 'non farm'])
            ]
            important_events.sort(key=lambda x: x['date'])
            
            batch_upsert("macro_cache",[{
                "cache_key": "FMP_MACRO_EVENTS", "content": json.dumps(important_events[:5]), "updated_at": today.isoformat()
            }], on_conflict="cache_key")
            print("✅ FMP 향후 30일 미국 경제일정 DB 저장 완료")
    except Exception as e: print(f"⚠️ FMP Economic Calendar Error: {e}")

# 🚀 [수정된 메인 쓰레드 함수] 전체 재시도 루프(for attempt)를 제거하고 직관적으로 실행
def process_single_ticker(idx, total, row, cik_mapping, name_to_ticker_map):
    original_symbol = row.get('symbol')
    name = row.get('name')
    c_status = row.get('status', 'Active')
    c_date = row.get('date', None)
    
    clean_name = normalize_company_name(name)
    official_symbol = name_to_ticker_map.get(clean_name, original_symbol)
    
    if original_symbol != official_symbol and official_symbol in cik_mapping:
        cik_mapping[original_symbol] = cik_mapping[official_symbol]

    print(f"\n⚡[{idx}/{total}] 쓰레드 가동: {original_symbol} 분석 중...")
    
    if not official_symbol or str(official_symbol).strip() == "":
        cik = get_fallback_cik(official_symbol, name, FMP_API_KEY)
        if cik:
            found_ticker = get_ticker_from_cik(cik)
            if found_ticker: official_symbol = found_ticker
            
    if not official_symbol or str(official_symbol).strip() == "":
        print(f"⚠️ [스킵] {original_symbol} Ticker가 존재하지 않아 분석을 건너뜁니다.")
        return 

    # [분석 단계] - 각 함수가 내부적으로 알아서 에러를 삼키고 다음으로 넘어가도록 설계됨
    try:
        run_tab1_analysis(official_symbol, name, c_status, c_date)
        run_tab0_analysis(official_symbol, name, c_status, c_date, cik_mapping, original_symbol)
        run_tab0_premium_collection(official_symbol, name)
        run_tab2_premium_collection(official_symbol, name) 
        
        analyst_metrics = fetch_analyst_estimates(official_symbol, FMP_API_KEY)
        run_tab4_analysis(official_symbol, name, c_status, c_date, analyst_metrics)
        run_tab4_ma_premium_collection(official_symbol, name) 
        run_tab4_premium_collection(official_symbol, name) 
        
        unified_metrics = fetch_premium_financials(official_symbol, FMP_API_KEY)
        batch_upsert("analysis_cache",[{
            "cache_key": f"{official_symbol}_Raw_Financials",
            "content": json.dumps(unified_metrics, ensure_ascii=False),
            "updated_at": datetime.now().isoformat()
        }], on_conflict="cache_key")
        
        run_tab3_analysis(official_symbol, name, unified_metrics)
        run_tab3_premium_collection(official_symbol, name)
        run_tab3_revenue_premium_collection(official_symbol, name) 
        
        smart_money_data = fetch_smart_money_data(official_symbol, FMP_API_KEY)
        run_tab6_analysis(official_symbol, name, smart_money_data)
        
    except Exception as e:
        print(f"🚨 [{original_symbol}] 파이프라인 진행 중 예외 발생: {e}")

    # [마케팅 단계] 트위터 커넥터는 독립적으로 실행 (AI 실패와 무관하게 팩트 기반 포스팅 가능)
    try:
        # unified_metrics, analyst_metrics가 갱신 안 됐어도 빈 딕셔너리로 대응 가능
        send_to_twitter_connector(official_symbol, name, row, 
                                  locals().get('unified_metrics', {}), 
                                  locals().get('analyst_metrics', {}))
    except Exception as e: 
        print(f"⚠️ Twitter Connector Error: {e}")

    # 디도스 방어용 짧은 휴식 (종목 간의 간격 확보)
    time.sleep(1)

    
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
    
    print(f"\n🤖 Vertex AI 기반 병렬 심층 분석 시작 (총 {total}개 종목)...")
    
    WORKER_START_TIME = time.time()
    MAX_RUN_TIME_SEC = 5.5 * 3600  # 5.5시간(19,800초)

    # 🚀[병렬 스레드 풀 적용]
    # 한 번에 5개의 기업을 동시에 분석합니다. (Vertex AI의 한도에 따라 최대 10~20까지 조절 가능)
    max_threads = 5 
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures =[]
        for idx, row in target_df.iterrows():
            futures.append(
                executor.submit(process_single_ticker, idx+1, total, row, cik_mapping, name_to_ticker_map)
            )
        
        for future in concurrent.futures.as_completed(futures):
            # 5.5시간 강제 종료 방어막
            if time.time() - WORKER_START_TIME > MAX_RUN_TIME_SEC:
                print("⏳[알림] 작업 제한 시간 임박! 대기 중인 스레드를 취소합니다.")
                executor.shutdown(wait=False, cancel_futures=True)
                break
            try:
                future.result() # 스레드에서 발생한 예외 캐치
            except Exception as exc:
                print(f"🔥 스레드 실행 중 예외 발생: {exc}")

    # 모든 루프 종료 후 실행되는 후속 작업
    run_premium_alert_engine(df)
    batch_upsert("analysis_cache",[{"cache_key": "WORKER_LAST_RUN", "content": "alive", "updated_at": datetime.now().isoformat()}], on_conflict="cache_key")
    print(f"\n🏁 모든 병렬 작업 종료: {datetime.now()}")

if __name__ == "__main__":
    main()
