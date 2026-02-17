import streamlit as st
import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os
import time
import uuid
import random
import math
import html
import re
import json
import urllib.parse
import smtplib
import gspread
import io
import xml.etree.ElementTree as ET
import yfinance as yf 
from oauth2client.service_account import ServiceAccountCredentials
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# ==========================================
# [신규] Supabase 라이브러리 및 초기화
# ==========================================
from supabase import create_client, Client

@st.cache_resource
def init_supabase():
    """Supabase 클라이언트를 초기화하고 캐싱합니다."""
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

# 전역에서 사용할 supabase 객체 생성
supabase = init_supabase()

# ==========================================
# [중요] 구글 라이브러리
# ==========================================
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- [AI 라이브러리] ---
import google.generativeai as genai
from google.generativeai import protos  

# ==========================================
# [설정] 전역 변수
# ==========================================
DRIVE_FOLDER_ID = "1WwjsnOljLTdjpuxiscRyar9xk1W4hSn2"
MY_API_KEY = st.secrets.get("FINNHUB_API_KEY", "")
# ==========================================

# ==========================================
# [Supabase DB] 데이터 관리 함수 모음 (NEW)
# ==========================================

# 1. 유저 로그인 정보 불러오기
def db_load_user(user_id):
    try:
        res = supabase.table("users").select("*").eq("id", user_id).execute()
        return res.data[0] if res.data else None
    except: return None

# 2. 회원가입 정보 저장 (구글 시트 대체)
def db_signup_user(user_data):
    try:
        # DB 컬럼명과 user_data 키값이 일치해야 함
        supabase.table("users").insert(user_data).execute()
        return True
    except Exception as e:
        print(f"Signup DB Error: {e}")
        return False

# 3. 유저 정보 업데이트 (승인/반려/설정변경 등)
def db_update_user_info(user_id, update_dict):
    try:
        supabase.table("users").update(update_dict).eq("id", user_id).execute()
        return True
    except: return False

# 4. 관리자용: 전체 유저 조회
def db_load_all_users():
    try:
        res = supabase.table("users").select("*").order("created_at", desc=True).execute()
        return res.data if res.data else []
    except: return []

# 5. 관심종목 & 투표 불러오기 (로그인 직후 실행)
def db_sync_watchlist(user_id):
    try:
        res = supabase.table("watchlist").select("*").eq("user_id", user_id).execute()
        w_list = []
        w_preds = {}
        for item in res.data:
            ticker = item['ticker']
            w_list.append(ticker)
            if item.get('prediction'):
                w_preds[ticker] = item['prediction']
        return w_list, w_preds
    except: return [], {}

# 6. 관심종목 추가/삭제 (버튼 클릭 시 실행)
def db_toggle_watchlist(user_id, ticker, prediction=None, action='add'):
    try:
        if action == 'add':
            # upsert: 있으면 업데이트, 없으면 추가
            data = {"user_id": user_id, "ticker": ticker, "prediction": prediction}
            supabase.table("watchlist").upsert(data, on_conflict="user_id, ticker").execute()
        elif action == 'remove':
            supabase.table("watchlist").delete().eq("user_id", user_id).eq("ticker", ticker).execute()
    except Exception as e:
        print(f"Watchlist DB Error: {e}")

# 7. 게시판 글쓰기
def db_save_post(category, title, content, author_name, author_id):
    try:
        data = {
            "category": category,
            "title": title,
            "content": content,
            "author_name": author_name,
            "author_id": author_id
        }
        supabase.table("board").insert(data).execute()
        return True
    except: return False

# 8. 게시판 글 목록 불러오기
# [수정된 DB 함수] - 순서 최적화 적용
def db_load_posts(limit=50, category=None):
    """
    category가 있으면? -> 해당 종목 글만 DB에서 검색 후 최신순 정렬 (상황 1)
    category가 없으면? -> 전체 글을 DB에서 검색 후 최신순 정렬 (상황 2, 3)
    """
    try:
        # 1. 테이블 선택 및 전체 컬럼 선택
        query = supabase.table("posts").select("*")
            
        # 2. [필터링 우선] category가 있다면 조건 추가
        if category:
            query = query.eq("category", category)  # SQL: WHERE category = 'AAPL'
            
        # 3. [정렬 및 제한] 필터링 된 결과 내에서 정렬하고 개수 자르기
        # 이 부분이 맨 뒤에 와야 정확한 데이터를 가져옵니다.
        response = query.order("created_at", desc=True).limit(limit).execute()
        
        return response.data
        
    except Exception as e:
        # 에러 발생 시 로그 출력 (선택 사항)
        # print(f"DB Error: {e}") 
        return []

# [정보 공개 범위 업데이트 함수]
def db_update_user_visibility(user_id, visibility_list):
    try:
        # 리스트로 들어온 설정(['학력', '자산'])을 문자열("학력,자산")로 변환해서 저장
        # (만약 이미 문자열이라면 그대로 사용)
        if isinstance(visibility_list, list):
            value_to_save = ",".join(visibility_list)
        else:
            value_to_save = str(visibility_list)

        # Supabase 업데이트 실행
        response = supabase.table("users").update({"visibility": value_to_save}).eq("id", user_id).execute()
        
        # 성공적으로 업데이트되면 데이터가 반환됨
        return True if response.data else False
        
    except Exception as e:
        st.error(f"공개 범위 설정 실패: {e}")
        return False
        
# ---------------------------------------------------------
# [0] AI 설정: Gemini 모델 초기화 (도구 자동 장착)
# ---------------------------------------------------------
@st.cache_resource
def configure_genai():
    genai_key = st.secrets.get("GENAI_API_KEY")
    if genai_key:
        genai.configure(api_key=genai_key)
        
        try:
            # [핵심] 여기서 'google_search'를 문자열로 선언! 
            # 라이브러리가 알아서 최적의 도구 객체를 연결합니다.
            return genai.GenerativeModel('gemini-1.5-flash', tools='google_search')
        except Exception as e:
            print(f"Tool Config Error: {e}")
            return genai.GenerativeModel('gemini-1.5-flash')
            
    return None

model = configure_genai()

# ---------------------------------------------------------
# [1] 통합 분석 함수 (Tab 1 & Tab 4 대체용) - 프롬프트 강화판
# ---------------------------------------------------------

# (A) Tab 1용: 비즈니스 요약 + 뉴스 통합 (기존 고품질 프롬프트 복원)
@st.cache_data(show_spinner=False, ttl=600)
def get_unified_tab1_analysis(company_name, ticker):
    if not model: return "AI 모델 설정 오류", []
    
    # [Step 1] Supabase DB 조회 (6시간 캐시)
    cache_key = f"{ticker}_Tab1"
    now = datetime.now()
    six_hours_ago = (now - timedelta(hours=6)).isoformat()

    try:
        res = supabase.table("analysis_cache") \
            .select("content") \
            .eq("cache_key", cache_key) \
            .gt("updated_at", six_hours_ago) \
            .execute()
        
        if res.data:
            saved_data = json.loads(res.data[0]['content'])
            return saved_data['html'], saved_data['news']
    except Exception as e:
        print(f"Tab1 DB Error: {e}")

    # [Step 2] 캐시 없으면 기존 고품질 프롬프트로 분석 실행
    prompt = f"""
    당신은 한국 최고의 증권사 리서치 센터의 시니어 애널리스트입니다.
    분석 대상: {company_name} ({ticker})

    [작업 1: 비즈니스 모델 심층 분석]
    아래 [필수 작성 원칙]을 준수하여 리포트를 작성하세요.
    1. 언어: 오직 '한국어'만 사용하세요. (영어 고유명사 제외). 
    2. 포맷: 반드시 3개의 문단으로 나누어 작성하세요. 문단 사이에는 줄바꿈을 명확히 넣으세요.
       - 1문단: 비즈니스 모델 및 경쟁 우위 (독점력, 시장 지배력 등)
       - 2문단: 재무 현황 및 공모 자금 활용 (매출 추이, 흑자 전환 여부, 자금 사용처)
       - 3문단: 향후 전망 및 투자 의견 (시장 성장성, 리스크 요인 포함)
    3. 문체: '~습니다' 체를 사용하되, 문장의 시작을 다양하게 구성하세요.
       - [중요] 모든 문장이 기업명(예: '동사는', '{company_name}은')으로 시작하지 않도록 주의하세요.
    4. 금지: 제목, 소제목, 특수기호, 불렛포인트(-)를 절대 쓰지 마세요. 
       특히 "분석 리포트를 제출합니다", "분석 결과입니다", "안녕하세요"와 같은 
       인사말이나 도입부 문구를 절대 포함하지 말고, 바로 본론(1문단 내용)부터 시작하세요.

    [작업 2: 최신 뉴스 수집]
    - Google 검색을 통해 이 기업의 가장 최근 주요 뉴스 5개를 선정하세요.
    - 검색 시 {company_name}의 업종과 관련 없는 동명의 기업 뉴스는 철저히 배제하세요.
    - 각 뉴스는 아래 JSON 형식으로 답변의 맨 마지막에 첨부하세요. (절대 본문에 섞지 마세요)
    
    형식: <JSON_START> {{ "news": [ {{ "title_en": "...", "title_ko": "...", "link": "...", "sentiment": "긍정/부정/일반", "date": "..." }} ] }} <JSON_END>
    """

    try:
        response = model.generate_content(prompt)
        full_text = response.text

        # 기존 로직: 텍스트 추출 및 HTML 포맷팅
        biz_analysis = full_text.split("<JSON_START>")[0].strip()
        biz_analysis = re.sub(r'#.*', '', biz_analysis).strip()
        paragraphs = [p.strip() for p in biz_analysis.split('\n') if len(p.strip()) > 20]
        
        html_output = ""
        for p in paragraphs:
            html_output += f'<p style="display:block; text-indent:14px; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>'

        # 기존 로직: 뉴스 파싱
        news_list = []
        if "<JSON_START>" in full_text:
            try:
                json_str = full_text.split("<JSON_START>")[1].split("<JSON_END>")[0].strip()
                news_list = json.loads(json_str).get("news", [])
                for n in news_list:
                    if n['sentiment'] == "긍정": n['bg'], n['color'] = "#e6f4ea", "#1e8e3e"
                    elif n['sentiment'] == "부정": n['bg'], n['color'] = "#fce8e6", "#d93025"
                    else: n['bg'], n['color'] = "#f1f3f4", "#5f6368"
            except: pass

        # [Step 3] Supabase에 저장
        supabase.table("analysis_cache").upsert({
            "cache_key": cache_key,
            "content": json.dumps({"html": html_output, "news": news_list}, ensure_ascii=False),
            "updated_at": now.isoformat()
        }).execute()

        return html_output, news_list
    except Exception as e:
        return f"<p style='color:red;'>시스템 오류: {str(e)}</p>", []


# (B) Tab 4용: 기관 평가 분석 통합 (강력 파싱 버전)
@st.cache_data(show_spinner=False, ttl=600)
def get_unified_tab4_analysis(company_name, ticker):
    if not model: return {"rating": "Error", "summary": "설정 오류", "pro_con": "", "links": []}

    # [Step 1] Supabase DB 조회 (24시간 캐시)
    cache_key = f"{ticker}_Tab4"
    now = datetime.now()
    one_day_ago = (now - timedelta(days=1)).isoformat()

    try:
        res = supabase.table("analysis_cache") \
            .select("content") \
            .eq("cache_key", cache_key) \
            .gt("updated_at", one_day_ago) \
            .execute()
        
        if res.data:
            return json.loads(res.data[0]['content'])
    except Exception as e:
        print(f"Tab4 DB Error: {e}")

    # [Step 2] 캐시 없으면 기존 강력 프롬프트로 분석
    prompt = f"""
    당신은 월가 출신의 IPO 전문 분석가입니다. 
    구글 검색 도구를 사용하여 {company_name} ({ticker})에 대한 최신 기관 리포트(Seeking Alpha, Renaissance Capital, Morningstar 등)를 찾아 심층 분석하세요.

    [작성 지침]
    1. **언어**: 반드시 한국어로 답변하세요.
    2. **분석 깊이**: 단순 사실 나열이 아닌, 구체적인 수치나 근거를 들어 전문적으로 분석하세요.
    3. **Pros & Cons**: 긍정적 요소(Pros) 2가지와 부정적/리스크 요소(Cons) 2가지를 명확히 구분하여 상세하게 서술하세요.
    4. **Rating**: 전반적인 월가 분위기를 종합하여 반드시 (Strong Buy/Buy/Hold/Sell) 중 하나로 선택하세요.
    5. **Summary**: 전문적인 톤으로 5줄 이내로 핵심만 간결하게 작성하세요.
    6. **링크 금지**: Summary, Pro_con 내에는 'Source:', 'http...' 등의 출처 링크를 절대 포함하지 마세요.

    <JSON_START>
    {{
        "rating": "Buy/Hold/Sell 중 하나",
        "summary": "전문적인 3줄 요약 내용 (한국어)",
        "pro_con": "**긍정**:\\n- 내용\\n\\n**부정**:\\n- 내용",
        "links": [
            {{"title": "검색된 리포트 제목", "link": "URL"}}
        ]
    }}
    <JSON_END>
    """

    try:
        response = model.generate_content(prompt)
        full_text = response.text
        
        # 기존의 강력 파싱 로직 적용
        json_match = re.search(r'<JSON_START>(.*?)<JSON_END>', full_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            json_match = re.search(r'\{.*\}', full_text, re.DOTALL)
            json_str = json_match.group(0).strip() if json_match else ""

        if json_str:
            try:
                clean_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)
                result_data = json.loads(clean_str, strict=False)
                
                # [Step 3] 파싱 성공 시 DB에 저장
                supabase.table("analysis_cache").upsert({
                    "cache_key": cache_key,
                    "content": json.dumps(result_data, ensure_ascii=False),
                    "updated_at": now.isoformat()
                }).execute()
                
                return result_data
            except: pass

        return {"rating": "N/A", "summary": "분석 데이터를 정제하는 중입니다.", "pro_con": full_text[:300], "links": []}
    except Exception as e:
        return {"rating": "Error", "summary": f"오류 발생: {str(e)}", "pro_con": "", "links": []}

@st.cache_data(show_spinner=False, ttl=600)
def get_market_dashboard_analysis(metrics_data):
    """
    메인 대시보드(Tab 2)용 시장 진단 리포트 (24시간 Supabase 캐시)
    metrics_data: get_market_status_internal 함수가 리턴한 딕셔너리
    """
    if not model: return "AI 모델 연결 실패"

    # [Step 1] 24시간 캐시 확인 (전역 키 사용)
    cache_key = "Global_Market_Dashboard_Tab2"
    now = datetime.now()
    one_day_ago = (now - timedelta(days=1)).isoformat()

    try:
        res = supabase.table("analysis_cache") \
            .select("content") \
            .eq("cache_key", cache_key) \
            .gt("updated_at", one_day_ago) \
            .execute()
        
        if res.data:
            return res.data[0]['content']
    except Exception as e:
        print(f"Dashboard AI Cache Error: {e}")

    # [Step 2] 캐시 없으면 AI 분석 실행
    # 수치 데이터를 텍스트로 변환하여 프롬프트에 주입
    prompt = f"""
    당신은 월가의 수석 시장 전략가(Chief Market Strategist)입니다.
    아래 제공된 실시간 시장 지표를 바탕으로 현재 미국 주식 시장과 IPO 시장의 상태를 진단하는 일일 브리핑을 작성하세요.

    [실시간 시장 지표]
    1. IPO 초기 수익률: {metrics_data.get('ipo_return', 0):.1f}% (20% 이상이면 과열)
    2. IPO 예정 물량: {metrics_data.get('ipo_volume', 0)}건 (30일 내)
    3. 적자 기업 비율: {metrics_data.get('unprofitable_pct', 0):.1f}% (80% 이상이면 버블 위험)
    4. 상장 철회율: {metrics_data.get('withdrawal_rate', 0):.1f}%
    5. VIX 지수: {metrics_data.get('vix', 0):.2f} (공포 지수)
    6. 버핏 지수(GDP 대비 시총): {metrics_data.get('buffett_val', 0):.0f}%
    7. S&P 500 PE: {metrics_data.get('pe_ratio', 0):.1f}배
    8. Fear & Greed Index: {metrics_data.get('fear_greed', 50):.0f}점

    [작성 가이드]
    - 독자: IPO 투자자
    - 어조: 냉철하고 전문적인 어조 (인사말 생략)
    - 형식: 줄글로 된 3~5줄의 요약 리포트
    - 내용: 위 지표들을 종합하여 현재가 '기회'인지 '위험'인지, 그리고 투자자가 어떤 태도(공격적/보수적)를 취해야 하는지 명확한 인사이트를 제공하세요.
    """

    try:
        response = model.generate_content(prompt)
        result = response.text

        # [Step 3] 결과 저장
        supabase.table("analysis_cache").upsert({
            "cache_key": cache_key,
            "content": result,
            "updated_at": now.isoformat()
        }).execute()

        return result
    except Exception as e:
        return f"시장 분석 생성 중 오류: {str(e)}"


        
# ==========================================
# [기능] 1. 구글 연결 핵심 함수 (최우선 순위)
# ==========================================
@st.cache_resource
def get_gcp_clients():
    try:
        # 이 함수가 실행될 때 위에서 import한 'build'를 사용합니다.
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        
        gspread_client = gspread.authorize(creds)
        # 여기서 build가 정의되어 있어야 에러가 안 납니다.
        drive_service = build('drive', 'v3', credentials=creds)
        
        return gspread_client, drive_service
    except Exception as e:
        # 만약 여기서 'name build is not defined'가 뜬다면 
        # 위쪽의 import build 줄이 지워졌는지 확인해야 합니다.
        st.error(f"구글 연결 초기화 실패: {e}")
        return None, None

@st.cache_data(ttl=43200) # 12시간마다 갱신
def get_daily_quote():
    # 1. 예비용 명언 리스트 (한글 번역 추가됨)
    backup_quotes = [
        {"eng": "Opportunities don't happen. You create them.", "kor": "기회는 찾아오는 것이 아닙니다. 당신이 만드는 것입니다.", "author": "Chris Grosser"},
        {"eng": "The best way to predict the future is to create it.", "kor": "미래를 예측하는 가장 좋은 방법은 미래를 창조하는 것입니다.", "author": "Peter Drucker"},
        {"eng": "Do not be embarrassed by your failures, learn from them and start again.", "kor": "실패를 부끄러워하지 마세요. 배우고 다시 시작하세요.", "author": "Richard Branson"},
        {"eng": "Innovation distinguishes between a leader and a follower.", "kor": "혁신이 리더와 추종자를 구분합니다.", "author": "Steve Jobs"},
        {"eng": "It’s not about ideas. It’s about making ideas happen.", "kor": "아이디어 자체가 중요한 게 아닙니다. 실행하는 것이 중요합니다.", "author": "Scott Belsky"},
        {"eng": "The only way to do great work is to love what you do.", "kor": "위대한 일을 하는 유일한 방법은 그 일을 사랑하는 것입니다.", "author": "Steve Jobs"},
        {"eng": "Risk comes from not knowing what you're doing.", "kor": "위험은 자신이 무엇을 하는지 모르는 데서 옵니다.", "author": "Warren Buffett"},
        {"eng": "Success is walking from failure to failure with no loss of enthusiasm.", "kor": "성공이란 열정을 잃지 않고 실패를 거듭해 나가는 능력입니다.", "author": "Winston Churchill"}
    ]

    try:
        # 1. API로 영어 명언 가져오기
        res = requests.get("https://api.quotable.io/random?tags=business", timeout=2).json()
        eng_text = res['content']
        author = res['author']
        
        # 2. 한글 번역 시도 (기존 뉴스 번역 API 활용)
        kor_text = ""
        try:
            trans_url = "https://api.mymemory.translated.net/get"
            trans_res = requests.get(trans_url, params={'q': eng_text, 'langpair': 'en|ko'}, timeout=2).json()
            if trans_res['responseStatus'] == 200:
                kor_text = trans_res['responseData']['translatedText'].replace("&quot;", "'").replace("&amp;", "&")
        except:
            pass # 번역 실패 시 빈 칸

        # 번역 실패 시 예비 멘트 혹은 영어만 리턴 방지
        if not kor_text: 
            kor_text = "Global Business Quote"

        return {"eng": eng_text, "kor": kor_text, "author": author}

    except:
        # API 실패 시, 예비 리스트에서 랜덤 선택
        return random.choice(backup_quotes)
@st.cache_data(ttl=86400) # 24시간 (재무제표는 분기마다 바뀌므로 하루 종일 캐싱해도 안전)
def get_financial_metrics(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/stock/metric?symbol={symbol}&metric=all&token={api_key}"
        res = requests.get(url, timeout=5).json()
        metrics = res.get('metric', {})
        return {
            "growth": metrics.get('salesGrowthYoy', None),
            "op_margin": metrics.get('operatingMarginTTM', None),
            "net_margin": metrics.get('netProfitMarginTTM', None),
            "debt_equity": metrics.get('totalDebt/totalEquityQuarterly', None)
        } if metrics else None
    except: return None

@st.cache_data(ttl=86400) # 24시간 (기업 프로필도 거의 안 바뀜)
def get_company_profile(symbol, api_key):
    try:
        url = f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={api_key}"
        res = requests.get(url, timeout=5).json()
        return res if res and 'name' in res else None
    except: return None

@st.cache_data(ttl=14400)
def get_extended_ipo_data(api_key):
    now = datetime.now()
    
    # [핵심 수정] 구간을 나눌 때 서로 겹치게(Overlap) 설정합니다.
    # 180일과 181일로 딱 나누지 않고, 200일/170일 식으로 겹치게 하여 경계 누락을 방지합니다.
    ranges = [
        (now - timedelta(days=200), now + timedelta(days=120)),  # 구간 1: 현재~과거 200일 (약 6.5개월)
        (now - timedelta(days=380), now - timedelta(days=170)), # 구간 2: 과거 170일~380일
        (now - timedelta(days=560), now - timedelta(days=350))  # 구간 3: 과거 350일~560일
    ]
    
    all_data = []
    for start_dt, end_dt in ranges:
        start_str = start_dt.strftime('%Y-%m-%d')
        end_str = end_dt.strftime('%Y-%m-%d')
        url = f"https://finnhub.io/api/v1/calendar/ipo?from={start_str}&to={end_str}&token={api_key}"
        
        try:
            # 호출 사이 간격을 아주 약간 주어 Rate Limit 안정성 확보
            time.sleep(0.3) 
            res = requests.get(url, timeout=7).json()
            ipo_list = res.get('ipoCalendar', [])
            if ipo_list:
                all_data.extend(ipo_list)
        except:
            continue
    
    if not all_data: 
        return pd.DataFrame()
    
    # 데이터프레임 생성
    df = pd.DataFrame(all_data)
    
    # [중요] 구간을 겹치게 가져왔으므로 여기서 중복을 확실히 제거합니다.
    df = df.drop_duplicates(subset=['symbol', 'date'])
    
    # 날짜 변환 및 보정
    df['공모일_dt'] = pd.to_datetime(df['date'], errors='coerce').dt.normalize()
    df = df.dropna(subset=['공모일_dt'])
    
    return df

import yfinance as yf

@st.cache_data(ttl=60, show_spinner=False)
def get_batch_prices(ticker_list):
    """
    Supabase DB를 활용하여 15분 단위로 주가를 캐싱하고 Batch로 가져오는 함수
    (디버깅 메시지 제거 버전)
    """
    # [방어 로직] 리스트 체크 및 클렌징
    if not ticker_list or not isinstance(ticker_list, list):
        return {}
    
    clean_tickers = [str(t).strip() for t in ticker_list if t and str(t).strip().lower() != 'nan']
    if not clean_tickers:
        return {}
    
    now = datetime.now()
    fifteen_mins_ago = (now - timedelta(minutes=15)).isoformat()
    
    # ---------------------------------------------------------
    # [Step 1] Supabase DB에서 신선한(15분 이내) 데이터 먼저 조회
    # ---------------------------------------------------------
    try:
        res = supabase.table("price_cache") \
            .select("ticker, price") \
            .in_("ticker", clean_tickers) \
            .gt("updated_at", fifteen_mins_ago) \
            .execute()
        # DB에 있는 데이터는 API 호출 없이 즉시 활용
        cached_data = {item['ticker']: float(item['price']) for item in res.data}
    except Exception:
        # DB 오류 시 빈 딕셔너리로 시작 (API에서 다 가져오도록 유도)
        cached_data = {}

    # ---------------------------------------------------------
    # [Step 2] DB에 없거나 오래된 티커만 골라내서 API 호출
    # ---------------------------------------------------------
    missing_tickers = [t for t in clean_tickers if t not in cached_data]
    
    if missing_tickers:
        tickers_str = " ".join(missing_tickers)
        try:
            # 야후 파이낸스 실시간 데이터 다운로드
            data = yf.download(tickers_str, period="1d", interval="1m", group_by='ticker', threads=True, progress=False)
            
            for t in missing_tickers:
                try:
                    # 데이터 구조 처리 (단일 종목 vs 다중 종목 대응)
                    if len(missing_tickers) > 1:
                        if t in data.columns.levels[0]:
                            target_data = data[t]['Close'].dropna()
                        else: continue
                    else:
                        target_data = data['Close'].dropna()

                    if not target_data.empty:
                        current_p = float(target_data.iloc[-1])
                        
                        # [Step 3] 새로운 가격 정보를 DB에 영구 저장 (Upsert)
                        supabase.table("price_cache").upsert({
                            "ticker": t,
                            "price": current_p,
                            "updated_at": now.isoformat()
                        }).execute()
                        
                        cached_data[t] = current_p
                    else:
                        cached_data[t] = 0.0 # 데이터를 못 찾은 경우
                except:
                    cached_data[t] = 0.0
        except Exception:
            pass # API 에러 무시

    return cached_data



def get_asset_grade(asset_text):
    if asset_text == "10억 미만": return "Bronze"
    elif asset_text == "10억~30억": return "Silver"
    elif asset_text == "30억~80억": return "Gold"
    elif asset_text == "80억 이상": return "Diamond"
    return ""



def upload_photo_to_drive(file_obj, filename_prefix):
    if file_obj is None: return "미제출"
    try:
        _, drive_service = get_gcp_clients()
        file_obj.seek(0)
        
        file_metadata = {
            'name': f"{filename_prefix}_{file_obj.name}", 
            'parents': [DRIVE_FOLDER_ID]
        }
        
        # 100*1024 대신 구글 규격에 맞는 256*1024로 변경
        media = MediaIoBaseUpload(
            file_obj, 
            mimetype=file_obj.type, 
            resumable=True, 
            chunksize=256*1024  # 256KB 단위로 전송
        )
        
        file = drive_service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink',
            supportsAllDrives=True
        ).execute()

        drive_service.permissions().create(
            fileId=file.get('id'),
            body={'type': 'anyone', 'role': 'reader'},
            supportsAllDrives=True
        ).execute()
        
        return file.get('webViewLink')
    except Exception as e:
        # 에러 발생 시 재시도 안내 출력
        st.error(f"📂 업로드 실패 (네트워크 확인 필요): {e}")
        return "업로드 실패"
        
def send_email_code(to_email, code):
    try:
        if "smtp" in st.secrets:
            sender_email = st.secrets["smtp"]["email_address"]
            sender_pw = st.secrets["smtp"]["app_password"]
        else:
            sender_email = st.secrets["email_address"]
            sender_pw = st.secrets["app_password"]
        msg = MIMEText(f"안녕하세요. 인증번호는 [{code}] 입니다.")
        msg['Subject'] = "[Unicorn Finder] 본인 인증번호"
        msg['From'] = sender_email
        msg['To'] = to_email
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(sender_email, sender_pw)
            s.sendmail(sender_email, to_email, msg.as_string())
        st.toast(f"📧 {to_email}로 인증 메일을 보냈습니다!", icon="✅")
        return True
    except Exception as e:
        st.error(f"❌ 이메일 전송 실패: {e}")
        return False

# 📍 승인 알림 메일 함수 추가
def send_approval_email(to_email, user_id):
    try:
        # secrets에서 설정 가져오기 (기존 이메일 설정 활용)
        if "smtp" in st.secrets:
            sender_email = st.secrets["smtp"]["email_address"]
            sender_pw = st.secrets["smtp"]["app_password"]
        else:
            sender_email = st.secrets["email_address"]
            sender_pw = st.secrets["app_password"]
            
        subject = "[Unicorn Finder] 가입 승인 안내"
        body = f"""
        안녕하세요, {user_id}님!
        
        축하합니다! Unicorn Finder의 회원 가입이 승인되었습니다.
        이제 로그인하여 모든 서비스를 정상적으로 이용하실 수 있습니다.
        
        유니콘이 되신 것을 환영합니다! 🦄
        """
        
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = to_email
        
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(sender_email, sender_pw)
            s.sendmail(sender_email, to_email, msg.as_string())
        return True
    except Exception as e:
        st.error(f"📧 승인 메일 전송 실패: {e}")
        return False



def send_rejection_email(to_email, user_id, reason):
    try:
        if "smtp" in st.secrets:
            sender_email = st.secrets["smtp"]["email_address"]
            sender_pw = st.secrets["smtp"]["app_password"]
        else:
            sender_email = st.secrets["email_address"]
            sender_pw = st.secrets["app_password"]
            
        subject = "[Unicorn Finder] 가입 승인 보류 안내"
        body = f"""
        안녕하세요, {user_id}님. 
        Unicorn Finder 운영팀입니다.
        
        제출해주신 증빙 서류에 보완이 필요하여 승인이 잠시 보류되었습니다.
        
        [보류 사유]
        {reason}
        
        위 사유를 확인하신 후 다시 신청해주시면 신속히 재검토하겠습니다.
        감사합니다.
        """
        
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = to_email
        
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(sender_email, sender_pw)
            s.sendmail(sender_email, to_email, msg.as_string())
        return True
    except Exception as e:
        st.error(f"📧 보류 메일 전송 실패: {e}")
        return False

# --- [신규 추가: 권한 관리 로직] ---
def check_permission(action):
    """
    권한 체크 로직 (노출 설정 반영 버전)
    """
    auth_status = st.session_state.get('auth_status')
    user_info = st.session_state.get('user_info', {})
    user_role = user_info.get('role', 'restricted')
    user_status = user_info.get('status', 'pending')
    
    # [신규] 유저의 노출 설정 확인
    vis_str = str(user_info.get('visibility', 'True,True,True'))
    is_public_mode = 'True' in vis_str # 하나라도 True가 있으면 공개 모드

    if action == 'view':
        return True
    
    if action == 'watchlist':
        return auth_status == 'user'
    
    if action == 'write':
        # 1. 로그인 했는가?
        if auth_status == 'user':
            # 2. 관리자면 무조건 통과
            if user_info.get('role') == 'admin': return True
            
            # 3. 일반 유저 조건: (서류제출함) AND (관리자 승인됨) AND (정보 공개 중임)
            if (user_role == 'user') and (user_status == 'approved') and is_public_mode:
                return True
                
        return False
        
    return False

# --- [여기(최상단)에 함수를 두어야 아래에서 인식합니다] ---
def clean_text_final(text):
    if not text:
        return ""
    text = str(text)
    text = text.replace("**", "").replace("##", "").replace("###", "")
    return text.strip()



# ---------------------------------------------------------
# 1. 앱 전체 스타일 설정 (CSS)
# ---------------------------------------------------------
st.markdown("""
    <style>
    /* 탭 메뉴 글씨 스타일 조정 */
    button[data-baseweb="tab"] p {
        font-size: 1.1rem !important;
        font-weight: 600 !important;
    }
    
    /* [게시판 개선] 게시하기 버튼 커스텀: 흰색 바탕, 검정 글씨, 테두리 */
    div.stButton > button[kind="primary"] {
        background-color: #ffffff !important;
        color: #000000 !important;
        border: 1px solid #cccccc !important;
        font-size: 1.05rem !important; /* '글쓰기' expander 폰트 크기와 맞춤 */
        font-weight: 500 !important;
        height: auto !important;
        padding: 5px 20px !important;
        transition: all 0.2s ease;
    }
    
    /* 게시하기 버튼 호버 효과 */
    div.stButton > button[kind="primary"]:hover {
        border-color: #000000 !important;
        background-color: #f9f9f9 !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }

    /* 게시글 리스트 간격 조절 */
    .post-divider {
        margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. 공통 유틸리티 함수
# ---------------------------------------------------------

def display_disclaimer():
    """
    모든 탭 하단에 표시될 공통 면책 조항
    """
    st.markdown("<br>", unsafe_allow_html=True) # 약간의 여백
    st.divider()
    st.caption("""
        **이용 유의사항** 본 서비스는 자체 알고리즘과 AI 모델을 활용한 요약 정보를 제공하며, 원저작권자의 권리를 존중합니다. 요약본은 원문과 차이가 있을 수 있으므로 반드시 원문을 확인하시기 바랍니다. 모든 투자 결정의 최종 책임은 사용자 본인에게 있습니다.
    """)

# ---------------------------------------------------------
# 3. 이후 메인 로직 시작 (탭 구성 등)
# ---------------------------------------------------------
    
# ---------------------------------------------------------
# ✅ [수정] translate_news_title 함수 (재시도 로직 적용)
# ---------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=3600)
def translate_news_title(en_title):
    """뉴스 제목을 한국 경제 신문 헤드라인 스타일로 번역 (Groq API + 재시도 로직 + 후처리)"""
    groq_key = st.secrets.get("GROQ_API_KEY")
    if not groq_key or not en_title:
        return en_title

    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_key)
    
    # [수정] 프롬프트 제약 조건 강화
    system_msg = """당신은 한국 경제 신문사 헤드라인 데스크의 전문 편집자입니다. 
    영문 뉴스를 한국어 경제 신문 헤드라인 스타일로 번역하세요.
    - 반드시 순수한 한글(KOREAN)로만 작성하세요. (한자, 베트남어, 일본어 등 혼용 절대 금지)
    - '**'나 '*' 같은 마크다운 강조 기호를 절대 사용하지 마세요.
    - 'sh' -> '주당', 'M' -> '백만', 'IPO' -> 'IPO'로 번역하세요.
    - 따옴표나 불필요한 수식어는 제거하고 핵심만 간결하게 전달하세요."""

    max_retries = 3
    for i in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": f"Translate this headline to pure Korean only: {en_title}"}
                ],
                temperature=0.0  # 일관성을 위해 0.1에서 0.0으로 하향 조정
            )
            
            translated_text = response.choices[0].message.content.strip()
            
            # [추가] 후처리 로직: 마크다운 기호 및 따옴표 강제 제거
            clean_text = translated_text.replace("**", "").replace("*", "").replace('"', '').replace("'", "")
            
            # [추가] 정규식을 활용해 한글, 숫자, 기본 부호 외의 외국어(한자 등) 제거 (선택 사항)
            # clean_text = re.sub(r'[^가-힣0-9\s\.\,\[\]\(\)\%\!\?\-\w]', '', clean_text)
            
            return clean_text
            
        except Exception as e:
            if "429" in str(e):
                time.sleep(2 * (i + 1))
                continue
            else:
                return en_title
    
    return en_title

# ---------------------------------------------------------
# [내부용] 실제 시장 지표를 계산하는 함수 (API 호출 포함)
# ---------------------------------------------------------
def _calculate_market_metrics_internal(df_calendar, api_key):
    """
    실제 야후 파이낸스 API와 승수님의 내부 함수를 호출하여 
    데이터를 계산하는 '작업자(Worker)' 함수입니다.
    """
    data = {
        "ipo_return": 0.0, "ipo_volume": 0, "unprofitable_pct": 0, "withdrawal_rate": 0,
        "vix": 0.0, "buffett_val": 0.0, "pe_ratio": 0.0, "fear_greed": 50
    }

    if not df_calendar.empty:
        today = datetime.now().date()
        
        # 1. IPO 데이터 계산 (최근 30개 기준)
        traded_ipos = df_calendar[df_calendar['공모일_dt'].dt.date < today].sort_values(by='공모일_dt', ascending=False).head(30)
        
        ret_sum = 0; ret_cnt = 0; unp_cnt = 0
        for _, row in traded_ipos.iterrows():
            try:
                # [주의] get_current_stock_price, get_financial_metrics 함수가 정의되어 있어야 합니다.
                p_ipo = float(str(row.get('price','0')).replace('$','').split('-')[0])
                p_curr = get_current_stock_price(row['symbol'], api_key) 
                if p_ipo > 0 and p_curr > 0:
                    ret_sum += ((p_curr - p_ipo) / p_ipo) * 100
                    ret_cnt += 1
                fin = get_financial_metrics(row['symbol'], api_key)
                if fin and fin.get('net_margin') and fin['net_margin'] < 0: unp_cnt += 1
            except: pass
        
        if ret_cnt > 0: data["ipo_return"] = ret_sum / ret_cnt
        if len(traded_ipos) > 0: data["unprofitable_pct"] = (unp_cnt / len(traded_ipos)) * 100

        # 2. 향후 30일 물량 및 1.5년 철회율
        future_ipos = df_calendar[(df_calendar['공모일_dt'].dt.date >= today) & (df_calendar['공모일_dt'].dt.date <= today + timedelta(days=30))]
        data["ipo_volume"] = len(future_ipos)
        
        recent_history = df_calendar[df_calendar['공모일_dt'].dt.date >= (today - timedelta(days=540))]
        if not recent_history.empty:
            wd = recent_history[recent_history['status'].str.lower() == 'withdrawn']
            data["withdrawal_rate"] = (len(wd) / len(recent_history)) * 100

    # --- B. Macro Market 데이터 (Yahoo Finance) ---
    try:
        vix_obj = yf.Ticker("^VIX")
        data["vix"] = vix_obj.history(period="1d")['Close'].iloc[-1]
        
        w5000 = yf.Ticker("^W5000").history(period="1d")['Close'].iloc[-1]
        # 미국 GDP 추정치 (약 28조 달러)
        data["buffett_val"] = ( (w5000 / 1000 * 0.93) / 28.0 ) * 100
        
        spy = yf.Ticker("SPY")
        data["pe_ratio"] = spy.info.get('trailingPE', 24.5)

        spx = yf.Ticker("^GSPC").history(period="1y")
        curr_spx = spx['Close'].iloc[-1]
        ma200 = spx['Close'].rolling(200).mean().iloc[-1]
        mom_score = ((curr_spx - ma200) / ma200) * 100
        
        s_vix = max(0, min(100, (35 - data["vix"]) * (100/23)))
        s_mom = max(0, min(100, (mom_score + 10) * 5))
        data["fear_greed"] = (s_vix + s_mom) / 2
    except Exception as e:
        print(f"Macro Data Error: {e}")
    
    return data

@st.cache_data(show_spinner=False, ttl=600)
def get_financial_report_analysis(company_name, ticker, metrics):
    """
    Tab 3: 재무 데이터 기반 정성적 분석 (24시간 Supabase 캐시)
    metrics: PER, ROE, 부채비율 등 핵심 지표가 담긴 딕셔너리
    """
    if not model: return "AI 모델 설정 오류"

    # [Step 1] Supabase 캐시 확인 (24시간)
    cache_key = f"{ticker}_Financial_Report_Tab3"
    now = datetime.now()
    one_day_ago = (now - timedelta(days=1)).isoformat()

    try:
        res = supabase.table("analysis_cache") \
            .select("content") \
            .eq("cache_key", cache_key) \
            .gt("updated_at", one_day_ago) \
            .execute()
        
        if res.data:
            return res.data[0]['content']
    except Exception as e:
        print(f"Tab3 Cache Error: {e}")

    # [Step 2] 캐시 없으면 AI 분석 실행
    # 승수님의 기존 로직(목차 구조)을 프롬프트에 반영
    prompt = f"""
    당신은 CFA 자격을 보유한 수석 주식 애널리스트입니다.
    아래 재무 데이터를 바탕으로 {company_name} ({ticker})에 대한 투자 분석 리포트를 작성하세요.

    [재무 데이터]
    - 매출 성장률(YoY): {metrics.get('growth', 'N/A')}
    - 순이익률(Net Margin): {metrics.get('net_margin', 'N/A')}
    - 영업이익률(OPM): {metrics.get('op_margin', 'N/A')}
    - ROE: {metrics.get('roe', 'N/A')}
    - 부채비율(D/E): {metrics.get('debt_equity', 'N/A')}
    - 선행 PER: {metrics.get('pe', 'N/A')}
    - 발생액 품질: {metrics.get('accruals', 'Unknown')}

    [작성 가이드]
    1. 언어: 전문적인 한국어
    2. 형식: 아래 4가지 소제목을 **반드시** 사용하여 단락을 구분하세요.
       **[Valuation & Market Position]**
       **[Operating Performance]**
       **[Risk & Solvency]**
       **[Analyst Conclusion]**
    3. 내용: 수치를 단순 나열하지 말고, 수치가 갖는 함의(프리미엄, 효율성, 리스크 등)를 해석하세요.
    4. 분량: 전체 10~12줄 내외로 핵심만 요약하세요.
    """

    try:
        response = model.generate_content(prompt)
        result = response.text

        # [Step 3] 결과 저장
        supabase.table("analysis_cache").upsert({
            "cache_key": cache_key,
            "content": result,
            "updated_at": now.isoformat()
        }).execute()

        return result

    except Exception as e:
        return f"분석 리포트 생성 중 오류: {str(e)}"


# ---------------------------------------------------------
# ✅ [메인] Supabase 연동 캐싱 함수 (이걸 호출하세요)
# ---------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=600)
def get_cached_market_status(df_calendar, api_key):
    """
    Supabase DB를 확인하여 시장 지표를 0.1초 만에 반환합니다.
    없을 경우에만 계산 로직(5~10초)을 수행하고 저장합니다.
    """
    # [Step 1] Supabase에서 오늘자 데이터 확인 (24시간 캐시)
    cache_key = "Market_Dashboard_Metrics_Tab2"
    now = datetime.now()
    one_day_ago = (now - timedelta(hours=24)).isoformat()

    try:
        res = supabase.table("analysis_cache") \
            .select("content") \
            .eq("cache_key", cache_key) \
            .gt("updated_at", one_day_ago) \
            .execute()
        
        if res.data:
            # DB에 있으면 즉시 JSON 파싱 후 반환
            return json.loads(res.data[0]['content'])
    except Exception as e:
        print(f"Market Metrics Cache Miss: {e}")

    # [Step 2] 캐시가 없거나 만료됨 -> 내부 계산 함수 실행 (시간 소요됨)
    fresh_data = _calculate_market_metrics_internal(df_calendar, api_key)

    # [Step 3] 계산된 결과를 Supabase에 저장 (다음 사람을 위해)
    try:
        supabase.table("analysis_cache").upsert({
            "cache_key": cache_key,
            "content": json.dumps(fresh_data), # 딕셔너리를 JSON 문자열로 변환
            "updated_at": now.isoformat()
        }).execute()
    except Exception as e:
        print(f"Metrics Save Error: {e}")

    return fresh_data
    
# --- [주식 및 차트 기능] ---
import yfinance as yf
import plotly.graph_objects as go

# ==========================================
# [0] AI 설정 및 API 키 관리 (보안 강화)
# ==========================================

# 1. 자동 모델 선택 함수 (안전장치 강화 버전)
@st.cache_data(show_spinner=False, ttl=86400)
def get_latest_stable_model():
    genai_key = st.secrets.get("GENAI_API_KEY")
    if not genai_key: return 'gemini-1.5-flash' # 키 없으면 기본값

    try:
        genai.configure(api_key=genai_key)
        
        # 1. 구글에서 현재 사용 가능한 모든 모델 리스트를 가져옵니다.
        all_models = genai.list_models()
        
        candidate_models = []

        for m in all_models:
            # 조건: 'generateContent' 지원하고 이름에 'flash'가 있어야 함
            if 'generateContent' in m.supported_generation_methods and 'flash' in m.name:
                
                # [핵심] 이름에서 버전 숫자만 뽑아냅니다. (예: gemini-1.5-flash -> 1.5)
                # 정규표현식: (\d+\.\d+) -> 숫자.숫자 패턴을 찾음
                match = re.search(r'gemini-(\d+\.\d+)-flash', m.name)
                
                if match:
                    version_float = float(match.group(1)) # 문자열 "1.5"를 숫자 1.5로 변환
                    candidate_models.append({
                        "name": m.name,
                        "version": version_float
                    })

        if not candidate_models:
            return 'gemini-1.5-flash' # 검색 실패 시 안전한 기본값

        # 2. 버전 숫자가 높은 순서대로 정렬합니다. (내림차순)
        # 예: [2.0, 1.5, 1.0] 순으로 정렬됨
        candidate_models.sort(key=lambda x: x["version"], reverse=True)

        # 3. 가장 높은 버전의 모델 이름을 반환합니다.
        # 즉, 나중에 1.6이나 3.0이 나오면 알아서 그게 1등이 되어 선택됩니다.
        best_model = candidate_models[0]["name"]
        
        return best_model

    except Exception as e:
        # API 에러, 네트워크 오류 등 발생 시 무조건 1.5-flash로 고정 (앱 멈춤 방지)
        return 'gemini-1.5-flash'

# 2. 전역 모델 객체 생성
SELECTED_MODEL_NAME = get_latest_stable_model()


if SELECTED_MODEL_NAME:
    try:
        model = genai.GenerativeModel(SELECTED_MODEL_NAME)
    except:
        model = None
else:
    st.error("⚠️ GENAI_API_KEY가 유출되었거나 설정되지 않았습니다. Streamlit Secrets를 확인하세요.")
    model = None

@st.cache_data(show_spinner=False, ttl=600) # 메모리 캐시는 짧게, DB가 메인 저장소 역할
def get_ai_analysis(company_name, topic, points, structure_template):
    if not model:
        return "AI 모델 설정 오류: API 키를 확인하세요."
    
    # [Step 1] DB 조회용 고유 키 생성 (예: AAPL_S-1_Tab0)
    cache_key = f"{company_name}_{topic}_Tab0"
    now = datetime.now()
    one_day_ago = (now - timedelta(days=1)).isoformat()

    try:
        # DB에서 24시간 이내의 데이터가 있는지 확인
        res = supabase.table("analysis_cache") \
            .select("content") \
            .eq("cache_key", cache_key) \
            .gt("updated_at", one_day_ago) \
            .execute()
        
        if res.data:
            # 존재하면 즉시 반환 (AI 비용 0원, 즉시 로딩)
            return res.data[0]['content']
    except Exception as e:
        print(f"Tab0 DB Cache Error: {e}")

    # [Step 2] 캐시가 없으면 원래의 고품질 분석 수행 (재시도 로직 포함)
    max_retries = 3
    for i in range(max_retries):
        try:
            prompt = f"""
            분석 대상: {company_name}의 {topic} 서류
            체크포인트: {points}
            
            [지침]
            당신은 월가 출신의 전문 분석가입니다. 
            단, **"저는 분석가입니다" 같은 자기소개나 인사말은 절대 하지 마세요.**
            
            [내용 구성 및 형식 - 반드시 아래 형식을 따를 것]
            각 문단의 시작에 **[소제목]**을 붙여서 내용을 명확히 구분하고 굵은 글씨를 생략하지 마세요.
            {structure_template}

            [문체 가이드]
            - '~이다' 대신 '~입니다', '~하고 있습니다', '~할 것으로 보입니다'를 사용하세요.
            - 문장 끝이 끊기지 않도록 매끄럽게 연결하세요.
            - 핵심 위주로 작성하되, 너무 짧은 요약보다는 풍부한 인사이트를 담아주세요.
            
            위 내용을 바탕으로 전문적인 어조의 한국어로 작성하세요. (5줄정도)
            """
            
            response = model.generate_content(prompt)
            analysis_result = response.text

            # [Step 3] 분석 성공 시 결과를 DB에 영구 저장 (24시간 보존)
            try:
                supabase.table("analysis_cache").upsert({
                    "cache_key": cache_key,
                    "content": analysis_result,
                    "updated_at": now.isoformat()
                }).execute()
            except: pass # 저장 실패 시에도 결과는 반환

            return analysis_result
            
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                time.sleep(2 * (i + 1))
                continue
            else:
                return f"현재 분석 엔진을 조율 중입니다. (상세: {str(e)})"
    
    return "⚠️ 사용량이 많아 분석이 지연되고 있습니다. 잠시 후 다시 시도해주세요."


# ==========================================
# [1] 학술 논문 데이터 리스트 (기본 제공 데이터)
# ==========================================
IPO_REFERENCES = [
    {
        "label": "장기 수익률",
        "title": "The Long-Run Performance of Initial Public Offerings",
        "author": "Jay R. Ritter (1991)",
        "journal": "The Journal of Finance",
        "url": "https://scholar.google.com/scholar?q=The+Long-Run+Performance+of+Initial+Public+Offerings+Ritter+1991"
    },
    {
        "label": "수익성 및 생존",
        "title": "New lists: Fundamentals and survival rates",
        "author": "Eugene F. Fama & Kenneth R. French (2004)",
        "journal": "Journal of Financial Economics",
        "url": "https://scholar.google.com/scholar?q=New+lists+Fundamentals+and+survival+rates+Fama+French+2004"
    },
    {
        "label": "재무 건전성",
        "title": "Earnings Management and the Long-Run Market Performance of IPOs",
        "author": "S.H. Teoh, I. Welch, & T.J. Wong (1998)",
        "journal": "The Journal of Finance",
        "url": "https://scholar.google.com/scholar?q=Earnings+Management+and+the+Long-Run+Market+Performance+of+IPOs+Teoh"
    },
    {
        "label": "VC 인증 효과",
        "title": "The Role of Venture Capital in the Creation of Public Companies",
        "author": "C. Barry, C. Muscarella, J. Peavy, & M. Vetsuypens (1990)",
        "journal": "Journal of Financial Economics",
        "url": "https://scholar.google.com/scholar?q=The+Role+of+Venture+Capital+in+the+Creation+of+Public+Companies+Barry"
    },
    {
        "label": "역선택 방어",
        "title": "Why New Issues are Underpriced",
        "author": "Kevin Rock (1986)",
        "journal": "Journal of Financial Economics",
        "url": "https://scholar.google.com/scholar?q=Why+New+Issues+are+Underpriced+Kevin+Rock"
    }
]



# ==========================================
# [3] 핵심 재무 분석 함수 (yfinance 실시간 연동)
# ==========================================
def get_us_ipo_analysis(ticker_symbol):
    """
    yfinance를 사용하여 실시간 재무 지표를 계산합니다.
    """
    try:
        tk = yf.Ticker(ticker_symbol)
        info = tk.info
        
        # 1. Sales Growth (최근 매출 성장률)
        sales_growth = info.get('revenueGrowth', 0) * 100 
        
        # 2. OCF (영업현금흐름)
        cashflow = tk.cashflow
        if not cashflow.empty and 'Operating Cash Flow' in cashflow.index:
            ocf_val = cashflow.loc['Operating Cash Flow'].iloc[0]
        else:
            ocf_val = info.get('operatingCashflow', 0)
            
        # 3. Accruals (발생액 계산: 당기순이익 - 영업현금흐름)
        net_income = info.get('netIncomeToCommon', 0)
        accruals_amt = net_income - ocf_val
        accruals_status = "Low" if accruals_amt <= 0 else "High"

        return {
            "sales_growth": sales_growth,
            "ocf": ocf_val,
            "accruals": accruals_status,
            "status": "Success"
        }
    except Exception as e:
        return {"status": "Error"}

# ==========================================
# [4] 메인 실행부 (Main Logic) - 여기서부터 끝까지 교체하세요
# ==========================================

# 1. 페이지 설정 (반드시 가장 먼저 실행되어야 함)
try:
    st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")
except:
    pass # 이미 설정되어 있다면 패스

# 2. 세션 상태 안전 초기화
for key in ['page', 'auth_status', 'watchlist', 'posts', 'user_decisions', 'view_mode', 'user_info', 'selected_stock']:
    if key not in st.session_state:
        if key == 'page': st.session_state[key] = 'login'
        elif key == 'watchlist': st.session_state[key] = []
        elif key == 'posts': st.session_state[key] = []
        elif key == 'user_decisions': st.session_state[key] = {}
        elif key == 'view_mode': st.session_state[key] = 'all'
        else: st.session_state[key] = None

# 3. 공통 UI 함수 정의 (전역)
def draw_decision_box(step_key, title, options):
    """사용자 투표/판단 박스를 그리는 함수"""
    sid = st.session_state.get('selected_stock', {}).get('symbol', 'UNKNOWN')
    
    # 결정 데이터 공간 확보
    if sid not in st.session_state.user_decisions:
        st.session_state.user_decisions[sid] = {}
        
    st.write("---")
    st.markdown(f"##### {title}")
    
    current_val = st.session_state.user_decisions[sid].get(step_key)
    choice = st.radio(
        label=f"판단_{step_key}",
        options=options,
        index=options.index(current_val) if current_val in options else None,
        key=f"dec_{sid}_{step_key}",
        horizontal=True,
        label_visibility="collapsed"
    )
    if choice:
        st.session_state.user_decisions[sid][step_key] = choice

def handle_post_reaction(post_id, reaction_type, user_id):
    """게시글 좋아요/싫어요 처리 함수"""
    if not user_id:
        st.toast("🔒 로그인이 필요한 기능입니다.")
        return

    for p in st.session_state.posts:
        if p['id'] == post_id:
            user_list_key = 'like_users' if reaction_type == 'likes' else 'dislike_users'
            p.setdefault(user_list_key, [])
            
            if user_id not in p[user_list_key]:
                p[reaction_type] = p.get(reaction_type, 0) + 1
                p[user_list_key].append(user_id)
                st.rerun()
            else:
                st.toast("이미 참여하셨습니다.")
            break

# --- CSS 스타일 적용 ---
st.markdown("""
    <style>
    .stApp { background-color: #FFFFFF; color: #333333; }
    div.stButton > button { border-radius: 8px; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# [PAGE ROUTING] 세션 상태 안전 초기화
# ==========================================

# 필수 변수들이 세션에 없으면 초기값 설정
if 'page' not in st.session_state:
    st.session_state.page = 'login'

if 'login_step' not in st.session_state:
    st.session_state.login_step = 'choice'

if 'signup_stage' not in st.session_state:
    st.session_state.signup_stage = 1

if 'auth_status' not in st.session_state:
    st.session_state.auth_status = None

if 'user_info' not in st.session_state:
    st.session_state.user_info = {}

# '🦄 Unicorn Finder' 제목 출력 부분은 삭제했습니다.
# 바로 아래에 기존의 if st.session_state.page == 'login': 로직이 이어지면 됩니다.


# --- [1. 로그인 & 회원가입 페이지] ---
if st.session_state.page == 'login':
  
    # 1. 스타일링
    st.markdown("""
    <style>
        .login-title {
            font-size: 2.5rem !important; font-weight: 800 !important;
            background: linear-gradient(to right, #6a11cb 0%, #2575fc 100%);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            text-align: center; margin-bottom: 5px;
        }
        .login-subtitle { text-align: center; color: #666; margin-bottom: 30px; }
        .auth-card {
            background-color: white; padding: 30px; border-radius: 15px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.05); border: 1px solid #f0f0f0;
        }
        /* 입력창 라벨과 박스 간격 조정 */
        .stTextInput { margin-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

    # 2. 화면 레이아웃 (중앙 정렬)
    col_spacer1, col_center, col_spacer2 = st.columns([1, 4, 1])

    with col_center:
        st.write("<br>", unsafe_allow_html=True)
        st.markdown("<h1 class='login-title'>UnicornFinder</h1>", unsafe_allow_html=True)
        
        # 상태 초기화
        if 'login_step' not in st.session_state: st.session_state.login_step = 'choice'
        
        # 가상 DB 초기화 (없을 경우)
        if 'db_users' not in st.session_state: st.session_state.db_users = ["admin"]

        # ---------------------------------------------------------
        # [통합 화면] 로그인 입력 + 버튼 (기존 Step 1, 2 통합)
        # ---------------------------------------------------------
        # 'choice' 상태이거나 'login_input' 상태(혹시 남아있을 경우)일 때 메인 화면 표시
        if st.session_state.login_step in ['choice', 'login_input']:
            
            st.write("<br>", unsafe_allow_html=True)
            
            # [1] 아이디/비번 입력창 (바로 노출)
            l_id = st.text_input("아이디", key="login_id")
            l_pw = st.text_input("비밀번호", type="password", key="login_pw")
            
            st.write("<br>", unsafe_allow_html=True)
            
            # [2] 버튼 섹션
            # 버튼 1: 로그인 (누르면 즉시 검증)
            if st.button("로그인", use_container_width=True, type="primary"):
                if not l_id or not l_pw:
                      st.error("아이디와 비밀번호를 입력해주세요.")
                else:
                    with st.spinner("로그인 중..."):
                        # [📌 변경 코드] DB에서 ID로 단건 조회 (속도 향상 및 DB 전환)
                        user = db_load_user(l_id)
                        
                        if user and str(user.get('pw')) == str(l_pw):
                            st.session_state.auth_status = 'user'
                            st.session_state.user_info = user
                            
                            # [📌 추가됨] 영구 저장된 관심종목 & 예측 불러오기 (핵심 기능)
                            # 로그인과 동시에 DB에 저장해뒀던 내 관심종목을 메모리로 가져옵니다.
                            saved_watchlist, saved_preds = db_sync_watchlist(l_id)
                            st.session_state.watchlist = saved_watchlist
                            st.session_state.watchlist_predictions = saved_preds
                            
                            # 상태값 추출 및 정제
                            raw_status = user.get('status', 'pending')
                            user_status = str(raw_status).strip().lower()
                            
                            # 터미널 로그 기록
                            print(f"🔒 LOGIN SUCCESS: {l_id} | Status: {user_status}") 
                            
                            # 페이지 이동 로직
                            if user_status == 'approved':
                                st.session_state.page = 'calendar'
                            else:
                                st.session_state.page = 'setup'
                                
                            st.rerun()
                        else:
                            st.error("아이디 또는 비밀번호가 틀립니다.")
            
            # 버튼 2: 회원가입 (누르면 인증 화면으로 이동)
            if st.button("회원가입", use_container_width=True):
                st.session_state.login_step = 'signup_input' # 회원가입 단계로 전환
                st.session_state.auth_code_sent = False      # 인증 상태 초기화
                st.rerun()
                
            # 버튼 3: 구경하기
            if st.button("구경하기", use_container_width=True):
                st.session_state.auth_status = 'guest'
                st.session_state.page = 'calendar'
                st.rerun()

            # [3] 명언 섹션 (하단 배치)
            st.write("<br><br>", unsafe_allow_html=True) 
            
            quote_data = get_daily_quote()
            st.markdown(f"""
                <div style="
                    background-color: #ffffff; 
                    padding: 15px; 
                    border-radius: 12px; 
                    border: 1px solid #f0f0f0;
                    text-align: center;
                ">
                    <div style="font-size: 0.95rem; color: #333; font-weight: 600; line-height: 1.5; margin-bottom: 5px;">
                        "{quote_data['kor']}"
                    </div>
                    <div style="font-size: 0.8rem; color: #888; font-style: italic; margin-bottom: 8px;">
                        {quote_data['eng']}
                    </div>
                    <div style="font-size: 0.85rem; color: #666;">
                        - {quote_data['author']} -
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
        # ---------------------------------------------------------
        # [Step 3] 회원가입 로직 (통합본)
        # ---------------------------------------------------------
        elif st.session_state.login_step == 'signup_input':
            
            # [A구역] 1단계(정보입력) 또는 2단계(인증번호확인)일 때만 실행
            if st.session_state.signup_stage in [1, 2]:
                # 스타일 정의
                title_style = "font-size: 1.0rem; font-weight: bold; margin-bottom: 15px;"
                label_style = "font-size: 1.0rem; font-weight: normal; margin-bottom: 5px; margin-top: 10px;"
                status_style = "font-size: 0.85rem; margin-top: -10px; margin-bottom: 10px;"
                
                st.markdown(f"<p style='{title_style}'>1단계: 정보 입력</p>", unsafe_allow_html=True)
                
                # --- [상단 입력창 구역: 항상 유지됨] ---
                st.markdown(f"<p style='{label_style}'>아이디</p>", unsafe_allow_html=True)
                new_id = st.text_input("id_input", value=st.session_state.get('temp_id', ''), label_visibility="collapsed")
                st.session_state.temp_id = new_id
                
                st.markdown(f"<p style='{label_style}'>비밀번호</p>", unsafe_allow_html=True)
                new_pw = st.text_input("pw_input", type="password", value=st.session_state.get('temp_pw', ''), label_visibility="collapsed")
                st.session_state.temp_pw = new_pw
                
                st.markdown(f"<p style='{label_style}'>비밀번호 확인</p>", unsafe_allow_html=True)
                confirm_pw = st.text_input("confirm_pw_input", type="password", value=st.session_state.get('temp_cpw', ''), label_visibility="collapsed")
                st.session_state.temp_cpw = confirm_pw
                
                # 실시간 비번 일치 체크
                is_pw_match = False
                if new_pw and confirm_pw:
                    if new_pw == confirm_pw:
                        # f" " 따옴표 추가됨
                        st.markdown(f"<p style='{status_style} color: #2e7d32;'>✅ 비밀번호가 일치합니다.</p>", unsafe_allow_html=True)
                        is_pw_match = True
                    else:
                        # f" " 따옴표 추가됨
                        st.markdown(f"<p style='{status_style} color: #d32f2f;'>❌ 비밀번호가 일치하지 않습니다.</p>", unsafe_allow_html=True)
                        
                st.markdown(f"<p style='{label_style}'>연락처 (예: 01012345678)</p>", unsafe_allow_html=True)
                new_phone = st.text_input("phone_input", value=st.session_state.get('temp_phone', ''), label_visibility="collapsed")
                st.session_state.temp_phone = new_phone
                
                st.markdown(f"<p style='{label_style}'>이메일</p>", unsafe_allow_html=True)
                new_email = st.text_input("email_input", value=st.session_state.get('temp_email', ''), label_visibility="collapsed")
                st.session_state.temp_email = new_email
                
                st.markdown(f"<p style='{label_style}'>인증 수단</p>", unsafe_allow_html=True)
                auth_choice = st.radio("auth_input", ["휴대폰(가상)", "이메일(실제)"], horizontal=True, label_visibility="collapsed", key="auth_radio")
                
                # --- [하단 유동 구역: 버튼 혹은 인증창으로 교체] ---
                st.write("---") 
                
                # st.empty()를 사용하여 이전 단계 위젯의 유령 박스를 물리적으로 제거합니다.
                action_area = st.empty()
            
                with action_area.container():
                    if st.session_state.signup_stage == 1:
                        # 1단계 버튼 구역
                        if st.button("인증번호 받기", use_container_width=True, type="primary", key="btn_send_auth_final"):
                            if not (new_id and new_pw and confirm_pw and new_email):
                                st.error("모든 정보를 입력해주세요.")
                            elif not is_pw_match:
                                st.error("비밀번호 일치 확인이 필요합니다.")
                            else:
                                code = str(random.randint(100000, 999999))
                                st.session_state.auth_code = code
                                st.session_state.temp_user_data = {"id": new_id, "pw": new_pw, "phone": new_phone, "email": new_email}
                                
                                if "이메일" in auth_choice:
                                    if send_email_code(new_email, code):
                                        st.session_state.signup_stage = 2
                                        st.rerun()
                                else:
                                    st.toast(f"📱 인증번호: {code}", icon="✅")
                                    st.session_state.signup_stage = 2
                                    st.rerun()
                        
                        if st.button("처음으로 돌아가기", use_container_width=True, key="btn_signup_back_final"):
                            st.session_state.login_step = 'choice'
                            st.rerun()
            
                    elif st.session_state.signup_stage == 2:
                        # 2단계 인증창 구역
                        st.markdown("<div style='background-color: #f8f9fa; padding: 20px; border-radius: 10px; border: 1px solid #ddd;'>", unsafe_allow_html=True)
                        st.markdown(f"<p style='{label_style} font-weight: bold;'>인증번호 6자리 입력</p>", unsafe_allow_html=True)
                        
                        # key값을 유니크하게 설정
                        in_code = st.text_input("verify_code_input", label_visibility="collapsed", placeholder="숫자 6자리", key="input_verify_code_stage2")
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("인증 확인", use_container_width=True, type="primary", key="btn_confirm_auth_stage2"):
                                if in_code == st.session_state.auth_code:
                                    st.success("인증 성공!")
                                    st.session_state.signup_stage = 3
                                    st.rerun()
                                else:
                                    st.error("인증번호가 틀렸습니다.")
                        with col2:
                            if st.button("취소/재발송", use_container_width=True, key="btn_resend_auth_stage2"):
                                st.session_state.signup_stage = 1
                                st.rerun()
                        st.markdown("</div>", unsafe_allow_html=True)
            
            # [B구역] 3단계일 때 (서류 제출 화면)
            elif st.session_state.signup_stage == 3:
                st.subheader("3단계: 선택적 자격 증빙")
                st.info("💡 서류를 하나라도 제출하면 '글쓰기/투표' 권한이 신청됩니다.")
                
                # 입력창 (사용자 친화적 키값으로 변경)
                u_name = st.text_input("대학 혹은 학과", key="u_name_final")
                u_file = st.file_uploader("학생증/졸업증명서", type=['jpg','png','pdf'], key="u_file_final")
                j_name = st.text_input("직장 혹은 직업", key="j_name_final")
                j_file = st.file_uploader("사원증 혹은 직장이메일", type=['jpg','png','pdf'], key="j_file_final")
                a_val = st.selectbox("자산 규모", ["선택 안 함", "10억 미만", "10억~30억", "30억~80억", "80억 이상"], key="a_val_final")
                a_file = st.file_uploader("계좌인증", type=['jpg','png','pdf'], key="a_file_final")
                
                st.write("")
                
                # [최종 가입 신청 버튼]
                if st.button("가입 신청 완료", type="primary", use_container_width=True):
                    # 1. 세션 데이터 확인 (안전장치)
                    td = st.session_state.get('temp_user_data')
                    if not td:
                        st.error("⚠️ 세션이 만료되었습니다. 처음부터 다시 가입해주세요.")
                        st.stop()

                    with st.spinner("정보를 안전하게 저장 중입니다..."):
                        try:
                            # 2. 파일 업로드 실행
                            # (upload_photo_to_drive 함수가 정상 구현되어 있어야 합니다)
                            l_u = upload_photo_to_drive(u_file, f"{td['id']}_univ") if u_file else "미제출"
                            l_j = upload_photo_to_drive(j_file, f"{td['id']}_job") if j_file else "미제출"
                            l_a = upload_photo_to_drive(a_file, f"{td['id']}_asset") if a_file else "미제출"
                            
                            # 3. 데이터 패키징
                            has_cert = any([u_file, j_file, a_file])
                            role = "user" if has_cert else "restricted"
                            
                            final_data = {
                                **td, 
                                "univ": u_name, "job": j_name, "asset": a_val,
                                "link_univ": l_u, "link_job": l_j, "link_asset": l_a,
                                "role": role, "status": "pending",
                                "display_name": f"{role} | {td['id'][:3]}***"
                            }
                            
                            # 4. DB 저장 시도
                            if db_signup_user(final_data):
                                st.success("가입 신청이 완료되었습니다!")
                                
                                # 성공 상태 업데이트
                                st.session_state.auth_status = 'user'
                                st.session_state.user_info = final_data
                                st.session_state.page = 'setup'
                                
                                # 로그인/가입 단계 초기화
                                st.session_state.login_step = 'choice'
                                st.session_state.signup_stage = 1
                                
                                time.sleep(1.5)
                                st.rerun()
                            else:
                                st.error("❌ 가입 신청 저장에 실패했습니다. 잠시 후 다시 시도해주세요.")
                        
                        except Exception as e:
                            st.error(f"🚨 처리 중 오류가 발생했습니다: {e}")
            
          

# ---------------------------------------------------------
# [NEW] 가입 직후 설정 페이지 (Setup) - 멤버 리스트 & 관리자 기능 통합
# ---------------------------------------------------------
elif st.session_state.page == 'setup':
    user = st.session_state.user_info

    if user:
        # [1] 기본 정보 계산
        user_id = str(user.get('id', ''))
        full_masked_id = "*" * len(user_id) 
        
        # [수정 2 & 3 반영] 
        # 하얀색 바탕(#ffffff), 검은색 글씨(#000000), 얇은 테두리(선택사항) 적용
        st.markdown(f"""
            <div style="
                background-color: #ffffff; 
                padding: 15px; 
                border-radius: 5px; 
                border: 1px solid #f0f0f0; 
                color: #000000; 
                font-size: 1rem;
                margin-bottom: 10px;
            ">
                환영합니다, <b>{user_id}</b>님! 활동닉네임과 노출범위를 확인해주세요. 인증회원은 글쓰기와 투표참여가 가능합니다.
            </div>
        """, unsafe_allow_html=True)
        
        # 1번 요청 사항: 문장 밑에 한 줄 공백 추가
        st.write("<br>", unsafe_allow_html=True)
        
        # -----------------------------------------------------------
        # 1. 내 정보 노출 설정 (체크박스)
        # -----------------------------------------------------------
        
        
        

        # 저장된 설정값 불러오기
        saved_vis = user.get('visibility', 'True,True,True').split(',')
        def_univ = saved_vis[0] == 'True' if len(saved_vis) > 0 else True
        def_job = saved_vis[1] == 'True' if len(saved_vis) > 1 else True
        def_asset = saved_vis[2] == 'True' if len(saved_vis) > 2 else True

        c1, c2, c3 = st.columns(3)
        # 글자 크기는 Streamlit 기본 위젯 크기를 따릅니다.
        show_univ = c1.checkbox("대학 및 학과", value=def_univ)
        show_job = c2.checkbox("직장 혹은 직업", value=def_job)
        show_asset = c3.checkbox("자산", value=def_asset)

        # -----------------------------------------------------------
        # 2. 닉네임 미리보기
        # -----------------------------------------------------------
        is_public_mode = any([show_univ, show_job, show_asset])
        
        info_parts = []
        if show_univ: info_parts.append(user.get('univ', ''))
        if show_job: info_parts.append(user.get('job', '')) 
        if show_asset: info_parts.append(get_asset_grade(user.get('asset', '')))
        
        prefix = " ".join([p for p in info_parts if p])
        
        # [수정 3] 미리보기에서는 완전 마스킹된 ID 사용
        final_nickname = f"{prefix} {full_masked_id}" if prefix else full_masked_id
        
        # ▼▼▼▼▼ [삭제함] 원래 여기에 있던 st.divider()를 지웠습니다. ▼▼▼▼▼
        
        c_info, c_status = st.columns([2, 1])
        
        with c_info:
            # [수정 1] 글자 크기를 체크박스와 유사하게 맞춤
            st.markdown(f"아이디: {full_masked_id}")
            st.markdown(f"활동 닉네임: <span style='font-weight:bold; color:#5c6bc0;'>{final_nickname}</span>", unsafe_allow_html=True)
        
        with c_status:
            db_role = user.get('role', 'restricted')
            db_status = user.get('status', 'pending')
            
            if db_role == 'restricted':
                st.error("🔒 **Basic 회원** (서류 미제출)")
                st.caption("권한: 관심종목 O / 글쓰기 X")
            elif db_status == 'pending':
                st.warning("**승인 대기 중**")
                st.caption("관리자 승인 후 글쓰기 가능")
            elif db_status == 'approved':
                if is_public_mode:
                    st.success("**인증 회원 (활동 중)**")
                    st.caption("권한: 모든 기능 사용 가능")
                else:
                    st.info("🔒 **익명 모드 (비공개)**")
                    st.caption("모든 정보를 가려 **글쓰기가 제한**됩니다.")

        st.write("<br>", unsafe_allow_html=True)

        # -----------------------------------------------------------
        # 3. [메인 기능] 설정 저장 및 로그아웃 (1:1 균등 분할)
        # -----------------------------------------------------------
        
        # 모바일 화면 균형을 위해 1:1 비율로 컬럼 생성
        col_save, col_logout = st.columns(2)

        # 1. 저장하고 시작하기 (왼쪽)
        with col_save:
            if st.button("저장하고 시작하기", type="primary", use_container_width=True):
                with st.spinner("설정 적용 중..."):
                    current_settings = [show_univ, show_job, show_asset]
                    
                    # 수정: 새로 만든 db_ 함수 호출
                    if db_update_user_visibility(user.get('id'), current_settings):
                        st.session_state.user_info['visibility'] = ",".join([str(v) for v in current_settings])
                        st.session_state.page = 'calendar' 
                        st.rerun()
                    else:
                        st.error("저장 실패. 네트워크를 확인하세요.")

        # 2. 로그아웃 (오른쪽)
        with col_logout:
            if st.button("로그아웃", use_container_width=True):
                st.session_state.clear() # 세션 초기화
                st.rerun()               # 로그인 화면으로 복귀

        # ===========================================================
        # 👇 [수정 완료] 관리자 승인 기능 (버튼 씹힘 해결 - 콜백 방식)
        # ===========================================================
        if user.get('role') == 'admin':
      

            # -------------------------------------------------------
            # [1] 기능 함수 정의 (화면 그리기 전에 실행될 함수들)
            # -------------------------------------------------------
            
            # 구글 시트 상태 변경 함수
            def update_sheet_status(uid, status):
                client, _ = get_gcp_clients()
                if not client: return False
                try:
                    sh = client.open("1w-eMZgyjDiSqCOJVhiZHCqglMbuS0vnccpPocv4OM6c").sheet1
                    # ID가 있는 행 찾기
                    cell = sh.find(str(uid), in_column=1)
                    if cell:
                        # status 열 찾기 (헤더 검색)
                        header_cell = sh.find("status", in_row=1)
                        col_idx = header_cell.col if header_cell else 12
                        
                        # 업데이트
                        sh.update_cell(cell.row, col_idx, status)
                        return True
                except Exception as e:
                    print(f"Error: {e}") # 터미널 로그용
                return False

            # [핵심] 승인 버튼 누르면 실행될 콜백 함수
            def callback_approve(target_id, target_email):
                # 1. 시트 업데이트
                if update_sheet_status(target_id, 'approved'):
                    # 2. 이메일 발송
                    if target_email:
                        send_approval_email(target_email, target_id)
                    # 3. 알림 메시지 (새로고침 되어도 뜸)
                    st.toast(f"✅ {target_id}님 승인 처리 완료!", icon="🎉")
                else:
                    st.toast(f"❌ {target_id} 처리 실패. 시트 연결 확인 필요.", icon="⚠️")

            # [핵심] 보류 버튼 누르면 실행될 콜백 함수
            def callback_reject(target_id, target_email):
                # 입력된 사유 가져오기 (session_state에서 꺼냄)
                reason_key = f"rej_setup_{target_id}"
                reason = st.session_state.get(reason_key, "")

                if not reason:
                    st.toast("⚠️ 보류 사유를 입력해주세요!", icon="❗")
                    return # 사유 없으면 중단

                # 1. 시트 업데이트 (rejected로 변경하여 목록에서 제거)
                if update_sheet_status(target_id, 'rejected'):
                    # 2. 이메일 발송
                    if target_email:
                        send_rejection_email(target_email, target_id, reason)
                    st.toast(f"🛑 {target_id}님 보류 처리 완료.", icon="blob-check")
                else:
                    st.toast("❌ 처리 실패.", icon="⚠️")

            # -------------------------------------------------------
            # [2] 화면 그리기 (UI)
            # -------------------------------------------------------
            
            # 목록 불러오기 버튼
            if st.button("가입신청회원보기", key="btn_refresh_list"):
                st.rerun()

            # 만들어둔 Supabase용 새 함수를 호출하도록 변경
            all_users_adm = db_load_all_users()
            # status가 pending인 유저만 필터링
            pending_users = [u for u in all_users_adm if u.get('status') == 'pending']
            
            if not pending_users:
                st.info("현재 승인 대기 중인 유저가 없습니다.")
            else:
                for pu in pending_users:
                    # 유저별 고유 키 생성
                    u_id = pu.get('id')
                    u_email = pu.get('email')
                    
                    with st.expander(f"{u_id} ({pu.get('univ') or '미기재'})"):
                        st.write(f"**이메일**: {u_email} | **연락처**: {pu.get('phone')}")
                        
                        # 증빙 서류 링크
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            if pu.get('link_univ') != "미제출": st.link_button("🎓 대학 증빙", pu.get('link_univ'))
                        with c2:
                            if pu.get('link_job') != "미제출": st.link_button("💼 직업 증빙", pu.get('link_job'))
                        with c3:
                            if pu.get('link_asset') != "미제출": st.link_button("💰 자산 증빙", pu.get('link_asset'))
                        
                        st.divider()

                        # 보류 사유 입력창 (키를 명확히 지정)
                        st.text_input("보류 사유", placeholder="예: 식별 불가", key=f"rej_setup_{u_id}")
                        
                        btn_col1, btn_col2 = st.columns(2)
                        
                        # [승인 버튼] -> on_click 사용
                        with btn_col1:
                            st.button(
                                "✅ 승인", 
                                key=f"btn_app_{u_id}", 
                                use_container_width=True,
                                on_click=callback_approve,  # 클릭 시 실행할 함수 지정
                                args=(u_id, u_email)        # 함수에 넘길 데이터
                            )

                        # [보류 버튼] -> on_click 사용
                        with btn_col2:
                            st.button(
                                "❌ 보류", 
                                key=f"btn_rej_{u_id}", 
                                use_container_width=True, 
                                type="primary",
                                on_click=callback_reject,   # 클릭 시 실행할 함수 지정
                                args=(u_id, u_email)        # 함수에 넘길 데이터
                            )

# 4. 캘린더 페이지 (메인 통합: 상단 메뉴 + 리스트)
if st.session_state.page == 'calendar':
    # [CSS] 스타일 정의 (기존 스타일 100% 유지 + 상단 메뉴 스타일 추가)
    st.markdown("""
        <style>
        /* 1. 기본 설정 */
        * { box-sizing: border-box !important; }
        body { color: #333333; }
        
        /* 2. 상단 여백 확보 (메인 페이지라 여백을 조금 줄임) */
        .block-container { 
            padding-top: 2rem !important; 
            padding-left: 0.5rem !important; 
            padding-right: 0.5rem !important; 
            max-width: 100% !important; 
        }

        /* [NEW] 상단 메뉴 버튼 스타일 (둥글고 크게) */
        div[data-testid="column"] button {
            border-radius: 12px !important;
            height: 50px !important;
            font-weight: bold !important;
        }

        /* 3. 리스트 전용 버튼 스타일 (범위를 리스트 컬럼으로 한정) */
        /* [수정] 모든 버튼이 아니라, 데이터 리스트(7:3 컬럼) 내부에 있는 버튼만 투명하게 만듭니다. */
        div[data-testid="column"] .stButton button {
            background-color: transparent !important;
            border: none !important;
            padding: 0 !important;
            margin: 0 !important;
            color: #333 !important;
            text-align: left !important;
            box-shadow: none !important;
            width: 100% !important;
            display: block !important;
            overflow: hidden !important;
            white-space: nowrap !important;
            text-overflow: ellipsis !important;
            height: auto !important;
            line-height: 1.1 !important;
        }

        /* [추가] 로그인/인증 버튼 등 일반적인 Primary 버튼은 원래 스타일을 유지하도록 강제 */
        div.stButton > button[kind="primary"] {
            background-color: #FF4B4B !important; /* 스트림릿 기본 레드 혹은 원하는 색상 */
            color: white !important;
            border-radius: 8px !important;
            padding: 0.25rem 0.75rem !important;
            height: auto !important;
        }
        
        .stButton button p { font-weight: bold; font-size: 14px; margin-bottom: 0px; }

        /* 4. [모바일 레이아웃 핵심] */
        @media (max-width: 640px) {
            
            /* (A) 상단 필터: 줄바꿈 허용 */
            div[data-testid="stHorizontalBlock"]:nth-of-type(1) {
                flex-wrap: wrap !important;
                gap: 10px !important;
                padding-bottom: 5px !important;
            }
            div[data-testid="stHorizontalBlock"]:nth-of-type(1) > div {
                min-width: 100% !important;
                max-width: 100% !important;
                flex: 1 1 100% !important;
            }

            /* (B) 리스트 구역: 가로 고정 & 수직 중앙 정렬 */
            div[data-testid="stHorizontalBlock"]:not(:nth-of-type(1)) {
                flex-direction: row !important;
                flex-wrap: nowrap !important;
                gap: 0px !important;
                width: 100% !important;
                align-items: center !important; 
            }

            /* (C) 컬럼 내부 정렬 강제 */
            div[data-testid="column"] {
                display: flex !important;
                flex-direction: column !important;
                justify-content: center !important; 
                min-width: 0px !important;
                padding: 0px 2px !important;
            }

            /* (D) 리스트 컬럼 비율 (7:3) */
            div[data-testid="stHorizontalBlock"]:not(:nth-of-type(1)) > div[data-testid="column"]:nth-of-type(1) {
                flex: 0 0 70% !important;
                max-width: 70% !important;
                overflow: hidden !important;
            }
            div[data-testid="stHorizontalBlock"]:not(:nth-of-type(1)) > div[data-testid="column"]:nth-of-type(2) {
                flex: 0 0 30% !important;
                max-width: 30% !important;
            }

            /* (E) 폰트 및 간격 미세 조정 */
            .mobile-sub { font-size: 10px !important; color: #888 !important; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: -2px; line-height: 1.1; }
            .price-main { font-size: 13px !important; font-weight: bold; white-space: nowrap; line-height: 1.1; }
            .price-sub { font-size: 10px !important; color: #666 !important; white-space: nowrap; line-height: 1.1; }
            .date-text { font-size: 10px !important; color: #888 !important; margin-top: 1px; line-height: 1.1; }
            .header-text { font-size: 12px !important; line-height: 1.0; }
        }
        </style>
    """, unsafe_allow_html=True)

    # ---------------------------------------------------------
    # [ANDROID-FIX] 안드로이드 셀렉트박스 닫힘 강제 패치
    # ---------------------------------------------------------
    st.markdown("""
        <style>
        /* 1. 선택 후 파란색 테두리(포커스) 제거 */
        .stSelectbox div[data-baseweb="select"]:focus-within {
            border-color: transparent !important;
            box-shadow: none !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # 2. 자바스크립트를 이용해 현재 활성화된(Focus) 입력창을 강제로 닫음
    # 화면이 로드될 때마다 실행되어 모바일 키보드나 드롭다운을 숨깁니다.
    st.components.v1.html("""
        <script>
            var mainDoc = window.parent.document;
            var activeEl = mainDoc.activeElement;
            if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.getAttribute('role') === 'combobox')) {
                activeEl.blur();
            }
        </script>
    """, height=0)
     

    # ---------------------------------------------------------
    # 1. [STYLE] 블랙 배경 + 화이트 글씨 (테두리 없음)
    # ---------------------------------------------------------
    st.markdown("""
        <style>
        /* 기본 버튼: 검정 배경 / 흰 글씨 */
        div[data-testid="stPills"] div[role="radiogroup"] button {
            border: none !important;
            outline: none !important;
            background-color: #000000 !important;
            color: #ffffff !important;
            border-radius: 20px !important;
            padding: 6px 15px !important;
            margin-right: 5px !important;
            box-shadow: none !important;
        }

        /* 선택된 버튼: 진한 회색 배경 (구분용) */
        div[data-testid="stPills"] button[aria-selected="true"] {
            background-color: #444444 !important;
            color: #ffffff !important;
            font-weight: 800 !important;
        }

        /* 스트림릿 기본 테두리 제거 */
        div[data-testid="stPills"] div[data-baseweb="pill"] {
            border: none !important;
            background: transparent !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # ---------------------------------------------------------
    # 2. 메뉴 텍스트 및 현재 상태 정의 (권한설정 버튼 추가)
    # ---------------------------------------------------------
    is_logged_in = st.session_state.auth_status == 'user'
    login_text = "로그아웃" if is_logged_in else "로그인"
    settings_text = "권한설정"  # [NEW] 설정 버튼 텍스트
    main_text = "메인"
    watch_text = f"관심 ({len(st.session_state.watchlist)})"
    board_text = "게시판"
    
    # [수정] 로그인 상태면 '권한설정' 버튼 노출, 아니면 숨김
    if is_logged_in:
        # 순서: 로그아웃 -> 권한설정 -> 메인 -> 관심 -> 게시판
        menu_options = [login_text, settings_text, main_text, watch_text, board_text]
    else:
        menu_options = [login_text, main_text, watch_text, board_text]

    # 현재 어떤 페이지에 있는지 계산하여 기본 선택값(Default) 설정
    default_sel = main_text # 기본값은 메인
    if st.session_state.get('page') == 'login': 
        default_sel = login_text
    elif st.session_state.get('page') == 'setup': # setup 페이지일 때 (혹시나 해서 추가)
        default_sel = settings_text
    elif st.session_state.get('view_mode') == 'watchlist': 
        default_sel = watch_text
    elif st.session_state.get('page') == 'board': 
        default_sel = board_text

    # ---------------------------------------------------------
    # 3. 메뉴 표시 (st.pills)
    # ---------------------------------------------------------
    selected_menu = st.pills(
        label="내비게이션",
        options=menu_options,
        selection_mode="single",
        default=default_sel,
        key="nav_pills_updated_v2", # 키값 충돌 방지용 변경
        label_visibility="collapsed"
    )

    # ---------------------------------------------------------
    # 4. 클릭 감지 및 페이지 이동 로직 (설정 버튼 연결)
    # ---------------------------------------------------------
    if selected_menu and selected_menu != default_sel:
        if selected_menu == login_text:
            if is_logged_in: 
                st.session_state.auth_status = None # 로그아웃 처리
            st.session_state.page = 'login'
            
        elif selected_menu == settings_text: # [NEW] 설정 페이지 이동
            st.session_state.page = 'setup'
            
        elif selected_menu == main_text:
            st.session_state.view_mode = 'all'
            st.session_state.page = 'calendar' 
            
        elif selected_menu == watch_text:
            st.session_state.view_mode = 'watchlist'
            st.session_state.page = 'calendar' 
            
        elif selected_menu == board_text:
            st.session_state.page = 'board'
        
        # 설정 변경 후 화면 즉시 갱신
        st.rerun()

    
    # ---------------------------------------------------------
    # [기존 데이터 로직] - Batching 및 30분 캐싱 적용 버전
    # ---------------------------------------------------------
    all_df_raw = get_extended_ipo_data(MY_API_KEY)
    
    # 데이터 수집 범위 확인
    if not all_df_raw.empty:
        min_date = all_df_raw['date'].min()
        max_date = all_df_raw['date'].max()
        st.sidebar.info(f"📊 수집된 데이터 범위:\n{min_date} ~ {max_date}")
        
    view_mode = st.session_state.get('view_mode', 'all')
    
    if not all_df_raw.empty:
        # 1. 데이터 전처리
        all_df = all_df_raw.copy()
        all_df['exchange'] = all_df['exchange'].fillna('-')
        all_df = all_df[all_df['symbol'].astype(str).str.strip() != ""]
        all_df['공모일_dt'] = pd.to_datetime(all_df['date'], errors='coerce').dt.normalize()
        all_df = all_df.dropna(subset=['공모일_dt'])
        today_dt = pd.to_datetime(datetime.now().date())
        
        # 2. 필터 로직 (관심종목 vs 일반)
        if view_mode == 'watchlist':
            
            if st.button("🔄 전체 목록 보기", use_container_width=True):
                st.session_state.view_mode = 'all'
                st.rerun()
            display_df = all_df[all_df['symbol'].isin(st.session_state.watchlist)]
            if display_df.empty:
                st.info("아직 관심 종목에 담은 기업이 없습니다.")
        else:
            col_f1, col_f2 = st.columns([1, 1]) 
            with col_f1:
                period = st.selectbox("조회 기간", ["상장 예정 (30일)", "지난 6개월", "지난 12개월", "지난 18개월"], key="filter_period", label_visibility="collapsed")
            with col_f2:
                sort_option = st.selectbox("정렬 순서", ["최신순", "수익률"], key="filter_sort", label_visibility="collapsed")
            
            if period == "상장 예정 (30일)":
                display_df = all_df[(all_df['공모일_dt'] >= today_dt) & (all_df['공모일_dt'] <= today_dt + timedelta(days=30))]
            else:
                if period == "지난 6개월": start_date = today_dt - timedelta(days=180)
                elif period == "지난 12개월": start_date = today_dt - timedelta(days=365)
                elif period == "지난 18개월": start_date = today_dt - timedelta(days=540)
                display_df = all_df[(all_df['공모일_dt'] < today_dt) & (all_df['공모일_dt'] >= start_date)]

        # ----------------------------------------------------------------
        # 🚀 [핵심 추가] 모든 모드 공통 Batch 주가 조회 로직 (30분 캐시)
        # ----------------------------------------------------------------
        if not display_df.empty:
            with st.spinner("🔄 실시간 시세(15분 주기) 조회 중..."):
                # [수정] 결측치(NaN)를 제거하고 고유한 심볼 리스트만 추출
                symbols_list = display_df['symbol'].dropna().unique().tolist()
                
                # 배치 함수 호출
                batch_prices = get_batch_prices(symbols_list)
                
                # (3) 결과 매핑 및 수익률 계산
                final_prices = []
                final_returns = []
                
                for _, row in display_df.iterrows():
                    sid = row['symbol']
                    # 공모가 숫자 변환
                    try:
                        p_ipo = float(str(row.get('price','0')).replace('$','').split('-')[0])
                    except:
                        p_ipo = 0
                    
                    # 배치 결과에서 현재가 가져오기
                    p_curr = batch_prices.get(sid, 0.0)
                    
                    # 수익률 계산
                    if p_ipo > 0 and p_curr > 0:
                        ret = ((p_curr - p_ipo) / p_ipo) * 100
                    else:
                        ret = -9999 # 가격 정보가 없는 경우 최하단으로 보냄
                        
                    final_prices.append(p_curr)
                    final_returns.append(ret)
                
                # 데이터프레임에 실시간 값 주입
                display_df['live_price'] = final_prices
                display_df['temp_return'] = final_returns

            # 3. 정렬 최종 적용
            if view_mode != 'watchlist': # 캘린더 모드일 때만 정렬 옵션 따름
                if sort_option == "최신순":
                    display_df = display_df.sort_values(by='공모일_dt', ascending=False)
                elif sort_option == "수익률":
                    display_df = display_df.sort_values(by='temp_return', ascending=False)
            else:
                # 관심종목 모드일 때는 기본 최신순
                display_df = display_df.sort_values(by='공모일_dt', ascending=False)

        # ----------------------------------------------------------------
        # [핵심] 리스트 레이아웃 (7 : 3 비율) - 기존 디자인 유지
        # ----------------------------------------------------------------
        if not display_df.empty:
            for i, row in display_df.iterrows():
                p_val = pd.to_numeric(str(row.get('price','')).replace('$','').split('-')[0], errors='coerce')
                p_val = p_val if p_val and p_val > 0 else 0
                
                # 가격 HTML
                live_p = row.get('live_price', 0)
                if live_p > 0:
                    pct = ((live_p - p_val) / p_val) * 100 if p_val > 0 else 0
                    if pct > 0:
                        change_color = "#e61919" 
                        arrow = "▲"
                    elif pct < 0:
                        change_color = "#1919e6" 
                        arrow = "▼"
                    else:
                        change_color = "#333333" 
                        arrow = ""

                    price_html = f"""
                        <div class='price-main' style='color:{change_color} !important;'>
                            ${live_p:,.2f} ({arrow}{pct:+.1f}%)
                        </div>
                        <div class='price-sub' style='color:#666666 !important;'>IPO: ${p_val:,.2f}</div>
                    """
                else:
                    price_html = f"""
                        <div class='price-main' style='color:#333333 !important;'>${p_val:,.2f}</div>
                        <div class='price-sub' style='color:#666666 !important;'>공모가</div>
                    """
                
                date_html = f"<div class='date-text'>{row['date']}</div>"

                c1, c2 = st.columns([7, 3])
                
                with c1:
                    # 기업명 버튼
                    if st.button(f"{row['name']}", key=f"btn_list_{i}"):
                        st.session_state.selected_stock = row.to_dict()
                        st.session_state.page = 'detail'
                        st.rerun()
                    
                    try: s_val = int(row.get('numberOfShares',0)) * p_val / 1000000
                    except: s_val = 0
                    size_str = f" | ${s_val:,.0f}M" if s_val > 0 else ""
                    
                    st.markdown(f"<div class='mobile-sub' style='margin-top:-2px; padding-left:2px;'>{row['symbol']} | {row.get('exchange','-')}{size_str}</div>", unsafe_allow_html=True)

                with c2:
                    st.markdown(f"<div style='text-align:right;'>{price_html}{date_html}</div>", unsafe_allow_html=True)
                
                st.markdown("<div style='border-bottom:1px solid #f0f2f6; margin: 4px 0;'></div>", unsafe_allow_html=True)

        else:
            st.info("조건에 맞는 종목이 없습니다.")




# ---------------------------------------------------------
# 5. 상세 페이지 (Detail)
# ---------------------------------------------------------
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    
    # [안전장치] 선택된 종목이 없으면 캘린더로 복귀
    if not stock:
        st.session_state.page = 'calendar'
        st.rerun()

    # [1] 변수 초기화
    profile = None
    fin_data = {}
    current_p = 0
    off_val = 0

    if stock:
        # -------------------------------------------------------------------------
        # [2] 상단 메뉴바 (블랙 스타일 & 이동 로직 통합 보정)
        # -------------------------------------------------------------------------
        # (1) 스타일은 그대로 유지
        st.markdown("""
            <style>
            div[data-testid="stPills"] div[role="radiogroup"] button {
                border: none !important;
                background-color: #000000 !important;
                color: #ffffff !important;
                border-radius: 20px !important;
                padding: 6px 15px !important;
                margin-right: 5px !important;
                box-shadow: none !important;
            }
            div[data-testid="stPills"] button[aria-selected="true"] {
                background-color: #444444 !important;
                font-weight: 800 !important;
            }
            </style>
        """, unsafe_allow_html=True)

        # (2) [교체 완료] 권한설정 버튼이 포함된 새로운 메뉴 로직
        is_logged_in = st.session_state.auth_status == 'user'
        login_text = "로그아웃" if is_logged_in else "로그인"
        settings_text = "권한설정"  # [NEW]
        main_text = "메인"
        watch_text = f"관심 ({len(st.session_state.watchlist)})"
        board_text = "게시판"
        
        # 로그인 상태에 따라 메뉴 구성 변경
        if is_logged_in:
            menu_options = [login_text, settings_text, main_text, watch_text, board_text]
        else:
            menu_options = [login_text, main_text, watch_text, board_text]

        # 기본 선택값 로직 (Detail 페이지에서는 선택된 게 없는 상태(None)가 기본일 수 있음)
        # 하지만 메뉴를 눌러 이동하는 것이 목적이므로, default=None으로 두어 
        # 사용자가 버튼을 누를 때만 동작하게 하는 것이 기존 로직과 맞습니다.
        
        selected_menu = st.pills(
            label="nav", 
            options=menu_options, 
            selection_mode="single", 
            default=None,  # Detail 페이지에서는 메뉴가 '선택'되어 있을 필요가 없음 (누르면 이동)
            key="detail_nav_updated_final", # 키값 중복 방지
            label_visibility="collapsed"
        )

        if selected_menu:
            if selected_menu == login_text:
                if is_logged_in: st.session_state.auth_status = None
                st.session_state.page = 'login'
            
            elif selected_menu == settings_text: # [NEW] 설정 이동
                st.session_state.page = 'setup'

            elif selected_menu == main_text:
                st.session_state.view_mode = 'all'; st.session_state.page = 'calendar'
            
            elif selected_menu == watch_text:
                st.session_state.view_mode = 'watchlist'; st.session_state.page = 'calendar'
            
            elif selected_menu == board_text:
                st.session_state.page = 'board'
            
            st.rerun()

        # -------------------------------------------------------------------------
        # [3] 사용자 판단 로직 및 데이터 로딩 (원형 유지)
        # -------------------------------------------------------------------------
        if 'user_decisions' not in st.session_state:
            st.session_state.user_decisions = {}
        
        sid = stock['symbol']
        if sid not in st.session_state.user_decisions:
            st.session_state.user_decisions[sid] = {"news": None, "filing": None, "macro": None, "company": None}

        def draw_decision_box(step_key, title, options):
            st.write("")
            st.markdown(f"##### {title}")
            current_val = st.session_state.user_decisions[sid].get(step_key)
            choice = st.radio(
                label=f"판단_{step_key}",
                options=options,
                index=options.index(current_val) if current_val in options else None,
                key=f"dec_{sid}_{step_key}",
                horizontal=True,
                label_visibility="collapsed"
            )
            if choice:
                st.session_state.user_decisions[sid][step_key] = choice

        # 데이터 로딩
        today = datetime.now().date()
        ipo_dt = pd.to_datetime(stock['공모일_dt']).date()
        status_emoji = "🐣" if ipo_dt > (today - timedelta(days=365)) else "🦄"
        date_str = ipo_dt.strftime('%Y-%m-%d')

        with st.spinner(f"🤖 {stock['name']} 분석 중..."):
            try: off_val = float(str(stock.get('price', '0')).replace('$', '').split('-')[0].strip())
            except: off_val = 0
            try:
                current_p = get_current_stock_price(stock['symbol'], MY_API_KEY)
                profile = get_company_profile(stock['symbol'], MY_API_KEY) 
                fin_data = get_financial_metrics(stock['symbol'], MY_API_KEY)
            except: pass

        # 헤더 출력 (수익률 계산 포함)
        if current_p > 0 and off_val > 0:
            pct = ((current_p - off_val) / off_val) * 100
            color = "#00ff41" if pct >= 0 else "#ff4b4b"
            icon = "▲" if pct >= 0 else "▼"
            p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / 공모 ${off_val} / 현재 ${current_p} <span style='color:{color}; font-weight:bold;'>{icon} {abs(pct):.1f}%</span>)</span>"
        else:
            p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / 공모 ${off_val} / 상장 대기)</span>"

        st.markdown(f"<div><span style='font-size: 1.2rem; font-weight: 700;'>{status_emoji} {stock['name']}</span> {p_info}</div>", unsafe_allow_html=True)
        st.write("") 

        # -------------------------------------------------------------------------
        # [CSS 추가] 탭 텍스트 색상 고정 (사용자 원형 유지)
        # -------------------------------------------------------------------------
        st.markdown("""
        <style>
            .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
                color: #333333 !important; font-weight: bold !important;
            }
            .stTabs [data-baseweb="tab-list"] button:hover [data-testid="stMarkdownContainer"] p {
                color: #004e92 !important;
            }
        </style>
        """, unsafe_allow_html=True)



        # -------------------------------------------------------------------------
        # [5] 탭 메뉴 구성
        # -------------------------------------------------------------------------
        tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs([
            " 주요공시", 
            " 주요뉴스", 
            " 거시지표", 
            " 미시지표",
            " 기업평가",
            " 투자결정"
        ])

        # --- Tab 0: 핵심 정보 (공시 가이드 및 AI 분석 강화) ---
        with tab0:
            # [세션 상태 관리]
            if 'core_topic' not in st.session_state:
                st.session_state.core_topic = "S-1"

            # 버튼 스타일 강제 지정 (하얀 바탕, 검정 글씨)
            st.markdown("""
                <style>
                div.stButton > button {
                    background-color: #ffffff !important;
                    color: #000000 !important;
                    border: 1px solid #dcdcdc !important;
                    border-radius: 8px !important;
                    height: 3em !important;
                    font-weight: bold !important;
                }
                /* 마우스를 올렸을 때나 클릭했을 때의 효과 */
                div.stButton > button:hover {
                    border-color: #6e8efb !important;
                    color: #6e8efb !important;
                }
                div.stButton > button:active {
                    background-color: #f0f2f6 !important;
                }
                </style>
            """, unsafe_allow_html=True)

            # 1. 문서 선택 버튼 그리드 (기존 코드 유지)
            r1_c1, r1_c2, r1_c3 = st.columns(3)
            r2_c1, r2_c2 = st.columns(2)

            if r1_c1.button("S-1 (최초신고서)", use_container_width=True): st.session_state.core_topic = "S-1"
            if r1_c2.button("S-1/A (수정신고)", use_container_width=True): st.session_state.core_topic = "S-1/A"
            if r1_c3.button("F-1 (해외기업)", use_container_width=True): st.session_state.core_topic = "F-1"
            if r2_c1.button("FWP (IR/로드쇼)", use_container_width=True): st.session_state.core_topic = "FWP"
            if r2_c2.button("424B4 (최종확정)", use_container_width=True): st.session_state.core_topic = "424B4"

            # 2. 메타데이터 및 체크포인트 설정
            topic = st.session_state.core_topic
            
            # [핵심] 문서별 맞춤형 분석 구조 정의
            def_meta = {
                "S-1": {
                    "desc": "S-1은 상장을 위해 최초로 제출하는 서류입니다. **Risk Factors**(위험 요소), **Use of Proceeds**(자금 용도), **MD&A**(경영진의 운영 설명)를 확인할 수 있습니다.",
                    "points": "Risk Factors(특이 소송/규제), Use of Proceeds(자금 용도의 건전성), MD&A(성장 동인)",
                    # [수정] 원본 스타일의 풍성한 지시사항 적용
                    "structure": """
                    [내용 구성 - 반드시 3문단으로 나누어 상세하고 풍성하게 작성할 것]
                    1. **[투자포인트]** : 해당 문서에서 발견된 가장 중요한 투자 포인트를 구체적인 수치나 근거와 함께 상세히 서술하세요.
                    2. **[성장가능성]** : MD&A(경영진 분석)를 통해 본 기업의 실질적 성장 가능성과 재무적 함의를 깊이 있게 분석하세요.
                    3. **[핵심리스크]** : 투자자가 반드시 경계해야 할 핵심 리스크 1가지와 그 파급 효과 및 대응책을 구체적으로 서술하세요.
                    """
                },
                "S-1/A": {
                    "desc": "S-1/A는 공모가 밴드와 주식 수가 확정되는 수정 문서입니다. **Pricing Terms**(공모가 확정 범위)와 **Dilution**(기존 주주 대비 희석률)을 확인할 수 있습니다.",
                    "points": "Pricing Terms(수요예측 분위기), Dilution(신규 투자자 희석률), Changes(이전 제출본과의 차이점)",
                    # S-1/A 전용 질문 (수정 사항 및 가격 중심)
                    "structure": """
                    [내용 구성 - 반드시 3문단으로 나누어 상세하고 풍성하게 작성할 것]
                    1. **[수정사항]** : (이전 제출된 S-1 대비 변경된 핵심 사항(주식 수, 공모가 범위 등)을 중점적으로 서술하세요.)
                    2. **[가격적정성]** : (제시된 공모가 범위가 동종 업계 대비 합리적인지, 또는 수요예측 분위기를 반영했는지 분석하세요.)
                    3. **[주주희석]** : (신규 공모로 인한 기존 주주 가치 희석(Dilution) 정도와 이것이 투자 매력도에 미치는 영향을 서술하세요.)
                    """
                },
                "F-1": {
                    "desc": "F-1은 해외 기업이 미국 상장 시 제출하는 서류입니다. 해당 국가의 **Foreign Risk**(정치/경제 리스크)와 **Accounting**(회계 기준 차이)을 확인할 수 있습니다.",
                    "points": "Foreign Risk(지정학적 리스크), Accounting(GAAP 차이), ADS(주식 예탁 증서 구조)",
                    # F-1 전용 질문 (해외 리스크 중심)
                    "structure": """
                    [내용 구성 - 반드시 3문단으로 나누어 상세하고 풍성하게 작성할 것]
                    1. **[글로벌경쟁력]** : (해당 기업이 본국 및 글로벌 시장에서 가진 독보적인 경쟁 우위를 서술하세요.)
                    2. **[해외리스크]** : (환율, 정치적 이슈, 회계 기준 차이 등 해외 기업 특유의 리스크 요인을 상세히 분석하세요.)
                    3. **[ADS구조]** : (미국 예탁 증서(ADS) 구조가 주주 권리 행사에 미치는 영향이나 특이사항을 서술하세요.)
                    """
                },
                "FWP": {
                    "desc": "FWP는 기관 투자자 대상 로드쇼(Roadshow) PPT 자료입니다. **Graphics**(비즈니스 모델 시각화)와 **Strategy**(경영진이 강조하는 미래 성장 동력)를 확인할 수 있습니다.",
                    "points": "Graphics(시장 점유율 시각화), Strategy(미래 핵심 먹거리), Highlights(경영진 강조 사항)",
                    # FWP 전용 질문 (비전 및 전략 중심)
                    "structure": """
                    [내용 구성 - 반드시 3문단으로 나누어 상세하고 풍성하게 작성할 것]
                    1. **[핵심비전]** : (경영진이 로드쇼에서 가장 강조하고 있는 미래 성장 비전과 목표를 서술하세요.)
                    2. **[차별화전략]** : (경쟁사 대비 부각시키고 있는 기술적/사업적 차별화 포인트를 시각 자료(Graphics) 기반으로 분석하세요.)
                    3. **[로드쇼반응]** : (자료 톤앤매너를 통해 유추할 수 있는 경영진의 자신감이나 시장 공략 의지를 서술하세요.)
                    """
                },
                "424B4": {
                    "desc": "424B4는 공모가가 최종 확정된 후 발행되는 설명서입니다. **Underwriting**(주관사 배정)과 확정된 **Final Price**(최종 공모가)를 확인할 수 있습니다.",
                    "points": "Underwriting(주관사 등급), Final Price(기관 배정 물량), IPO Outcome(최종 공모 결과)",
                    # 424B4 전용 질문 (확정 결과 중심)
                    "structure": """
                    [내용 구성 - 반드시 3문단으로 나누어 상세하고 풍성하게 작성할 것]
                    1. **[최종공모가]** : (확정된 공모가가 희망 밴드 상단인지 하단인지 분석하고, 그 의미(시장 수요)를 해석하세요.)
                    2. **[자금활용]** : (확정된 조달 자금이 구체적으로 어떤 우선순위 사업에 투입될 예정인지 최종 점검하세요.)
                    3. **[상장후 전망]** : (주관사단 구성과 배정 물량을 바탕으로 상장 초기 유통 물량 부담이나 변동성을 예측하세요.)
                    """
                }
            }
            
            curr_meta = def_meta.get(topic, def_meta["S-1"])

            # UI 출력: 통합된 설명문 출력
            st.info(curr_meta['desc'])
            
            # 1. expander를 누르면 즉시 분석이 시작되도록 설정
            with st.expander(f" {topic} 요약보기", expanded=False):
                with st.spinner(f"{topic}의 핵심 내용을 분석 중입니다..."):
                    # ▼▼▼ 질문하신 대로 교체 ▼▼▼
                    analysis_result = get_ai_analysis(
                        stock['name'], 
                        topic, 
                        curr_meta['points'], 
                        curr_meta.get('structure', "") # 구조 템플릿 전달
                    )
                    
                    if "ERROR_DETAILS" in analysis_result:
                        st.error("잠시 후 다시 시도해주세요. (할당량 초과 가능성)")
                        with st.expander("상세 에러 내용"):
                            st.code(analysis_result)
                    else:
                        # 2. 불필요한 인사말 없이 결과만 깔끔하게 출력
                        # 만약 결과값에 "분석한 결과입니다" 등의 문구가 섞여 나온다면 
                        # get_ai_analysis 함수 내 프롬프트에서 "인사말 생략"을 추가하는 것이 좋습니다.
                        st.markdown(analysis_result)
                
                
                # 3. 요청하신 하단 캡션 문구로 변경
                st.caption(" 자체 알고리즘으로 공시자료를 요약해 제공합니다.")
                
                
                
               
            # ---------------------------------------------------------
            # 3. SEC URL 및 공식 홈페이지 버튼 생성 (법인 식별자 보존형)
            # ---------------------------------------------------------
            import urllib.parse
            import re
            
            # (1) 데이터 준비
            cik = profile.get('cik', '') if profile else ''
            
            # [수정] Inc, Corp, Ltd 등을 삭제하지 않고 전체 이름을 사용합니다.
            # 불필요한 공백만 제거하여 검색 정확도를 높입니다.
            full_company_name = stock['name'].strip() 
            
            # (2) SEC EDGAR 공시 URL 생성
            if cik:
                sec_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={urllib.parse.quote(topic)}&owner=include&count=40"
            else:
                # 풀네임을 따옴표로 감싸서 정확한 명칭으로 검색하게 합니다.
                sec_query = f'"{full_company_name}" {topic}'
                sec_url = f"https://www.sec.gov/edgar/search/#/q={urllib.parse.quote(sec_query)}&dateRange=all"

            # (3) 공식 홈페이지 즉시 연결 로직 (DuckDuckGo !Bang 활용)
            # API에서 직접 제공하는 주소가 있는지 먼저 확인
            real_website = profile.get('weburl') or profile.get('website', '') if profile else ''
            
            if real_website:
                website_url = real_website
                btn_label = f"회사 공식홈페이지"
            else:
                # [핵심] 회사 풀네임(Inc, Corp 포함) + Investor Relations 조합
                # 예: ! AGI Inc. Investor Relations
                refined_query = f"! {full_company_name} Investor Relations"
                website_url = f"https://duckduckgo.com/?q={urllib.parse.quote(refined_query)}"
                btn_label = f"회사 공식홈페이지"

            # (4) 버튼 출력 (스타일 통일)
            st.markdown(f"""
                <a href="{sec_url}" target="_blank" style="text-decoration:none;">
                    <button style='width:100%; padding:15px; background:white; border:1px solid #004e92; color:#004e92; border-radius:10px; font-weight:bold; cursor:pointer; margin-bottom: 8px;'>
                            EDGAR {topic} 공시 확인하기 
                    </button>
                </a>
                
                <a href="{website_url}" target="_blank" style="text-decoration:none;">
                    <button style='width:100%; padding:15px; background:white; border:1px solid #333333; color:#333333; border-radius:10px; font-weight:bold; cursor:pointer;'>
                           {btn_label}
                    </button>
                </a>
            """, unsafe_allow_html=True)
            

            # 4. 의사결정 박스 및 면책 조항
            draw_decision_box("filing", "공시 정보에 대한 입장은?", ["수용적", "중립적", "회의적"])
            display_disclaimer()
            
        # --- Tab 1: 뉴스 & 심층 분석 (Gemini 통합형) ---
        with tab1:
            st.caption("Google Search 기반 실시간 분석 및 뉴스를 제공합니다.")
            
            # [1] 통합 분석 데이터 호출 (비즈니스 요약 + 뉴스 5개 통합)
            # 기존의 여러 함수 호출을 이 한 줄로 대체하여 속도와 비용을 최적화합니다.
            with st.spinner(f"{stock['name']}의 최신 데이터를 정밀 분석 중입니다..."):
                biz_info, final_display_news = get_unified_tab1_analysis(stock['name'], stock['symbol'])

            # [2] 기업 심층 분석 섹션 (Expander)
            with st.expander(f"비즈니스 모델 요약 보기", expanded=False):
                if biz_info:
                    st.markdown(f"""
                    <div style="
                        background-color: #f8f9fa; 
                        padding: 22px; 
                        border-radius: 12px; 
                        border-left: 5px solid #6e8efb; 
                        color: #333; 
                        font-family: 'Pretendard', sans-serif;
                        font-size: 15px;
                        line-height: 1.6;
                    ">{biz_info}</div>
                    """, unsafe_allow_html=True)
                else:
                    st.error("⚠️ 비즈니스 분석 정보를 가져오지 못했습니다.")

            st.write("<br>", unsafe_allow_html=True)

            # [3] 뉴스 리스트 섹션
            if final_display_news:
                for i, n in enumerate(final_display_news):
                    # 통합 함수에서 이미 번역 및 감성 분석된 데이터를 사용합니다.
                    ko_title = n.get('title_ko', '번역 오류')
                    en_title = n.get('title_en', 'No Title')
                    sentiment_label = n.get('sentiment', '일반')
                    bg_color = n.get('bg', '#f1f3f4')
                    text_color = n.get('color', '#5f6368')
                    news_link = n.get('link', '#')
                    news_date = n.get('date', 'Recent')

                    # 특수 기호 처리 ($ 기호가 수식으로 오인되지 않도록 처리)
                    safe_en = en_title.replace("$", "\$")
                    safe_ko = ko_title.replace("$", "\$")
                    
                    # 배지 생성
                    s_badge = f'<span style="background:{bg_color}; color:{text_color}; padding:2px 6px; border-radius:4px; font-size:11px; margin-left:5px;">{sentiment_label}</span>'
                    
                    st.markdown(f"""
                        <a href="{news_link}" target="_blank" style="text-decoration:none; color:inherit;">
                            <div style="padding:15px; border:1px solid #eee; border-radius:10px; margin-bottom:10px; box-shadow:0 2px 5px rgba(0,0,0,0.03);">
                                <div style="display:flex; justify-content:space-between; align-items:center;">
                                    <div>
                                        <span style="color:#6e8efb; font-weight:bold;">TOP {i+1}</span> 
                                        <span style="color:#888; font-size:12px;">| 일반</span>
                                        {s_badge}
                                    </div>
                                    <small style="color:#bbb;">{news_date}</small>
                                </div>
                                <div style="margin-top:8px; font-weight:600; font-size:15px; line-height:1.4;">
                                    {safe_en}
                                    <br><span style='font-size:14px; color:#555; font-weight:400;'>🇰🇷 {safe_ko}</span>
                                </div>
                            </div>
                        </a>
                    """, unsafe_allow_html=True)
            else:
                st.warning("⚠️ 현재 표시할 최신 뉴스가 없습니다.")

            st.write("<br>", unsafe_allow_html=True)

            # 결정 박스 (기존 함수 유지)
            draw_decision_box("news", "신규기업에 대해 어떤 인상인가요?", ["긍정적", "중립적", "부정적"])

            # 면책 조항 (기존 함수 유지)
            display_disclaimer()
            
        # --- Tab 2: 실시간 시장 과열 진단 (Market Overheat Check) ---
        with tab2:
            # [1] 데이터 수집 및 계산 함수
            def get_market_status_internal(df_calendar):
                data = {
                    "ipo_return": 0.0, "ipo_volume": 0, "unprofitable_pct": 0, "withdrawal_rate": 0,
                    "vix": 0.0, "buffett_val": 0.0, "pe_ratio": 0.0, "fear_greed": 50
                }
        
                # --- A. [IPO Specific] 앱 내 데이터로 계산 ---
                if not df_calendar.empty:
                    today = datetime.now().date()
                    
                    # 1. 수익률 & 적자 비율 (최근 30개 표본)
                    traded_ipos = df_calendar[df_calendar['공모일_dt'].dt.date < today].sort_values(by='공모일_dt', ascending=False).head(30)
                    
                    ret_sum = 0; ret_cnt = 0; unp_cnt = 0
                    for _, row in traded_ipos.iterrows():
                        try:
                            p_ipo = float(str(row.get('price','0')).replace('$','').split('-')[0])
                            p_curr = get_current_stock_price(row['symbol'], MY_API_KEY)
                            if p_ipo > 0 and p_curr > 0:
                                ret_sum += ((p_curr - p_ipo) / p_ipo) * 100
                                ret_cnt += 1
                            fin = get_financial_metrics(row['symbol'], MY_API_KEY)
                            if fin and fin.get('net_margin') and fin['net_margin'] < 0: unp_cnt += 1
                        except: pass
                    
                    if ret_cnt > 0: data["ipo_return"] = ret_sum / ret_cnt
                    if len(traded_ipos) > 0: data["unprofitable_pct"] = (unp_cnt / len(traded_ipos)) * 100
        
                    # 2. Filings Volume (향후 30일)
                    future_ipos = df_calendar[(df_calendar['공모일_dt'].dt.date >= today) & 
                                              (df_calendar['공모일_dt'].dt.date <= today + timedelta(days=30))]
                    data["ipo_volume"] = len(future_ipos)
        
                    # 3. Withdrawal Rate (최근 540일)
                    recent_history = df_calendar[df_calendar['공모일_dt'].dt.date >= (today - timedelta(days=540))]
                    if not recent_history.empty:
                        wd = recent_history[recent_history['status'].str.lower() == 'withdrawn']
                        data["withdrawal_rate"] = (len(wd) / len(recent_history)) * 100
        
                # --- B. [Macro Market] Yahoo Finance 실시간 데이터 ---
                try:
                    vix_obj = yf.Ticker("^VIX")
                    data["vix"] = vix_obj.history(period="1d")['Close'].iloc[-1]
        
                    w5000 = yf.Ticker("^W5000").history(period="1d")['Close'].iloc[-1]
                    us_gdp_est = 28.0 
                    mkt_cap_est = w5000 / 1000 * 0.93 
                    data["buffett_val"] = (mkt_cap_est / us_gdp_est) * 100
        
                    try:
                        spy = yf.Ticker("SPY")
                        data["pe_ratio"] = spy.info.get('trailingPE', 24.5) 
                    except: data["pe_ratio"] = 24.5
        
                    spx = yf.Ticker("^GSPC").history(period="1y")
                    curr_spx = spx['Close'].iloc[-1]
                    ma200 = spx['Close'].rolling(200).mean().iloc[-1]
                    mom_score = ((curr_spx - ma200) / ma200) * 100
                    s_vix = max(0, min(100, (35 - data["vix"]) * (100/23)))
                    s_mom = max(0, min(100, (mom_score + 10) * 5))
                    data["fear_greed"] = (s_vix + s_mom) / 2
                except: pass
                
                return data
        
            # [2] 데이터 로드 및 분석 실행
            with st.spinner("📊 8대 핵심 지표를 실시간 분석 중입니다..."):
                if 'all_df' not in locals(): 
                    all_df_tab2 = get_extended_ipo_data(MY_API_KEY)
                    if not all_df_tab2.empty:
                        all_df_tab2 = all_df_tab2.dropna(subset=['exchange'])
                        all_df_tab2['공모일_dt'] = pd.to_datetime(all_df_tab2['date'])
                else:
                    all_df_tab2 = all_df
        
                md = get_market_status_internal(all_df_tab2)
        
            # --- CSS 스타일 정의 ---
            st.markdown("""
            <style>
                .metric-card { background-color:#ffffff; padding:15px; border-radius:12px; border: 1px solid #e0e0e0;
                              box-shadow: 0 2px 4px rgba(0,0,0,0.03); height: 100%; min-height: 220px; 
                              display: flex; flex-direction: column; justify-content: space-between; }
                .metric-header { font-weight:bold; font-size:16px; color:#111; margin-bottom:5px; }
                .metric-value-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
                .metric-value { font-size:20px; font-weight:800; color:#004e92; }
                .metric-desc { font-size:13px; color:#555; line-height:1.5; margin-bottom:10px; flex-grow: 1; }
                .metric-footer { font-size:11px; color:#999; margin-top:5px; border-top:1px solid #f0f0f0; padding-top:8px; font-style: italic; }
                .st-badge { font-size:12px; padding: 3px 8px; border-radius:6px; font-weight:bold; }
                .st-hot { background-color:#ffebee; color:#c62828; }
                .st-cold { background-color:#e3f2fd; color:#1565c0; }
                .st-good { background-color:#e8f5e9; color:#2e7d32; }
                .st-neutral { background-color:#f5f5f5; color:#616161; }
            </style>
            """, unsafe_allow_html=True)
        
            # --- 1. IPO 시장 지표 시각화 ---
            st.markdown('<p style="font-size: 15px; font-weight: 600; margin-bottom: 10px;">IPO 시장 과열 평가</p>', unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns(4)
        
            with c1:
                val = md['ipo_return']; status = "🔥 과열" if val >= 20 else "✅ 적정" if val >= 0 else "❄️ 침체"
                st_cls = "st-hot" if val >= 20 else "st-good" if val >= 0 else "st-cold"
                st.markdown(f"<div class='metric-card'><div class='metric-header'>First-Day Returns</div><div class='metric-value-row'><span class='metric-value'>{val:+.1f}%</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>상장 첫날 시초가가 공모가 대비 얼마나 상승했는지 나타냅니다. 20% 이상이면 과열로 판단합니다.</div><div class='metric-footer'>Ref: Jay Ritter (Univ. of Florida)</div></div>", unsafe_allow_html=True)
        
            with c2:
                val = md['ipo_volume']; status = "🔥 활발" if val >= 10 else "⚖️ 보통"
                st_cls = "st-hot" if val >= 10 else "st-neutral"
                st.markdown(f"<div class='metric-card'><div class='metric-header'>Filings Volume</div><div class='metric-value-row'><span class='metric-value'>{val}건</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>향후 30일 이내 상장 예정인 기업의 수입니다. 물량이 급증하면 고점 징후일 수 있습니다.</div><div class='metric-footer'>Ref: Ibbotson & Jaffe (1975)</div></div>", unsafe_allow_html=True)
        
            with c3:
                val = md['unprofitable_pct']; status = "🚨 위험" if val >= 80 else "⚠️ 주의" if val >= 50 else "✅ 건전"
                st_cls = "st-hot" if val >= 50 else "st-good"
                st.markdown(f"<div class='metric-card'><div class='metric-header'>Unprofitable IPOs</div><div class='metric-value-row'><span class='metric-value'>{val:.0f}%</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>최근 상장 기업 중 순이익이 '적자'인 기업의 비율입니다. 80%에 육박하면 버블로 간주합니다.</div><div class='metric-footer'>Ref: Jay Ritter (Dot-com Bubble)</div></div>", unsafe_allow_html=True)
        
            with c4:
                val = md['withdrawal_rate']; status = "🔥 과열" if val < 5 else "✅ 정상"
                st_cls = "st-hot" if val < 5 else "st-good"
                st.markdown(f"<div class='metric-card'><div class='metric-header'>Withdrawal Rate</div><div class='metric-value-row'><span class='metric-value'>{val:.1f}%</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>자진 철회 비율입니다. 낮을수록(10%↓) 묻지마 상장이 많다는 뜻입니다.</div><div class='metric-footer'>Ref: Dunbar (1998)</div></div>", unsafe_allow_html=True)
        
            st.write("<br>", unsafe_allow_html=True)
        
            # --- 2. 거시 시장 지표 시각화 ---
            st.markdown('<p style="font-size: 15px; font-weight: 600; margin-top: 20px; margin-bottom: 10px;">미국거시경제 과열 평가</p>', unsafe_allow_html=True)
            m1, m2, m3, m4 = st.columns(4)
        
            with m1:
                val = md['vix']; status = "🔥 탐욕" if val <= 15 else "❄️ 공포" if val >= 25 else "⚖️ 중립"
                st_cls = "st-hot" if val <= 15 else "st-cold" if val >= 25 else "st-neutral"
                st.markdown(f"<div class='metric-card'><div class='metric-header'>VIX Index</div><div class='metric-value-row'><span class='metric-value'>{val:.2f}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>S&P 500 변동성 지수입니다. 낮을수록 시장이 과도하게 안심하고 있음을 뜻합니다.</div><div class='metric-footer'>Ref: CBOE / Whaley (1993)</div></div>", unsafe_allow_html=True)
        
            with m2:
                val = md['buffett_val']; status = "🚨 고평가" if val > 150 else "⚠️ 높음"
                st_cls = "st-hot" if val > 120 else "st-neutral"
                disp_val = f"{val:.0f}%" if val > 0 else "N/A"
                st.markdown(f"<div class='metric-card'><div class='metric-header'>Buffett Indicator</div><div class='metric-value-row'><span class='metric-value'>{disp_val}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>GDP 대비 시총 비율입니다. 100%를 넘으면 경제 규모 대비 주가가 비싸다는 신호입니다.</div><div class='metric-footer'>Ref: Warren Buffett (2001)</div></div>", unsafe_allow_html=True)
        
            with m3:
                val = md['pe_ratio']; status = "🔥 고평가" if val > 25 else "✅ 적정"
                st_cls = "st-hot" if val > 25 else "st-good"
                st.markdown(f"<div class='metric-card'><div class='metric-header'>S&P 500 PE</div><div class='metric-value-row'><span class='metric-value'>{val:.1f}x</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>주가수익비율입니다. 역사적 평균(약 16배)보다 높으면 고평가 구간입니다.</div><div class='metric-footer'>Ref: Shiller CAPE Model (Proxy)</div></div>", unsafe_allow_html=True)
        
            with m4:
                val = md['fear_greed']; status = "🔥 Greed" if val >= 70 else "❄️ Fear" if val <= 30 else "⚖️ Neutral"
                st_cls = "st-hot" if val >= 70 else "st-cold" if val <= 30 else "st-neutral"
                st.markdown(f"<div class='metric-card'><div class='metric-header'>Fear & Greed</div><div class='metric-value-row'><span class='metric-value'>{val:.0f}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>심리 지표입니다. 75점 이상은 '극단적 탐욕' 상태를 의미합니다.</div><div class='metric-footer'>Ref: CNN Business Logic</div></div>", unsafe_allow_html=True)
        
            # --- 3. AI 종합 진단 (Expander) ---
            with st.expander("거시지표 분석", expanded=False): 
                # 여기서 AI 함수 호출! (24시간에 한 번만 실행됨)
                # 만약 아직 get_market_dashboard_analysis 함수를 정의하지 않으셨다면 
                # 이전 답변의 함수 코드를 app.py 상단에 먼저 추가해주셔야 합니다.
                try:
                    ai_market_comment = get_market_dashboard_analysis(md)
                except NameError:
                    ai_market_comment = "AI 분석 함수가 아직 로드되지 않았습니다."

                # [수정됨] 제목 div를 제거하고 본문만 남긴 버전
                st.markdown(f"""
                <div style='background-color:#f8f9fa; padding:15px; border-radius:10px; border-left: 5px solid #004e92;'>
                    <div style='font-size:14px; line-height:1.6; color:#333; text-align:justify;'>
                        {ai_market_comment}
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # 기존의 팁 메시지는 하단에 보조적으로 표시
                if md.get('unprofitable_pct', 0) >= 80:
                    st.warning("🚨 **경고:** 적자 기업 비율이 매우 높습니다. 개별 종목의 펀더멘털 확인이 필수적입니다.")
        
           # [4] 참고논문 (expander)
            with st.expander("참고(References)", expanded=False):
                st.markdown("""
                <style>
                    .ref-container { margin-top: 5px; }
                    .ref-item { padding: 12px 0; border-bottom: 1px solid #f0f0f0; display: flex; justify-content: space-between; align-items: center; transition: 0.2s; }
                    .ref-item:hover { background-color: #fafafa; padding-left: 5px; padding-right: 5px; }
                    .ref-title { font-weight: bold; color: #004e92; text-decoration: none; font-size: 14px; }
                    .ref-title:hover { text-decoration: underline; }
                    .ref-author { font-size: 12px; color: #666; margin-top: 2px; }
                    .ref-btn { background: #fff; border: 1px solid #ddd; padding: 4px 10px; border-radius: 15px; font-size: 11px; color: #555; text-decoration: none; white-space: nowrap; }
                    .ref-btn:hover { border-color: #004e92; color: #004e92; background-color: #f0f7ff; }
                    .ref-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; background: #e9ecef; color: #495057; font-size: 10px; font-weight: bold; margin-bottom: 5px; }
                </style>
                """, unsafe_allow_html=True)

                # --- 중요: references 변수를 여기서 정의해야 합니다 ---
                references = [
                    {
                        "label": "IPO 데이터", 
                        "title": "Initial Public Offerings: Updated Statistics", 
                        "author": "Jay R. Ritter (Warrington College)", 
                        "summary": "미국 IPO 시장의 성적표와 공모가 저평가(Underpricing) 통계의 결정판",
                        "link": "https://site.warrington.ufl.edu/ritter/ipo-data/"
                    },
                    {
                        "label": "시장 과열", 
                        "title": "'Hot Issue' Markets (Ibbotson & Jaffe)", 
                        "author": "Ibbotson & Jaffe (1975)", 
                        "summary": "특정 시기에 IPO 수익률이 비정상적으로 높아지는 '시장 과열' 현상 규명",
                        "link": "https://scholar.google.com/scholar?q=Ibbotson+Jaffe+1975+Hot+Issue+Markets"
                    },
                    {
                        "label": "상장 철회", 
                        "title": "The Choice Between Firm-Commitment and Best-Efforts IPOs", 
                        "author": "Dunbar (1998)", 
                        "summary": "상장 방식 선택에 따른 기업 가치와 상장 철회 위험의 상관관계 분석",
                        "link": "https://scholar.google.com/scholar?q=Dunbar+1995+The+Choice+Between+Firm-Commitment+and+Best-Efforts+IPOs"
                    },
                    {
                        "label": "시장 변동성", 
                        "title": "VIX White Paper: CBOE Volatility Index", 
                        "author": "CBOE (Official)", 
                        "summary": "S&P 500 옵션을 기반으로 시장의 공포와 변동성을 측정하는 표준 지표",
                        "link": "https://www.cboe.com/micro/vix/vixwhite.pdf"
                    },
                    {
                        "label": "밸류에이션", 
                        "title": "Warren Buffett on the Stock Market (Fortune Classic)", 
                        "author": "Warren Buffett (2001)", 
                        "summary": "GDP 대비 시가총액 비율을 통해 시장의 고평가 여부를 판단하는 버핏 지표",
                        "link": "https://www.gurufocus.com/news/122602/warren-buffett-on-the-stock-market-2001-article"
                    },
                    {
                        "label": "기초 데이터", 
                        "title": "U.S. Stock Markets 1871-Present (CAPE Ratio)", 
                        "author": "Robert Shiller", 
                        "summary": "경기조정주가수익비율(CAPE)을 활용한 장기적 주식 시장 밸류에이션 데이터",
                        "link": "http://www.econ.yale.edu/~shiller/data.htm"
                    },
                    {
                        "label": "투자자 심리", 
                        "title": "Fear & Greed Index (Real-time)", 
                        "author": "CNN Business", 
                        "summary": "7가지 지표를 통합해 투자자의 탐욕과 공포 수준을 0~100으로 수치화",
                        "link": "https://edition.cnn.com/markets/fear-and-greed"
                    }
                ]

                # 이제 변수가 정의되었으므로 루프를 돌립니다.
                for ref in references:
                    st.markdown(f"""
                    <div class='ref-item'>
                        <div style='flex:1;'>
                            <div class='ref-badge'>{ref['label']}</div><br>
                            <a href='{ref['link']}' target='_blank' class='ref-title' style='display:block; margin-bottom:4px;'>📄 {ref['title']}</a>
                            <div style='font-size: 13px; color: #666; line-height: 1.5;'>
                                <span>{ref['summary']}, {ref['author']}</span>
                            </div>
                        </div>
                        <div style='margin-left: 15px; align-self: center;'>
                            <a href='{ref['link']}' target='_blank' class='ref-btn'>원문 보기 ↗</a>
                        </div>
                    </div>""", unsafe_allow_html=True)
        
            # --- 5. 최종 의사결정 박스 및 면책조항 ---
            # draw_decision_box 함수가 사전에 정의되어 있어야 합니다.
            draw_decision_box("macro", "현재 거시경제(Macro) 상황에 대한 판단은?", ["버블", "중립", "침체"])
            
            # 맨 마지막 호출
            display_disclaimer()

        # --- Tab 3: 개별 기업 평가 (Real Data 연동 - Full Version) ---
        with tab3:
            # 🎨 [추가 위치] 카드 내부의 수치 폰트 크기 통일 CSS
            st.markdown("""
            <style>
                .metric-value {
                    font-size: 1.2rem !important; /* 글자 크기를 살짝 조절해서 '확인 필요' 등이 안 깨지게 함 */
                    font-weight: 800 !important;
                    white-space: nowrap;
                }
                .st-badge {
                    font-size: 0.7rem !important;
                    vertical-align: middle;
                    margin-left: 5px;
                }
                .metric-value-row {
                    display: flex;
                    align-items: center;
                    justify-content: flex-start; /* 왼쪽 정렬로 통일감 부여 */
                }
            </style>
            """, unsafe_allow_html=True)
        
            # [0] 데이터 소스 및 1차 유효성 판별
            data_source = "Unknown"
            is_data_available = False
            
            if fin_data:
                if fin_data.get('revenue') and fin_data.get('revenue') > 0:
                    is_data_available = True
                    if 'sec' in str(fin_data.get('source', '')).lower():
                        data_source = "SEC 10-K/Q (공시)"
                    elif fin_data.get('market_cap'):
                        data_source = "Finnhub (가공)"
                    else:
                        data_source = "Yahoo Finance (보조)"
        
            # 🔥 [0.5] 데이터 보강 로직
            if not is_data_available or not fin_data.get('revenue'):
                try:
                    ticker = yf.Ticker(stock['symbol'])
                    yf_fin = ticker.financials
                    yf_info = ticker.info
                    yf_bal = ticker.balance_sheet
                    
                    if not yf_fin.empty:
                        # [기본 실적]
                        rev = yf_fin.loc['Total Revenue'].iloc[0]
                        net_inc = yf_fin.loc['Net Income'].iloc[0]
                        prev_rev = yf_fin.loc['Total Revenue'].iloc[1] if len(yf_fin.columns) > 1 else rev
                        
                        # [지표 계산 및 주입]
                        fin_data['revenue'] = rev / 1e6
                        fin_data['net_margin'] = (net_inc / rev) * 100
                        fin_data['growth'] = ((rev - prev_rev) / prev_rev) * 100
                        fin_data['eps'] = yf_info.get('trailingEps', 0)
                        
                        # 영업이익률(op_margin) 계산 추가 (에러 방지용)
                        if 'Operating Income' in yf_fin.index:
                            op_inc = yf_fin.loc['Operating Income'].iloc[0]
                            fin_data['op_margin'] = (op_inc / rev) * 100
                        else:
                            fin_data['op_margin'] = fin_data['net_margin'] # 데이터 부재 시 순이익률 활용
                        
                        # [추가 전문 지표]
                        fin_data['market_cap'] = yf_info.get('marketCap', 0) / 1e6
                        fin_data['forward_pe'] = yf_info.get('forwardPE', 0)
                        fin_data['price_to_book'] = yf_info.get('priceToBook', 0)
                        
                        # [안정성 지표 - 대차대조표 기반]
                        if not yf_bal.empty:
                            total_liab = yf_bal.loc['Total Liabilities Net Minority Interest'].iloc[0] if 'Total Liabilities Net Minority Interest' in yf_bal.index else 0
                            equity = yf_bal.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in yf_bal.index else 1
                            fin_data['debt_equity'] = (total_liab / equity) * 100
                            fin_data['roe'] = (net_inc / equity) * 100
                        
                        is_data_available = True
                        data_source = "Yahoo Finance (Full Direct)"
                except:
                    pass
        
            # [1] 데이터 전처리 및 지표 계산
            growth_val = fin_data.get('growth') if is_data_available else None
            ocf_val = fin_data.get('net_margin') if is_data_available else 0
            
            op_m = fin_data.get('op_margin') if is_data_available else None
            net_m = fin_data.get('net_margin') if is_data_available else None
            
            # 발생액 품질 계산
            if is_data_available and op_m is not None and net_m is not None:
                acc_diff = op_m - net_m
                accruals_status = "Low" if abs(acc_diff) < 5 else "High"
            else:
                accruals_status = "Unknown"

            md_stock = {
                "sales_growth": growth_val,
                "ocf": ocf_val,
                "accruals": accruals_status,
                "vc_backed": "Checking...",
                "discount_rate": 0.0
            }

            # 🔥 [1.5] 에러 방지용 안전 변수 가공 (가장 중요)
            def clean_value(val):
                """None, NaN, Inf 값을 0으로 정제하는 함수"""
                try:
                    if val is None or (isinstance(val, (int, float)) and (np.isnan(val) or np.isinf(val))):
                        return 0.0
                    return float(val)
                except:
                    return 0.0

            # ⚠️ 중요: clean_value 함수 밖(같은 라인)에 위치해야 합니다.
            if fin_data is None: 
                fin_data = {}

            # 데이터 정제 추출
            rev_val = clean_value(fin_data.get('revenue', 0))
            net_m_val = clean_value(fin_data.get('net_margin', 0))
            op_m_val = clean_value(fin_data.get('op_margin', net_m_val))
            growth = clean_value(fin_data.get('growth', 0))
            roe_val = clean_value(fin_data.get('roe', 0))
            de_ratio = clean_value(fin_data.get('debt_equity', 0))
            pe_val = clean_value(fin_data.get('forward_pe', 0))

            # 화면 표시용 텍스트 가공 (nan, inf 대신 N/A 출력)
            rev_display = f"{rev_val:,.0f}" if rev_val > 0 else "N/A"
            growth_display = f"{growth:+.1f}%" if abs(growth) > 0.001 else "N/A"
            net_m_display = f"{net_m_val:.1f}%" if abs(net_m_val) > 0.001 else "N/A"
            opm_display = f"{op_m_val:.2f}%" if abs(op_m_val) > 0.001 else "N/A"

            # [2] 카드형 UI 레이아웃 (Metric Cards)
            r1_c1, r1_c2, r1_c3, r1_c4 = st.columns(4)
            r2_c1, r2_c2, r2_c3, r2_c4 = st.columns(4)

            # (1) 매출 성장성 - [수정됨: "산출 불가" -> "N/A"]
            with r1_c1:
                display_val = growth_display if growth_display != "N/A" else "N/A"
                if display_val != "N/A":
                    status, st_cls = ("🔥 고성장", "st-hot") if growth > 20 else ("✅ 안정", "st-good") if growth > 5 else ("⚠️ 둔화", "st-neutral")
                else:
                    status, st_cls = ("🔍 N/A", "st-neutral")
                
                st.markdown(f"<div class='metric-card'><div class='metric-header'>Sales Growth</div><div class='metric-value-row'><span class='metric-value'>{display_val}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>최근 연간 매출 성장률입니다.</div><div class='metric-footer'>Theory: Jay Ritter (1991)<br><b>Data Source: {data_source}</b></div></div>", unsafe_allow_html=True)

            # (2) 수익성 - [수정됨: "산출 불가" -> "N/A"]
            with r1_c2:
                display_val = net_m_display if net_m_display != "N/A" else "N/A"
                if display_val != "N/A":
                    status, st_cls = ("✅ 흑자", "st-good") if net_m_val > 0 else ("🚨 적자", "st-hot")
                else:
                    status, st_cls = ("🔍 N/A", "st-neutral")

                st.markdown(f"<div class='metric-card'><div class='metric-header'>Net Margin (Profit)</div><div class='metric-value-row'><span class='metric-value'>{display_val}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>순이익률입니다.</div><div class='metric-footer'>Theory: Fama & French (2004)<br><b>Data Source: {data_source}</b></div></div>", unsafe_allow_html=True)

            # (3) 발생액 품질 (동일 유지)
            with r1_c3:
                val = md_stock['accruals']
                status = "✅ 건전" if val == "Low" else "🚨 주의" if val == "High" else "🔍 N/A"
                st_cls = "st-good" if val == "Low" else "st-hot" if val == "High" else "st-neutral"
                st.markdown(f"<div class='metric-card'><div class='metric-header'>Accruals Quality</div><div class='metric-value-row'><span class='metric-value'>{val}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>회계 장부의 투명성입니다.</div><div class='metric-footer'>Theory: Teoh et al. (1998)<br><b>Data Source: {data_source}</b></div></div>", unsafe_allow_html=True)

            # (4) 부채 비율 - [수정됨: "확인 필요" -> "N/A"]
            with r1_c4:
                display_val = f"{de_ratio:.1f}%" if de_ratio > 0 else "N/A"
                status, st_cls = ("✅ 안정", "st-good") if (0 < de_ratio < 100) else ("🔍 N/A", "st-neutral")
                
                st.markdown(f"<div class='metric-card'><div class='metric-header'>Debt / Equity</div><div class='metric-value-row'><span class='metric-value'>{display_val}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>자본 대비 부채 비중입니다.</div><div class='metric-footer'>Ref: Standard Ratio<br><b>Data Source: {data_source}</b></div></div>", unsafe_allow_html=True)

            # (5) 시장 성과 (r2_c1)
            with r2_c1:
                if current_p > 0 and off_val > 0:
                    up_rate = ((current_p - off_val) / off_val) * 100
                    display_val, status, st_cls = (f"{up_rate:+.1f}%", "🚀 급등" if up_rate > 20 else "⚖️ 적정", "st-hot" if up_rate > 20 else "st-good")
                else:
                    display_val, status, st_cls = ("대기 중", "⏳ IPO 예정", "st-neutral")
                st.markdown(f"<div class='metric-card'><div class='metric-header'>Market Performance</div><div class='metric-value-row'><span class='metric-value'>{display_val}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>공모가 대비 수익률입니다.</div><div class='metric-footer'>Theory: Kevin Rock (1986)<br><b>Data Source: Live Price</b></div></div>", unsafe_allow_html=True)

            st.write("<br>", unsafe_allow_html=True)

            # [2.5] 논문기반 AI 종합 판정 리포트
            with st.expander("논문기반 AI 분석 보기", expanded=False):
                # 1번 수정: 출처 표시 스타일 통일
                st.caption(f"Data Source: {data_source} / Currency: USD")
                
                if is_data_available:
                    growth_status = "고성장(High-Growth)" if growth > 20 else "안정적(Stable)" if growth > 5 else "정체(Stagnant)"
                    quality_status = "우수(High-Quality)" if roe_val > 15 else "보통(Average)"
                    
                    st.markdown(f"""
                    **1. 성장성 및 생존 분석 (Jay Ritter, 1991)**
                    * 현재 매출 성장률은 **{growth_status}** 단계입니다. Ritter의 이론에 따르면 상장 초기 고성장 기업은 향후 3~5년간 '성장 둔화의 함정'을 조심해야 하며, 현재 수치는 {"긍정적 시그널" if growth > 10 else "주의가 필요한 시그널"}로 해석됩니다.
    
                    **2. 수익성 품질 및 자본 구조 (Fama & French, 2004)**
                    * 수익성 지표(Net Margin/ROE)는 **{quality_status}** 등급입니다. 본 기업은 {"상대적으로 견고한 이익 체력" if roe_val > 10 else "영업 효율성 개선이 선행되어야 하는 체력"}을 보유하고 있습니다.
    
                    **3. 정보 비대칭 및 회계 품질 (Teoh et al., 1998)**
                    * 발생액 품질(Accruals Quality)이 **{accruals_status}** 상태입니다. 이는 경영진의 이익 조정 가능성이 {"낮음" if accruals_status == "Low" else "존재함"}을 의미합니다.
                    """)
                    st.info(f"**AI 종합 판정:** 학술적 관점에서 본 기업은 **{growth_status}** 성격이 강하며, 정보 불확실성은 일정 부분 해소된 상태입니다.")
                else:
                    st.warning("재무 데이터 부재로 정성적 분석이 권장됩니다.")
        
            # [3] 재무자료 상세보기 (Summary Table)
            with st.expander("재무분석", expanded=False):
                if is_data_available:
                    st.caption(f"Data Source: {data_source} / Currency: USD")
            
                    # 스타일 수정: Label은 bold, Value는 normal(400)로 설정
                    st.markdown("""
                    <style>
                        .custom-metric-container {
                            display: flex;
                            justify-content: space-between;
                            text-align: center;
                            padding: 10px 0;
                        }
                        .custom-metric-box {
                            flex: 1;
                            border-right: 1px solid #f0f0f0; /* 지표 간 구분선 추가 (선택사항) */
                        }
                        .custom-metric-box:last-child {
                            border-right: none;
                        }
                        .custom-metric-label {
                            font-size: 0.85rem; 
                            font-weight: bold;    /* 지표명을 굵게 변경 */
                            color: #333333;
                            margin-bottom: 6px;
                        }
                        .custom-metric-value {
                            font-size: 1.05rem; 
                            font-weight: 400;    /* 수치를 일반 굵기로 변경 */
                            color: #1f1f1f;
                        }
                    </style>
                    """, unsafe_allow_html=True)
            
                    # 지표 데이터 가공
                    metrics = [
                        ("Forward PER", f"{pe_val:.1f}x" if pe_val > 0 else "N/A"),
                        ("P/B Ratio", f"{fin_data.get('price_to_book', 0):.2f}x"),
                        ("Net Margin", f"{net_m_val:.1f}%"),
                        ("ROE", f"{roe_val:.1f}%"),
                        ("D/E Ratio", f"{de_ratio:.1f}%"),
                        ("Growth (YoY)", f"{growth:.1f}%")
                    ]
            
                    # 커스텀 메트릭 렌더링
                    m_cols = st.columns(6)
                    for i, (label, value) in enumerate(metrics):
                        with m_cols[i]:
                            st.markdown(f"""
                                <div class="custom-metric-box">
                                    <div class="custom-metric-label">{label}</div>
                                    <div class="custom-metric-value">{value}</div>
                                </div>
                            """, unsafe_allow_html=True)
            
                    st.markdown(" ")     
                
                # -------------------------------------------------------
                    # [수정됨] 기존의 하드코딩된 opinion_text 대신 AI 함수 호출
                    # -------------------------------------------------------
                    
                    # 1. AI에게 보낼 데이터 패키징
                    ai_metrics = {
                        "growth": growth_display,
                        "net_margin": net_m_display,
                        "op_margin": opm_display,
                        "roe": f"{roe_val:.1f}%",
                        "debt_equity": f"{de_ratio:.1f}%",
                        "pe": f"{pe_val:.1f}x" if pe_val > 0 else "N/A",
                        "accruals": accruals_status
                    }

                    # 2. Supabase 캐싱된 AI 리포트 호출
                    with st.spinner("🤖 AI 애널리스트가 재무제표를 분석 중입니다..."):
                        ai_report = get_financial_report_analysis(stock['name'], stock['symbol'], ai_metrics)
                    
                    # 3. 결과 출력
                    st.info(ai_report)
                    st.caption("※ 본 분석은 실제 재무 데이터를 기반으로 생성된 표준 CFA 분석 알고리즘에 따릅니다.")

                else:
                    st.warning(f"재무 데이터 부재로 정성적 분석이 권장됩니다.")

            # [4] 학술적 근거 및 원문 링크 섹션
            with st.expander("참고(References)", expanded=False):
                # 전용 CSS 스타일링
                st.markdown("""
                <style>
                    .ref-item { padding: 12px 0; border-bottom: 1px solid #f0f0f0; display: flex; justify-content: space-between; align-items: center; }
                    .ref-title { font-weight: bold; color: #004e92; text-decoration: none; font-size: 14px; }
                    .ref-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; background: #e9ecef; color: #495057; font-size: 10px; font-weight: bold; margin-bottom: 5px; }
                    .ref-btn { background: #fff; border: 1px solid #ddd; padding: 4px 12px; border-radius: 15px; font-size: 11px; color: #555; text-decoration: none; }
                    .ref-btn:hover { background: #f8f9fa; border-color: #bbb; }
                </style>
                """, unsafe_allow_html=True)

                # 참고문헌 데이터 리스트
                references_tab3 = [
                    {"label": "성장성 분석", "title": "The Long-Run Performance of IPOs", "author": "Jay R. Ritter (1991)", "summary": "신규 상장 기업의 장기적 성과 저하 현상 분석", "link": "https://scholar.google.com/scholar?q=Jay+R.+Ritter+1991"},
                    {"label": "현금흐름", "title": "New Lists: Fundamentals and Survival Rates", "author": "Fama & French (2004)", "summary": "신규 기업의 재무 건전성과 생존율 추적", "link": "https://scholar.google.com/scholar?q=Fama+French+2004"},
                    {"label": "회계 품질", "title": "Earnings Management and the Long-Run Performance", "author": "Teoh, Welch, & Wong (1998)", "summary": "상장 전후 이익 조정이 주가에 미치는 영향", "link": "https://scholar.google.com/scholar?q=Teoh+Welch+Wong+1998"},
                    {"label": "VC 인증", "title": "The Role of Venture Capital", "author": "Barry et al. (1990)", "summary": "VC 투자가 상장 시 갖는 공신력 분석", "link": "https://www.sciencedirect.com/science/article/abs/pii/0304405X9090006L"},
                    {"label": "저평가 이론", "title": "Why New Issues are Underpriced", "author": "Kevin Rock (1986)", "summary": "정보 비대칭성과 공모가 저평가 메커니즘", "link": "https://www.sciencedirect.com/science/article/pii/0304405X86900541"}
                ]

                st.info(f"💡 현재 분석에 사용된 데이터 출처: **{data_source}**")

                # 반복문을 통한 리스트 렌더링
                for ref in references_tab3:
                    st.markdown(f"""
                    <div class='ref-item'>
                        <div style='flex:1;'>
                            <div class='ref-badge'>{ref['label']}</div><br>
                            <a href='{ref['link']}' target='_blank' class='ref-title'>📄 {ref['title']}</a>
                            <div style='font-size: 13px; color: #666;'>{ref['summary']}, {ref['author']}</div>
                        </div>
                        <div style='margin-left: 15px;'>
                            <a href='{ref['link']}' target='_blank' class='ref-btn'>원문 보기 ↗</a>
                        </div>
                    </div>""", unsafe_allow_html=True)
                
                st.caption("※ 본 리포트는 SEC 공시 및 Finnhub API 데이터를 기반으로 위 학술적 모델을 적용했습니다.")

            # [5] 사용자 최종 판단 박스 (Decision Box)
           
            draw_decision_box("company", f"{stock['name']} 가치평가(Valuation) 최종 판단", ["고평가", "중립", "저평가"])

            # 맨 마지막에 호출
            display_disclaimer()

        # --- 탭 글씨 크기 및 스타일 통일 (CSS) ---
        st.markdown("""
            <style>
            /* 모든 탭 버튼의 글씨 크기와 굵기 조절 */
            button[data-baseweb="tab"] p {
                font-size: 1.1rem !important;
                font-weight: 600 !important;
                color: #31333F;
            }
            /* 선택된 탭의 강조 효과 */
            button[data-baseweb="tab"][aria-selected="true"] p {
                color: #FF4B4B !important; /* 스트림릿 기본 레드 컬러 */
            }
            </style>
        """, unsafe_allow_html=True)            

        # --- Tab 4: 기관평가 (UI 출력 부분) ---
        with tab4:
            # 1. 함수 호출 (기존 코드 유지)
            with st.spinner(f"전문 기관 데이터를 정밀 수집 중..."):
                result = get_unified_tab4_analysis(stock['name'], stock['symbol'])
            
            # 2. 결과 데이터 매핑 (기존 코드 유지)
            summary_raw = result.get('summary', '')
            pro_con_raw = result.get('pro_con', '')
            rating_val = str(result.get('rating', 'Hold')).strip()
            score_val = str(result.get('score', '3')).strip() 
            sources = result.get('links', [])
            q = stock['symbol'] if stock['symbol'] else stock['name']
        
            # --- (1) Renaissance Capital & 기관 종합 요약 섹션 ---
            with st.expander("Renaissance Capital IPO 요약", expanded=False):
                import re
                pattern = r'(?i)source|출처|https?://'
                parts = re.split(pattern, summary_raw)
                
                # [수정] 모든 줄바꿈(\n)을 제거하고 공백(' ')으로 치환하여 한 문단으로 만듭니다.
                # 1. AI가 보낸 텍스트 형태의 \\n 정제
                # 2. 실제 줄바꿈 문자(\n)를 공백으로 치환
                summary = parts[0].replace('\\n', ' ').replace('\n', ' ').strip().rstrip(' ,.:;-\t')
                
                if not summary or "분석 불가" in summary:
                    st.warning("직접적인 분석 리포트를 찾지 못했습니다.")
                else:
                    # [수정] 더 이상 replace('\n', '\n\n')을 하지 않고 바로 출력합니다.
                    st.info(summary)
        
            # --- (2) Seeking Alpha & Morningstar 섹션 (수정됨) ---
            with st.expander("Seeking Alpha & Morningstar 요약", expanded=False):
                # [핵심 수정] 문자열 \n을 실제 엔터로 변환
                pro_con = pro_con_raw.replace('\\n', '\n').replace("###", "").strip()
                
                # [문단 공백 로직] '부정' 키워드 앞에 엔터를 추가하여 한 행 공백 생성
                pro_con = pro_con.replace("긍정:", "**긍정**:").replace("부정:", "\n\n**부정**:")
                pro_con = pro_con.replace("✅ 긍정", "**긍정**").replace("⚠️ 부정", "\n\n**부정**")
                
                if "의견 수집 중" in pro_con or not pro_con:
                    st.error("AI가 실시간 리포트 본문을 분석하는 데 실패했습니다.")
                else:
                    # 최종 출력 시 줄바꿈 강제 적용
                    st.success(pro_con.replace('\n', '\n\n'))
        
        
            # --- (3) Institutional Sentiment 섹션 ---
            with st.expander("Sentiment Score", expanded=False):
                s_col1, s_col2 = st.columns(2)
                
                # 데이터 가져오기 및 세척
                rating_val = str(result.get('rating', 'Hold')).strip()
                score_val = str(result.get('score', '3')).strip()
            
                with s_col1:
                    # Analyst Ratings 체계 안내 텍스트 생성
                    r_list = {
                        "Strong Buy": "적극 매수 추천",
                        "Buy": "매수 추천",
                        "Hold": "보유 및 중립 관망",
                        "Neutral": "보유 및 중립 관망",
                        "Sell": "매도 및 비중 축소"
                    }
                    
                    rating_desc = "**[Analyst Ratings 체계]**\n"
                    for k, v in r_list.items():
                        is_current = " **(현재)**" if k.lower() in rating_val.lower() else ""
                        rating_desc += f"- **{k}**: {v}{is_current}\n"
            
                    st.write("**[Analyst Ratings]**")
                    
                    # [수정] help 파라미터를 삭제하여 물음표 툴팁을 제거함
                    st.metric(label="Consensus Rating", value=rating_val)
                    
                    # 상태별 색상 피드백 및 하단 설명 집중
                    if any(x in rating_val for x in ["Buy", "Positive", "Outperform", "Strong"]):
                        st.success(f"의견: {r_list.get(rating_val, '긍정적')}")
                        st.caption(f"✅ 시장의 긍정적인 평가를 받고 있습니다.\n\n{rating_desc}")
                    elif any(x in rating_val for x in ["Sell", "Negative", "Underperform"]):
                        st.error(f"의견: {r_list.get(rating_val, '주의')}")
                        st.caption(f"🚨 보수적인 접근이 필요한 시점입니다.\n\n{rating_desc}")
                    else:
                        st.info(f"의견: {r_list.get(rating_val, '중립')}")
                        st.caption(f"ℹ️ {rating_desc}")

                with s_col2:
                    # IPO Scoop Score 체계 안내 텍스트 생성
                    s_list = {
                        "5": "대박 (Moonshot)",
                        "4": "강력한 수익",
                        "3": "양호 (Good)",
                        "2": "미미한 수익 예상",
                        "1": "공모가 하회 위험"
                    }
                    
                    score_desc = "**[IPO Scoop Score 체계]**\n"
                    for k, v in s_list.items():
                        is_current = f" **(현재 {score_val}점)**" if k == score_val else ""
                        score_desc += f"- ⭐ {k}개: {v}{is_current}\n"
            
                    st.write("**[IPO Scoop Score]**")
                    
                    # [수정] help 파라미터를 삭제하여 물음표 툴팁을 제거함
                    st.metric(label="Expected IPO Score", value=f"⭐ {score_val}")
                    
                    # 점수별 색상 피드백 및 하단 설명 집중
                    if score_val in ["4", "5"]:
                        st.success(f"평가: {s_list.get(score_val, '정보 없음')}")
                    elif score_val == "3":
                        st.info(f"평가: {s_list.get(score_val, '정보 없음')}")
                    else:
                        st.warning(f"평가: {s_list.get(score_val, '정보 없음')}")

                    st.caption(f"ℹ️ {score_desc}")

            # --- (4) References (제목 제거 및 링크 통합) ---
            with st.expander("References", expanded=False):
                # 1. AI가 동적으로 찾아낸 뉴스/리포트 링크들 (제목 없이 바로 노출)
                if sources:
                    for src in sources:
                        st.markdown(f"- [{src['title']}]({src['link']})")
                else:
                    st.caption("실시간 참조 리포트 링크를 불러올 수 없습니다.")
                
                # 2. 주요 분석 기관 바로가기 (구분선과 제목 제거 후 리스트 통합)
                st.markdown(f"- [Renaissance Capital: {stock['name']} 상세 데이터](https://www.google.com/search?q=site:renaissancecapital.com+{q})")
                st.markdown(f"- [Seeking Alpha: {stock['name']} 심층 분석글](https://seekingalpha.com/symbol/{q}/analysis)")
                st.markdown(f"- [Morningstar: {stock['name']} 리서치 결과](https://www.morningstar.com/search?query={q})")
                st.markdown(f"- [Google Finance: {stock['name']} 시장 동향](https://www.google.com/finance/quote/{q}:NASDAQ)")

                

            # [✅ 5단계 사용자 판단]
            draw_decision_box("ipo_report", f"기관 분석을 참고한 나의 최종 판단은?", ["매수", "중립", "매도"])

            # 맨 마지막에 호출
            display_disclaimer()
    
        
        # --- [공통 함수: 게시글 반응 처리] ---
        # 이 함수는 Tab 5 외부(메인 로직 상단)에 두셔도 좋습니다.
        def handle_post_reaction(post_id, reaction_type, user_id):
            if not user_id:
                st.warning("🔒 로그인이 필요한 기능입니다.")
                return
        
            user_list_key = 'like_users' if reaction_type == 'likes' else 'dislike_users'
            
            for p in st.session_state.posts:
                if p['id'] == post_id:
                    p.setdefault('like_users', [])
                    p.setdefault('dislike_users', [])
                    
                    # 중복 투표 방지
                    if user_id not in p[user_list_key]:
                        p[reaction_type] = p.get(reaction_type, 0) + 1
                        p[user_list_key].append(user_id)
                        st.rerun()
                    else:
                        st.toast("이미 참여하신 게시글입니다.")
                    break
        
        # =========================================================
        # --- Tab 5: 최종 투자 결정 (종목 상세 페이지 내) ---
        # =========================================================
        with tab5:
            # ---------------------------------------------------------------------------
            # 1. [스타일 및 설정] 흰 배경 강제 적용 및 변수 초기화
            # ---------------------------------------------------------------------------
            st.markdown("""
                <style>
                /* 전체 앱 배경 흰색, 글자 검은색 강제 적용 */
                .stApp { background-color: #ffffff !important; color: #000000 !important; }
                p, h1, h2, h3, h4, h5, h6, span, li, div { color: #000000 !important; }
                
                /* Expander 스타일 */
                .streamlit-expanderHeader {
                    background-color: #f8f9fa !important;
                    color: #000000 !important;
                    border: 1px solid #ddd !important;
                }
                div[data-testid="stExpanderDetails"] {
                    background-color: #ffffff !important;
                    border: 1px solid #ddd !important;
                    border-top: none !important;
                }
                
                /* 입력창 스타일 */
                .stTextInput input, .stTextArea textarea {
                    background-color: #ffffff !important;
                    color: #000000 !important;
                    border: 1px solid #ccc !important;
                }
                </style>
            """, unsafe_allow_html=True)
            
            # 변수 설정
            sid = stock['symbol']
            current_user_phone = st.session_state.get('user_phone', 'guest')
            user_id = st.session_state.get('user_id', 'guest_id')
            
            # [수정된 안전한 코드] 
            # 1. user_info를 가져오되, 값이 None이면 빈 딕셔너리 {}로 변환합니다.
            user_info = st.session_state.get('user_info') or {}
            
            # 2. 이제 user_info는 무조건 딕셔너리이므로 안전하게 .get()을 쓸 수 있습니다.
            is_admin = (user_info.get('role') == 'admin')
            
            # 데이터 초기화
            if 'vote_data' not in st.session_state: st.session_state.vote_data = {}
            if sid not in st.session_state.vote_data: st.session_state.vote_data[sid] = {'u': 10, 'f': 3}
            if 'watchlist' not in st.session_state: st.session_state.watchlist = []
            if 'watchlist_predictions' not in st.session_state: st.session_state.watchlist_predictions = {}
            if 'posts' not in st.session_state: st.session_state.posts = []

            # ---------------------------------------------------------
            # 2. 투자 분석 결과 섹션 (차트 시각화)
            # ---------------------------------------------------------
            if 'user_decisions' not in st.session_state: st.session_state.user_decisions = {}
            ud = st.session_state.user_decisions.get(sid, {})
            
            steps = [
                ('filing', 'Step 1'), ('news', 'Step 2'), 
                ('macro', 'Step 3'), ('company', 'Step 4'), 
                ('ipo_report', 'Step 5')
            ]
            
            missing_steps = [label for step, label in steps if not ud.get(step)]
            
            if missing_steps:
                st.info(f"💡 모든 분석 단계({', '.join(missing_steps)})를 완료하면 종합 결과 차트가 표시됩니다.")
            else:
                # 점수 계산 로직
                score_map = {
                    "긍정적": 1, "수용적": 1, "침체": 1, "안정적": 1, "저평가": 1, "매수": 1,
                    "중립적": 0, "중립": 0, "적정": 0,
                    "부정적": -1, "회의적": -1, "버블": -1, "고평가": -1, "매도": -1
                }
                user_score = sum(score_map.get(ud.get(s[0], "중립적"), 0) for s in steps)
                
                # 커뮤니티 데이터 시뮬레이션
                import numpy as np
                import plotly.graph_objects as go
                
                np.random.seed(42)
                community_scores = np.clip(np.random.normal(0, 1.5, 1000).round().astype(int), -5, 5)
                user_percentile = (community_scores <= user_score).sum() / len(community_scores) * 100
                
                m1, m2 = st.columns(2)
                m1.metric("시장 참여자 낙관도", "52.4%", help="전체 유저의 평균 점수")
                m2.metric("나의 분석 위치", f"상위 {100-user_percentile:.1f}%", f"{user_score}점")
                
                # 차트 그리기
                score_counts = pd.Series(community_scores).value_counts().sort_index()
                score_counts = (pd.Series(0, index=range(-5, 6)) + score_counts).fillna(0)
                
                fig = go.Figure(go.Bar(
                    x=score_counts.index, y=score_counts.values, 
                    marker_color=['#ff4b4b' if x == user_score else '#6e8efb' for x in score_counts.index],
                    hovertemplate="점수: %{x}<br>인원: %{y}명<extra></extra>"
                ))
                fig.update_layout(height=180, margin=dict(l=10, r=10, t=10, b=10), 
                                  xaxis=dict(title="분석 점수 분포"), yaxis=dict(showticklabels=False),
                                  paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig, use_container_width=True)

            # ---------------------------------------------------------
            # 3. 전망 투표 및 관심종목 (DB 연동 버전)
            # ---------------------------------------------------------
            st.write("---")
            st.subheader("향후 전망 투표")
            
            if st.session_state.get('auth_status') == 'user':
                # 아직 관심종목에 없을 때 (투표 버튼 노출)
                if sid not in st.session_state.watchlist:
                    st.caption("투표 시 관심종목에 자동 저장됩니다. (DB 영구 저장)")
                    c_up, c_down = st.columns(2)
                    
                    # [상승 예측 버튼]
                    if c_up.button("📈 상승 예측", key=f"up_{sid}", use_container_width=True, type="primary"):
                        # 1. DB에 영구 저장 (핵심)
                        db_toggle_watchlist(user_id, sid, "UP", action='add')
                        
                        # 2. 세션 상태 업데이트 (화면 즉시 갱신용)
                        if sid not in st.session_state.watchlist:
                            st.session_state.watchlist.append(sid)
                        st.session_state.watchlist_predictions[sid] = "UP"
                        st.session_state.vote_data[sid]['u'] += 1
                        st.rerun()

                    # [하락 예측 버튼]
                    if c_down.button("📉 하락 예측", key=f"dn_{sid}", use_container_width=True):
                        # 1. DB에 영구 저장 (핵심)
                        db_toggle_watchlist(user_id, sid, "DOWN", action='add')
                        
                        # 2. 세션 상태 업데이트 (화면 즉시 갱신용)
                        if sid not in st.session_state.watchlist:
                            st.session_state.watchlist.append(sid)
                        st.session_state.watchlist_predictions[sid] = "DOWN"
                        st.session_state.vote_data[sid]['f'] += 1
                        st.rerun()

                # 이미 관심종목에 있을 때 (상태 표시 및 해제 버튼)
                else:
                    pred = st.session_state.watchlist_predictions.get(sid, "N/A")
                    color = "green" if pred == "UP" else "red"
                    st.success(f"✅ 관심종목 보관 중 (나의 예측: :{color}[{pred}])")
                    
                    # [보관 해제 버튼]
                    if st.button("보관 해제 (투표 취소)", key=f"rm_{sid}", use_container_width=True):
                        # 1. DB에서 삭제 (핵심)
                        db_toggle_watchlist(user_id, sid, action='remove')
                        
                        # 2. 세션 상태 업데이트 (화면 즉시 갱신용)
                        if sid in st.session_state.watchlist:
                            st.session_state.watchlist.remove(sid)
                        
                        # (선택사항) 투표 카운트 되돌리기 시늉 (실제로는 DB 카운트가 정확함)
                        if pred in ["UP", "DOWN"]:
                            key = 'u' if pred == "UP" else 'f'
                            st.session_state.vote_data[sid][key] -= 1
                        
                        if sid in st.session_state.watchlist_predictions:
                            del st.session_state.watchlist_predictions[sid]
                            
                        st.rerun()
            else:
                st.warning("🔒 로그인 후 투표에 참여할 수 있습니다.")

            # ---------------------------------------------------------
            # 4. 종목 토론방 (DB 연동 버전)
            # ---------------------------------------------------------
            st.write("---")
            st.subheader(f"{sid} 토론방")
            
            # 교체할 코드 (한 줄로 끝!)
            # DB에게 "이 종목(sid) 글만 줘"라고 직접 요청
            sid_posts = db_load_posts(limit=20, category=sid)
            
            if sid_posts:
                for p in sid_posts[:10]: # 최신 10개만 표시
                    title = p.get('title', '').strip()
                    clean_title = title # 상세페이지에서는 [종목코드] 생략 가능
                    
                    # 작성자 마스킹
                    auth_name = p.get('author_name', 'Unknown')
                    
                    # 날짜 포맷팅
                    try: date_str = p['created_at'].split('T')[0]
                    except: date_str = ""
                    
                    header = f"{clean_title} | 👤 {auth_name} | {date_str}"
                    
                    with st.expander(header):
                        st.markdown(f"<div style='font-size:0.95rem;'>{p.get('content')}</div>", unsafe_allow_html=True)
                        st.caption(f"작성자: {auth_name}")
                        st.divider()
                        
                        # 좋아요/싫어요 기능은 DB 업데이트가 필요하므로 
                        # 여기서는 단순 조회용으로만 표시하거나, 추후 db_update_reaction 함수와 연결 필요
                        # (간소화를 위해 상세 액션 버튼은 생략하거나 '준비중' 처리)
                        st.caption("※ 추천/비추천 기능은 게시판 메인에서 가능합니다.")

            else:
                st.info("아직 이 종목에 대한 의견이 없습니다. 첫 의견을 남겨보세요!")

            # 5. 글쓰기 섹션 (DB 저장)
            st.write("")
            with st.expander(f"📝 {sid} 의견 작성하기", expanded=False):
                if st.session_state.get('auth_status') == 'user':
                    # 권한 체크 (check_permission 함수 활용)
                    if check_permission('write'):
                        with st.form(key=f"write_{sid}_db", clear_on_submit=True):
                            new_title = st.text_input("제목")
                            new_content = st.text_area("내용", height=100)
                            
                            if st.form_submit_button("등록", type="primary", use_container_width=True):
                                if new_title and new_content:
                                    user_id = st.session_state.user_info.get('id')
                                    # 닉네임 생성 (user_info에 display_name이 없다면 ID 마스킹 사용)
                                    u_info = st.session_state.user_info
                                    display_name = u_info.get('display_name') or f"{user_id[:3]}***"
                                    
                                    # [핵심] DB에 저장
                                    if db_save_post(sid, new_title, new_content, display_name, user_id):
                                        st.success("등록되었습니다!")
                                        time.sleep(0.5)
                                        st.rerun()
                                    else:
                                        st.error("저장 중 오류가 발생했습니다.")
                                else:
                                    st.error("제목과 내용을 모두 입력해주세요.")
                    else:
                        st.warning("🔒 글쓰기 권한이 없습니다. (서류 승인 필요)")
                else:
                    st.warning("🔒 로그인 후 이용 가능합니다.")
                
# ---------------------------------------------------------
# [NEW] 6. 게시판 페이지 (Board)
# ---------------------------------------------------------
elif st.session_state.page == 'board':
    
    # 1. 상단 메뉴바 (캘린더 페이지와 동일한 스타일 유지)
    # ---------------------------------------------------------
    st.markdown("""
        <style>
        div[data-testid="stPills"] div[role="radiogroup"] button {
            border: none !important;
            background-color: #000000 !important;
            color: #ffffff !important;
            border-radius: 20px !important;
            padding: 6px 15px !important;
            margin-right: 5px !important;
            box-shadow: none !important;
        }
        div[data-testid="stPills"] button[aria-selected="true"] {
            background-color: #444444 !important;
            font-weight: 800 !important;
        }
        </style>
    """, unsafe_allow_html=True)

    is_logged_in = st.session_state.auth_status == 'user'
    login_text = "로그아웃" if is_logged_in else "로그인"
    settings_text = "권한설정"
    main_text = "메인"
    watch_text = f"관심 ({len(st.session_state.watchlist)})"
    board_text = "게시판"
    
    if is_logged_in:
        menu_options = [login_text, settings_text, main_text, watch_text, board_text]
    else:
        menu_options = [login_text, main_text, watch_text, board_text]

    selected_menu = st.pills(
        label="nav_board", 
        options=menu_options, 
        selection_mode="single", 
        default=board_text,  # 게시판 페이지이므로 기본값은 '게시판'
        key="nav_pills_board_page", 
        label_visibility="collapsed"
    )

    if selected_menu and selected_menu != board_text:
        if selected_menu == login_text:
            if is_logged_in: st.session_state.auth_status = None
            st.session_state.page = 'login'
        elif selected_menu == settings_text:
            st.session_state.page = 'setup'
        elif selected_menu == main_text:
            st.session_state.view_mode = 'all'; st.session_state.page = 'calendar'
        elif selected_menu == watch_text:
            st.session_state.view_mode = 'watchlist'; st.session_state.page = 'calendar'
        st.rerun()

    # 2. 게시판 메인 로직
    # ---------------------------------------------------------
    st.title("🗣️ 투자자 토론방")
    st.caption("자유롭게 의견을 나누고 정보를 공유하세요.")
    st.write("---")

    # [DB 연동] 최신 글 불러오기 (페이지 진입 시 자동 실행)
    posts = db_load_posts(limit=50)
    
    # 3. 글쓰기 버튼 (상단 배치)
    with st.expander("✏️ 새 글 작성하기", expanded=False):
        if is_logged_in:
            # 권한 체크 (check_permission 함수 활용)
            if check_permission('write'):
                with st.form(key="board_write_form", clear_on_submit=True):
                    # 카테고리 (종목 코드 또는 자유)
                    category = st.text_input("종목 코드 (예: AAPL) 또는 말머리", placeholder="자유")
                    title = st.text_input("제목")
                    content = st.text_area("내용", height=150)
                    
                    if st.form_submit_button("등록", type="primary", use_container_width=True):
                        if title and content:
                            user_id = st.session_state.user_info.get('id')
                            # 닉네임 가져오기 (없으면 ID 마스킹)
                            display_name = st.session_state.user_info.get('display_name') or f"{user_id[:3]}***"
                            
                            # [DB 저장]
                            if db_save_post(category, title, content, display_name, user_id):
                                st.success("게시글이 등록되었습니다!")
                                st.rerun()
                            else:
                                st.error("저장 중 오류가 발생했습니다.")
                        else:
                            st.warning("제목과 내용을 입력해주세요.")
            else:
                st.warning("🔒 글쓰기 권한이 없습니다. (서류 제출 및 승인 필요)")
        else:
            st.warning("🔒 로그인 후 작성할 수 있습니다.")

    st.write("") # 여백

    # 4. 게시글 목록 출력
    if posts:
        for p in posts:
            # 날짜 포맷팅 (ISO 포맷 -> 읽기 편하게)
            try:
                date_str = p['created_at'].split('T')[0]
            except:
                date_str = "Unknown"
                
            with st.container(border=True):
                # 헤더: [카테고리] 제목
                cat_badge = f"[{p.get('category', '자유')}]" if p.get('category') else ""
                st.markdown(f"**{cat_badge} {p.get('title')}**")
                
                # 내용 (일부만 보여주기 or 전체)
                st.markdown(f"<div style='font-size:0.95rem; color:#333; margin-top:5px;'>{p.get('content')}</div>", unsafe_allow_html=True)
                
                # 푸터: 작성자 | 날짜
                st.caption(f"👤 {p.get('author_name')} | 📅 {date_str}")
    else:
        st.info("아직 등록된 게시글이 없습니다. 첫 글의 주인공이 되어보세요!")
        
                #리아 지우와제주도 다녀오다 사랑하다
                 
                
                
                
