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

# 1. Supabase 연결 초기화 (리소스 캐싱)
@st.cache_resource
def init_supabase():
    """Supabase 클라이언트를 초기화하고 연결을 유지합니다."""
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Supabase 연결 오류: {e}")
        return None

# 전역 Supabase 객체 생성
supabase = init_supabase()

# [app.py 전용] 데이터 정제 및 범용 직송 함수
def sanitize_value(v):
    if v is None or pd.isna(v): return None
    if isinstance(v, (np.floating, float)):
        return float(v) if not (np.isinf(v) or np.isnan(v)) else 0.0
    if isinstance(v, (np.integer, int)): return int(v)
    if isinstance(v, (np.bool_, bool)): return bool(v)
    return str(v).strip().replace('\x00', '')

# [app.py 최적화 버전]
def batch_upsert(table_name, data_list, on_conflict="ticker"):
    """
    기존: 1개씩 여러 번 호출 (느림, 에러 위험)
    변경: 리스트 전체를 1번에 호출 (빠름, 안정적)
    """
    if not data_list: return
    
    url = st.secrets["supabase"]["url"].rstrip('/')
    key = st.secrets["supabase"]["key"]
    
    # URL 및 엔드포인트 설정
    base_url = url if "/rest/v1" in url else f"{url}/rest/v1"
    endpoint = f"{base_url}/{table_name}?on_conflict={on_conflict}"
    
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates" # 중복 시 덮어쓰기 허용
    }

    # 데이터 정제 및 벌크 전송용 리스트 생성
    clean_batch = []
    for item in data_list:
        payload = {k: sanitize_value(v) for k, v in item.items()}
        if payload.get(on_conflict):
            clean_batch.append(payload)

    if not clean_batch: return

    try:
        # [핵심] 리스트 전체를 한 번의 POST로 전송!
        resp = requests.post(endpoint, json=clean_batch, headers=headers)
        if resp.status_code not in [200, 201, 204]:
            st.error(f"DB 업데이트 실패: {resp.text}")
    except Exception as e:
        st.error(f"통신 오류: {e}")
            
# 2. 데이터 캐싱 함수 (데이터 캐싱: 3초 -> 0.1초 마법)
@st.cache_data(ttl=600)  # 600초(10분) 동안 메모리에 저장
def load_price_data():
    """
    Supabase의 price_cache 테이블에서 데이터를 한 번에 가져와서 DataFrame으로 변환합니다.
    이 함수는 10분에 한 번만 실행되고, 그 사이에는 0.1초 만에 결과를 반환합니다.
    """
    if not supabase:
        return pd.DataFrame()

    try:
        # 1. Supabase에서 모든 데이터 조회 (행 제한 없이)
        response = supabase.table("price_cache").select("*").execute()
        
        # 2. 데이터가 없으면 빈 DataFrame 반환
        if not response.data:
            return pd.DataFrame()
            
        # 3. DataFrame으로 변환
        df = pd.DataFrame(response.data)
        
        # 4. 숫자형 변환 및 날짜 정리 (오류 방지)
        if 'price' in df.columns:
            df['price'] = pd.to_numeric(df['price'], errors='coerce')
        if 'updated_at' in df.columns:
            df['updated_at'] = pd.to_datetime(df['updated_at'])
            
        return df
        
    except Exception as e:
        st.error(f"데이터 불러오기 실패: {e}")
        return pd.DataFrame()


# ==========================================
# [중요] 구글 라이브러리
# ==========================================
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- [AI 라이브러리] ---
import google.generativeai as genai
from google.generativeai import protos  
from openai import OpenAI

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

def db_load_sentiment_counts(ticker):
    """watchlist 테이블에서 해당 종목의 UP/DOWN 개수를 집계 (디버깅 추가)"""
    try:
        # 상승(UP) 투표 수 조회
        up_res = supabase.table("watchlist").select("ticker", count="exact").eq("ticker", ticker).eq("prediction", "UP").execute()
        up_count = up_res.count if up_res.count is not None else 0
        
        # 하락(DOWN) 투표 수 조회
        down_res = supabase.table("watchlist").select("ticker", count="exact").eq("ticker", ticker).eq("prediction", "DOWN").execute()
        down_count = down_res.count if down_res.count is not None else 0
        
        # [디버그 로그]
        print(f"--- DB Fetch Debug ({ticker}) --- UP: {up_count}, DOWN: {down_count}")
        return up_count, down_count
    except Exception as e:
        # 화면에 에러 표시
        import streamlit as st
        st.error(f"🐞 DB 집계 에러: {e}")
        return 0, 0


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

# # 8. 게시판 글 목록 불러오기
# [수정된 DB 함수] - 테이블 명칭 "board"로 정정
def db_load_posts(limit=50, category=None):
    """
    category가 있으면? -> 해당 종목 글만 DB에서 검색 후 최신순 정렬 (상황 1)
    category가 없으면? -> 전체 글을 DB에서 검색 후 최신순 정렬 (상황 2, 3)
    """
    try:
        # 🚨 [핵심 수정] "posts"를 "board"로 변경했습니다.
        query = supabase.table("board").select("*")
            
        # 2. [필터링 우선] category가 있다면 조건 추가
        if category:
            query = query.eq("category", category)  # SQL: WHERE category = 'AAPL'
            
        # 3. [정렬 및 제한] 최신순 정렬 후 개수 제한
        response = query.order("created_at", desc=True).limit(limit).execute()
        
        # 데이터가 있으면 리턴, 없으면 빈 리스트 리턴
        return response.data if response.data else []
        
    except Exception as e:
        # 에러 발생 시 로그 출력
        print(f"❌ DB 로딩 에러: {e}")
        return []

def db_toggle_post_reaction(post_id, user_id, reaction_type):
    """게시글 추천/비추천 토글 및 DB 저장 (중복 방지 포함)"""
    try:
        # 1. 현재 게시글 데이터 가져오기
        res = supabase.table("board").select("likes, dislikes, like_users, dislike_users").eq("id", post_id).execute()
        if not res.data: return False
        
        post = res.data[0]
        likes = post.get('likes') or 0
        dislikes = post.get('dislikes') or 0
        
        # 콤마(,)로 구분된 유저 ID 문자열을 리스트로 변환
        l_str = post.get('like_users') or ""
        d_str = post.get('dislike_users') or ""
        l_list = l_str.split(',') if l_str else []
        d_list = d_str.split(',') if d_str else []
        
        # 2. 추천(like) 버튼을 눌렀을 때
        if reaction_type == 'like':
            if user_id in l_list:      # 이미 추천했다면 취소
                l_list.remove(user_id)
                likes = max(0, likes - 1)
            else:                      # 추천하기
                l_list.append(user_id)
                likes += 1
                if user_id in d_list:  # 비추천 상태였다면 비추천 해제
                    d_list.remove(user_id)
                    dislikes = max(0, dislikes - 1)
                    
        # 3. 비추천(dislike) 버튼을 눌렀을 때
        elif reaction_type == 'dislike':
            if user_id in d_list:      # 이미 비추천했다면 취소
                d_list.remove(user_id)
                dislikes = max(0, dislikes - 1)
            else:                      # 비추천하기
                d_list.append(user_id)
                dislikes += 1
                if user_id in l_list:  # 추천 상태였다면 추천 해제
                    l_list.remove(user_id)
                    likes = max(0, likes - 1)
        
        # 4. DB 업데이트 적용
        supabase.table("board").update({
            "likes": likes,
            "dislikes": dislikes,
            "like_users": ",".join(l_list),
            "dislike_users": ",".join(d_list)
        }).eq("id", post_id).execute()
        
        return True
    except Exception as e:
        print(f"Reaction Update Error: {e}")
        return False

#  게시글 삭제 함수
def db_delete_post(post_id):
    try:
        response = supabase.table("board").delete().eq("id", post_id).execute()
        return True if response.data else False
    except Exception as e:
        print(f"Post Delete Error: {e}")
        return False

# [정보 공개 범위 업데이트 함수 - 수정 버전]
def db_update_user_visibility(user_id, visibility_data):
    try:
        # 1. 데이터가 리스트 형태인 경우 (예: ['학력', '직업'])
        if isinstance(visibility_data, list):
            # 리스트 안의 모든 요소를 강제로 문자열로 바꾸고, 'True/False'는 걸러냄
            clean_list = [str(item) for item in visibility_data if isinstance(item, str)]
            value_to_save = ",".join(clean_list)
        
        # 2. 데이터가 딕셔너리 형태인 경우 (예: {'학력': True, '직업': False})
        elif isinstance(visibility_data, dict):
            # 값이 True인 키(Key)들만 뽑아서 합침
            clean_list = [key for key, val in visibility_data.items() if val is True]
            value_to_save = ",".join(clean_list)
            
        # 3. 그 외 (이미 문자열인 경우 등)
        else:
            value_to_save = str(visibility_data)

        # Supabase 업데이트 실행
        response = supabase.table("users").update({"visibility": value_to_save}).eq("id", user_id).execute()
        
        return True if response.data else False
        
    except Exception as e:
        # 에러 발생 시 상세 내용 출력
        st.error(f"공개 범위 설정 실패: {e}")
        return False

# [관리자용] 회원 승인 처리 함수
def db_approve_user(user_id):
    try:
        # 1. 해당 유저의 status를 'approved'로 업데이트
        # 2. role도 'user'로 확실히 격상 (필요시)
        response = supabase.table("users")\
            .update({"status": "approved", "role": "user"})\
            .eq("id", user_id)\
            .execute()
        
        if response.data:
            return True
        return False
    except Exception as e:
        st.error(f"승인 처리 중 오류 발생: {e}")
        return False        

# [관리자용] 회원 삭제/거절 함수
def db_delete_user(user_id):
    try:
        response = supabase.table("users").delete().eq("id", user_id).execute()
        return True if response.data else False
    except Exception as e:
        st.error(f"삭제 실패: {e}")
        return False


# --- [수정된 버전] 데이터 신선도 조회 함수 ---
def get_last_cache_update_time():
    """Supabase에서 15분 워커의 가장 최근 생존 신고 시간을 가져옵니다."""
    if not supabase:
        return datetime.now() - timedelta(days=2)
        
    try:
        # 🚨 [핵심 수정] 무작정 최신순이 아니라, 워커가 남긴 "WORKER_LAST_RUN"만 콕 집어서 가져옴
        res = supabase.table("analysis_cache")\
            .select("updated_at")\
            .eq("cache_key", "WORKER_LAST_RUN")\
            .execute()
        
        if res.data and len(res.data) > 0:
            last_time_str = res.data[0]['updated_at']
            # pandas.to_datetime을 쓰면 복잡한 Z(UTC) 문자열이나 타임존을 에러 없이 완벽하게 변환해줍니다.
            return pd.to_datetime(last_time_str)
            
    except Exception as e:
        print(f"시간 조회 오류: {e}")
    
    return datetime.now() - timedelta(days=2)

# [수정] 5개 선택 항목을 모두 포함하여 저장하는 함수
def db_save_user_decision(user_id, ticker, total_score, ud_dict):
    if user_id == 'guest_id' or not user_id: return False
    try:
        data = {
            "user_id": str(user_id),
            "ticker": str(ticker),
            "score": int(total_score),
            "filing": ud_dict.get('filing'),
            "news": ud_dict.get('news'),
            "macro": ud_dict.get('macro'),
            "company": ud_dict.get('company'),
            "ipo_report": ud_dict.get('ipo_report'),
            "updated_at": datetime.now().isoformat()
        }
        # user_id와 ticker가 겹치면 덮어쓰기(Upsert)
        supabase.table("user_decisions").upsert(data, on_conflict="user_id,ticker").execute()
        return True
    except Exception as e:
        print(f"Decision Save Error: {e}")
        return False

# [신규] 재접속 시 해당 유저의 기존 선택값들을 불러오는 함수
def db_load_user_specific_decisions(user_id, ticker):
    if user_id == 'guest_id' or not user_id: return None
    try:
        res = supabase.table("user_decisions").select("*").eq("user_id", user_id).eq("ticker", ticker).execute()
        return res.data[0] if res.data else None
    except:
        return None

def db_load_community_scores(ticker):
    """특정 종목(ticker)에 대한 모든 실제 유저의 점수 리스트를 불러옴"""
    try:
        res = supabase.table("user_decisions").select("score").eq("ticker", ticker).execute()
        if res.data:
            return [item['score'] for item in res.data]
        return []
    except Exception as e:
        print(f"Community Load Error: {e}")
        return []

# ---------------------------------------------------------
# [0] AI 설정: Gemini 모델 초기화 (도구 자동 장착)
# ---------------------------------------------------------
@st.cache_resource
def configure_genai():
    genai_key = st.secrets.get("GENAI_API_KEY")
    if genai_key:
        genai.configure(api_key=genai_key)
        
        try:
            # [수정] worker.py와 동일한 구글 검색 도구 설정 적용
            return genai.GenerativeModel(
                model_name='gemini-2.0-flash', 
                tools=[{'google_search_retrieval': {}}] 
            )
        except Exception as e:
            # 설정 오류 시 검색 없이 기본 모델 반환
            print(f"Tool Config Error: {e}")
            return genai.GenerativeModel(model_name='gemini-2.0-flash')
            
    return None

model = configure_genai()

# ---------------------------------------------------------
# [1] 통합 분석 함수 (Tab 1 & Tab 4 대체용) - 프롬프트 강화판
# ---------------------------------------------------------

# (A) Tab 1용: 비즈니스 요약(고품질 유지) + 뉴스 통합(날짜 필터링 적용)
@st.cache_data(show_spinner=False, ttl=600)
def get_unified_tab1_analysis(company_name, ticker, lang_code):
    if not model: return "AI 모델 설정 오류", []
    
    # [Step 1] 언어별 고유 캐시 키 생성 (예: AAPL_Tab1_en)
    cache_key = f"{ticker}_Tab1_{lang_code}"
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

    # [Step 2] 캐시 없으면 AI 분석 실행
    current_date = now.strftime("%Y-%m-%d")
    one_year_ago = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    target_lang = LANG_PROMPT_MAP.get(lang_code, '전문적인 한국어(Korean)')

    prompt = f"""
    당신은 최고 수준의 증권사 리서치 센터의 시니어 애널리스트입니다.
    분석 대상: {company_name} ({ticker})
    오늘 날짜: {current_date}

    [작업 1: 비즈니스 모델 심층 분석]
    아래 [필수 작성 원칙]을 준수하여 리포트를 작성하세요.
    1. 언어: 반드시 '{target_lang}'로만 작성하세요. (영어 고유명사 제외). 
    2. 포맷: 반드시 3개의 문단으로 나누어 작성하세요. 문단 사이에는 줄바꿈을 명확히 넣으세요.
       - 1문단: 비즈니스 모델 및 경쟁 우위 (독점력, 시장 지배력 등)
       - 2문단: 재무 현황 및 공모 자금 활용 (매출 추이, 흑자 전환 여부, 자금 사용처)
       - 3문단: 향후 전망 및 투자 의견 (시장 성장성, 리스크 요인 포함)
    3. 금지: 제목, 소제목, 특수기호, 불렛포인트(-)를 절대 쓰지 마세요. 인사말이나 도입부 문구를 절대 포함하지 말고, 바로 본론부터 시작하세요.

    [작업 2: 최신 뉴스 수집]
    - 반드시 구글 검색(Google Search)을 실행하여 최신 정보를 확인하세요.
    - {current_date} 기준, 최근 3개월 이내의 뉴스 위주로 5개를 선정하세요.
    - 경고: {one_year_ago} 이전의 오래된 뉴스는 절대 포함하지 마세요.
    - 각 뉴스는 아래 JSON 형식으로 답변의 맨 마지막에 첨부하세요. 
    - [중요] sentiment 값은 파싱을 위해 무조건 "긍정", "부정", "일반" 중 하나를 한국어로 적으세요.
    
    형식: <JSON_START> {{ "news": [ {{ "title_en": "원문 영어 제목", "title_ko": "{target_lang}로 번역된 제목", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }} <JSON_END>
    """

    try:
        response = model.generate_content(prompt)
        full_text = response.text

        biz_analysis = full_text.split("<JSON_START>")[0].strip()
        biz_analysis = re.sub(r'#.*', '', biz_analysis).strip()
        paragraphs = [p.strip() for p in biz_analysis.split('\n') if len(p.strip()) > 20]
        
        html_output = ""
        for p in paragraphs:
            html_output += f'<p style="display:block; text-indent:14px; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>'

        news_list = []
        if "<JSON_START>" in full_text:
            try:
                json_str = full_text.split("<JSON_START>")[1].split("<JSON_END>")[0].strip()
                news_list = json.loads(json_str).get("news", [])
                for n in news_list:
                    if n.get('sentiment') == "긍정": n['bg'], n['color'] = "#e6f4ea", "#1e8e3e"
                    elif n.get('sentiment') == "부정": n['bg'], n['color'] = "#fce8e6", "#d93025"
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
def get_unified_tab4_analysis(company_name, ticker, lang_code):
    if not model: return {"rating": "Error", "summary": "설정 오류", "pro_con": "", "links": []}

    # [Step 1] Supabase DB 조회 (24시간 캐시) - 언어별 캐시 키 분리
    cache_key = f"{ticker}_Tab4_{lang_code}"
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

    # 현재 언어 설정 가져오기 (없으면 한국어 기본)
    target_lang = LANG_PROMPT_MAP.get(lang_code, '한국어')

    # [Step 2] 캐시 없으면 강력 프롬프트로 분석
    prompt = f"""
    당신은 월가 출신의 IPO 전문 분석가입니다. 
    구글 검색 도구를 사용하여 {company_name} ({ticker})에 대한 최신 기관 리포트(Seeking Alpha, Renaissance Capital, Morningstar 등)를 찾아 심층 분석하세요.

    [작성 지침]
    1. **언어**: 반드시 '{target_lang}'로 답변하세요.
    2. **분석 깊이**: 단순 사실 나열이 아닌, 구체적인 수치나 근거를 들어 전문적으로 분석하세요.
    3. **Pros & Cons**: 긍정적 요소(Pros) 2가지와 부정적/리스크 요소(Cons) 2가지를 명확히 구분하여 상세하게 서술하세요.
    4. **Rating**: 전반적인 월가 분위기를 종합하여 반드시 (Strong Buy/Buy/Hold/Sell) 중 하나로 선택하세요. (이 값은 영어로 유지)
    5. **Summary**: 전문적인 톤으로 5줄 이내로 핵심만 간결하게 작성하세요.
    6. **링크 금지**: Summary, Pro_con 내에는 'Source:', 'http...' 등의 출처 링크를 절대 포함하지 마세요.

    <JSON_START>
    {{
        "rating": "Buy/Hold/Sell 중 하나",
        "summary": "전문적인 3줄 요약 내용 ({target_lang})",
        "pro_con": "**Pros**:\\n- 내용\\n\\n**Cons**:\\n- 내용 (언어: {target_lang})",
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
                
                # [Step 3] 파싱 성공 시 DB에 저장 (언어별 키로 저장)
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
def get_market_dashboard_analysis(metrics_data, lang_code):
    if not model: return "AI 모델 연결 실패"

    cache_key = f"Global_Market_Dashboard_Tab2_{lang_code}"
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

    target_lang = LANG_PROMPT_MAP.get(lang_code, '한국어')

    prompt = f"""
    당신은 월가의 수석 시장 전략가(Chief Market Strategist)입니다.
    아래 제공된 실시간 시장 지표를 바탕으로 현재 미국 주식 시장과 IPO 시장의 상태를 진단하는 일일 브리핑을 작성하세요.

    [실시간 시장 지표]
    1. IPO 초기 수익률: {metrics_data.get('ipo_return', 0):.1f}%
    2. IPO 예정 물량: {metrics_data.get('ipo_volume', 0)}건
    3. 적자 기업 비율: {metrics_data.get('unprofitable_pct', 0):.1f}%
    4. 상장 철회율: {metrics_data.get('withdrawal_rate', 0):.1f}%
    5. VIX 지수: {metrics_data.get('vix', 0):.2f}
    6. 버핏 지수(GDP 대비 시총): {metrics_data.get('buffett_val', 0):.0f}%
    7. S&P 500 PE: {metrics_data.get('pe_ratio', 0):.1f}배
    8. Fear & Greed Index: {metrics_data.get('fear_greed', 50):.0f}점

    [작성 가이드]
    - 언어: 반드시 '{target_lang}'로 작성하세요.
    - 어조: 냉철하고 전문적인 어조 (인사말 생략)
    - 형식: 줄글로 된 3~5줄의 요약 리포트
    - 내용: 위 지표들을 종합하여 현재가 '기회'인지 '위험'인지 명확한 인사이트를 제공하세요.
    """

    try:
        response = model.generate_content(prompt)
        result = response.text

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
def get_daily_quote(lang='ko'):
    # 1. 예비용 명언 리스트 (다국어 지원)
    backup_quotes = [
        {"eng": "Opportunities don't happen. You create them.", "ko": "기회는 찾아오는 것이 아닙니다. 당신이 만드는 것입니다.", "ja": "機会は起こるものではありません。あなたが創り出すものです。", "author": "Chris Grosser"},
        {"eng": "The best way to predict the future is to create it.", "ko": "미래를 예측하는 가장 좋은 방법은 미래를 창조하는 것입니다.", "ja": "未来を予測する最良の方法は、それを創り出すことです。", "author": "Peter Drucker"},
        {"eng": "Innovation distinguishes between a leader and a follower.", "ko": "혁신이 리더와 추종자를 구분합니다.", "ja": "イノベーションがリーダーとフォロワーを区別します。", "author": "Steve Jobs"},
        {"eng": "Risk comes from not knowing what you're doing.", "ko": "위험은 자신이 무엇을 하는지 모르는 데서 옵니다.", "ja": "リスクは、自分が何をしているかを知らないことから来ます。", "author": "Warren Buffett"}
    ]

    try:
        # 1. API로 영어 명언 가져오기
        res = requests.get("https://api.quotable.io/random?tags=business", timeout=2).json()
        eng_text = res['content']
        author = res['author']
        
        # 영어를 선택한 경우 원문만 반환
        if lang == 'en':
            return {"eng": eng_text, "translated": eng_text, "author": author}
        
        # 2. 번역 API 시도 (선택된 언어로)
        translated_text = ""
        try:
            trans_url = "https://api.mymemory.translated.net/get"
            trans_res = requests.get(trans_url, params={'q': eng_text, 'langpair': f'en|{lang}'}, timeout=2).json()
            if trans_res['responseStatus'] == 200:
                translated_text = trans_res['responseData']['translatedText'].replace("&quot;", "'").replace("&amp;", "&")
        except:
            pass 

        # 번역 실패 시 영어 원문 유지
        if not translated_text: 
            translated_text = eng_text

        return {"eng": eng_text, "translated": translated_text, "author": author}

    except:
        # API 실패 시, 예비 리스트에서 랜덤 선택
        choice = random.choice(backup_quotes)
        trans = choice.get(lang, choice['eng'])
        return {"eng": choice['eng'], "translated": trans, "author": choice['author']}
        
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

@st.cache_data(ttl=3600) # 1시간 동안 Finnhub API 재호출 방지
def get_extended_ipo_data(api_key):
    now = datetime.now()
    ranges = [
        (now - timedelta(days=200), now + timedelta(days=120)),
        (now - timedelta(days=380), now - timedelta(days=170)),
        (now - timedelta(days=560), now - timedelta(days=350))
    ]
    
    all_data = []
    for start_dt, end_dt in ranges:
        start_str = start_dt.strftime('%Y-%m-%d')
        end_str = end_dt.strftime('%Y-%m-%d')
        url = f"https://finnhub.io/api/v1/calendar/ipo?from={start_str}&to={end_str}&token={api_key}"
        
        try:
            time.sleep(0.2) # 속도를 조금 더 올렸습니다.
            res = requests.get(url, timeout=5).json()
            ipo_list = res.get('ipoCalendar', [])
            if ipo_list:
                all_data.extend(ipo_list)
        except:
            continue
    
    if not all_data: return pd.DataFrame()
    
    df = pd.DataFrame(all_data)
    df = df.drop_duplicates(subset=['symbol', 'date'])
    df['공모일_dt'] = pd.to_datetime(df['date'], errors='coerce').dt.normalize()
    df = df.dropna(subset=['공모일_dt'])
    
    return df

@st.cache_data(ttl=600, show_spinner=False)
@st.cache_data(ttl=600, show_spinner=False)
def get_batch_prices(ticker_list):
    """
    DB에서 가격과 상태를 가져오고, 부족한 정보만 API로 채운 뒤 
    다시 DB에 '직송 모드'로 저장합니다.
    """
    if not ticker_list: return {}, {}
    clean_tickers = [str(t).strip() for t in ticker_list if t and str(t).strip().lower() != 'nan']
    
    cached_prices = {}
    db_status_map = {} 
    
    # [Step 1] Supabase DB 조회
    try:
        res = supabase.table("price_cache") \
            .select("ticker, price, status") \
            .in_("ticker", clean_tickers) \
            .execute()
        
        if res.data:
            for item in res.data:
                t = item['ticker']
                cached_prices[t] = float(item['price']) if item['price'] else 0.0
                db_status_map[t] = item.get('status', 'Active')
    except Exception as e:
        print(f"DB Read Error: {e}")

    # [Step 2] API 호출 대상 선별 (상태가 Active이면서 가격이 없는 경우만)
    missing_tickers = []
    for t in clean_tickers:
        status = db_status_map.get(t)
        price = cached_prices.get(t, 0)
        if status is None or (status == "Active" and price <= 0):
            missing_tickers.append(t)

    # [Step 3] API 호출 및 "직송 모드" 저장
    if missing_tickers:
        try:
            tickers_str = " ".join(missing_tickers)
            data = yf.download(tickers_str, period="1d", group_by='ticker', threads=True, progress=False)
            
            upsert_payload = []
            now_iso = datetime.now().isoformat()
            
            for t in missing_tickers:
                try:
                    # 데이터 추출
                    if len(missing_tickers) > 1:
                        target_data = data[t]['Close'].dropna()
                    else:
                        target_data = data['Close'].dropna()

                    if not target_data.empty:
                        current_p = float(round(target_data.iloc[-1], 4))
                        cached_prices[t] = current_p
                        db_status_map[t] = "Active"
                        
                        upsert_payload.append({
                            "ticker": t, 
                            "price": current_p, 
                            "status": "Active",
                            "updated_at": now_iso
                        })
                except: continue
            
            # [수정 핵심] 라이브러리 upsert 대신 우리가 만든 batch_upsert를 사용합니다.
            if upsert_payload:
                batch_upsert("price_cache", upsert_payload, on_conflict="ticker")

        except Exception as e:
            print(f"API Fetch Error: {e}")

    # [핵심] 호출부(app.py)에서 두 개를 받기로 했으므로 반드시 두 개를 리턴합니다.
    return cached_prices, db_status_map

def get_current_stock_price(ticker, api_key=None):
    """
    단일 종목의 현재가를 조회하되, DB에 '상장연기/폐지' 기록이 있다면 
    야후 API 호출을 건너뛰는 똑똑한 안전장치입니다.
    """
    try:
        # [Step 1] DB에서 먼저 상태와 가격 확인
        res = supabase.table("price_cache").select("price, status").eq("ticker", ticker).execute()
        
        if res.data:
            db_data = res.data[0]
            db_status = db_data.get('status', 'Active')
            db_price = float(db_data.get('price', 0.0))
            
            # 상장연기나 폐지 상태라면 API 호출 없이 바로 결과 반환
            if db_status in ["상장연기", "상장폐지"]:
                return db_price, db_status
            
            # Active이고 가격이 이미 있다면 그것도 바로 반환 (API 절약)
            if db_price > 0:
                return db_price, "Active"

        # [Step 2] DB에 없거나 업데이트가 필요할 때만 야후 호출
        stock = yf.Ticker(ticker)
        # 주말 대응을 위해 interval="1m"은 제거한 상태로 조회
        df = stock.history(period='1d')
        
        if not df.empty:
            current_p = float(round(df['Close'].iloc[-1], 4))
            return current_p, "Active"
        else:
            # 야후에서도 데이터가 없다면? (이 종목은 문제가 있는 것)
            return 0.0, "데이터없음"
            
    except Exception:
        return 0.0, "에러"


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
def get_financial_report_analysis(company_name, ticker, metrics, lang_code):
    if not model: return "AI 모델 설정 오류"

    cache_key = f"{ticker}_Financial_Report_Tab3_{lang_code}"
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

    target_lang = LANG_PROMPT_MAP.get(lang_code, '한국어')

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
    1. 언어: 반드시 '{target_lang}'로 작성하세요.
    2. 형식: 아래 4가지 소제목을 **반드시** 사용하여 단락을 구분하세요. (소제목 자체도 {target_lang}에 맞게 번역해도 좋습니다.)
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

# 1. 자동 모델 선택 함수 (2026년형 완전판)
@st.cache_data(show_spinner=False, ttl=86400)
def get_latest_stable_model():
    genai_key = st.secrets.get("GENAI_API_KEY")
    # 키가 없을 때의 기본값도 2.0으로 상향
    if not genai_key: return 'gemini-2.0-flash' 

    try:
        genai.configure(api_key=genai_key)
        
        # 1. 사용 가능한 모델 리스트 확보
        all_models = genai.list_models()
        candidate_models = []

        for m in all_models:
            # 조건: 'generateContent' 지원 및 이름에 'flash' 포함
            if 'generateContent' in m.supported_generation_methods and 'flash' in m.name:
                # 정규표현식으로 버전 숫자 추출
                match = re.search(r'gemini-(\d+\.\d+)-flash', m.name)
                if match:
                    version_float = float(match.group(1))
                    candidate_models.append({
                        "name": m.name,
                        "version": version_float
                    })

        # 2. 후보 모델이 있을 경우 가장 높은 버전을 반환
        if candidate_models:
            # 내림차순 정렬 (2.0, 1.5, 1.0 순)
            candidate_models.sort(key=lambda x: x["version"], reverse=True)
            return candidate_models[0]["name"]
            
        # 3. 후보가 없으면 2.0을 안전장치로 반환
        return 'gemini-2.0-flash'
        
    except Exception as e:
        # [중요] 모든 에러 발생 시 최후의 보루도 2.0-flash로 고정
        # 이제 1.5 때문에 404 에러가 나는 일은 없을 겁니다.
        print(f"Model selection error: {e}")
        return 'gemini-2.0-flash'

# ---------------------------------------------------------
# 2. 전역 모델 객체 생성 (404 에러 원천 차단 버전)
# ---------------------------------------------------------

# 함수를 호출하는 대신, 2026년 표준인 2.0 모델명을 직접 지정합니다.
SELECTED_MODEL_NAME = 'gemini-2.0-flash' 

if st.secrets.get("GENAI_API_KEY"):
    try:
        # model_name을 명시적으로 선언하여 가상 환경 오류를 방지합니다.
        model = genai.GenerativeModel(model_name=SELECTED_MODEL_NAME)
        print(f"✅ 전역 AI 모델 '{SELECTED_MODEL_NAME}' 로드 성공")
    except Exception as e:
        print(f"⚠️ 모델 로드 실패: {e}")
        model = None
else:
    # API 키가 없을 때만 에러 메시지를 띄웁니다.
    st.error("⚠️ GENAI_API_KEY가 설정되지 않았습니다. Streamlit Secrets를 확인하세요.")
    model = None

@st.cache_data(show_spinner=False, ttl=600) 
def get_ai_analysis(company_name, topic, points, structure_template, lang_code):
    if not model:
        return "AI 모델 설정 오류: API 키를 확인하세요."
    
    cache_key = f"{company_name}_{topic}_Tab0_{lang_code}"
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
        print(f"Tab0 DB Cache Error: {e}")

    target_lang = LANG_PROMPT_MAP.get(lang_code, '한국어')

    max_retries = 3
    for i in range(max_retries):
        try:
            prompt = f"""
            분석 대상: {company_name}의 {topic} 서류
            체크포인트: {points}
            
            [지침]
            당신은 월가 출신의 전문 분석가입니다. 
            단, "저는 분석가입니다" 같은 자기소개나 인사말은 절대 하지 마세요.
            
            [내용 구성 및 형식 - 반드시 아래 형식을 따를 것]
            각 문단의 시작에 **[소제목]**을 붙여서 내용을 명확히 구분하고 굵은 글씨를 생략하지 마세요.
            {structure_template}

            [문체 가이드]
            - 반드시 '{target_lang}'로 작성하세요.
            - 문장 끝이 끊기지 않도록 매끄럽게 연결하세요.
            - 핵심 위주로 작성하되, 너무 짧은 요약보다는 풍부한 인사이트를 담아주세요.
            """
            
            response = model.generate_content(prompt)
            analysis_result = response.text

            try:
                supabase.table("analysis_cache").upsert({
                    "cache_key": cache_key,
                    "content": analysis_result,
                    "updated_at": now.isoformat()
                }).execute()
            except: pass 

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

# 2. 세션 상태 안전 초기화 (lang 추가됨)
for key in ['page', 'auth_status', 'watchlist', 'posts', 'user_decisions', 'view_mode', 'user_info', 'selected_stock', 'lang']:
    if key not in st.session_state:
        if key == 'page': st.session_state[key] = 'login'
        elif key == 'watchlist': st.session_state[key] = []
        elif key == 'posts': st.session_state[key] = []
        elif key == 'user_decisions': st.session_state[key] = {}
        elif key == 'view_mode': st.session_state[key] = 'all'
        elif key == 'lang': st.session_state[key] = 'ko'  # 💡 [핵심] 언어 기본값 한국어 설정
        else: st.session_state[key] = None

# ==========================================
# [추가] 다국어(i18n) 지원 설정 및 사전(Dictionary)
# ==========================================
# 다국어 매핑 사전 (필요한 UI 텍스트를 여기에 계속 추가하시면 됩니다)
UI_TEXT = {
    # 1. 로그인 및 회원가입 (Auth)
    'id_label': {'ko': '아이디', 'en': 'User ID', 'ja': 'ユーザーID'},
    'pw_label': {'ko': '비밀번호', 'en': 'Password', 'ja': 'パスワード'},
    'pw_confirm': {'ko': '비밀번호 확인', 'en': 'Confirm Password', 'ja': 'パスワード再確認'},
    'btn_login': {'ko': '로그인', 'en': 'Login', 'ja': 'ログイン'},
    'btn_signup': {'ko': '회원가입', 'en': 'Sign Up', 'ja': '新規登録'},
    'btn_guest': {'ko': '구경하기', 'en': 'Explore as Guest', 'ja': 'ゲストとして見る'},
    'signup_step1': {'ko': '1단계: 정보 입력', 'en': 'Step 1: Information', 'ja': 'ステップ1：情報入力'},
    'signup_step3': {'ko': '3단계: 선택적 자격 증빙', 'en': 'Step 3: Verification (Optional)', 'ja': 'ステップ3：資格証明 (任意)'},
    'phone_label': {'ko': '연락처 (예: 01012345678)', 'en': 'Phone Number', 'ja': '電話番号'},
    'email_label': {'ko': '이메일', 'en': 'Email', 'ja': 'メールアドレス'},
    'auth_method': {'ko': '인증 수단', 'en': 'Verification Method', 'ja': '認証手段'},
    'auth_phone': {'ko': '휴대폰(가상)', 'en': 'Phone (Virtual)', 'ja': '携帯電話(仮想)'},
    'auth_email': {'ko': '이메일(실제)', 'en': 'Email (Real)', 'ja': 'メール(実用)'},
    'btn_get_code': {'ko': '인증번호 받기', 'en': 'Get Code', 'ja': '認証番号取得'},
    'btn_back': {'ko': '처음으로 돌아가기', 'en': 'Back to Home', 'ja': 'ホームに戻る'},
    'placeholder_code': {'ko': '숫자 6자리', 'en': '6-digit number', 'ja': '数字6桁'},
    'btn_confirm_code': {'ko': '인증 확인', 'en': 'Confirm', 'ja': '認証確認'},
    'btn_resend_code': {'ko': '취소/재발송', 'en': 'Resend/Cancel', 'ja': 'キャンセル/再送'},

    # 2. 네비게이션 메뉴 (Navigation)
    'menu_main': {'ko': '메인', 'en': 'Main', 'ja': 'メイン'},
    'menu_watch': {'ko': '관심', 'en': 'Watchlist', 'ja': 'お気に入り'},
    'menu_board': {'ko': '게시판', 'en': 'Board', 'ja': '掲示板'},
    'menu_settings': {'ko': '권한설정', 'en': 'Settings', 'ja': '設定'},
    'menu_logout': {'ko': '로그아웃', 'en': 'Logout', 'ja': 'ログアウト'},
    'menu_back': {'ko': '뒤로가기', 'en': 'Back', 'ja': '戻る'},

    # 3. 설정 페이지 (Setup)
    'setup_guide': {'ko': '활동닉네임과 노출범위를 확인해주세요. 인증회원은 글쓰기와 투표참여가 가능합니다.', 'en': 'Check your nickname and visibility. Verified members can write and vote.', 'ja': 'ニックネームと公開範囲を確認してください。認証会員は投稿と投票が可能です。'},
    'show_univ': {'ko': '대학 및 학과', 'en': 'University/Dept', 'ja': '大学・学科'},
    'show_job': {'ko': '직장 혹은 직업', 'en': 'Company/Job', 'ja': '職場・職業'},
    'show_asset': {'ko': '자산', 'en': 'Assets', 'ja': '資産'},
    'label_id_info': {'ko': '아이디: ', 'en': 'ID: ', 'ja': 'ユーザーID: '},
    'label_nick_info': {'ko': '활동 닉네임: ', 'en': 'Nickname: ', 'ja': '活動ニックネーム: '},
    'status_basic': {'ko': '🔒 Basic 회원(비인증회원)', 'en': '🔒 Basic Member (Unverified)', 'ja': '🔒 Basic会員(未認証)'},
    'status_pending': {'ko': '⏳ 승인 대기중', 'en': '⏳ Pending Approval', 'ja': '⏳ 承認待ち'},
    'status_approved': {'ko': '✅ 인증 회원', 'en': '✅ Verified Member', 'ja': '✅ 認証会員'},
    'status_anonymous': {'ko': '🔒 익명 모드', 'en': '🔒 Anonymous Mode', 'ja': '🔒 匿名モード'},
    
    # 💡 [수정됨] 저장 및 인증 버튼 텍스트 간소화
    'btn_save': {'ko': '저장', 'en': 'Save', 'ja': '保存'},
    'btn_verify': {'ko': '인증', 'en': 'Verify', 'ja': '認証'},

    # 4. 메인 캘린더 리스트 (Calendar)
    'filter_period': {'ko': '조회 기간', 'en': 'Period', 'ja': '照会期間'},
    'filter_sort': {'ko': '정렬 순서', 'en': 'Sort By', 'ja': '整列順序'},
    'period_upcoming': {'ko': '상장 예정 (30일)', 'en': 'Upcoming (30d)', 'ja': '上場予定 (30日)'},
    'period_6m': {'ko': '지난 6개월', 'en': 'Past 6 Months', 'ja': '過去6ヶ月'},
    'period_12m': {'ko': '지난 12개월', 'en': 'Past 12 Months', 'ja': '過去12ヶ月'},
    'period_18m': {'ko': '지난 18개월', 'en': 'Past 18 Months', 'ja': '過去18ヶ月'},
    'sort_latest': {'ko': '최신순', 'en': 'Latest', 'ja': '最新順'},
    'sort_return': {'ko': '수익률', 'en': 'Returns', 'ja': '収益率'},
    'status_delayed': {'ko': '상장연기', 'en': 'Delayed', 'ja': '上場延期'},
    'status_delisted': {'ko': '상장폐지', 'en': 'Delisted', 'ja': '上場廃止'},
    'label_ipo_price': {'ko': '공모가', 'en': 'IPO Price', 'ja': '公募価格'},
    'msg_no_stocks': {'ko': '조건에 맞는 종목이 없습니다.', 'en': 'No stocks match the criteria.', 'ja': '条件に合う銘柄がありません。'},

    # 5. 상세 페이지 탭 및 헤더 (Detail Tabs)
    'tab_0': {'ko': ' 주요공시', 'en': ' Filings', 'ja': ' 主な開示'},
    'tab_1': {'ko': ' 주요뉴스', 'en': ' News', 'ja': ' ニュース'},
    'tab_2': {'ko': ' 거시지표', 'en': ' Macro', 'ja': ' マクロ指標'},
    'tab_3': {'ko': ' 미시지표', 'en': ' Micro', 'ja': ' ミクロ指標'},
    'tab_4': {'ko': ' 기업평가', 'en': ' Valuation', 'ja': ' 企業評価'},
    'tab_5': {'ko': ' 투자결정', 'en': ' Decision', 'ja': ' 投資決定'},

    # 6. 각 탭 내부 텍스트 (Tab Content)
    'btn_summary_view': {'ko': ' 요약보기', 'en': ' View Summary', 'ja': ' 要約表示'},
    'msg_analyzing': {'ko': '핵심 내용을 분석 중입니다...', 'en': 'Analyzing key content...', 'ja': '主要内容を分析中です...'},
    'caption_algorithm': {'ko': ' 자체 알고리즘으로 공시자료를 요약해 제공합니다.', 'en': ' Summarized by our proprietary algorithm.', 'ja': ' 独自のアルゴリズムで開示資料を要約して提供します。'},
    'btn_sec_link': {'ko': ' 공시 확인하기', 'en': ' View SEC Filings', 'ja': ' 開示を確認する'},
    'btn_official_web': {'ko': '회사 공식홈페이지', 'en': 'Official Website', 'ja': '公式サイト'},
    'decision_question_filing': {'ko': '공시 정보에 대한 입장은?', 'en': 'Opinion on Filings?', 'ja': '開示情報に対する立場は？'},
    'opt_positive': {'ko': '수용적', 'en': 'Positive', 'ja': '受容的'},
    'opt_neutral': {'ko': '중립적', 'en': 'Neutral', 'ja': '中立的'},
    'opt_skeptical': {'ko': '회의적', 'en': 'Skeptical', 'ja': '懐疑的'},

    # Tab 2 & 3 (Macro/Micro)
    'market_overheat': {'ko': 'IPO 시장 과열 평가', 'en': 'IPO Market Overheat', 'ja': 'IPO市場の過熱評価'},
    'macro_overheat': {'ko': '미국거시경제 과열 평가', 'en': 'US Macro Overheat', 'ja': '米国マクロ経済の過熱評価'},
    'decision_question_macro': {'ko': '현재 거시경제(Macro) 상황에 대한 판단은?', 'en': 'Macro Outlook?', 'ja': '現在のマクロ経済状況の判断は？'},
    'opt_bubble': {'ko': '버블', 'en': 'Bubble', 'ja': 'バブル'},
    'opt_recession': {'ko': '침체', 'en': 'Recession', 'ja': '停滞'},
    'decision_question_micro': {'ko': ' 가치평가(Valuation) 최종 판단', 'en': ' Valuation Verdict', 'ja': ' 価値評価の最終判断'},
    'opt_overvalued': {'ko': '고평가', 'en': 'Overvalued', 'ja': '高評価'},
    'opt_undervalued': {'ko': '저평가', 'en': 'Undervalued', 'ja': '低評価'},

    # Tab 5 (Decision & Community)
    'community_outlook': {'ko': '실시간 커뮤니티 전망', 'en': 'Community Sentiment', 'ja': 'コミュニティ展望'},
    'btn_vote_up': {'ko': '📈 상승', 'en': '📈 Bull', 'ja': '📈 上昇'},
    'btn_vote_down': {'ko': '📉 하락', 'en': '📉 Bear', 'ja': '📉 下落'},
    'btn_vote_cancel': {'ko': '투표 취소 및 관심종목 해제', 'en': 'Cancel Vote & Remove', 'ja': '投票取消・お気に入り解除'},
    'decision_question_final': {'ko': '기관 분석을 참고한 나의 최종 판단은?', 'en': 'Final Investment Decision?', 'ja': '最終的な投資判断は？'},
    'opt_buy': {'ko': '매수', 'en': 'Buy', 'ja': '買い'},
    'opt_sell': {'ko': '매도', 'en': 'Sell', 'ja': '売り'},

    # 7. 게시판 (Board)
    'btn_write': {'ko': '글쓰기', 'en': 'Write', 'ja': '投稿'},
    'btn_search': {'ko': '검색하기', 'en': 'Search', 'ja': '検索'},
    'label_category': {'ko': '종목/말머리', 'en': 'Category', 'ja': 'カテゴリ'},
    'label_title': {'ko': '제목', 'en': 'Title', 'ja': 'タイトル'},
    'label_content': {'ko': '내용', 'en': 'Content', 'ja': '内容'},
    'btn_submit': {'ko': '등록', 'en': 'Submit', 'ja': '登録'},
    'hot_posts': {'ko': '인기글', 'en': 'HOT Posts', 'ja': '人気投稿'},
    'new_posts': {'ko': '최신글', 'en': 'Latest Posts', 'ja': '最新投稿'},
    'btn_more': {'ko': '🔽 더보기', 'en': '🔽 More', 'ja': '🔽 もっと見る'},
    'btn_recommend': {'ko': '추천', 'en': 'Like', 'ja': 'おすすめ'},
    'btn_dislike': {'ko': '비추천', 'en': 'Dislike', 'ja': '低評価'},
    'btn_delete': {'ko': '삭제', 'en': 'Delete', 'ja': '削除'},

    # 8. 면책 조항 (Disclaimer)
    'disclaimer_title': {'ko': '이용 유의사항', 'en': 'Disclaimer', 'ja': '免責事項'},
    'disclaimer_text': {
        'ko': '본 서비스는 자체 알고리즘과 AI 모델을 활용한 요약 정보를 제공하며, 원저작권자의 권리를 존중합니다. 요약본은 원문과 차이가 있을 수 있으므로 반드시 원문을 확인하시기 바랍니다. 모든 투자 결정의 최종 책임은 사용자 본인에게 있습니다.',
        'en': 'This service provides summaries using its own algorithms and AI models. Summaries may differ from the original; please check the source. All investment decisions are the sole responsibility of the user.',
        'ja': '本サービスは独自のアルゴリズムとAIモデルを活用した要約情報を提供します。要約は原文と異なる場合があるため、必ず原文を確認してください。すべての投資決定の最終責任は利用者本人が負うものとします。'
    },

    # 9. 메시지 알림 (Toast/Messages)
    'msg_login_needed': {'ko': '🔒 로그인이 필요한 기능입니다.', 'en': '🔒 Login required.', 'ja': '🔒 ログインが必要です。'},
}

def get_text(key):
    """현재 세션 언어에 맞는 텍스트를 반환하는 헬퍼 함수"""
    lang = st.session_state.lang
    return UI_TEXT.get(key, {}).get(lang, UI_TEXT.get(key, {}).get('ko', key))

# 현재 AI 프롬프트에 주입할 언어명 문자열 매핑
LANG_PROMPT_MAP = {
    'ko': '전문적인 한국어(Korean)',
    'en': 'Professional English',
    'ja': '専門的な日本語(Japanese)'
}

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
        # 💡 타이틀 영문 고정
        st.markdown("<h1 class='login-title'>UnicornFinder</h1>", unsafe_allow_html=True)
        
        # 상태 초기화
        if 'login_step' not in st.session_state: st.session_state.login_step = 'choice'
        
        # 가상 DB 초기화 (없을 경우)
        if 'db_users' not in st.session_state: st.session_state.db_users = ["admin"]

        # ---------------------------------------------------------
        # [통합 화면] 로그인 입력 + 버튼
        # ---------------------------------------------------------
        if st.session_state.login_step in ['choice', 'login_input']:
            
            st.write("<br>", unsafe_allow_html=True)
            
            # [1] 아이디/비번 입력창 (다국어 적용)
            l_id = st.text_input(get_text('id_label'), key="login_id")
            l_pw = st.text_input(get_text('pw_label'), type="password", key="login_pw")
            
            st.write("<br>", unsafe_allow_html=True)
            
            # [2] 버튼 섹션
            # 버튼 1: 로그인 (다국어 적용)
            if st.button(get_text('btn_login'), use_container_width=True, type="primary"):
                if not l_id or not l_pw:
                      st.error("아이디와 비밀번호를 입력해주세요." if st.session_state.lang == 'ko' else "Please enter your ID and password.")
                else:
                    with st.spinner("로그인 중..." if st.session_state.lang == 'ko' else "Logging in..."):
                        user = db_load_user(l_id)
                        
                        if user and str(user.get('pw')) == str(l_pw):
                            st.session_state.auth_status = 'user'
                            st.session_state.user_info = user
                            
                            saved_watchlist, saved_preds = db_sync_watchlist(l_id)
                            st.session_state.watchlist = saved_watchlist
                            st.session_state.watchlist_predictions = saved_preds
                            
                            raw_status = user.get('status', 'pending')
                            user_status = str(raw_status).strip().lower()
                            
                            if user_status == 'approved':
                                st.session_state.page = 'calendar'
                            else:
                                st.session_state.page = 'setup'
                                
                            st.rerun()
                        else:
                            st.error("아이디 또는 비밀번호가 틀립니다." if st.session_state.lang == 'ko' else "Invalid ID or password.")
            
            # 버튼 2: 회원가입 (다국어 적용)
            if st.button(get_text('btn_signup'), use_container_width=True):
                st.session_state.login_step = 'signup_input' 
                st.session_state.auth_code_sent = False      
                st.rerun()
                
            # 버튼 3: 구경하기 (다국어 적용)
            if st.button(get_text('btn_guest'), use_container_width=True):
                st.session_state.auth_status = 'guest'
                st.session_state.page = 'calendar'
                st.rerun()

            # =========================================================
            # [NEW 위치] 3개 국어 언어 선택 버튼 (구경하기 버튼 바로 아래)
            # =========================================================
            
            lang_cols = st.columns(3)
            with lang_cols[0]:
                if st.button("🇰🇷 한국어", use_container_width=True): 
                    st.session_state.lang = 'ko'
                    st.rerun()
            with lang_cols[1]:
                if st.button("🇺🇸 English", use_container_width=True): 
                    st.session_state.lang = 'en'
                    st.rerun()
            with lang_cols[2]:
                if st.button("🇯🇵 日本語", use_container_width=True): 
                    st.session_state.lang = 'ja'
                    st.rerun()

            # ---------------------------------------------------------
            # [3] 명언 섹션 (언어 선택에 따라 동적 번역)
            # ---------------------------------------------------------
            st.write("<br>", unsafe_allow_html=True) 
            
            # 선택된 언어 파라미터 전달
            quote_data = get_daily_quote(st.session_state.lang) 
            
            # 영어를 선택했을 때는 원문만 표기, 다른 언어일 때는 번역본 + 원문(sub_text) 표기
            if st.session_state.lang == 'en':
                sub_text = ""
            else:
                sub_text = f"<div style='font-size: 0.8rem; color: #888; font-style: italic; margin-bottom: 8px;'>{quote_data['eng']}</div>"

            # 💡 아래 html_content 부분에서 태그 사이의 줄바꿈을 없애서 에러를 방지합니다.
            html_content = f"""
            <div style="background-color: #ffffff; padding: 15px; border-radius: 12px; border: 1px solid #f0f0f0; text-align: center;">
                <div style="font-size: 0.95rem; color: #333; font-weight: 600; line-height: 1.5; margin-bottom: 5px;">
                    "{quote_data['translated']}"
                </div>{sub_text}<div style="font-size: 0.85rem; color: #666;">- {quote_data['author']} -</div>
            </div>
            """
            st.markdown(html_content, unsafe_allow_html=True)
            
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
                활동닉네임과 노출범위를 확인해주세요. 인증회원은 글쓰기와 투표참여가 가능합니다.
            </div>
        """, unsafe_allow_html=True)
        
        # -----------------------------------------------------------
        # 1. 내 정보 노출 설정 (체크박스)
        # -----------------------------------------------------------
        # 저장된 설정값 불러오기
        saved_vis = user.get('visibility', 'True,True,True').split(',')
        def_univ = saved_vis[0] == 'True' if len(saved_vis) > 0 else True
        def_job = saved_vis[1] == 'True' if len(saved_vis) > 1 else True
        def_asset = saved_vis[2] == 'True' if len(saved_vis) > 2 else True

        c1, c2, c3 = st.columns(3)
        show_univ = c1.checkbox("대학 및 학과", value=def_univ)
        show_job = c2.checkbox("직장 혹은 직업", value=def_job)
        show_asset = c3.checkbox("자산", value=def_asset)

        # -----------------------------------------------------------
        # 2. 닉네임 미리보기 (캡션 제거 버전)
        # -----------------------------------------------------------
        is_public_mode = any([show_univ, show_job, show_asset])
        
        info_parts = []
        if show_univ: info_parts.append(user.get('univ', ''))
        if show_job: info_parts.append(user.get('job', '')) 
        if show_asset: info_parts.append(get_asset_grade(user.get('asset', '')))
        
        prefix = " ".join([p for p in info_parts if p])
        
        final_nickname = f"{prefix} {full_masked_id}" if prefix else full_masked_id
        
        c_info, c_status = st.columns([2, 1])
        
        with c_info:
            st.markdown(f"아이디: {full_masked_id}")
            st.markdown(f"활동 닉네임: <span style='font-weight:bold; color:#5c6bc0;'>{final_nickname}</span>", unsafe_allow_html=True)
        
        with c_status:
            db_role = user.get('role', 'restricted')
            db_status = user.get('status', 'pending')
            
            if db_role == 'restricted':
                st.error("🔒 **Basic 회원(비인증회원)** (글쓰기 제한)")
            elif db_status == 'pending':
                st.warning("⏳ **승인 대기중** (관리자 확인중)")
            elif db_status == 'approved':
                if is_public_mode:
                    st.success("✅ **인증 회원** (모든 기능 사용가능)")
                else:
                    st.info("🔒 **익명 모드** (글쓰기 제한됨)")
        
        st.write("<br>", unsafe_allow_html=True)

        # -----------------------------------------------------------
        # 3. [메인 기능] 설정 저장 / 인증하기 / 로그아웃 (비율 조정)
        # -----------------------------------------------------------
        
        # 💡 [핵심 수정] 인증하기 버튼 추가를 위해 컬럼을 3개로 나눕니다.
        col_cert, col_save, col_logout = st.columns([1, 1.5, 1])

        # [인증하기 버튼] (회원 등급이 restricted 일 때만 노출하는 것이 좋습니다)
        with col_cert:
            if db_role == 'restricted' or db_status == 'rejected':
                if st.button("인증)", use_container_width=True):
                    # 1. 회원가입 프로세스 페이지로 강제 전환
                    st.session_state.page = 'login' 
                    st.session_state.login_step = 'signup_input'
                    # 2. 바로 서류제출 단계(3단계)로 점프
                    st.session_state.signup_stage = 3 
                    # 3. 현재 유저 정보를 임시 데이터에 백업 (DB 업데이트를 위해)
                    st.session_state.temp_user_data = {
                        "id": user.get('id'), 
                        "pw": user.get('pw'), 
                        "phone": user.get('phone'), 
                        "email": user.get('email')
                    }
                    st.rerun()

        # [저장 버튼]
        with col_save:
            if st.button("저장", type="primary", use_container_width=True):
                with st.spinner("설정 적용 중..."):
                    current_settings = [show_univ, show_job, show_asset]
                    vis_str = ",".join([str(v) for v in current_settings])
                    
                    update_data = {
                        "visibility": vis_str,
                        "display_name": final_nickname
                    }
                    
                    if db_update_user_info(user.get('id'), update_data):
                        st.session_state.user_info['visibility'] = vis_str
                        st.session_state.user_info['display_name'] = final_nickname
                        
                        st.session_state.page = 'calendar' 
                        st.rerun()
                    else:
                        st.error("저장 실패. 네트워크를 확인하세요.")

        # [로그아웃 버튼]
        with col_logout:
            if st.button("로그아웃", use_container_width=True):
                st.session_state.clear()
                st.rerun()

        
        # ===========================================================
        # 👇 [수정 완료] 관리자 승인 기능 (Supabase 연동 버전)
        # ===========================================================
        if user.get('role') == 'admin':

            # -------------------------------------------------------
            # [1] 기능 함수 정의 (Supabase 전용)
            # -------------------------------------------------------

            # [핵심] 승인 버튼 누르면 실행될 콜백 함수
            def callback_approve(target_id, target_email):
                # 1. Supabase 상태 업데이트 (기존 만들어둔 db_approve_user 활용)
                if db_approve_user(target_id):
                    # 2. 이메일 발송 (이메일 기능이 살아있다면)
                    if target_email:
                        try:
                            send_approval_email(target_email, target_id)
                        except: pass
                    # 3. 알림 메시지
                    st.toast(f"✅ {target_id}님 승인 처리 완료!", icon="🎉")
                else:
                    st.toast(f"❌ {target_id} 처리 실패. DB 연결 확인 필요.", icon="⚠️")

            # [핵심] 보류 버튼 누르면 실행될 콜백 함수
            def callback_reject(target_id, target_email):
                # 입력된 사유 가져오기
                reason_key = f"rej_setup_{target_id}"
                reason = st.session_state.get(reason_key, "")

                if not reason:
                    st.toast("⚠️ 보류 사유를 입력해주세요!", icon="❗")
                    return 

                # 1. Supabase 상태 업데이트 (rejected로 변경)
                try:
                    res = supabase.table("users").update({"status": "rejected"}).eq("id", target_id).execute()
                    if res.data:
                        # 2. 이메일 발송
                        if target_email:
                            try:
                                send_rejection_email(target_email, target_id, reason)
                            except: pass
                        st.toast(f"🛑 {target_id}님 보류 처리 완료.", icon="✅")
                    else:
                        st.toast("❌ 처리 실패 (데이터 없음).", icon="⚠️")
                except Exception as e:
                    st.toast(f"❌ 오류: {e}", icon="⚠️")

            # -------------------------------------------------------
            # [2] 화면 그리기 (UI)
            # -------------------------------------------------------


            # --- [추가] 📡 데이터 워커 상태 점검 배지 ---
            # 이 섹션은 워커(GitHub Actions)가 정상인지 관리자가 즉시 확인하는 용도입니다.
            with st.container():
                last_update = get_last_cache_update_time() # 아까 만든 함수 호출
                
                # 한국 시간 표시를 위해 9시간 더하기
                display_time = last_update + timedelta(hours=9)
                now = datetime.now(last_update.tzinfo)
    
                col_status1, col_status2 = st.columns([2, 1])
                with col_status1:
                    if last_update < now - timedelta(hours=24):
                        st.error(f"❌ 워커 중단됨: {display_time.strftime('%Y-%m-%d %H:%M')}")
                    else:
                        st.success(f"✅ 데이터 정상: {display_time.strftime('%m-%d %H:%M')}")
                
                with col_status2:
                    if st.button("🔄 시스템 전체 새로고침", key="admin_refresh"):
                        st.cache_data.clear() # 🚨 [핵심 추가] 쥐고 있던 예전 데이터를 강제로 버림
                        st.rerun()
            
            st.divider()
                
            
            # 목록 불러오기 버튼
            if st.button("가입신청회원 새로고침", key="btn_refresh_list"):
                st.rerun()

            # Supabase에서 전체 유저 로드
            all_users_adm = db_load_all_users()
            # status가 pending인 유저만 필터링
            pending_users = [u for u in all_users_adm if u.get('status') == 'pending']
            
            if not pending_users:
                st.info("현재 승인 대기 중인 유저가 없습니다.")
            else:
                for pu in pending_users:
                    u_id = pu.get('id')
                    u_email = pu.get('email')
                    
                    with st.expander(f"{u_id} ({pu.get('univ') or '미기재'})"):
                        st.write(f"**이메일**: {u_email} | **연락처**: {pu.get('phone')}")
                        st.write(f"**직업**: {pu.get('job')} | **자산**: {pu.get('asset')}")
                        
                        # 증빙 서류 링크 (Supabase Storage URL 또는 Drive URL)
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            if pu.get('link_univ') not in ["미제출", None]: st.link_button("🎓 대학 증빙", pu.get('link_univ'))
                        with c2:
                            if pu.get('link_job') not in ["미제출", None]: st.link_button("💼 직업 증빙", pu.get('link_job'))
                        with c3:
                            if pu.get('link_asset') not in ["미제출", None]: st.link_button("💰 자산 증빙", pu.get('link_asset'))
                        
                        st.divider()

                        # 보류 사유 입력창
                        st.text_input("보류 사유", placeholder="예: 서류 식별 불가", key=f"rej_setup_{u_id}")
                        
                        btn_col1, btn_col2 = st.columns(2)
                        
                        # [승인 버튼]
                        with btn_col1:
                            st.button(
                                "✅ 승인", 
                                key=f"btn_app_{u_id}", 
                                use_container_width=True,
                                on_click=callback_approve, 
                                args=(u_id, u_email)
                            )

                        # [보류 버튼]
                        with btn_col2:
                            st.button(
                                "❌ 보류", 
                                key=f"btn_rej_{u_id}", 
                                use_container_width=True, 
                                type="primary",
                                on_click=callback_reject,
                                args=(u_id, u_email)
                            )

# [추가] 메인 화면 전용 컨테이너 생성
# 이 컨테이너는 페이지가 바뀔 때 내부를 완전히 비우고 새로 그립니다.
main_area = st.empty()

with main_area.container():
    # ---------------------------------------------------------
    # 4. 캘린더 페이지 (Calendar)
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
            
            # 🚨 안전장치: 변수가 없어서 튕기는 현상을 원천 차단하기 위해 미리 기본값 선언
            sort_option = "최신순"  
            period = "상장 예정 (30일)"
            display_df = pd.DataFrame() 
    
            if view_mode == 'watchlist':
                if st.button("🔄 전체 목록 보기", use_container_width=True, key="btn_view_all_main_final"):
                    st.session_state.view_mode = 'all'
                    st.rerun()
                    
                display_df = all_df[all_df['symbol'].isin(st.session_state.watchlist)]
                if display_df.empty:
                    st.info("아직 관심 종목에 담은 기업이 없습니다.")
                    
            else:
                col_f1, col_f2 = st.columns([1, 1]) 
                with col_f1:
                    period = st.selectbox("조회 기간", ["상장 예정 (30일)", "지난 6개월", "지난 12개월", "지난 18개월"], key="filter_period_final", label_visibility="collapsed")
                with col_f2:
                    sort_option = st.selectbox("정렬 순서", ["최신순", "수익률"], key="filter_sort_final", label_visibility="collapsed")
                
                # 🚨 [복구된 핵심 코드] 선택한 기간에 맞춰 display_df 데이터를 깎아냅니다.
                if period == "상장 예정 (30일)":
                    display_df = all_df[(all_df['공모일_dt'] >= today_dt) & (all_df['공모일_dt'] <= today_dt + timedelta(days=30))]
                else:
                    if period == "지난 6개월": start_date = today_dt - timedelta(days=180)
                    elif period == "지난 12개월": start_date = today_dt - timedelta(days=365)
                    elif period == "지난 18개월": start_date = today_dt - timedelta(days=540)
                    
                    display_df = all_df[(all_df['공모일_dt'] < today_dt) & (all_df['공모일_dt'] >= start_date)]
    
            # ----------------------------------------------------------------
            # 🚀 [최적화 수정본] Batch 주가 조회 및 안전한 상태 표시
            # ----------------------------------------------------------------
            if not display_df.empty:
                symbols_to_fetch = display_df['symbol'].dropna().unique().tolist()
                
                with st.spinner("실시간 주가 확인 중..."):
                    # [수정] 이제 함수가 (가격맵, 상태맵) 두 개를 리턴합니다.
                    all_prices_map, all_status_map = get_batch_prices(symbols_to_fetch)
                    
                db_count = len(all_prices_map)
                total_req = len(symbols_to_fetch)
                missing_count = total_req - db_count
    
                if missing_count > 0:
                    st.toast(f"🐢 속도 저하: DB({db_count}개) / ☁️ API 호출({missing_count}개)", icon="⚠️")
                else:
                    st.toast(f"⚡ 고속 로딩: {db_count}개 전량 DB 호출 성공!", icon="✅")
    
                # 데이터 매핑 (가격과 상태를 데이터프레임에 추가)
                display_df['live_price'] = display_df['symbol'].map(all_prices_map).fillna(0.0)
                display_df['live_status'] = display_df['symbol'].map(all_status_map).fillna("Active")
                
                # 수익률 계산 (Active인 경우만 계산)
                def parse_price(x):
                    try: return float(str(x).replace('$','').split('-')[0])
                    except: return 0.0
    
                p_ipo_series = display_df['price'].apply(parse_price)
                display_df['temp_return'] = np.where(
                    (p_ipo_series > 0) & (display_df['live_price'] > 0) & (display_df['live_status'] == "Active"),
                    ((display_df['live_price'] - p_ipo_series) / p_ipo_series) * 100,
                    -9999
                )
    
                # [수정] 5. 정렬 최종 적용 (구조 통합)
                # 먼저 컬럼의 타입을 확실히 float으로 강제 변환합니다.
                display_df['temp_return'] = pd.to_numeric(display_df['temp_return'], errors='coerce').fillna(-9999.0)
        
                if sort_option == "수익률":
                    # 수익률 정렬 (내림차순)
                    # -9999인 데이터(Active가 아니거나 가격 없는 종목)를 마지막으로 보냅니다.
                    display_df = display_df.sort_values(by='temp_return', ascending=False)
                else:
                    # 기본값: 최신순 정렬
                    display_df = display_df.sort_values(by='공모일_dt', ascending=False)
        
                # 만약 watchlist 모드에서만 추가적인 정렬 규칙이 필요하다면 여기에 별도로 작성 가능하지만, 
                # 위 로직만으로도 '관심종목' 페이지 내에서의 수익률 정렬이 가능해집니다.
    
            # ----------------------------------------------------------------
            # [핵심] 리스트 레이아웃 (7 : 3 비율) - 상태값(Status) 반영 버전
            # ----------------------------------------------------------------
            if not display_df.empty:
                for i, row in display_df.iterrows():
                    p_val = pd.to_numeric(str(row.get('price','')).replace('$','').split('-')[0], errors='coerce')
                    p_val = p_val if p_val and p_val > 0 else 0
                    
                    live_p = row.get('live_price', 0)
                    live_s = row.get('live_status', 'Active')
                    
                    # [수정] 가격 표시 로직: 상태에 따라 텍스트 변경
                    if live_s == "상장연기":
                        price_html = f"""
                            <div class='price-main' style='color:#1919e6 !important;'>상장연기</div>
                            <div class='price-sub' style='color:#666666 !important;'>IPO: ${p_val:,.2f}</div>
                        """
                    elif live_s == "상장폐지":
                        price_html = f"""
                            <div class='price-main' style='color:#888888 !important;'>상장폐지</div>
                            <div class='price-sub' style='color:#666666 !important;'>IPO: ${p_val:,.2f}</div>
                        """
                    elif live_p > 0:
                        pct = ((live_p - p_val) / p_val) * 100 if p_val > 0 else 0
                        if pct > 0:
                            change_color = "#e61919"; arrow = "▲"
                        elif pct < 0:
                            change_color = "#1919e6"; arrow = "▼"
                        else:
                            change_color = "#333333"; arrow = ""
    
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
        
        if not stock:
            st.session_state.page = 'calendar'
            st.rerun()
    
        # --- [데이터 복구 핵심 변수 추출] ---
        sid = stock['symbol']
        user_info = st.session_state.get('user_info') or {}
        user_id = user_info.get('id', 'guest_id')
    
        # --- [신규] 재접속 유저를 위한 데이터 복구 로직 ---
        # 세션에 해당 종목의 판단 데이터가 없을 때만 DB에서 1회 로드합니다.
        if sid not in st.session_state.user_decisions:
            with st.spinner("과거 분석 기록을 불러오는 중..."):
                saved_data = db_load_user_specific_decisions(user_id, sid)
                if saved_data:
                    # DB에 저장된 값이 있다면 세션 상태에 복구 (라디오 버튼 위치 고정)
                    st.session_state.user_decisions[sid] = {
                        "filing": saved_data.get('filing'),
                        "news": saved_data.get('news'),
                        "macro": saved_data.get('macro'),
                        "company": saved_data.get('company'),
                        "ipo_report": saved_data.get('ipo_report')
                    }
                else:
                    # 기록이 없는 신규 종목일 경우 빈 딕셔너리 생성
                    st.session_state.user_decisions[sid] = {}
    
        # [1] 변수 초기화 (기존 코드 유지)
        profile = None
        fin_data = {}
        current_p = 0
        off_val = 0
    
        if stock:
            # -------------------------------------------------------------------------
            # [2] 상단 메뉴바 및 스타일 설정
            # -------------------------------------------------------------------------
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
    
            # 'symbol' 대신 'stock['symbol']'을 직접 넣어서 호출합니다.
            current_p, current_s = get_current_stock_price(stock['symbol'], MY_API_KEY)
    
            # 2. 헤더 출력 로직 (상태값에 따른 분기 처리)
            if current_s == "상장연기":
                p_info = f"<span style='font-size: 0.9rem; color: #1919e6;'>({date_str} / 공모 ${off_val} / 📅 상장연기/기타)</span>"
            elif current_s == "상장폐지":
                p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / 공모 ${off_val} / 🚫 상장폐지)</span>"
            elif current_p > 0 and off_val > 0:
                # 정상적인 Active 상태일 때 수익률 계산
                pct = ((current_p - off_val) / off_val) * 100
                color = "#00ff41" if pct >= 0 else "#ff4b4b"
                icon = "▲" if pct >= 0 else "▼"
                # 소수점 2자리까지만 예쁘게 출력
                p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / 공모 ${off_val} / 현재 ${current_p:,.2f} <span style='color:{color}; font-weight:bold;'>{icon} {abs(pct):.1f}%</span>)</span>"
            else:
                # 상장 전이거나 가격 데이터가 아직 없는 경우
                p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / 공모 ${off_val} / 상장 대기)</span>"
    
            # 3. 여기까지 (최종 출력)
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
                        analysis_result = get_ai_analysis(
                            stock['name'], 
                            topic, 
                            curr_meta['points'], 
                            curr_meta.get('structure', ""), # 쉼표(,) 필수
                            st.session_state.lang           # 💡 다국어 파라미터 추가 완료
                        )
                        
                        if "ERROR_DETAILS" in analysis_result:
                            st.error("잠시 후 다시 시도해주세요. (할당량 초과 가능성)")
                            with st.expander("상세 에러 내용"):
                                st.code(analysis_result)
                        else:
                            st.markdown(analysis_result)
                    
                    # 3. 요청하신 하단 캡션 문구
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
                # [1] 통합 분석 데이터 호출 (비즈니스 요약 + 뉴스 5개 통합)
                with st.spinner(f"{stock['name']}의 최신 데이터를 정밀 분석 중입니다..."):
                    # [수정] 파라미터 맨 끝에 st.session_state.lang 을 추가합니다.
                    biz_info, final_display_news = get_unified_tab1_analysis(stock['name'], stock['symbol'], st.session_state.lang)

                # [2] 기업 심층 분석 섹션 (Expander)
                st.write("<br>", unsafe_allow_html=True)
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
                        
                        st.caption("Google Search 기반으로 실시간 분석 및 뉴스를 제공합니다.")
                    else:
                        st.error("⚠️ 비즈니스 분석 정보를 가져오지 못했습니다.")
    
                st.write("<br>", unsafe_allow_html=True)
    
                # [3] 뉴스 리스트 섹션
                if final_display_news:
                    for i, n in enumerate(final_display_news):
                        ko_title = n.get('title_ko', '번역 오류')
                        en_title = n.get('title_en', 'No Title')
                        sentiment_label = n.get('sentiment', '일반')
                        bg_color = n.get('bg', '#f1f3f4')
                        text_color = n.get('color', '#5f6368')
                        news_link = n.get('link', '#')
                        news_date = n.get('date', 'Recent')
    
                        # 특수 기호 처리
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
    
                # 결정 박스
                draw_decision_box("news", "신규기업에 대해 어떤 인상인가요?", ["긍정적", "중립적", "부정적"])
    
                # 면책 조항
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
            
                st.write("<br>", unsafe_allow_html=True)
                
                # --- 3. AI 종합 진단 (Expander) ---
                with st.expander("거시지표 분석", expanded=False): 
                    try:
                        # 💡 [핵심 수정] 여기에 st.session_state.lang 을 추가했습니다!
                        ai_market_comment = get_market_dashboard_analysis(md, st.session_state.lang)
                        
                        # AI 답변에 포함된 불필요한 HTML 태그 강제 제거!
                        if isinstance(ai_market_comment, str):
                            ai_market_comment = ai_market_comment.replace("</div>", "").replace("<div>", "").replace("```html", "").replace("```", "").strip()
                            
                    except NameError:
                        ai_market_comment = "AI 분석 함수가 아직 로드되지 않았습니다."
    
                    # 제목 div를 제거하고 본문만 남긴 버전
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
                # 1. 함수 호출 (다국어 파라미터 추가)
                with st.spinner(f"전문 기관 데이터를 정밀 수집 중..."):
                    # 💡 [핵심 수정] 맨 끝에 st.session_state.lang 을 추가했습니다!
                    result = get_unified_tab4_analysis(stock['name'], stock['symbol'], st.session_state.lang)
                
                # 2. 결과 데이터 매핑 (기존 코드 유지)
                summary_raw = result.get('summary', '')
                pro_con_raw = result.get('pro_con', '')
                rating_val = str(result.get('rating', 'Hold')).strip()
                score_val = str(result.get('score', '3')).strip() 
                sources = result.get('links', [])
                q = stock['symbol'] if stock['symbol'] else stock['name']
    
                st.write("<br>", unsafe_allow_html=True)
            
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
            # --- Tab 5: 최종 투자 결정 (데이터 영구 저장 및 복구 통합) ---
            # =========================================================
            with tab5:
                # ---------------------------------------------------------------------------
                # 1. [스타일] 흰 배경 및 UI 설정
                # ---------------------------------------------------------------------------
                st.markdown("""
                    <style>
                    .stApp { background-color: #ffffff !important; color: #000000 !important; }
                    p, h1, h2, h3, h4, h5, h6, span, li, div { color: #000000 !important; }
                    .streamlit-expanderHeader { background-color: #f8f9fa !important; color: #000000 !important; border: 1px solid #ddd !important; }
                    div[data-testid="stExpanderDetails"] { background-color: #ffffff !important; border: 1px solid #ddd !important; border-top: none !important; }
                    </style>
                """, unsafe_allow_html=True)
                
                sid = stock['symbol']
                user_info = st.session_state.get('user_info') or {}
                user_id = user_info.get('id', 'guest_id')
    
                # ---------------------------------------------------------
                # 2. 투자 분석 결과 섹션 (차트 시각화 및 DB 동기화)
                # ---------------------------------------------------------
                if 'user_decisions' not in st.session_state: st.session_state.user_decisions = {}
                ud = st.session_state.user_decisions.get(sid, {})
                
                steps = [
                    ('filing', 'Step 1 (공시)'), ('news', 'Step 2 (뉴스)'), 
                    ('macro', 'Step 3 (거시)'), ('company', 'Step 4 (미시)'), 
                    ('ipo_report', 'Step 5 (기관)')
                ]
                
                missing_steps = [label for step, label in steps if not ud.get(step)]
                
                if missing_steps:
                    st.info(f"모든 분석단계({', '.join(missing_steps)})를 완료하면 나와 시장 참여자들의 리얼타임 종합 결과 차트가 표시됩니다.")
                else:
                    # 1) 내 점수 계산 로직
                    score_map = {
                        "긍정적": 1, "수용적": 1, "안정적": 1, "저평가": 1, "매수": 1, "침체": 1,
                        "중립적": 0, "중립": 0, "적정": 0,
                        "부정적": -1, "회의적": -1, "버블": -1, "고평가": -1, "매도": -1
                    }
                    user_score = sum(score_map.get(ud.get(s[0], "중립적"), 0) for s in steps)
                    
                    # 2) 🚨 [영구 저장] 내 선택 텍스트들과 합산 점수를 DB에 동시 저장
                    if user_id != 'guest_id':
                        db_save_user_decision(user_id, sid, user_score, ud)
                    
                    # 3) DB에서 전체 커뮤니티 데이터 로드
                    community_scores = db_load_community_scores(sid)
                    if not community_scores:
                        community_scores = [user_score]
    
                    import pandas as pd
                    import plotly.graph_objects as go
                    
                    total_participants = len(community_scores)
    
                    # 4) 통계 계산
                    optimists = sum(1 for s in community_scores if s > 0)
                    optimist_pct = (optimists / total_participants * 100) if total_participants > 0 else 0
                    user_percentile = (sum(1 for s in community_scores if s <= user_score) / total_participants * 100) if total_participants > 0 else 100
    
                    m1, m2 = st.columns(2)
                    m1.metric("시장 참여자 낙관도", f"{optimist_pct:.1f}%", help="전체 참여자 중 긍정 평가 비율")
                    m2.metric("나의 분석 위치", f"상위 {100-user_percentile:.1f}%", f"{user_score}점")
                    
                    # 5) 차트 그리기
                    score_counts = pd.Series(community_scores).value_counts().sort_index()
                    score_counts = (pd.Series(0, index=range(-5, 6)) + score_counts).fillna(0)
                    
                    fig = go.Figure(go.Bar(
                        x=score_counts.index, 
                        y=score_counts.values, 
                        marker_color=['#ff4b4b' if x == user_score else '#6e8efb' for x in score_counts.index],
                        hovertemplate="점수: %{x}<br>인원: %{y}명<extra></extra>"
                    ))
                    fig.update_layout(
                        height=220, 
                        margin=dict(l=10, r=10, t=30, b=10), 
                        xaxis=dict(title="종합 분석 점수 (-5 ~ +5)", tickmode='linear'), 
                        yaxis=dict(title="참여자 수", showticklabels=True),
                       
                        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
                    )
                    st.plotly_chart(fig, use_container_width=True)
    
                # ---------------------------------------------------------
                # 3. 전망 투표 및 실시간 Sentiment (BULL vs BEAR) - 최종본
                # ---------------------------------------------------------
                st.write("<br>", unsafe_allow_html=True)
                st.markdown("<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 15px;'>실시간 커뮤니티 전망</div>", unsafe_allow_html=True)
                
                # [1] 실시간 데이터 로드 (DB에서 직접 집계)
                up_voters, down_voters = db_load_sentiment_counts(sid)
                total_votes = up_voters + down_voters
                
                # 비율 계산 (분모 0 방지)
                up_pct = (up_voters / total_votes * 100) if total_votes > 0 else 50
                down_pct = (down_voters / total_votes * 100) if total_votes > 0 else 50
    
                # [2] Bullish & Bearish 시각화 카드
                col_bull, col_bear = st.columns(2)
                
                with col_bull:
                    st.markdown(f"""
                        <div style="background-color: #ebfaef; padding: 20px; border-radius: 15px; text-align: center; border: 1px solid #c3e6cb;">
                            <img src="https://img.icons8.com/color/96/bull.png" width="60" style="margin-bottom:10px;">
                            <div style="color: #28a745; font-weight: 800; font-size: 1.2rem;">BULLISH</div>
                            <div style="color: #333; font-size: 1.5rem; font-weight: 900;">{up_pct:.1f}%</div>
                            
                        </div>
                    """, unsafe_allow_html=True)
    
                with col_bear:
                    st.markdown(f"""
                        <div style="background-color: #fff5f5; padding: 20px; border-radius: 15px; text-align: center; border: 1px solid #feb2b2;">
                            <img src="https://img.icons8.com/color/96/bear.png" width="60" style="margin-bottom:10px;">
                            <div style="color: #dc3545; font-weight: 800; font-size: 1.2rem;">BEARISH</div>
                            <div style="color: #333; font-size: 1.5rem; font-weight: 900;">{down_pct:.1f}%</div>
                           
                        </div>
                    """, unsafe_allow_html=True)
    
               
    
                # [3] 투표 버튼 및 관심종목 로직
                if st.session_state.get('auth_status') == 'user':
                    if sid not in st.session_state.watchlist:
                        st.caption("투표시 관심종목에 자동 저장되며, 실시간 결과에 반영됩니다.")
                        c_up, c_down = st.columns(2)
                        
                        if c_up.button("📈 상승", key=f"up_vote_{sid}", use_container_width=True, type="primary"):
                            db_toggle_watchlist(user_id, sid, "UP", action='add')
                            if sid not in st.session_state.watchlist: st.session_state.watchlist.append(sid)
                            st.session_state.watchlist_predictions[sid] = "UP"
                            st.rerun()
    
                        if c_down.button("📉 하락", key=f"dn_vote_{sid}", use_container_width=True):
                            db_toggle_watchlist(user_id, sid, "DOWN", action='add')
                            if sid not in st.session_state.watchlist: st.session_state.watchlist.append(sid)
                            st.session_state.watchlist_predictions[sid] = "DOWN"
                            st.rerun()
                    else:
                        # 이미 참여한 경우 상태 표시
                        pred = st.session_state.watchlist_predictions.get(sid, "N/A")
                        color = "#28a745" if pred == "UP" else "#dc3545"
                        pred_text = "BULLISH (상승)" if pred == "UP" else "BEARISH (하락)"
                        
                        st.markdown(f"""
                            <div style="padding: 15px; border-radius: 10px; border: 1px solid {color}; text-align: center; font-weight: bold; color: {color};">
                                나의 선택: {pred_text} 
                            </div>
                        """, unsafe_allow_html=True)
                        
                        if st.button("투표 취소 및 관심종목 해제", key=f"rm_vote_{sid}", use_container_width=True):
                            db_toggle_watchlist(user_id, sid, action='remove')
                            if sid in st.session_state.watchlist: st.session_state.watchlist.remove(sid)
                            if sid in st.session_state.watchlist_predictions: del st.session_state.watchlist_predictions[sid]
                            st.rerun()
                else:
                    st.warning("🔒 로그인 후 투표에 참여하고 전체 결과를 확인할 수 있습니다.")
    
                # ---------------------------------------------------------
                # 4. 종목 토론방 (글쓰기 상단 + HOT/최신 정렬 + 페이징 적용)
                # ---------------------------------------------------------
                st.write("<br>", unsafe_allow_html=True)
                # 폰트 크기 및 굵기 적용
                st.markdown(f"<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 10px;'>{sid} 토론방</div>", unsafe_allow_html=True)
                
                # [1] 글쓰기 섹션을 리스트 최상단으로 배치
                with st.expander("글쓰기"):
                    if st.session_state.get('auth_status') == 'user':
                        if check_permission('write'):
                            with st.form(key=f"write_{sid}_form", clear_on_submit=True):
                                new_title = st.text_input("제목")
                                new_content = st.text_area("내용")
                                if st.form_submit_button("등록", type="primary", use_container_width=True):
                                    if new_title and new_content:
                                        u_id = st.session_state.user_info.get('id')
                                        try:
                                            fresh_user = db_load_user(u_id)
                                            d_name = fresh_user.get('display_name') or f"{u_id[:3]}***"
                                            st.session_state.user_info = fresh_user
                                        except:
                                            d_name = f"{u_id[:3]}***"
                                        
                                        if db_save_post(sid, new_title, new_content, d_name, u_id):
                                            st.success("등록되었습니다!")
                                            import time; time.sleep(0.5)
                                            st.rerun()
                    else:
                        st.warning("🔒 로그인 후 이용 가능합니다.")
                
                st.write("<br>", unsafe_allow_html=True)
                
                # [2] DB에서 해당 종목(sid) 관련 글 넉넉히 로드
                sid_posts = db_load_posts(limit=100, category=sid)
                
                if sid_posts:
                    from datetime import datetime, timedelta
                    three_days_ago = datetime.now() - timedelta(days=3)
                    
                    hot_candidates = []
                    normal_posts = []
    
                    # 날짜 및 추천수 기반 분류
                    for p in sid_posts:
                        try:
                            created_dt_str = str(p.get('created_at', '')).split('.')[0]
                            created_dt = datetime.strptime(created_dt_str.replace('T', ' '), '%Y-%m-%d %H:%M:%S')
                            if created_dt >= three_days_ago and p.get('likes', 0) > 0:
                                hot_candidates.append(p)
                            else:
                                normal_posts.append(p)
                        except:
                            normal_posts.append(p)
                            
                    # HOT 정렬 및 5개 추출
                    hot_candidates.sort(key=lambda x: (x.get('likes', 0), x.get('created_at', '')), reverse=True)
                    top_5_hot = hot_candidates[:5]
                    
                    # 나머지 병합 및 최신순 정렬
                    normal_posts.extend(hot_candidates[5:])
                    normal_posts.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    
                    # 종목 토론방 전용 페이징 상태 관리
                    page_key = f'detail_display_count_{sid}'
                    if page_key not in st.session_state:
                        st.session_state[page_key] = 5
                    current_display = normal_posts[:st.session_state[page_key]]
    
                    # 종목 토론방용 UI 출력 함수
                    def render_detail_post(p, is_hot=False):
                        p_auth = p.get('author_name', 'Unknown')
                        p_date = str(p.get('created_at', '')).split('T')[0]
                        p_id = p.get('id')
                        p_uid = p.get('author_id')
                        likes = p.get('likes') or 0
                        dislikes = p.get('dislikes') or 0
                        
                        prefix = "[HOT]" if is_hot else ""
                        # 괄호 안 텍스트도 영어로
                        title_disp = f"{prefix} {p.get('title')} | {p_auth} | {p_date} (추천{likes}  비추천{dislikes})"
                        
                        with st.expander(title_disp.strip()):
                            st.markdown(f"<div style='font-size:0.95rem; color:#333;'>{p.get('content')}</div>", unsafe_allow_html=True)
                            st.write("<br>", unsafe_allow_html=True)
                            
                            action_c1, action_c2, action_c3, _ = st.columns([1.5, 1.5, 1.5, 5.5])
                            
                            with action_c1:
                                if st.button(f"추천{likes}", key=f"like_sid_{p_id}", use_container_width=True):
                                    if st.session_state.get('auth_status') == 'user':
                                        db_toggle_post_reaction(p_id, user_id, 'like')
                                        st.rerun()
                                    else: st.toast("🔒 로그인 후 이용 가능합니다.")
                                        
                            with action_c2:
                                if st.button(f"비추천{dislikes}", key=f"dislike_sid_{p_id}", use_container_width=True):
                                    if st.session_state.get('auth_status') == 'user':
                                        db_toggle_post_reaction(p_id, user_id, 'dislike')
                                        st.rerun()
                                    else: st.toast("🔒 로그인 후 이용가능합니다.")
                                        
                            with action_c3:
                                raw_u_info = st.session_state.get('user_info')
                                u_info = raw_u_info if isinstance(raw_u_info, dict) else {}
                                is_admin = u_info.get('role') == 'admin'
                                
                                if st.session_state.get('auth_status') == 'user':
                                    if u_info.get('id') == p_uid or is_admin:
                                        if st.button("삭제", key=f"del_sid_{p_id}", type="secondary", use_container_width=True):
                                            if db_delete_post(p_id):
                                                st.success("삭제되었습니다.")
                                                import time; time.sleep(0.5)
                                                st.rerun()
    
                    # (A) 상단: HOT 게시물 출력
                    if top_5_hot:
                        st.markdown("<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 10px; margin-top: 10px;'>인기글</div>", unsafe_allow_html=True)
                        for p in top_5_hot:
                            render_detail_post(p, is_hot=True)
                        st.write("<br><br>", unsafe_allow_html=True)
    
                    # (B) 하단: 최신 게시물 출력
                    st.markdown("<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 10px;'>최신글</div>", unsafe_allow_html=True)
                    if current_display:
                        for p in current_display:
                            render_detail_post(p, is_hot=False)
                    else:
                        st.info("조건에 맞는 최신 글이 없습니다.")
                        
                    # (C) 더 보기 버튼
                    if len(normal_posts) > st.session_state[page_key]:
                        st.write("<br>", unsafe_allow_html=True)
                        if st.button("🔽 더보기", key=f"more_{sid}", use_container_width=True):
                            st.session_state[page_key] += 10
                            st.rerun()
                else:
                    st.info("첫 의견을 남겨보세요!")
    
    
    # ---------------------------------------------------------
    # [NEW] 6. 게시판 페이지 (Board)
    # ---------------------------------------------------------
    elif st.session_state.page == 'board':
        
        st.markdown("""
            <style>
            div[data-testid="stPills"] div[role="radiogroup"] button {
                border: none !important;
                background-color: #000000 !important;
                color: #ffffff !important;
                border-radius: 20px !important;
                padding: 6px 15px !important;
                margin-right: 5px !important;
            }
            div[data-testid="stPills"] button[aria-selected="true"] {
                background-color: #444444 !important;
                font-weight: 800 !important;
            }
            </style>
        """, unsafe_allow_html=True)
    
        # [1] 메뉴 구성 및 네비게이션
        is_logged_in = (st.session_state.auth_status == 'user')
        login_text, settings_text, main_text, watch_text, board_text, back_text = "로그아웃" if is_logged_in else "로그인", "권한설정", "메인", f"관심 ({len(st.session_state.watchlist)})", "게시판", "뒤로가기"
        
        menu_options = [login_text]
        if is_logged_in: menu_options.append(settings_text)
        menu_options.extend([main_text, watch_text, board_text])
        
        last_stock = st.session_state.get('selected_stock')
        if last_stock: menu_options.append(back_text)
    
        selected_menu = st.pills(label="nav_board", options=menu_options, selection_mode="single", default=board_text, key="nav_board_v3", label_visibility="collapsed")
    
        if selected_menu and selected_menu != board_text:
            if selected_menu == back_text: st.session_state.page = 'detail'; st.rerun()
            elif selected_menu == login_text: 
                if is_logged_in: st.session_state.auth_status = None
                st.session_state.page = 'login'; st.rerun()
            elif selected_menu == settings_text: st.session_state.page = 'setup'; st.rerun()
            elif selected_menu == main_text: st.session_state.page = 'calendar'; st.session_state.view_mode = 'all'; st.rerun()
            elif selected_menu == watch_text: st.session_state.page = 'calendar'; st.session_state.view_mode = 'watchlist'; st.rerun()
    
        # [2] 게시판 데이터 로드 및 검색 필터링 적용
        s_keyword = ""
        s_type = "제목"
        
        # 세션에서 검색 상태를 기억하도록 하여 검색 후 페이지 새로고침 시에도 유지되도록 함.
        if 'b_s_type' in st.session_state:
            s_type = st.session_state.b_s_type
        if 'b_s_keyword' in st.session_state:
            s_keyword = st.session_state.b_s_keyword
            
        all_posts = db_load_posts(limit=100) 
        
        posts = all_posts
        if s_keyword:
            k = s_keyword.lower()
            if s_type == "제목": posts = [p for p in posts if k in p.get('title','').lower()]
            elif s_type == "제목+내용": posts = [p for p in posts if k in p.get('title','').lower() or k in p.get('content','').lower()]
            elif s_type == "카테고리": posts = [p for p in posts if k in p.get('category','').lower()]
            elif s_type == "작성자": posts = [p for p in posts if k in p.get('author_name','').lower()]
    
        # [3] 정렬 및 분리 로직 (HOT 5개 / 나머지 최신순 페이징)
        hot_candidates = []
        normal_posts = []
    
        if posts:
            from datetime import datetime, timedelta
            three_days_ago = datetime.now() - timedelta(days=3)
    
            for p in posts:
                try:
                    created_dt_str = str(p.get('created_at', '')).split('.')[0]
                    created_dt = datetime.strptime(created_dt_str.replace('T', ' '), '%Y-%m-%d %H:%M:%S')
                    if created_dt >= three_days_ago and p.get('likes', 0) > 0:
                        hot_candidates.append(p)
                    else:
                        normal_posts.append(p)
                except:
                    normal_posts.append(p)
                    
            # HOT 정렬 및 최대 5개 추출
            hot_candidates.sort(key=lambda x: (x.get('likes', 0), x.get('created_at', '')), reverse=True)
            top_5_hot = hot_candidates[:5]
            
            # 나머지 병합 및 최신순 정렬
            normal_posts.extend(hot_candidates[5:])
            normal_posts.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    
        # 게시판에 들어올 때 무조건 5개로 시작하도록 강제 설정
        if 'board_display_count' not in st.session_state:
            st.session_state.board_display_count = 5
        
        current_display = normal_posts[:st.session_state.board_display_count]
    
        # UI 출력 함수
        def render_post(p, is_hot=False):
            p_auth = p.get('author_name', 'Unknown')
            p_date = str(p.get('created_at', '')).split('T')[0]
            p_id = p.get('id')
            p_uid = p.get('author_id')
            p_cat = p.get('category', '자유')
            likes = p.get('likes') or 0
            dislikes = p.get('dislikes') or 0
            
            prefix = "[HOT]" if is_hot else f"[{p_cat}]"
            title_disp = f"{prefix} {p.get('title')} | {p_auth} | {p_date} (추천{likes}  비추천{dislikes})"
            
            with st.expander(title_disp.strip()):
                st.markdown(f"<div style='font-size:0.95rem; color:#333;'>{p.get('content')}</div>", unsafe_allow_html=True)
                st.write("<br>", unsafe_allow_html=True)
                
                action_c1, action_c2, action_c3, _ = st.columns([1.5, 1.5, 1.5, 5.5])
                with action_c1:
                    if st.button(f"추천{likes}", key=f"l_{p_id}", use_container_width=True):
                        if is_logged_in:
                            db_toggle_post_reaction(p_id, st.session_state.user_info.get('id', ''), 'like')
                            st.rerun()
                        else: st.toast("🔒 로그인이 필요합니다.")
                with action_c2:
                    if st.button(f"비추천{dislikes}", key=f"d_{p_id}", use_container_width=True):
                        if is_logged_in:
                            db_toggle_post_reaction(p_id, st.session_state.user_info.get('id', ''), 'dislike')
                            st.rerun()
                        else: st.toast("🔒 로그인이 필요합니다.")
                with action_c3:
                    raw_u_info = st.session_state.get('user_info')
                    u_info = raw_u_info if isinstance(raw_u_info, dict) else {}
                    is_admin = u_info.get('role') == 'admin'
                    
                    if is_logged_in and (u_info.get('id') == p_uid or is_admin):
                        if st.button("삭제", key=f"del_{p_id}", type="secondary", use_container_width=True):
                            if db_delete_post(p_id):
                                st.success("삭제됨")
                                import time; time.sleep(0.5)
                                st.rerun()
    
        # [4] 리스트 및 컨트롤 UI 렌더링
        post_list_area = st.container()
        
        with post_list_area:
            
            # 1. 검색 및 글쓰기 영역 (최상단으로 이동)
            f_col1, f_col2 = st.columns(2)
            with f_col1:
                with st.expander("검색하기"):
                    s_type_new = st.selectbox("범위", ["제목", "제목+내용", "카테고리", "작성자"], key="b_s_type_temp", index=["제목", "제목+내용", "카테고리", "작성자"].index(s_type))
                    s_keyword_new = st.text_input("키워드", value=s_keyword, key="b_s_keyword_temp")
                    if st.button("검색", key="search_btn", use_container_width=True):
                        st.session_state.b_s_type = s_type_new
                        st.session_state.b_s_keyword = s_keyword_new
                        st.rerun()
            
            with f_col2:
                with st.expander("글쓰기"):
                    if is_logged_in and check_permission('write'):
                        with st.form(key="board_main_form", clear_on_submit=True):
                            b_cat = st.text_input("종목/말머리", placeholder="자유")
                            b_tit = st.text_input("제목")
                            b_cont = st.text_area("내용")
                            if st.form_submit_button("등록", type="primary", use_container_width=True):
                                if b_tit and b_cont:
                                    u_id = st.session_state.user_info['id']
                                    try:
                                        fresh_user = db_load_user(u_id)
                                        d_name = fresh_user.get('display_name') or f"{u_id[:3]}***"
                                    except: d_name = f"{u_id[:3]}***"
                                    
                                    if db_save_post(b_cat, b_tit, b_cont, d_name, u_id):
                                        st.success("등록 완료!")
                                        import time; time.sleep(0.5)
                                        # 글 작성 후 전체 리스트를 다시 불러오도록 검색 조건 초기화
                                        if 'b_s_type' in st.session_state: del st.session_state.b_s_type
                                        if 'b_s_keyword' in st.session_state: del st.session_state.b_s_keyword
                                        st.rerun()
                    else:
                        st.warning("🔒 로그인 및 권한 인증이 필요합니다.")
    
            st.write("<br>", unsafe_allow_html=True)
            
            # 2. 인기글 영역 (검색창 아래)
            if hot_candidates and top_5_hot: # 에러 방지용 조건 강화
                st.markdown("<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 10px; margin-top: 10px;'>인기글</div>", unsafe_allow_html=True)
                for p in top_5_hot:
                    render_post(p, is_hot=True)
                st.write("<br><br>", unsafe_allow_html=True)
            
            # 3. 최신글 영역 (인기글 아래)
            st.markdown("<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 10px;'>최신글</div>", unsafe_allow_html=True)
            
            if posts:
                if current_display:
                    for p in current_display:
                        render_post(p, is_hot=False)
                else:
                    st.info("조건에 맞는 최신 글이 없습니다.")
                    
                # 더보기 버튼 로직 (고유 Key 추가)
                if len(normal_posts) > st.session_state.board_display_count:
                    st.write("<br>", unsafe_allow_html=True)
                    if st.button("🔽 더보기", key="more_board_posts", use_container_width=True):
                        st.session_state.board_display_count += 10
                        st.rerun()
            else:
                st.info("게시글이 없습니다.")

                
                        
        
                #리아 지우와 제주도 다녀오다 사랑하다.
                
                
                
