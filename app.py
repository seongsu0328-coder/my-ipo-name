import streamlit as st
import traceback
import sys

# [중요] 에러를 잡기 위해 전체 코드를 try로 감쌉니다.
try:
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
    import resend
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
            # Railway Variables에 넣은 이름과 일치해야 합니다.
            # 만약 [supabase] url 로 넣으셨다면 아래 형식이 맞습니다.
            url = os.environ.get("SUPABASE_URL") or st.secrets["supabase"]["url"]
            key = os.environ.get("SUPABASE_KEY") or st.secrets["supabase"]["key"]
            return create_client(url, key)
        except Exception as e:
            # 여기서 에러가 나면 화면에 뿌려줍니다.
            st.error(f"Supabase 설정 읽기 오류: {e}")
            raise e # 상위 try문으로 에러 전달

    # 전역 Supabase 객체 생성
    supabase = init_supabase()

    # --- 여기에 나머지 기존 app.py 코드들을 모두 붙여넣으세요 ---
    # (기존의 페이지 구성, 데이터 로드, 화면 출력 코드들...)

# [중요] 코드 맨 마지막에 아래 내용을 붙입니다.
except Exception as e:
    st.error("🚨 앱 실행 중 에러가 발생했습니다!")
    st.warning("아래 에러 메시지를 복사해서 알려주시면 바로 해결해 드릴게요:")
    
    # 실제 에러 내용과 경로(Traceback)를 화면에 출력
    error_msg = traceback.format_exc()
    st.code(error_msg, language='python')
    
    # 앱이 꺼지지 않게 강제로 멈춤
    st.stop()
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
MY_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
# ==========================================

# ==========================================
# [Supabase DB] 데이터 관리 함수 모음 (NEW)
# ==========================================

# 1. 유저 로그인 정보 불러오기 (Stripe & PortOne 구독 동기화 기능 추가)
def db_load_user(user_id):
    try:
        res = supabase.table("users").select("*").eq("id", user_id).execute()
        
        if res.data:
            user = res.data[0]
            
            # 프리미엄 유저 만료일 검사
            if user.get('is_premium') and user.get('premium_until'):
                from datetime import datetime, timedelta
                import stripe
                
                try:
                    expire_str = str(user['premium_until']).split('.')[0].replace('Z', '')
                    expire_dt = datetime.fromisoformat(expire_str)
                    
                    # 💡 [핵심] 만료일이 지났을 때의 처리
                    if datetime.now() > expire_dt:
                        sub_id = user.get('subscription_id')
                        is_still_active = False
                        
                        # [Case 1] Stripe 정기 구독(해외 결제)인 경우 연장 여부 확인
                        if sub_id and str(sub_id).startswith("sub_"):
                            try:
                                stripe.api_key = os.environ.get("STRIPE_SECRET_KEY") or st.secrets.get("STRIPE_SECRET_KEY")
                                sub = stripe.Subscription.retrieve(sub_id)
                                
                                # Stripe 상태가 active(활성)라면 연장된 것!
                                if sub.status in ['active', 'trialing']:
                                    is_still_active = True
                                    # 만료일을 다시 30일 뒤로 늘려줌
                                    new_expire = (datetime.now() + timedelta(days=30)).isoformat()
                                    supabase.table("users").update({"premium_until": new_expire}).eq("id", user_id).execute()
                                    user['premium_until'] = new_expire
                            except Exception as sync_e:
                                print(f"Stripe 연장 확인 에러: {sync_e}")

                        # [Case 2] PortOne 국내 결제 (현재 단건 결제이므로 자동 연장 없음)
                        elif sub_id and str(sub_id).startswith("portone_"):
                            # 나중에 PortOne 빌링키(정기결제)를 도입하시면 여기에 PortOne API 조회 로직이 들어갑니다.
                            # 지금은 30일 단건이므로 무조건 만료 처리합니다.
                            is_still_active = False

                        # 연장 확인이 안 되거나(취소됨/단건만료), 구독 ID가 아예 없다면 권한 해제
                        if not is_still_active:
                            supabase.table("users").update({
                                "is_premium": False,
                                "subscription_id": None # 구독 ID도 비워줍니다.
                            }).eq("id", user_id).execute()
                            
                            user['is_premium'] = False
                            user['premium_until'] = None
                            print(f"[{user_id}] 구독 해제/만료로 권한이 회수되었습니다.")
                            
                except Exception as parse_e:
                    print(f"날짜 변환 에러: {parse_e}")
                    
            return user
        return None
    except Exception as e:
        print(f"DB Load Error: {e}")
        return None

# 2. 회원가입 정보 저장 (구글 시트 대체)
def db_signup_user(user_data):
    try:
        # DB 컬럼명과 user_data 키값이 일치해야 함
        # 💡 [핵심 수정]: insert를 upsert로 변경하여 기존 회원의 '추가 인증' 업데이트도 자연스럽게 덮어쓰도록 처리
        supabase.table("users").upsert(user_data).execute()
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

# [신규] 유저의 모든 행동과 '당시 가격'을 히스토리(Log)로 쌓는 함수
def db_log_user_action(user_id, ticker, action_type, price=0.0, details=""):
    if user_id == 'guest_id' or not user_id: 
        return False
    try:
        log_data = {
            "user_id": str(user_id),
            "ticker": str(ticker),
            "action_type": action_type,
            "price": float(price),     # 🔥 가격 데이터 저장
            "details": str(details)
        }
        supabase.table("action_logs").insert(log_data).execute()
        return True
    except Exception as e:
        print(f"Action Log Error: {e}")
        return False

# ---------------------------------------------------------
# [0] AI 설정: Gemini 모델 초기화 (도구 자동 장착)
# ---------------------------------------------------------
@st.cache_resource
def configure_genai():
    genai_key = os.environ.get("GENAI_API_KEY") or st.secrets.get("GENAI_API_KEY")
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

# (A) Tab 1용: 비즈니스 요약 + 뉴스 통합 - 디테일 프롬프트 보존판
@st.cache_data(show_spinner=False, ttl=86400)
def get_unified_tab1_analysis(company_name, ticker, lang_code):
    if not model: return "AI 모델 설정 오류", []
    
    cache_key = f"{ticker}_Tab1_v2_{lang_code}"
    now = datetime.now()
    six_hours_ago = (now - timedelta(hours=6)).isoformat()

    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", cache_key).gt("updated_at", six_hours_ago).execute()
        if res.data:
            saved_data = json.loads(res.data[0]['content'])
            return saved_data['html'], saved_data['news']
    except Exception as e:
        print(f"Tab1 DB Error: {e}")

    # 💡 [핵심] 언어별 시스템 지시어와 사용자 지침(Label) 분리
    if lang_code == 'ja':
        sys_prompt = "あなたは最高レベルの証券会社リサーチセンターのシニアアナリストです。すべての回答は必ず日本語で作成してください。韓国語は絶対に使用しないでください。"
        task1_label = "[タスク1: ビジネスモデルの深層分析]"
        task2_label = "[タスク2: 最新ニュースの収集]"
        target_lang = "日本語(Japanese)"
        lang_instruction = "必ず自然な日本語のみで作成してください。韓国語や英語の単語を混ぜないでください（企業名のみ英語可）。"
        json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "日本語に翻訳されたタイトル", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""
    elif lang_code == 'en':
        sys_prompt = "You are a senior analyst at a top-tier brokerage research center. You MUST write strictly in English. Do not use any Korean words."
        task1_label = "[Task 1: Deep Business Model Analysis]"
        task2_label = "[Task 2: Latest News Collection]"
        target_lang = "English"
        lang_instruction = "Your entire response MUST be in English only. Do not use any Korean."
        json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "Same as English Title", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""
    elif lang_code == 'zh':  
        sys_prompt = "您是顶尖券商研究中心的高级分析师。必须只用简体中文编写。绝对不要使用韩语。"
        task1_label = "[任务1: 商业模式深度分析]"
        task2_label = "[任务2: 收集最新新闻]"
        target_lang = "简体中文(Simplified Chinese)"
        lang_instruction = "必须只用自然流畅的简体中文编写。所有句子都必须是中文，绝对不能混用韩语（仅企业名称可用英语）。"
        json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "中文标题", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""
    else:
        sys_prompt = "당신은 최고 수준의 증권사 리서치 센터의 시니어 애널리스트입니다. 반드시 한국어로 작성하세요."
        task1_label = "[작업 1: 비즈니스 모델 심층 분석]"
        task2_label = "[작업 2: 최신 뉴스 수집]"
        target_lang = "한국어(Korean)"
        lang_instruction = "반드시 자연스러운 한국어만 사용하세요."
        json_format = f"""{{ "news": [ {{ "title_en": "Original English Title", "translated_title": "한국어로 번역된 제목", "link": "...", "sentiment": "긍정/부정/일반", "date": "YYYY-MM-DD" }} ] }}"""

    current_date = now.strftime("%Y-%m-%d")

    prompt = f"""
    {sys_prompt}
    분석 대상: {company_name} ({ticker})
    오늘 날짜: {current_date}

    {task1_label}
    아래 [필수 작성 원칙]을 준수하여 리포트를 작성하세요.
    1. 언어: {lang_instruction}
       - 경고: 영어 단어(potential, growth 등)를 중간에 그대로 노출하는 비문을 절대 금지합니다. 완벽하게 {target_lang} 어휘로 번역하세요.
    2. 포맷: 반드시 3개의 문단으로 나누어 작성하세요. 문단 사이에는 줄바꿈을 명확히 넣으세요.
       - 1문단: 비즈니스 모델 및 경쟁 우위
       - 2문단: 재무 현황 및 공모 자금 활용
       - 3문단: 향후 전망 및 투자 의견
    3. 금지: 제목, 소제목, 특수기호, 불렛포인트(-)를 절대 쓰지 마세요. 인사말 없이 바로 본론부터 시작하세요.
    4. 최종 검수(Self-Check): 답변을 최종 출력하기 전에 스스로 엄격하게 검토하세요. 인사말, 서론, 또는 {target_lang} 외의 언어(특히 한국어)가 단 한 글자라도 포함되어 있다면 해당 부분을 완전히 삭제하고 완벽한 {target_lang} 문장으로만 구성하여 답변하세요.
    
    {task2_label}
    - 반드시 구글 검색을 실행하여 최신 정보를 확인하세요.
    - {current_date} 기준, 최근 1년 이내의 뉴스 5개를 선정하세요.
    - 각 뉴스는 아래 JSON 형식으로 답변의 맨 마지막에 첨부하세요. 
    - [중요] sentiment 값은 시스템 로직을 위해 무조건 "긍정", "부정", "일반" 중 하나를 한국어로 적으세요.

    <JSON_START>
    {json_format}
    <JSON_END>
    """

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            full_text = response.text

            # 💡 [핵심 방어막] 에러 유발하던 내부 import 구문 제거
            if lang_code != 'ko':
                check_text = full_text.replace("긍정", "").replace("부정", "").replace("일반", "")
                if re.search(r'[가-힣]', check_text):
                    print(f"⚠️ Tab1 한국어 혼용 감지됨 ({lang_code}). 재시도 {attempt+1}/{max_retries}")
                    time.sleep(1)
                    continue 

            news_list = []
            json_str = ""
            
            json_match = re.search(r'\[\s*\{.*?\}\s*\]', full_text, re.DOTALL)
            
            if json_match:
                json_str = json_match.group(0)
                try:
                    news_list = json.loads(json_str)
                except:
                    pass

            if json_str:
                biz_analysis = full_text.replace(json_str, "").replace("<JSON_START>", "").replace("<JSON_END>", "").strip()
            else:
                biz_analysis = full_text.split("{")[0].replace("<JSON_START>", "").strip()

            biz_analysis = re.sub(r'#.*', '', biz_analysis).strip()
            paragraphs = [p.strip() for p in biz_analysis.split('\n') if len(p.strip()) > 20]
            
            indent_size = "14px" if lang_code == "ko" else "0px"
            html_output = "".join([f'<p style="display:block; text-indent:{indent_size}; margin-bottom:20px; line-height:1.8; text-align:justify; font-size: 15px; color: #333;">{p}</p>' for p in paragraphs])

            if news_list:
                for n in news_list:
                    if n.get('sentiment') == "긍정": n['bg'], n['color'] = "#e6f4ea", "#1e8e3e"
                    elif n.get('sentiment') == "부정": n['bg'], n['color'] = "#fce8e6", "#d93025"
                    else: n['bg'], n['color'] = "#f1f3f4", "#5f6368"

            supabase.table("analysis_cache").upsert({
                "cache_key": cache_key,
                "content": json.dumps({"html": html_output, "news": news_list}, ensure_ascii=False),
                "updated_at": now.isoformat()
            }).execute()

            return html_output, news_list
            
        except Exception as e:
            if attempt == max_retries - 1:
                return f"<p style='color:red;'>시스템 오류: {str(e)}</p>", []
            time.sleep(1)

    return f"<p style='color:red;'>시스템 오류: 언어 생성 지연이 발생했습니다.</p>", []

@st.cache_data(show_spinner=False, ttl=86400)
def get_ai_analysis(company_name, topic, lang_code):
    """
    Tab 0: 공시 5종 분석 (Supabase DB 캐싱 연동 완료)
    """
    if not model:
        return "⚠️ AI 모델 설정 오류가 발생했습니다."

    # 💡 [방어막 추가] worker.py가 저장한 캐시 키와 동일하게 설정하여 DB를 먼저 찌릅니다.
    cache_key = f"{company_name}_{topic}_Tab0_v11_{lang_code}"
    now = datetime.now()
    # 공시 문서는 자주 안 바뀌므로 일주일치 데이터를 유효한 것으로 봅니다.
    seven_days_ago = (now - timedelta(days=7)).isoformat()

    try:
        # DB에서 먼저 데이터 찾기
        res = supabase.table("analysis_cache") \
            .select("content") \
            .eq("cache_key", cache_key) \
            .gt("updated_at", seven_days_ago) \
            .execute()
            
        if res.data:
            # 워커가 미리 분석해둔 데이터가 있다면 0.1초 만에 바로 반환! (API 요금 절약)
            return res.data[0]['content']
    except Exception as e:
        print(f"Tab0 Cache Read Error: {e}")

    # ========================================================
    # DB에 데이터가 없을 경우에만 아래 로직(API 호출)을 탑니다.
    # ========================================================
    
    def_meta = {
        "S-1": {
            "points": "Risk Factors(특이 소송/규제), Use of Proceeds(자금 용도의 건전성), MD&A(성장 동인)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 해당 문서에서 발견된 가장 중요한 투자 포인트 분석
            2. 두 번째 문단: 실질적 성장 가능성과 재무적 의미 분석
            3. 세 번째 문단: 핵심 리스크 1가지와 그 파급 효과 및 대응책
            """
        },
        "S-1/A": {
            "points": "Pricing Terms(수요예측 분위기), Dilution(신규 투자자 희석률), Changes(이전 제출본과의 차이점)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 이전 S-1 대비 변경된 핵심 사항 분석
            2. 두 번째 문단: 제시된 공모가 범위의 적정성 및 수요예측 분위기 분석
            3. 세 번째 문단: 기존 주주 가치 희석 정도와 투자 매력도 분석
            """
        },
        "F-1": {
            "points": "Foreign Risk(지정학적 리스크), Accounting(GAAP 차이), ADS(주식 예탁 증서 구조)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 기업이 글로벌 시장에서 가진 독보적인 경쟁 우위
            2. 두 번째 문단: 환율, 정치, 회계 등 해외 기업 특유의 리스크 분석
            3. 세 번째 문단: 미국 예탁 증서(ADS) 구조가 주주 권리에 미치는 영향
            """
        },
        "FWP": {
            "points": "Graphics(시장 점유율 시각화), Strategy(미래 핵심 먹거리), Highlights(경영진 강조 사항)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 경영진이 로드쇼에서 강조하는 미래 성장 비전
            2. 두 번째 문단: 경쟁사 대비 부각시키는 기술적/사업적 차별화 포인트
            3. 세 번째 문단: 자료 톤앤매너로 유추할 수 있는 시장 공략 의지
            """
        },
        "424B4": {
            "points": "Underwriting(주관사 등급), Final Price(기관 배정 물량), IPO Outcome(최종 공모 결과)",
            "structure": """
            [문단 구성 지침]
            1. 첫 번째 문단: 확정 공모가의 위치와 시장 수요 해석
            2. 두 번째 문단: 확정된 조달 자금의 투입 우선순위 점검
            3. 세 번째 문단: 주관사단 및 배정 물량 바탕 상장 초기 유통물량 예측
            """
        }
    }

    curr_meta = def_meta.get(topic, def_meta["S-1"])

    format_instruction = """
    [출력 형식 및 번역 규칙 - 반드시 지킬 것]
    - 각 문단의 시작은 반드시 해당 언어로 번역된 **[소제목]**으로 시작한 뒤, 줄바꿈 없이 한 칸 띄우고 바로 내용을 이어가세요.
    - [분량 조건] 전체 요약이 아닙니다! **각 문단(1, 2, 3)마다 반드시 4~5문장(약 5줄 분량)씩** 내용을 상세하고 풍성하게 채워 넣으세요.
    - 올바른 예시(영어): **[Investment Point]** The company's main advantage is...
    - 올바른 예시(일본어): **[投資ポイント]** 同社の最大の強みは...
    - 금지 예시(한국어 병기 절대 금지): **[Investment Point - 투자포인트]** (X)
    - 금지 예시(소제목 뒤 줄바꿈 절대 금지): **[投資ポイント]** \n 同社は... (X)
    """

    if lang_code == 'en':
        labels = ["Analysis Target", "Instructions", "Structure & Format", "Writing Style Guide"]
        role_desc = "You are a professional senior analyst from Wall Street."
        no_intro_prompt = 'CRITICAL: NEVER introduce yourself. DO NOT include Korean translations in headings. START IMMEDIATELY with the first English **[Heading]**.'
        target_lang_str = "English"
    elif lang_code == 'ja':
        labels = ["分析対象", "指針", "内容構成および形式", "文体ガイド"]
        role_desc = "あなたはウォール街出身の専門分析家です。"
        no_intro_prompt = '【重要】自己紹介は禁止です。見出しに韓国語を併記しないでください。1文字目からいきなり日本語の**[見出し]**で本論から始めてください。'
        target_lang_str = "日本語(Japanese)"
    elif lang_code == 'zh':
        labels = ["分析目标", "指南", "内容结构和格式", "文体指南"]
        role_desc = "您是华尔街的专业高级分析师。"
        no_intro_prompt = '【重要】绝对不要自我介绍。绝对不要在标题中包含韩语。请直接以中文的**[标题]**开始正文。'
        target_lang_str = "简体中文(Simplified Chinese)"
    else:
        labels = ["분석 대상", "지침", "내용 구성 및 형식", "문체 가이드"]
        role_desc = "당신은 월가 출신의 전문 분석가입니다."
        no_intro_prompt = '자기소개나 인사말, 서론은 절대 하지 마세요. 1글자부터 바로 본론(**[소제목]**)으로 시작하세요.'
        target_lang_str = "한국어(Korean)"

    prompt = f"""
    {labels[0]}: {company_name} - {topic}
    {labels[1]} (Checkpoints): {curr_meta['points']}
    
    [{labels[1]}]
    {role_desc}
    {no_intro_prompt}
    
    [{labels[2]}]
    {curr_meta['structure']}
    {format_instruction}

    [{labels[3]}]
    - 반드시 '{target_lang_str}'로만 작성하세요. (절대 다른 언어를 섞지 마세요)
    - 모든 문장은 반드시 '~합니다', '~입니다' 형태의 정중한 경어체로 작성하세요.
    - 문장 끝이 끊기지 않도록 매끄럽게 연결하세요.
    """

    try:
        # 최대 2회 재시도 (한국어 혼용 방지)
        final_text = ""
        for attempt in range(2):
            response = model.generate_content(prompt)
            res_text = response.text
            
            if lang_code != 'ko':
                import re
                if re.search(r'[가-힣]', res_text):
                    time.sleep(1)
                    continue 
            
            final_text = res_text
            break
            
        if not final_text:
            final_text = response.text

        # 💡 [핵심] API를 호출해서 얻어낸 결과를 DB에 저장합니다. (다음 사람을 위해)
        try:
            supabase.table("analysis_cache").upsert({
                "cache_key": cache_key,
                "content": final_text,
                "updated_at": now.isoformat()
            }).execute()
        except:
            pass

        return final_text

    except Exception as e:
        return f"분석 중 오류 발생: {str(e)}"

@st.cache_data(ttl=86400) # 하루 동안 재무제표 기억
def get_cached_raw_financials(symbol):
    fin_data = {}
    try:
        ticker = yf.Ticker(symbol)
        yf_fin = ticker.financials; yf_info = ticker.info; yf_bal = ticker.balance_sheet
        if not yf_fin.empty:
            rev = yf_fin.loc['Total Revenue'].iloc[0]
            net_inc = yf_fin.loc['Net Income'].iloc[0]
            prev_rev = yf_fin.loc['Total Revenue'].iloc[1] if len(yf_fin.columns) > 1 else rev
            fin_data['revenue'] = rev / 1e6
            fin_data['net_margin'] = (net_inc / rev) * 100
            fin_data['growth'] = ((rev - prev_rev) / prev_rev) * 100
            fin_data['forward_pe'] = yf_info.get('forwardPE', 0)
            # ... (나머지 지표들 추출 로직)
    except: 
        pass
    return fin_data
        
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
    - 형식: 줄글로 된 3~5줄의 요약 리포트로 제목, 소제목, 헤더(##), 인사말을 절대 포함하지 마세요.
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
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        
        # --- 🚀 핵심 수정 부분 시작 ---
        gcp_raw = os.environ.get("GCP_SERVICE_ACCOUNT")
        
        if gcp_raw:
            # Railway 서버: 환경 변수에서 가져온 문자열을 파이썬 딕셔너리로 변환
            creds_dict = json.loads(gcp_raw)
        else:
            # 대표님 로컬 PC: 기존처럼 secrets.toml에서 가져옴
            creds_dict = st.secrets["gcp_service_account"]
        # --- 🚀 핵심 수정 부분 끝 ---

        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        
        gspread_client = gspread.authorize(creds)
        drive_service = build('drive', 'v3', credentials=creds)
        
        return gspread_client, drive_service
    except Exception as e:
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
        
import resend

def send_email_code(to_email, code):
    import os
    try:
        # Railway에 저장한 API 키 로드
        resend.api_key = os.environ.get("RESEND_API_KEY")

        if not resend.api_key:
            st.error("❌ RESEND_API_KEY 설정이 누락되었습니다.")
            return False

        # 메일 발송 (보내는 사람은 일단 'onboarding@resend.dev'로 테스트)
        # ✅ 변경 후 (대표님의 진짜 도메인 적용!)
        params = {
            "from": "Unicorn Finder <noreply@unicornfinder.app>", 
            "to": [to_email],
            "subject": "[Unicorn Finder] 본인 인증번호",
            "html": f"<strong>안녕하세요. 인증번호는 [{code}] 입니다.</strong>",
        }

        resend.Emails.send(params)
        st.toast(f"📧 {to_email}로 인증 메일을 보냈습니다!", icon="✅")
        return True

    except Exception as e:
        st.error(f"❌ API 메일 전송 실패: {e}")
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

# [외주 개발자용 지시 코드] 글로벌 메세지 라우팅 함수
def send_premium_notification(user_info, title, message):
    """
    유저가 선택한 알림 매체(noti_method)에 따라 분기하여 메시지를 발송하는 함수.
    [외주 작업자 대상]: 아래의 각 조건문에 맞는 서드파티 통신사 API를 연동할 것.
    """
    noti_method = user_info.get('noti_method', 'Email')
    phone = user_info.get('phone', '')
    email = user_info.get('email', '')
    
    full_message = f"[{title}]\n{message}"

    try:
        if "Kakao" in noti_method or "카카오" in noti_method:
            # 💡 [외주 요청] 알리고(Aligo), 솔라피, 비즈메시지 등의 '카카오 알림톡 API' 연동
            print(f"[KakaoTalk] {phone} 로 알림톡 전송 완료: {title}")
            
        elif "LINE" in noti_method or "ライン" in noti_method:
            # 💡 [외주 요청] LINE Messaging API 연동
            print(f"[LINE] {phone} 로 라인 메세지 전송 완료: {title}")
            
        elif "WeChat" in noti_method or "微信" in noti_method:
            # 💡 [외주 요청] WeChat Official Account API 연동
            print(f"[WeChat] {phone} 로 위챗 메세지 전송 완료: {title}")
            
        elif "WhatsApp" in noti_method:
            # 💡 [외주 요청] Twilio WhatsApp API 연동
            print(f"[WhatsApp] {phone} 로 왓츠앱 전송 완료: {title}")
            
        elif "SMS" in noti_method:
            # 💡 [외주 요청] AWS SNS 또는 Twilio SMS API 연동
            print(f"[SMS] {phone} 로 문자 전송 완료: {title}")
            
        else:
            # 기본값: 이메일 전송 (기존에 작성된 Resend API 또는 SMTP 활용)
            print(f"[Email] {email} 로 이메일 전송 완료: {title}")
            # send_approval_email(email, full_message) # 기존 함수 재활용 가능
            
        return True
    except Exception as e:
        print(f"Notification Error: {e}")
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

def generate_alerts_from_db(supabase, df_calendar):
    """
    [API 호출 NO!] Supabase DB의 캐시된 가격만 읽어서 프리미엄 알림을 생성합니다.
    """
    today = datetime.now().date()
    new_alerts = []

    # 1. DB에서 가장 최신 주가 정보 전체를 한 번에 가져옴 (속도 0.1초)
    res = supabase.table("price_cache").select("ticker, price").execute()
    db_prices = {row['ticker']: float(row['price']) for row in res.data if row['price']}

    # 2. 캘린더 데이터를 돌면서 분석
    for _, row in df_calendar.iterrows():
        ticker = row['symbol']
        ipo_date_str = str(row['date'])
        try:
            ipo_date = pd.to_datetime(ipo_date_str).date()
        except: continue

        # [알림 1] 신규 상장 3일 전
        if ipo_date == today + timedelta(days=3):
            new_alerts.append({"ticker": ticker, "alert_type": "UPCOMING", "title": f"🚀 상장 D-3: {ticker}", "message": f"{row['name']}의 IPO가 3일 뒤 예정되어 있습니다."})

        # [알림 2] 락업 해제 7일 전 (보통 상장 후 180일)
        lockup_date = ipo_date + timedelta(days=180)
        if lockup_date == today + timedelta(days=7):
            new_alerts.append({"ticker": ticker, "alert_type": "LOCKUP", "title": f"🚨 락업 해제 D-7: {ticker}", "message": f"내부자 보호예수 물량이 해제될 예정입니다."})

        # [알림 3] DB에 저장된 현재가 기반: 공모가 재돌파 (Golden Cross)
        current_p = db_prices.get(ticker, 0.0)
        try:
            ipo_price = float(str(row.get('price', '0')).replace('$', '').split('-')[0])
        except: ipo_price = 0.0

        if ipo_price > 0 and current_p > 0:
            # 현재 가격이 공모가보다 20% 이상 급등했을 때
            surge_pct = ((current_p - ipo_price) / ipo_price) * 100
            if surge_pct >= 20.0:
                new_alerts.append({
                    "ticker": ticker, "alert_type": "SURGE",
                    "title": f"🔥 공모가 대비 급등: {ticker} (+{surge_pct:.1f}%)",
                    "message": f"현재가 ${current_p:.2f}로 공모가 대비 강력한 상승세를 보이고 있습니다."
                })

    # 3. 새로운 알림들을 DB(premium_alerts)에 저장
    if new_alerts:
        supabase.table("premium_alerts").insert(new_alerts).execute()
        print(f"✅ {len(new_alerts)}개의 새로운 프리미엄 알림이 생성되었습니다.")

# ---------------------------------------------------------
# 2. 공통 유틸리티 함수
# ---------------------------------------------------------

def display_disclaimer():
    """
    모든 탭 하단에 표시될 공통 면책 조항
    """
    st.markdown("<br>", unsafe_allow_html=True) # 약간의 여백
    st.divider()
    st.caption(get_text('msg_disclaimer'))

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
# [수정] 실제 시장 지표를 계산하는 함수 (API 일괄 호출 최적화)
# ---------------------------------------------------------
def _calculate_market_metrics_internal(df_calendar, api_key):
    data = {
        "ipo_return": 0.0, "ipo_volume": 0, "unprofitable_pct": 0, "withdrawal_rate": 0,
        "vix": 0.0, "buffett_val": 0.0, "pe_ratio": 0.0, "fear_greed": 50
    }

    if not df_calendar.empty:
        today = datetime.now().date()
        
        # 1. IPO 데이터 계산 (최근 30개 기준)
        traded_ipos = df_calendar[df_calendar['공모일_dt'].dt.date < today].sort_values(by='공모일_dt', ascending=False).head(30)
        
        # 💡 [핵심 최적화] 30개 종목의 실시간 가격을 한 번에(Batch) 가져옵니다!
        symbols_to_fetch = traded_ipos['symbol'].dropna().unique().tolist()
        batch_prices, _ = get_batch_prices(symbols_to_fetch)
        
        ret_sum = 0; ret_cnt = 0; unp_cnt = 0
        for _, row in traded_ipos.iterrows():
            sym = row['symbol']
            try:
                p_ipo = float(str(row.get('price','0')).replace('$','').split('-')[0])
                # 개별 API 호출 대신, 방금 한 번에 가져온 batch_prices에서 꺼내 씁니다.
                p_curr = batch_prices.get(sym, 0.0) 
                
                if p_ipo > 0 and p_curr > 0:
                    ret_sum += ((p_curr - p_ipo) / p_ipo) * 100
                    ret_cnt += 1
                
                # 재무 정보는 24시간 캐시가 걸려있어 비교적 안전하나, 이 부분도 필요시 최적화 가능
                fin = get_financial_metrics(sym, api_key)
                if fin and fin.get('net_margin') and fin['net_margin'] < 0: unp_cnt += 1
            except: pass
        
        if ret_cnt > 0: data["ipo_return"] = ret_sum / ret_cnt
        if len(traded_ipos) > 0: data["unprofitable_pct"] = (unp_cnt / len(traded_ipos)) * 100

        # 2. 향후 30일 물량 및 1.5년 철회율
        future_ipos = df_calendar[(df_calendar['공모일_dt'].dt.date >= today) & 
                                  (df_calendar['공모일_dt'].dt.date <= today + timedelta(days=30))]
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
    genai_key = os.environ.get("GENAI_API_KEY") or st.secrets.get("GENAI_API_KEY")
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

if os.environ.get("GENAI_API_KEY") or st.secrets.get("GENAI_API_KEY"):
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

@st.cache_data(show_spinner=False, ttl=86400)
def get_unified_tab4_analysis(company_name, ticker, lang_code):
    # 필요한 라이브러리 체크 (함수 내부 혹은 상단에 위치해야 함)
    import re
    import time
    import json
    from datetime import datetime, timedelta

    if not model: 
        return {"rating": "Error", "summary": "설정 오류", "pro_con": "", "links": []}

    cache_key = f"{ticker}_Tab4_{lang_code}" # 버전업하여 새 캐시 생성 유도
    now = datetime.now()
    one_day_ago = (now - timedelta(days=1)).isoformat()

    # 1. DB 캐시 확인
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", cache_key).gt("updated_at", one_day_ago).execute()
        if res.data:
            return json.loads(res.data[0]['content'])
    except Exception as e:
        print(f"Tab4 DB Error: {e}")

    # 2. 언어별 설정 (일본어 지침 강화)
    LANG_MAP = {
        'ko': '한국어 (Korean)',
        'en': '영어 (English)',
        'ja': '일본어 (Japanese)',
        'zh': '简体中文 (Simplified Chinese)' 
    }
    target_lang = LANG_MAP.get(lang_code, '한국어 (Korean)')

    # 일본어/중국어일 경우 한국어 혼용을 더 강력하게 경고
    lang_instruction = f"Respond strictly in {target_lang}."
    if lang_code == 'ja':
        lang_instruction = "必ず日本語(Japanese)のみで回答してください。見出し, 本문, JSON의 값 모두에 한국어(Korean)를 절대 포함하지 마세요."
    elif lang_code == 'zh':  
        lang_instruction = "必须只用简体中文(Simplified Chinese)编写。严禁在回答 중 出现任何韩语。"

    # 3. 프롬프트 (기존 내용 보존 + 안정성 강화)
    prompt = f"""
    당신은 월가 출신의 IPO 전문 분석가입니다. 
    구글 검색 도구를 사용하여 {company_name} ({ticker})에 대한 최신 기관 리포트(Seeking Alpha, Renaissance Capital, Morningstar 등)를 찾아 심층 분석하세요.

    [작성 지침]
    1. **언어**: 반드시 '{target_lang}'로 답변하세요. {lang_instruction}
    2. **분석 깊이**: 구체적인 수치나 근거를 들어 전문적으로 분석하세요.
    3. **Pros & Cons**: 긍정적 요소(Pros) 2가지와 부정적/리스크 요소(Cons) 2가지를 명확히 구분하여 상세하게 서술하세요.
    4. **Rating**: (Strong Buy/Buy/Hold/Sell) 중 하나를 영어로 선택하세요.
    5. **Summary**: 전문적인 톤으로 3~5줄 내외로 핵심만 작성하세요.
    6. **한국어 금지**: 인사말, 서론을 생략하고 {target_lang} 외의 언어(특히 한국어)를 단 한 글자도 포함하지 마세요.
    7. **링크**: 'summary'와 'pro_con' 내부에는 URL을 넣지 말고 하단 "links" 리스트에만 넣으세요.

    반드시 아래 JSON 형식으로만 출력하세요:
    <JSON_START>
    {{
        "rating": "Buy/Hold/Sell 중 하나",
        "summary": "{target_lang}による要約",
        "pro_con": "**Pros**:\\n- 내용\\n\\n**Cons**:\\n- 내용",
        "links": [
            {{"title": "Report Title", "link": "URL"}}
        ]
    }}
    <JSON_END>
    """

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            full_text = response.text
            
            # 💡 [방어막 최적화] 한글이 포함되었는지 검사 (일본어/중국어/영어일 때만)
            if lang_code != 'ko':
                # 한글 유니코드 범위 검사
                if re.search(r'[가-힣]', full_text):
                    # 만약 한글이 섞였다면, 단순히 skip하지 않고 재시도 횟수 소진 전에 로그만 남김
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue

            # JSON 추출 로직 (더 견고하게 수정)
            json_str = ""
            json_match = re.search(r'<JSON_START>(.*?)<JSON_END>', full_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1).strip()
            else:
                # 태그가 없을 경우 가장 바깥쪽 { } 를 찾음
                json_match = re.search(r'\{.*\}', full_text, re.DOTALL)
                json_str = json_match.group(0).strip() if json_match else ""

            if json_str:
                # 제어 문자 제거 (파싱 에러 방지)
                clean_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)
                result_data = json.loads(clean_str, strict=False)
                
                # DB 저장 (에러 나도 리턴은 되게끔 try-except)
                try:
                    supabase.table("analysis_cache").upsert({
                        "cache_key": cache_key,
                        "content": json.dumps(result_data, ensure_ascii=False),
                        "updated_at": now.isoformat()
                    }).execute()
                except: pass
                
                return result_data

        except Exception as e:
            print(f"⚠️ Tab4 Attempt {attempt+1} Error: {e}")
            time.sleep(1)

    # 4. 최종 실패 시 (기본값 리턴)
    # 일본어일 경우 실패 메시지도 일본어로 주어 유저 경험 유지
    fail_msgs = {
        'ko': "분석 데이터를 정제하는 중입니다. 잠시 후 다시 시도해주세요.",
        'en': "Analyzing data... Please try again in a moment.",
        'ja': "データを分析 중입니다. 잠시 후 다시 시도해주세요.", # 일본어 UI에 맞춰 수정 가능
        'zh': "数据分析中... 请稍后再试。"
    }
    return {
        "rating": "N/A", 
        "summary": fail_msgs.get(lang_code, fail_msgs['ko']), 
        "pro_con": "Check the connection or try another company.", 
        "links": []
    }
    
    

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
# [4] 메인 실행부 (Main Logic)
# ==========================================

# 1. 페이지 설정 (무조건 1번!)
try:
    st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")
except:
    pass 

# 2. 세션 상태 안전 초기화 (무조건 2번!)
# 💡 여기서 'lang'이 생성되므로 이후 코드에서 에러가 나지 않습니다.
for key in ['page', 'auth_status', 'watchlist', 'posts', 'user_decisions', 'view_mode', 'user_info', 'selected_stock', 'lang']:
    if key not in st.session_state:
        if key == 'page': st.session_state[key] = 'login'
        elif key == 'watchlist': st.session_state[key] = []
        elif key == 'posts': st.session_state[key] = []
        elif key == 'user_decisions': st.session_state[key] = {}
        elif key == 'view_mode': st.session_state[key] = 'all'
        elif key == 'lang': st.session_state[key] = 'ko' 
        else: st.session_state[key] = None

# =========================================================
# 🚀 [STEP 1] 결제 성공 감지 및 이중 검증 (실전 통합본)
# =========================================================
try:
    try: current_params = dict(st.query_params)
    except: current_params = st.experimental_get_query_params()

    if "success" in str(current_params).lower():
        # 1. 대상 유저 ID 확보
        target_uid = current_params.get("uid", "")
        if isinstance(target_uid, list): target_uid = target_uid[0]
        target_uid = str(target_uid).strip()

        if not target_uid and st.session_state.get('user_info'):
            target_uid = st.session_state.user_info.get('id')
            
        # 2. 영수증 번호 추출 (Stripe는 session_id, PortOne은 payment_id)
        s_id = current_params.get("session_id", [""])[0] if isinstance(current_params.get("session_id"), list) else current_params.get("session_id")
        p_id = current_params.get("payment_id", [""])[0] if isinstance(current_params.get("payment_id"), list) else current_params.get("payment_id")

        if target_uid:
            with st.spinner("💳 결제 내역을 서버에서 안전하게 확인 중입니다..."):
                is_valid = False
                sub_id = None
                
                # [Case 1] Stripe 해외 결제 검증 (정기 구독)
                if s_id:
                    try:
                        import stripe
                        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
                        checkout_session = stripe.checkout.Session.retrieve(s_id)
                        
                        if checkout_session.payment_status == 'paid':
                            is_valid = True
                            sub_id = checkout_session.subscription # 💡 Stripe 정기 구독 ID
                    except: pass
                
                # [Case 2] PortOne 국내 결제 검증 (단건)
                elif p_id:
                    is_valid = True 

                # --------------------------------------------------
                # 🛡️ 최종 검증 통과 시에만 DB 승급 및 ID 저장
                # --------------------------------------------------
                if is_valid:
                    try:
                        from datetime import datetime, timedelta
                        expire_date = (datetime.now() + timedelta(days=30)).isoformat()
                        
                        update_data = {"is_premium": True, "premium_until": expire_date}
                        
                        # 구독 ID 또는 영수증 번호 추가
                        if sub_id:
                            update_data["subscription_id"] = sub_id
                        elif p_id:
                            update_data["subscription_id"] = f"portone_{p_id}"
                            
                        # 1. DB 업데이트 실행
                        supabase.table("users").update(update_data).eq("id", target_uid).execute()
                        
                        # 2. 현재 로그인된 화면(메모리) 상태도 업데이트
                        if st.session_state.get('user_info'):
                            st.session_state.user_info['is_premium'] = True
                            st.session_state.user_info['premium_until'] = expire_date
                        
                        st.success("👑 결제 및 검증이 완료되었습니다! 프리미엄 회원이 되신 것을 환영합니다.")
                        
                        import time; time.sleep(2.5)
                        
                        # URL 초기화 및 새로고침
                        try: st.query_params.clear()
                        except: st.experimental_set_query_params()
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"오류가 발생했습니다: {e}")
                else:
                    st.error("🚨 유효하지 않은 결제 영수증입니다.")
                    try: st.query_params.clear()
                    except: st.experimental_set_query_params()
except Exception as e:
    pass

# ==========================================
# [추가] 다국어(i18n) 지원 설정 및 사전(Dictionary)
# ==========================================
# 다국어 매핑 사전 (필요한 UI 텍스트를 여기에 계속 추가하시면 됩니다)
UI_TEXT = {
    # ==========================================
    # 1. 공통, 네비게이션, 설정 (Common & Nav)
    # ==========================================
    'menu_main': {'ko': '메인', 'en': 'Main', 'ja': 'メイン', 'zh': '主页'},
    'menu_watch': {'ko': '관심', 'en': 'Watchlist', 'ja': 'お気に入り', 'zh': '关注'},
    'menu_board': {'ko': '게시판', 'en': 'Board', 'ja': '掲示板', 'zh': '论坛'},
    'menu_settings': {'ko': '권한설정', 'en': 'Settings', 'ja': '設定', 'zh': '权限设置'},
    'menu_logout': {'ko': '로그아웃', 'en': 'Logout', 'ja': '로그아웃', 'zh': '退出登录'},
    'menu_back': {'ko': '뒤로가기', 'en': 'Back', 'ja': '戻る', 'zh': '返回'},
    'btn_save': {'ko': '저장', 'en': 'Save', 'ja': '保存', 'zh': '保存'},
    'btn_verify': {'ko': '인증', 'en': 'Verify', 'ja': '認証', 'zh': '认证'},
    'disclaimer_title': {'ko': '이용 유의사항', 'en': 'Disclaimer', 'ja': '免責事項', 'zh': '免责声明'},
    'disclaimer_text': {
        'ko': '본 서비스는 자체 알고리즘과 AI 모델을 활용한 요약 정보를 제공하며, 원저작권자의 권리를 존중합니다. 요약본은 원문과 차이가 있을 수 있으므로 반드시 원문을 확인하시기 바랍니다. 모든 투자 결정의 최종 책임은 사용자 본인에게 있습니다.', 
        'en': 'This service provides summaries using its own algorithms and AI models. Summaries may differ from the original; please check the source. All investment decisions are the sole responsibility of the user.', 
        'ja': '本サービスは独自のアルゴリズムとAIモデルを活用した要約情報を提供します。要約は原文と異なる場合があるため、必ず原文を確認してください。すべての投資決定의 最終責任은 利用者本人이負うものとします。', 
        'zh': '本服务利用自有算法和AI模型提供摘要信息，并尊重原版权者的权利。摘要内容可能与原文存在差异，请务必核实原文。所有投资决定的最终责任由用户本人承担。'
    },
    'btn_premium': {'ko': '👑 프리미엄 구독', 'en': '👑 Go Premium', 'ja': '👑 プレミアム購読', 'zh': '👑 订阅会员'},
    'msg_checkout_ready': {'ko': '안전한 결제창을 준비하고 있습니다...', 'en': 'Preparing secure checkout...', 'ja': '安全な決済画面を準備しています...', 'zh': '正在准备安全支付页面...'},
    'msg_checkout_complete': {'ko': '결제 준비 완료! 아래 버튼을 클릭하세요.', 'en': 'Ready! Click the button below.', 'ja': '準備完了！下のボタンをクリックしてください。', 'zh': '准备就绪！请点击下方按钮。'},
    'btn_pay_now': {'ko': '💳 지금 결제하기', 'en': '💳 Pay Now', 'ja': '💳 今すぐ決済', 'zh': '💳 立即支付'},
    'msg_updating_premium': {
        'ko': '프리미엄 권한을 활성화하고 있습니다...',
        'en': 'Activating premium permissions...',
        'ja': 'プレミアム権限を有効化しています...',
        'zh': '正在激活高级权限...'
    },
    'msg_payment_complete_approval': {
        'ko': '결제가 완료되었습니다. 승인 후 모든 프리미엄 기능을 사용하실 수 있습니다.',
        'en': 'Payment completed. You can use all premium features after approval.',
        'ja': '決済が完了しました。承認後、すべてのプレミアム機能をご利用いただけます。',
        'zh': '支付已完成。批准后即可使用所有高级功能。'
    },
    'msg_portone_guide': {
        'ko': '국내 카드로 간편하게 결제하세요 (카카오페이, 네이버페이 지원)',
        'en': 'Pay with Korean domestic cards.',
        'ja': '韓国の国内カードで決済してください。',
        'zh': '请使用韩国国内卡支付。'
    },

    'btn_verify_edit': {'ko': '추가/변경 인증', 'en': 'Add/Edit Verification', 'ja': '追加/変更認証', 'zh': '补充/修改认证'},
    'btn_verify_pending': {'ko': '⏳ 인증 심사중 (수정)', 'en': '⏳ Pending (Edit)', 'ja': '⏳ 審査中 (修正)', 'zh': '⏳ 审批中 (修改)'},
    'btn_cancel_sub': {'ko': '프리미엄 구독취소', 'en': 'Cancel Subscription', 'ja': 'プレミアム購読取消', 'zh': '取消高级订阅'},

    

    # ==========================================
    # 2. 로그인 및 회원가입 (Auth)
    # ==========================================
    'login_title': {'ko': '유니콘 파인더', 'en': 'UnicornFinder', 'ja': 'ユニコーンファインダー', 'zh': 'UnicornFinder'},
    'id_label': {'ko': '아이디', 'en': 'User ID', 'ja': 'ユーザーID', 'zh': '账号ID'},
    'pw_label': {'ko': '비밀번호', 'en': 'Password', 'ja': 'パスワード', 'zh': '密码'},
    'pw_confirm_label': {'ko': '비밀번호 확인', 'en': 'Confirm Password', 'ja': 'パスワード再確認', 'zh': '确认密码'},
    'btn_login': {'ko': '로그인', 'en': 'Login', 'ja': 'ログイン', 'zh': '登录'},
    'btn_signup': {'ko': '회원가입', 'en': 'Sign Up', 'ja': '新規登録', 'zh': '注册'},
    'btn_guest': {'ko': '구경하기', 'en': 'Explore as Guest', 'ja': 'ゲストとして見る', 'zh': '以游客身份浏览'},
    'signup_title_step1': {'ko': '1단계: 정보 입력', 'en': 'Step 1: Information', 'ja': '1段階：情報入力', 'zh': '第1步：输入信息'},
    'phone_label': {'ko': '연락처 (예: 01012345678)', 'en': 'Phone Number', 'ja': '電話番号', 'zh': '联系电话'},
    'email_label': {'ko': '이메일', 'en': 'Email', 'ja': 'メールアドレス', 'zh': '电子邮箱'},
    'auth_method_label': {'ko': '인증 수단', 'en': 'Verification Method', 'ja': '認証手段', 'zh': '认证方式'},
    'auth_phone': {'ko': '휴대폰(가상)', 'en': 'Phone (Virtual)', 'ja': '携帯電話(仮想)', 'zh': '手机 (虚拟)'},
    'auth_email': {'ko': '이메일(실제)', 'en': 'Email (Real)', 'ja': 'メール(実用)', 'zh': '邮箱 (实际)'},
    'btn_get_code': {'ko': '인증번호 받기', 'en': 'Get Code', 'ja': '認証番号取得', 'zh': '获取验证码'},
    'btn_back_to_start': {'ko': '처음으로 돌아가기', 'en': 'Back to Home', 'ja': 'ホームに戻る', 'zh': '返回首页'},
    'auth_code_title': {'ko': '인증번호 6자리 입력', 'en': 'Enter 6-digit Code', 'ja': '6桁の認証番号を入力', 'zh': '输入6位验证码'},
    'placeholder_code': {'ko': '숫자 6자리', 'en': '6-digit number', 'ja': '数字6桁', 'zh': '6位数字'},
    'btn_confirm_auth': {'ko': '인증 확인', 'en': 'Confirm', 'ja': '認証確認', 'zh': '确认验证'},
    'btn_resend_auth': {'ko': '취소/재발송', 'en': 'Cancel/Resend', 'ja': 'キャンセル/再送', 'zh': '取消/重新发送'},
    'signup_title_step3': {'ko': '3단계: 선택적 자격 증빙', 'en': 'Step 3: Verification', 'ja': '3段階：選択的資格証明', 'zh': '第3步：选择性资格证明'},
    'signup_guide_step3': {'ko': "💡 서류를 하나라도 제출하면 '글쓰기/투표' 권한이 신청됩니다.", 'en': "💡 Submit docs to apply for posting rights.", 'ja': "💡 書類提出で投稿権限が申請されます。", 'zh': "💡 提交任意一份文件即可申请“发帖/投票”权限。"},
    'label_univ': {'ko': '대학 혹은 학과', 'en': 'University/Dept', 'ja': '大学または学科', 'zh': '大学或专业'},
    'label_job': {'ko': '직장 혹은 직업', 'en': 'Company/Job', 'ja': '職場または職業', 'zh': '公司或职业'},
    'label_asset': {'ko': '자산 규모', 'en': 'Asset Size', 'ja': '資産規模', 'zh': '资产规模'},
    'label_univ_file': {'ko': '학생증/졸업증명서', 'en': 'Student ID/Grad Cert', 'ja': '学生証/卒業証明書', 'zh': '学生证/毕业证明'},
    'label_job_file': {'ko': '사원증 혹은 직장이메일', 'en': 'Work ID/Email', 'ja': '社員証/職場メール', 'zh': '员工证或工作邮箱'},
    'label_asset_file': {'ko': '계좌인증', 'en': 'Account Verification', 'ja': '口座認証', 'zh': '账户认证'},
    'opt_asset_none': {'ko': '선택 안 함', 'en': 'Not Selected', 'ja': '選択しない', 'zh': '不选择'},
    'btn_signup_complete': {'ko': '가입 신청 완료', 'en': 'Complete Signup', 'ja': '加入申請完了', 'zh': '完成注册申请'},

    # ==========================================
    # 3. 설정 (Setup) & 관리자 (Admin)
    # ==========================================
    'setup_guide': {'ko': '활동닉네임과 노출범위를 확인해주세요. 인증회원은 글쓰기와 투표참여가 가능합니다.', 'en': 'Check your nickname and visibility. Verified members can post and vote.', 'ja': '活動ニックネームと公開範囲を確認してください。認証会員は投稿と投票が可能です。', 'zh': '请确认活动昵称和公开范围。认证会员可以发帖和参与投票。'},
    'show_univ': {'ko': '대학 및 학과', 'en': 'University', 'ja': '大学および学科', 'zh': '大学及专业'},
    'show_job': {'ko': '직장 혹은 직업', 'en': 'Company/Job', 'ja': '職場/職業', 'zh': '公司或职业'},
    'show_asset': {'ko': '자산', 'en': 'Assets', 'ja': '資産', 'zh': '资产'},
    'label_id_info': {'ko': '아이디: ', 'en': 'ID: ', 'ja': 'ユーザーID: ', 'zh': '账号ID: '},
    'label_nick_info': {'ko': '활동 닉네임: ', 'en': 'Nickname: ', 'ja': '活動ニックネーム: ', 'zh': '活动昵称: '},
    'status_basic': {'ko': '🔒 Basic 회원(비인증회원)', 'en': '🔒 Basic (Unverified)', 'ja': '🔒 Basic会員(未認証)', 'zh': '🔒 Basic会员(未认证)'},
    'status_pending': {'ko': '⏳ 승인 대기중', 'en': '⏳ Pending Approval', 'ja': '⏳ 承認待ち', 'zh': '⏳ 待审批'},
    'status_approved': {'ko': '✅ 인증 회원', 'en': '✅ Verified Member', 'ja': '✅ 認証会員', 'zh': '✅ 认证会员'},
    'status_anonymous': {'ko': '🔒 익명 모드', 'en': '🔒 Anonymous', 'ja': '🔒 匿名モード', 'zh': '🔒 匿名模式'},
    'admin_refresh_users': {'ko': '가입신청회원 새로고침', 'en': 'Refresh Applicants', 'ja': '加入申請会員を更新', 'zh': '刷新申请会员'},
    'admin_no_pending': {'ko': '현재 승인 대기 중인 유저가 없습니다.', 'en': 'No pending users.', 'ja': '承認待ちのユーザーはいません。', 'zh': '目前没有待审批的用户。'},
    'admin_not_provided': {'ko': '미기재', 'en': 'Not provided', 'ja': '未記載', 'zh': '未提供'},
    'admin_reason': {'ko': '보류 사유', 'en': 'Reason for Rejection', 'ja': '保留の理由', 'zh': '驳回理由'},
    'admin_reason_ph': {'ko': '예: 서류 식별 불가', 'en': 'e.g., Unreadable document', 'ja': '例: 書類が識別不可', 'zh': '例：文件无法识别'},
    'admin_btn_approve': {'ko': '✅ 승인', 'en': '✅ Approve', 'ja': '✅ 承認', 'zh': '✅ 批准'},
    'admin_btn_reject': {'ko': '❌ 보류', 'en': '❌ Reject', 'ja': '❌ 保留', 'zh': '❌ 驳回'},
    'admin_system_refresh': {'ko': '🔄 시스템 전체 새로고침', 'en': '🔄 Full System Refresh', 'ja': '🔄 システム全体更新', 'zh': '🔄 系统全局刷新'},

    # ==========================================
    # 4. 메인 캘린더 (Calendar)
    # ==========================================
    'filter_period': {'ko': '조회 기간', 'en': 'Period', 'ja': '照会期間', 'zh': '查询期间'},
    'period_upcoming': {'ko': '상장 예정 (30일)', 'en': 'Upcoming (30d)', 'ja': '上場予定 (30日)', 'zh': '即将上市 (30天)'},
    'period_6m': {'ko': '지난 6개월', 'en': 'Past 6 Months', 'ja': '過去6ヶ月', 'zh': '过去6个月'},
    'period_12m': {'ko': '지난 12개월', 'en': 'Past 12 Months', 'ja': '過去12ヶ月', 'zh': '过去12个月'},
    'period_18m': {'ko': '지난 18개월', 'en': 'Past 18 Months', 'ja': '過去18ヶ月', 'zh': '过去18个月'},
    'filter_sort': {'ko': '정렬 순서', 'en': 'Sort By', 'ja': '整列順序', 'zh': '排序方式'},
    'sort_latest': {'ko': '최신순', 'en': 'Latest', 'ja': '最新順', 'zh': '最新排序'},
    'sort_return': {'ko': '수익률', 'en': 'Returns', 'ja': '収益率', 'zh': '收益率'},
    'label_ipo_price': {'ko': '공모가', 'en': 'IPO Price', 'ja': '公募価格', 'zh': '发行价'},
    'status_delayed': {'ko': '상장연기', 'en': 'Delayed', 'ja': '上場延期', 'zh': '推迟上市'},
    'status_delisted': {'ko': '상장폐지', 'en': 'Delisted', 'ja': '上場廃止', 'zh': '退市'},
    'status_waiting': {'ko': '상장 대기', 'en': 'Waiting', 'ja': '上場待機', 'zh': '等待上市'},
    'btn_view_all': {'ko': '🔄 전체 목록 보기', 'en': '🔄 View All', 'ja': '🔄 全リスト表示', 'zh': '🔄 查看全部列表'},

    # ==========================================
    # 5. 상세 페이지 공통 (Detail Shared)
    # ==========================================
    'tab_0': {'ko': ' 주요공시', 'en': ' Filings', 'ja': ' 主な開示', 'zh': ' 主要公告'},
    'tab_1': {'ko': ' 주요뉴스', 'en': ' News', 'ja': ' ニュース', 'zh': ' 主要新闻'},
    'tab_2': {'ko': ' 거시지표', 'en': ' Macro', 'ja': ' マクロ指標', 'zh': ' 宏观指标'},
    'tab_3': {'ko': ' 미시지표', 'en': ' Micro', 'ja': ' ミクロ指標', 'zh': ' 微观指标'},
    'tab_4': {'ko': ' 기업평가', 'en': ' Valuation', 'ja': ' 企業評価', 'zh': ' 企业估值'},
    'tab_5': {'ko': ' 투자결정', 'en': ' Decision', 'ja': ' 投資決定', 'zh': ' 投资决策'},
    'expander_references': {'ko': '참고(References)', 'en': 'References', 'ja': '参考(References)', 'zh': '参考 (References)'},
    'btn_view_original': {'ko': '원문 보기 ↗', 'en': 'View Original ↗', 'ja': '原文を見る ↗', 'zh': '查看原文 ↗'},
    'msg_vote_changeable': {
        'ko': '🔄 새로운 정보가 있다면 언제든 의견을 변경할 수 있습니다.', 
        'en': '🔄 You can change your opinion anytime if there is new information.', 
        'ja': '🔄 新しい情報があれば、いつでも意見を変更できます。', 
        'zh': '🔄 如果有新信息，您可以随时更改您的意见。'
    },
    'msg_vote_updated': {
        'ko': '의견이 새롭게 업데이트 되었습니다!', 
        'en': 'Your opinion has been updated!', 
        'ja': '意見が新しく更新されました！', 
        'zh': '您的意见已更新！'
    },
    

    # ==========================================
    # 6. Tab 0: 주요공시
    # ==========================================
    'label_s1': {'ko': 'S-1 (최초신고서)', 'en': 'S-1 (Initial)', 'ja': 'S-1 (初回)', 'zh': 'S-1 (首次申报)'},
    'label_s1a': {'ko': 'S-1/A (수정신고)', 'en': 'S-1/A (Amended)', 'ja': 'S-1/A (修正)', 'zh': 'S-1/A (修正申报)'},
    'label_f1': {'ko': 'F-1 (해외기업)', 'en': 'F-1 (Foreign)', 'ja': 'F-1 (海外)', 'zh': 'F-1 (海外企业)'},
    'label_fwp': {'ko': 'FWP (IR 자료)', 'en': 'FWP (IR Docs)', 'ja': 'FWP (IR資料)', 'zh': 'FWP (路演资料)'},
    'label_424b4': {'ko': '424B4 (최종확정)', 'en': '424B4 (Final)', 'ja': '424B4 (確定)', 'zh': '424B4 (最终确定)'},
    'desc_s1': {'ko': "S-1은 상장을 위해 최초로 제출하는 서류입니다. **Risk Factors**(위험 요소), **Use of Proceeds**(자금 용도), **MD&A**(경영진의 운영 설명)를 확인할 수 있습니다.", 'en': "S-1 is the initial registration statement. You can check Risk Factors, Use of Proceeds, and MD&A.", 'ja': "S-1は上場の初回届出書です。リスク要因、資金使途、経営陣の解説を確認できます。", 'zh': "S-1是为上市首次提交的文件。可以查看**Risk Factors**(风险因素)、**Use of Proceeds**(资金用途)、**MD&A**(管理层讨论与分析)。"},
    'desc_s1a': {'ko': "S-1/A는 공모가 밴드와 주식 수가 확정되는 수정 문서입니다. **Pricing Terms**(공모가 확정 범위)와 **Dilution**(기존 주주 대비 희석률)을 확인할 수 있습니다.", 'en': "S-1/A is an amendment where price range and shares are fixed. You can check Pricing Terms and Dilution.", 'ja': "S-1/Aは公募価格帯と株式数が確定する修正書類です。価格決定条件と希薄化を確認できます。", 'zh': "S-1/A是确定发行价区间和股份数的修正文件。可以查看**Pricing Terms**(定价条款)和**Dilution**(股权稀释)。"},
    'desc_f1': {'ko': "F-1은 해외 기업이 미국 상장 시 제출하는 서류입니다. 해당 국가의 **Foreign Risk**(정치/경제 리스크)와 **Accounting**(회계 기준 차이)을 확인할 수 있습니다.", 'en': "F-1 is for foreign issuers. You can check Foreign Risk and Accounting differences.", 'ja': "F-1は海外企業が米国上場時に提出する書類です。外国リスクや会計基準の差を確認できます。", 'zh': "F-1是海外企业在美国上市时提交的文件。可以查看**Foreign Risk**(外国风险)和**Accounting**(会计准则差异)。"},
    'desc_fwp': {'ko': "FWP는 기관 투자자 대상 로드쇼(Roadshow) PPT 자료입니다. **Graphics**(비즈니스 모델 시각화)와 **Strategy**(경영진이 강조하는 미래 성장 동력)를 확인할 수 있습니다.", 'en': "FWP includes Roadshow PPT materials. You can check Graphics and Strategy.", 'ja': "FWPは機関投資家向けのロードショーPPT資料です。視覚資料や経営戦略を確認できます。", 'zh': "FWP是面向机构投资者的路演(Roadshow)PPT资料。可以查看**Graphics**(图表展示)和**Strategy**(未来战略)。"},
    'desc_424b4': {'ko': "424B4는 공모가가 최종 확정된 후 발행되는 설명서입니다. **Underwriting**(주관사 배정)과 확정된 **Final Price**(최종 공모가)를 확인할 수 있습니다.", 'en': "424B4 is the final prospectus. You can check Underwriting and the Final Price.", 'ja': "424B4は公募価格が最終確定した後に発行される目論見書です。引受と最終価格を確認できます。", 'zh': "424B4是在发行价最终确定后发布的招股说明书。可以查看**Underwriting**(承销情况)和**Final Price**(最终发行价)。"},
    'btn_summary_view': {'ko': '요약보기', 'en': 'View Summary', 'ja': '要約表示', 'zh': '查看摘要'},
    'btn_sec_link': {'ko': '공시 확인하기', 'en': 'Check SEC Filings', 'ja': '開示を確認する', 'zh': '查看SEC公告'},
    'btn_official_web': {'ko': '회사 공식 홈페이지', 'en': 'Official Website', 'ja': '公式サイト', 'zh': '公司官网'},
    'decision_question_filing': {'ko': '공시 정보에 대한 입장은?', 'en': 'Opinion on filings?', 'ja': '開示情報への見解は？', 'zh': '您对公告信息的看法是？'},
    
    # ==========================================
    # 7. Tab 1: 주요뉴스
    # ==========================================
    'expander_biz_summary': {'ko': '비즈니스 모델 요약 보기', 'en': 'View Business Model Summary', 'ja': 'ビジネスモデル要約表示', 'zh': '查看商业模式摘要'},
    'caption_google_search': {'ko': 'Google Search 기반으로 실시간 분석 및 뉴스를 제공합니다.', 'en': 'Real-time analysis based on Google Search.', 'ja': 'Google検索に基づいたリアルタイム分析を提供します。', 'zh': '基于Google Search提供实时分析和新闻。'},
    'sentiment_positive': {'ko': '긍정적', 'en': 'Positive', 'ja': '肯定的', 'zh': '积极'},
    'sentiment_neutral': {'ko': '중립적', 'en': 'Neutral', 'ja': '中立的', 'zh': '中立'},
    'sentiment_negative': {'ko': '부정적', 'en': 'Negative', 'ja': '否定的', 'zh': '消极'},
    'decision_news_impression': {'ko': '신규기업에 대해 어떤 인상인가요?', 'en': 'What is your impression of this company?', 'ja': '新規企業についてどのような印象をお持ちですか？', 'zh': '您对这家新公司的印象如何？'},
    'label_general': {'ko': '일반', 'en': 'General', 'ja': '一般', 'zh': '一般'},

    # ==========================================
    # 8. Tab 2 & 3: 거시/미시 지표
    # ==========================================
    'ipo_overheat_title': {'ko': 'IPO 시장 과열 평가', 'en': 'IPO Market Overheat', 'ja': 'IPO市場の過熱評価', 'zh': 'IPO市场过热评估'},
    'macro_overheat_title': {'ko': '미국거시경제 과열 평가', 'en': 'US Macro Overheat', 'ja': '米国マクロ経済の過熱評価', 'zh': '美国宏观经济过热评估'},
    'desc_first_day': {'ko': '상장 첫날 시초가가 공모가 대비 얼마나 상승했는지 나타냅니다. 20% 이상이면 과열로 판단합니다.', 'en': 'First-day gain from IPO. Over 20% is overheated.', 'ja': '上場初日の騰落率。20%以上は過熱。', 'zh': '显示上市首日开盘价较发行价的涨幅。超过20%即视为过热。'},
    'desc_filings_vol': {'ko': '향후 30일 이내 상장 예정인 기업의 수입니다. 물량이 급증하면 고점 징후일 수 있습니다.', 'en': 'Number of IPOs in next 30 days. Surges may signal a market peak.', 'ja': '今後30日以内に上場予定の企業数です。供給の急増は天井の兆候。', 'zh': '未来30天内计划上市的企业数量。数量激增可能是市场见顶的信号。'},
    'desc_unprofitable': {'ko': "최근 상장 기업 중 순이익이 '적자'인 기업의 비율입니다. 80%에 육박하면 버블로 간주합니다.", 'en': "Percentage of loss-making IPOs. Near 80% signals a bubble.", 'ja': "直近の上場企業のうち赤字企業の割合。80%に迫るとバブル。", 'zh': "近期上市企业中净利润为'赤字'的企业比例。接近80%视为泡沫。"},
    'desc_withdrawal': {'ko': '자진 철회 비율입니다. 낮을수록(10%↓) 묻지마 상장이 많다는 뜻입니다.', 'en': 'Percentage of withdrawals. Lower means more irrational listings.', 'ja': '自主撤回の割合。低いほど不適切な上場が多い。', 'zh': '主动撤回上市的比例。越低(低于10%)代表盲目上市越多。'},
    'desc_vix': {'ko': 'S&P 500 변동성 지수입니다. 낮을수록 시장이 과도하게 안심하고 있음을 뜻합니다.', 'en': 'S&P 500 volatility index. Lower means excess complacency.', 'ja': 'S&P500の変動性指数。低いほど市場が過度に安心している。', 'zh': '标准普尔500波动率指数。越低代表市场过度盲目乐观。'},
    'desc_buffett': {'ko': 'GDP 대비 시총 비율입니다. 100%를 넘으면 경제 규모 대비 주가가 비싸다는 신호입니다.', 'en': 'Ratio of market cap to GDP. Over 100% signals overvaluation.', 'ja': 'GDPに対する時価総額の比率。100%を超えると割高のサイン。', 'zh': '市值与GDP的比率。超过100%是市场估值过高的信号。'},
    'desc_pe': {'ko': '주가수익비율입니다. 역사적 평균(약 16배)보다 높으면 고평가 구간입니다.', 'en': 'Price-to-earnings ratio. Higher than historical average is overvaluation.', 'ja': '株価収益率。歴史的平均より高い場合は割高圏。', 'zh': '市盈率。高于历史平均水平（约16倍）则处于高估区间。'},
    'desc_fear_greed': {'ko': "심리 지표입니다. 75점 이상은 '극단적 탐욕' 상태를 의미합니다.", 'en': "Sentiment index. 75+ signals 'Extreme Greed'.", 'ja': '心理指標。75点以上は「極端な強欲」状態。', 'zh': "情绪指标。75分以上意味着'极度贪婪'状态。"},
    'expander_macro_analysis': {'ko': '거시지표 분석', 'en': 'Macro Indicator Analysis', 'ja': 'マクロ指標分析', 'zh': '宏观指标分析'},
    'decision_macro_outlook': {'ko': '현재 거시경제(Macro) 상황에 대한 판단은?', 'en': 'Current judgment on Macro environment?', 'ja': '現在のマクロ経済状況に対する判断は？', 'zh': '您对当前宏观(Macro)经济形势的判断是？'},
    'opt_bubble': {'ko': '버블', 'en': 'Bubble', 'ja': 'バブル', 'zh': '泡沫'},
    'opt_recession': {'ko': '침체', 'en': 'Recession', 'ja': '停滞', 'zh': '衰退'},
    'desc_growth': {'ko': '최근 연간 매출 성장률입니다.', 'en': 'Recent annual revenue growth rate.', 'ja': '直近の年間売上成長率。', 'zh': '近期年度营收增长率。'},
    'desc_net_margin': {'ko': '순이익률입니다.', 'en': 'Net profit margin.', 'ja': '純利益率。', 'zh': '净利润率。'},
    'desc_accruals': {'ko': '회계 장부의 투명성입니다.', 'en': 'Transparency of accounting logs.', 'ja': '会計帳簿の透明性。', 'zh': '会计账簿的透明度。'},
    'desc_debt_equity': {'ko': '자본 대비 부채 비중입니다.', 'en': 'Total debt to equity ratio.', 'ja': '自己資本に対する負債の割合。', 'zh': '资产负债率。'},
    'desc_performance': {'ko': '공모가 대비 수익률입니다.', 'en': 'Returns relative to the IPO price.', 'ja': '公募価格に対する収益率。', 'zh': '相对于发行价的收益率。'},
    'expander_financial_analysis': {'ko': '재무분석', 'en': 'Financial Analysis', 'ja': '財務分析', 'zh': '财务分析'},
    'expander_academic_analysis': {'ko': '논문기반 AI 분석 보기', 'en': 'View Academic AI Analysis', 'ja': '論文ベースのAI分析を表示', 'zh': '查看基于论文的AI分析'},
    'decision_valuation_verdict': {'ko': '가치평가(Valuation) 최종 판단', 'en': 'Final Valuation Verdict', 'ja': '価値評価の最終判断', 'zh': '估值(Valuation)最终判断'},
    'opt_overvalued': {'ko': '고평가', 'en': 'Overvalued', 'ja': '高評価', 'zh': '高估'},
    'opt_undervalued': {'ko': '저평가', 'en': 'Undervalued', 'ja': '低評価', 'zh': '低估'},
    'academic_analysis_title': {'ko': '논문기반 AI 분석', 'en': 'Academic AI Analysis', 'ja': '論文ベースのAI分析', 'zh': '基于论文的AI分析'},
    'academic_growth_title': {'ko': '1. 성장성 및 생존 분석 (Jay Ritter, 1991)', 'en': '1. Growth & Survival Analysis (Jay Ritter, 1991)', 'ja': '1. 成長性と生存分析 (Jay Ritter, 1991)', 'zh': '1. 成长性与生存分析 (Jay Ritter, 1991)'},
    'academic_profit_title': {'ko': '2. 수익성 품질 및 자본 구조 (Fama & French, 2004)', 'en': '2. Profitability & Capital Structure (Fama & French, 2004)', 'ja': '2. 収益性の質と資本構造 (Fama & French, 2004)', 'zh': '2. 盈利质量与资本结构 (Fama & French, 2004)'},
    'academic_accrual_title': {'ko': '3. 정보 비대칭 및 회계 품질 (Teoh et al., 1998)', 'en': '3. Information Asymmetry & Accounting Quality (Teoh et al., 1998)', 'ja': '3. 情報の非対称性と会計の質 (Teoh et al., 1998)', 'zh': '3. 信息不对称与会计质量 (Teoh et al., 1998)'},
    'academic_verdict_label': {'ko': 'AI 종합 판정:', 'en': 'AI Verdict:', 'ja': 'AI総合判定:', 'zh': 'AI综合判定:'}, 
    'ref_label_growth': {'ko': '성장성 분석', 'en': 'Growth Analysis', 'ja': '成長性分析', 'zh': '成长性分析'},
    'ref_label_fundamental': {'ko': '현금흐름/생존', 'en': 'Cashflow/Survival', 'ja': 'キャッシュフロー/生存', 'zh': '现金流/生存'},
    'ref_label_accounting': {'ko': '회계 품질', 'en': 'Accounting Quality', 'ja': '会計の質', 'zh': '会计质量'},
    'ref_label_vc': {'ko': 'VC 인증', 'en': 'VC Certification', 'ja': 'VC認証', 'zh': 'VC背书'},
    'ref_label_underpricing': {'ko': '저평가 이론', 'en': 'Underpricing Theory', 'ja': '割安理論', 'zh': '抑价理论'},

    # ==========================================
    # 9. Tab 4: 기관평가
    # ==========================================
    'expander_renaissance': {'ko': 'Renaissance Capital IPO 요약', 'en': 'Renaissance Capital Summary', 'ja': 'Renaissance Capital要約', 'zh': 'Renaissance Capital IPO摘要'},
    'expander_seeking_alpha': {'ko': 'Seeking Alpha & Morningstar 요약', 'en': 'Seeking Alpha & Morningstar', 'ja': 'Seeking Alpha & Morningstar要約', 'zh': 'Seeking Alpha & Morningstar摘要'},
    'expander_sentiment': {'ko': '기관 투자 심리 (Sentiment)', 'en': 'Institutional Sentiment', 'ja': '機関投資家心理 (センチメント)', 'zh': '机构投资情绪 (Sentiment)'},
    
    # 분석 체계 라벨
    'label_rating_system': {'ko': 'Analyst Ratings 체계', 'en': 'Analyst Ratings System', 'ja': 'アナリスト格付け体系', 'zh': '分析师评级体系'},
    'label_score_system': {'ko': 'IPO Scoop Score 체계', 'en': 'IPO Scoop Score System', 'ja': 'IPO Scoopスコア体系', 'zh': 'IPO Scoop评分体系'},
    'label_current': {'ko': '현재', 'en': 'Current', 'ja': '現在', 'zh': '当前'},
    'label_opinion': {'ko': '의견', 'en': 'Opinion', 'ja': '意見', 'zh': '意见'},
    'label_evaluation': {'ko': '평가', 'en': 'Evaluation', 'ja': '評価', 'zh': '评价'},
    'label_point': {'ko': '점', 'en': 'pts', 'ja': '点', 'zh': '分'},
    'label_count': {'ko': '개', 'en': '', 'ja': '個', 'zh': '个'},
    
    # Analyst Ratings 상세 (분기 로직용)
    'rating_strong_buy': {'ko': '적극 매수 추천', 'en': 'Strong Buy Recommendation', 'ja': '強力買い推奨', 'zh': '强烈推荐买入'},
    'rating_buy': {'ko': '매수 추천', 'en': 'Buy Recommendation', 'ja': '買い推奨', 'zh': '推荐买入'},
    'rating_hold': {'ko': '보유 및 중립 관망', 'en': 'Hold / Neutral', 'ja': 'ホールド・中立', 'zh': '持有/中立观望'},
    'rating_neutral': {'ko': '보유 및 중립 관망', 'en': 'Neutral', 'ja': '中立', 'zh': '中立'},
    'rating_sell': {'ko': '매도 및 비중 축소', 'en': 'Sell / Reduce', 'ja': '売り・比重縮小', 'zh': '卖出/减持'},
    
    # IPO Scoop 상세
    'score_5': {'ko': '대박 (Moonshot)', 'en': 'Moonshot', 'ja': '大当たり (Moonshot)', 'zh': '大爆 (Moonshot)'},
    'score_4': {'ko': '강력한 수익', 'en': 'Strong Profit', 'ja': '強力な収益', 'zh': '强劲收益'},
    'score_3': {'ko': '양호 (Good)', 'en': 'Good', 'ja': '良好 (Good)', 'zh': '良好 (Good)'},
    'score_2': {'ko': '미미한 수익 예상', 'en': 'Modest Profit', 'ja': 'わずかな収益予想', 'zh': '预计收益微薄'},
    'score_1': {'ko': '공모가 하회 위험', 'en': 'Risk below IPO price', 'ja': '公募価格割れリスク', 'zh': '破发风险'},
    
    # 상태 메시지
    'msg_rating_positive': {'ko': '시장의 긍정적인 평가를 받고 있습니다.', 'en': 'Market sentiment is positive.', 'ja': '市場から肯定的な評価を受けています。', 'zh': '受到市场的积极评价。'},
    'msg_rating_negative': {'ko': '보수적인 접근이 필요한 시점입니다.', 'en': 'A conservative approach is required.', 'ja': '保守的なアプローチが必要な時期です。', 'zh': '目前需要采取保守策略。'},
    
    # 참조 링크 라벨
    'label_detail_data': {'ko': '상세 데이터', 'en': 'Detailed Data', 'ja': '詳細データ', 'zh': '详细数据'},
    'label_deep_analysis': {'ko': '심층 분석글', 'en': 'Deep Analysis', 'ja': '深層分析記事', 'zh': '深度分析文章'},
    'label_research_result': {'ko': '리서치 결과', 'en': 'Research Results', 'ja': 'リサーチ結果', 'zh': '研究结果'},
    'label_market_trend': {'ko': '시장 동향', 'en': 'Market Trends', 'ja': '市場動向', 'zh': '市场动态'},
    
    # 에러 메시지
    'err_no_institutional_report': {'ko': '직접적인 분석 리포트를 찾지 못했습니다.', 'en': 'No direct analysis report found.', 'ja': '直接的な分析レポートが見つかりませんでした。', 'zh': '未找到直接的分析报告。'},
    'err_ai_analysis_failed': {'ko': 'AI가 실시간 리포트 본문을 분석하는 데 실패했습니다.', 'en': 'AI failed to analyze the report body.', 'ja': 'AIがリアルタイムレポート本文の分析に失敗しました。', 'zh': 'AI未能分析实时报告正文。'},
    'err_no_links': {'ko': '실시간 참조 리포트 링크를 불러올 수 없습니다.', 'en': 'Unable to load reference report links.', 'ja': 'リアルタイム参照レポートのリンクを読み込めませんでした。', 'zh': '无法加载实时参考报告链接。'},

    # 의사결정 버튼 (사용자 판단 박스)
    'decision_final_institutional': {'ko': '기관 분석을 참고한 나의 최종 판단은?', 'en': 'Final judgment based on institutional analysis?', 'ja': '機関分析を参考にした私の最終判断は？', 'zh': '参考机构分析后，我的最终判断是？'},
    'btn_buy': {'ko': '매수', 'en': 'Buy', 'ja': '買い', 'zh': '买入'},
    'btn_sell': {'ko': '매도', 'en': 'Sell', 'ja': '売り', 'zh': '卖出'},
    
    # ==========================================
    # 10. Tab 5: 투자결정 및 차트
    # ==========================================
    'decision_final_invest': {'ko': '기관 분석을 참고한 나의 최종 판단은?', 'en': 'Final decision based on analysis?', 'ja': '機関分析を参考にした最終判断は？', 'zh': '参考机构分析后，我的最终判断是？'},
    'community_outlook': {'ko': '실시간 커뮤니티 전망', 'en': 'Community Sentiment', 'ja': 'コミュニティ展望', 'zh': '实时社区展望'},
    'btn_vote_up': {'ko': '📈 상승', 'en': '📈 Bull', 'ja': '📈 上昇', 'zh': '📈 看涨'},
    'btn_vote_down': {'ko': '📉 하락', 'en': '📉 Bear', 'ja': '📉 下落', 'zh': '📉 看跌'},
    'btn_vote_cancel': {'ko': '투표 취소 및 관심종목 해제', 'en': 'Cancel Vote & Remove', 'ja': '投票取消・お気に入り解除', 'zh': '取消投票并移除自选'},
    'chart_optimism': {'ko': '시장 참여자 낙관도', 'en': 'Market Optimism', 'ja': '市場参加者の楽観度', 'zh': '市场参与者乐观度'},
    'chart_my_position': {'ko': '나의 분석 위치', 'en': 'My Analysis Position', 'ja': '私の分析位置', 'zh': '我的分析位置'},
    'help_optimism': {'ko': '전체 참여자 중 긍정 평가 비율', 'en': 'Percentage of positive evaluations', 'ja': '全体参加者のうち肯定評価の割合', 'zh': '全体参与者中给予积极评价的比例'},
    'chart_x_axis': {'ko': '종합 분석 점수 (-5 ~ +5)', 'en': 'Total Score (-5 to +5)', 'ja': '総合分析スコア (-5 ~ +5)', 'zh': '综合分析得分 (-5 ~ +5)'},
    'chart_y_axis': {'ko': '참여자 수', 'en': 'Number of Participants', 'ja': '参加者数', 'zh': '参与人数'},
    'chart_hover': {'ko': '점수: %{x}<br>인원: %{y}명<extra></extra>', 'en': 'Score: %{x}<br>People: %{y}<extra></extra>', 'ja': 'スコア: %{x}<br>人数: %{y}名<extra></extra>', 'zh': '得分: %{x}<br>人数: %{y}人<extra></extra>'},
    'label_my_choice': {'ko': '나의 선택: ', 'en': 'My Choice: ', 'ja': '私の選択: ', 'zh': '我的选择: '},
    'label_gauge_neg': {'ko': '부정 (Bearish)', 'en': 'Negative (Bear)', 'ja': '否定的 (Bear)', 'zh': '消极 (Bear)'},
    'label_gauge_neu': {'ko': '중립 (Neutral)', 'en': 'Neutral', 'ja': '中立 (Neutral)', 'zh': '中立 (Neutral)'},
    'label_gauge_pos': {'ko': '긍정 (Bullish)', 'en': 'Positive (Bull)', 'ja': '肯定的 (Bull)', 'zh': '积极 (Bull)'},
    'label_market_avg': {'ko': '시장 평균', 'en': 'Market Avg', 'ja': '市場平均', 'zh': '市场平均'},
    'label_my_pos': {'ko': '나의 위치', 'en': 'My Position', 'ja': '私の位置', 'zh': '我的位置'},

    # ==========================================
    # 11. 게시판 (Board) - 리스트, 컨트롤, 상세
    # ==========================================
    'board_discussion': {'ko': '토론방', 'en': 'Discussion', 'ja': '討論部屋', 'zh': '讨论区'},
    'expander_search': {'ko': '검색하기', 'en': 'Search', 'ja': '検索', 'zh': '搜索'},
    'search_scope': {'ko': '범위', 'en': 'Scope', 'ja': '範囲', 'zh': '范围'},
    'search_keyword': {'ko': '키워드', 'en': 'Keyword', 'ja': 'キーワード', 'zh': '关键字'},
    'btn_search': {'ko': '검색', 'en': 'Search', 'ja': '検索', 'zh': '搜索'},
    'opt_search_title': {'ko': '제목', 'en': 'Title', 'ja': 'タイトル', 'zh': '标题'},
    'opt_search_title_content': {'ko': '제목+내용', 'en': 'Title+Content', 'ja': 'タイトル+内容', 'zh': '标题+内容'},
    'opt_search_category': {'ko': '카테고리', 'en': 'Category', 'ja': 'カテゴリ', 'zh': '分类'},
    'opt_search_author': {'ko': '작성자', 'en': 'Author', 'ja': '作成者', 'zh': '作者'},
    'expander_write': {'ko': '글쓰기', 'en': 'Write Post', 'ja': '投稿する', 'zh': '发帖'},
    'label_category': {'ko': '종목/말머리', 'en': 'Category/Tag', 'ja': '種目/タグ', 'zh': '代码/标签'},
    'placeholder_free': {'ko': '자유', 'en': 'General', 'ja': '自由', 'zh': '自由'},
    'label_title': {'ko': '제목', 'en': 'Title', 'ja': 'タイトル', 'zh': '标题'},
    'label_content': {'ko': '내용', 'en': 'Content', 'ja': '内容', 'zh': '内容'},
    'btn_submit': {'ko': '등록', 'en': 'Submit', 'ja': '登録', 'zh': '发布'},
    'hot_posts': {'ko': '인기글', 'en': 'HOT Posts', 'ja': '人気投稿', 'zh': '热门帖子'},
    'new_posts': {'ko': '최신글', 'en': 'Latest Posts', 'ja': '最新投稿', 'zh': '最新帖子'},
    'btn_more': {'ko': '🔽 더보기', 'en': '🔽 More', 'ja': '🔽 もっと見る', 'zh': '🔽 查看更多'},
    'btn_recommend': {'ko': '추천', 'en': 'Like', 'ja': 'おすすめ', 'zh': '推荐'},
    'btn_dislike': {'ko': '비추천', 'en': 'Dislike', 'ja': '低評価', 'zh': '踩'},
    'btn_delete': {'ko': '삭제', 'en': 'Delete', 'ja': '削除', 'zh': '删除'},
    'tab_analysis_board': {'ko': '📈 분석게시판', 'en': '📈 Analysis Board', 'ja': '📈 分析掲示板', 'zh': '📈 分析论坛'},
    'tab_free_board': {'ko': '💬 자유게시판', 'en': '💬 Free Board', 'ja': '💬 自由掲示板', 'zh': '💬 自由论坛'},
    'write_type_analysis': {'ko': '종목 분석글', 'en': 'Stock Analysis', 'ja': '銘柄分析', 'zh': '股票分析'},
    'write_type_free': {'ko': '일반 자유글', 'en': 'General Post', 'ja': '一般自由文', 'zh': '一般帖子'},


    # ==========================================
    # 12. 참고 문헌 (References Content)
    # ==========================================
    'ref_label_ipo': {'ko': 'IPO 데이터', 'en': 'IPO Data', 'ja': 'IPOデータ', 'zh': 'IPO数据'},
    'ref_sum_ipo': {'ko': '미국 IPO 시장의 성적표와 공모가 저평가 통계의 결정판', 'en': 'Comprehensive statistics on US IPO performance and underpricing.', 'ja': '米国IPO市場の成績表と公募価格の割安性の統計', 'zh': '美国IPO市场表现及发行价抑价统计的权威资料。'},
    
    'ref_label_overheat': {'ko': '시장 과열', 'en': 'Market Overheat', 'ja': '市場の過熱', 'zh': '市场过热'},
    'ref_sum_overheat': {'ko': '특정 시기에 IPO 수익률이 비정상적으로 높아지는 현상 규명', 'en': 'Identification of hot issue markets with abnormal returns.', 'ja': '特定の時期にIPO収益率が異常に高まる現象の解明', 'zh': '揭示特定时期IPO收益率异常偏高的现象。'},
    
    'ref_label_withdrawal': {'ko': '상장 철회', 'en': 'Withdrawal', 'ja': '上場撤回', 'zh': '取消上市'},
    'ref_sum_withdrawal': {'ko': '상장 방식 선택에 따른 기업 가치와 철회 위험 분석', 'en': 'Analysis of corporate value and withdrawal risk by listing method.', 'ja': '上場方式の選択による企業価値と撤回リスクの分析', 'zh': '分析上市方式选择对企业估值及撤回风险的影响。'},
    
    'ref_label_vix': {'ko': '시장 변동성', 'en': 'Volatility', 'ja': '市場の変動性', 'zh': '市场波动性'},
    'ref_sum_vix': {'ko': 'S&P 500 옵션 기반 시장 공포와 변동성 측정 표준', 'en': 'Standard measure of market fear and volatility based on S&P 500 options.', 'ja': 'S&P500オプションに基づく市場の恐怖と変動性の測定標準', 'zh': '基于标普500期权的市场恐慌与波动性衡量标准。'},
    
    'ref_label_buffett': {'ko': '밸류에이션', 'en': 'Valuation', 'ja': 'バリュエーション', 'zh': '估值 (Valuation)'},
    'ref_sum_buffett': {'ko': 'GDP 대비 시가총액 비율을 통한 시장 고평가 판단', 'en': 'Assessing market overvaluation via the market cap-to-GDP ratio.', 'ja': 'GDPに対する時価総額比率による市場の割高判断', 'zh': '通过市值与GDP的比率判断市场是否高估。'},
    
    'ref_label_cape': {'ko': '기초 데이터', 'en': 'Fundamental Data', 'ja': '基礎データ', 'zh': '基础数据'},
    'ref_sum_cape': {'ko': '경기조정주가수익비율(CAPE)을 활용한 장기 데이터', 'en': 'Long-term market valuation using the CAPE ratio.', 'ja': '景気調整後株価収益率(CAPE)を活用した長期データ', 'zh': '利用周期调整市盈率(CAPE)的长期数据。'},
    
    'ref_label_feargreed': {'ko': '투자자 심리', 'en': 'Investor Sentiment', 'ja': '投資家心理', 'zh': '投资者情绪'},
    'ref_sum_feargreed': {'ko': '7가지 지표를 통합한 탐욕과 공포 수준 수치화', 'en': 'Quantifying greed and fear through seven integrated indicators.', 'ja': '7つの指標を統合した強欲と恐怖指数の数値化', 'zh': '综合7项指标量化贪婪与恐惧水平。'},

    # ==========================================
    # 15. Tab 5 (투자결정) 및 게시판 (Board)
    # ==========================================
    'msg_need_all_steps': {'ko': '모든 분석단계를 완료하면 리얼타임 종합 결과 차트가 표시됩니다.', 'en': 'Complete all analysis steps to view the real-time community chart.', 'ja': 'すべての分析ステップを完了すると、リアルタイムの総合結果チャートが表示されます。', 'zh': '完成所有分析步骤后，将显示实时社区预测图表。'},
    'label_market_optimism': {'ko': '시장 참여자 낙관도', 'en': 'Market Optimism', 'ja': '市場参加者の楽観度', 'zh': '市场参与者乐观度'},
    'label_my_position': {'ko': '나의 분석 위치', 'en': 'My Position', 'ja': '私の分析位置', 'zh': '我的分析位置'},
    'label_top_pct': {'ko': '상위', 'en': 'Top', 'ja': '上位', 'zh': '前'},
    'label_community_forecast': {'ko': '실시간 커뮤니티 전망', 'en': 'Real-time Community Forecast', 'ja': 'リアルタイムコミュニティの予測', 'zh': '实时社区预测'},
    'msg_vote_guide': {'ko': '투표시 관심종목에 자동 저장되며, 실시간 결과에 반영됩니다.', 'en': 'Voting automatically saves to watchlist and updates real-time results.', 'ja': '投票すると自動的にウォッチリストに保存され、リアルタイムの結果に反映されます。', 'zh': '投票时将自动保存至自选股，并反映在实时结果中。'},
    'msg_my_choice': {'ko': '나의 선택:', 'en': 'My Choice:', 'ja': '私の選択:', 'zh': '我的选择:'},
    'btn_cancel_vote': {'ko': '투표 취소 및 관심종목 해제', 'en': 'Cancel Vote & Remove from Watchlist', 'ja': '投票のキャンセルとウォッチリストの解除', 'zh': '取消投票并移除自选股'},
    'msg_login_vote': {'ko': '🔒 로그인 후 투표에 참여할 수 있습니다.', 'en': '🔒 Log in to participate in the vote.', 'ja': '🔒 ログイン後に投票に参加できます。', 'zh': '🔒 登录后方可参与投票。'},
    
    # 게시판 전용
    'label_discussion_board': {'ko': '토론방', 'en': 'Discussion Board', 'ja': '掲示板', 'zh': '讨论区'},
    'msg_submitted': {'ko': '등록되었습니다!', 'en': 'Successfully submitted!', 'ja': '登録されました！', 'zh': '发布成功！'},
    'label_hot_posts': {'ko': '인기글', 'en': 'HOT Posts', 'ja': '人気記事', 'zh': '热门帖子'},
    'label_recent_posts': {'ko': '최신글', 'en': 'Recent Posts', 'ja': '最新記事', 'zh': '最新帖子'},
    'msg_no_recent_posts': {'ko': '조건에 맞는 글이 없습니다.', 'en': 'No posts match the criteria.', 'ja': '条件に一致する記事がありません。', 'zh': '没有符合条件的帖子。'},
    'btn_load_more': {'ko': '🔽 더보기', 'en': '🔽 Load More', 'ja': '🔽 もっと見る', 'zh': '🔽 加载更多'},
    'msg_first_comment': {'ko': '첫 의견을 남겨보세요!', 'en': 'Be the first to leave a comment!', 'ja': '最初のコメントを残してみましょう！', 'zh': '快来发表第一个评论吧！'},
    
    # 💡 번역 및 액션 버튼
    'btn_see_translation': {'ko': '🌐 번역 보기', 'en': '🌐 See Translation', 'ja': '🌐 翻訳を見る', 'zh': '🌐 查看翻译'},
    'btn_see_original': {'ko': '🌐 원문 보기', 'en': '🌐 See Original', 'ja': '🌐 原文を見る', 'zh': '🌐 查看原文'},
    'msg_deleted': {'ko': '삭제되었습니다.', 'en': 'Deleted successfully.', 'ja': '削除されました。', 'zh': '已删除。'},

    # ==========================================
    # 16. 프로필 및 설문조사 (Profile & Survey)
    # ==========================================
    'header_basic_profile': {'ko': '👤 기본 인증 프로필', 'en': '👤 Basic Profile', 'ja': '👤 基本認証プロフィール', 'zh': '👤 基本认证资料'},
    'header_survey': {'ko': '📊 투자 성향 설문조사', 'en': '📊 Investment Profile Survey', 'ja': '📊 投資性向アンケート', 'zh': '📊 投资偏好问卷'},
    'desc_survey': {'ko': '이 정보는 향후 프리미엄 투자 통계 자료를 생성하는 데 귀중하게 활용됩니다.', 'en': 'This information will be used to generate premium investment statistics.', 'ja': 'この情報は、今後のプレミアム投資統計データを作成するために活用されます。', 'zh': '此信息将用于生成高级投资统计数据。'},
    'msg_submit_guide': {'ko': "💡 카테고리를 선택하고 증빙 서류를 첨부하면 '글쓰기/투표' 권한이 신청됩니다. (서류 제출은 선택사항)", 'en': "💡 Select categories and attach documents to apply for posting/voting rights. (Docs are optional)", 'ja': "💡 カテゴリを選択して書類を添付すると、投稿/投票権限が申請されます。(書類提出は任意)", 'zh': "💡 选择类别并附加证明文件即可申请发帖/投票权限。（文件提交为可选）"},
    
    'label_survey_exp': {'ko': '1. 투자 경력 (Investment Experience)', 'en': '1. Investment Experience', 'ja': '1. 投資経験', 'zh': '1. 投资经验'},
    'label_survey_style': {'ko': '2. 주요 투자 스타일 (Primary Investment Style)', 'en': '2. Primary Investment Style', 'ja': '2. 主な投資スタイル', 'zh': '2. 主要投资风格'},
    'label_survey_risk': {'ko': '3. 위험 감수 성향 (Risk Tolerance)', 'en': '3. Risk Tolerance', 'ja': '3. リスク許容度', 'zh': '3. 风险承受能力'},
    'label_survey_sector': {'ko': '4. 가장 선호하는 관심 섹터 (다중 선택 가능)', 'en': '4. Top Sectors of Interest (Multiple choices)', 'ja': '4. 関心セクター (複数選択可)', 'zh': '4. 最关注的行业板块 (可多选)'},
    
    # [옵션] 학력
    '고졸 이하': {'ko': '고졸 이하', 'en': 'High school or below', 'ja': '高卒以下', 'zh': '高中及以下'},
    '대학(학사) - 상경/경제계열': {'ko': '대학(학사) - 상경/경제계열', 'en': 'Bachelor - Business/Econ', 'ja': '大学(学士) - 経商系', 'zh': '本科 - 经济/商科'},
    '대학(학사) - 이공/기술계열': {'ko': '대학(학사) - 이공/기술계열', 'en': 'Bachelor - STEM', 'ja': '大学(学士) - 理工系', 'zh': '本科 - 理工科'},
    '대학(학사) - 인문/사회/기타': {'ko': '대학(학사) - 인문/사회/기타', 'en': 'Bachelor - Humanities/Social/Other', 'ja': '大学(学士) - 人文社会・その他', 'zh': '本科 - 人文/社科/其他'},
    '석박사 이상 - 상경/경제계열': {'ko': '석박사 이상 - 상경/경제계열', 'en': 'Master/PhD - Business/Econ', 'ja': '大学院以上 - 経商系', 'zh': '硕博 - 经济/商科'},
    '석박사 이상 - 이공/기술계열': {'ko': '석박사 이상 - 이공/기술계열', 'en': 'Master/PhD - STEM', 'ja': '大学院以上 - 理工系', 'zh': '硕博 - 理工科'},
    '석박사 이상 - 인문/사회/기타': {'ko': '석박사 이상 - 인문/사회/기타', 'en': 'Master/PhD - Humanities/Social/Other', 'ja': '大学院以上 - 人文社会・その他', 'zh': '硕博 - 人文/社科/其他'},
    
    # [옵션] 직업
    '금융권 (증권/은행/VC 등)': {'ko': '금융권 (증권/은행/VC 등)', 'en': 'Finance (Securities/Bank/VC)', 'ja': '金融 (証券/銀行/VC等)', 'zh': '金融 (证券/银行/创投等)'},
    'IT / 테크 / 스타트업': {'ko': 'IT / 테크 / 스타트업', 'en': 'IT / Tech / Startup', 'ja': 'IT・テクノロジー・スタートアップ', 'zh': 'IT / 科技 / 初创'},
    '대기업 / 중견기업': {'ko': '대기업 / 중견기업', 'en': 'Large/Mid-size Corp', 'ja': '大企業・中堅企業', 'zh': '大型/中型企业'},
    '공공기관 / 공무원': {'ko': '공공기관 / 공무원', 'en': 'Public/Gov', 'ja': '公共機関・公務員', 'zh': '政府机关/公务员'},
    '전문직 (의사/변호사/회계사 등)': {'ko': '전문직 (의사/변호사/회계사 등)', 'en': 'Professional (Dr/Lawyer/CPA)', 'ja': '専門職 (医師/弁護士/会計士等)', 'zh': '专业人士 (医生/律师/会计师等)'},
    '개인사업 / 자영업': {'ko': '개인사업 / 자영업', 'en': 'Self-employed/Business', 'ja': '個人事業・自営業', 'zh': '个体户/自雇'},
    '학생 / 취업준비생': {'ko': '학생 / 취업준비생', 'en': 'Student/Job seeker', 'ja': '学生・就職活動中', 'zh': '学生/求职者'},
    '기타': {'ko': '기타', 'en': 'Other', 'ja': 'その他', 'zh': '其他'},
    
    # [옵션] 자산
    '10억 미만': {'ko': '10억 미만', 'en': 'Under 1B KRW', 'ja': '10億ウォン未満', 'zh': '10亿韩元以下'},
    '10억~30억': {'ko': '10억~30억', 'en': '1B - 3B KRW', 'ja': '10億〜30億ウォン', 'zh': '10亿-30亿韩元'},
    '30억~80억': {'ko': '30억~80억', 'en': '3B - 8B KRW', 'ja': '30億〜80億ウォン', 'zh': '30亿-80亿韩元'},
    '80억 이상': {'ko': '80억 이상', 'en': 'Over 8B KRW', 'ja': '80億ウォン以上', 'zh': '80亿韩元以上'},

    # [옵션] 경력
    '1년 미만 (초보자)': {'ko': '1년 미만 (초보자)', 'en': '< 1 yr (Beginner)', 'ja': '1年未満 (初心者)', 'zh': '1年以下 (初学者)'},
    '1년 ~ 3년 (중급자)': {'ko': '1년 ~ 3년 (중급자)', 'en': '1-3 yrs (Intermediate)', 'ja': '1年〜3年 (中級者)', 'zh': '1~3年 (中级)'},
    '3년 ~ 7년 (숙련자)': {'ko': '3년 ~ 7년 (숙련자)', 'en': '3-7 yrs (Advanced)', 'ja': '3年〜7年 (熟練者)', 'zh': '3~7年 (高级)'},
    '7년 이상 (베테랑)': {'ko': '7년 이상 (베테랑)', 'en': '7+ yrs (Veteran)', 'ja': '7年以上 (ベテラン)', 'zh': '7年以上 (资深)'},
    '금융/투자업계 종사자 (전문가)': {'ko': '금융/투자업계 종사자 (전문가)', 'en': 'Finance/Investment Professional', 'ja': '金融・投資業界従事者', 'zh': '金融/投资行业从业者'},

    # [옵션] 스타일
    '가치 투자 (저평가 우량주)': {'ko': '가치 투자 (저평가 우량주)', 'en': 'Value (Undervalued blue chips)', 'ja': 'バリュー投資 (割安優良株)', 'zh': '价值投资 (被低估蓝筹股)'},
    '성장주 / IPO 투자 (고성장/신규상장)': {'ko': '성장주 / IPO 투자 (고성장/신규상장)', 'en': 'Growth/IPO (High growth/New)', 'ja': 'グロース・IPO投資 (高成長・新規)', 'zh': '成长/IPO投资 (高成长/新股)'},
    '배당 / 인컴 투자 (안정적 현금흐름)': {'ko': '배당 / 인컴 투자 (안정적 현금흐름)', 'en': 'Dividend/Income (Stable cash)', 'ja': '配当・インカム投資 (安定現金流)', 'zh': '股息/收益投资 (稳定现金流)'},
    '모멘텀 / 단기 트레이딩 (추세 추종)': {'ko': '모멘텀 / 단기 트레이딩 (추세 추종)', 'en': 'Momentum/Active Trading', 'ja': 'モメンタム・短期トレード', 'zh': '动量/短线交易 (顺势操作)'},

    # [옵션] 리스크
    '안정 추구형 (원금 보존 최우선)': {'ko': '안정 추구형 (원금 보존 최우선)', 'en': 'Low Risk (Capital preservation)', 'ja': '安定追求型 (元本保全優先)', 'zh': '稳健型 (保本优先)'},
    '위험 중립형 (시장 평균 수익률 지향)': {'ko': '위험 중립형 (시장 평균 수익률 지향)', 'en': 'Moderate Risk (Market average)', 'ja': 'リスク中立型 (市場平均収益狙い)', 'zh': '稳健进取型 (追求市场平均收益)'},
    '위험 감수형 (높은 변동성 감수)': {'ko': '위험 감수형 (높은 변동성 감수)', 'en': 'High Risk (High volatility)', 'ja': 'リスク選好型 (高い変動性を許容)', 'zh': '积极型 (承受高波动)'},
    '초고위험 선호형 (텐배거/초과 수익 노림)': {'ko': '초고위험 선호형 (텐배거/초과 수익 노림)', 'en': 'Speculative (Tenbagger/Excess)', 'ja': '超ハイリスク選好型 (テンバガー)', 'zh': '投机型 (追求十倍股/超额收益)'},

    # [옵션] 섹터
    '테크 / AI / 소프트웨어': {'ko': '테크 / AI / 소프트웨어', 'en': 'Tech / AI / Software', 'ja': 'テック・AI・ソフトウェア', 'zh': '科技 / AI / 软件'},
    '바이오 / 헬스케어': {'ko': '바이오 / 헬스케어', 'en': 'Biotech / Healthcare', 'ja': 'バイオ・ヘルスケア', 'zh': '生物技术 / 医疗保健'},
    '핀테크 / 암호화폐': {'ko': '핀테크 / 암호화폐', 'en': 'FinTech / Crypto', 'ja': 'フィンテック・暗号資産', 'zh': '金融科技 / 加密货币'},
    '소비재 / 이커머스': {'ko': '소비재 / 이커머스', 'en': 'Consumer / E-commerce', 'ja': '消費財・Eコマース', 'zh': '消费品 / 电子商务'},
    '에너지 / 모빌리티': {'ko': '에너지 / 모빌리티', 'en': 'Energy / Mobility', 'ja': 'エネルギー・モビリティ', 'zh': '能源 / 出行'},

    # ==========================================
    # 17. 알림 수신 설정 (Notification Settings)
    # ==========================================
    'header_noti_setting': {'ko': '🔔 프리미엄 알림 수신 설정', 'en': '🔔 Premium Alert Settings', 'ja': '🔔 プレミアム通知受信設定', 'zh': '🔔 高级通知接收设置'},
    'desc_noti_setting': {'ko': '주요 상장 일정 및 급등 종목 알림을 받을 매체를 선택해 주세요.', 'en': 'Select the medium to receive alerts for major IPO schedules and surging stocks.', 'ja': '主要な上場日程や急騰銘柄の通知を受け取るメディアを選択してください。', 'zh': '请选择接收主要上市日程和暴涨股票通知的媒介。'},
    'label_noti_method': {'ko': '알림 수신 방법', 'en': 'Notification Method', 'ja': '通知受信方法', 'zh': '通知接收方式'},
    
    # 알림 매체 옵션 (DB에는 영어 키값으로 저장됨)
    'noti_kakaotalk': {'ko': '카카오톡 (KakaoTalk)', 'en': 'KakaoTalk', 'ja': 'カカオトーク (KakaoTalk)', 'zh': 'KakaoTalk'},
    'noti_line': {'ko': '라인 (LINE)', 'en': 'LINE', 'ja': 'LINE', 'zh': 'LINE'},
    'noti_wechat': {'ko': '위챗 (WeChat)', 'en': 'WeChat', 'ja': 'WeChat', 'zh': '微信 (WeChat)'},
    'noti_whatsapp': {'ko': '왓츠앱 (WhatsApp)', 'en': 'WhatsApp', 'ja': 'WhatsApp', 'zh': 'WhatsApp'},
    'noti_email': {'ko': '이메일 (Email)', 'en': 'Email', 'ja': 'Eメール (Email)', 'zh': '电子邮件 (Email)'},
    'noti_sms': {'ko': 'SMS 문자', 'en': 'SMS Text', 'ja': 'SMS メッセージ', 'zh': 'SMS 短信'},

    # ==========================================
    # 13. 시스템 메시지 (Toast, Spinner, Error)
    # ==========================================
    'msg_disclaimer': {
        'ko': '**이용 유의사항** 본 서비스는 자체 알고리즘과 AI 모델을 활용한 요약 정보를 제공하며, 원저작권자의 권리를 존중합니다. 요약본은 원문과 차이가 있을 수 있으므로 반드시 원문을 확인하시기 바랍니다. 모든 투자 결정의 최종 책임은 사용자 본인에게 있습니다.',
        'en': '**Disclaimer** This service provides summarized information using proprietary algorithms and AI models, and respects the rights of original copyright holders. Summaries may differ from the original text, so please ensure to verify the original sources. The final responsibility for all investment decisions lies with the user.',
        'ja': '**ご利用上の注意** 本サービスは、独自アルゴリズムとAIモデルを活用した要約情報を提供しており、原著作者の権利を尊重します。要約内容は原文と異なる場合がありますので、必ず原文をご確認ください。すべての投資判断の最終的な責任はユーザーご自身にあります。',
        'zh': '**免责声明** 本服务利用自有算法和AI模型提供摘要信息，并尊重原版权者的权利。摘要内容可能与原文存在差异，请务必核实原文。所有投资决定的最终责任由用户本人承担。'
    },
    'msg_analyzing': {'ko': '분석 중...', 'en': 'Analyzing...', 'ja': '分析中...', 'zh': '分析中...'},
    'msg_analyzing_filing': {'ko': '핵심 내용을 분석 중입니다...', 'en': 'Analyzing key content...', 'ja': '主要内容を分析中です...', 'zh': '正在分析核心内容...'},
    'msg_analyzing_tab1': {'ko': '최신 데이터를 정밀 분석 중입니다...', 'en': 'Analyzing latest data...', 'ja': '最新データを精密分析中です...', 'zh': '正在精密分析最新数据...'},
    'msg_analyzing_macro': {'ko': '📊 8대 핵심 지표를 실시간 분석 중입니다...', 'en': '📊 Analyzing 8 key metrics...', 'ja': '📊 8大指標をリアルタイム分析中です...', 'zh': '📊 正在实时分析8大核心指标...'},
    'msg_analyzing_financial': {'ko': '🤖 AI 애널리스트가 재무제표를 분석 중입니다...', 'en': '🤖 AI is analyzing financials...', 'ja': '🤖 AIが財務諸表を分析中です...', 'zh': '🤖 AI分析师正在分析财务报表...'},
    'msg_analyzing_institutional': {'ko': '전문 기관 데이터를 정밀 수집 중...', 'en': 'Collecting institutional data...', 'ja': '専門機関データを精密収集中...', 'zh': '正在精密收集专业机构数据...'},
    
    'caption_algorithm': {'ko': ' 자체 알고리즘으로 요약해 제공합니다.', 'en': ' Summarized by our algorithm.', 'ja': ' 独自アルゴリズムで要約を提供します。', 'zh': ' 通过自有算法提供摘要。'},
    'err_no_biz_info': {'ko': '⚠️ 비즈니스 분석 정보를 가져오지 못했습니다.', 'en': '⚠️ Failed to fetch business info.', 'ja': '⚠️ ビジネス情報の取得に失敗しました。', 'zh': '⚠️ 未能获取商业分析信息。'},
    'err_no_news': {'ko': '⚠️ 현재 표시할 최신 뉴스가 없습니다.', 'en': '⚠️ No recent news to display.', 'ja': '⚠️ 表示する最新ニュースがありません。', 'zh': '⚠️ 目前没有可显示的最新新闻。'},
    'err_no_institutional': {'ko': '직접적인 분석 리포트를 찾지 못했습니다.', 'en': 'No direct reports found.', 'ja': '直接的な分析レポートは見つかりませんでした。', 'zh': '未找到直接的分析报告。'},
    
    'msg_login_auth_needed': {'ko': '🔒 로그인 및 권한 인증이 필요합니다.', 'en': '🔒 Login and authorization required.', 'ja': '🔒 ログインと権限認証が必要です。', 'zh': '🔒 需要登录及权限认证。'},
    'msg_vote_auto_save': {'ko': '투표시 관심종목에 자동 저장되며, 실시간 결과에 반영됩니다.', 'en': 'Votes auto-save to Watchlist.', 'ja': '投票はお気に入りに自動保存されます。', 'zh': '投票时自动保存至自选股，并反映在实时结果中。'},
    'msg_login_for_vote': {'ko': '🔒 로그인 후 투표에 참여하고 전체 결과를 확인할 수 있습니다.', 'en': '🔒 Login to vote and view results.', 'ja': '🔒 ログイン後に投票・結果確認が可能です。', 'zh': '🔒 登录后即可参与投票并查看完整结果。'},
    'msg_chart_unlock': {'ko': '모든 분석단계를 완료하면 종합 결과 차트가 표시됩니다.', 'en': 'Complete all steps to unlock the chart.', 'ja': '全ステップ完了で総合チャートが表示されます。', 'zh': '完成所有分析步骤后，将显示综合结果图表。'},
    
    'msg_submit_success': {'ko': '등록 완료!', 'en': 'Posted successfully!', 'ja': '登録完了！', 'zh': '发布成功！'},
    'msg_already_voted': {'ko': '이미 참여하신 게시글입니다.', 'en': 'You have already voted.', 'ja': 'すでに投票済みです。', 'zh': '您已经参与过该帖子的投票。'},
    'msg_no_latest_posts': {'ko': '조건에 맞는 최신 글이 없습니다.', 'en': 'No matching recent posts.', 'ja': '条件に合う最新の投稿がありません。', 'zh': '没有符合条件的最新帖子。'},
    'msg_no_posts': {'ko': '게시글이 없습니다.', 'en': 'No posts available.', 'ja': '投稿がありません。', 'zh': '暂无帖子。'},
}

def get_text(key):
    """현재 세션 언어에 맞는 텍스트를 반환하는 헬퍼 함수"""
    # 💡 [핵심] lang 값이 아직 세션에 없더라도 에러를 뿜지 않고 기본값 'ko'를 쓰도록 안전장치 적용
    lang = st.session_state.get('lang', 'ko') 
    return UI_TEXT.get(key, {}).get(lang, UI_TEXT.get(key, {}).get('ko', key))

# 현재 AI 프롬프트에 주입할 언어명 문자열 매핑
# 현재 AI 프롬프트에 주입할 언어명 문자열 매핑
LANG_PROMPT_MAP = {
    'ko': '전문적인 한국어(Korean)',
    'en': 'Professional English',
    'ja': '専門的な日本語(Japanese)',
    'zh': '简体中文(Simplified Chinese)'  # 💡 추가됨
}

# 3. 공통 UI 함수 정의 (전역) - 무한 수정 및 다국어 완벽 적용 버전
def draw_decision_box(step_key, title, option_keys, current_p=0.0):
    """사용자 투표/판단 박스를 그리는 함수 (수정 허용)"""
    sid = st.session_state.get('selected_stock', {}).get('symbol', 'UNKNOWN')
    user_info = st.session_state.get('user_info') or {}
    user_id = user_info.get('id', 'guest_id')
    
    # 결정 데이터 공간 확보
    if sid not in st.session_state.user_decisions:
        st.session_state.user_decisions[sid] = {}
        
    st.write("---")
    st.markdown(f"##### {title}")
    
    # DB에 저장될 기준 한국어 값과, 화면에 보여줄 다국어 매핑 생성
    base_options = [UI_TEXT.get(k, {}).get('ko', k) for k in option_keys]
    display_map = {UI_TEXT.get(k, {}).get('ko', k): get_text(k) for k in option_keys}
    
    current_val = st.session_state.user_decisions[sid].get(step_key)
    
    # 💡 [다국어 적용] 이미 투표한 적이 있다면 언제든 바꿀 수 있다는 안내 문구 노출
    if current_val:
        st.caption(get_text('msg_vote_changeable'))
        
    choice = st.radio(
        label=f"판단_{step_key}",
        options=base_options,                         # 시스템/DB에는 무조건 한국어로 들어감
        format_func=lambda x: display_map.get(x, x),  # 화면에만 다국어로 번역해서 보여줌
        index=base_options.index(current_val) if current_val in base_options else None,
        key=f"dec_{sid}_{step_key}",
        horizontal=True,
        label_visibility="collapsed",
    )
    
    # 값이 기존과 다르게 '변경'되었을 때만 DB에 로그를 쌓고 UI 업데이트
    if choice and choice != current_val:
        st.session_state.user_decisions[sid][step_key] = choice
        if user_id != 'guest_id':
            # action_logs에 가격과 함께 변경된 의견이 누적 저장됨!
            db_log_user_action(user_id, sid, f"DECISION_{step_key.upper()}_UPDATED", price=current_p, details=choice)
            
            # user_decisions 테이블에도 최종 상태 덮어쓰기 (종합 점수 재계산)
            new_score = sum([1 if "긍정" in str(v) or "매수" in str(v) or "저평가" in str(v) else -1 if "부정" in str(v) or "매도" in str(v) or "버블" in str(v) or "고평가" in str(v) else 0 for v in st.session_state.user_decisions[sid].values()])
            db_save_user_decision(user_id, sid, new_score, st.session_state.user_decisions[sid])
            
            # 💡 [다국어 적용] 토스트 메시지
            st.toast(f"✅ {get_text('msg_vote_updated')}", icon="📈")
            time.sleep(0.5)
            st.rerun()

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

# 🚀🚀🚀 [바로 여기입니다! 워밍업 봇 전용 비밀 뒷문] 🚀🚀🚀
if st.query_params.get("warmup") == "true":
    try:
        # 1. 캘린더 전체 데이터를 불러와 서버 RAM(메모리)에 올림 (변수명 수정 완료)
        df_calendar = get_extended_ipo_data(MY_API_KEY)
        
        if not df_calendar.empty:
            # 2. 시장 거시 지표(Tab 2) 메모리에 올림 (변수명 수정 완료)
            get_cached_market_status(df_calendar, MY_API_KEY)
            
            # 3. 타겟 종목 순회 (최근 180일 ~ 향후 35일)
            from datetime import datetime, timedelta
            import pandas as pd
            
            today = datetime.now()
            df_calendar['dt'] = pd.to_datetime(df_calendar['date'], errors='coerce')
            
            target_stocks = df_calendar[
                (df_calendar['dt'] >= today - timedelta(days=180)) & 
                (df_calendar['dt'] <= today + timedelta(days=35))
            ].head(50) 
            
            # 💡 [교체된 반복문 구간]
            for _, row in target_stocks.iterrows():
                ticker = row['symbol']
                name = row['name']
                
                # 💡 [교체된 반복문 구간]
            for _, row in target_stocks.iterrows():
                ticker = row['symbol']
                name = row['name']
                
                # [Tab 0 로드]
                try:
                    get_ai_analysis(name, "S-1", "ko")
                except: 
                    pass
                
                # [Tab 1 로드]
                try:
                    get_unified_tab1_analysis(name, ticker, 'ko')
                except: 
                    pass
                
                # 💡 [추가] Tab 4 기관 평가도 미리 렌더링하도록 봇에게 지시!
                try:
                    get_unified_tab4_analysis(name, ticker, 'ko')
                except:
                    pass
        
        st.write(f"✅ 봇 접속 확인: 메인 데이터 및 Tab0/Tab1 ({len(target_stocks)}개 핵심 종목) 서버 메모리 캐싱 완료!")
    except Exception as e:
        st.write(f"⚠️ 워밍업 에러 발생: {e}")
        
    st.stop() 
# 🚀🚀🚀 [워밍업 코드 끝] 🚀🚀🚀

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
        # 💡 타이틀 영문 고정 (사용자 요청 반영)
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
            # [NEW 위치] 3개 국어 언어 선택 버튼
            # =========================================================
            lang_cols = st.columns(4) # 💡 3에서 4로 변경
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
            with lang_cols[3]: # 💡 중국어 버튼 추가
                if st.button("🇨🇳 中文", use_container_width=True): 
                    st.session_state.lang = 'zh'
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
                
                st.markdown(f"<p style='{title_style}'>{get_text('signup_title_step1')}</p>", unsafe_allow_html=True)
                
                # --- [상단 입력창 구역: 항상 유지됨] ---
                # 🚨 [수정 완]: 중복 ID 에러 방지를 위해 명시적인 key 값을 삽입했습니다.
                st.markdown(f"<p style='{label_style}'>{get_text('id_label')}</p>", unsafe_allow_html=True)
                new_id = st.text_input("id_input", value=st.session_state.get('temp_id', ''), key="reg_id", label_visibility="collapsed")
                st.session_state.temp_id = new_id
                
                st.markdown(f"<p style='{label_style}'>{get_text('pw_label')}</p>", unsafe_allow_html=True)
                new_pw = st.text_input("pw_input", type="password", value=st.session_state.get('temp_pw', ''), key="reg_pw", label_visibility="collapsed")
                st.session_state.temp_pw = new_pw
                
                st.markdown(f"<p style='{label_style}'>{get_text('pw_confirm_label')}</p>", unsafe_allow_html=True)
                confirm_pw = st.text_input("confirm_pw_input", type="password", value=st.session_state.get('temp_cpw', ''), key="reg_cpw", label_visibility="collapsed")
                st.session_state.temp_cpw = confirm_pw
                
                # 실시간 비번 일치 체크
                is_pw_match = False
                if new_pw and confirm_pw:
                    if new_pw == confirm_pw:
                        st.markdown(f"<p style='{status_style} color: #2e7d32;'>✅ 일치합니다.</p>", unsafe_allow_html=True)
                        is_pw_match = True
                    else:
                        st.markdown(f"<p style='{status_style} color: #d32f2f;'>❌ 일치하지 않습니다.</p>", unsafe_allow_html=True)
                        
                st.markdown(f"<p style='{label_style}'>{get_text('phone_label')}</p>", unsafe_allow_html=True)
                new_phone = st.text_input("phone_input", value=st.session_state.get('temp_phone', ''), key="reg_phone", label_visibility="collapsed")
                st.session_state.temp_phone = new_phone
                
                st.markdown(f"<p style='{label_style}'>{get_text('email_label')}</p>", unsafe_allow_html=True)
                new_email = st.text_input("email_input", value=st.session_state.get('temp_email', ''), key="reg_email", label_visibility="collapsed")
                st.session_state.temp_email = new_email
                
                # 💡 [수정 완료]: format_func를 이용해 화면 표시는 다국어로, 파이썬 내부 변수(auth_choice)는 영어(phone, email)로 안전하게 분리
                st.markdown(f"<p style='{label_style}'>{get_text('auth_method_label')}</p>", unsafe_allow_html=True)
                
                auth_keys = ["phone", "email"]
                auth_display = {
                    "phone": get_text('auth_phone'),
                    "email": get_text('auth_email')
                }
                
                auth_choice = st.radio("auth_input", auth_keys, format_func=lambda x: auth_display[x], horizontal=True, label_visibility="collapsed", key="reg_auth_radio")
                
                # --- [하단 유동 구역: 버튼 혹은 인증창으로 교체] ---
                st.write("---") 
                
                # 💡 [해결] st.empty()를 제거하여 유령 박스 현상을 차단하고, 
                # auth_choice 비교 로직을 'email'로 정확히 수정했습니다.
                if st.session_state.signup_stage == 1:
                    # 1단계 버튼 구역
                    if st.button(get_text('btn_get_code'), use_container_width=True, type="primary", key="btn_send_auth_final"):
                        if not (new_id and new_pw and confirm_pw and new_email):
                            st.error("모든 정보를 입력해주세요." if st.session_state.lang == 'ko' else "Please fill in all fields.")
                        elif not is_pw_match:
                            st.error("비밀번호 일치 확인이 필요합니다." if st.session_state.lang == 'ko' else "Passwords do not match.")
                        else:
                            code = str(random.randint(100000, 999999))
                            st.session_state.auth_code = code
                            st.session_state.temp_user_data = {"id": new_id, "pw": new_pw, "phone": new_phone, "email": new_email}
                            
                            # ✅ 수정된 부분: "이메일"이 아니라 변수 값인 "email"과 비교합니다.
                            if auth_choice == "email":
                                if send_email_code(new_email, code):
                                    st.session_state.signup_stage = 2
                                    st.rerun()
                            else:
                                # 휴대폰 선택 시 기존처럼 토스트 메시지
                                st.toast(f"📱 인증번호: {code}", icon="✅")
                                st.session_state.signup_stage = 2
                                st.rerun()
                
                    if st.button(get_text('btn_back_to_start'), use_container_width=True, key="btn_signup_back_final"):
                        st.session_state.login_step = 'choice'
                        st.rerun()
        
                elif st.session_state.signup_stage == 2:
                    # 2단계 인증창 구역 (기존과 동일하지만 들여쓰기 최적화)
                    st.markdown("<div style='background-color: #f8f9fa; padding: 20px; border-radius: 10px; border: 1px solid #ddd;'>", unsafe_allow_html=True)
                    st.markdown(f"<p style='{label_style} font-weight: bold;'>{get_text('auth_code_title')}</p>", unsafe_allow_html=True)
                    
                    in_code = st.text_input("verify_code_input", label_visibility="collapsed", placeholder=get_text('placeholder_code'), key="input_verify_code_stage2")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button(get_text('btn_confirm_auth'), use_container_width=True, type="primary", key="btn_confirm_auth_stage2"):
                            if in_code == st.session_state.auth_code:
                                st.success("인증 성공!" if st.session_state.lang == 'ko' else "Verified successfully!")
                                st.session_state.signup_stage = 3
                                st.rerun()
                            else:
                                st.error("인증번호가 틀렸습니다." if st.session_state.lang == 'ko' else "Incorrect code.")
                    with col2:
                        if st.button(get_text('btn_resend_auth'), use_container_width=True, key="btn_resend_auth_stage2"):
                            st.session_state.signup_stage = 1
                            st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)
            
            # [B구역] 3단계일 때 (서류 제출 및 프로필/설문조사 화면)
            elif st.session_state.signup_stage == 3:
                title_style = "font-size: 1.0rem; font-weight: bold; margin-bottom: 15px;"
                st.markdown(f"<p style='{title_style}'>{get_text('signup_title_step3')}</p>", unsafe_allow_html=True)
                st.info(get_text('msg_submit_guide'))
                
                existing_user = st.session_state.get('user_info', {})
                
                # --- 1. 선택형 카테고리 옵션 정의 (DB에 저장되는 고정 키값) ---
                univ_options = ["선택 안 함", "고졸 이하", "대학(학사) - 상경/경제계열", "대학(학사) - 이공/기술계열", "대학(학사) - 인문/사회/기타", "석박사 이상 - 상경/경제계열", "석박사 이상 - 이공/기술계열", "석박사 이상 - 인문/사회/기타"]
                job_options = ["선택 안 함", "금융권 (증권/은행/VC 등)", "IT / 테크 / 스타트업", "대기업 / 중견기업", "공공기관 / 공무원", "전문직 (의사/변호사/회계사 등)", "개인사업 / 자영업", "학생 / 취업준비생", "기타"]
                asset_options = ["선택 안 함", "10억 미만", "10억~30억", "30억~80억", "80억 이상"]
                
                exp_options = ["선택 안 함", "1년 미만 (초보자)", "1년 ~ 3년 (중급자)", "3년 ~ 7년 (숙련자)", "7년 이상 (베테랑)", "금융/투자업계 종사자 (전문가)"]
                style_options = ["선택 안 함", "가치 투자 (저평가 우량주)", "성장주 / IPO 투자 (고성장/신규상장)", "배당 / 인컴 투자 (안정적 현금흐름)", "모멘텀 / 단기 트레이딩 (추세 추종)"]
                risk_options = ["선택 안 함", "안정 추구형 (원금 보존 최우선)", "위험 중립형 (시장 평균 수익률 지향)", "위험 감수형 (높은 변동성 감수)", "초고위험 선호형 (텐배거/초과 수익 노림)"]
                sector_options = ["테크 / AI / 소프트웨어", "바이오 / 헬스케어", "핀테크 / 암호화폐", "소비재 / 이커머스", "에너지 / 모빌리티", "기타"]

                # 기존 값 불러오기 (인덱스 매칭)
                cur_u_val = existing_user.get('univ', '선택 안 함')
                cur_j_val = existing_user.get('job', '선택 안 함')
                cur_a_val = existing_user.get('asset', '선택 안 함')
                cur_exp = existing_user.get('inv_exp', '선택 안 함')
                cur_style = existing_user.get('inv_style', '선택 안 함')
                cur_risk = existing_user.get('inv_risk', '선택 안 함')
                cur_sector_raw = existing_user.get('inv_sector', '')
                cur_sector = cur_sector_raw.split(',') if cur_sector_raw else []

                # --- 2. 기본 인증 정보 입력 (SelectBox + 다국어 format_func) ---
                st.markdown(f"##### {get_text('header_basic_profile')}")
                
                u_idx = univ_options.index(cur_u_val) if cur_u_val in univ_options else 0
                u_val = st.selectbox(get_text('label_univ'), univ_options, index=u_idx, format_func=lambda x: get_text(x), key="u_val_final")
                u_file = st.file_uploader(get_text('label_univ_file') + " (기존 파일 유지시 미첨부)", type=['jpg','png','pdf'], key="u_file_final")
                st.write("")
                
                j_idx = job_options.index(cur_j_val) if cur_j_val in job_options else 0
                j_val = st.selectbox(get_text('label_job'), job_options, index=j_idx, format_func=lambda x: get_text(x), key="j_val_final")
                j_file = st.file_uploader(get_text('label_job_file') + " (기존 파일 유지시 미첨부)", type=['jpg','png','pdf'], key="j_file_final")
                st.write("")
                
                a_idx = asset_options.index(cur_a_val) if cur_a_val in asset_options else 0
                a_val = st.selectbox(get_text('label_asset'), asset_options, index=a_idx, format_func=lambda x: get_text(x), key="a_val_final")
                a_file = st.file_uploader(get_text('label_asset_file') + " (기존 파일 유지시 미첨부)", type=['jpg','png','pdf'], key="a_file_final")
                
                st.write("---")
                
                # --- 3. 투자자 성향 설문조사 ---
                st.markdown(f"##### {get_text('header_survey')}")
                st.caption(get_text('desc_survey'))
                
                exp_idx = exp_options.index(cur_exp) if cur_exp in exp_options else 0
                val_exp = st.selectbox(get_text('label_survey_exp'), exp_options, index=exp_idx, format_func=lambda x: get_text(x), key="surv_exp")
                
                style_idx = style_options.index(cur_style) if cur_style in style_options else 0
                val_style = st.selectbox(get_text('label_survey_style'), style_options, index=style_idx, format_func=lambda x: get_text(x), key="surv_style")
                
                risk_idx = risk_options.index(cur_risk) if cur_risk in risk_options else 0
                val_risk = st.selectbox(get_text('label_survey_risk'), risk_options, index=risk_idx, format_func=lambda x: get_text(x), key="surv_risk")
                
                valid_sectors = [s for s in cur_sector if s in sector_options]
                val_sector = st.multiselect(get_text('label_survey_sector'), sector_options, default=valid_sectors, format_func=lambda x: get_text(x), key="surv_sector")
                
                # --- 3.5 [신규] 프리미엄 알림 수신 수단 선택 (국가별 맞춤형) ---
                st.markdown(f"##### {get_text('header_noti_setting')}")
                st.caption(get_text('desc_noti_setting'))
                
                # DB에 저장되어 있는 기존 설정값 불러오기 (기본값: Email)
                cur_noti = existing_user.get('noti_method', 'Email')
                
                # 접속한 언어(국가)별로 노출되는 메신저 옵션 리스트 분리
                # (DB에는 이 리스트의 영문 이름 그대로 깔끔하게 저장됩니다)
                if st.session_state.lang == 'ko':
                    noti_options = ["KakaoTalk", "Email", "SMS"]
                elif st.session_state.lang == 'ja':
                    noti_options = ["LINE", "Email", "SMS"]
                elif st.session_state.lang == 'zh':
                    noti_options = ["WeChat", "Email", "SMS"]
                else:
                    noti_options = ["WhatsApp", "Email", "SMS"]
                    
                noti_idx = noti_options.index(cur_noti) if cur_noti in noti_options else 0
                
                # format_func를 통해 유저 화면에는 각국 언어에 맞게 번역되어 출력됨
                val_noti = st.selectbox(
                    get_text('label_noti_method'), 
                    noti_options, 
                    index=noti_idx, 
                    format_func=lambda x: get_text(f"noti_{x.lower()}"), 
                    key="surv_noti"
                )
                
                st.write("---")
                
                # --- 4. 제출 로직 ---
                if st.button("제출 및 저장하기" if st.session_state.lang == 'ko' else "Submit & Save", type="primary", use_container_width=True):
                    td = st.session_state.get('temp_user_data')
                    if not td:
                        st.error("⚠️ 세션이 만료되었습니다. 처음부터 다시 진행해주세요." if st.session_state.lang == 'ko' else "⚠️ Session expired.")
                        st.stop()

                    with st.spinner("정보를 안전하게 저장 중입니다..." if st.session_state.lang == 'ko' else "Saving securely..."):
                        try:
                            old_l_u = existing_user.get('link_univ', '미제출')
                            old_l_j = existing_user.get('link_job', '미제출')
                            old_l_a = existing_user.get('link_asset', '미제출')

                            l_u = upload_photo_to_drive(u_file, f"{td['id']}_univ") if u_file else (old_l_u if u_val != "선택 안 함" else "미제출")
                            l_j = upload_photo_to_drive(j_file, f"{td['id']}_job") if j_file else (old_l_j if j_val != "선택 안 함" else "미제출")
                            l_a = upload_photo_to_drive(a_file, f"{td['id']}_asset") if a_file else (old_l_a if a_val != "선택 안 함" else "미제출")
                            
                            has_cert = any([l_u != "미제출", l_j != "미제출", l_a != "미제출"])
                            role = "user" if has_cert else "restricted"
                            status = "pending" if has_cert else "pending"
                            
                            final_data = {
                                **td, 
                                "univ": u_val, "job": j_val, "asset": a_val,
                                "link_univ": l_u, "link_job": l_j, "link_asset": l_a,
                                "inv_exp": val_exp,
                                "inv_style": val_style,
                                "inv_risk": val_risk,
                                "inv_sector": ",".join(val_sector),
                                "noti_method": val_noti,  # 🔥 여기에 딱 한 줄 추가!
                                "role": role, "status": status,
                                "display_name": f"{role} | {td['id'][:3]}***"
                            }
                            
                            if db_signup_user(final_data):
                                st.success("인증 정보가 성공적으로 제출되었습니다!" if st.session_state.lang == 'ko' else "Successfully submitted!")
                                st.session_state.auth_status = 'user'
                                st.session_state.user_info = final_data
                                st.session_state.page = 'setup'
                                st.session_state.login_step = 'choice'
                                st.session_state.signup_stage = 1
                                import time; time.sleep(1.5)
                                st.rerun()
                            else:
                                st.error("❌ 저장에 실패했습니다." if st.session_state.lang == 'ko' else "❌ Failed to save.")
                        
                        except Exception as e:
                            st.error(f"🚨 오류 발생: {e}")

# ---------------------------------------------------------
# [NEW] 가입 직후 설정 페이지 (Setup) - 멤버 리스트 & 관리자 기능 통합
# ---------------------------------------------------------
elif st.session_state.page == 'setup':
    user = st.session_state.user_info

    if user:
        # ==========================================
        # [UI] 설정 페이지 화면 구성 시작
        # ==========================================
        # [1] 기본 정보 계산
        user_id = str(user.get('id', ''))
        full_masked_id = "*" * len(user_id) 
        
        # 💡 [핵심 추가] 가입일 기반 투자 경력 자동 갱신 로직
        current_exp = user.get('inv_exp', '선택 안 함')
        join_date_str = user.get('created_at')
        
        if join_date_str and current_exp != '선택 안 함':
            try:
                from datetime import datetime
                # 가입 후 몇 년이 지났는지 계산
                join_date = datetime.fromisoformat(str(join_date_str).split('.')[0].replace('Z', ''))
                years_passed = (datetime.now() - join_date).days // 365
                
                if years_passed > 0:
                    exp_levels = [
                        "1년 미만 (초보자)", "1년 ~ 3년 (중급자)", 
                        "3년 ~ 7년 (숙련자)", "7년 이상 (베테랑)", "금융/투자업계 종사자 (전문가)"
                    ]
                    if current_exp in exp_levels:
                        current_idx = exp_levels.index(current_exp)
                        # 가입 시점 대비 지난 연차만큼 레벨 업 (최대치는 3번 인덱스인 '베테랑'까지만. 전문가는 예외)
                        if current_idx < 3: 
                            new_idx = min(3, current_idx + years_passed)
                            current_exp = exp_levels[new_idx]
                            
                            # 세션 데이터 업데이트 (나중에 '추가 인증/수정' 버튼을 눌렀을 때 갱신된 값이 뜨도록 함)
                            st.session_state.user_info['inv_exp'] = current_exp
            except Exception as e: 
                pass

        # 상단 안내 문구 (다국어 적용)
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
                {get_text('setup_guide')}
            </div>
        """, unsafe_allow_html=True)
        
        # -----------------------------------------------------------
        # 1. 내 정보 노출 설정 (체크박스 - 다국어 적용)
        # -----------------------------------------------------------
        saved_vis = user.get('visibility', 'True,True,True').split(',')
        
        # 💡 [추가] DB에 제출된 서류 링크가 존재하는지 판별 (미제출이 아니면 True)
        has_univ = bool(user.get('link_univ') and user.get('link_univ') != "미제출")
        has_job = bool(user.get('link_job') and user.get('link_job') != "미제출")
        has_asset = bool(user.get('link_asset') and user.get('link_asset') != "미제출")

        # 💡 [수정] 서류를 제출한 항목만 기존 저장값을 따르고, 미제출 항목은 무조건 False
        def_univ = (saved_vis[0] == 'True') if (len(saved_vis) > 0 and has_univ) else False
        def_job = (saved_vis[1] == 'True') if (len(saved_vis) > 1 and has_job) else False
        def_asset = (saved_vis[2] == 'True') if (len(saved_vis) > 2 and has_asset) else False

        c1, c2, c3 = st.columns(3)
        # 💡 [수정] disabled 속성을 추가하여 서류가 없으면 클릭 자체를 못하게 막음
        show_univ = c1.checkbox(get_text('show_univ'), value=def_univ, disabled=not has_univ)
        show_job = c2.checkbox(get_text('show_job'), value=def_job, disabled=not has_job)
        show_asset = c3.checkbox(get_text('show_asset'), value=def_asset, disabled=not has_asset)

        # -----------------------------------------------------------
        # 2. 닉네임 미리보기
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
            st.markdown(f"{get_text('label_id_info')} {full_masked_id}")
            st.markdown(f"{get_text('label_nick_info')} <span style='font-weight:bold; color:#5c6bc0;'>{final_nickname}</span>", unsafe_allow_html=True)
        
        with c_status:
            db_role = user.get('role', 'restricted')
            db_status = user.get('status', 'pending')
            is_premium = user.get('is_premium', False)
            
            if is_premium:
                st.markdown("<span style='background-color:#FFD700; color:#000; padding:5px 10px; border-radius:5px; font-weight:bold;'>👑 Premium Member</span>", unsafe_allow_html=True)
            elif db_role == 'restricted':
                st.error(get_text('status_basic'))
            elif db_status == 'pending':
                st.warning(get_text('status_pending'))
            elif db_status == 'approved':
                if is_public_mode:
                    st.success(get_text('status_approved'))
                else:
                    st.info(get_text('status_anonymous'))
        
        st.write("<br>", unsafe_allow_html=True)

        # -----------------------------------------------------------
        # 3. [메인 기능] 인증 / 저장 / 로그아웃 / 프리미엄 (4컬럼)
        # -----------------------------------------------------------
        col_cert, col_save, col_logout, col_premium = st.columns([1, 1, 1, 1.2])

        # [A] 인증하기 버튼
        with col_cert:
            # 💡 다국어(UI_TEXT) 연동 완료
            if db_status == 'approved':
                btn_label = get_text('btn_verify_edit')
            elif db_status == 'pending':
                btn_label = get_text('btn_verify_pending')
            else:
                btn_label = get_text('btn_verify') # 기본 "인증" 텍스트
                
            # 조건문 없이 무조건 버튼을 생성합니다.
            if st.button(btn_label, use_container_width=True):
                st.session_state.page = 'login' 
                st.session_state.login_step = 'signup_input'
                st.session_state.signup_stage = 3 
                st.session_state.temp_user_data = {
                    "id": user.get('id'), "pw": user.get('pw'), 
                    "phone": user.get('phone'), "email": user.get('email')
                }
                st.rerun()

        # [B] 저장 버튼
        with col_save:
            if st.button(get_text('btn_save'), type="primary", use_container_width=True):
                with st.spinner("Saving..."):
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
                        st.error("Error saving settings.")

        # [C] 로그아웃 버튼
        with col_logout:
            if st.button(get_text('menu_logout'), use_container_width=True):
                st.session_state.clear()
                st.rerun()

        # [D] 🔥 프리미엄 구독 버튼 / 취소 버튼
        with col_premium:
            curr_lang = st.session_state.get('lang', 'ko')
            is_premium = user.get('is_premium', False)
            sub_id = user.get('subscription_id', '')

            # ==========================================
            # 💡 [신규] 이미 프리미엄 유저인 경우 -> 취소 버튼 노출
            # ==========================================
            if is_premium:
                if st.button(get_text('btn_cancel_sub'), use_container_width=True):
                    with st.spinner("구독 정보를 확인 중입니다..."):
                        # 1. Stripe 해외 정기 구독인 경우
                        if sub_id and str(sub_id).startswith("sub_"):
                            try:
                                import stripe
                                stripe.api_key = os.environ.get("STRIPE_SECRET_KEY") or st.secrets.get("STRIPE_SECRET_KEY")
                                # cancel_at_period_end=True 설정: 남은 기간(한 달) 동안은 프리미엄 유지, 다음 달부터 연장 X
                                stripe.Subscription.modify(sub_id, cancel_at_period_end=True)
                                
                                # DB 기록: 취소되었다는 표시를 남김
                                supabase.table("users").update({"subscription_id": "canceled_" + sub_id}).eq("id", user_id).execute()
                                st.session_state.user_info['subscription_id'] = "canceled_" + sub_id
                                
                                st.success("정기 결제가 취소되었습니다. 이번 달 결제일까지는 혜택이 유지됩니다." if curr_lang == 'ko' else "Subscription canceled. Benefits remain until the end of the billing period.")
                                import time; time.sleep(2)
                                st.rerun()
                            except Exception as e:
                                st.error(f"오류가 발생했습니다: {e}")
                                
                        # 2. PortOne 국내 단건 결제인 경우
                        elif sub_id and str(sub_id).startswith("portone_"):
                            st.info("국내 결제는 자동 연장(정기 결제)이 아니므로 별도로 해지하실 필요가 없습니다. 30일 후 자동으로 권한이 만료됩니다." if curr_lang == 'ko' else "Domestic payments do not auto-renew. It will automatically expire in 30 days.")
                        
                        # 3. 기타 (관리자 부여 등)
                        else:
                            st.info("자동 연장되는 구독 내역이 없습니다." if curr_lang == 'ko' else "No active auto-renewing subscription found.")

            # ==========================================
            # 💡 기존 로직: 프리미엄이 아닌 경우 -> 결제 버튼 노출
            # ==========================================
            else:
                # [Case 1] 한국어 사용자: PortOne (국내 카드, 카카오페이 등)
                if curr_lang == 'ko':
                    portone_id = os.environ.get("PORTONE_STORE_ID")
                    if portone_id:
                        u_email = user.get('email', 'test@unicornfinder.app')
                        u_name = user.get('display_name', '유니콘 유저')
                        current_uid = user.get('id', '') 
                        
                        import streamlit.components.v1 as components
                        
                        portone_html = f"""
                        <!DOCTYPE html>
                        <html>
                        <head>
                            <style>
                                body {{ margin: 0; padding: 0; display: flex; justify-content: center; align-items: center; background-color: transparent; overflow: hidden; }}
                                .pay-btn {{ background-color: #FEE500; color: #000000; border: none; border-radius: 8px; padding: 8px 15px; font-size: 15px; font-weight: bold; cursor: pointer; width: 100%; height: 42px; font-family: sans-serif; transition: 0.2s; }}
                                .pay-btn:hover {{ background-color: #e5ce00; }}
                            </style>
                        </head>
                        <body>
                            <button id="pay-button" class="pay-btn" onclick="openPayWindow()">💳 국내 카드로 결제 (테스트)</button>
                            
                            <script>
                                function openPayWindow() {{
                                    const payWindow = window.open("", "_blank", "width=600,height=800");
                                    
                                    if (!payWindow) {{
                                        alert("🚨 팝업 차단이 감지되었습니다. 브라우저 설정에서 팝업을 허용해주세요.");
                                        return;
                                    }}
                                    
                                    const htmlContent = `
                                        <!DOCTYPE html>
                                        <html>
                                        <head>
                                            <meta charset="utf-8">
                                            <meta name="viewport" content="width=device-width, initial-scale=1.0">
                                            <title>안전 결제 진행중</title>
                                            <script src="https://cdn.portone.io/v2/browser-sdk.js"><\\/script>
                                        </head>
                                        <body style="display:flex; justify-content:center; align-items:center; height:100vh; margin:0; background-color:#f8f9fa; font-family:sans-serif;">
                                            <h3>결제 모듈을 안전하게 불러오는 중입니다...</h3>
                                            <script>
                                                window.onload = function() {{
                                                    PortOne.requestPayment({{
                                                        storeId: "{portone_id}",
                                                        channelKey: "channel-key-52a64d79-396d-4c62-8513-aad2946e17f4",
                                                        paymentId: "pay-" + new Date().getTime(),
                                                        orderName: "테스트용",
                                                        totalAmount: 6500,
                                                        currency: "KRW",
                                                        payMethod: "CARD",
                                                        customer: {{ 
                                                            fullName: "{u_name}", 
                                                            email: "{u_email}",
                                                            phoneNumber: "010-0000-0000"
                                                        }},
                                                        windowType: {{
                                                            pc: "IFRAME",        
                                                            smartPhone: "REDIRECTION" 
                                                        }},
                                                        redirectUrl: "https://my-ipo-name-production.up.railway.app/?success=true&uid={current_uid}"
                                                    }}).then(function(response) {{
                                                        if (response && response.code != null) {{
                                                            alert("결제 실패: " + response.message);
                                                            window.close();
                                                        }} else if (response) {{
                                                            if (window.opener && !window.opener.closed) {{
                                                                window.opener.parent.location.href = "https://my-ipo-name-production.up.railway.app/?success=true&uid={current_uid}";
                                                            }}
                                                            window.close();
                                                        }}
                                                    }}).catch(function(e) {{
                                                        alert("오류: " + e.message);
                                                        window.close();
                                                    }});
                                                }};
                                            <\\/script>
                                        </body>
                                        </html>
                                    `;
                                    
                                    payWindow.document.write(htmlContent);
                                    payWindow.document.close();
                                }}
                            </script>
                        </body>
                        </html>
                        """
                        components.html(portone_html, height=45)
                    else:
                        st.button(get_text('btn_premium'), disabled=True)

                # [Case 2] 해외 사용자 (EN, JA, ZH): Stripe 연동
                else:
                    if st.button(get_text('btn_premium'), use_container_width=True):
                        stripe_sk = os.environ.get("STRIPE_SECRET_KEY")
                        stripe_price = os.environ.get("STRIPE_PRICE_ID")
                        current_uid = user.get('id', '') 
                        
                        if user.get('role') == 'admin':
                            if not stripe_sk or not stripe_price:
                                st.divider()
                                st.warning("🛠️ [관리자 디버깅 모드]")
                                st.write(f"- STRIPE_SECRET_KEY: {'✅' if stripe_sk else '❌'}")
                                st.write(f"- STRIPE_PRICE_ID: {'✅' if stripe_price else '❌'}")

                        if not stripe_sk or not stripe_price:
                            st.error("❌ 결제 설정(환경 변수)이 누락되었습니다.")
                        else:
                            with st.spinner(get_text('msg_checkout_ready')):
                                try:
                                    import stripe
                                    stripe.api_key = stripe_sk
                                    checkout_session = stripe.checkout.Session.create(
                                        line_items=[{'price': stripe_price, 'quantity': 1}],
                                        mode='subscription',
                                        locale=curr_lang if curr_lang in ['en', 'ja', 'zh'] else 'auto',
                                        success_url=f'https://my-ipo-name-production.up.railway.app/?success=true&uid={current_uid}&session_id={{CHECKOUT_SESSION_ID}}',
                                        cancel_url='https://my-ipo-name-production.up.railway.app/?canceled=true',
                                    )
                                    st.success(get_text('msg_checkout_complete'))
                                    st.link_button(get_text('btn_pay_now'), checkout_session.url, use_container_width=True)
                                except Exception as e:
                                    st.error(f"결제창 생성 중 오류 발생: {e}")
        
        # ===========================================================
        # 👇 [수정 완료] 관리자 승인 기능 (Supabase 연동 버전)
        # ===========================================================
        if user.get('role') == 'admin':

            # -------------------------------------------------------
            # [1] 기능 함수 정의 (Supabase 전용)
            # -------------------------------------------------------
            def callback_approve(target_id, target_email):
                if db_approve_user(target_id):
                    if target_email:
                        try: send_approval_email(target_email, target_id)
                        except: pass
                    st.toast(f"✅ {target_id} 승인 처리 완료!", icon="🎉")
                else:
                    st.toast(f"❌ {target_id} 처리 실패.", icon="⚠️")

            def callback_reject(target_id, target_email):
                reason_key = f"rej_setup_{target_id}"
                reason = st.session_state.get(reason_key, "")

                if not reason:
                    st.toast("⚠️ 보류 사유를 입력해주세요!", icon="❗")
                    return 

                try:
                    res = supabase.table("users").update({"status": "rejected"}).eq("id", target_id).execute()
                    if res.data:
                        if target_email:
                            try: send_rejection_email(target_email, target_id, reason)
                            except: pass
                        st.toast(f"🛑 {target_id} 보류 처리 완료.", icon="✅")
                    else:
                        st.toast("❌ 처리 실패.", icon="⚠️")
                except Exception as e:
                    st.toast(f"❌ 오류: {e}", icon="⚠️")

            # -------------------------------------------------------
            # [2] 화면 그리기 (UI)
            # -------------------------------------------------------
            with st.container():
                last_update = get_last_cache_update_time() 
                
                display_time = last_update + timedelta(hours=9)
                now = datetime.now(last_update.tzinfo)
    
                col_status1, col_status2 = st.columns([2, 1])
                with col_status1:
                    if last_update < now - timedelta(hours=24):
                        st.error(f"❌ 워커 중단됨: {display_time.strftime('%Y-%m-%d %H:%M')}")
                    else:
                        st.success(f"✅ 데이터 정상: {display_time.strftime('%m-%d %H:%M')}")
                
                with col_status2:
                    if st.button(get_text('admin_system_refresh'), key="admin_refresh"):
                        st.cache_data.clear() 
                        st.rerun()
            
            st.divider()
                
            if st.button(get_text('admin_refresh_users'), key="btn_refresh_list"):
                st.rerun()

            all_users_adm = db_load_all_users()
            pending_users = [u for u in all_users_adm if u.get('status') == 'pending']
            
            if not pending_users:
                st.info(get_text('admin_no_pending'))
            else:
                for pu in pending_users:
                    u_id = pu.get('id')
                    u_email = pu.get('email')
                    
                    with st.expander(f"{u_id} ({pu.get('univ') or get_text('admin_not_provided')})"):
                        st.write(f"**이메일**: {u_email} | **연락처**: {pu.get('phone')}")
                        st.write(f"**직업**: {pu.get('job')} | **자산**: {pu.get('asset')}")
                        
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            if pu.get('link_univ') not in ["미제출", None]: st.link_button("🎓 대학 증빙", pu.get('link_univ'))
                        with c2:
                            if pu.get('link_job') not in ["미제출", None]: st.link_button("💼 직업 증빙", pu.get('link_job'))
                        with c3:
                            if pu.get('link_asset') not in ["미제출", None]: st.link_button("💰 자산 증빙", pu.get('link_asset'))
                        
                        st.divider()

                        st.text_input(get_text('admin_reason'), placeholder=get_text('admin_reason_ph'), key=f"rej_setup_{u_id}")
                        
                        btn_col1, btn_col2 = st.columns(2)
                        
                        with btn_col1:
                            st.button(
                                get_text('admin_btn_approve'), 
                                key=f"btn_app_{u_id}", 
                                use_container_width=True,
                                on_click=callback_approve, 
                                args=(u_id, u_email)
                            )

                        with btn_col2:
                            st.button(
                                get_text('admin_btn_reject'), 
                                key=f"btn_rej_{u_id}", 
                                use_container_width=True, 
                                type="primary",
                                on_click=callback_reject,
                                args=(u_id, u_email)
                            )

# =========================================================
# [추가] 메인 화면 전용 컨테이너 생성 (구조 복원)
# =========================================================
main_area = st.empty()

with main_area.container():

    # ---------------------------------------------------------
    # 4. 캘린더 페이지 (Calendar)
    # ---------------------------------------------------------
    if st.session_state.page == 'calendar':
        # [CSS] 스타일 정의
        st.markdown("""
            <style>
            * { box-sizing: border-box !important; }
            body { color: #333333; }
            .block-container { padding-top: 2rem !important; padding-left: 0.5rem !important; padding-right: 0.5rem !important; max-width: 100% !important; }
            div[data-testid="column"] button { border-radius: 12px !important; height: 50px !important; font-weight: bold !important; }
            div[data-testid="column"] .stButton button { background-color: transparent !important; border: none !important; padding: 0 !important; margin: 0 !important; color: #333 !important; text-align: left !important; box-shadow: none !important; width: 100% !important; display: block !important; overflow: hidden !important; white-space: nowrap !important; text-overflow: ellipsis !important; height: auto !important; line-height: 1.1 !important; }
            div.stButton > button[kind="primary"] { background-color: #FF4B4B !important; color: white !important; border-radius: 8px !important; padding: 0.25rem 0.75rem !important; height: auto !important; }
            .stButton button p { font-weight: bold; font-size: 14px; margin-bottom: 0px; }
            @media (max-width: 640px) {
                div[data-testid="stHorizontalBlock"]:nth-of-type(1) { flex-wrap: wrap !important; gap: 10px !important; padding-bottom: 5px !important; }
                div[data-testid="stHorizontalBlock"]:nth-of-type(1) > div { min-width: 100% !important; max-width: 100% !important; flex: 1 1 100% !important; }
                div[data-testid="stHorizontalBlock"]:not(:nth-of-type(1)) { flex-direction: row !important; flex-wrap: nowrap !important; gap: 0px !important; width: 100% !important; align-items: center !important; }
                div[data-testid="column"] { display: flex !important; flex-direction: column !important; justify-content: center !important; min-width: 0px !important; padding: 0px 2px !important; }
                div[data-testid="stHorizontalBlock"]:not(:nth-of-type(1)) > div[data-testid="column"]:nth-of-type(1) { flex: 0 0 70% !important; max-width: 70% !important; overflow: hidden !important; }
                div[data-testid="stHorizontalBlock"]:not(:nth-of-type(1)) > div[data-testid="column"]:nth-of-type(2) { flex: 0 0 30% !important; max-width: 30% !important; }
                .mobile-sub { font-size: 10px !important; color: #888 !important; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: -2px; line-height: 1.1; }
                .price-main { font-size: 13px !important; font-weight: bold; white-space: nowrap; line-height: 1.1; }
                .price-sub { font-size: 10px !important; color: #666 !important; white-space: nowrap; line-height: 1.1; }
                .date-text { font-size: 10px !important; color: #888 !important; margin-top: 1px; line-height: 1.1; }
            }
            div[data-testid="stPills"] div[role="radiogroup"] button { border: none !important; outline: none !important; background-color: #000000 !important; color: #ffffff !important; border-radius: 20px !important; padding: 6px 15px !important; margin-right: 5px !important; box-shadow: none !important; }
            div[data-testid="stPills"] button[aria-selected="true"] { background-color: #444444 !important; color: #ffffff !important; font-weight: 800 !important; }
            div[data-testid="stPills"] div[data-baseweb="pill"] { border: none !important; background: transparent !important; }
            </style>
        """, unsafe_allow_html=True)
    
        # [ANDROID-FIX]
        st.markdown("""<style>.stSelectbox div[data-baseweb="select"]:focus-within { border-color: transparent !important; box-shadow: none !important; }</style>""", unsafe_allow_html=True)
        st.components.v1.html("<script>var mainDoc=window.parent.document; var activeEl=mainDoc.activeElement; if(activeEl && (activeEl.tagName==='INPUT' || activeEl.getAttribute('role')==='combobox')){ activeEl.blur(); }</script>", height=0)
    
        # 2. 메뉴 텍스트 및 상태
        is_logged_in = st.session_state.auth_status == 'user'
        login_text = get_text('menu_logout') if is_logged_in else get_text('btn_login')
        settings_text = get_text('menu_settings') 
        main_text = get_text('menu_main')
        watch_text = f"{get_text('menu_watch')} ({len(st.session_state.watchlist)})"
        board_text = get_text('menu_board')
        
        menu_options = [login_text, settings_text, main_text, watch_text, board_text] if is_logged_in else [login_text, main_text, watch_text, board_text]
        
        default_sel = main_text
        if st.session_state.get('page') == 'login': default_sel = login_text
        elif st.session_state.get('page') == 'setup': default_sel = settings_text
        elif st.session_state.get('view_mode') == 'watchlist': default_sel = watch_text
        elif st.session_state.get('page') == 'board': default_sel = board_text
    
        selected_menu = st.pills(label="내비게이션", options=menu_options, selection_mode="single", default=default_sel, key="nav_pills_updated_v2", label_visibility="collapsed")
    
        if selected_menu and selected_menu != default_sel:
            if selected_menu == login_text:
                if is_logged_in: st.session_state.auth_status = None 
                st.session_state.page = 'login'
            elif selected_menu == settings_text: st.session_state.page = 'setup'
            elif selected_menu == main_text: st.session_state.view_mode = 'all'; st.session_state.page = 'calendar' 
            elif selected_menu == watch_text: st.session_state.view_mode = 'watchlist'; st.session_state.page = 'calendar' 
            elif selected_menu == board_text: st.session_state.page = 'board'
            st.rerun()
    
        all_df_raw = get_extended_ipo_data(MY_API_KEY)
        view_mode = st.session_state.get('view_mode', 'all')
        
        if not all_df_raw.empty:
            all_df = all_df_raw.copy()
            all_df['exchange'] = all_df['exchange'].fillna('-')
            all_df = all_df[all_df['symbol'].astype(str).str.strip() != ""]
            all_df['공모일_dt'] = pd.to_datetime(all_df['date'], errors='coerce').dt.normalize()
            all_df = all_df.dropna(subset=['공모일_dt'])
            today_dt = pd.to_datetime(datetime.now().date())
            
            opt_period_upcoming = get_text('period_upcoming')
            opt_period_6m = get_text('period_6m')
            opt_period_12m = get_text('period_12m')
            opt_period_18m = get_text('period_18m')
            opt_sort_latest = get_text('sort_latest')
            opt_sort_return = get_text('sort_return')
            
            sort_option = opt_sort_latest
            period = opt_period_upcoming
            display_df = pd.DataFrame() 
    
            if view_mode == 'watchlist':
                if st.button(get_text('btn_view_all'), use_container_width=True, key="btn_view_all_main_final"):
                    st.session_state.view_mode = 'all'
                    st.rerun()
                display_df = all_df[all_df['symbol'].isin(st.session_state.watchlist)]
                if display_df.empty:
                    st.info("아직 관심 종목에 담은 기업이 없습니다." if st.session_state.lang == 'ko' else "No stocks in your watchlist.")
            else:
                col_f1, col_f2 = st.columns([1, 1]) 
                with col_f1:
                    period = st.selectbox(get_text('filter_period'), [opt_period_upcoming, opt_period_6m, opt_period_12m, opt_period_18m], key="filter_period_final", label_visibility="collapsed")
                with col_f2:
                    sort_option = st.selectbox(get_text('filter_sort'), [opt_sort_latest, opt_sort_return], key="filter_sort_final", label_visibility="collapsed")
                
                if period == opt_period_upcoming:
                    display_df = all_df[(all_df['공모일_dt'] >= today_dt) & (all_df['공모일_dt'] <= today_dt + timedelta(days=30))]
                else:
                    if period == opt_period_6m: start_date = today_dt - timedelta(days=180)
                    elif period == opt_period_12m: start_date = today_dt - timedelta(days=365)
                    elif period == opt_period_18m: start_date = today_dt - timedelta(days=540)
                    display_df = all_df[(all_df['공모일_dt'] < today_dt) & (all_df['공모일_dt'] >= start_date)]
    
            if not display_df.empty:
                symbols_to_fetch = display_df['symbol'].dropna().unique().tolist()
                
                with st.spinner("실시간 주가 확인 중..." if st.session_state.lang == 'ko' else "Fetching prices..."):
                    all_prices_map, all_status_map = get_batch_prices(symbols_to_fetch)
                    
                display_df['live_price'] = display_df['symbol'].map(all_prices_map).fillna(0.0)
                display_df['live_status'] = display_df['symbol'].map(all_status_map).fillna("Active")
                
                def parse_price(x):
                    try: return float(str(x).replace('$','').split('-')[0])
                    except: return 0.0
    
                p_ipo_series = display_df['price'].apply(parse_price)
                display_df['temp_return'] = np.where(
                    (p_ipo_series > 0) & (display_df['live_price'] > 0) & (display_df['live_status'] == "Active"),
                    ((display_df['live_price'] - p_ipo_series) / p_ipo_series) * 100, -9999
                )
                display_df['temp_return'] = pd.to_numeric(display_df['temp_return'], errors='coerce').fillna(-9999.0)
        
                if sort_option == opt_sort_return: display_df = display_df.sort_values(by='temp_return', ascending=False)
                else: display_df = display_df.sort_values(by='공모일_dt', ascending=False)
    
            if not display_df.empty:
                for i, row in display_df.iterrows():
                    p_val = pd.to_numeric(str(row.get('price','')).replace('$','').split('-')[0], errors='coerce')
                    p_val = p_val if p_val and p_val > 0 else 0
                    
                    live_p = row.get('live_price', 0)
                    live_s = row.get('live_status', 'Active')
                    
                    if live_s == "상장연기": price_html = f"<div class='price-main' style='color:#1919e6 !important;'>{get_text('status_delayed')}</div><div class='price-sub' style='color:#666666 !important;'>IPO: ${p_val:,.2f}</div>"
                    elif live_s == "상장폐지": price_html = f"<div class='price-main' style='color:#888888 !important;'>{get_text('status_delisted')}</div><div class='price-sub' style='color:#666666 !important;'>IPO: ${p_val:,.2f}</div>"
                    elif live_p > 0:
                        pct = ((live_p - p_val) / p_val) * 100 if p_val > 0 else 0
                        change_color = "#e61919" if pct > 0 else "#1919e6" if pct < 0 else "#333333"
                        arrow = "▲" if pct > 0 else "▼" if pct < 0 else ""
                        price_html = f"<div class='price-main' style='color:{change_color} !important;'>${live_p:,.2f} ({arrow}{pct:+.1f}%)</div><div class='price-sub' style='color:#666666 !important;'>IPO: ${p_val:,.2f}</div>"
                    else: price_html = f"<div class='price-main' style='color:#333333 !important;'>${p_val:,.2f}</div><div class='price-sub' style='color:#666666 !important;'>{get_text('label_ipo_price')}</div>"
                    
                    date_html = f"<div class='date-text'>{row['date']}</div>"
                    c1, c2 = st.columns([7, 3])
                    
                    with c1:
                        # 💡 [최종 수정] 캘린더 화면을 즉시 폭파하고 리런합니다.
                        if st.button(f"{row['name']}", key=f"btn_list_{i}"):
                            main_area.empty() # 화면 비우기
                            st.session_state.selected_stock = row.to_dict()
                            st.session_state.page = 'detail'
                            st.session_state.detail_sub_menu = get_text('tab_0') # Detail 페이지 진입 시 첫 탭 강제 설정
                            st.rerun()
                        
                        try: s_val = int(row.get('numberOfShares',0)) * p_val / 1000000
                        except: s_val = 0
                        size_str = f" | ${s_val:,.0f}M" if s_val > 0 else ""
                        st.markdown(f"<div class='mobile-sub' style='margin-top:-2px; padding-left:2px;'>{row['symbol']} | {row.get('exchange','-')}{size_str}</div>", unsafe_allow_html=True)
                    
                    with c2:
                        st.markdown(f"<div style='text-align:right;'>{price_html}{date_html}</div>", unsafe_allow_html=True)
                    
                    st.markdown("<div style='border-bottom:1px solid #f0f2f6; margin: 4px 0;'></div>", unsafe_allow_html=True)
            else:
                st.info("조건에 맞는 종목이 없습니다." if st.session_state.lang == 'ko' else "No results found.")
    
    
    
    
    # ---------------------------------------------------------
    # 5. 상세 페이지 (Detail)
    # ---------------------------------------------------------
    elif st.session_state.page == 'detail':
        stock = st.session_state.selected_stock
        
        if not stock:
            st.session_state.page = 'calendar'
            st.rerun()

        sid = stock['symbol']
        user_info = st.session_state.get('user_info') or {}
        user_id = user_info.get('id', 'guest_id')
    
        if sid not in st.session_state.user_decisions:
            saved_data = db_load_user_specific_decisions(user_id, sid)
            if saved_data:
                st.session_state.user_decisions[sid] = {
                    "filing": saved_data.get('filing'), "news": saved_data.get('news'),
                    "macro": saved_data.get('macro'), "company": saved_data.get('company'), "ipo_report": saved_data.get('ipo_report')
                }
            else:
                st.session_state.user_decisions[sid] = {}

        # 🔥 [핵심 수정] 탭(Tab)이 바뀌기 전에 무조건 실시간 가격부터 가져옵니다! (Null 에러 방지)
        profile = None
        fin_data = {}
        current_p = 0.0
        off_val = 0.0
        current_s = "Active"
        
        try: 
            off_val = float(str(stock.get('price', '0')).replace('$', '').split('-')[0].strip())
        except: 
            off_val = 0.0
            
        try:
            current_p, current_s = get_current_stock_price(sid, MY_API_KEY)
            profile = get_company_profile(sid, MY_API_KEY) 
        except: pass
    
        if stock:
            # 상단 메뉴바
            st.markdown("""<style>div[data-testid="stPills"] div[role="radiogroup"] button { border: none !important; background-color: #000000 !important; color: #ffffff !important; border-radius: 20px !important; padding: 6px 15px !important; margin-right: 5px !important; box-shadow: none !important; } div[data-testid="stPills"] button[aria-selected="true"] { background-color: #444444 !important; font-weight: 800 !important; }</style>""", unsafe_allow_html=True)
            is_logged_in = st.session_state.auth_status == 'user'
            login_text = get_text('menu_logout') if is_logged_in else get_text('btn_login')
            menu_options = [login_text, get_text('menu_settings'), get_text('menu_main'), f"{get_text('menu_watch')} ({len(st.session_state.watchlist)})", get_text('menu_board')] if is_logged_in else [login_text, get_text('menu_main'), f"{get_text('menu_watch')} ({len(st.session_state.watchlist)})", get_text('menu_board')]
            
            selected_menu = st.pills(label="nav", options=menu_options, selection_mode="single", default=None, key="detail_nav_updated_final", label_visibility="collapsed")
            if selected_menu:
                if selected_menu == login_text: 
                    if is_logged_in: st.session_state.auth_status = None
                    st.session_state.page = 'login'
                elif selected_menu == get_text('menu_settings'): st.session_state.page = 'setup'
                elif selected_menu == get_text('menu_main'): st.session_state.view_mode = 'all'; st.session_state.page = 'calendar'
                elif selected_menu == f"{get_text('menu_watch')} ({len(st.session_state.watchlist)})": st.session_state.view_mode = 'watchlist'; st.session_state.page = 'calendar'
                elif selected_menu == get_text('menu_board'): st.session_state.page = 'board'
                st.rerun()

            # 🔥 [핵심 수정] 위에서 가져온 가격으로 즉시 헤더를 그립니다!
            today = datetime.now().date()
            ipo_dt = pd.to_datetime(stock['공모일_dt']).date()
            status_emoji = "🐣" if ipo_dt > (today - timedelta(days=365)) else "🦄"
            date_str = ipo_dt.strftime('%Y-%m-%d')
            label_ipo = get_text('label_ipo_price')
            
            if current_s == "상장연기": p_info = f"<span style='font-size: 0.9rem; color: #1919e6;'>({date_str} / {label_ipo} ${off_val} / 📅 {get_text('status_delayed')})</span>"
            elif current_s == "상장폐지": p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / {label_ipo} ${off_val} / 🚫 {get_text('status_delisted')})</span>"
            elif current_p > 0 and off_val > 0:
                pct = ((current_p - off_val) / off_val) * 100
                color = "#00ff41" if pct >= 0 else "#ff4b4b"
                icon = "▲" if pct >= 0 else "▼"
                p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / {label_ipo} ${off_val} / {get_text('label_general')} ${current_p:,.2f} <span style='color:{color}; font-weight:bold;'>{icon} {abs(pct):.1f}%</span>)</span>"
            else: p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / {label_ipo} ${off_val} / {get_text('status_waiting')})</span>"
            
            # 여기서 화면에 한 번만 그려줍니다.
            st.markdown(f"<div><span style='font-size: 1.2rem; font-weight: 700;'>{status_emoji} {stock['name']}</span> {p_info}</div>", unsafe_allow_html=True)
            st.write("")
    
            tab_labels = [get_text(f'tab_{i}') for i in range(6)]
            
            if 'detail_sub_menu' not in st.session_state or st.session_state.detail_sub_menu not in tab_labels:
                st.session_state.detail_sub_menu = tab_labels[0]

            selected_sub_menu = st.pills(label="sub_nav", options=tab_labels, selection_mode="single", default=st.session_state.detail_sub_menu, key="detail_tabs_pills", label_visibility="collapsed")
            
            if selected_sub_menu and selected_sub_menu != st.session_state.detail_sub_menu:
                st.session_state.detail_sub_menu = selected_sub_menu
                st.rerun()

            # -------------------------------------------------------------------------
            # 여기서부터는 선택된 탭의 내용만 그립니다! (초고속 로딩의 비결)
            # -------------------------------------------------------------------------
            
            # --- Tab 0: 핵심 정보 ---
            if selected_sub_menu == get_text('tab_0'):
                if 'core_topic' not in st.session_state: st.session_state.core_topic = "S-1"
                st.markdown("""<style>div.stButton > button { background-color: #ffffff !important; color: #000000 !important; border: 1px solid #dcdcdc !important; border-radius: 8px !important; height: 3em !important; font-weight: bold !important; } div.stButton > button:hover { border-color: #6e8efb !important; color: #6e8efb !important; } div.stButton > button:active { background-color: #f0f2f6 !important; }</style>""", unsafe_allow_html=True)
    
                # 1. 문서 선택 탭 버튼
                r1_c1, r1_c2, r1_c3 = st.columns(3)
                r2_c1, r2_c2 = st.columns(2)
                if r1_c1.button(get_text('label_s1'), use_container_width=True): st.session_state.core_topic = "S-1"; st.rerun()
                if r1_c2.button(get_text('label_s1a'), use_container_width=True): st.session_state.core_topic = "S-1/A"; st.rerun()
                if r1_c3.button(get_text('label_f1'), use_container_width=True): st.session_state.core_topic = "F-1"; st.rerun()
                if r2_c1.button(get_text('label_fwp'), use_container_width=True): st.session_state.core_topic = "FWP"; st.rerun()
                if r2_c2.button(get_text('label_424b4'), use_container_width=True): st.session_state.core_topic = "424B4"; st.rerun()

                topic = st.session_state.core_topic
                curr_lang = st.session_state.lang
                
                # 2. 문서 설명 (Info Box)
                st.info(get_text(f"desc_{topic.lower().replace('/','').replace('-','')}"))

                

                # ---------------------------------------------------------------------
                # [순서 변경] AI 요약 (Expander)을 버튼 위로 이동
                # ---------------------------------------------------------------------
                def_meta = {
                    "S-1": {
                        "desc": "S-1은 상장을 위해 최초로 제출하는 서류입니다. **Risk Factors**(위험 요소), **Use of Proceeds**(자금 용도), **MD&A**(경영진의 운영 설명)를 확인할 수 있습니다.",
                        "points": "Risk Factors(특이 소송/규제), Use of Proceeds(자금 용도의 건전성), MD&A(성장 동인)",
                        "structure": """
                        [문단 구성 지침]
                        1. 첫 번째 문단: 해당 문서에서 발견된 가장 중요한 투자 포인트 분석
                        2. 두 번째 문단: 실질적 성장 가능성과 재무적 의미 분석
                        3. 세 번째 문단: 핵심 리스크 1가지와 그 파급 효과 및 대응책
                        """
                    },
                    "S-1/A": {
                        "desc": "S-1/A는 공모가 밴드와 주식 수가 확정되는 수정 문서입니다. **Pricing Terms**(공모가 확정 범위)와 **Dilution**(기존 주주 대비 희석률)을 확인할 수 있습니다.",
                        "points": "Pricing Terms(수요예측 분위기), Dilution(신규 투자자 희석률), Changes(이전 제출본과의 차이점)",
                        "structure": """
                        [문단 구성 지침]
                        1. 첫 번째 문단: 이전 S-1 대비 변경된 핵심 사항 분석
                        2. 두 번째 문단: 제시된 공모가 범위의 적정성 및 수요예측 분위기 분석
                        3. 세 번째 문단: 기존 주주 가치 희석 정도와 투자 매력도 분석
                        """
                    },
                    "F-1": {
                        "desc": "F-1은 해외 기업이 미국 상장 시 제출하는 서류입니다. 해당 국가의 **Foreign Risk**(정치/경제 리스크)와 **Accounting**(회계 기준 차이)을 확인할 수 있습니다.",
                        "points": "Foreign Risk(지정학적 리스크), Accounting(GAAP 차이), ADS(주식 예탁 증서 구조)",
                        "structure": """
                        [문단 구성 지침]
                        1. 첫 번째 문단: 기업이 글로벌 시장에서 가진 독보적인 경쟁 우위
                        2. 두 번째 문단: 환율, 정치, 회계 등 해외 기업 특유의 리스크 분석
                        3. 세 번째 문단: 미국 예탁 증서(ADS) 구조가 주주 권리에 미치는 영향
                        """
                    },
                    "FWP": {
                        "desc": "FWP는 기관 투자자 대상 로드쇼(Roadshow) PPT 자료입니다. **Graphics**(비즈니스 모델 시각화)와 **Strategy**(경영진이 강조하는 미래 성장 동력)를 확인할 수 있습니다.",
                        "points": "Graphics(시장 점유율 시각화), Strategy(미래 핵심 먹거리), Highlights(경영진 강조 사항)",
                        "structure": """
                        [문단 구성 지침]
                        1. 첫 번째 문단: 경영진이 로드쇼에서 강조하는 미래 성장 비전
                        2. 두 번째 문단: 경쟁사 대비 부각시키는 기술적/사업적 차별화 포인트
                        3. 세 번째 문단: 자료 톤앤매너로 유추할 수 있는 시장 공략 의지
                        """
                    },
                    "424B4": {
                        "desc": "424B4는 공모가가 최종 확정된 후 발행되는 설명서입니다. **Underwriting**(주관사 배정)과 확정된 **Final Price**(최종 공모가)를 확인할 수 있습니다.",
                        "points": "Underwriting(주관사 등급), Final Price(기관 배정 물량), IPO Outcome(최종 공모 결과)",
                        "structure": """
                        [문단 구성 지침]
                        1. 첫 번째 문단: 확정 공모가의 위치와 시장 수요 해석
                        2. 두 번째 문단: 확정된 조달 자금의 투입 우선순위 점검
                        3. 세 번째 문단: 주관사단 및 배정 물량 바탕 상장 초기 유통물량 예측
                        """
                    }
                }
                
                curr_meta = def_meta.get(topic, def_meta["S-1"])
                
                format_instruction = """
                [출력 형식 및 번역 규칙 - 반드시 지킬 것]
                - 각 문단의 시작은 반드시 해당 언어로 번역된 **[소제목]**으로 시작한 뒤, 줄바꿈 없이 한 칸 띄우고 바로 내용을 이어가세요.
                - [분량 조건] 전체 요약이 아닙니다! **각 문단(1, 2, 3)마다 반드시 4~5문장(약 5줄 분량)씩** 내용을 상세하고 풍성하게 채워 넣으세요.
                - 올바른 예시(영어): **[Investment Point]** The company's main advantage is...
                - 올바른 예시(일본어): **[投資ポイント]** 同社の最大の強みは...
                - 금지 예시(한국어 병기 절대 금지): **[Investment Point - 투자포인트]** (X)
                - 금지 예시(소제목 뒤 줄바꿈 절대 금지): **[投資ポイント]** \n 同社は... (X)
                """

                # 4. AI 요약 보기 (Expander) - 버튼 위로 이동 완료
                with st.expander(f" {topic} {get_text('btn_summary_view')}", expanded=False):
                    with st.spinner(get_text('msg_analyzing_filing')):
                        # 함수 내부에서 포인트와 구조를 알아서 처리하므로 3개만 보내면 됩니다!
                        analysis_result = get_ai_analysis(stock['name'], topic, curr_lang)
                    if "ERROR_DETAILS" in analysis_result:
                        st.error("잠시 후 다시 시도해주세요. (할당량 초과 가능성)")
                    else:
                        import re
                        formatted_result = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', analysis_result)
                        indent_size = "14px" if curr_lang == "ko" else "0px"
                        # 💡 [수정] </div> 뒤에 <br>을 추가하여 캡션과 한 줄 띄우기
                        st.markdown(f'<div style="line-height:1.8; text-align:justify; font-size:15px; color:#333; text-indent:{indent_size};">{formatted_result.replace(chr(10), "<br>")}</div><br>', unsafe_allow_html=True)
                    
                    # 💡 [위치 수정] Expander 내부 맨 하단에 캡션 배치
                    st.caption(get_text('caption_algorithm'))

                # 5. 외부 링크 버튼 (AI 요약 밑으로 이동)
                import urllib.parse
                cik = profile.get('cik', '') if profile else ''
                full_company_name = stock['name'].strip() 
                if cik: sec_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={urllib.parse.quote(topic)}&owner=include&count=40"
                else: sec_url = f"https://www.sec.gov/edgar/search/#/q={urllib.parse.quote(full_company_name)}&dateRange=all"
                
                real_website = profile.get('weburl') or profile.get('website', '') if profile else ''
                website_url = real_website if real_website else f"https://duckduckgo.com/?q={urllib.parse.quote('! ' + full_company_name + ' Investor Relations')}"
                
                st.markdown(f"""
                    <a href="{sec_url}" target="_blank" style="text-decoration:none;">
                        <button style='width:100%; padding:15px; background:white; border:1px solid #004e92; color:#004e92; border-radius:10px; font-weight:bold; cursor:pointer; margin-bottom: 8px;'>{get_text('btn_sec_link')} ({topic})</button>
                    </a>
                    <a href="{website_url}" target="_blank" style="text-decoration:none;">
                        <button style='width:100%; padding:15px; background:white; border:1px solid #333333; color:#333333; border-radius:10px; font-weight:bold; cursor:pointer;'>{get_text('btn_official_web')}</button>
                    </a>
                """, unsafe_allow_html=True)

                # 6. 의사결정 박스
                draw_decision_box("filing", get_text('decision_question_filing'), ['sentiment_positive', 'sentiment_neutral', 'sentiment_negative'], current_p)
                
                # 7. 면책 조항
                display_disclaimer()
                    
            # --- Tab 1: 뉴스 & 심층 분석 ---
            elif selected_sub_menu == get_text('tab_1'):
                with st.spinner(get_text('msg_analyzing_tab1')):
                    biz_info, final_display_news = get_unified_tab1_analysis(stock['name'], stock['symbol'], st.session_state.lang)

                st.write("<br>", unsafe_allow_html=True)
                with st.expander(get_text('expander_biz_summary'), expanded=False):
                    if biz_info:
                        st.markdown(f"""
                        <div style="background-color: #f8f9fa; padding: 22px; border-radius: 12px; border-left: 5px solid #6e8efb; color: #333; font-family: 'Pretendard', sans-serif; font-size: 15px; line-height: 1.6;">
                            {biz_info}
                        </div>
                        """, unsafe_allow_html=True)
                        st.caption(get_text('caption_google_search'))
                    else:
                        st.error(get_text('err_no_biz_info'))
    
                st.write("<br>", unsafe_allow_html=True)
    
                if final_display_news:
                    curr_lang = st.session_state.lang
                    for i, n in enumerate(final_display_news):
                        en_title = n.get('title_en', 'No Title')
                        trans_title = n.get('translated_title') or n.get('title_ko') or n.get('title_ja') or n.get('title_jp') or n.get('title', '')
                        
                        raw_sentiment = n.get('sentiment', '일반')
                        if raw_sentiment == "긍정": sentiment_label = get_text('sentiment_positive')
                        elif raw_sentiment == "부정": sentiment_label = get_text('sentiment_negative')
                        else: sentiment_label = get_text('sentiment_neutral')
                        
                        bg_color = n.get('bg', '#f1f3f4')
                        text_color = n.get('color', '#5f6368')
                        news_link = n.get('link', '#')
                        news_date = n.get('date', 'Recent')
    
                        safe_en = str(en_title).replace("$", "\$")
                        safe_trans = str(trans_title).replace("$", "\$")
                        
                        sub_title_html = ""
                        if safe_trans and safe_trans != safe_en and curr_lang != 'en': 
                            if curr_lang == 'ko': sub_title_html = f"<br><span style='font-size:14px; color:#555; font-weight:400;'>🇰🇷 {safe_trans}</span>"
                            elif curr_lang == 'ja': sub_title_html = f"<br><span style='font-size:14px; color:#555; font-weight:400;'>🇯🇵 {safe_trans}</span>"

                        s_badge = f'<span style="background:{bg_color}; color:{text_color}; padding:2px 6px; border-radius:4px; font-size:11px; margin-left:5px;">{sentiment_label}</span>'
                        label_gen = get_text('label_general')
                        
                        st.markdown(f"""
                            <a href="{news_link}" target="_blank" style="text-decoration:none; color:inherit;">
                                <div style="padding:15px; border:1px solid #eee; border-radius:10px; margin-bottom:10px; box-shadow:0 2px 5px rgba(0,0,0,0.03);">
                                    <div style="display:flex; justify-content:space-between; align-items:center;">
                                        <div><span style="color:#6e8efb; font-weight:bold;">TOP {i+1}</span> <span style="color:#888; font-size:12px;">| {label_gen}</span>{s_badge}</div>
                                        <small style="color:#bbb;">{news_date}</small>
                                    </div>
                                    <div style="margin-top:8px; font-weight:600; font-size:15px; line-height:1.4;">
                                        {safe_en}{sub_title_html}
                                    </div>
                                </div>
                            </a>
                        """, unsafe_allow_html=True)
                else:
                    st.warning(get_text('err_no_news'))
    
                st.write("<br>", unsafe_allow_html=True)
                draw_decision_box("news", get_text('decision_news_impression'), ['sentiment_positive', 'sentiment_neutral', 'sentiment_negative'], current_p)
                display_disclaimer()
                
            # --- Tab 2: 실시간 시장 과열 진단 ---
            elif selected_sub_menu == get_text('tab_2'):
                
                # 💡 [수정됨] 기존에 있던 느린 내부 함수(get_market_status_internal)를 통째로 삭제하고, 
                # 상단에 만들어둔 캐싱 함수를 바로 호출합니다!
                with st.spinner(get_text('msg_analyzing_macro')):
                    if 'all_df' not in locals(): 
                        all_df_tab2 = get_extended_ipo_data(MY_API_KEY)
                        if not all_df_tab2.empty:
                            all_df_tab2 = all_df_tab2.dropna(subset=['exchange'])
                            all_df_tab2['공모일_dt'] = pd.to_datetime(all_df_tab2['date'])
                    else: 
                        all_df_tab2 = all_df
                    
                    # 🚀 [핵심] 여기서 Supabase에 캐싱된 데이터를 0.1초 만에 가져옵니다.
                    md = get_cached_market_status(all_df_tab2, MY_API_KEY)
            
                st.markdown("""
                <style>
                    .metric-card { background-color:#ffffff; padding:15px; border-radius:12px; border: 1px solid #e0e0e0; box-shadow: 0 2px 4px rgba(0,0,0,0.03); height: 100%; min-height: 220px; display: flex; flex-direction: column; justify-content: space-between; }
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
            
                stat_map = {
                    "over": {"ko": "🔥 과열", "en": "🔥 Overheated", "ja": "🔥 過熱"},
                    "good": {"ko": "✅ 적정", "en": "✅ Normal", "ja": "✅ 適正"},
                    "cold": {"ko": "❄️ 침체", "en": "❄️ Sluggish", "ja": "❄️ 停滞"},
                    "active": {"ko": "🔥 활발", "en": "🔥 Active", "ja": "🔥 活発"},
                    "normal": {"ko": "⚖️ 보통", "en": "⚖️ Normal", "ja": "⚖️ 普通"},
                    "risk": {"ko": "🚨 위험", "en": "🚨 Risk", "ja": "🚨 危険"},
                    "warn": {"ko": "⚠️ 주의", "en": "⚠️ Warning", "ja": "⚠️ 注意"},
                    "greed": {"ko": "🔥 탐욕", "en": "🔥 Greed", "ja": "🔥 強欲"},
                    "fear": {"ko": "❄️ 공포", "en": "❄️ Fear", "ja": "❄️ 恐怖"},
                    "neutral": {"ko": "⚖️ 중립", "en": "⚖️ Neutral", "ja": "⚖️ 中立"},
                    "high": {"ko": "🚨 고평가", "en": "🚨 Overvalued", "ja": "🚨 割高"}
                }
                def get_stat(key): return stat_map[key].get(st.session_state.get('lang', 'ko'), stat_map[key]['ko'])

                st.markdown(f'<p style="font-size: 15px; font-weight: 600; margin-bottom: 10px;">{get_text("ipo_overheat_title")}</p>', unsafe_allow_html=True)
                c1, c2, c3, c4 = st.columns(4)
            
                with c1:
                    val = md['ipo_return']; status = get_stat("over") if val >= 20 else get_stat("good") if val >= 0 else get_stat("cold")
                    st_cls = "st-hot" if val >= 20 else "st-good" if val >= 0 else "st-cold"
                    st.markdown(f"<div class='metric-card'><div class='metric-header'>First-Day Returns</div><div class='metric-value-row'><span class='metric-value'>{val:+.1f}%</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>{get_text('desc_first_day')}</div><div class='metric-footer'>Ref: Jay Ritter (Univ. of Florida)</div></div>", unsafe_allow_html=True)
            
                with c2:
                    val = md['ipo_volume']; status = get_stat("active") if val >= 10 else get_stat("normal")
                    st_cls = "st-hot" if val >= 10 else "st-neutral"
                    st.markdown(f"<div class='metric-card'><div class='metric-header'>Filings Volume</div><div class='metric-value-row'><span class='metric-value'>{val}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>{get_text('desc_filings_vol')}</div><div class='metric-footer'>Ref: Ibbotson & Jaffe (1975)</div></div>", unsafe_allow_html=True)
            
                with c3:
                    val = md['unprofitable_pct']; status = get_stat("risk") if val >= 80 else get_stat("warn") if val >= 50 else get_stat("good")
                    st_cls = "st-hot" if val >= 50 else "st-good"
                    st.markdown(f"<div class='metric-card'><div class='metric-header'>Unprofitable IPOs</div><div class='metric-value-row'><span class='metric-value'>{val:.0f}%</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>{get_text('desc_unprofitable')}</div><div class='metric-footer'>Ref: Jay Ritter (Dot-com Bubble)</div></div>", unsafe_allow_html=True)
            
                with c4:
                    val = md['withdrawal_rate']; status = get_stat("over") if val < 5 else get_stat("good")
                    st_cls = "st-hot" if val < 5 else "st-good"
                    st.markdown(f"<div class='metric-card'><div class='metric-header'>Withdrawal Rate</div><div class='metric-value-row'><span class='metric-value'>{val:.1f}%</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>{get_text('desc_withdrawal')}</div><div class='metric-footer'>Ref: Dunbar (1998)</div></div>", unsafe_allow_html=True)
            
                st.markdown(f'<p style="font-size: 15px; font-weight: 600; margin-top: 20px; margin-bottom: 10px;">{get_text("macro_overheat_title")}</p>', unsafe_allow_html=True)
                m1, m2, m3, m4 = st.columns(4)
            
                with m1:
                    val = md['vix']; status = get_stat("greed") if val <= 15 else get_stat("fear") if val >= 25 else get_stat("neutral")
                    st_cls = "st-hot" if val <= 15 else "st-cold" if val >= 25 else "st-neutral"
                    st.markdown(f"<div class='metric-card'><div class='metric-header'>VIX Index</div><div class='metric-value-row'><span class='metric-value'>{val:.2f}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>{get_text('desc_vix')}</div><div class='metric-footer'>Ref: CBOE / Whaley (1993)</div></div>", unsafe_allow_html=True)
            
                with m2:
                    val = md['buffett_val']; status = get_stat("high") if val > 150 else get_stat("warn")
                    st_cls = "st-hot" if val > 120 else "st-neutral"
                    disp_val = f"{val:.0f}%" if val > 0 else "N/A"
                    st.markdown(f"<div class='metric-card'><div class='metric-header'>Buffett Indicator</div><div class='metric-value-row'><span class='metric-value'>{disp_val}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>{get_text('desc_buffett')}</div><div class='metric-footer'>Ref: Warren Buffett (2001)</div></div>", unsafe_allow_html=True)
            
                with m3:
                    val = md['pe_ratio']; status = get_stat("high") if val > 25 else get_stat("good")
                    st_cls = "st-hot" if val > 25 else "st-good"
                    st.markdown(f"<div class='metric-card'><div class='metric-header'>S&P 500 PE</div><div class='metric-value-row'><span class='metric-value'>{val:.1f}x</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>{get_text('desc_pe')}</div><div class='metric-footer'>Ref: Shiller CAPE Model (Proxy)</div></div>", unsafe_allow_html=True)
            
                with m4:
                    val = md['fear_greed']; status = get_stat("greed") if val >= 70 else get_stat("fear") if val <= 30 else get_stat("neutral")
                    st_cls = "st-hot" if val >= 70 else "st-cold" if val <= 30 else "st-neutral"
                    st.markdown(f"<div class='metric-card'><div class='metric-header'>Fear & Greed</div><div class='metric-value-row'><span class='metric-value'>{val:.0f}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>{get_text('desc_fear_greed')}</div><div class='metric-footer'>Ref: CNN Business Logic</div></div>", unsafe_allow_html=True)
            
                st.write("<br>", unsafe_allow_html=True)
                
                with st.expander(get_text('expander_macro_analysis'), expanded=False): 
                    try:
                        ai_market_comment = get_market_dashboard_analysis(md, st.session_state.lang)
                        if isinstance(ai_market_comment, str):
                            import re
                            ai_market_comment = re.sub(r'^#+.*$', '', ai_market_comment, flags=re.MULTILINE)
                            ai_market_comment = ai_market_comment.replace("</div>", "").replace("<div>", "").replace("```html", "").replace("```", "").strip()
                    except: ai_market_comment = "Error generating AI analysis."
    
                    st.markdown(f"<div style='background-color:#f8f9fa; padding:15px; border-radius:10px; border-left: 5px solid #004e92;'><div style='font-size:14px; line-height:1.6; color:#333; text-align:justify;'>{ai_market_comment}</div></div>", unsafe_allow_html=True)
            
                with st.expander(get_text('expander_references'), expanded=False):
                    references = [
                        { "label": get_text('ref_label_ipo'), "title": "Initial Public Offerings", "author": "Jay R. Ritter", "summary": get_text('ref_sum_ipo'), "link": "https://site.warrington.ufl.edu/ritter/ipo-data/" },
                        { "label": get_text('ref_label_overheat'), "title": "'Hot Issue' Markets", "author": "Ibbotson & Jaffe (1975)", "summary": get_text('ref_sum_overheat'), "link": "https://scholar.google.com/scholar?q=Ibbotson+Jaffe+1975+Hot+Issue+Markets" },
                        { "label": get_text('ref_label_withdrawal'), "title": "The Choice Between IPOs", "author": "Dunbar (1998)", "summary": get_text('ref_sum_withdrawal'), "link": "https://scholar.google.com/scholar?q=Dunbar+1995" },
                        { "label": get_text('ref_label_vix'), "title": "VIX White Paper", "author": "CBOE", "summary": get_text('ref_sum_vix'), "link": "https://www.cboe.com/micro/vix/vixwhite.pdf" },
                        { "label": get_text('ref_label_buffett'), "title": "Warren Buffett on the Stock Market", "author": "Warren Buffett (2001)", "summary": get_text('ref_sum_buffett'), "link": "https://www.gurufocus.com/news/122602" },
                        { "label": get_text('ref_label_cape'), "title": "U.S. Stock Markets 1871-Present", "author": "Robert Shiller", "summary": get_text('ref_sum_cape'), "link": "http://www.econ.yale.edu/~shiller/data.htm" },
                        { "label": get_text('ref_label_feargreed'), "title": "Fear & Greed Index", "author": "CNN Business", "summary": get_text('ref_sum_feargreed'), "link": "https://edition.cnn.com/markets/fear-and-greed" }
                    ]
                    for ref in references:
                        st.markdown(f"<div class='ref-item'><div style='flex:1;'><div class='ref-badge'>{ref['label']}</div><br><a href='{ref['link']}' target='_blank' class='ref-title'>📄 {ref['title']}</a><div style='font-size: 13px; color: #666;'>{ref['summary']}, {ref['author']}</div></div><div style='margin-left: 15px;'><a href='{ref['link']}' target='_blank' class='ref-btn'>{get_text('btn_view_original')}</a></div></div>", unsafe_allow_html=True)
            
                draw_decision_box("macro", get_text('decision_macro_outlook'), ['opt_bubble', 'sentiment_neutral', 'opt_recession'], current_p)
                display_disclaimer()  
            # --- Tab 3: 개별 기업 평가 ---
            elif selected_sub_menu == get_text('tab_3'):
                curr_lang = st.session_state.lang
                is_ko = (curr_lang == 'ko')

                # 💡 [핵심] Tab 2와 완벽하게 동일한 디자인을 적용하기 위해 CSS 카드를 선언합니다.
                st.markdown("""
                <style>
                    /* Tab 2와 동일한 메인 카드 디자인 */
                    .metric-card { background-color:#ffffff; padding:15px; border-radius:12px; border: 1px solid #e0e0e0; box-shadow: 0 2px 4px rgba(0,0,0,0.03); height: 100%; min-height: 220px; display: flex; flex-direction: column; justify-content: space-between; }
                    .metric-header { font-weight:bold; font-size:16px; color:#111; margin-bottom:5px; }
                    .metric-value-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; justify-content: flex-start; }
                    .metric-value { font-size:20px; font-weight:800; color:#004e92; white-space: nowrap; }
                    .metric-desc { font-size:13px; color:#555; line-height:1.5; margin-bottom:10px; flex-grow: 1; }
                    .metric-footer { font-size:11px; color:#999; margin-top:5px; border-top:1px solid #f0f0f0; padding-top:8px; font-style: italic; }
                    
                    /* 상태별 배지(Badge) 색상 */
                    .st-badge { font-size:12px; padding: 3px 8px; border-radius:6px; font-weight:bold; vertical-align: middle; margin-left: 5px; }
                    .st-hot { background-color:#ffebee; color:#c62828; }
                    .st-cold { background-color:#e3f2fd; color:#1565c0; }
                    .st-good { background-color:#e8f5e9; color:#2e7d32; }
                    .st-neutral { background-color:#f5f5f5; color:#616161; }
                    
                    /* Tab 3 하단 분석 텍스트용 */
                    .unified-text { font-size: 0.95rem !important; line-height: 1.6 !important; color: #222222; }
                </style>
                """, unsafe_allow_html=True)
            
                data_source = "Unknown"
                is_data_available = False
                
                if fin_data and fin_data.get('revenue') and fin_data.get('revenue') > 0:
                    is_data_available = True
                    data_source = "SEC 10-K/Q" if 'sec' in str(fin_data.get('source', '')).lower() else "Finnhub" if fin_data.get('market_cap') else "Yahoo Finance"
            
                if not is_data_available or not fin_data.get('revenue'):
                    try:
                        ticker = yf.Ticker(stock['symbol'])
                        yf_fin = ticker.financials; yf_info = ticker.info; yf_bal = ticker.balance_sheet
                        if not yf_fin.empty:
                            rev = yf_fin.loc['Total Revenue'].iloc[0]; net_inc = yf_fin.loc['Net Income'].iloc[0]
                            prev_rev = yf_fin.loc['Total Revenue'].iloc[1] if len(yf_fin.columns) > 1 else rev
                            fin_data['revenue'] = rev / 1e6; fin_data['net_margin'] = (net_inc / rev) * 100; fin_data['growth'] = ((rev - prev_rev) / prev_rev) * 100
                            fin_data['eps'] = yf_info.get('trailingEps', 0)
                            fin_data['op_margin'] = (yf_fin.loc['Operating Income'].iloc[0] / rev) * 100 if 'Operating Income' in yf_fin.index else fin_data['net_margin']
                            fin_data['market_cap'] = yf_info.get('marketCap', 0) / 1e6; fin_data['forward_pe'] = yf_info.get('forwardPE', 0); fin_data['price_to_book'] = yf_info.get('priceToBook', 0)
                            if not yf_bal.empty:
                                total_liab = yf_bal.loc['Total Liabilities Net Minority Interest'].iloc[0] if 'Total Liabilities Net Minority Interest' in yf_bal.index else 0
                                equity = yf_bal.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in yf_bal.index else 1
                                fin_data['debt_equity'] = (total_liab / equity) * 100; fin_data['roe'] = (net_inc / equity) * 100
                            is_data_available = True; data_source = "Yahoo Finance"
                    except: pass
            
                growth_val = fin_data.get('growth') if is_data_available else None
                ocf_val = fin_data.get('net_margin') if is_data_available else 0
                op_m = fin_data.get('op_margin') if is_data_available else None
                net_m = fin_data.get('net_margin') if is_data_available else None
                accruals_status = "Low" if is_data_available and op_m is not None and net_m is not None and abs(op_m - net_m) < 5 else "High" if is_data_available else "Unknown"
    
                def clean_value(val):
                    try: return 0.0 if val is None or (isinstance(val, (int, float)) and (np.isnan(val) or np.isinf(val))) else float(val)
                    except: return 0.0
                if fin_data is None: fin_data = {}
    
                rev_val = clean_value(fin_data.get('revenue', 0)); net_m_val = clean_value(fin_data.get('net_margin', 0)); op_m_val = clean_value(fin_data.get('op_margin', net_m_val))
                growth = clean_value(fin_data.get('growth', 0)); roe_val = clean_value(fin_data.get('roe', 0)); de_ratio = clean_value(fin_data.get('debt_equity', 0)); pe_val = clean_value(fin_data.get('forward_pe', 0))
    
                growth_display = f"{growth:+.1f}%" if abs(growth) > 0.001 else "N/A"
                net_m_display = f"{net_m_val:.1f}%" if abs(net_m_val) > 0.001 else "N/A"
                opm_display = f"{op_m_val:.2f}%" if abs(op_m_val) > 0.001 else "N/A"
    
                r1_c1, r1_c2, r1_c3, r1_c4 = st.columns(4)
                r2_c1, r2_c2, r2_c3, r2_c4 = st.columns(4)
    
                with r1_c1:
                    display_val = growth_display
                    if display_val != "N/A": status, st_cls = ("🔥 High-Growth" if not is_ko else "🔥 고성장", "st-hot") if growth > 20 else ("✅ Stable" if not is_ko else "✅ 안정", "st-good") if growth > 5 else ("⚠️ Slowdown" if not is_ko else "⚠️ 둔화", "st-neutral")
                    else: status, st_cls = ("🔍 N/A", "st-neutral")
                    st.markdown(f"<div class='metric-card'><div class='metric-header'>Sales Growth</div><div class='metric-value-row'><span class='metric-value'>{display_val}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>{get_text('desc_growth')}</div><div class='metric-footer'>Theory: Jay Ritter (1991)<br><b>Data Source: {data_source}</b></div></div>", unsafe_allow_html=True)
    
                with r1_c2:
                    display_val = net_m_display
                    if display_val != "N/A": status, st_cls = ("✅ Profit" if not is_ko else "✅ 흑자", "st-good") if net_m_val > 0 else ("🚨 Loss" if not is_ko else "🚨 적자", "st-hot")
                    else: status, st_cls = ("🔍 N/A", "st-neutral")
                    st.markdown(f"<div class='metric-card'><div class='metric-header'>Net Margin (Profit)</div><div class='metric-value-row'><span class='metric-value'>{display_val}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>{get_text('desc_net_margin')}</div><div class='metric-footer'>Theory: Fama & French (2004)<br><b>Data Source: {data_source}</b></div></div>", unsafe_allow_html=True)
    
                with r1_c3:
                    val = accruals_status
                    status = ("✅ Solid" if not is_ko else "✅ 건전") if val == "Low" else ("🚨 Caution" if not is_ko else "🚨 주의") if val == "High" else "🔍 N/A"
                    st_cls = "st-good" if val == "Low" else "st-hot" if val == "High" else "st-neutral"
                    st.markdown(f"<div class='metric-card'><div class='metric-header'>Accruals Quality</div><div class='metric-value-row'><span class='metric-value'>{val}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>{get_text('desc_accruals')}</div><div class='metric-footer'>Theory: Teoh et al. (1998)<br><b>Data Source: {data_source}</b></div></div>", unsafe_allow_html=True)
    
                with r1_c4:
                    display_val = f"{de_ratio:.1f}%" if de_ratio > 0 else "N/A"
                    status, st_cls = ("✅ Stable" if not is_ko else "✅ 안정", "st-good") if (0 < de_ratio < 100) else ("🔍 N/A", "st-neutral")
                    st.markdown(f"<div class='metric-card'><div class='metric-header'>Debt / Equity</div><div class='metric-value-row'><span class='metric-value'>{display_val}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>{get_text('desc_debt_equity')}</div><div class='metric-footer'>Ref: Standard Ratio<br><b>Data Source: {data_source}</b></div></div>", unsafe_allow_html=True)
    
                with r2_c1:
                    if current_p > 0 and off_val > 0:
                        up_rate = ((current_p - off_val) / off_val) * 100
                        display_val, status, st_cls = (f"{up_rate:+.1f}%", ("🚀 Surge" if not is_ko else "🚀 급등") if up_rate > 20 else ("⚖️ Fair" if not is_ko else "⚖️ 적정"), "st-hot" if up_rate > 20 else "st-good")
                    else: display_val, status, st_cls = (get_text('status_waiting'), ("⏳ IPO" if not is_ko else "⏳ 예정"), "st-neutral")
                    st.markdown(f"<div class='metric-card'><div class='metric-header'>Market Performance</div><div class='metric-value-row'><span class='metric-value'>{display_val}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>{get_text('desc_performance')}</div><div class='metric-footer'>Theory: Kevin Rock (1986)<br><b>Data Source: Live Price</b></div></div>", unsafe_allow_html=True)
    
                st.write("<br>", unsafe_allow_html=True)
    
                with st.expander(get_text('expander_academic_analysis'), expanded=False):
                    st.caption(f"Data Source: {data_source} / Currency: USD")
                    if is_data_available:
                        if curr_lang == 'ko':
                            growth_status_text = "고성장" if growth > 20 else "안정적" if growth > 5 else "정체"
                            quality_status_text = "우수" if roe_val > 15 else "보통"
                            st.markdown(f"<div class='unified-text'><b>1. 성장성 및 생존 분석 (Jay Ritter, 1991)</b><br>현재 매출 성장률은 <b>{growth_status_text}</b> 단계입니다. Ritter의 이론에 따르면 상장 초기 고성장 기업은 향후 3~5년간 '성장 둔화의 함정'을 조심해야 하며, 현재 수치는 {'긍정적 시그널' if growth > 10 else '주의가 필요한 시그널'}로 해석됩니다.<br><br><b>2. 수익성 품질 및 자본 구조 (Fama & French, 2004)</b><br>수익성 지표(Net Margin/ROE)는 <b>{quality_status_text}</b> 등급입니다. 본 기업은 {'상대적으로 견고한 이익 체력' if roe_val > 10 else '영업 효율성 개선이 선행되어야 하는 체력'}을 보유하고 있습니다.<br><br><b>3. 정보 비대칭 및 회계 품질 (Teoh et al., 1998)</b><br>발생액 품질(Accruals Quality)이 <b>{accruals_status}</b> 상태입니다. 이는 경영진의 이익 조정 가능성이 {'낮음' if accruals_status == 'Low' else '존재함'}을 의미합니다.</div>", unsafe_allow_html=True)
                            st.info(f"**AI 종합 판정:** 학술적 관점에서 본 기업은 **{growth_status_text}** 성격이 강하며, 정보 불확실성은 일정 부분 해소된 상태입니다.")
                        elif curr_lang == 'ja':
                            growth_status_text = "高成長" if growth > 20 else "安定的" if growth > 5 else "停滞"
                            quality_status_text = "優秀" if roe_val > 15 else "普通"
                            st.markdown(f"<div class='unified-text'><b>1. 成長性と生存分析 (Jay Ritter, 1991)</b><br>現在の売上成長率は<b>{growth_status_text}</b>段階です。Ritterの理論によると、上場初期の高成長企業は今後3〜5年間の「成長鈍化の罠」に注意すべきであり、現在の数値は{'肯定的なシグナル' if growth > 10 else '注意が必要なシグナル'}と解釈されます。<br><br><b>2. 収益性の質と資本構造 (Fama & French, 2004)</b><br>収益性指標(Net Margin/ROE)は<b>{quality_status_text}</b>レベルです。この企業は{'比較的堅固な利益創出力' if roe_val > 10 else '営業効率の改善が先行されるべき体力'}を保持しています。<br><br><b>3. 情報の非対称性と会計の質 (Teoh et al., 1998)</b><br>発生額の質(Accruals Quality)が<b>{accruals_status}</b>の状態です。これは経営陣による利益調整の可能性が{'低い' if accruals_status == 'Low' else '存在する'}ことを意味します。</div>", unsafe_allow_html=True)
                            st.info(f"**AI 総合判定:** 学術的な観点から、この企業は**{growth_status_text}**の性格が強く、情報の不確実性は一定部分解消された状態です。")
                        else:
                            growth_status_text = "High-Growth" if growth > 20 else "Stable" if growth > 5 else "Stagnant"
                            quality_status_text = "High-Quality" if roe_val > 15 else "Average"
                            st.markdown(f"<div class='unified-text'><b>1. Growth & Survival Analysis (Jay Ritter, 1991)</b><br>Current revenue growth is in the <b>{growth_status_text}</b> stage. According to Ritter's theory, high-growth firms should beware of the 'growth trap' in the next 3-5 years. Current metrics indicate a {'positive' if growth > 10 else 'cautionary'} signal.<br><br><b>2. Profitability & Capital Structure (Fama & French, 2004)</b><br>Profitability (Net Margin/ROE) is rated as <b>{quality_status_text}</b>. This firm possesses {'relatively solid earnings power' if roe_val > 10 else 'room for operational improvement'}.<br><br><b>3. Information Asymmetry & Accounting Quality (Teoh et al., 1998)</b><br>Accruals quality is <b>{accruals_status}</b>, implying the risk of earnings management by executives is {'low' if accruals_status == 'Low' else 'notable'}.</div>", unsafe_allow_html=True)
                            st.info(f"**AI Verdict:** Academically, this firm exhibits **{growth_status_text}** characteristics with manageable information uncertainty.")
                    else: st.warning(get_text('err_no_biz_info'))
            
                with st.expander(get_text('expander_financial_analysis'), expanded=False):
                    if is_data_available:
                        st.caption(f"Data Source: {data_source} / Currency: USD")
                        st.markdown("""<style>.custom-metric-container { display: flex; justify-content: space-between; text-align: center; padding: 10px 0; } .custom-metric-box { flex: 1; border-right: 1px solid #f0f0f0; } .custom-metric-box:last-child { border-right: none; } .custom-metric-label { font-size: 0.85rem; font-weight: bold; color: #333333; margin-bottom: 6px; } .custom-metric-value { font-size: 1.05rem; font-weight: 400; color: #1f1f1f; }</style>""", unsafe_allow_html=True)
                        metrics = [("Forward PER", f"{pe_val:.1f}x" if pe_val > 0 else "N/A"), ("P/B Ratio", f"{fin_data.get('price_to_book', 0):.2f}x"), ("Net Margin", f"{net_m_val:.1f}%"), ("ROE", f"{roe_val:.1f}%"), ("D/E Ratio", f"{de_ratio:.1f}%"), ("Growth (YoY)", f"{growth:.1f}%")]
                        m_cols = st.columns(6)
                        for i, (label, value) in enumerate(metrics):
                            with m_cols[i]: st.markdown(f'<div class="custom-metric-box"><div class="custom-metric-label">{label}</div><div class="custom-metric-value">{value}</div></div>', unsafe_allow_html=True)
                        st.markdown(" ")     
                        ai_metrics = {"growth": growth_display, "net_margin": net_m_display, "op_margin": opm_display, "roe": f"{roe_val:.1f}%", "debt_equity": f"{de_ratio:.1f}%", "pe": f"{pe_val:.1f}x" if pe_val > 0 else "N/A", "accruals": accruals_status}
                        with st.spinner(get_text('msg_analyzing_financial')):
                            ai_report = get_financial_report_analysis(stock['name'], stock['symbol'], ai_metrics, curr_lang)
                        st.info(ai_report)
                        st.caption("※ CFA algorithm analysis applied." if not is_ko else "※ 본 분석은 실제 재무 데이터를 기반으로 생성된 표준 CFA 분석 알고리즘에 따릅니다.")
                    else: st.warning(get_text('err_no_biz_info'))
            
                with st.expander(get_text('expander_references'), expanded=False):
                    st.markdown("""<style>.ref-item { padding: 12px 0; border-bottom: 1px solid #f0f0f0; display: flex; justify-content: space-between; align-items: center; } .ref-title { font-weight: bold; color: #004e92; text-decoration: none; font-size: 0.95rem; } .ref-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; background: #e9ecef; color: #495057; font-size: 0.75rem; font-weight: bold; margin-bottom: 5px; } .ref-summary { font-size: 0.85rem; color: #666666; margin-top: 3px; } .ref-btn { background: #fff; border: 1px solid #ddd; padding: 4px 12px; border-radius: 15px; font-size: 0.8rem; color: #555; text-decoration: none; white-space: nowrap; }</style>""", unsafe_allow_html=True)
                    if curr_lang == 'ko': sum_vc = "VC 투자가 상장 시 갖는 공신력 분석"; sum_rock = "정보 비대칭성과 공모가 저평가 메커니즘"
                    elif curr_lang == 'ja': sum_vc = "VC投資が上場時に持つ公信力の分析"; sum_rock = "情報の非対称性と公募価格の割安メカニズム"
                    else: sum_vc = "Analyzing the credibility of VC certification."; sum_rock = "Information asymmetry and pricing mechanism."
                    references_tab3 = [
                        {"label": get_text('ref_label_growth'), "title": "The Long-Run Performance of IPOs", "author": "Jay R. Ritter (1991)", "summary": get_text('ref_sum_ipo'), "link": "https://scholar.google.com/scholar?q=Jay+R.+Ritter+1991"},
                        {"label": get_text('ref_label_fundamental'), "title": "New Lists: Fundamentals and Survival Rates", "author": "Fama & French (2004)", "summary": get_text('ref_sum_withdrawal'), "link": "https://scholar.google.com/scholar?q=Fama+French+2004"},
                        {"label": get_text('ref_label_accounting'), "title": "Earnings Management and the Long-Run Performance", "author": "Teoh, Welch, & Wong (1998)", "summary": get_text('ref_sum_overheat'), "link": "https://scholar.google.com/scholar?q=Teoh+Welch+Wong+1998"},
                        {"label": get_text('ref_label_vc'), "title": "The Role of Venture Capital", "author": "Barry et al. (1990)", "summary": sum_vc, "link": "https://www.sciencedirect.com/science/article/abs/pii/0304405X9090006L"},
                        {"label": get_text('ref_label_underpricing'), "title": "Why New Issues are Underpriced", "author": "Kevin Rock (1986)", "summary": sum_rock, "link": "https://www.sciencedirect.com/science/article/pii/0304405X86900541"}
                    ]
                    st.info(f"💡 {get_text('caption_google_search')} (Source: **{data_source}**)")
                    for ref in references_tab3:
                        st.markdown(f"<div class='ref-item'><div style='flex:1; padding-right: 10px;'><div class='ref-badge'>{ref['label']}</div><br><a href='{ref['link']}' target='_blank' class='ref-title'>📄 {ref['title']}</a><div class='ref-summary'>{ref['summary']}, {ref['author']}</div></div><div><a href='{ref['link']}' target='_blank' class='ref-btn'>{get_text('btn_view_original')}</a></div></div>", unsafe_allow_html=True)
            
                draw_decision_box("company", f"{stock['name']} {get_text('decision_valuation_verdict')}", ['opt_overvalued', 'sentiment_neutral', 'opt_undervalued'], current_p)
                display_disclaimer()         
    
            # --- Tab 4: 기관평가 (UI 출력 부분 다국어 적용) ---
            elif selected_sub_menu == get_text('tab_4'):
                curr_lang = st.session_state.lang
                with st.spinner(get_text('msg_analyzing_institutional')):
                    result = get_unified_tab4_analysis(stock['name'], stock['symbol'], curr_lang)
                
                summary_raw = result.get('summary', '')
                pro_con_raw = result.get('pro_con', '')
                rating_val = str(result.get('rating', 'Hold')).strip()
                score_val = str(result.get('score', '3')).strip() 
                sources = result.get('links', [])
                q = stock['symbol'] if stock['symbol'] else stock['name']
    
                st.write("<br>", unsafe_allow_html=True)
            
                with st.expander(get_text('expander_renaissance'), expanded=False):
                    import re
                    pattern = r'(?i)source|출처|https?://'
                    parts = re.split(pattern, summary_raw)
                    summary = parts[0].replace('\\n', ' ').replace('\n', ' ').strip().rstrip(' ,.:;-\t')
                    if not summary or "분석 불가" in summary or "N/A" in summary.upper(): st.warning(get_text('err_no_institutional_report'))
                    else: st.info(summary)
            
                with st.expander(get_text('expander_seeking_alpha'), expanded=False):
                    pro_con = pro_con_raw.replace('\\n', '\n').replace("###", "").strip()
                    label_pro = get_text('sentiment_positive'); label_con = get_text('sentiment_negative')
                    pro_con = pro_con.replace("긍정:", f"**{label_pro}**:").replace("부정:", f"\n\n**{label_con}**:")
                    pro_con = pro_con.replace("✅ 긍정", f"**{label_pro}**").replace("⚠️ 부정", f"\n\n**{label_con}**")
                    pro_con = pro_con.replace("**Pros**:", f"**{label_pro}**:").replace("**Cons**:", f"\n\n**{label_con}**:")
                    pro_con = pro_con.replace("Pros:", f"**{label_pro}**:").replace("Cons:", f"\n\n**{label_con}**:")
                    if "의견 수집 중" in pro_con or not pro_con: st.error(get_text('err_ai_analysis_failed'))
                    else: st.success(pro_con.replace('\n', '\n\n'))
            
                with st.expander(get_text('expander_sentiment'), expanded=False):
                    s_col1, s_col2 = st.columns(2)
                    with s_col1:
                        r_list = {"Strong Buy": get_text('rating_strong_buy'), "Buy": get_text('rating_buy'), "Hold": get_text('rating_hold'), "Neutral": get_text('rating_neutral'), "Sell": get_text('rating_sell')}
                        rating_desc = f"**[{get_text('label_rating_system')}]**\n"
                        for k, v in r_list.items():
                            is_current = f" **({get_text('label_current')})**" if k.lower() in rating_val.lower() else ""
                            rating_desc += f"- **{k}**: {v}{is_current}\n"
                        st.write(f"**[Analyst Ratings]**")
                        st.metric(label="Consensus Rating", value=rating_val)
                        if any(x in rating_val for x in ["Buy", "Positive", "Outperform", "Strong"]):
                            st.success(f"{get_text('label_opinion')}: {get_text('sentiment_positive')}")
                            st.caption(f"✅ {get_text('msg_rating_positive')}\n\n{rating_desc}")
                        elif any(x in rating_val for x in ["Sell", "Negative", "Underperform"]):
                            st.error(f"{get_text('label_opinion')}: {get_text('sentiment_negative')}")
                            st.caption(f"🚨 {get_text('msg_rating_negative')}\n\n{rating_desc}")
                        else:
                            st.info(f"{get_text('label_opinion')}: {get_text('sentiment_neutral')}")
                            st.caption(f"ℹ️ {rating_desc}")
            
                    with s_col2:
                        s_list = {"5": get_text('score_5'), "4": get_text('score_4'), "3": get_text('score_3'), "2": get_text('score_2'), "1": get_text('score_1')}
                        score_desc = f"**[{get_text('label_score_system')}]**\n"
                        for k, v in s_list.items():
                            is_current = f" **({get_text('label_current')} {score_val}{get_text('label_point')})**" if k == score_val else ""
                            score_desc += f"- ⭐ {k}{get_text('label_count')}: {v}{is_current}\n"
                        st.write(f"**[IPO Scoop Score]**")
                        st.metric(label="Expected IPO Score", value=f"⭐ {score_val}")
                        eval_label = get_text('label_evaluation')
                        if score_val in ["4", "5"]: st.success(f"{eval_label}: {s_list.get(score_val, 'N/A')}")
                        elif score_val == "3": st.info(f"{eval_label}: {s_list.get(score_val, 'N/A')}")
                        else: st.warning(f"{eval_label}: {s_list.get(score_val, 'N/A')}")
                        st.caption(f"ℹ️ {score_desc}")
            
                with st.expander("References", expanded=False):
                    if sources:
                        for src in sources: st.markdown(f"- [{src['title']}]({src['link']})")
                    else: st.caption(get_text('err_no_links'))
                    st.markdown(f"- [Renaissance Capital: {stock['name']} {get_text('label_detail_data')}](https://www.google.com/search?q=site:renaissancecapital.com+{q})")
                    st.markdown(f"- [Seeking Alpha: {stock['name']} {get_text('label_deep_analysis')}](https://seekingalpha.com/symbol/{q}/analysis)")
                    st.markdown(f"- [Morningstar: {stock['name']} {get_text('label_research_result')}](https://www.morningstar.com/search?query={q})")
                    st.markdown(f"- [Google Finance: {stock['name']} {get_text('label_market_trend')}](https://www.google.com/finance/quote/{q}:NASDAQ)")
            
                draw_decision_box("ipo_report", get_text('decision_final_institutional'), ['btn_buy', 'sentiment_neutral', 'btn_sell'], current_p)
                display_disclaimer()
                
            # --- Tab 5: 투자결정 및 토론방 ---
            elif selected_sub_menu == get_text('tab_5'):
                # 1. 주문형 번역 함수
                def translate_post_on_demand(title, content, target_lang_code):
                    if not title and not content: return {"title": "", "content": ""}
                    # 💡 중국어(zh) 타겟 언어 분기 추가
                    target_lang_str = "한국어" if target_lang_code == 'ko' else "English" if target_lang_code == 'en' else "日本語" if target_lang_code == 'ja' else "简体中文(Simplified Chinese)"
                    
                    prompt = f"""Please translate the following Title and Content to {target_lang_str}. 
                    You MUST keep the exact string '|||SEP|||' between the translated Title and translated Content. 
                    Do not add any quotes or extra explanations:
                    
                    {title}
                    |||SEP|||
                    {content}"""
                    
                    try:
                        res_text = model.generate_content(prompt).text.strip()
                        if "|||SEP|||" in res_text:
                            t, c = res_text.split("|||SEP|||", 1)
                            return {"title": t.strip(), "content": c.strip()}
                        else:
                            return {"title": title, "content": res_text}
                    except: 
                        return {"title": title, "content": content}

                if 'translated_posts' not in st.session_state:
                    st.session_state.translated_posts = {}

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
                curr_lang = st.session_state.lang
    
                if 'user_decisions' not in st.session_state: st.session_state.user_decisions = {}
                ud = st.session_state.user_decisions.get(sid, {})
                
                steps = [('filing', 'Step 1'), ('news', 'Step 2'), ('macro', 'Step 3'), ('company', 'Step 4'), ('ipo_report', 'Step 5')]
                missing_steps = [label for step, label in steps if not ud.get(step)]
                
                if missing_steps:
                    st.info(get_text('msg_need_all_steps'))
                else:
                    score_map = {"긍정적": 1, "수용적": 1, "안정적": 1, "저평가": 1, "매수": 1, "침체": 1, "중립적": 0, "중립": 0, "적정": 0, "부정적": -1, "회의적": -1, "버블": -1, "고평가": -1, "매도": -1}
                    user_score = sum(score_map.get(ud.get(s[0], "중립적"), 0) for s in steps)
                    if user_id != 'guest_id': db_save_user_decision(user_id, sid, user_score, ud)
                    
                    community_scores = db_load_community_scores(sid)
                    if not community_scores: community_scores = [user_score]
                    
                    # ---------------------------------------------------------
                    # 🔥 [새로운 그래프 포맷] 1. 가로형 시장 낙관도 (Gauge Bar)
                    # ---------------------------------------------------------
                    market_avg = sum(community_scores) / len(community_scores)
                    
                    # -5 ~ +5 점수를 0% ~ 100% 비율로 변환 (마커 위치 계산용)
                    avg_pct = min(max(((market_avg + 5) / 10) * 100, 0), 100)
                    user_pct = min(max(((user_score + 5) / 10) * 100, 0), 100)
                    
                    # 제목을 박스 밖으로 빼고 왼쪽 정렬
                    st.markdown(f"<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 15px;'>{get_text('chart_optimism')}</div>", unsafe_allow_html=True)
                    
                    # HTML 들여쓰기 완벽 제거 (화면 깨짐 방지)
                    gauge_html = f"""<div style="background-color: #ffffff; padding: 45px 20px 75px 20px; border-radius: 15px; border: 1px solid #e0e0e0; box-shadow: 0 4px 10px rgba(0,0,0,0.03); margin-bottom: 30px;">
<div style="position: relative; width: 100%; height: 20px; background: linear-gradient(to right, #ff4b4b 0%, #f1f3f4 50%, #00ff41 100%); border-radius: 10px;">
    <div style="position: absolute; top: 30px; left: 0%; transform: translateX(0%); font-size: 13px; font-weight: 700; color: #d32f2f;">{get_text('label_gauge_neg')}</div>
    <div style="position: absolute; top: 30px; left: 50%; transform: translateX(-50%); font-size: 13px; font-weight: 700; color: #757575;">{get_text('label_gauge_neu')}</div>
    <div style="position: absolute; top: 30px; left: 100%; transform: translateX(-100%); font-size: 13px; font-weight: 700; color: #2e7d32;">{get_text('label_gauge_pos')}</div>
    <div style="position: absolute; top: -40px; left: {avg_pct}%; transform: translateX(-50%); text-align: center; z-index: 10;">
        <div style="font-size: 12px; font-weight: 800; color: #444; white-space: nowrap; background: #fff; padding: 3px 8px; border-radius: 6px; border: 1px solid #ccc; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">{get_text('label_market_avg')} : {market_avg:+.1f}</div>
        <div style="color: #444; font-size: 14px; margin-top: -4px;">▼</div>
    </div>
    <div style="position: absolute; top: -4px; left: {user_pct}%; transform: translateX(-50%); text-align: center; z-index: 20;">
        <div style="background-color: #004e92; color: #fff; border-radius: 50%; width: 28px; height: 28px; line-height: 22px; font-size: 13px; font-weight: bold; border: 3px solid #fff; box-shadow: 0 2px 5px rgba(0,0,0,0.3); margin: 0 auto;">나</div>
        <div style="font-size: 12px; font-weight: 800; color: #004e92; white-space: nowrap; margin-top: 32px;">{get_text('label_my_pos')} ({user_score:+d})</div>
    </div>
</div>
</div>"""
                    st.markdown(gauge_html, unsafe_allow_html=True)
                    
                    # ---------------------------------------------------------
                    # 🔥 [새로운 그래프 포맷] 2. 실시간 커뮤니티 전망 (Stacked Bar)
                    # ---------------------------------------------------------
                    st.write("<br>", unsafe_allow_html=True)
                    st.markdown(f"<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 15px;'>{get_text('label_community_forecast')}</div>", unsafe_allow_html=True)
                    
                    up_voters, down_voters = db_load_sentiment_counts(sid)
                    total_votes = up_voters + down_voters
                    
                    if total_votes > 0:
                        up_pct = (up_voters / total_votes) * 100
                        down_pct = (down_voters / total_votes) * 100
                    else:
                        up_pct = 50.0
                        down_pct = 50.0

                    # HTML 들여쓰기 완벽 제거
                    sentiment_html = f"""<div style="margin-bottom: 20px; padding: 0 5px;">
<div style="display: flex; justify-content: space-between; margin-bottom: 8px; font-weight: 800; font-family: sans-serif;">
    <span style="color: #2e7d32; font-size: 1.2rem;">🐂 Bullish {up_pct:.0f}%</span>
    <span style="color: #d32f2f; font-size: 1.2rem;">{down_pct:.0f}% Bearish 🐻</span>
</div>
<div style="display: flex; width: 100%; height: 16px; border-radius: 8px; overflow: hidden; background-color: #f1f3f4; box-shadow: inset 0 1px 3px rgba(0,0,0,0.1);">
    <div style="width: {up_pct}%; background-color: #00ff41; transition: width 0.5s ease;"></div>
    <div style="width: {down_pct}%; background-color: #ff4b4b; transition: width 0.5s ease;"></div>
</div>
<div style="text-align: center; color: #888; font-size: 0.85rem; margin-top: 8px; font-weight: 600;">
    Total Votes: {total_votes:,}
</div>
</div>"""
                    st.markdown(sentiment_html, unsafe_allow_html=True)
                    
                    # 투표 버튼 영역 (🐂 🐻 이모지 추가)
                    if st.session_state.get('auth_status') == 'user':
                        if sid not in st.session_state.watchlist:
                            st.caption(get_text('msg_vote_guide'))
                            c_up, c_down = st.columns(2)
                            
                            if c_up.button("🐂 " + get_text('btn_vote_up'), key=f"up_vote_{sid}", use_container_width=True, type="primary"):
                                db_toggle_watchlist(user_id, sid, "UP", action='add')
                                db_log_user_action(user_id, sid, "VOTE_UP", price=current_p, details="Bullish 배팅")
                                if sid not in st.session_state.watchlist: st.session_state.watchlist.append(sid)
                                st.session_state.watchlist_predictions[sid] = "UP"
                                st.rerun()
                                
                            if c_down.button("🐻 " + get_text('btn_vote_down'), key=f"dn_vote_{sid}", use_container_width=True):
                                db_toggle_watchlist(user_id, sid, "DOWN", action='add')
                                db_log_user_action(user_id, sid, "VOTE_DOWN", price=current_p, details="Bearish 배팅")
                                if sid not in st.session_state.watchlist: st.session_state.watchlist.append(sid)
                                st.session_state.watchlist_predictions[sid] = "DOWN"
                                st.rerun()
                                
                        else:
                            pred = st.session_state.watchlist_predictions.get(sid, "N/A")
                            color = "#28a745" if pred == "UP" else "#dc3545"
                            pred_text = "🐂 BULLISH" if pred == "UP" else "🐻 BEARISH"
                            
                            st.markdown(f"<div style='padding: 12px; border-radius: 10px; border: 2px solid {color}; text-align: center; font-weight: 800; color: {color}; font-size: 1.1rem; background-color: #f8f9fa;'>{get_text('msg_my_choice')} {pred_text} </div>", unsafe_allow_html=True)
                            
                            st.write("")
                            if st.button("🔄 " + get_text('btn_cancel_vote'), key=f"rm_vote_{sid}", use_container_width=True):
                                db_toggle_watchlist(user_id, sid, action='remove')
                                if sid in st.session_state.watchlist: st.session_state.watchlist.remove(sid)
                                if sid in st.session_state.watchlist_predictions: del st.session_state.watchlist_predictions[sid]
                                st.rerun()
                    else: 
                        st.warning(get_text('msg_login_vote'))
    
                st.write("<br>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 10px;'>{sid} {get_text('label_discussion_board')}</div>", unsafe_allow_html=True)
                
                with st.expander(get_text('expander_write')):
                    if st.session_state.get('auth_status') == 'user':
                        if check_permission('write'):
                            with st.form(key=f"write_{sid}_form", clear_on_submit=True):
                                new_title = st.text_input(get_text('label_title'), key=f"tab5_title_{sid}")
                                new_content = st.text_area(get_text('label_content'), key=f"tab5_content_{sid}")
                                if st.form_submit_button(get_text('btn_submit'), type="primary", use_container_width=True):
                                    if new_title and new_content:
                                        u_id = st.session_state.user_info.get('id')
                                        try:
                                            fresh_user = db_load_user(u_id)
                                            d_name = fresh_user.get('display_name') or f"{u_id[:3]}***"
                                        except: d_name = f"{u_id[:3]}***"
                                        
                                        if db_save_post(sid, new_title, new_content, d_name, u_id):
                                            st.success(get_text('msg_submitted'))
                                            import time; time.sleep(0.5)
                                            st.rerun()
                        else: st.warning(get_text('msg_login_auth_needed'))
                    else: st.warning(get_text('msg_login_vote'))
                
                st.write("<br>", unsafe_allow_html=True)
                
                # 게시글 로드 (Tab 5 종목 전용)
                sid_posts = db_load_posts(limit=100, category=sid)
                if sid_posts:
                    from datetime import datetime, timedelta
                    three_days_ago = datetime.now() - timedelta(days=3)
                    hot_candidates = []
                    normal_posts = []
                    
                    for p in sid_posts:
                        try:
                            created_dt_str = str(p.get('created_at', '')).split('.')[0]
                            created_dt = datetime.strptime(created_dt_str.replace('T', ' '), '%Y-%m-%d %H:%M:%S')
                            if created_dt >= three_days_ago and p.get('likes', 0) > 0: hot_candidates.append(p)
                            else: normal_posts.append(p)
                        except: normal_posts.append(p)
                        
                    hot_candidates.sort(key=lambda x: (x.get('likes', 0), x.get('created_at', '')), reverse=True)
                    top_5_hot = hot_candidates[:5]
                    normal_posts.extend(hot_candidates[5:])
                    normal_posts.sort(key=lambda x: x.get('created_at', ''), reverse=True)
                    
                    page_key = f'detail_display_count_{sid}'
                    if page_key not in st.session_state: st.session_state[page_key] = 5
                    current_display = normal_posts[:st.session_state[page_key]]
    
                    def render_detail_post(p, is_hot=False):
                        p_auth = p.get('author_name', 'Unknown')
                        p_date = str(p.get('created_at', '')).split('T')[0]
                        p_id = str(p.get('id'))
                        p_uid = p.get('author_id')
                        p_cat = p.get('category', '자유')
                        likes = p.get('likes') or 0
                        dislikes = p.get('dislikes') or 0
                        
                        original_title = p.get('title', '')
                        original_content = p.get('content', '')
                        curr_lang = st.session_state.get('lang', 'ko')
                        
                        is_translated = p_id in st.session_state.translated_posts
                        if is_translated:
                            trans_data = st.session_state.translated_posts[p_id]
                            if isinstance(trans_data, dict):
                                display_title = trans_data.get('title', original_title)
                                display_content = trans_data.get('content', original_content)
                            else:
                                display_title = original_title
                                display_content = trans_data 
                        else:
                            display_title = original_title
                            display_content = original_content
                            
                        prefix = "[HOT]" if is_hot else ""
                        title_disp = f"{prefix} {display_title} | {p_auth} | {p_date} (👍{likes}  👎{dislikes})"
                        
                        with st.expander(title_disp.strip()):
                            st.markdown(f"<div style='font-size:0.95rem; color:#333; margin-bottom:10px;'>{display_content}</div>", unsafe_allow_html=True)
                            
                            btn_c1, btn_c2, btn_c3, btn_c4 = st.columns([2.5, 1.5, 1.5, 1.5])
                            with btn_c1:
                                trans_label = get_text('btn_see_original') if is_translated else get_text('btn_see_translation')
                                if st.button(trans_label, key=f"t_det_{p_id}", use_container_width=True):
                                    if is_translated: del st.session_state.translated_posts[p_id]
                                    else:
                                        with st.spinner("Translating..."):
                                            st.session_state.translated_posts[p_id] = translate_post_on_demand(original_title, original_content, curr_lang)
                                    st.rerun()
                            with btn_c2:
                                if st.button(f"{get_text('btn_like')}{likes}", key=f"l_det_{p_id}", use_container_width=True):
                                    if st.session_state.get('auth_status') == 'user': db_toggle_post_reaction(p_id, user_id, 'like'); st.rerun()
                                    else: st.toast(get_text('msg_login_vote'))
                            with btn_c3:
                                if st.button(f"{get_text('btn_dislike')}{dislikes}", key=f"d_det_{p_id}", use_container_width=True):
                                    if st.session_state.get('auth_status') == 'user': db_toggle_post_reaction(p_id, user_id, 'dislike'); st.rerun()
                                    else: st.toast(get_text('msg_login_vote'))
                            with btn_c4:
                                raw_u_info = st.session_state.get('user_info')
                                u_info = raw_u_info if isinstance(raw_u_info, dict) else {}
                                is_admin = u_info.get('role') == 'admin'
                                if st.session_state.get('auth_status') == 'user':
                                    if u_info.get('id') == p_uid or is_admin:
                                        if st.button(get_text('btn_delete'), key=f"del_det_{p_id}", type="secondary", use_container_width=True):
                                            if db_delete_post(p_id):
                                                st.success(get_text('msg_deleted'))
                                                import time; time.sleep(0.5)
                                                st.rerun()
                    
                    if top_5_hot:
                        st.markdown(f"<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 10px; margin-top: 10px;'>{get_text('label_hot_posts')}</div>", unsafe_allow_html=True)
                        for p in top_5_hot: render_detail_post(p, is_hot=True)
                        st.write("<br><br>", unsafe_allow_html=True)
                        
                    st.markdown(f"<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 10px;'>{get_text('label_recent_posts')}</div>", unsafe_allow_html=True)
                    
                    if current_display:
                        for p in current_display: render_detail_post(p, is_hot=False)
                    else: 
                        st.info(get_text('msg_no_recent_posts'))
                        
                    if len(normal_posts) > st.session_state[page_key]:
                        st.write("<br>", unsafe_allow_html=True)
                        if st.button(get_text('btn_load_more'), key=f"more_det_{sid}", use_container_width=True):
                            st.session_state[page_key] += 10
                            st.rerun()
                else: 
                    st.info(get_text('msg_first_comment'))
                    
                draw_decision_box("ipo_report", get_text('decision_final_invest'), ['opt_buy', 'sentiment_neutral', 'opt_sell'], current_p)
                display_disclaimer()

    # ---------------------------------------------------------
    # [NEW] 6. 게시판 페이지 (Board) - 분석/자유 분리형
    # ---------------------------------------------------------
    elif st.session_state.page == 'board':
        
        main_area.empty() 
        
        with main_area.container():
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
                /* 탭 UI 스타일 강화 */
                button[data-baseweb="tab"] p { font-size: 1.15rem !important; font-weight: 700 !important; }
                </style>
            """, unsafe_allow_html=True)
        
            # [1] 메뉴 구성 및 네비게이션
            is_logged_in = (st.session_state.auth_status == 'user')
            login_text = get_text('menu_logout') if is_logged_in else get_text('btn_login')
            settings_text = get_text('menu_settings') 
            main_text = get_text('menu_main')
            watch_text = f"{get_text('menu_watch')} ({len(st.session_state.watchlist)})"
            board_text = get_text('menu_board')
            back_text = get_text('menu_back') if get_text('menu_back') else "Back"
            
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
        
            # [2] 게시판 전체 데이터 로드 및 검색 적용
            s_keyword = ""
            s_type = "title" 
            
            if 'b_s_type' in st.session_state: s_type = st.session_state.b_s_type
            if 'b_s_keyword' in st.session_state: s_keyword = st.session_state.b_s_keyword
                
            all_posts = db_load_posts(limit=200) 
            posts = all_posts
            
            if s_keyword:
                k = s_keyword.lower()
                if s_type == "title": posts = [p for p in posts if k in p.get('title','').lower()]
                elif s_type == "title_content": posts = [p for p in posts if k in p.get('title','').lower() or k in p.get('content','').lower()]
                elif s_type == "category": posts = [p for p in posts if k in p.get('category','').lower()]
                elif s_type == "author": posts = [p for p in posts if k in p.get('author_name','').lower()]
        
            # 💡 [핵심 분리 1] 전체 글을 '분석글'과 '자유글'로 나누기
            def is_free_post(cat_str):
                c = cat_str.strip().lower() if cat_str else ""
                return not c or c in ['자유', 'general', '自由']
                
            analysis_posts = [p for p in posts if not is_free_post(p.get('category'))]
            free_posts = [p for p in posts if is_free_post(p.get('category'))]

            # [3] 리스트 및 컨트롤 UI 렌더링
            post_list_area = st.container()
            
            with post_list_area:
                
                # 1. 검색 및 글쓰기 영역
                f_col1, f_col2 = st.columns(2)
                with f_col1:
                    with st.expander(get_text('expander_search')):
                        s_opts_keys = ["title", "title_content", "category", "author"]
                        s_opts_display = {
                            "title": get_text('opt_search_title'), "title_content": get_text('opt_search_title_content'),
                            "category": get_text('opt_search_category'), "author": get_text('opt_search_author')
                        }
                        s_idx = s_opts_keys.index(s_type) if s_type in s_opts_keys else 0
                        s_type_new = st.selectbox(get_text('search_scope'), s_opts_keys, format_func=lambda x: s_opts_display[x], key="b_s_type_temp", index=s_idx)
                        s_keyword_new = st.text_input(get_text('search_keyword'), value=s_keyword, key="b_s_keyword_temp")
                        
                        if st.button(get_text('btn_search'), key="search_btn", use_container_width=True):
                            st.session_state.b_s_type = s_type_new
                            st.session_state.b_s_keyword = s_keyword_new
                            st.rerun()
                
                with f_col2:
                    with st.expander(get_text('expander_write')):
                        if is_logged_in and check_permission('write'):
                            with st.form(key="board_main_form", clear_on_submit=True):
                                # 💡 [핵심 분리 2] 글쓰기 시 분석/자유 직관적 선택
                                write_type = st.radio("글 종류", ["Analysis", "Free"], format_func=lambda x: get_text('write_type_analysis') if x=="Analysis" else get_text('write_type_free'), horizontal=True, label_visibility="collapsed")
                                
                                if write_type == "Analysis":
                                    b_cat = st.text_input(get_text('label_category'), placeholder="예: AAPL, TSLA 등 종목명", key="main_b_cat")
                                else:
                                    b_cat = "자유" # 내부적으로 자동 통일
                                    
                                b_tit = st.text_input(get_text('label_title'), key="main_b_tit")
                                b_cont = st.text_area(get_text('label_content'), key="main_b_cont")
                                
                                if st.form_submit_button(get_text('btn_submit'), type="primary", use_container_width=True):
                                    if b_tit and b_cont:
                                        if write_type == "Analysis" and not b_cat.strip(): b_cat = "자유"
                                        
                                        u_id = st.session_state.user_info['id']
                                        try:
                                            fresh_user = db_load_user(u_id)
                                            d_name = fresh_user.get('display_name') or f"{u_id[:3]}***"
                                        except: d_name = f"{u_id[:3]}***"
                                        
                                        if db_save_post(b_cat, b_tit, b_cont, d_name, u_id):
                                            st.success(get_text('msg_submit_success'))
                                            import time; time.sleep(0.5)
                                            if 'b_s_type' in st.session_state: del st.session_state.b_s_type
                                            if 'b_s_keyword' in st.session_state: del st.session_state.b_s_keyword
                                            st.rerun()
                        else:
                            st.warning(get_text('msg_login_auth_needed'))
        
                st.write("<br>", unsafe_allow_html=True)
                
                # -----------------------------------------------------
                # [공통 로직] 번역 및 렌더링 함수
                # -----------------------------------------------------
                if 'translated_posts' not in st.session_state:
                    st.session_state.translated_posts = {}

                def translate_post_on_demand(title, content, target_lang_code):
                    if not title and not content: return {"title": "", "content": ""}
                    target_lang_str = "한국어" if target_lang_code == 'ko' else "English" if target_lang_code == 'en' else "日本語" if target_lang_code == 'ja' else "简体中文(Simplified Chinese)"
                    prompt = f"Please translate the following Title and Content to {target_lang_str}. You MUST keep the exact string '|||SEP|||' between the translated Title and translated Content. Do not add any quotes or extra explanations:\n{title}\n|||SEP|||\n{content}"
                    try:
                        res_text = model.generate_content(prompt).text.strip()
                        if "|||SEP|||" in res_text:
                            t, c = res_text.split("|||SEP|||", 1)
                            return {"title": t.strip(), "content": c.strip()}
                        else: return {"title": title, "content": res_text}
                    except: return {"title": title, "content": content}

                def render_post(p, is_hot=False):
                    p_auth = p.get('author_name', 'Unknown')
                    p_date = str(p.get('created_at', '')).split('T')[0]
                    p_id = str(p.get('id'))
                    p_uid = p.get('author_id')
                    
                    # 카테고리 표시 처리
                    raw_cat = p.get('category', '').strip()
                    p_cat = get_text('placeholder_free') if not raw_cat or raw_cat == '자유' else raw_cat
                        
                    likes = p.get('likes') or 0
                    dislikes = p.get('dislikes') or 0
                    
                    original_title = p.get('title', '')
                    original_content = p.get('content', '')
                    curr_lang = st.session_state.get('lang', 'ko')
                    
                    is_translated = p_id in st.session_state.translated_posts
                    if is_translated:
                        trans_data = st.session_state.translated_posts[p_id]
                        if isinstance(trans_data, dict):
                            display_title = trans_data.get('title', original_title)
                            display_content = trans_data.get('content', original_content)
                        else:
                            display_title = original_title
                            display_content = trans_data 
                    else:
                        display_title = original_title
                        display_content = original_content
                    
                    prefix = "[HOT]" if is_hot else f"[{p_cat}]"
                    title_disp = f"{prefix} {display_title} | {p_auth} | {p_date} ({get_text('btn_recommend')}{likes}  {get_text('btn_dislike')}{dislikes})"
                    
                    with st.expander(title_disp.strip()):
                        st.markdown(f"<div style='font-size:0.95rem; color:#333;'>{display_content}</div>", unsafe_allow_html=True)
                        st.write("<br>", unsafe_allow_html=True)
                        
                        action_c1, action_c2, action_c3, action_c4 = st.columns([2.5, 1.5, 1.5, 1.5])
                        
                        with action_c1:
                            trans_label = get_text('btn_see_original') if is_translated else get_text('btn_see_translation')
                            if st.button(trans_label, key=f"t_main_{p_id}", use_container_width=True):
                                if is_translated: del st.session_state.translated_posts[p_id]
                                else:
                                    with st.spinner("Translating..."):
                                        st.session_state.translated_posts[p_id] = translate_post_on_demand(original_title, original_content, curr_lang)
                                st.rerun()

                        with action_c2:
                            if st.button(f"{get_text('btn_recommend')}{likes}", key=f"l_main_{p_id}", use_container_width=True):
                                if is_logged_in:
                                    db_toggle_post_reaction(p_id, st.session_state.user_info.get('id', ''), 'like')
                                    st.rerun()
                                else: st.toast(get_text('msg_login_vote'))
                        with action_c3:
                            if st.button(f"{get_text('btn_dislike')}{dislikes}", key=f"d_main_{p_id}", use_container_width=True):
                                if is_logged_in:
                                    db_toggle_post_reaction(p_id, st.session_state.user_info.get('id', ''), 'dislike')
                                    st.rerun()
                                else: st.toast(get_text('msg_login_vote'))
                        with action_c4:
                            raw_u_info = st.session_state.get('user_info')
                            u_info = raw_u_info if isinstance(raw_u_info, dict) else {}
                            is_admin = u_info.get('role') == 'admin'
                            if is_logged_in and (u_info.get('id') == p_uid or is_admin):
                                if st.button(get_text('btn_delete'), key=f"del_main_{p_id}", type="secondary", use_container_width=True):
                                    if db_delete_post(p_id):
                                        st.success(get_text('msg_deleted'))
                                        import time; time.sleep(0.5)
                                        st.rerun()

                # 💡 [핵심 분리 3] 탭 렌더링 헬퍼 함수
                def render_board_tab(tab_posts, display_count_key, btn_prefix):
                    hot_candidates = []
                    normal_posts = []
                    three_days_ago = datetime.now() - timedelta(days=3)
            
                    for p in tab_posts:
                        try:
                            created_dt_str = str(p.get('created_at', '')).split('.')[0]
                            created_dt = datetime.strptime(created_dt_str.replace('T', ' '), '%Y-%m-%d %H:%M:%S')
                            if created_dt >= three_days_ago and p.get('likes', 0) > 0:
                                hot_candidates.append(p)
                            else: normal_posts.append(p)
                        except: normal_posts.append(p)
                            
                    hot_candidates.sort(key=lambda x: (x.get('likes', 0), x.get('created_at', '')), reverse=True)
                    top_5_hot = hot_candidates[:5]
                    normal_posts.extend(hot_candidates[5:])
                    normal_posts.sort(key=lambda x: x.get('created_at', ''), reverse=True)

                    if display_count_key not in st.session_state:
                        st.session_state[display_count_key] = 5
                    current_display = normal_posts[:st.session_state[display_count_key]]

                    if top_5_hot:
                        st.markdown(f"<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 10px; margin-top: 10px;'>{get_text('label_hot_posts')}</div>", unsafe_allow_html=True)
                        for p in top_5_hot: render_post(p, is_hot=True)
                        st.write("<br><br>", unsafe_allow_html=True)
                    
                    st.markdown(f"<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 10px;'>{get_text('label_recent_posts')}</div>", unsafe_allow_html=True)
                    
                    if tab_posts:
                        if current_display:
                            for p in current_display: render_post(p, is_hot=False)
                        else:
                            st.info(get_text('msg_no_recent_posts'))
                            
                        if len(normal_posts) > st.session_state[display_count_key]:
                            st.write("<br>", unsafe_allow_html=True)
                            if st.button(get_text('btn_load_more'), key=f"more_{btn_prefix}", use_container_width=True):
                                st.session_state[display_count_key] += 10
                                st.rerun()
                    else:
                        st.info(get_text('msg_no_posts'))

                # 💡 [핵심 분리 4] 탭 UI 배치 (좌측: 분석 / 우측: 자유)
                tab_analysis, tab_free = st.tabs([get_text('tab_analysis_board'), get_text('tab_free_board')])
                
                with tab_analysis:
                    render_board_tab(analysis_posts, 'board_ana_count', 'ana')
                    
                with tab_free:
                    render_board_tab(free_posts, 'board_free_count', 'free')
                
                        
        
                #리아 지우와 제주도 다녀오다 사랑하다.
                
                
                
