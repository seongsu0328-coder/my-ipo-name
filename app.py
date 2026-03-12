import streamlit as st
import streamlit.components.v1 as components # [추가] GA4 스크립트 실행용
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
    from oauth2client.service_account import ServiceAccountCredentials
    from email.mime.text import MIMEText
    from datetime import datetime, timedelta

    # =======================================================
    # [수정] Google Analytics 4 (GA4) 연동 세팅 - Streamlit 우회 버전
    # =======================================================
    GA_ID = "G-NC5TH230ME"
    ga_script = f"""
    <script>
        // Streamlit의 격리된 상자(iframe)를 벗어나 실제 메인 창(parent)에 코드를 심습니다.
        var parentDocument = window.parent.document;
        
        // 코드가 여러 번 중복 실행되는 것을 방지합니다.
        if (!parentDocument.getElementById("google-analytics-script")) {{
            var script1 = parentDocument.createElement("script");
            script1.id = "google-analytics-script";
            script1.async = true;
            script1.src = "https://www.googletagmanager.com/gtag/js?id={GA_ID}";
            parentDocument.head.appendChild(script1);

            var script2 = parentDocument.createElement("script");
            script2.innerHTML = `
                window.dataLayer = window.dataLayer || [];
                function gtag(){{dataLayer.push(arguments);}}
                gtag('js', new Date());
                gtag('config', '{GA_ID}');
            `;
            parentDocument.head.appendChild(script2);
        }}
    </script>
    """
    components.html(ga_script, width=0, height=0)
    # =======================================================

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
            url = os.environ.get("SUPABASE_URL") or st.secrets["supabase"]["url"]
            key = os.environ.get("SUPABASE_KEY") or st.secrets["supabase"]["key"]
            return create_client(url, key)
        except Exception as e:
            st.error(f"Supabase 설정 읽기 오류: {e}")
            raise e # 상위 try문으로 에러 전달

    # 전역 Supabase 객체 생성
    supabase = init_supabase()

    # --- [AI 라이브러리] ---
    import google.generativeai as genai
    from google.generativeai import protos  
    # 💡 [핵심] from openai import OpenAI <- 이 부분이 영구 삭제되었습니다!

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

# 💡 [여기에 추가!] Tab 3 등에서 N/A, %, x 등 기호가 섞인 문자열을 숫자로 바꿔주는 전역 헬퍼 함수
def clean_value(val):
    import numpy as np
    if val in ['N/A', 'Unknown', None, '']:
        return 0.0
    if isinstance(val, str):
        try:
            clean_str = val.replace('%', '').replace('x', '').replace('+', '').replace(',', '')
            return float(clean_str)
        except:
            return 0.0
    try: 
        return 0.0 if (isinstance(val, (int, float)) and (np.isnan(val) or np.isinf(val))) else float(val)
    except: 
        return 0.0

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

# ==========================================
# [설정] 전역 변수
# ==========================================
DRIVE_FOLDER_ID = "1WwjsnOljLTdjpuxiscRyar9xk1W4hSn2"
MY_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

# 현재 AI 프롬프트에 주입할 언어명 문자열 매핑
LANG_PROMPT_MAP = {
    "ko": "전문적인 한국어(Korean)",
    "en": "Professional English",
    "ja": "専門的な日本語(Japanese)",
    "zh": "简体中文(Simplified Chinese)"
}

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
# [수정된 함수]
def db_log_user_action(user_id, ticker, action_type, price=0.0, details=""):
    if user_id == 'guest_id' or not user_id: 
        return False
    try:
        # 1. 체류 시간 계산 (현재 시각 - 탭 진입 시각)
        entry_time = st.session_state.get('tab_entry_time', time.time())
        stay_duration = round(time.time() - entry_time, 2)
        
        # 2. 다음 측정을 위해 진입 시각 리셋 (선택 사항)
        st.session_state.tab_entry_time = time.time()

        current_lang = st.session_state.get('lang', 'ko').upper() 
        
        log_data = {
            "user_id": str(user_id),
            "ticker": str(ticker),
            "action_type": action_type, # 예: 'Tab 0_POS'
            "price": float(price),     
            "details": str(details),
            "user_lang": current_lang,
            "stay_duration_sec": stay_duration  # 🔥 [신규 추가] 체류 시간 기록
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

# (A) Tab 1용: 비즈니스 요약 + 뉴스 통합 (동적 캐싱 및 맞춤형 프롬프트 적용)
@st.cache_data(show_spinner=False, ttl=600)
def get_unified_tab1_analysis(company_name, ticker, lang_code, ipo_status="Active", ipo_date_str=None):
    """[디커플링 완료] 구글 뉴스 검색 및 AI 요약 앱단에서 금지. DB만 조회합니다."""
    cache_key = f"{ticker}_Tab1_v5_{lang_code}"
    
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", cache_key).execute()
        if res.data:
            import json
            saved_data = json.loads(res.data[0]['content'])
            return saved_data.get('html', ''), saved_data.get('news', [])
    except Exception as e:
        print(f"Tab1 DB Error: {e}")

    wait_msgs = {
        'ko': "🤖 최신 뉴스와 비즈니스 모델을 분석 중입니다...",
        'en': "🤖 Analyzing latest news and business model...",
        'ja': "🤖 最新ニュースとビジネスモデルを分析中です...",
        'zh': "🤖 正在分析最新新闻和商业模式..."
    }
    return f"<p style='color:#666;'>{wait_msgs.get(lang_code, wait_msgs['ko'])}</p>", []

@st.cache_data(show_spinner=False, ttl=600)
def get_premium_tab1_summaries(ticker, lang_code):
    """[Tab 1] 프리미엄 뉴스 및 보도자료 AI 요약본을 DB에서 가져옵니다."""
    news_summary, pr_summary = "", ""
    try:
        res_n = supabase.table("analysis_cache").select("content").eq("cache_key", f"{ticker}_PremiumNewsSummary_v1_{lang_code}").execute()
        if res_n.data: news_summary = res_n.data[0]['content']
        
        res_p = supabase.table("analysis_cache").select("content").eq("cache_key", f"{ticker}_PressReleaseSummary_v1_{lang_code}").execute()
        if res_p.data: pr_summary = res_p.data[0]['content']
    except Exception as e:
        print(f"Premium Tab1 Cache Error: {e}")
        
    return news_summary, pr_summary

@st.cache_data(show_spinner=False, ttl=600)
def get_premium_tab0_ec(ticker, lang_code):
    """[Tab 0] 어닝 콜 AI 요약본을 DB에서 가져옵니다."""
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", f"{ticker}_PremiumEarningsCall_v1_{lang_code}").execute()
        if res.data: return res.data[0]['content']
    except: pass
    return ""

@st.cache_data(show_spinner=False, ttl=600)
def get_premium_tab2_esg(ticker, lang_code):
    """[Tab 2] ESG 평가 AI 요약본을 DB에서 가져옵니다."""
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", f"{ticker}_PremiumESG_v1_{lang_code}").execute()
        if res.data: return res.data[0]['content']
    except: pass
    return ""
    
@st.cache_data(show_spinner=False, ttl=600)
def get_ai_analysis(company_name, topic, lang_code):
    """
    [Tab 0] 공시 요약과 8-K 분석이 포함된 원본 캐시를 가져옵니다.
    """
    cache_key = f"{company_name}_{topic}_Tab0_v16_{lang_code}"
    
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", cache_key).execute()
        if res.data:
            return res.data[0]['content']
    except Exception as e:
        print(f"Tab0 Cache Read Error: {e}")

    wait_msgs = {
        'ko': f"🤖 AI 애널리스트가 {topic} 리포트를 작성 중입니다...",
        'en': f"🤖 AI is generating the {topic} report...",
        'ja': f"🤖 AIが {topic} レポートを作成中です...",
        'zh': f"🤖 AI正在生成 {topic} 报告..."
    }
    return wait_msgs.get(lang_code, wait_msgs['ko'])

@st.cache_data(ttl=600)
def get_cached_raw_financials(symbol):
    """
    [디커플링 완료] FMP API 직접 호출(Income, CF, DCF, Rating 등) 전면 삭제.
    워커가 수집해둔 재무 데이터를 Supabase DB에서 한 번에 꺼내옵니다.
    """
    fin_data = {'status': 'Error'}
    try:
        # 워커가 '{symbol}_Raw_Financials' 키로 저장했다고 가정
        cache_key = f"{symbol}_Raw_Financials"
        res = supabase.table("analysis_cache").select("content").eq("cache_key", cache_key).execute()
        
        if res.data:
            import json
            fin_data = json.loads(res.data[0]['content'])
            fin_data['status'] = 'Success'
    except Exception as e:
        print(f"Financials DB Read Error: {e}")
    
    return fin_data
        
@st.cache_data(show_spinner=False, ttl=600)
def get_market_dashboard_analysis(metrics_data, lang_code):
    """[디커플링 완료] 앱에서 거시경제 AI 프롬프트 생성 금지. DB만 조회합니다."""
    
    # 💡 [핵심 수정] worker.py가 저장하는 이름과 100% 동일하게 '_Tab2'를 제거합니다!
    cache_key = f"Global_Market_Dashboard_{lang_code}"
    
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", cache_key).execute()
        if res.data:
            import re
            ai_market_comment = res.data[0]['content']
            ai_market_comment = re.sub(r'^#+.*$', '', ai_market_comment, flags=re.MULTILINE)
            ai_market_comment = ai_market_comment.replace("</div>", "").replace("<div>", "").replace("```html", "").replace("```", "").strip()
            return ai_market_comment
    except Exception as e:
        print(f"Dashboard AI Cache Error: {e}")

    wait_msgs = {
        'ko': "🤖 AI 애널리스트가 거시 경제 지표를 분석 중입니다... (최대 15분 소요)",
        'en': "🤖 AI is analyzing macroeconomic indicators...",
        'ja': "🤖 AIがマクロ経済指標を分析中です...",
        'zh': "🤖 AI正在分析宏观经济指标..."
    }
    return wait_msgs.get(lang_code, wait_msgs['ko'])


        
# ==========================================
# [기능] 1. 구글 연결 핵심 함수 (최우선 순위)
# ==========================================
def get_gcp_clients():
    # 💡 에러를 숨기지 않고 그대로 노출시켜 진짜 원인을 찾습니다.
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    gcp_raw = os.environ.get("GCP_SERVICE_ACCOUNT")
    
    if gcp_raw:
        try:
            # Railway 등 환경변수 문자열 파싱
            import json
            creds_dict = json.loads(gcp_raw, strict=False)
        except:
            # JSON 규격이 살짝 깨졌을 때를 대비한 2차 파싱
            import ast
            creds_dict = ast.literal_eval(gcp_raw)
    else:
        # 로컬(PC) 환경
        creds_dict = st.secrets["gcp_service_account"]

    from oauth2client.service_account import ServiceAccountCredentials
    import gspread
    from googleapiclient.discovery import build

    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    gspread_client = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)
    
    return gspread_client, drive_service

@st.cache_data(ttl=604800) # 1주일(604,800초) 캐싱
def get_daily_quote(lang='ko'):
    from datetime import datetime
    import random
    
    # 1. 투자, 경영, 성장을 위한 고품질 명언 리스트 (30개)
    backup_quotes = [
        {"eng": "Opportunities don't happen. You create them.", "ko": "기회는 찾아오는 것이 아닙니다. 당신이 만드는 것입니다.", "ja": "機会は起こるものではありません。あなたが創り出すものです。", "zh": "机会不是偶然发生的。它们是你创造的。", "author": "Chris Grosser"},
        {"eng": "The best way to predict the future is to create it.", "ko": "미래를 예측하는 가장 좋은 방법은 미래를 창조하는 것입니다.", "ja": "未来を予測する最良の方法は、それを創り出すことです。", "zh": "预测未来最好的方法就是创造未来。", "author": "Peter Drucker"},
        {"eng": "Innovation distinguishes between a leader and a follower.", "ko": "혁신이 리더와 추종자를 구분합니다.", "ja": "イノベーションがリーダーとフォロワーを区別します。", "zh": "创新是将领导者和追随者区分开来的标准。", "author": "Steve Jobs"},
        {"eng": "Risk comes from not knowing what you're doing.", "ko": "위험은 자신이 무엇을 하는지 모르는 데서 옵니다.", "ja": "リスクは、自分が何をしているかを知らないことから来ます。", "zh": "风险来自于你不知道自己在做什么。", "author": "Warren Buffett"},
        {"eng": "Price is what you pay. Value is what you get.", "ko": "가격은 당신이 지불하는 것이고, 가치는 당신이 얻는 것입니다.", "ja": "価格とは支払うもの。価値とは得るもの。", "zh": "价格是你支付的，价值是你得到的。", "author": "Warren Buffett"},
        {"eng": "The only way to do great work is to love what you do.", "ko": "위대한 일을 하는 유일한 방법은 당신이 하는 일을 사랑하는 것입니다.", "ja": "偉大な仕事をする唯一の方法は、自分のしていることを愛することだ。", "zh": "做伟大工作的唯一方法是热爱你所做的事。", "author": "Steve Jobs"},
        {"eng": "Success is not final; failure is not fatal: It is the courage to continue that counts.", "ko": "성공은 최종적인 것이 아니며, 실패는 치명적인 것이 아닙니다. 중요한 것은 지속하는 용기입니다.", "ja": "成功は最終的なものではなく、失敗は致命的なものではない。大切なのは続ける勇気だ。", "zh": "成功不是终点，失败也不是终结：唯有继续前进的勇气才是最重要的。", "author": "Winston Churchill"},
        {"eng": "The stock market is filled with individuals who know the price of everything, but the value of nothing.", "ko": "주식 시장은 모든 것의 가격은 알지만 가치는 아무것도 모르는 사람들로 가득 차 있습니다.", "ja": "株式市場はあらゆるものの価格を知っているが、価値については何も知らない人々で溢れている。", "zh": "股票市场充满了知道所有东西的价格，却不知道任何东西的价值的人。", "author": "Philip Fisher"},
        {"eng": "In the short run, the market is a voting machine but in the long run, it is a weighing machine.", "ko": "단기적으로 시장은 투표기계지만 장기적으로는 체중계와 같습니다.", "ja": "短期的には市場は投票機だが、長期的には計量機である。", "zh": "股市短期看是投票机，长期看是称重机。", "author": "Benjamin Graham"},
        {"eng": "Be fearful when others are greedy and greedy when others are fearful.", "ko": "남들이 탐욕스러울 때 두려워하고, 남들이 두려워할 때 탐욕스러워지십시오.", "ja": "他人が強欲な時は恐れ、他人が恐れている時は強欲になれ。", "zh": "在他人贪婪时恐惧，在他人恐惧时贪婪。", "author": "Warren Buffett"},
        {"eng": "Do not save what is left after spending, but spend what is left after saving.", "ko": "쓰고 남은 돈을 저축하지 말고, 저축하고 남은 돈을 쓰십시오.", "ja": "使った後に残った分を貯金するのではなく、貯金した後に残った分を使いなさい。", "zh": "不要存花剩的钱，要花存剩的钱。", "author": "Warren Buffett"},
        {"eng": "The goal of a successful investor is to purchase securities at prices that are significantly below their intrinsic value.", "ko": "성공한 투자자의 목표는 내재 가치보다 훨씬 낮은 가격에 증권을 사는 것입니다.", "ja": "成功する投資家の目標は、本質的な価値を大幅に下回る価格で証券を購入することだ。", "zh": "成功的投资者的目标是以显著低于其内在价值的价格购买证券。", "author": "Seth Klarman"},
        {"eng": "If you are not willing to own a stock for 10 years, do not even think about owning it for 10 minutes.", "ko": "주식을 10년 동안 보유할 생각이 없다면, 10분도 보유할 생각을 하지 마십시오.", "ja": "10年間株を保有するつもりがなければ、10分間保有することさえ考えてはいけない。", "zh": "如果你不想拥有一只股票十年，那就连十分钟也不要拥有它。", "author": "Warren Buffett"},
        {"eng": "The big money is not in the buying and the selling, but in the waiting.", "ko": "큰 돈은 사고파는 것이 아니라 기다림 속에 있습니다.", "ja": "大きな利益は売買ではなく、待機の中にこそある。", "zh": "赚大钱不在于买进卖出，而在于等待。", "author": "Charlie Munger"},
        {"eng": "The four most dangerous words in investing are: 'This time it's different.'", "ko": "투자에서 가장 위험한 네 마디는 '이번에는 다르다'입니다.", "ja": "投資において最も危険な言葉は「今回は違う」だ。", "zh": "投资中最危险的四个字是：这次不同。", "author": "Sir John Templeton"},
        {"eng": "An investment in knowledge pays the best interest.", "ko": "지식에 대한 투자가 가장 높은 이자를 지급합니다.", "ja": "知識への投資が、最高の利息を支払う。", "zh": "投资知识所得的利息最高。", "author": "Benjamin Franklin"},
        {"eng": "Formal education will make you a living; self-education will make you a fortune.", "ko": "정규 교육은 당신에게 생계를 보장해주지만, 독학은 당신에게 부를 가져다줍니다.", "ja": "学校教育は生活の糧になるが、自己教育は富をもたらす。", "zh": "正规教育能让你维持生计，自我教育能让你发财。", "author": "Jim Rohn"},
        {"eng": "Quality is not an act, it is a habit.", "ko": "품질은 행동이 아니라 습관입니다.", "ja": "品質とは行為ではなく、習慣である。", "zh": "质量不是一种行为，而是一种习惯。", "author": "Aristotle"},
        {"eng": "I find that the harder I work, the more luck I seem to have.", "ko": "열심히 일할수록 더 많은 행운이 찾아온다는 사실을 발견했습니다.", "ja": "懸命に働けば働くほど、運が向いてくるように思える。", "zh": "我发现，我工作越努力，运气就越好。", "author": "Thomas Jefferson"},
        {"eng": "Vision without execution is hallucination.", "ko": "실행 없는 비전은 환상일 뿐입니다.", "ja": "実行のないビジョンは、ただの妄想だ。", "zh": "没有执行力的愿景只是幻觉。", "author": "Thomas Edison"},
        {"eng": "A person who never made a mistake never tried anything new.", "ko": "한 번도 실수하지 않은 사람은 한 번도 새로운 시도를 하지 않은 사람입니다.", "ja": "一度も失敗をしたことがない人は、一度も新しいことに挑戦したことがない人だ。", "zh": "一个从不犯错误的人，也从未尝试过任何新鲜事物。", "author": "Albert Einstein"},
        {"eng": "It's not whether you're right or wrong that's important, but how much money you make when you're right and how much you lose when you're wrong.", "ko": "맞느냐 틀리느냐가 중요한 게 아니라, 맞았을 때 얼마나 벌고 틀렸을 때 얼마나 잃느냐가 중요합니다.", "ja": "重要なのは正しいか間違っているかではなく、正しい時にどれだけ稼ぎ、間違っている時にどれだけ失うかだ。", "zh": "重要的不是你判断对还是错，而是当你判断正确时赚了多少钱，判断错误时赔了多少钱。", "author": "George Soros"},
        {"eng": "The most important quality for an investor is temperament, not intellect.", "ko": "투자자에게 가장 중요한 자질은 지성이 아니라 기질입니다.", "ja": "投資家に最も重要な資質は知性ではなく、気質だ。", "zh": "对于投资者来说，最重要的品质是性格，而不是头脑。", "author": "Warren Buffett"},
        {"eng": "Investing should be more like watching paint dry or watching grass grow. If you want excitement, take $800 and go to Las Vegas.", "ko": "투자는 페인트가 마르는 것을 지켜보거나 풀이 자라는 것을 지켜보는 것과 같아야 합니다. 자극을 원한다면 800달러를 들고 라스베이거스로 가십시오.", "ja": "投資はペンキが乾くのを見たり、草が伸びるのを見たりするようなものであるべきだ。刺激が欲しいならラスベガスへ行け。", "zh": "投资应该更像是看着油漆变干或看着草生长。如果你想要刺激，拿上800美元去拉斯维加斯吧。", "author": "Paul Samuelson"},
        {"eng": "Knowing what you don't know is more useful than being brilliant.", "ko": "자신이 무엇을 모르는지 아는 것이 똑똑한 것보다 더 유용합니다.", "ja": "自分が何を知らないかを知ることは、優秀であることよりも役に立つ。", "zh": "了解自己不知道什么是比聪明更有用的。", "author": "Charlie Munger"},
        {"eng": "The individual investor should act consistently as an investor and not as a speculator.", "ko": "개인 투자자는 투기꾼이 아니라 철저히 투자자로서 행동해야 합니다.", "ja": "個人投資家は投機家としてではなく、常に投資家として行動すべきである。", "zh": "个人投资者应始终作为投资者而非投机者行事。", "author": "Benjamin Graham"},
        {"eng": "Don't look for the needle in the haystack. Just buy the haystack!", "ko": "건초더미에서 바늘을 찾지 마십시오. 그냥 건초더미를 통째로 사십시오!", "ja": "干し草の山から針を探すな。干し草の山を丸ごと買え！", "zh": "不要在草堆里找针。把整个草堆买下来就行了！", "author": "John Bogle"},
        {"eng": "Compound interest is the eighth wonder of the world. He who understands it, earns it; he who doesn't, pays it.", "ko": "복리는 세계 8대 불가사의입니다. 이를 이해하는 사람은 돈을 벌고, 이해하지 못하는 사람은 대가를 치릅니다.", "ja": "複利は世界で8番目の不思議だ。理解する者はそれを手に入れ、理解しない者はそれを支払う。", "zh": "复利是世界第八大奇迹。理解它的人赚取它，不理解它的人支付它。", "author": "Albert Einstein"},
        {"eng": "Rule No. 1: Never lose money. Rule No. 2: Never forget rule No. 1.", "ko": "제1원칙: 절대 돈을 잃지 마라. 제2원칙: 제1원칙을 절대 잊지 마라.", "ja": "ルール1：絶対にお金を失うな。ルール2：ルール1を忘れるな。", "zh": "第一条规则：永远不要赔钱。第二条规则：永远不要忘记第一条规则。", "author": "Warren Buffett"},
        {"eng": "Your most unhappy customers are your greatest source of learning.", "ko": "가장 불만족스러워하는 고객이 당신에게 가장 큰 배움의 원천입니다.", "ja": "最も不満を持っている顧客こそが、最大の学習源である。", "zh": "你最不满意的客户是你最大的学习来源。", "author": "Bill Gates"}
    ]

    # 💡 [핵심 수정] '연도'와 '주차(ISO Week)'를 조합하여 시드 생성
    # 예: 2026년 9주차일 경우 202609라는 숫자가 생성되어 일주일 내내 고정됩니다.
    now = datetime.now()
    year_week_seed = int(now.strftime("%Y%V")) 
    random.seed(year_week_seed)
    
    # 시드가 고정되었으므로 리스트에서 항상 같은 항목이 선택됩니다.
    choice = random.choice(backup_quotes)
    trans = choice.get(lang, choice['eng'])
    
    return {"eng": choice['eng'], "translated": trans, "author": choice['author']}
        

@st.cache_data(ttl=600)
def get_financial_metrics(symbol, api_key=None):
    """[디커플링 완료] DB의 통합 재무 데이터에서 필요한 지표만 뽑아 씁니다."""
    fin_data = get_cached_raw_financials(symbol)
    if fin_data and fin_data.get('status') == 'Success':
        return {
            "growth": fin_data.get('growth'),
            "op_margin": fin_data.get('op_margin'),
            "net_margin": fin_data.get('net_margin'),
            "debt_equity": fin_data.get('debt_equity')
        }
    return None

@st.cache_data(ttl=600)
def get_company_profile(symbol, api_key=None):
    """[디커플링 완료] 외부 API 통신 차단. 워커가 저장한 프로필을 읽습니다."""
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", f"{symbol}_Profile").execute()
        if res.data:
            import json
            return json.loads(res.data[0]['content'])
    except:
        pass
    # SEC 링크용 웹사이트나 CIK 코드가 없어도 앱이 터지지 않도록 기본값 반환
    return {"weburl": "", "cik": ""}

# 💡 [신규 추가] 앱단 SEC 티커 교정 헬퍼
@st.cache_data(ttl=86400)
def get_sec_ticker_mapping_for_app():
    try:
        import requests, re
        headers = {'User-Agent': 'UnicornFinder App admin@unicornfinder.com'}
        res = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=10)
        data = res.json()
        mapping = {}
        for k, v in data.items():
            name = str(v['title']).lower()
            name = re.sub(r'\b(inc|corp|corporation|co|ltd|plc|group|company|holdings)\b\.?', '', name)
            name = re.sub(r'[^a-z0-9]', '', name)
            if name: mapping[name] = v['ticker']
        return mapping
    except:
        return {}

def normalize_name_for_app(name):
    import re, pandas as pd
    if not name or pd.isna(name): return ""
    name = str(name).lower()
    name = re.sub(r'\b(inc|corp|corporation|co|ltd|plc|group|company|holdings)\b\.?', '', name)
    return re.sub(r'[^a-z0-9]', '', name)    

# 💡 [기존 함수 교체] 캘린더를 부를 때 API 대신 DB에서 가져오고 티커를 일괄 교정합니다!
@st.cache_data(ttl=600) 
def get_extended_ipo_data(api_key=None):
    """[디커플링 완료] Finnhub API 직접 호출 전면 삭제. DB에서 전체 달력 읽어오기"""
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", "IPO_CALENDAR_DATA").execute()
        
        if res.data:
            import json
            
            # 💡 [안전장치] DB에서 꺼낸 데이터가 문자열인지 딕셔너리/리스트인지 판별하여 에러 방지
            raw_content = res.data[0]['content']
            calendar_data = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
            
            df = pd.DataFrame(calendar_data)
            
            # SEC 티커 교정 적용
            sec_map = get_sec_ticker_mapping_for_app()
            if sec_map and not df.empty:
                df['clean_name'] = df['name'].apply(normalize_name_for_app)
                df['symbol'] = df.apply(lambda r: sec_map.get(r['clean_name'], r['symbol']), axis=1)

            df['공모일_dt'] = pd.to_datetime(df['date'], errors='coerce').dt.normalize()
            return df.dropna(subset=['공모일_dt'])
            
    except Exception as e:
        print(f"Calendar DB Read Error: {e}")
        
    return pd.DataFrame()

@st.cache_data(ttl=600, show_spinner=False)
def get_batch_prices(ticker_list):
    """
    [완벽 최적화 버전] 
    오직 Supabase DB(price_cache)에서만 가격을 읽어옵니다. 
    야후 파이낸스 API 중복 호출을 완전히 제거하여 로딩을 0.1초로 단축합니다.
    """
    if not ticker_list: return {}, {}
    clean_tickers = [str(t).strip() for t in ticker_list if t and str(t).strip().lower() != 'nan']
    
    cached_prices = {}
    db_status_map = {} 
    
    # [Step 1] Supabase DB에서 한 번에 싹 다 가져옵니다. (매우 빠름)
    try:
        res = supabase.table("price_cache") \
            .select("ticker, price, status") \
            .in_("ticker", clean_tickers) \
            .execute()
        
        if res.data:
            for item in res.data:
                t = item['ticker']
                # DB에 있으면 그 값을, 없으면(상장예정 등) 0.0을 세팅
                cached_prices[t] = float(item['price']) if item['price'] else 0.0
                db_status_map[t] = item.get('status', 'Active')
    except Exception as e:
        print(f"DB Read Error: {e}")

    # 🚨 [Step 2, 3 완전 삭제] 
    # 원래 여기에 '가격이 0원이면 야후 API 찌르기(yf.download)' 로직이 있었으나 
    # 상장 예정 종목 로딩 지연의 주범이므로 완전히 삭제했습니다.
    # 주가 수집은 백그라운드의 price_worker.py가 100% 전담합니다.

    return cached_prices, db_status_map

# =====================================================================
# 💡 [외주 개발자 지시용] 향후 유료 API(Polygon.io 등) 연동을 위한 예비 공간
# =====================================================================
def fetch_otc_price_for_app(ticker):
    """
    TODO: 상세 페이지 진입 시 야후 무료 API가 실패할 경우 호출되는 백업 함수입니다.
    추후 Polygon 연동 전까지는 0.0을 반환합니다. 구조를 절대 삭제하지 마세요.
    """
    # --------------------------------------------------
    # [미래에 대표님이 삽입할 코드 예시]
    # import requests
    # POLYGON_KEY = st.secrets.get("POLYGON_API_KEY", "")
    # url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev?adjusted=true&apiKey={POLYGON_KEY}"
    # try:
    #     res = requests.get(url, timeout=3).json()
    #     return float(res['results'][0]['c'])
    # except:
    #     return 0.0
    # --------------------------------------------------
    return 0.0


def get_current_stock_price(ticker, api_key=None):
    """
    [디커플링 완료] 외부 API를 절대 직접 호출하지 않고, 
    오직 Supabase DB(price_cache)에 있는 가격만 읽어옵니다.
    """
    try:
        res = supabase.table("price_cache").select("price, status").eq("ticker", ticker).execute()
        
        if res.data:
            db_data = res.data[0]
            db_status = db_data.get('status', 'Active')
            db_price = float(db_data.get('price', 0.0))
            
            if db_status in ["상장연기", "상장폐지"]: 
                return db_price, db_status
            if db_price > 0: 
                return db_price, "Active"

        # 🚨 [핵심] DB에 없으면 API를 부르지 않고 워커의 작업을 기다립니다.
        return 0.0, "업데이트 대기중"
            
    except Exception as e:
        print(f"Price DB Read Error: {e}")
        return 0.0, "에러"


def get_asset_grade(asset_text):
    if "10억 미만" in str(asset_text): return "Mass Affluent"
    elif "10억~50억" in str(asset_text): return "HNWI"
    elif "50억~300억" in str(asset_text): return "VHNWI"
    elif "300억 이상" in str(asset_text): return "UHNWI"
    return "Unknown"



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

def draw_footer():
    """웹사이트 하단(Footer) 회사 정보 및 약관 링크 영역 (다국어 완벽 적용)"""
    
    # UI_TEXT 사전에서 현재 선택된 언어에 맞는 텍스트 호출
    info_html = get_text('footer_company_info')
    terms_txt = get_text('footer_terms')
    privacy_txt = get_text('footer_privacy')
    refund_txt = get_text('footer_refund')
    
    # f-string을 사용하여 다국어 변수를 HTML 뼈대에 삽입
    footer_html = f"""
    <hr style="margin-top: 50px; border-color: #F0F2F6;">
    <div style="color: #666666; font-size: 13px; line-height: 1.6; padding-bottom: 30px; text-align: center;">
        {info_html}
        <br><br>
        <a href="[이용약관_URL]" target="_blank" style="color: #666666; text-decoration: none; margin: 0 10px;">{terms_txt}</a> | 
        <a href="[개인정보처리방침_URL]" target="_blank" style="color: #666666; text-decoration: none; margin: 0 10px;">{privacy_txt}</a> | 
        <a href="[환불정책_URL]" target="_blank" style="color: #666666; text-decoration: none; margin: 0 10px;">{refund_txt}</a>
        <br><br>
        © 2026 UnicornFinder. All rights reserved.
    </div>
    """
    
    st.markdown(footer_html, unsafe_allow_html=True)

# ---------------------------------------------------------
# 3. 이후 메인 로직 시작 (탭 구성 등)
# ---------------------------------------------------------
    
# ---------------------------------------------------------
# ✅ [수정] translate_news_title 함수 (Gemini API 텍스트 번역 백업용)
# ---------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=3600)
def translate_news_title(en_title):
    """
    뉴스 제목을 현재 접속한 유저의 언어에 맞춰 경제 신문 헤드라인 스타일로 번역합니다.
    (Worker 캐싱 누락 시 작동하는 Gemini API 백업 로직)
    """
    if not en_title:
        return en_title

    # 전역 model 객체 확인 (app.py 상단에서 이미 초기화된 model 사용)
    if 'model' not in globals() or not model:
        return en_title

    # 💡 현재 유저가 선택한 언어 설정 가져오기
    lang_code = st.session_state.get('lang', 'ko')

    # 💡 언어별 프롬프트 동적 세팅 (한국어는 특별 제약조건 강력 적용)
    if lang_code == 'en':
        return en_title  # 영어 원문 상태면 번역 없이 바로 반환
        
    elif lang_code == 'ko':
        prompt = f"""당신은 한국 경제 신문사 헤드라인 데스크의 전문 편집자입니다. 
영문 뉴스를 한국어 경제 신문 헤드라인 스타일로 번역하세요.
- 반드시 순수한 한글(KOREAN)로만 작성하세요. (한자, 베트남어, 일본어 등 혼용 절대 금지)
- '**'나 '*' 같은 마크다운 강조 기호를 절대 사용하지 마세요.
- 'sh' -> '주당', 'M' -> '백만', 'IPO' -> 'IPO'로 번역하세요.
- 따옴표나 불필요한 수식어는 제거하고 핵심만 간결하게 전달하세요.

Original Headline: {en_title}"""

    else:
        # 일본어, 중국어 전용 프롬프트
        if lang_code == 'ja':
            target_lang = "Japanese"
            style_desc = "日経新聞のヘッドライン風(記号なし)"
        else: # zh
            target_lang = "Simplified Chinese"
            style_desc = "财经新闻头条风格(不含特殊符号)"
            
        prompt = f"""You are a professional financial news editor.
Translate the following English news headline into {target_lang}.
Apply the following style: {style_desc}

[Rules]
- ONLY return the translated headline text.
- DO NOT include any markdown symbols like **, *, or quotes.
- DO NOT include any additional explanations or greetings.

Original Headline: {en_title}"""

    max_retries = 3
    for i in range(max_retries):
        try:
            # Gemini(model) 호출
            response = model.generate_content(prompt)
            translated_text = response.text.strip()
            
            # 후처리 로직: 마크다운 기호 및 불필요한 따옴표 강제 제거
            clean_text = translated_text.replace("**", "").replace("*", "").replace('"', '').replace("'", "")
            
            # 한글/외국어 혼용 방지 (최소한의 길이 체크)
            if len(clean_text) < 2:
                continue
                
            return clean_text
            
        except Exception as e:
            import time
            if "429" in str(e):
                time.sleep(2)  # 트래픽 제한 걸릴 시 2초 대기
            elif i < max_retries - 1:
                time.sleep(1)
            else:
                # 3번 다 실패하면 에러를 띄우지 않고 안전하게 영어 원문 반환
                return en_title
                
    return en_title

@st.cache_data(show_spinner=False, ttl=600)
def get_financial_report_analysis(company_name, ticker, metrics, lang_code):
    """[디커플링 완료] 앱에서 재무제표 AI 분석 금지."""
    cache_key = f"{ticker}_Tab3_v2_Premium_{lang_code}"
    
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", cache_key).execute()
        if res.data:
            return res.data[0]['content']
    except Exception as e:
        print(f"Tab3 Cache Error: {e}")

    wait_msgs = {
        'ko': "🤖 AI 퀀트 애널리스트가 재무 데이터를 분석 중입니다...",
        'en': "🤖 AI Quant Analyst is reviewing financials...",
        'ja': "🤖 AIクオンツアナリストが財務データを分析中です...",
        'zh': "🤖 AI量化分析师正在审查财务数据..."
    }
    return wait_msgs.get(lang_code, wait_msgs['ko'])

# 💡 [신규 추가] 스팩/직상장 등 갑자기 편입된 Ticker 리스트 불러오기 (캐싱)

@st.cache_data(show_spinner=False, ttl=600)
def get_premium_tab3_summaries(ticker, lang_code):
    """[Tab 3] 어닝 서프라이즈 및 실적 전망치 AI 요약본을 DB에서 가져옵니다."""
    surp_summary, est_summary = "", ""
    try:
        res_s = supabase.table("analysis_cache").select("content").eq("cache_key", f"{ticker}_PremiumSurprise_v1_{lang_code}").execute()
        if res_s.data: surp_summary = res_s.data[0]['content']
        
        res_e = supabase.table("analysis_cache").select("content").eq("cache_key", f"{ticker}_PremiumEstimate_v1_{lang_code}").execute()
        if res_e.data: est_summary = res_e.data[0]['content']
    except Exception as e:
        print(f"Premium Tab3 Cache Error: {e}")
        
    return surp_summary, est_summary

@st.cache_data(show_spinner=False, ttl=600)
def get_premium_tab3_revenue(ticker, lang_code):
    """[Tab 3] 부문별 매출 비중 AI 요약본을 DB에서 가져옵니다."""
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", f"{ticker}_PremiumRevenueSeg_v1_{lang_code}").execute()
        if res.data: return res.data[0]['content']
    except: pass
    return ""

@st.cache_data(show_spinner=False, ttl=600)
def get_premium_tab4_summaries(ticker, lang_code):
    """[Tab 4] 투자의견 히스토리 및 경쟁사 비교 AI 요약본을 DB에서 가져옵니다."""
    ud_summary, peers_summary = "", ""
    try:
        res_ud = supabase.table("analysis_cache").select("content").eq("cache_key", f"{ticker}_PremiumUpgrades_v1_{lang_code}").execute()
        if res_ud.data: ud_summary = res_ud.data[0]['content']
        
        res_p = supabase.table("analysis_cache").select("content").eq("cache_key", f"{ticker}_PremiumPeers_v1_{lang_code}").execute()
        if res_p.data: peers_summary = res_p.data[0]['content']
    except Exception as e:
        print(f"Premium Tab4 Cache Error: {e}")
        
    return ud_summary, peers_summary

@st.cache_data(ttl=3600) 
def get_sudden_additions():
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", "SUDDEN_ADDITIONS_LIST").execute()
        if res.data:
            import json
            return set(json.loads(res.data[0]['content']))
    except:
        pass
    return set()

@st.cache_data(show_spinner=False, ttl=600)
def get_premium_tab4_ma(ticker, lang_code):
    """[Tab 4] M&A 내역 AI 요약본을 DB에서 가져옵니다."""
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", f"{ticker}_PremiumMA_v1_{lang_code}").execute()
        if res.data: return res.data[0]['content']
    except: pass
    return ""


# ---------------------------------------------------------
# ✅ [메인] Supabase 연동 캐싱 함수 (이걸 호출하세요)
# ---------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=600)
def get_cached_market_status(df_calendar=None, api_key=None):
    """
    [디커플링 완료] FMP API로 VIX, SPY 긁어오는 로직 완전 삭제.
    워커가 저장해둔 거시 지표만 0.1초 만에 불러옵니다.
    """
    cache_key = "Market_Dashboard_Metrics"
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", cache_key).execute()
        if res.data:
            import json
            return json.loads(res.data[0]['content'])
    except Exception as e:
        print(f"Market Metrics Cache Miss: {e}")

    # 워커가 아직 데이터를 안 만들었다면 기본값 반환 (절대 API 찌르지 않음)
    return {
        "ipo_return": 0.0, "ipo_volume": 0, "unprofitable_pct": 0, "withdrawal_rate": 0,
        "vix": 0.0, "buffett_val": 0.0, "pe_ratio": 0.0, "fear_greed": 50
    }
    
# --- [주식 및 차트 기능] ---

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


@st.cache_data(show_spinner=False, ttl=600)
def get_unified_tab4_analysis(company_name, ticker, lang_code, ipo_status="Active", ipo_date_str=None):
    """[디커플링 완료] 앱에서 목표가 및 기관 리포트 AI 생성 금지."""
    # 💡 주의: worker.py에서 저장하는 키가 v4_Premium 입니다. 반드시 맞춰야 합니다.
    cache_key = f"{ticker}_Tab4_v4_Premium_{lang_code}"
    
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", cache_key).execute()
        if res.data:
            import json
            return json.loads(res.data[0]['content'])
    except Exception as e:
        print(f"Tab4 DB Error: {e}")

    fail_msgs = {
        'ko': "🤖 월가 투자 의견 데이터를 수집 중입니다...",
        'en': "🤖 Collecting Wall Street consensus data...",
        'ja': "🤖 ウォール街の投資意見データを収集中です...",
        'zh': "🤖 正在收集华尔街投资意见数据..."
    }
    return {
        "target_price": "N/A",
        "rating": "N/A", 
        "score": "3", 
        "summary": fail_msgs.get(lang_code, fail_msgs['ko']), 
        "pro_con": "데이터 대기 중...", 
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
# [3] 핵심 재무 분석 함수 (FMP API 완벽 대체)
# ==========================================


# =========================================================
# 👑 [Premium Plus 전용] 스마트머니 퀀트 분석 엔진 (API 역할)
# (추후 앱/웹 외주 개발 시, 이 블록은 백엔드 API로 그대로 이관됩니다)
# =========================================================

def get_smart_money_market_eval(sid):
    """
    [기능 1] 고자산가(최상위 자산 등급) 유저들의 평가만 필터링하여 평균을 냅니다.
    """
    try:
        # TODO: 실제 DB 연결 시, user_info 테이블과 조인하여 
        # 자산 규모(asset_size)가 특정 기준(예: Gold/Diamond 등급 등) 이상인 
        # 유저들의 user_decision 점수만 필터링하여 가져오는 SQL 쿼리를 작성합니다.
        
        # 지금은 UI 테스트를 위한 가상(Mock) 데이터를 반환합니다.
        market_avg = 2.8 
        total_votes = 42
        
        return {"market_avg": market_avg, "total_votes": total_votes}
    except Exception as e:
        print(f"스마트머니 시장평가 연동 에러: {e}")
        return {"market_avg": 0.0, "total_votes": 0}


def get_pro_fund_manager_eval(sid):
    """
    [기능 2] 펀드매니저/기관투자자(Pro) 인증을 받은 유저들의 투표 비율을 계산합니다.
    """
    try:
        # TODO: 실제 DB 연결 시, role이 'pro_manager'인 유저들이 
        # 해당 종목(sid)에 투표한 UP/DOWN 개수를 카운트합니다.
        
        # 지금은 UI 테스트를 위한 가상(Mock) 데이터를 반환합니다.
        up_pct = 78.0
        down_pct = 22.0
        total_votes = 15
        
        return {"up_pct": up_pct, "down_pct": down_pct, "total_votes": total_votes}
    except Exception as e:
        print(f"펀드매니저 평가 연동 에러: {e}")
        return {"up_pct": 50.0, "down_pct": 50.0, "total_votes": 0}

# 추후 여기에 get_insider_trading_trend(sid) 등 

# ==========================================
# [신규] Tab 6: 스마트머니 데이터 수집 및 분석 (Worker 백업용)
# ==========================================


@st.cache_data(show_spinner=False, ttl=600)
def get_smart_money_analysis_app(company_name, ticker, lang_code):
    """
    [디커플링 완료] 앱에서 SEC 13F 데이터 호출 및 Gemini 직접 요청 차단.
    오직 워커가 완성해 둔 리포트만 DB에서 읽어옵니다.
    """
    cache_key = f"{ticker}_Tab6_SmartMoney_v1_{lang_code}"
    
    try:
        res = supabase.table("analysis_cache").select("content").eq("cache_key", cache_key).execute()
        if res.data: 
            return res.data[0]['content']
    except Exception as e:
        print(f"Smart Money Cache Read Error: {e}")

    # 캐시가 비어있을 경우 (API 호출 없이 안내 문구만 노출)
    fail_msgs = {
        'ko': "스마트머니 데이터를 수집 중입니다. (15분 주기로 업데이트됩니다)",
        'en': "Collecting Smart Money data. (Updates every 15 mins)",
        'ja': "スマートマネーデータを収集中です。(15分間隔で更新)",
        'zh': "正在收集聪明钱数据。(每15分钟更新一次)"
    }
    return fail_msgs.get(lang_code, fail_msgs['ko'])


# 프리미엄 전용 함수들을 계속 추가해 나가시면 됩니다!

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
# 🚀 [STEP 1] 결제 성공 감지 및 이중 검증 (실전 통합본 - 등급 구분 추가)
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
            
        # 2. 영수증 번호 및 💡[신규] 결제 등급(Tier) 추출
        s_id = current_params.get("session_id", [""])[0] if isinstance(current_params.get("session_id"), list) else current_params.get("session_id")
        p_id = current_params.get("payment_id", [""])[0] if isinstance(current_params.get("payment_id"), list) else current_params.get("payment_id")
        
        # URL에서 tier 값을 추출 (기본값은 premium)
        purchased_tier = current_params.get("tier", ["premium"])[0] if isinstance(current_params.get("tier"), list) else current_params.get("tier", "premium")

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
                            sub_id = checkout_session.subscription 
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
                        
                        # 💡 [핵심] is_premium뿐만 아니라 membership_level도 업데이트!
                        update_data = {
                            "is_premium": True, 
                            "premium_until": expire_date,
                            "membership_level": purchased_tier
                        }
                        
                        # 구독 ID 또는 영수증 번호 추가
                        if sub_id: update_data["subscription_id"] = sub_id
                        elif p_id: update_data["subscription_id"] = f"portone_{p_id}"
                            
                        # 1. DB 업데이트 실행
                        supabase.table("users").update(update_data).eq("id", target_uid).execute()
                        
                        # 2. 현재 로그인된 화면(메모리) 상태도 업데이트
                        if st.session_state.get('user_info'):
                            st.session_state.user_info['is_premium'] = True
                            st.session_state.user_info['premium_until'] = expire_date
                            st.session_state.user_info['membership_level'] = purchased_tier
                        
                        st.success(f"👑 결제 완료! [{purchased_tier.upper()}] 회원이 되신 것을 환영합니다.")
                        
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
    'menu_logout': {'ko': '로그아웃', 'en': 'Logout', 'ja': 'ログアウト', 'zh': '退出登录'},
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
    'btn_verify_pending': {'ko': '인증심사중', 'en': 'Pending', 'ja': '審査中', 'zh': '审批中'},
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
    'status_price_checking': {
        'ko': '가격 확인중 ⏳', 
        'en': 'Checking Price ⏳', 
        'ja': '価格確認中 ⏳', 
        'zh': '价格确认中 ⏳'
    },
    'status_otc_unsupported': {
        'ko': 'OTC / 야후미지원', 
        'en': 'OTC / Unsupported', 
        'ja': 'OTC / 未対応', 
        'zh': 'OTC / 不支持'
    },
    'status_delayed_unlisted': {
        'ko': '상장지연 혹은 비상장', 
        'en': 'Delayed or Unlisted', 
        'ja': '上場延期または非上場', 
        'zh': '上市延期或未上市'
    },
    'tooltip_price_checking': {
        'ko': '상장 직후 데이터 동기화 중이거나, 실시간 호가 제공이 일시 지연되고 있는 상태입니다. (최대 14일 소요)',
        'en': 'Price data is synchronizing post-IPO, or real-time quotes are temporarily delayed.',
        'ja': '上場直後のデータ同期中、またはリアルタイム気配値の提供が一時的に遅延しています。',
        'zh': '上市后数据正在同步中，或实时报价提供暂时延迟。'
    },
    'tooltip_otc_unsupported': {
        'ko': '비상장기업이나 장외거래 주식으로 VC, Angel fund나 Broker-dealer 네트워크를 통한 사적 거래만 가능합니다.',
        'en': 'Unlisted or OTC stock. Trading is only possible through VC, Angel funds, or Broker-dealer networks.',
        'ja': '非上場企業または店頭取引（OTC）株式であり、VC、エンジェルファンドなどのネットワークを通じた取引のみ可能です。',
        'zh': '未上市企业或场外交易(OTC)股票，仅能通过VC、天使基金或经纪商网络进行交易。'
    },
    

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
    'status_otc_delayed': {
        'ko': '데이터 지연/OTC', 
        'en': 'Data Delayed/OTC', 
        'ja': 'データ遅延/OTC', 
        'zh': '数据延迟/OTC'
    },
    'badge_sudden_addition': {
        'ko': '🚀 신규 편입', 
        'en': '🚀 New Addition', 
        'ja': '🚀 新規編入', 
        'zh': '🚀 新增编入'
    },
    'tooltip_sudden_addition': {
        'ko': '이 기업들은 상장 일정이 당일 확정되는 특수 목적 회사(SPAC)나 직상장 케이스로, 상장 직후 리스트에 안전하게 추가되었습니다.',
        'en': 'These are SPACs or direct listings whose schedules are confirmed on the day. They were added safely right after listing.',
        'ja': 'これらの企業は上場日程が当日に確定する特別買収目的会社(SPAC)や直接上場であり、上場直後にリストへ追加されました。',
        'zh': '这些是上市日程在当天确定的特殊目的收购公司(SPAC)或直接上市企业，因此在上市后立即安全地添加到了列表中。'
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
    'label_fwp': {'ko': 'FWP (IR 자료)', 'en': 'FWP (IR Docs)', 'ja': 'FWP (IR資料)', 'zh': 'FWP (路演资料)'},
    'label_424b4': {'ko': '424B4 (최종확정)', 'en': '424B4 (Final)', 'ja': '424B4 (確定)', 'zh': '424B4 (最终确定)'},
    'label_10k': {'ko': '10-K (연간)', 'en': '10-K (Annual)', 'ja': '10-K (年間)', 'zh': '10-K (年度)'},
    'label_10q': {'ko': '10-Q (분기)', 'en': '10-Q (Quarter)', 'ja': '10-Q (四半期)', 'zh': '10-Q (季度)'},
    'label_bs': {'ko': 'BS (재무상태표)', 'en': 'BS (Balance Sheet)', 'ja': 'BS (貸借対照表)', 'zh': 'BS (资产负债表)'},
    'label_is': {'ko': 'IS (손익계산서)', 'en': 'IS (Income Stmt)', 'ja': 'IS (損益計算書)', 'zh': 'IS (利润表)'},
    'label_cf': {'ko': 'CF (현금흐름표)', 'en': 'CF (Cash Flow)', 'ja': 'CF (キャッシュフロー)', 'zh': 'CF (现金流量表)'},

    'desc_10k': {'ko': '10-K는 미국의 상장기업이 매년 SEC에 제출하는 연간 사업보고서입니다. 한 해의 전반적인 사업 성과와 위험 요소를 포괄적으로 다룹니다.', 'en': '10-K is a comprehensive annual report submitted to the SEC.', 'ja': '10-Kは米国の上場企業が毎年SECに提出する年次事業報告書です。', 'zh': '10-K是企业每年向SEC提交的年度业务报告。'},
    'desc_10q': {'ko': '10-Q는 분기별로 제출되는 실적 보고서입니다. 최근 3개월간의 재무 상태 변화와 단기적인 사업 현황을 파악할 수 있습니다.', 'en': '10-Q is a quarterly report detailing recent financial changes.', 'ja': '10-Qは四半期ごとに提出される業績報告書です。', 'zh': '10-Q是每季度提交的业绩报告。'},
    'desc_bs': {'ko': '재무상태표(Balance Sheet)는 기업의 자산, 부채, 자본의 현재 상태를 보여줍니다. 기업의 재무 건전성과 지급 능력을 분석합니다.', 'en': 'The Balance Sheet shows the current state of assets, liabilities, and equity.', 'ja': '貸借対照表は企業の資産、負債、資本の現在の状態を示します。', 'zh': '资产负债表显示企业资产、负债和所有者权益的现状。'},
    'desc_is': {'ko': '손익계산서(Income Statement)는 일정 기간 동안의 매출과 비용, 순이익을 나타냅니다. 기업의 수익 창출 능력을 분석합니다.', 'en': 'The Income Statement shows revenue, expenses, and net income over a period.', 'ja': '損益計算書は一定期間の売上と費用、純利益を示します。', 'zh': '利润表显示一定期间内的收入、费用和净利润。'},
    'desc_cf': {'ko': '현금흐름표(Cash Flow)는 기업에 실제 현금이 어떻게 들어오고 나갔는지를 보여줍니다. 흑자 도산 위험 등을 판별하는 핵심 지표입니다.', 'en': 'The Cash Flow statement shows how actual cash entered and left the company.', 'ja': 'キャッシュフロー計算書は実際の現金の出入りを示します。', 'zh': '现金流量表显示企业实际现金的流入和流出情况。'},
    
    # 💡 [신규 추가] 철회 및 폐지 서류 라벨 및 설명
    'label_rw': {'ko': 'RW (상장철회)', 'en': 'RW (Withdrawal)', 'ja': 'RW (上場撤回)', 'zh': 'RW (撤回上市)'},
    'label_form25': {'ko': 'Form 25 (상장폐지)', 'en': 'Form 25 (Delisted)', 'ja': 'Form 25 (上場廃止)', 'zh': 'Form 25 (退市)'},
    'desc_rw': {'ko': "RW(Registration Withdrawal)는 기업이 상장 절차를 공식적으로 중단하고 증권신고서를 철회할 때 제출하는 문서입니다. 주로 시장 환경 악화나 내부 사정으로 인한 철회 사유가 담깁니다.", 'en': "Form RW is submitted when a company officially halts its IPO. It contains reasons for withdrawal.", 'ja': "RWは企業が上場手続きを公式に中断・撤回する際に提出する文書です。", 'zh': "RW是企业正式中止上市程序并撤回注册声明时提交的文件。"},
    'desc_form25': {'ko': "Form 25는 거래소에서 상장 폐지되거나 등록이 취소될 때 제출하는 공식 통지서입니다. 인수합병(M&A)이나 상장 유지 규정 위반 등의 사유를 확인할 수 있습니다.", 'en': "Form 25 is an official notification of removal from listing. It shows reasons like M&A or rule violations.", 'ja': "Form 25は取引所から上場廃止になる際に提出される公式通知書です。", 'zh': "Form 25是自交易所退市或取消注册时提交的官方通知书。"},
    'label_market_eval_80b': {
        'ko': '시장평가(80억 이상 자산가)', 
        'en': 'Market Eval (High Net Worth)', 
        'ja': '市場評価(80億以上の資産家)', 
        'zh': '市场评估(80亿以上资产家)'
    },
    'expander_8k_premium': {
        'ko': '🚨 실시간 8-K 중대 이벤트 분석', 
        'en': '🚨 Real-time 8-K Critical Event Analysis', 
        'ja': '🚨 リアルタイム8-K重大イベント分析', 
        'zh': '🚨 实时8-K重大事件分析'
    },
    'msg_8k_blur_teaser': {
        'ko': '임원 교체, 대규모 소송, M&A 등 주가에 치명적인 영향을 미치는 8-K 돌발 공시 내역입니다. 프리미엄 등급부터 열람할 수 있습니다.',
        'en': 'Critical 8-K filings affecting stock prices, such as executive changes, lawsuits, and M&A. Available for Premium members.',
        'ja': '役員交代、大規模訴訟、M&Aなど、株価に致命的な影響を与える8-K突発開示履歴です。プレミアム等級から閲覧できます。',
        'zh': '高管变动、大规模诉讼、并购等对股价产生致命影响的8-K突发公告记录。高级会员及以上可查看。'
    },
    'btn_upgrade_premium': {
        'ko': '👑 프리미엄 구독하고 확인하기',
        'en': '👑 Go Premium to Unlock',
        'ja': '👑 プレミアムを購読して確認する',
        'zh': '👑 订阅高级会员查看'
    },
    'tab0_ec_title': {'ko': '🎙️ 어닝 콜 (Earnings Call) 핵심 요약', 'en': '🎙️ Earnings Call Summary', 'ja': '🎙️ アーニングコール要約', 'zh': '🎙️ 财报电话会议摘要'},
    'desc_ec_blur': {
        'ko': '이번 분기 어닝 콜에서 경영진은 향후 잉여현금흐름(FCF) 마진율 개선 및 신사업 추진에 대한 강력한 가이던스를 제시했습니다... (이하 블러 처리)',
        'en': 'During this earnings call, management provided strong guidance on margin improvement and new business expansions... (Blurred)',
        'ja': '今回のアーニングコールで経営陣は、今後のマージン改善および新規事業に関する強力なガイダンスを提示しました... (以下ぼかし処理)',
        'zh': '在本次财报电话会议中，管理层就未来利润率改善及新业务推进给出了强有力的指引... (以下模糊处理)'
    },
    
    # ==========================================
    # 7. Tab 1: 주요뉴스
    # ==========================================
    'expander_biz_summary': {'ko': '공식 기업소개', 'en': 'Official Corporate Overview', 'ja': '公式企業紹介', 'zh': '官方企业介绍'},
    'caption_biz_source': {
        'ko': '기업소개는 FMP 공식 자료를 원칙으로 하되, 자료가 부족할 경우 Google 검색 정보를 활용하여 보완합니다.', 
        'en': 'Corporate overview is primarily based on FMP data, utilizing Google Search when data is insufficient.', 
        'ja': '企業紹介はFMPの公式データを原則とし、データが不足している場合はGoogle検索情報を活用して補完します。', 
        'zh': '企业介绍原则上基于FMP官方数据，当数据不足时，将利用Google搜索信息进行补充。'
    },
    'sentiment_positive': {'ko': '긍정적', 'en': 'Positive', 'ja': '肯定的', 'zh': '积极'},
    'sentiment_neutral': {'ko': '중립적', 'en': 'Neutral', 'ja': '中立的', 'zh': '中立'},
    'sentiment_negative': {'ko': '부정적', 'en': 'Negative', 'ja': '否定的', 'zh': '消极'},
    'decision_news_impression': {'ko': '신규기업에 대해 어떤 인상인가요?', 'en': 'What is your impression of this company?', 'ja': '新規企業についてどのような印象をお持ちですか？', 'zh': '您对这家新公司的印象如何？'},
    'label_general': {'ko': '일반', 'en': 'General', 'ja': '一般', 'zh': '一般'},
    'err_try_again': {
        'ko': '잠시 후 다시 시도해주세요.', 
        'en': 'Please try again later.', 
        'ja': 'しばらくしてからもう一度お試しください。', 
        'zh': '请稍后再试。'
    },
    'err_ai_generation': {
        'ko': '분석 데이터를 정제하는 중입니다. 잠시 후 다시 시도해주세요.', 
        'en': 'Refining analysis data. Please try again in a moment.', 
        'ja': '分析データを精製中です。しばらくしてからもう一度お試しください。', 
        'zh': '正在整理分析数据。请稍后再试。'
    },

    'tab3_score': {'ko': '점수:', 'en': 'Score:', 'ja': 'スコア:', 'zh': '得分:'},
    'tab3_score_suffix': {'ko': '/ 9 (우량)', 'en': '/ 9 (Strong)', 'ja': '/ 9 (優良)', 'zh': '/ 9 (优良)'},
    'tab3_score_weak': {'ko': '/ 9 (주의)', 'en': '/ 9 (Weak)', 'ja': '/ 9 (注意)', 'zh': '/ 9 (注意)'},
    'tab1_premium_news_title': {
        'ko': '기관용 금융뉴스', 'en': 'Institutional Financial News', 
        'ja': '機関投資家向けニュース要約', 'zh': '机构级财经新闻摘要'
    },
    'tab1_press_release_title': {
        'ko': '기업 공식보도자료', 'en': 'Official Press Releases', 
        'ja': '企業公式プレスリリース', 'zh': '公司官方新闻稿摘要'
    },
    'tab1_recent_news_title': {
        'ko': '최근 주요뉴스 (Top 5)', 'en': 'Recent Top 5 News', 
        'ja': '最新の主要ニュース', 'zh': '近期五大核心新闻'
    },
    'msg_premium_lock': {
        'ko': '이 정보는 프리미엄 회원 전용 분석 리포트입니다.', 
        'en': 'This report is exclusive to Premium members.', 
        'ja': 'この情報はプレミアム会員専用の分析レポートです。', 
        'zh': '此信息为高级会员专属的分析报告。'
    }, 

    
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
    'desc_net_margin': {
        'ko': '매출액 대비 최종 순이익의 비율입니다. 기업이 비용을 얼마나 효율적으로 통제하며 실제로 돈을 남기고 있는지 보여줍니다.',
        'en': 'Ratio of net income to revenue. It shows how efficiently the company controls costs and generates actual profit.',
        'ja': '売上高に対する最終純利益の割合です。企業が費用をいかに効率的に管理し、実際に利益を残しているかを示します。',
        'zh': '净利润占收入的比例。它显示了公司在控制成本和产生实际利润方面的效率。'
    },
    'desc_accruals': {
        'ko': '회계 장부상 이익과 실제 현금 흐름의 차이를 분석합니다. 이 수치가 낮을수록 장난치지 않은 "진짜 현금성 이익"이 많음을 의미합니다.',
        'en': 'Analyzes the gap between book profit and actual cash flow. A lower value indicates higher "real cash earnings" without accounting tricks.',
        'ja': '会計上の利益と実際のキャッシュフローの差を分析します。この数値が低いほど、操作のない「真の現金性利益」が多いことを意味します。',
        'zh': '分析账面利润与实际现金流之间的差距。数值越低，表明没有会计欺诈的“真实现金收益”越多。'
    },
    'desc_debt_equity': {
        'ko': '자기자본 대비 부채의 비중을 나타냅니다. 고금리 시대에 IPO 기업이 외부 자금 압박 없이 독자 생존할 수 있는 재무 체력을 평가합니다.',
        'en': 'Ratio of total debt to shareholder equity. Assesses the financial stamina to survive without external funding pressure in a high-rate era.',
        'ja': '自己資本に対する負債の比率を示します。高金利時代において、IPO企業が外部資金の圧力なしに独力で生存できる財務力を評価します。',
        'zh': '总负债与股东权益的比率。评估在利率上升时代，IPO公司在没有外部资金压力的情况下独立生存 hydraulic 财力。'
    },
    'desc_performance': {
        'ko': '공모가 대비 현재 주가의 변동률입니다. 상장 이후 시장 참여자들이 이 기업의 미래 가치를 얼마나 높게 평가하고 있는지 나타내는 성적표입니다.',
        'en': 'Percentage change in current price relative to the IPO price. A scorecard showing how much investors value the company\'s future growth.',
        'ja': '公募価格に対する現在株価の変動率です。上場後、市場参加者がこの企業の将来価値をいかに高く評価しているかを示す成績表です。',
        'zh': '当前价格相对于IPO价格的变化百分比。这份成绩单显示了市场参与者对公司未来价值的评价有多高。'
    },
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
    'tab3_data_source_prem': {
        'ko': '※ 본 분석은 월스트리트 기관용 데이터(FMP Premium)를 바탕으로 생성된 전문가용 심층 리포트입니다.',
        'en': '※ This is an in-depth professional report generated based on institutional Wall Street data (FMP Premium).',
        'ja': '※ 本分析はウォール街の機関投資家向けデータ(FMP Premium)に基づいて作成された専門家向けの深層レポート입니다.',
        'zh': '※ 本分析是基于华尔街机构级数据(FMP Premium)生成的专家级深度报告。'
    },
    'tab3_dcf_title': {
        'ko': 'FMP Target (DCF)', 
        'en': 'FMP Target (DCF)', 
        'ja': 'FMP目標株価 (DCF)', 
        'zh': 'FMP目标价 (DCF)'
    },
    'tab3_quant_title': {
        'ko': 'Piotroski Score', 
        'en': 'Piotroski Score', 
        'ja': 'Piotroski Score', 
        'zh': 'Piotroski Score'
    },
    'tab3_dcf_desc': {
        'ko': '현금흐름할인법(DCF) 알고리즘으로 산출된 적정주가 대비 현재가의 괴리율입니다.',
        'en': 'Gap between DCF algorithm target price and current price.',
        'ja': '現金収益を基に算出された適正株価と現在価格の乖離率です。',
        'zh': '基于现金流折现法(DCF)算法计算的目标价与当前股价的差距。'
    },
    'tab3_quant_desc': {
        'ko': '피오트로스키(Piotroski) 점수를 포함하여 재무 건전성과 수익성을 종합 평가한 월스트리트 퀀트(Quant) 알고리즘 등급입니다.',
        'en': 'Comprehensive quantitative rating based on Piotroski F-Score, evaluating financial health and profitability by Wall Street standards.',
        'ja': 'ピオトロスキー(Piotroski)スコアに基づき、財務健全性と収益性を総合評価したウォール街のクオンツアルゴリズム等級です。',
        'zh': '基于皮奥特罗斯基(Piotroski)分数，综合评估财务健康状况和盈利能力的华尔街量化算法等级。'
    },
    'tab3_per_desc': {
        'ko': '주가수익비율(PER)로, 1주당 창출하는 순이익 대비 현재 주가의 밸류에이션 배수입니다.',
        'en': 'Price-to-Earnings ratio, indicating valuation relative to forward earnings.',
        'ja': '株価収益率(PER)で、1株当たりの純利益に対する株価の割安・割高指標です。',
        'zh': '市盈率(PER)，表示相对于每股净利润的股价估值倍数。'
    },
    'tab3_undervalued': {'ko': '저평가', 'en': 'Undervalued', 'ja': '割安', 'zh': '低估'},
    'tab3_overvalued': {'ko': '고평가', 'en': 'Overvalued', 'ja': '割高', 'zh': '高估'},
    'tab3_score': {'ko': '점수:', 'en': 'Score:', 'ja': 'スコア:', 'zh': '得分:'},
    'tab3_report_caption': {
        'ko': '※ 본 분석은 월스트리트 기관용 데이터(FMP Premium)를 바탕으로 생성된 전문가용 심층 리포트입니다.',
        'en': '※ This is an in-depth professional report generated based on FMP Premium data.',
        'ja': '※ 本分析はウォール街の機関用データ(FMP Premium)に基づいた専門家向けの深層レポートです。',
        'zh': '※ 本分析是基于华尔街机构级数据(FMP Premium)生成的专家级深度报告。'
    },
    'tab3_academic_limited': {
        'ko': '상장 전 기업이거나 공식 재무 제표가 확인되지 않아 학술적 분석이 제한됩니다.',
        'en': 'Academic analysis is limited due to missing financial statements for this company.',
        'ja': '上場前の企業、または公式財務諸表が確認できないため、学術的分析が制限されます。',
        'zh': '由于是拟上市公司或未查到官方财务报表，学术分析受限。'
    },
    # 기존 키값 보강 (혹시 누락된 경우를 위해)
    'desc_growth': {
        'ko': '최근 연간 매출 성장률입니다. 고성장 IPO 기업의 생존 가능성을 판단하는 핵심 지표입니다.',
        'en': 'Annual revenue growth. A key metric for assessing the survival of high-growth IPOs.',
        'ja': '直近の年間売上成長率です。高成長IPO企業の生存可能性を判断する重要指標です。',
        'zh': '最近一年的营收增长率。判断高成长拟上市企业生存可能性的核心指标。'
    },
    'tab3_surprise_title': {
        'ko': '어닝서프라이즈 (Earnings Surprises)', 'en': 'Earnings Surprises', 
        'ja': 'アーニングサプライズ (業績上振れ)', 'zh': '财报超预期记录(Earnings Surprises)'
    },
    'tab3_estimate_title': {
        'ko': '향후 실적전망 (Analyst Estimates)', 'en': 'Analyst Estimates', 
        'ja': '今後の業績予想 (アナリスト予測)', 'zh': '未来业绩预期 (分析师预测)'
    },
    'tab2_esg_title': {'ko': 'ESG 심층평가(글로벌 기관기준)', 'en': 'Corporate ESG Evaluation', 'ja': '企業ESG深層評価', 'zh': '企业ESG深度评估'},
    'desc_esg_blur': {
        'ko': '최근 블랙록 등 글로벌 메가 펀드들은 투자의 핵심 지표로 ESG 등급을 활용합니다. 해당 기업의 환경(E), 사회(S), 지배구조(G) 리스크에 대한 글로벌 평가 점수와 세부 분석 리포트는... (이하 블러 처리)',
        'en': 'Global mega-funds like BlackRock use ESG scores as key investment metrics. The detailed analysis of this company\'s Environmental, Social, and Governance risks... (Blurred)',
        'ja': '最近、ブラックロックなどのグローバルメガファンドは投資の核心指標としてESG等級を活用しています。該当企業の環境(E)、社会(S)、ガバナンス(G)リスクに対する詳細な評価スコアは... (以下ぼかし処理)',
        'zh': '最近，包括贝莱德在内的全球大型基金都将ESG评级作为核心投资指标。关于该企业环境(E)、社会(S)和治理(G)风险的全球评估分数及详细分析报告... (以下模糊处理)'
    },
    'tab3_revenue_title': {'ko': '📊 부문별 매출 비중 (Revenue Segmentation)', 'en': '📊 Revenue Segmentation', 'ja': '📊 部門別売上比率', 'zh': '📊 各部门营收占比'},
    'desc_revenue_blur': {
        'ko': '이 기업의 진정한 캐시카우(Cash Cow)는 어디일까요? 전체 매출의 60% 이상을 차지하는 주력 사업 부문과, 전년 대비 40% 이상 폭발적으로 고성장 중인 신규 사업 부문의 구체적인 매출 비중 및 영업이익 기여도는... (이하 블러 처리)',
        'en': 'Where is this company\'s true cash cow? The specific revenue breakdown of the flagship business generating over 60% of sales, and the newly emerging sector growing at 40% YoY... (Blurred)',
        'ja': 'この企業の真のキャッシュカウ（Cash Cow）はどこでしょうか？全体の売上の60%以上を占める主力事業部門と、前年比40%以上で爆発的に高成長している新規事業部門の具体的な売上比率および営業利益貢献度は... (以下ぼかし処理)',
        'zh': '这家企业真正的摇钱树(Cash Cow)在哪里？占总营收60%以上的主力业务部门，以及同比增长超40%的爆发性新业务部门的具体营收占比和营业利润贡献度是... (以下模糊处理)'
    },
    # [Card 1] IPO Sentiment (초기 수익성과 철회율)
    'label_ret_name': {
        'ko': 'IPO 초기 수익률', 
        'en': 'IPO Initial Return', # 학계 공식 명칭
        'ja': 'IPO初期収益率', 
        'zh': 'IPO初期收益率'
    },
    'label_with_name': {
        'ko': 'IPO 상장 철회율', 
        'en': 'IPO Withdrawal Rate', # 금융권 표준 명칭
        'ja': 'IPO取下げ率', 
        'zh': 'IPO撤回率'
    },

    # [Card 2] Supply & Quality (공급량과 질적 분석)
    'label_vol_name': {
        'ko': '상장 파이프라인(30일)', # Upcoming보다 전문적인 표현
        'en': 'IPO Pipeline (30d)', 
        'ja': '上場パイプライン', 
        'zh': 'IPO排队数量'
    },
    'label_unprof_name': {
        'ko': '미수익 기업 상장 비중', # '적자'보다 정제된 학술적 용어
        'en': 'Unprofitable IPO Share', # Jay Ritter 교수 논문 표준 용어
        'ja': '未収益企業の上場比率', 
        'zh': '未盈利企业发行占比'
    },

    # [Card 3] Market Fundamentals (거시 환경)
    'label_vix_fg_name': {
        'ko': '변동성 및 투자심리', # Fear보다 Sentiment가 학계 표준
        'en': 'Volatility & Sentiment', 
        'ja': '変動性および投資心理', 
        'zh': '波动率及投资情绪'
    },
    'label_buff_pe_name': {
        'ko': '시장 가치 평가(Valuation)', 
        'en': 'Market Valuation', 
        'ja': '市場バリュエーション', 
        'zh': '市场估值水平'
    },
    
   # [Tab 2] 3D 통합 카드 타이틀 (명확히 _title 키값으로 저장)
    'tab2_card1_title': {
        'ko': 'IPO 투기 심리 및 유동성', 
        'en': 'IPO Speculative Sentiment', 
        'ja': 'IPO投機心理と流動性', 
        'zh': 'IPO投机情绪与流动性'
    },
    'tab2_card2_title': {
        'ko': '신규 공급 및 질적 리스크', 
        'en': 'Supply Glut & Quality Risk', 
        'ja': '新規供給と質的低下リスク', 
        'zh': '新增供给与质量风险'
    },
    'tab2_card3_title': {
        'ko': '글로벌 거시경제', 
        'en': 'Global Macroeconomy', 
        'ja': 'グローバルマクロ経済', 
        'zh': '全球宏观经济'
    },
    'tab3_card1_title': {
        'ko': '비즈니스 성장 및 수익성', 
        'en': 'Business Growth & Profitability', 
        'ja': 'ビジネス成長と収益性', 
        'zh': '业务增长与盈利能力'
    },
    'tab3_card2_title': {
        'ko': '재무 건전성 및 이익 품질', 
        'en': 'Financial Health & Quality', 
        'ja': '財務健全性と利益の質', 
        'zh': '财务健康与利润质量'
    },
    'tab3_card3_title': {
        'ko': '시장 가치 평가 (Valuation)', 
        'en': 'Market Valuation', 
        'ja': '市場バリュエーション', 
        'zh': '市场估值水平'
    },
    
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
    'expander_wallstreet_pt': {
        'ko': '월가 컨센서스 & 목표 주가', 
        'en': 'Wall St. Consensus & Target Price', 
        'ja': 'ウォール街コンセンサスと目標株価', 
        'zh': '华尔街共识与目标价'
    },
    'tab4_upgrades_title': {
        'ko': '투자의견 변화추이', 'en': 'Upgrades & Downgrades', 
        'ja': '投資意見の変化推移', 'zh': '投资意见变化趋势'
    },
    'tab4_peers_title': {
        'ko': 'Sector내 비교', 'en': 'Peer Comparison', 
        'ja': 'セクター内比較', 'zh': '行业内比较'
    },
    'tab4_ma_title': {'ko': '🤝 M&A 및 기업 인수합병 내역', 'en': '🤝 M&A Transactions & Targets', 'ja': '🤝 M&Aおよび企業買収履歴', 'zh': '🤝 M&A及企业并购记录'},
    'desc_ma_blur': {
        'ko': '이 기업이 최근 진행한 인수합병(M&A) 딜의 정확한 규모와 타겟 기업은 어디일까요? 월가 IB들이 분석한 합병 시너지 효과와 향후 밸류에이션(Valuation)에 미치는 파급력은... (이하 블러 처리)',
        'en': 'What is the exact size and target of this company\'s recent M&A deals? The synergy effect and future valuation impact analyzed by Wall Street IBs are... (Blurred)',
        'ja': 'この企業が最近行ったM&Aの正確な規模とターゲット企業はどこでしょうか？ウォール街のIBが分析した合併シナジー効果と今後のバリュエーションへの波及力は... (以下ぼかし処理)',
        'zh': '这家企业近期进行的并购(M&A)交易的确切规模和目标企业是谁？华尔街投行分析的合并协同效应及其对未来估值(Valuation)的影响是... (以下模糊处理)'
    },
    
    
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
    # 11. Tab 6: 스마트머니
    # ==========================================
    'tab_6': {
        'ko': '스마트머니', 
        'en': 'Smart Money', 
        'ja': 'スマートマネー', 
        'zh': '聪明钱'
    },
    'label_market_eval_high_asset': {
        'ko': '시장평가(80억이상 자산가)', 
        'en': 'Market Eval (High Net Worth)', 
        'ja': '市場評価(80億以上の資産家)', 
        'zh': '市场评估(80亿以上资产家)'
    },
    'label_pro_eval': {
        'ko': '펀드매니저의 기업 평가', 
        'en': 'Fund Manager Evaluation', 
        'ja': 'ファンドマネージャーの企業評価', 
        'zh': '基金经理的企业评估'
    },
    'label_gauge_recession': {'ko': '침체', 'en': 'Recession', 'ja': '沈滞', 'zh': '衰退'},
    'label_gauge_bubble': {'ko': '버블', 'en': 'Bubble', 'ja': 'バブル', 'zh': '泡沫'},
    'expander_insider': {
        'ko': 'SEC Form 4 내부자 거래 감시', 
        'en': 'SEC Form 4 Insider Tracking', 
        'ja': 'SEC Form 4 内部者取引監視', 
        'zh': 'SEC Form 4 内幕交易监控'
    },
    'expander_institutional': {
        'ko': 'SEC 13F 고래(기관) 매집 동향', 
        'en': 'SEC 13F Institutional Whales', 
        'ja': 'SEC 13F 機関投資家の動向', 
        'zh': 'SEC 13F 机构巨头动向'
    },
    'expander_senate': {
        'ko': '상원의 주식거래 감시', 
        'en': 'US Senate Trading Tracker', 
        'ja': '米国上院議員の株式取引監視', 
        'zh': '美国参议员股票交易监控'
    },
    'expander_ftd': {
        'ko': '공매도 숏스퀴즈 경고 (FTD)', 
        'en': 'Short Squeeze Warning (FTD)', 
        'ja': '空売りショートスクイーズ警告 (FTD)', 
        'zh': '卖空轧空警告 (FTD)'
    },
    'caption_smart_money_source': {
        'ko': '※ 본 분석은 월스트리트 공식 SEC Form 4, 13F 및 미국 의회 제출 서류를 기반으로 실시간 추적된 데이터입니다.',
        'en': '※ This analysis is based on real-time data tracked from official Wall Street SEC Form 4, 13F, and US Congressional filings.',
        'ja': '※ 本分析はウォール街の公式SEC Form 4、13F、および米国議会提出書類に基づいてリアルタイムで追跡されたデータです。',
        'zh': '※ 本分析基于华尔街官方SEC Form 4、13F及美国国会提交文件实时追踪的数据。'
    },
    'label_pro_eval_corp': {
        'ko': "펀드매니저의 '{0}' 평가",
        'en': "Fund Manager's Evaluation of '{0}'",
        'ja': "ファンドマネージャーの「{0}」評価",
        'zh': "基金经理对“{0}”的评估"
    },
    'title_sec_smart_money': {
        'ko': '실시간 SEC 자금 흐름 추적 (Smart Money)',
        'en': 'Real-time SEC Flow Tracking (Smart Money)',
        'ja': 'リアルタイムSEC資金フロー追跡 (Smart Money)',
        'zh': '实时SEC资金流向追踪 (Smart Money)'
    },

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
    'header_basic_profile': {'ko': ' 기본 인증프로필', 'en': 'Basic Profile', 'ja': '基本認証プロフィール', 'zh': '基本认证资料'},
    'header_survey': {'ko': ' 투자성향 설문조사', 'en': 'Investment Profile Survey', 'ja': '投資性向アンケート', 'zh': '投资偏好问卷'},
    'desc_survey': {
        'ko': '개인별 맞춤투자전략 및 시장상황평가를 위해 활용됩니다.', 
        'en': 'This information is used for personalized investment strategies and market condition assessments.', 
        'ja': '個人別のカスタマイ즈投資戦略および市場状況評価のために活用されます。', 
        'zh': '此信息用于个人定制投资策略和市场状况评估。'
    },
    'msg_submit_guide': {'ko': "카테고리를 선택하고 증빙 서류를 첨부하면 '글쓰기/투표' 권한이 신청됩니다. (서류 제출은 선택사항)", 'en': "Select categories and attach documents to apply for posting/voting rights. (Docs are optional)", 'ja': "カテゴリを選択して書類を添付すると、投稿/投票権限が申請されます。(書類提出は任意)", 'zh': "选择类别并附加证明文件即可申请发帖/投票权限。（文件提交为可选）"},
    
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
    
    # [옵션] 자산 (글로벌 프라이빗 뱅킹 표준 적용)
    '10억 미만 (Under $1M)': {
        'ko': '10억 미만 (Under $1M)', 
        'en': 'Under $1M (Mass Affluent)', 
        'ja': '10億ウォン未満 (Under $1M)', 
        'zh': '10亿韩元以下 (Under $1M)'
    },
    '10억~50억 ($1M-$5M)': {
        'ko': '10억~50억 ($1M-$5M)', 
        'en': '$1M - $5M (HNWI)', 
        'ja': '10億〜50億ウォン ($1M-$5M)', 
        'zh': '10亿-50亿韩元 ($1M-$5M)'
    },
    '50억~300억 ($5M-$30M)': {
        'ko': '50억~300억 ($5M-$30M)', 
        'en': '$5M - $30M (VHNWI)', 
        'ja': '50億〜300億ウォン ($5M-$30M)', 
        'zh': '50亿-300亿韩元 ($5M-$30M)'
    },
    '300억 이상 ($30M+)': {
        'ko': '300억 이상 ($30M+)', 
        'en': 'Over $30M (UHNWI)', 
        'ja': '300億ウォン以上 ($30M+)', 
        'zh': '300亿韩元以上 ($30M+)'
    },

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
    'header_noti_setting': {'ko': '프리미엄 알림 수신설정', 'en': 'Premium Alert Settings', 'ja': 'プレミアム通知受信設定', 'zh': '高级通知接收设置'},
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
    # 18. 시스템 메시지 (Toast, Spinner, Error)
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

    # ==========================================
    # 18. 웹사이트 하단 푸터 (Footer)
    # ==========================================
    'footer_company_info': {
        'ko': '<strong>UnicornFinder (유니콘파인더)</strong><br>대표자(CEO) : 김승수 | 고객센터 : [전화번호 입력] | 이메일 : unicornfinder0328@gmail.com<br>사업장 소재지 : [우편번호] 서울특별시 강남구 언주로 123 (도곡동, 개포한신아파트)<br>사업자등록번호 : [발급 대기 중] | 통신판매업신고번호 : [발급 대기 중]',
        'en': '<strong>UnicornFinder</strong><br>CEO : Seungsoo Kim | CS : [Phone Number] | Email : unicornfinder0328@gmail.com<br>Address : [Zip Code] 123, Eonju-ro, Gangnam-gu, Seoul, Republic of Korea (Dogok-dong, Gaepo Hanshin Apt.)<br>Business Registration No. : [Pending] | E-commerce Registration No. : [Pending]',
        'ja': '<strong>UnicornFinder (ユニコーンファインダー)</strong><br>代表者(CEO) : 金承洙 (Kim Seungsoo) | カスタマーセンター : [電話番号] | メール : unicornfinder0328@gmail.com<br>所在地 : [郵便番号] ソウル特別市 江南区 彦州路 123 (道谷洞、開浦韓信アパート)<br>事業者登録番号 : [発行待機中] | 通信販売業申告番号 : [発行待機中]',
        'zh': '<strong>UnicornFinder</strong><br>首席执行官(CEO) : 金承洙 | 客服中心 : [电话号码] | 电子邮箱 : unicornfinder0328@gmail.com<br>营业地址 : [邮政编码] 首尔特别市 江南区 彦州路 123 (道谷洞，开浦韩信公寓)<br>商业登记号 : [待发放] | 电子商务登记号 : [待发放]'
    },
    'footer_terms': {
        'ko': '이용약관', 
        'en': 'Terms of Service', 
        'ja': '利用規約', 
        'zh': '服务条款'
    },
    'footer_privacy': {
        'ko': '개인정보처리방침', 
        'en': 'Privacy Policy', 
        'ja': 'プライバシーポリシー', 
        'zh': '隐私政策'
    },
    'footer_refund': {
        'ko': '환불정책', 
        'en': 'Refund Policy', 
        'ja': '返金ポリシー', 
        'zh': '退款政策'
    }
}

def get_text(key):
    """현재 세션 언어에 맞는 텍스트를 반환하는 헬퍼 함수"""
    # 💡 [핵심] lang 값이 아직 세션에 없더라도 에러를 뿜지 않고 기본값 'ko'를 쓰도록 안전장치 적용
    lang = st.session_state.get('lang', 'ko') 
    return UI_TEXT.get(key, {}).get(lang, UI_TEXT.get(key, {}).get('ko', key))

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

# =========================================================
# 🚀🚀🚀 [수정됨: 워밍업 봇 전용 비밀 뒷문 (핵심 종목 RAM 쾌속 로딩)] 🚀🚀🚀
# =========================================================
try:
    current_params = dict(st.query_params)
except:
    current_params = st.experimental_get_query_params()

if current_params.get("warmup", [""])[0] == "true" or current_params.get("warmup") == "true":
    st.warning("🔥 워밍업 봇 가동 중... DB 커넥션 유지 및 핵심 타겟 종목을 서버 RAM에 적재합니다.")
    try:
        # 1. 캘린더 전체 데이터 최신화
        df_calendar = get_extended_ipo_data(MY_API_KEY)
        
        if not df_calendar.empty:
            # 2. 시장 거시 지표(Tab 2) 메모리 적재
            get_cached_market_status(df_calendar, MY_API_KEY)
            
            # 3. 전체 주가 메모리 적재 (수익률 계산용)
            df_price = load_price_data()
            price_map = dict(zip(df_price['ticker'], df_price['price'])) if not df_price.empty else {}
            
            # 4. 갑자기 추가된 종목(스팩 등) 명단 적재
            get_sudden_additions()

            # =======================================================
            # 💡 [핵심 타겟팅] 상장 예정 종목 + 수익률 상위 50개 선별
            # =======================================================
            today = datetime.now()
            df_calendar['dt'] = pd.to_datetime(df_calendar['date'], errors='coerce')
            
            # 타겟 1: 상장 예정 종목 (오늘 이후 35일 이내)
            upcoming_df = df_calendar[(df_calendar['dt'] > today) & (df_calendar['dt'] <= today + timedelta(days=35))]
            
            # 타겟 2: 수익률 상위 50개 종목 (실시간 주가 기반 계산)
            past_df = df_calendar[df_calendar['dt'] <= today].copy()
            def calc_return(row):
                try:
                    p_ipo = float(str(row.get('price','0')).replace('$','').split('-')[0])
                    p_curr = price_map.get(row['symbol'], 0.0)
                    if p_ipo > 0 and p_curr > 0: return ((p_curr - p_ipo) / p_ipo) * 100
                    return -9999.0
                except: return -9999.0
            
            past_df['return'] = past_df.apply(calc_return, axis=1)
            top50_df = past_df.sort_values(by='return', ascending=False).head(50)
            
            # 두 타겟 그룹 병합 및 중복 제거
            target_stocks = pd.concat([upcoming_df, top50_df]).drop_duplicates(subset=['symbol'])
            
            # =======================================================
            # 💡 핵심 종목 순회하며 Tab 0, 1, 3, 4 (4개 국어) RAM 강제 캐싱
            # =======================================================
            langs = ['ko', 'en', 'ja', 'zh']
            for _, row in target_stocks.iterrows():
                ticker = row['symbol']
                name = row['name']
                c_status = row.get('status', 'Active')
                c_date = row.get('date', None)
                
                for lang in langs:
                    # [Tab 0] S-1 공시 리포트 적재
                    try: get_ai_analysis(name, "S-1", lang) 
                    except: pass
                    
                    # [Tab 1] 심층 분석 & 뉴스 적재
                    try: get_unified_tab1_analysis(name, ticker, lang, c_status, c_date) 
                    except: pass
                    
                    # [Tab 3] 재무 데이터 및 AI 재무 리포트 적재
                    # (워커가 이미 DB에 만들어 둔 리포트를 빈 파라미터{}로 가볍게 호출하여 RAM에만 저장)
                    try: get_cached_raw_financials(ticker) 
                    except: pass
                    try: get_financial_report_analysis(name, ticker, {}, lang) 
                    except: pass
                    
                    # [Tab 4] 월가 기관 리포트 적재
                    try: get_unified_tab4_analysis(name, ticker, lang, c_status, c_date) 
                    except: pass

            st.success(f"✅ 봇 접속 완료: 글로벌 지표 및 핵심 타겟 {len(target_stocks)}개 종목(Tab 0, 1, 3, 4) 서버 RAM 캐싱 완료!")
    except Exception as e:
        st.error(f"⚠️ 워밍업 에러 발생: {e}")
        
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
                asset_options = ["선택 안 함", "10억 미만 (Under $1M)", "10억~50억 ($1M-$5M)", "50억~300억 ($5M-$30M)", "300억 이상 ($30M+)"]
                
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
                                "country_code": st.session_state.lang.upper(),  # 🔥 [신규 추가] 가입 당시 언어(국적) 저장 (KO, EN, JA, ZH)
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
        # 3. [메인 기능] 인증 / 저장 / 로그아웃 / 프리미엄 / 스마트머니 (5컬럼)
        # -----------------------------------------------------------
        col_cert, col_save, col_logout, col_prem, col_prem_plus = st.columns([1, 1, 1, 1.2, 1.3])

        # [A] 인증하기 버튼
        with col_cert:
            if db_status == 'approved':
                btn_label = get_text('btn_verify_edit')
            elif db_status == 'pending':
                btn_label = get_text('btn_verify_pending')
            else:
                btn_label = get_text('btn_verify')
                
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

        # [D & E] 🔥 결제 버튼 영역 (실제 결제 로직 유지 + 2개 버튼 분리)
        curr_lang = st.session_state.get('lang', 'ko')
        is_premium = user.get('is_premium', False)
        user_level = (st.session_state.get('user_info') or {}).get('membership_level', 'free')
        current_uid = user.get('id', '')

        # 이미 유료 회원인 경우 (취소 버튼 및 현재 등급 표시)
        if is_premium:
            with col_prem:
                if st.button(get_text('btn_cancel_sub'), use_container_width=True):
                    with st.spinner("구독 정보를 확인 중입니다..."):
                        sub_id = user.get('subscription_id', '')
                        # 1. Stripe 해외 정기 구독인 경우
                        if sub_id and str(sub_id).startswith("sub_"):
                            try:
                                import stripe
                                stripe.api_key = os.environ.get("STRIPE_SECRET_KEY") or st.secrets.get("STRIPE_SECRET_KEY")
                                stripe.Subscription.modify(sub_id, cancel_at_period_end=True)
                                
                                supabase.table("users").update({"subscription_id": "canceled_" + sub_id}).eq("id", current_uid).execute()
                                st.session_state.user_info['subscription_id'] = "canceled_" + sub_id
                                
                                st.success("정기 결제가 취소되었습니다. 이번 달 결제일까지는 혜택이 유지됩니다." if curr_lang == 'ko' else "Subscription canceled.")
                                import time; time.sleep(2)
                                st.rerun()
                            except Exception as e:
                                st.error(f"오류가 발생했습니다: {e}")
                        # 2. PortOne 국내 단건 결제인 경우
                        elif sub_id and str(sub_id).startswith("portone_"):
                            st.info("국내 결제는 자동 연장(정기 결제)이 아니므로 별도로 해지하실 필요가 없습니다." if curr_lang == 'ko' else "Domestic payments do not auto-renew.")
                        else:
                            st.info("자동 연장되는 구독 내역이 없습니다." if curr_lang == 'ko' else "No active auto-renewing subscription found.")
                            
            with col_prem_plus:
                display_level = "스마트머니" if user_level == "premium_plus" else "프리미엄"
                st.markdown(f"<div style='padding: 6px; text-align: center; border: 1px solid #ddd; border-radius: 8px; color: #5c6bc0; font-weight: bold;'>현재 등급: {display_level}</div>", unsafe_allow_html=True)
        
        # 일반(무료) 회원인 경우 (2가지 플랜 버튼 노출 - 실제 결제 연동)
        else:
            import streamlit.components.v1 as components
            u_email = user.get('email', 'test@unicornfinder.app')
            u_name = user.get('display_name', '유니콘 유저')
            
            # 👑 [D] 프리미엄 구독 (월 1.9만)
            with col_prem:
                if curr_lang == 'ko':
                    portone_id = os.environ.get("PORTONE_STORE_ID")
                    if portone_id:
                        redirect_premium = f"https://my-ipo-name-production.up.railway.app/?success=true&uid={current_uid}&tier=premium"
                        portone_html_prem = f"""
                        <!DOCTYPE html><html><head><style>
                            body {{ margin: 0; padding: 0; display: flex; justify-content: center; align-items: center; background-color: transparent; overflow: hidden; }}
                            .pay-btn {{ background-color: #ffffff; color: #333; border: 1px solid #ccc; border-radius: 8px; padding: 8px 10px; font-size: 14px; font-weight: bold; cursor: pointer; width: 100%; height: 42px; transition: 0.2s; }}
                            .pay-btn:hover {{ background-color: #f0f0f0; }}
                        </style></head><body>
                            <button class="pay-btn" onclick="openPay()">👑 프리미엄 (1.9만)</button>
                            <script>
                                function openPay() {{
                                    const pw = window.open("", "_blank", "width=600,height=800");
                                    if (!pw) {{ alert("팝업을 허용해주세요."); return; }}
                                    pw.document.write(`
                                        <script src="https://cdn.portone.io/v2/browser-sdk.js"><\\/script>
                                        <body><script>
                                            window.onload = function() {{
                                                PortOne.requestPayment({{
                                                    storeId: "{portone_id}", channelKey: "channel-key-52a64d79-396d-4c62-8513-aad2946e17f4", paymentId: "pay-" + new Date().getTime(),
                                                    orderName: "Premium Subscription", totalAmount: 19000, currency: "KRW", payMethod: "CARD",
                                                    customer: {{ fullName: "{u_name}", email: "{u_email}", phoneNumber: "010-0000-0000" }},
                                                    windowType: {{ pc: "IFRAME", smartPhone: "REDIRECTION" }}, redirectUrl: "{redirect_premium}"
                                                }}).then(function(res) {{
                                                    if (res && res.code != null) {{ alert("실패: " + res.message); window.close(); }}
                                                    else if (res) {{ if (window.opener) window.opener.parent.location.href = "{redirect_premium}"; window.close(); }}
                                                }});
                                            }};
                                        <\\/script></body>
                                    `); pw.document.close();
                                }}
                            </script>
                        </body></html>
                        """
                        components.html(portone_html_prem, height=45)
                else:
                    if st.button("👑 Premium ($19)", use_container_width=True):
                        stripe_sk = os.environ.get("STRIPE_SECRET_KEY")
                        stripe_price = os.environ.get("STRIPE_PRICE_ID") 
                        if not stripe_sk or not stripe_price: st.error("❌ Stripe API Key/Price ID missing.")
                        else:
                            try:
                                import stripe; stripe.api_key = stripe_sk
                                session = stripe.checkout.Session.create(
                                    line_items=[{'price': stripe_price, 'quantity': 1}], mode='subscription',
                                    success_url=f'https://my-ipo-name-production.up.railway.app/?success=true&uid={current_uid}&tier=premium&session_id={{CHECKOUT_SESSION_ID}}',
                                    cancel_url='https://my-ipo-name-production.up.railway.app/?canceled=true',
                                )
                                st.link_button("🌐 Pay via Stripe", session.url, use_container_width=True)
                            except Exception as e: st.error(f"Error: {e}")

            # 💎 [E] 스마트머니 구독 (월 4.9만)
            with col_prem_plus:
                if curr_lang == 'ko':
                    portone_id = os.environ.get("PORTONE_STORE_ID")
                    if portone_id:
                        redirect_plus = f"https://my-ipo-name-production.up.railway.app/?success=true&uid={current_uid}&tier=premium_plus"
                        portone_html_plus = f"""
                        <!DOCTYPE html><html><head><style>
                            body {{ margin: 0; padding: 0; display: flex; justify-content: center; align-items: center; background-color: transparent; overflow: hidden; }}
                            .pay-btn {{ background-color: #ff4b4b; color: #fff; border: none; border-radius: 8px; padding: 8px 10px; font-size: 14px; font-weight: bold; cursor: pointer; width: 100%; height: 42px; transition: 0.2s; }}
                            .pay-btn:hover {{ background-color: #d32f2f; }}
                        </style></head><body>
                            <button class="pay-btn" onclick="openPayPlus()">💎 스마트머니 (4.9만)</button>
                            <script>
                                function openPayPlus() {{
                                    const pw = window.open("", "_blank", "width=600,height=800");
                                    if (!pw) {{ alert("팝업을 허용해주세요."); return; }}
                                    pw.document.write(`
                                        <script src="https://cdn.portone.io/v2/browser-sdk.js"><\\/script>
                                        <body><script>
                                            window.onload = function() {{
                                                PortOne.requestPayment({{
                                                    storeId: "{portone_id}", channelKey: "channel-key-52a64d79-396d-4c62-8513-aad2946e17f4", paymentId: "pay-" + new Date().getTime(),
                                                    orderName: "SmartMoney Subscription", totalAmount: 49000, currency: "KRW", payMethod: "CARD",
                                                    customer: {{ fullName: "{u_name}", email: "{u_email}", phoneNumber: "010-0000-0000" }},
                                                    windowType: {{ pc: "IFRAME", smartPhone: "REDIRECTION" }}, redirectUrl: "{redirect_plus}"
                                                }}).then(function(res) {{
                                                    if (res && res.code != null) {{ alert("실패: " + res.message); window.close(); }}
                                                    else if (res) {{ if (window.opener) window.opener.parent.location.href = "{redirect_plus}"; window.close(); }}
                                                }});
                                            }};
                                        <\\/script></body>
                                    `); pw.document.close();
                                }}
                            </script>
                        </body></html>
                        """
                        components.html(portone_html_plus, height=45)
                else:
                    if st.button("💎 SmartMoney ($49)", use_container_width=True, type="primary"):
                        stripe_sk = os.environ.get("STRIPE_SECRET_KEY")
                        stripe_price = os.environ.get("STRIPE_PRICE_ID_PLUS") # 💡 Plus용 환경변수 (Railway에 추가 필요!)
                        if not stripe_sk or not stripe_price: st.error("❌ Stripe API Key/Price ID missing.")
                        else:
                            try:
                                import stripe; stripe.api_key = stripe_sk
                                session = stripe.checkout.Session.create(
                                    line_items=[{'price': stripe_price, 'quantity': 1}], mode='subscription',
                                    success_url=f'https://my-ipo-name-production.up.railway.app/?success=true&uid={current_uid}&tier=premium_plus&session_id={{CHECKOUT_SESSION_ID}}',
                                    cancel_url='https://my-ipo-name-production.up.railway.app/?canceled=true',
                                )
                                st.link_button("🌐 Pay via Stripe", session.url, use_container_width=True)
                            except Exception as e: st.error(f"Error: {e}")
        
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
                            
            # ===========================================================
            # 🔎 [풀버전] 관리자 전용: 캐시 헬스체크(Health Check) 대시보드
            # ===========================================================
            st.write("<br>", unsafe_allow_html=True)
            st.markdown("### 📊 시스템 캐시 & API 방어막 상태 점검")
            st.caption("워커(Worker)들이 백그라운드에서 데이터를 얼마나 잘 캐싱해두고 있는지 탭별로 모니터링합니다.")
            
            try:
                now = datetime.now()
                
                # [1] 주가 캐시 (Price) 모니터링
                res_price_all = supabase.table("price_cache").select("ticker", count="exact").execute()
                total_price_cnt = res_price_all.count if res_price_all and res_price_all.count else 1
                
                thirty_mins_ago = (now - timedelta(minutes=30)).isoformat()
                res_price_active = supabase.table("price_cache").select("ticker").gt("updated_at", thirty_mins_ago).execute()
                active_price_cnt = len(res_price_active.data) if res_price_active.data else 0
                
                price_pct = int((active_price_cnt / total_price_cnt) * 100) if total_price_cnt > 0 else 0
                
                # 💡 [핵심 추가] 미국 동부 시간 기준으로 장이 열려있는지 판단 (워커 휴식 시간 동기화)
                import pytz
                now_est = datetime.now(pytz.timezone('US/Eastern'))
                is_market_open = (now_est.weekday() < 5) and (4 <= now_est.hour <= 20)
                
                # [2] AI 리포트 전체 캐시 (Tab 0 ~ 6) 모니터링
                res_analysis_all = supabase.table("analysis_cache").select("cache_key, updated_at").execute()
                
                tab0_total = 0; tab0_fresh = 0
                tab1_total = 0; tab1_fresh = 0
                tab2_total = 0; tab2_fresh = 0
                tab3_total = 0; tab3_fresh = 0
                tab4_total = 0; tab4_fresh = 0
                tab6_total = 0; tab6_fresh = 0 # 💡 Tab 6 변수 추가
                
                seven_days_ago = now - timedelta(days=7)
                
                if res_analysis_all.data:
                    for item in res_analysis_all.data:
                        key = item['cache_key']
                        try:
                            item_time_str = str(item['updated_at']).split('.')[0].replace('Z', '')
                            item_dt = datetime.fromisoformat(item_time_str)
                            is_fresh = item_dt > seven_days_ago
                        except:
                            is_fresh = False

                        if "Tab0" in key:
                            tab0_total += 1
                            if is_fresh: tab0_fresh += 1
                        elif "Tab1" in key:
                            tab1_total += 1
                            if is_fresh: tab1_fresh += 1
                        elif "Tab2" in key or "Market_Dashboard" in key:
                            tab2_total += 1
                            if is_fresh: tab2_fresh += 1
                        elif "Tab3" in key:
                            tab3_total += 1
                            if is_fresh: tab3_fresh += 1
                        elif "Tab4" in key:
                            tab4_total += 1
                            if is_fresh: tab4_fresh += 1
                        # 💡 Tab 6 카운트 추가 (키에 'Tab6' 포함)
                        elif "Tab6" in key:
                            tab6_total += 1
                            if is_fresh: tab6_fresh += 1

                tab0_pct = int((tab0_fresh / tab0_total) * 100) if tab0_total > 0 else 0
                tab1_pct = int((tab1_fresh / tab1_total) * 100) if tab1_total > 0 else 0
                tab2_pct = int((tab2_fresh / tab2_total) * 100) if tab2_total > 0 else 0
                tab3_pct = int((tab3_fresh / tab3_total) * 100) if tab3_total > 0 else 0
                tab4_pct = int((tab4_fresh / tab4_total) * 100) if tab4_total > 0 else 0
                tab6_pct = int((tab6_fresh / tab6_total) * 100) if tab6_total > 0 else 0 # 💡 Tab 6 퍼센트

                # [3] 대시보드 화면 렌더링
                # 레이아웃을 2칸 x 3줄 혹은 3칸/3칸/1칸 등으로 유연하게 구성
                dash_r1_c1, dash_r1_c2, dash_r1_c3 = st.columns(3)
                dash_r2_c1, dash_r2_c2, dash_r2_c3 = st.columns(3)
                dash_r3_c1, dash_r3_c2, dash_r3_c3 = st.columns(3) # 💡 세 번째 줄 추가
                
                # 첫 번째 줄
                with dash_r1_c1:
                    if is_market_open:
                        st.metric(label="🟢 실시간 주가 (최근 30분)", value=f"{price_pct}% 정상", delta=f"{active_price_cnt} / {total_price_cnt} 종목", delta_color="normal" if price_pct >= 90 else "inverse")
                    else:
                        st.metric(label="💤 실시간 주가 (최근 30분)", value="장 마감 (종가 유지)", delta=f"DB 조회로 API 100% 방어 중", delta_color="normal")
                with dash_r1_c2:
                    st.metric(label="📄 공시 분석 캐시 (Tab 0)", value=f"{tab0_pct}% 완료", delta=f"{tab0_fresh} / {tab0_total} 건 방어 중", delta_color="normal" if tab0_pct >= 90 else "inverse")
                with dash_r1_c3:
                    st.metric(label="📰 뉴스 분석 캐시 (Tab 1)", value=f"{tab1_pct}% 완료", delta=f"{tab1_fresh} / {tab1_total} 건 방어 중", delta_color="normal" if tab1_pct >= 90 else "inverse")
                
                st.write("<br>", unsafe_allow_html=True) # 줄 간격 띄우기

                # 두 번째 줄
                with dash_r2_c1:
                    st.metric(label="🌍 거시 지표 캐시 (Tab 2)", value=f"{tab2_pct}% 완료", delta=f"{tab2_fresh} / {tab2_total} 건 방어 중", delta_color="normal" if tab2_pct >= 90 else "inverse")
                with dash_r2_c2:
                    st.metric(label="📊 미시 재무 캐시 (Tab 3)", value=f"{tab3_pct}% 완료", delta=f"{tab3_fresh} / {tab3_total} 건 방어 중", delta_color="normal" if tab3_pct >= 90 else "inverse")
                with dash_r2_c3:
                    st.metric(label="👔 기관 평가 캐시 (Tab 4)", value=f"{tab4_pct}% 완료", delta=f"{tab4_fresh} / {tab4_total} 건 방어 중", delta_color="normal" if tab4_pct >= 90 else "inverse")

                st.write("<br>", unsafe_allow_html=True) # 줄 간격 띄우기

                # 세 번째 줄 (Tab 6 추가)
                with dash_r3_c1:
                    st.metric(label="🚨 스마트머니 캐시 (Tab 6)", value=f"{tab6_pct}% 완료", delta=f"{tab6_fresh} / {tab6_total} 건 방어 중", delta_color="normal" if tab6_pct >= 90 else "inverse")
                    
                st.info("💡 진척률이 100%에 가깝다면, 각 탭에 유저가 진입할 때마다 발생하는 모든 API 과금을 완벽히 방어(0원)하고 있다는 뜻입니다.")

            except Exception as e:
                st.error(f"상태 점검 중 데이터베이스 오류: {e}")
            st.divider()
            

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
                # 💡 [핵심 추가] 화면을 그리기 전에 미리 신규 편입 기업 명단을 가져옵니다.
                sudden_tickers = get_sudden_additions()
                
                for i, row in display_df.iterrows():
                    p_val = pd.to_numeric(str(row.get('price','')).replace('$','').split('-')[0], errors='coerce')
                    p_val = p_val if p_val and p_val > 0 else 0
                    
                    live_p = row.get('live_price', 0)
                    live_s = row.get('live_status', 'Active')

                    raw_status = str(row.get('status', '')).lower()
                    status_lower = str(live_s).lower()
                    combined_status = f"{raw_status} {status_lower}"
                    
                    import re
                    is_withdrawn = bool(re.search(r'\b(withdrawn|rw|철회|취소)\b', combined_status))
                    is_delayed = bool(re.search(r'\b(delayed|연기)\b', combined_status))
                    is_delisted = bool(re.search(r'\b(delisted|폐지)\b', combined_status))
                    is_expected = bool(re.search(r'\b(expected|filed|active|priced)\b', combined_status))
                    
                    # 1. 상장 철회
                    if is_withdrawn:
                        price_html = f"<div class='price-main' style='color:#888888 !important;'>{get_text('label_rw')}</div><div class='price-sub' style='color:#666666 !important;'>IPO: ${p_val:,.2f}</div>"
                    
                    # 2. 공식 상장 연기
                    elif is_delayed:
                        price_html = f"<div class='price-main' style='color:#1919e6 !important;'>{get_text('status_delayed')}</div><div class='price-sub' style='color:#666666 !important;'>IPO: ${p_val:,.2f}</div>"
                    
                    # 3. 상장 폐지
                    elif is_delisted:
                        price_html = f"<div class='price-main' style='color:#888888 !important;'>{get_text('status_delisted')}</div><div class='price-sub' style='color:#666666 !important;'>IPO: ${p_val:,.2f}</div>"
                    
                    # 4. 가격이 잡히는 정상 거래 종목
                    elif live_p > 0:
                        pct = ((live_p - p_val) / p_val) * 100 if p_val > 0 else 0
                        change_color = "#e61919" if pct > 0 else "#1919e6" if pct < 0 else "#333333"
                        arrow = "▲" if pct > 0 else "▼" if pct < 0 else ""
                        price_html = f"<div class='price-main' style='color:{change_color} !important;'>${live_p:,.2f} ({arrow}{pct:+.1f}%)</div><div class='price-sub' style='color:#666666 !important;'>IPO: ${p_val:,.2f}</div>"
                    
                    # 5. 다국어 지원 시간 기반 3단 방어막 + 툴팁 적용
                    else: 
                        item_date = row['공모일_dt'].date()
                        days_passed = (today_dt.date() - item_date).days
                        
                        if item_date > today_dt.date():
                            price_html = f"<div class='price-main' style='color:#333333 !important;'>${p_val:,.2f}</div><div class='price-sub' style='color:#666666 !important;'>{get_text('status_waiting')}</div>"
                        
                        elif 0 <= days_passed <= 14:
                            if is_expected:
                                tooltip = get_text('tooltip_price_checking')
                                price_html = f"<div title='{tooltip}' class='price-main' style='color:#333333 !important; font-size:12px; cursor:help;'>{get_text('status_price_checking')}</div><div class='price-sub' style='color:#666666 !important;'>IPO: ${p_val:,.2f}</div>"
                            else:
                                tooltip = get_text('tooltip_otc_unsupported')
                                price_html = f"<div title='{tooltip}' class='price-main' style='color:#f57c00 !important; font-size:11.5px !important; cursor:help;'>{get_text('status_delayed_unlisted')}</div><div class='price-sub' style='color:#666666 !important;'>IPO: ${p_val:,.2f}</div>"
                        
                        else:
                            tooltip = get_text('tooltip_otc_unsupported')
                            price_html = f"<div title='{tooltip}' class='price-main' style='color:#888888 !important; font-size:11.5px !important; cursor:help;'>{get_text('status_otc_unsupported')}</div><div class='price-sub' style='color:#666666 !important;'>IPO: ${p_val:,.2f}</div>"
                    
                    # --- [UI 렌더링 시작] ---
                    date_html = f"<div class='date-text'>{row['date']}</div>"
                    c1, c2 = st.columns([7, 3])
                    
                    with c1:
                        if st.button(f"{row['name']}", key=f"btn_list_{i}"):
                            main_area.empty()
                            st.session_state.selected_stock = row.to_dict()
                            st.session_state.page = 'detail'
                            st.session_state.detail_sub_menu = get_text('tab_0')
                            st.rerun()
                        
                        try: s_val = int(row.get('numberOfShares',0)) * p_val / 1000000
                        except: s_val = 0
                        size_str = f" | ${s_val:,.0f}M" if s_val > 0 else ""
                        
                        # 💡 [핵심 추가] Ticker 목록에 있으면 HTML 뱃지를 생성합니다. (다국어 완벽 적용)
                        badge_html = ""
                        if str(row['symbol']) in sudden_tickers:
                            # UI_TEXT에 추가한 다국어 텍스트를 불러옵니다.
                            tooltip_text = get_text('tooltip_sudden_addition')
                            badge_text = get_text('badge_sudden_addition')
                            
                            badge_html = f" <span title='{tooltip_text}' style='background-color: #e0f2fe; color: #0284c7; padding: 2px 6px; border-radius: 6px; font-size: 10px; font-weight: bold; cursor: help;'>{badge_text}</span>"

                        # 원래 있던 렌더링 문구 끝에 {badge_html}을 붙여줍니다.
                        st.markdown(f"<div class='mobile-sub' style='margin-top:-2px; padding-left:2px;'>{row['symbol']} | {row.get('exchange','-')}{size_str}{badge_html}</div>", unsafe_allow_html=True)
                    
                    with c2:
                        st.markdown(f"<div style='text-align:right;'>{price_html}{date_html}</div>", unsafe_allow_html=True)
                    
                    st.markdown("<div style='border-bottom:1px solid #f0f2f6; margin: 4px 0;'></div>", unsafe_allow_html=True)
    
    
    
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

        # 실시간 주가 및 기업 정보 로드
        profile = None
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
            # 1. 상단 메뉴바 스타일 및 네비게이션
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

            # 2. 기업 헤더 정보 (상태 emoji, 가격 툴팁 등)
            today = datetime.now().date()
            ipo_dt = pd.to_datetime(stock['공모일_dt']).date()
            status_emoji = "🐣" if ipo_dt > (today - timedelta(days=365)) else "🦄"
            date_str = ipo_dt.strftime('%Y-%m-%d')
            label_ipo = get_text('label_ipo_price')
            
            raw_status = str(stock.get('status', '')).lower()
            live_s = str(current_s).lower()
            combined_status = f"{raw_status} {live_s}"
            
            import re
            is_withdrawn = bool(re.search(r'\b(withdrawn|rw|철회|취소)\b', combined_status))
            is_delayed = bool(re.search(r'\b(delayed|연기)\b', combined_status))
            is_delisted = bool(re.search(r'\b(delisted|폐지)\b', combined_status))
            is_expected = bool(re.search(r'\b(expected|filed|active|priced)\b', combined_status))

            if is_withdrawn:
                p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / {label_ipo} ${off_val} / 🚫 {get_text('label_rw')})</span>"
            elif is_delayed:
                p_info = f"<span style='font-size: 0.9rem; color: #1919e6;'>({date_str} / {label_ipo} ${off_val} / 📅 {get_text('status_delayed')})</span>"
            elif is_delisted:
                p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / {label_ipo} ${off_val} / 🚫 {get_text('status_delisted')})</span>"
            elif current_p > 0 and off_val > 0:
                pct = ((current_p - off_val) / off_val) * 100
                color = "#00ff41" if pct >= 0 else "#ff4b4b"
                icon = "▲" if pct >= 0 else "▼"
                p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / {label_ipo} ${off_val} / {get_text('label_general')} ${current_p:,.2f} <span style='color:{color}; font-weight:bold;'>{icon} {abs(pct):.1f}%</span>)</span>"
            else: 
                if ipo_dt > today:
                    p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / {label_ipo} ${off_val} / ⏳ {get_text('status_waiting')})</span>"
                elif 0 <= (today - ipo_dt).days <= 14:
                    if is_expected:
                        tooltip = get_text('tooltip_price_checking')
                        p_info = f"<span style='font-size: 0.9rem; color: #333333; cursor: help;' title='{tooltip}'>({date_str} / {label_ipo} ${off_val} / {get_text('status_price_checking')})</span>"
                    else:
                        tooltip = get_text('tooltip_otc_unsupported')
                        p_info = f"<span style='font-size: 0.9rem; color: #f57c00; cursor: help;' title='{tooltip}'>({date_str} / {label_ipo} ${off_val} / {get_text('status_delayed_unlisted')})</span>"
                else:
                    tooltip = get_text('tooltip_otc_unsupported')
                    p_info = f"<span style='font-size: 0.9rem; color: #888888; cursor: help;' title='{tooltip}'>({date_str} / {label_ipo} ${off_val} / {get_text('status_otc_unsupported')})</span>"

            st.markdown(f"<div><span style='font-size: 1.2rem; font-weight: 700;'>{status_emoji} {stock['name']}</span> {p_info}</div>", unsafe_allow_html=True)
            st.write("")

            # 3. 💡 [체류 시간 측정 및 탭 제어] 
            import time
            if 'tab_entry_time' not in st.session_state:
                st.session_state.tab_entry_time = time.time()

            tab_labels = [get_text(f'tab_{i}') for i in range(7)] 
            if 'detail_sub_menu' not in st.session_state or st.session_state.detail_sub_menu not in tab_labels:
                st.session_state.detail_sub_menu = tab_labels[0]

            selected_sub_menu = st.pills(label="sub_nav", options=tab_labels, selection_mode="single", 
                                         default=st.session_state.detail_sub_menu, key="detail_tabs_pills", label_visibility="collapsed")
            
            # 🚀 탭 변경 시 시간 리셋
            if selected_sub_menu and selected_sub_menu != st.session_state.detail_sub_menu:
                st.session_state.tab_entry_time = time.time() 
                st.session_state.detail_sub_menu = selected_sub_menu
                st.rerun()

            
            # --- Tab 0: 핵심 정보 (8-K 찌꺼기 제거 및 밀착 레이아웃 통합본) ---
            if selected_sub_menu == get_text('tab_0'):
                # 💡 [핵심 에러 해결] Tab 0 안에서도 user_info를 불러와 is_premium 상태를 정의해 줍니다!
                raw_info = st.session_state.get('user_info')
                user_info = raw_info if isinstance(raw_info, dict) else {}
                user_level = user_info.get('membership_level', 'free')
                is_premium = user_level in ['premium', 'premium_plus']
                # 1. 버튼 스타일링 (깔끔한 디자인 유지)
                st.markdown("""<style>
                    div.stButton > button[kind="secondary"] { background-color: #ffffff !important; color: #000000 !important; border: 1px solid #dcdcdc !important; border-radius: 8px !important; height: 3em !important; font-weight: bold !important; } 
                    div.stButton > button[kind="secondary"]:hover { border-color: #6e8efb !important; color: #6e8efb !important; } 
                    div.stButton > button[kind="primary"] { background-color: #d32f2f !important; color: #ffffff !important; border: 1px solid #d32f2f !important; border-radius: 8px !important; height: 3em !important; font-weight: bold !important; }
                    div.stButton > button[kind="primary"]:hover { background-color: #b71c1c !important; border-color: #b71c1c !important; }
                </style>""", unsafe_allow_html=True)
            
                # 2. 기업 상태 및 버튼 레이아웃 결정
                f_status = str(stock.get('status', current_s)).lower()
                is_withdrawn = any(x in f_status for x in ['철회', '취소', 'withdrawn'])
                is_delisted = any(x in f_status for x in ['폐지', 'delisted'])
                
                is_over_1y = False
                try:
                    ipo_dt_val = pd.to_datetime(stock['공모일_dt']).date()
                    if (datetime.now().date() - ipo_dt_val).days > 365: is_over_1y = True
                except: pass
            
                if is_withdrawn:
                    btn_layout = [("S-1", "secondary"), ("S-1/A", "secondary"), ("F-1", "secondary"), ("FWP", "secondary"), ("RW", "primary")]
                    default_topic = "RW"
                elif is_delisted:
                    btn_layout = [("S-1", "secondary"), ("S-1/A", "secondary"), ("F-1", "secondary"), ("FWP", "secondary"), ("424B4", "secondary"), ("Form 25", "primary")]
                    default_topic = "Form 25"
                elif is_over_1y:
                    btn_layout = [("S-1", "secondary"), ("FWP", "secondary"), ("10-K", "secondary"), ("10-Q", "secondary"), ("BS", "secondary"), ("IS", "secondary"), ("CF", "secondary")]
                    default_topic = "10-K"
                else:
                    btn_layout = [("S-1", "secondary"), ("S-1/A", "secondary"), ("F-1", "secondary"), ("FWP", "secondary"), ("424B4", "secondary")]
                    default_topic = "S-1"
            
                # 🔍 8-K 데이터 존재 여부 확인
                has_8k = False
                try:
                    r_8k = supabase.table("analysis_cache").select("cache_key").eq("cache_key", f"{stock['name']}_8-K_Tab0_v16_{st.session_state.lang}").execute()
                    if r_8k.data: has_8k = True
                except: pass
                if has_8k: btn_layout.append(("8-K", "primary"))
            
                valid_topics = [b[0] for b in btn_layout]
                if 'core_topic' not in st.session_state or st.session_state.core_topic not in valid_topics:
                    st.session_state.core_topic = default_topic
            
                label_map = { "S-1": get_text('label_s1'), "S-1/A": get_text('label_s1a'), "F-1": get_text('label_f1'), "FWP": get_text('label_fwp'), "424B4": get_text('label_424b4'), "RW": get_text('label_rw'), "Form 25": get_text('label_form25'), "10-K": get_text('label_10k'), "10-Q": get_text('label_10q'), "BS": get_text('label_bs'), "IS": get_text('label_is'), "CF": get_text('label_cf'), "8-K": "🚨 8-K" }
                
                cols = st.columns(4)
                for i, (t_name, t_style) in enumerate(btn_layout):
                    if cols[i % 4].button(label_map.get(t_name, t_name), type=t_style, use_container_width=True, key=f"btn_tab0_final_{t_name}"):
                        st.session_state.core_topic = t_name
                        st.rerun()
            
                t_topic = st.session_state.core_topic
                st.info(get_text(f"desc_{t_topic.lower().replace('/','').replace('-','').replace(' ','')}"))
            
                # 3. 데이터 로드 및 고도화 파싱
                # 💡 [수정] expanded=False 로 변경하여 기본적으로 카드가 '닫혀 있도록' 설정합니다.
                with st.expander(f" {t_topic} {get_text('btn_summary_view')}", expanded=False):
                    with st.spinner("분석 리포트를 불러오는 중..."):
                        a_res = get_ai_analysis(stock['name'], t_topic, st.session_state.lang)
                    
                    if not a_res or "ERROR" in a_res:
                        st.error("데이터를 불러올 수 없습니다.")
                    else:
                        import re
                        # [Step 1] 기본 텍스트 정리
                        raw_text = a_res.replace("|||SEP|||", "\n").replace("**", "").strip()
                        
                        # 💡 [핵심] 일반 서류 탭일 때 8-K 흔적 강제 절단 로직 보강
                        if t_topic != "8-K":
                            stop_keywords = ["실시간 8-K", "8-K 분석", "보고된 돌발", "중대 이벤트"]
                            for skw in stop_keywords:
                                if skw in raw_text:
                                    raw_text = raw_text.split(skw)[0].strip()
                            
                            raw_text = raw_text.rstrip('[ ').strip()
            
                        # [Step 2] 하단 미완성 찌꺼기 제거
                        lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
                        while lines:
                            last_l = lines[-1]
                            if last_l == "[]" or (last_l.startswith('[') and len(last_l) < 15) or (len(last_l) < 7 and not re.search(r'[.。!?>]', last_l)):
                                lines.pop()
                            else:
                                break
            
                        # [Step 3] HTML 조립 (제목-본문 밀착)
                        formatted_html = ""
                        last_was_heading = False
                        for line in lines:
                            if any(x in line for x in ["기본 요약", "요약보기", "분석 결과"]): continue
                            
                            is_heading = (line.startswith('[') and line.endswith(']')) or \
                                         (len(line) < 55 and not re.search(r'[.。!?>]', line) and not line.endswith(('다', '요', 'ね', 'る', '了')))
                            
                            if is_heading:
                                title = line.replace('[', '').replace(']', '').strip()
                                if formatted_html: formatted_html += "<br><br>"
                                formatted_html += f"<b>[{title}]</b><br>"
                                last_was_heading = True
                            else:
                                if last_was_heading: formatted_html += line
                                else: formatted_html += " " + line
                                last_was_heading = False
            
                        d_text = formatted_html.strip()
                        if len(d_text) < 15: d_text = raw_text.replace('\n', '<br>')
            
# [Step 4] 출력 및 8-K 프리미엄 블러 처리 (Tab 0 내부 로직)
                if t_topic == "8-K" and not is_premium:
                    # 🔒 비결제자 블러 처리
                    locked_8k_html = """
                    <div style="position: relative; width: 100%; margin-top: 10px;">
                        <div style="filter: blur(5px); opacity: 0.4; padding: 15px; line-height: 1.6; user-select: none;">
                            <b>[핵심 이벤트]</b><br>최근 발생한 주요 공시 사유 요약 내용이 표시됩니다. 회사의 재무 상태 및 주가에 영향을 줄 수 있는 중대한 결정 사항입니다.<br><br>
                            <b>[재무 파급력]</b><br>해당 이벤트가 기업의 매출, 영업이익, 현금흐름 등에 미치는 단기 및 장기적 파급 효과 분석이 이곳에 표시됩니다.<br><br>
                            <b>[향후 전망]</b><br>투자자가 주의 깊게 살펴봐야 할 핵심 투자 포인트와 향후 예상 시나리오입니다.
                        </div>
                        <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center; width: 100%;">
                            <span style="background-color: rgba(32, 33, 36, 0.85); color: #ffffff; padding: 12px 24px; border-radius: 30px; font-weight: 600; font-size: 16px; letter-spacing: 0.5px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                                🔒 Premium Only
                            </span>
                        </div>
                    </div>
                    """
                    st.markdown(locked_8k_html, unsafe_allow_html=True)

                else:
                    # ✅ 결제 회원 혹은 일반 공시 출력 (8-K가 아니거나 프리미엄인 경우)
                    if d_text:
                        st.markdown(f'<div style="line-height:1.8; text-align:justify; font-size:15px; color:#333; white-space: pre-wrap;">{d_text}</div>', unsafe_allow_html=True)
                    else:
                        st.info("해당 서류의 분석 리포트를 생성 중이거나 데이터가 없습니다.")

                    # 4. 외부 링크 및 하단 버튼
                    import urllib.parse
                    cik_val = profile.get('cik', '') if profile else ''
                    sec_q_val = "10-K" if t_topic in ["BS", "IS", "CF"] else t_topic
                    
                    if cik_val: 
                        sec_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_val}&type={urllib.parse.quote(sec_q_val)}&owner=include&count=40"
                    else: 
                        sec_url = f"https://www.sec.gov/edgar/search/#/q={urllib.parse.quote(stock['name'])}"
                    
                    st.markdown(f'<a href="{sec_url}" target="_blank" style="text-decoration:none;"><button style="width:100%; padding:15px; background:white; border:1px solid #004e92; color:#004e92; border-radius:10px; font-weight:bold; cursor:pointer; margin-bottom: 12px;">{get_text("btn_sec_link")} ({t_topic})</button></a>', unsafe_allow_html=True)

                    # 🚀 어닝 콜 (Earnings Call) 섹션
                    ec_summary = get_premium_tab0_ec(sid, st.session_state.lang)
                    if ec_summary:
                        with st.expander(get_text('tab0_ec_title'), expanded=False):
                            if is_premium:
                                st.markdown(ec_summary, unsafe_allow_html=True)
                            else:
                                blur_text = get_text('desc_ec_blur')
                                st.markdown(f'<div style="filter: blur(5.5px); opacity: 0.4; padding: 20px;">{blur_text}</div>', unsafe_allow_html=True)
                
                # 🚨 [가장 중요한 원인!!] 이 두 줄은 위의 else: 와 수직선이 똑같아야 합니다.
                # 이 줄들이 왼쪽으로 빠져나가 있으면 그 아래 elif가 에러를 냅니다.
                draw_decision_box("filing", get_text('decision_question_filing'), ['sentiment_positive', 'sentiment_neutral', 'sentiment_negative'], current_p)
                display_disclaimer()

            # 🚨 [여기서부터 다시 왼쪽으로 4칸 당겨집니다]
            elif selected_sub_menu == get_text('tab_1'):
                curr_lang = st.session_state.lang
                
                # user_info 안전 장치
                user_info = st.session_state.get('user_info') or {}
                user_level = user_info.get('membership_level', 'free')
                is_premium = user_level in ['premium', 'premium_plus']
                with st.spinner(get_text('msg_analyzing_tab1')):
                    # 1. 무료 데이터 분석 로드
                    biz_info, final_display_news = get_unified_tab1_analysis(
                        stock['name'], 
                        stock['symbol'], 
                        curr_lang, 
                        stock.get('status', 'Unknown'), 
                        stock.get('date') 
                    )
                    # 2. 프리미엄 데이터 요약 로드
                    news_summary, pr_summary = get_premium_tab1_summaries(sid, curr_lang)

                st.write("<br>", unsafe_allow_html=True)
                
                # =========================================================
                # [1] 비즈니스 모델 요약 (모든 유저 열람 가능)
                # =========================================================
                with st.expander(get_text('expander_biz_summary'), expanded=False):
                    if biz_info:
                        st.markdown(f"""
                        <div style="background-color: #f8f9fa; padding: 22px; border-radius: 12px; border-left: 5px solid #6e8efb; color: #333; font-family: 'Pretendard', sans-serif; font-size: 15px; line-height: 1.6;">
                            {biz_info}
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # 🚨 호출 키값을 수정합니다
                        st.caption(get_text('caption_biz_source'))
                        
                    else:
                        st.error(get_text('err_no_biz_info'))

                # =========================================================
                # 🚀 [2] 기관용 금융 뉴스 요약 (Premium 전용 - Blur 적용)
                # =========================================================
                if news_summary: 
                    with st.expander(get_text('tab1_premium_news_title'), expanded=False):
                        if is_premium:
                            st.markdown(news_summary, unsafe_allow_html=True)
                        else:
                            # 비결제자 Blur 화면
                            blur_text = "최근 월가 기관들은 이 기업의 잉여 현금 흐름과 신규 프로젝트의 수익성에 대해 매우 긍정적인 평가를 내리고 있습니다... (이하 생략)"
                            st.markdown(f"""
                                <div style="position: relative; border-radius: 10px; overflow: hidden; border: 1px solid #e0e0e0; padding: 20px;">
                                    <div style="filter: blur(5.5px); user-select: none; color: #333; line-height: 1.8;">{blur_text}</div>
                                    <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,255,255,0.4); display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center;">
                                        <h4 style="color: #004e92; margin-bottom: 10px;">🔒 Premium Only</h4>
                                        <p style="color: #333; font-weight: bold; margin-bottom: 15px;">{get_text('msg_premium_lock')}</p>
                                    </div>
                                </div>
                            """, unsafe_allow_html=True)

                # =========================================================
                # 🚀 [3] 기업 공식 보도자료 요약 (Premium 전용 - Blur 적용)
                # =========================================================
                if pr_summary:
                    with st.expander(get_text('tab1_press_release_title'), expanded=False):
                        if is_premium:
                            st.markdown(pr_summary, unsafe_allow_html=True)
                        else:
                            # 비결제자 Blur 화면
                            blur_text = "본 기업은 최근 핵심 소프트웨어의 메이저 업그레이드 버전을 성공적으로 런칭했으며, 글로벌 시장 점유율 확대를 위한 대규모 마케팅 캠페인을 전개할 예정임을 공식적으로 발표했습니다... (이하 블러 처리)"
                            st.markdown(f"""
                                <div style="position: relative; border-radius: 10px; overflow: hidden; border: 1px solid #e0e0e0; padding: 20px;">
                                    <div style="filter: blur(5.5px); user-select: none; color: #333; line-height: 1.8;">{blur_text}</div>
                                    <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,255,255,0.4); display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center;">
                                        <h4 style="color: #004e92; margin-bottom: 10px;">🔒 Premium Only</h4>
                                        <p style="color: #333; font-weight: bold; margin-bottom: 15px;">{get_text('msg_premium_lock')}</p>
                                    </div>
                                </div>
                            """, unsafe_allow_html=True)

                # =========================================================
                # 🚀 [4] Recent News (UI 통합 최적화 버전)
                # =========================================================
                st.markdown(f"#### {get_text('tab1_recent_news_title')}")
                
                if final_display_news:
                    # 💡 [핵심 수정] 리스트에 몇 개가 있든 무조건 최상위 5개만 자릅니다!
                    top5_news = final_display_news[:5]
                    
                    news_html = '<div style="background-color: #ffffff; border: 1px solid #e0e0e0; border-radius: 12px; padding: 20px; box-shadow: 0 4px 10px rgba(0,0,0,0.03); margin-bottom: 20px;">'
                    
                    for i, n in enumerate(top5_news):
                        en_title = n.get('title_en', 'No Title')
                        trans_title = n.get('translated_title') or n.get('title_ko') or n.get('title_ja') or n.get('title_jp') or n.get('title', '')
                        
                        raw_sentiment = n.get('sentiment', '일반')
                        if "긍정" in raw_sentiment or "肯定" in raw_sentiment: 
                            sentiment_label = get_text('sentiment_positive')
                            s_color = "#1e8e3e"
                            s_bg = "#e6f4ea"
                        elif "부정" in raw_sentiment or "否定" in raw_sentiment: 
                            sentiment_label = get_text('sentiment_negative')
                            s_color = "#d93025"
                            s_bg = "#fce8e6"
                        else: 
                            sentiment_label = get_text('sentiment_neutral')
                            s_color = "#5f6368"
                            s_bg = "#f1f3f4"
                        
                        news_link = n.get('link', '#')
                        news_date = n.get('date', 'Recent')
                        
                        safe_en = str(en_title).replace("$", "\\$")
                        safe_trans = str(trans_title).replace("$", "\\$")
                        
                        sub_title_html = ""
                        if safe_trans and safe_trans != safe_en and curr_lang != 'en': 
                            if curr_lang == 'ko': sub_title_html = f"<div style='font-size:14.5px; color:#555; font-weight:500; margin-top:3px;'>🇰🇷 {safe_trans}</div>"
                            elif curr_lang == 'ja': sub_title_html = f"<div style='font-size:14.5px; color:#555; font-weight:500; margin-top:3px;'>🇯🇵 {safe_trans}</div>"
                            elif curr_lang == 'zh': sub_title_html = f"<div style='font-size:14.5px; color:#555; font-weight:500; margin-top:3px;'>🇨🇳 {safe_trans}</div>"

                        s_badge = f'<span style="background:{s_bg}; color:{s_color}; padding:2px 8px; border-radius:12px; font-size:11px; font-weight:bold; margin-left:8px;">{sentiment_label}</span>'
                        label_gen = get_text('label_general')
                        
                        # 하단 선 긋기 (마지막 항목은 선 제외)
                        border_style = "border-bottom: 1px solid #f0f0f0; margin-bottom: 15px; padding-bottom: 15px;" if i < len(top5_news) - 1 else "margin-bottom: 5px;"
                        
                        # 🚨 주의: 아래 HTML 텍스트는 절대 들여쓰기 하지 마세요!
                        news_html += f"""
<div style="{border_style}">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 6px;">
        <div style="display:flex; align-items:center;">
            <span style="color:#004e92; font-weight:800; font-size:13px; letter-spacing:0.5px;">TOP {i+1}</span> 
            <span style="color:#ccc; font-size:12px; margin: 0 6px;">|</span>
            <span style="color:#888; font-size:12px;">{label_gen}</span>
            {s_badge}
        </div>
        <div style="color:#aaa; font-size:11px;">{news_date}</div>
    </div>
    <a href="{news_link}" target="_blank" style="text-decoration:none; display:block; transition: opacity 0.2s;">
        <div style="color:#222; font-weight:700; font-size:15px; line-height:1.4;">
            {safe_en}
        </div>
        {sub_title_html}
    </a>
</div>
"""
                    news_html += "</div>"
                    st.markdown(news_html, unsafe_allow_html=True)
                else:
                    st.warning(get_text('err_no_news'))

                st.write("<br>", unsafe_allow_html=True)
                draw_decision_box("news", get_text('decision_news_impression'), ['sentiment_positive', 'sentiment_neutral', 'sentiment_negative'], current_p)
                display_disclaimer()
                
            # --- Tab 2: 실시간 시장 과열 진단 (3개 통합 카드 + 이중 AI 분석 적용) ---
            elif selected_sub_menu == get_text('tab_2'):
                with st.spinner(get_text('msg_analyzing_macro')):
                    # 1. 지표 데이터 로드
                    all_df_tab2 = all_df if 'all_df' in locals() else get_extended_ipo_data(MY_API_KEY)
                    md = get_cached_market_status(all_df_tab2, MY_API_KEY)
                    lang = st.session_state.lang
                    
                    # 🚀 [핵심 1] 3D 카드용 '심층 요약 조각' 로드
                    res_sum = supabase.table("analysis_cache").select("content").eq("cache_key", f"Global_Market_Summary_{lang}").execute()
                    sum_text = res_sum.data[0]['content'] if res_sum.data else ""
                    
                    # 💡 [정규식 클리너 추가] AI가 남긴 "(1번 카드:", "Card 1:", 괄호 찌꺼기를 완벽히 제거하는 함수
                    import re
                    def clean_ai_card_text(text):
                        if not text: return ""
                        # "(1번 카드: ", "(Card 1: ", "(カード1: " 등 시작 부분 제거
                        text = re.sub(r'^\(\s*\d+[^:]+:\s*', '', text.strip())
                        # 마지막 닫는 괄호 ")" 제거
                        if text.endswith(')'):
                            text = text[:-1]
                        return text.strip()

                    try:
                        ai_parts = [p.strip() for p in sum_text.split('|||SEP|||')]
                        c1_sum = clean_ai_card_text(ai_parts[0]) if len(ai_parts) > 0 else ""
                        c2_sum = clean_ai_card_text(ai_parts[1]) if len(ai_parts) > 1 else ""
                        c3_sum = clean_ai_card_text(ai_parts[2]) if len(ai_parts) > 2 else ""
                    except:
                        c1_sum = c2_sum = c3_sum = ""

                    # 🚀 [핵심 2] 하단 익스팬더용 '전문 리포트' 로드
                    full_market_report = get_market_dashboard_analysis(md, lang)

                # 💡 [CSS] 4~5문장 분량을 소화하기 위해 group-desc 최적화
                st.markdown("""
                <style>
                    .group-card { background:#ffffff; padding:20px; border-radius:18px; border:1px solid #e0e0e0; margin-bottom:20px; box-shadow:0 4px 12px rgba(0,0,0,0.05); min-height: 380px; display: flex; flex-direction: column; }
                    .group-title { font-size:16px; font-weight:800; color:#111; margin-bottom:10px; border-bottom: 2px solid #f0f0f0; padding-bottom: 8px; }
                    .group-desc { font-size:14px; color:#333; font-weight:500; margin-bottom:18px; line-height:1.6; background:#f8f9fa; padding:15px; border-radius:10px; border-left: 4px solid #004e92; flex-grow: 1; overflow-y: auto; min-height: 130px; text-align: justify; }
                    .sub-grid { display: grid; grid-template-columns: 1fr; gap: 8px; flex-grow: 0; margin-top: auto; }
                    .sub-item { background:#f9f9fb; padding:10px 14px; border-radius:10px; border: 1px solid #f0f0f0; display: flex; justify-content: space-between; align-items: center; }
                    .sub-label { font-size:12px; color:#666; font-weight:500; }
                    .sub-value { font-size:15px; font-weight:700; color:#111; }
                    .sub-badge { font-size:10px; padding: 2px 6px; border-radius:5px; font-weight:bold; margin-left:8px; }
                    .bg-hot { background-color:#ffebee; color:#c62828; }
                    .bg-cold { background-color:#e3f2fd; color:#1565c0; }
                    .bg-good { background-color:#e8f5e9; color:#2e7d32; }
                    .bg-neutral { background-color:#f5f5f5; color:#616161; }
                </style>
                """, unsafe_allow_html=True)

                def get_badge(status_key):
                    stat_map = {"over": ("과열", "bg-hot"), "good": ("적정", "bg-good"), "cold": ("침체", "bg-cold"), "risk": ("위험", "bg-hot"), "greed": ("탐욕", "bg-hot"), "fear": ("공포", "bg-cold"), "high": ("고가", "bg-hot"), "normal": ("보통", "bg-neutral")}
                    label, cls = stat_map.get(status_key, ("-", "bg-neutral"))
                    return f'<span class="sub-badge {cls}">{label}</span>'

                # --- 3개 통합 카드 렌더링 ---
                col1, col2, col3 = st.columns(3)

                with col1: # [Card 1] IPO 시장 심리
                    ret = md.get('ipo_return', 0); w_rate = md.get('withdrawal_rate', 0)
                    # 💡 불필요한 "💡 AI Sentiment analysis:" 문구를 제거했습니다.
                    st.markdown(f"""<div class="group-card">
                        <div class="group-title">{get_text('tab2_card1_title')}</div>
                        <div class="group-desc">{c1_sum}</div>
                        <div class="sub-grid">
                            <div class="sub-item"><span class="sub-label">{get_text('label_ret_name')}</span><span class="sub-value">{ret:+.1f}%{get_badge("over" if ret>=20 else "good")}</span></div>
                            <div class="sub-item"><span class="sub-label">{get_text('label_with_name')}</span><span class="sub-value">{w_rate:.1f}%{get_badge("over" if w_rate<5 else "good")}</span></div>
                        </div>
                    </div>""", unsafe_allow_html=True)

                with col2: # [Card 2] IPO 공급 및 질적 위험
                    vol = md.get('ipo_volume', 0); unp = md.get('unprofitable_pct', 0)
                    st.markdown(f"""<div class="group-card">
                        <div class="group-title">{get_text('tab2_card2_title')}</div>
                        <div class="group-desc">{c2_sum}</div>
                        <div class="sub-grid">
                            <div class="sub-item"><span class="sub-label">{get_text('label_vol_name')}</span><span class="sub-value">{vol}건{get_badge("over" if vol>=15 else "normal")}</span></div>
                            <div class="sub-item"><span class="sub-label">{get_text('label_unprof_name')}</span><span class="sub-value">{unp:.0f}%{get_badge("risk" if unp>=80 else "good")}</span></div>
                        </div>
                    </div>""", unsafe_allow_html=True)

                with col3: # [Card 3] 미국 증시 펀더멘털
                    vix = md.get('vix', 20); buff = md.get('buffett_val', 100); pe = md.get('pe_ratio', 20); fg = md.get('fear_greed', 50)
                    st.markdown(f"""<div class="group-card">
                        <div class="group-title">{get_text('tab2_card3_title')}</div>
                        <div class="group-desc">{c3_sum}</div>
                        <div class="sub-grid">
                            <div class="sub-item"><span class="sub-label">{get_text('label_vix_fg_name')}</span><span class="sub-value" style="font-size:14px;">{vix:.1f} / {fg:.0f}{get_badge("greed" if vix<=15 else "normal")}</span></div>
                            <div class="sub-item"><span class="sub-label">{get_text('label_buff_pe_name')}</span><span class="sub-value" style="font-size:14px;">{buff:.0f}% / {pe:.1f}x{get_badge("high" if pe>25 else "good")}</span></div>
                        </div>
                    </div>""", unsafe_allow_html=True)

                st.write("<br>", unsafe_allow_html=True)

                # 💡 [복구 완료] 거시지표 통합 분석 리포트 전문 보기
                with st.expander(get_text('expander_macro_analysis'), expanded=False): 
                    # AI가 만든 줄바꿈(\n)을 HTML 줄바꿈(<br>)으로 변환하여 깨짐 방지
                    formatted_report = full_market_report.replace('\n', '<br>')
                    
                    st.markdown(f"""
                        <div style='background-color:#f8f9fa; padding:22px; border-radius:12px; border-left: 5px solid #004e92; font-size:15px; line-height:1.8; color:#333; text-align:justify;'>
                            {formatted_report}
                        </div>
                    """, unsafe_allow_html=True)
            
                # =========================================================
                # 🚀 [NEW] Tab 2 기업 ESG 평가 등급 프리미엄 섹션
                # =========================================================
                # 💡 [방어막] 유저 결제 상태 확인
                raw_info = st.session_state.get('user_info')
                user_info = raw_info if isinstance(raw_info, dict) else {}
                user_level = user_info.get('membership_level', 'free')
                is_premium = user_level in ['premium', 'premium_plus']
                
                esg_summary = get_premium_tab2_esg(sid, st.session_state.lang)
                
                if esg_summary:
                    with st.expander(get_text('tab2_esg_title'), expanded=False):
                        if is_premium:
                            st.markdown(esg_summary, unsafe_allow_html=True)
                        else:
                            blur_text = get_text('desc_esg_blur')
                            st.markdown(f"""
                                <div style="position: relative; border-radius: 10px; overflow: hidden; border: 1px solid #e0e0e0; padding: 20px;">
                                    <div style="filter: blur(5.5px); user-select: none; color: #333; line-height: 1.8;">{blur_text}</div>
                                    <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,255,255,0.4); display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center;">
                                        <h4 style="color: #004e92; margin-bottom: 10px;">🔒 Premium Only</h4>
                                        <p style="color: #333; font-weight: bold; margin-bottom: 15px;">{get_text('msg_premium_lock')}</p>
                                    </div>
                                </div>
                            """, unsafe_allow_html=True)
            
                draw_decision_box("macro", get_text('decision_macro_outlook'), ['opt_bubble', 'sentiment_neutral', 'opt_recession'], current_p)
                display_disclaimer()  
            
            # --- Tab 3: 개별 기업 재무 평가 (3개 통합 카드 + 이중 AI 분석) ---
            elif selected_sub_menu == get_text('tab_3'):
                curr_lang = st.session_state.lang
                is_ko = (curr_lang == 'ko')

                with st.spinner(get_text('msg_analyzing_financial')):
                    # 1. 워커가 저장한 재무 숫자 데이터 로드
                    fin_data = get_cached_raw_financials(stock['symbol'])
                    
                    # 피오트로스키 점수 추출
                    if fin_data:
                        raw_p_score = clean_value(fin_data.get('health_score', 0))
                        fin_data['piotroski_score_raw'] = int(raw_p_score)

                    data_source = "FMP Premium API" if (fin_data and len(fin_data) > 5) else "Data Unavailable"
                    
                    # 🚀 [핵심 1] 3D 카드용 '심층 요약 조각' 로드 (Tab3_Summary)
                    res_sum = supabase.table("analysis_cache").select("content").eq("cache_key", f"{sid}_Tab3_Summary_{curr_lang}").execute()
                    sum_text = res_sum.data[0]['content'] if res_sum.data else ""
                    
                    # 💡 [대체 텍스트 완전 삭제] 캐시가 없으면 빈칸 처리
                    try:
                        ai_parts = [p.strip() for p in sum_text.split('|||SEP|||')]
                        c1_sum = ai_parts[0] if len(ai_parts) > 0 else ""
                        c2_sum = ai_parts[1] if len(ai_parts) > 1 else ""
                        c3_sum = ai_parts[2] if len(ai_parts) > 2 else ""
                    except:
                        c1_sum = c2_sum = c3_sum = ""

                    # 🚀 [핵심 2] 하단 익스팬더용 '논문 기반 CFA 전문 리포트' 로드 (Tab3_v2_Premium)
                    full_financial_report = get_financial_report_analysis(stock['name'], sid, {}, curr_lang)

                # 💡 [CSS] 4~5문장 소화용 높이와 스크롤 최적화
                st.markdown("""
                <style>
                    .group-card { background:#ffffff; padding:20px; border-radius:18px; border:1px solid #e0e0e0; margin-bottom:20px; box-shadow:0 4px 12px rgba(0,0,0,0.05); min-height: 400px; display: flex; flex-direction: column; }
                    .group-title { font-size:16px; font-weight:800; color:#111; margin-bottom:10px; border-bottom: 2px solid #f0f0f0; padding-bottom: 8px; }
                    .group-desc { font-size:13px; color:#004e92; font-weight:500; margin-bottom:18px; line-height:1.6; background:#f0f7ff; padding:15px; border-radius:10px; border-left: 4px solid #004e92; flex-grow: 1; overflow-y: auto; min-height: 150px; }
                    .sub-grid { display: grid; grid-template-columns: 1fr; gap: 8px; flex-grow: 0; margin-top: auto; }
                    .sub-item { background:#f9f9fb; padding:10px 14px; border-radius:10px; border: 1px solid #f0f0f0; display: flex; justify-content: space-between; align-items: center; }
                    .sub-label { font-size:12px; color:#666; font-weight:500; }
                    .sub-value { font-size:15px; font-weight:700; color:#111; }
                    .sub-badge { font-size:10px; padding: 2px 6px; border-radius:5px; font-weight:bold; margin-left:8px; }
                    .bg-hot { background-color:#ffebee; color:#c62828; }
                    .bg-cold { background-color:#e3f2fd; color:#1565c0; }
                    .bg-good { background-color:#e8f5e9; color:#2e7d32; }
                    .bg-neutral { background-color:#f5f5f5; color:#616161; }
                </style>
                """, unsafe_allow_html=True)

                def get_badge(status_key):
                    stat_map = {"over": ("경고", "bg-hot"), "good": ("우수", "bg-good"), "cold": ("침체", "bg-cold"), "risk": ("위험", "bg-hot"), "neutral": ("보통", "bg-neutral")}
                    label, cls = stat_map.get(status_key, ("-", "bg-neutral"))
                    return f'<span class="sub-badge {cls}">{label}</span>'

                # --- 데이터 전처리 ---
                growth = clean_value(fin_data.get('growth', 0))
                net_m_val = clean_value(fin_data.get('net_margin', 0))
                de_ratio = clean_value(fin_data.get('debt_equity', 0))
                pe_val = clean_value(fin_data.get('pe', fin_data.get('forward_pe', 0)))
                accruals_status = str(fin_data.get('accruals', 'Unknown'))
                
                growth_disp = fin_data.get('growth', f"{growth:+.1f}%") if str(fin_data.get('growth')) not in ["N/A", "None", ""] else "N/A"
                net_m_disp = fin_data.get('net_margin', f"{net_m_val:.1f}%") if str(fin_data.get('net_margin')) not in ["N/A", "None", ""] else "N/A"
                de_disp = f"{de_ratio:.1f}%" if de_ratio > 0 else "N/A"
                pe_disp = f"{pe_val:.1f}x" if pe_val > 0 else "N/A"
                
                dcf_raw = str(fin_data.get('dcf_price', '0')).replace('$', '').replace(',', '').strip()
                dcf_p = float(dcf_raw) if dcf_raw not in ['N/A', 'Unknown', 'None', ''] else 0.0
                gap_pct = ((dcf_p - current_p) / current_p * 100) if current_p > 0 and dcf_p > 0 else 0

                up_rate = ((current_p - off_val) / off_val * 100) if current_p > 0 and off_val > 0 else 0
                perf_disp = f"{up_rate:+.1f}%" if current_p > 0 and off_val > 0 else "N/A"

                # --- 3개 통합 카드 렌더링 ---
                col1, col2, col3 = st.columns(3)

                with col1: # [Card 1] 비즈니스 성장 및 수익성
                    st.markdown(f"""<div class="group-card">
                        <div class="group-title">{get_text('tab3_card1_title')}</div>
                        <div class="sub-grid">
                            <div class="sub-item"><span class="sub-label">Sales Growth</span><span class="sub-value">{growth_disp}{get_badge("good" if growth > 5 else "over" if growth < 0 else "neutral")}</span></div>
                            <div class="sub-item"><span class="sub-label">Net Margin</span><span class="sub-value">{net_m_disp}{get_badge("good" if net_m_val > 0 else "over")}</span></div>
                            <div class="sub-item"><span class="sub-label">Piotroski Score</span><span class="sub-value">{fin_data.get('piotroski_score_raw', 0)}/9{get_badge("good" if fin_data.get('piotroski_score_raw', 0) >= 6 else "over" if fin_data.get('piotroski_score_raw', 0) <= 3 else "neutral")}</span></div>
                        </div>
                    </div>""", unsafe_allow_html=True)

                with col2: # [Card 2] 재무 건전성
                    acc_badge = "good" if accruals_status == "Low" else "over" if accruals_status == "High" else "neutral"
                    st.markdown(f"""<div class="group-card">
                        <div class="group-title">{get_text('tab3_card2_title')}</div>
                        <div class="sub-grid">
                            <div class="sub-item"><span class="sub-label">Debt / Equity</span><span class="sub-value">{de_disp}{get_badge("good" if 0 < de_ratio < 100 else "over" if de_ratio >= 100 else "neutral")}</span></div>
                            <div class="sub-item"><span class="sub-label">Accruals Quality</span><span class="sub-value">{accruals_status}{get_badge(acc_badge)}</span></div>
                        </div>
                    </div>""", unsafe_allow_html=True)

                with col3: # [Card 3] 밸류에이션
                    st.markdown(f"""<div class="group-card">
                        <div class="group-title">{get_text('tab3_card3_title')}</div>
                        <div class="sub-grid">
                            <div class="sub-item"><span class="sub-label">Forward P/E</span><span class="sub-value">{pe_disp}{get_badge("good" if 0 < pe_val < 25 else "over" if pe_val >= 25 else "neutral")}</span></div>
                            <div class="sub-item"><span class="sub-label">DCF Gap</span><span class="sub-value">{gap_pct:+.1f}%{get_badge("good" if gap_pct > 0 else "over" if gap_pct < 0 else "neutral")}</span></div>
                            <div class="sub-item"><span class="sub-label">IPO Return</span><span class="sub-value">{perf_disp}{get_badge("over" if up_rate > 20 else "good" if up_rate >= 0 else "cold")}</span></div>
                        </div>
                    </div>""", unsafe_allow_html=True)

                st.write("<br>", unsafe_allow_html=True)

                # 💡 [하단 전문 복구] 논문 기반 CFA 퀀트 리포트
                with st.expander(get_text('expander_academic_analysis'), expanded=False): 
                    st.markdown(f"""
                        <div style='background-color:#f8f9fa; padding:22px; border-radius:12px; border-left: 5px solid #004e92; font-size:15px; line-height:1.8; color:#333; text-align:justify;'>
                            {full_financial_report}
                        </div>
                    """, unsafe_allow_html=True)
                    st.caption(f"Data Source: {data_source} / Currency: USD")

                # =========================================================
                # 🚀 [Premium 섹션 완벽 복원] 어닝 서프라이즈, 실적 전망치, 부문별 매출
                # =========================================================
                surp_summary, est_summary = get_premium_tab3_summaries(sid, curr_lang)
                
                # 유저 프리미엄 권한 확인
                user_info = st.session_state.get('user_info') if isinstance(st.session_state.get('user_info'), dict) else {}
                is_premium = user_info.get('membership_level', 'free') in ['premium', 'premium_plus']

                if surp_summary:
                    with st.expander(get_text('tab3_surprise_title'), expanded=False):
                        if is_premium:
                            st.markdown(surp_summary, unsafe_allow_html=True)
                        else:
                            blur_text = "최근 4분기 연속으로 월가 애널리스트들의 주당순이익(EPS) 예상치를 평균 15% 이상 상회(Beat)하는 어닝 서프라이즈를 기록했습니다. 이는 동종 업계 대비 압도적인 비용 통제 능력을... (이하 블러 처리)"
                            st.markdown(f"""<div style="position: relative; border-radius: 10px; overflow: hidden; border: 1px solid #e0e0e0; padding: 20px;"><div style="filter: blur(5.5px); user-select: none; color: #333; line-height: 1.8;">{blur_text}</div><div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,255,255,0.4); display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center;"><h4 style="color: #004e92; margin-bottom: 10px;">🔒 Premium Only</h4><p style="color: #333; font-weight: bold; margin-bottom: 15px;">{get_text('msg_premium_lock')}</p></div></div>""", unsafe_allow_html=True)

                if est_summary:
                    with st.expander(get_text('tab3_estimate_title'), expanded=False):
                        if is_premium:
                            st.markdown(est_summary, unsafe_allow_html=True)
                        else:
                            blur_text = "월가 컨센서스에 따르면, 내년도 예상 매출액은 전년 대비 약 35% 폭증할 것으로 추정되며, 주당순이익(EPS) 역시 적자에서 흑자로 턴어라운드(Turnaround)할 강력한 모멘텀을... (이하 블러 처리)"
                            st.markdown(f"""<div style="position: relative; border-radius: 10px; overflow: hidden; border: 1px solid #e0e0e0; padding: 20px;"><div style="filter: blur(5.5px); user-select: none; color: #333; line-height: 1.8;">{blur_text}</div><div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,255,255,0.4); display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center;"><h4 style="color: #004e92; margin-bottom: 10px;">🔒 Premium Only</h4><p style="color: #333; font-weight: bold; margin-bottom: 15px;">{get_text('msg_premium_lock')}</p></div></div>""", unsafe_allow_html=True)

                rev_summary = get_premium_tab3_revenue(sid, st.session_state.lang)
                if rev_summary:
                    with st.expander(get_text('tab3_revenue_title'), expanded=False):
                        if is_premium:
                            st.markdown(rev_summary, unsafe_allow_html=True)
                        else:
                            blur_text = get_text('desc_revenue_blur')
                            st.markdown(f"""
                                <div style="position: relative; border-radius: 10px; overflow: hidden; border: 1px solid #e0e0e0; padding: 20px;">
                                    <div style="filter: blur(5.5px); user-select: none; color: #333; line-height: 1.8;">{blur_text}</div>
                                    <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,255,255,0.4); display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center;">
                                        <h4 style="color: #004e92; margin-bottom: 10px;">🔒 Premium Only</h4>
                                        <p style="color: #333; font-weight: bold; margin-bottom: 15px;">{get_text('msg_premium_lock')}</p>
                                    </div>
                                </div>
                            """, unsafe_allow_html=True)

                # =========================================================
                # 🚀 [의사결정 및 면책조항 완벽 복원]
                # =========================================================
                draw_decision_box("company", f"{stock['name']} {get_text('decision_valuation_verdict')}", ['opt_overvalued', 'sentiment_neutral', 'opt_undervalued'], current_p)
                display_disclaimer()
    
            # --- Tab 4: 기관평가 (UI 출력 부분 다국어 적용) ---
            elif selected_sub_menu == get_text('tab_4'):
                curr_lang = st.session_state.lang
                
                # 💡 [에러 해결] Tab 1과 동일하게 user_info가 None일 때를 대비한 철벽 방어 코드 적용
                user_info = st.session_state.get('user_info') or {}
                user_level = user_info.get('membership_level', 'free')
                is_premium = user_level in ['premium', 'premium_plus']

                with st.spinner(get_text('msg_analyzing_institutional')):
                    # 1. 기존 무료 데이터 로드 (구글 검색 기반)
                    result = get_unified_tab4_analysis(
                        stock['name'], 
                        stock['symbol'], 
                        curr_lang, 
                        ipo_status=stock.get('status', 'Active'), 
                        ipo_date_str=stock.get('date')
                    )
                    # 2. 🚀 [NEW] 신규 프리미엄 데이터 로드 (FMP 기반)
                    ud_summary, peers_summary = get_premium_tab4_summaries(sid, curr_lang)
                
                summary_raw = result.get('summary', '')
                pro_con_raw = result.get('pro_con', '')
                rating_val = str(result.get('rating', 'Hold')).strip()
                score_val = str(result.get('score', '3')).strip() 
                sources = result.get('links', [])
                q = stock['symbol'] if stock['symbol'] else stock['name']
    
                st.write("<br>", unsafe_allow_html=True)

                # =========================================================
                # 🚀 [수정 완료] 1. 월가 컨센서스 & 목표 주가 (Premium 일관성 적용)
                # =========================================================
                target_price_val = str(result.get('target_price', 'N/A')).strip()
                has_pt_data = target_price_val not in ['N/A', '', 'None']
                
                # 💡 [UI 제어] 데이터가 있을 때만 렌더링하고, 결제 여부에 따라 블러를 씌웁니다!
                if has_pt_data:
                    with st.expander(get_text('expander_wallstreet_pt'), expanded=False):
                        if is_premium:
                            st.success(f"🎯 **평균 목표 주가 (Target Price) : {target_price_val}**")
                            st.caption("※ FMP Premium에서 실시간으로 수집된 월가 애널리스트 평균(Consensus) 데이터입니다." if curr_lang == 'ko' else "※ Wall Street Consensus from FMP Premium.")
                        else:
                            # 비결제자용 블러 화면
                            blur_text = "월가 주요 투자은행(IB)들이 제시한 평균 목표 주가는 현재가 대비 약 25% 상승 여력이 있는 것으로 분석되었습니다. 기관들의 세부 매수/매도 비율과 적정 주가 범위는... (이하 블러 처리)"
                            st.markdown(f"""
                                <div style="position: relative; border-radius: 10px; overflow: hidden; border: 1px solid #e0e0e0; padding: 20px;">
                                    <div style="filter: blur(5.5px); user-select: none; color: #333; line-height: 1.8;">{blur_text}</div>
                                    <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,255,255,0.4); display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center;">
                                        <h4 style="color: #004e92; margin-bottom: 10px;">🔒 Premium Only</h4>
                                        <p style="color: #333; font-weight: bold; margin-bottom: 15px;">{get_text('msg_premium_lock')}</p>
                                    </div>
                                </div>
                            """, unsafe_allow_html=True)
            
                # =========================================================
                # [기존 기능 유지] 2. 르네상스 & 시킹알파 요약
                # =========================================================
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
            
                # =========================================================
                # [기존 기능 유지] 3. 기관 투자 심리 (Sentiment)
                # =========================================================
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

                
                # =========================================================
                # 🚀 [NEW] 투자의견 변화추이 (Premium 전용 - Blur 적용)
                # =========================================================
                # 💡 [UI 제어] 데이터가 있을 때만 렌더링하고, 결제 여부에 따라 블러를 씌웁니다!
                if ud_summary:
                    with st.expander(get_text('tab4_upgrades_title'), expanded=False):
                        if is_premium:
                            st.markdown(ud_summary, unsafe_allow_html=True)
                        else:
                            blur_text = "모건스탠리는 최근 이 기업의 투자의견을 'Neutral'에서 'Buy'로 상향 조정했습니다. 목표가 역시 기존 대비 15% 상향된 수치를 제시하며 기관들의 강력한 매수세가 관측되고 있습니다... (이하 블러 처리)"
                            st.markdown(f"""<div style="position: relative; border-radius: 10px; overflow: hidden; border: 1px solid #e0e0e0; padding: 20px;"><div style="filter: blur(5.5px); user-select: none; color: #333; line-height: 1.8;">{blur_text}</div><div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,255,255,0.4); display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center;"><h4 style="color: #004e92; margin-bottom: 10px;">🔒 Premium Only</h4><p style="color: #333; font-weight: bold; margin-bottom: 15px;">{get_text('msg_premium_lock')}</p></div></div>""", unsafe_allow_html=True)

                # =========================================================
                # 🚀 [NEW] Sector내 비교 (Premium 전용 - Blur 적용)
                # =========================================================
                if peers_summary:
                    with st.expander(get_text('tab4_peers_title'), expanded=False):
                        if is_premium:
                            st.markdown(peers_summary, unsafe_allow_html=True)
                        else:
                            blur_text = "동일 섹터 내 경쟁사인 주요 상장사들과 비교할 때 본 기업의 주가수익비율(PER)은 상대적으로 저평가 구간에 머물러 있습니다. 이는 시장 점유율 확보 전략이... (이하 블러 처리)"
                            st.markdown(f"""<div style="position: relative; border-radius: 10px; overflow: hidden; border: 1px solid #e0e0e0; padding: 20px;"><div style="filter: blur(5.5px); user-select: none; color: #333; line-height: 1.8;">{blur_text}</div><div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,255,255,0.4); display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center;"><h4 style="color: #004e92; margin-bottom: 10px;">🔒 Premium Only</h4><p style="color: #333; font-weight: bold; margin-bottom: 15px;">{get_text('msg_premium_lock')}</p></div></div>""", unsafe_allow_html=True)
                
                # =========================================================
                # 🚀 [NEW] Tab 4 M&A 및 기업 인수합병 내역 프리미엄 섹션
                # =========================================================
                ma_summary = get_premium_tab4_ma(sid, st.session_state.lang)
                
                if ma_summary:
                    with st.expander(get_text('tab4_ma_title'), expanded=False):
                        if is_premium:
                            st.markdown(ma_summary, unsafe_allow_html=True)
                        else:
                            blur_text = get_text('desc_ma_blur')
                            st.markdown(f"""
                                <div style="position: relative; border-radius: 10px; overflow: hidden; border: 1px solid #e0e0e0; padding: 20px;">
                                    <div style="filter: blur(5.5px); user-select: none; color: #333; line-height: 1.8;">{blur_text}</div>
                                    <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,255,255,0.4); display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center;">
                                        <h4 style="color: #004e92; margin-bottom: 10px;">🔒 Premium Only</h4>
                                        <p style="color: #333; font-weight: bold; margin-bottom: 15px;">{get_text('msg_premium_lock')}</p>
                                    </div>
                                </div>
                            """, unsafe_allow_html=True)
            
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
                        # 💡 [수정됨] 이모지 제거 및 다국어 텍스트(추천/비추천) 적용
                        title_disp = f"{prefix} {display_title} | {p_auth} | {p_date} ({get_text('btn_recommend')} {likes}  {get_text('btn_dislike')} {dislikes})"
                        
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
                
                # 💡 [요청 사항 반영] 의사결정 박스(draw_decision_box) 제거. 면책조항만 출력!
                display_disclaimer()


            # ---------------------------------------------------------
            # 🔥 [NEW] Tab 6: 스마트머니 (Smart Money)
            # ---------------------------------------------------------
            elif selected_sub_menu == get_text('tab_6'):
                user_info = st.session_state.get('user_info') or {}
                user_level = (st.session_state.get('user_info') or {}).get('membership_level', 'free')
                corp_name = stock.get('corp_name', sid)
                curr_lang = st.session_state.lang
                
                if user_level == 'premium_plus':
                    # [기존 기능 1 & 2] 시장 평가 & 펀드매니저 평가
                    smart_eval_data = get_smart_money_market_eval(sid)
                    pro_eval_data = get_pro_fund_manager_eval(sid)

                    # [A] 80억 이상 자산가 시장평가 (Gauge Bar)
                    st.markdown(f"<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 15px;'> {get_text('label_market_eval_80b')}</div>", unsafe_allow_html=True)
                    
                    m_avg = smart_eval_data.get('market_avg', 0.0)
                    avg_pct = min(max(((m_avg + 5) / 10) * 100, 0), 100)
                    
                    user_score = 0
                    if 'user_decisions' in st.session_state and sid in st.session_state.user_decisions:
                        ud = st.session_state.user_decisions[sid]
                        score_map = {"긍정적": 1, "수용적": 1, "안정적": 1, "저평가": 1, "매수": 1, "침체": 1, "중립적": 0, "중립": 0, "적정": 0, "부정적": -1, "회의적": -1, "버블": -1, "고평가": -1, "매도": -1}
                        steps = ['filing', 'news', 'macro', 'company', 'ipo_report']
                        user_score = sum(score_map.get(ud.get(s, "중립적"), 0) for s in steps)
                    
                    user_pct = min(max(((user_score + 5) / 10) * 100, 0), 100)

                    gauge_html_smart = f"""<div style="background-color: #ffffff; padding: 45px 20px 75px 20px; border-radius: 15px; border: 1px solid #e0e0e0; box-shadow: 0 4px 10px rgba(0,0,0,0.03); margin-bottom: 30px;">
<div style="position: relative; width: 100%; height: 20px; background: linear-gradient(to right, #ff4b4b 0%, #f1f3f4 50%, #00ff41 100%); border-radius: 10px;">
    <div style="position: absolute; top: 30px; left: 0%; transform: translateX(0%); font-size: 13px; font-weight: 700; color: #d32f2f;">{get_text('label_gauge_recession')}</div>
    <div style="position: absolute; top: 30px; left: 50%; transform: translateX(-50%); font-size: 13px; font-weight: 700; color: #757575;">중립</div>
    <div style="position: absolute; top: 30px; left: 100%; transform: translateX(-100%); font-size: 13px; font-weight: 700; color: #2e7d32;">{get_text('label_gauge_bubble')}</div>
    <div style="position: absolute; top: -40px; left: {avg_pct}%; transform: translateX(-50%); text-align: center; z-index: 10;">
        <div style="font-size: 12px; font-weight: 800; color: #444; white-space: nowrap; background: #fff; padding: 3px 8px; border-radius: 6px; border: 1px solid #ccc; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">{get_text('label_market_avg')} : {m_avg:+.1f}</div>
        <div style="color: #444; font-size: 14px; margin-top: -4px;">▼</div>
    </div>
    <div style="position: absolute; top: -4px; left: {user_pct}%; transform: translateX(-50%); text-align: center; z-index: 20;">
        <div style="background-color: #004e92; color: #fff; border-radius: 50%; width: 28px; height: 28px; line-height: 22px; font-size: 13px; font-weight: bold; border: 3px solid #fff; box-shadow: 0 2px 5px rgba(0,0,0,0.3); margin: 0 auto;">나</div>
        <div style="font-size: 12px; font-weight: 800; color: #004e92; white-space: nowrap; margin-top: 32px;">나의 위치 ({user_score:+d})</div>
    </div>
</div>
</div>"""
                    st.markdown(gauge_html_smart, unsafe_allow_html=True)

                    # [B] 펀드매니저 평가 (Stacked Bar)
                    st.write("<br>", unsafe_allow_html=True)
                    pro_eval_title = get_text('label_pro_eval_corp').format(corp_name)
                    st.markdown(f"<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 15px;'>{pro_eval_title}</div>", unsafe_allow_html=True)
                    
                    up_pct = pro_eval_data.get('up_pct', 50.0)
                    down_pct = pro_eval_data.get('down_pct', 50.0)
                    total_votes = pro_eval_data.get('total_votes', 0)
                    
                    sentiment_html_smart = f"""<div style="margin-bottom: 20px; padding: 0 5px;">
<div style="display: flex; justify-content: space-between; margin-bottom: 8px; font-weight: 800; font-family: sans-serif;">
    <span style="color: #2e7d32; font-size: 1.2rem;">🐂 Bullish {up_pct:.0f}%</span>
    <span style="color: #d32f2f; font-size: 1.2rem;">{down_pct:.0f}% Bearish 🐻</span>
</div>
<div style="display: flex; width: 100%; height: 16px; border-radius: 8px; overflow: hidden; background-color: #f1f3f4; box-shadow: inset 0 1px 3px rgba(0,0,0,0.1);">
    <div style="width: {up_pct}%; background-color: #00ff41;"></div>
    <div style="width: {down_pct}%; background-color: #ff4b4b;"></div>
</div>
<div style="text-align: center; color: #888; font-size: 0.85rem; margin-top: 8px; font-weight: 600;">
    Total Votes: {total_votes:,}
</div>
</div>"""
                    st.markdown(sentiment_html_smart, unsafe_allow_html=True)
                    st.write("<br>", unsafe_allow_html=True)

                    # =========================================================
                    # 🚀 [NEW] SEC Form 4 (내부자 거래) & SEC 13F (기관 매집) & 정치인/공매도 AI 리포트
                    # =========================================================
                    sec_tracking_title = get_text('title_sec_smart_money')
                    st.markdown(f"<div style='font-size: 1.1rem; font-weight: 700; margin-bottom: 15px;'>{sec_tracking_title}</div>", unsafe_allow_html=True)
                    
                    with st.spinner("Decrypting SEC Smart Money filings..."):
                        # 💡 [핵심] 상단에 정의한 깔끔한 함수를 호출!
                        ai_report = get_smart_money_analysis_app(stock['name'], sid, curr_lang)

                        # 워커가 |||SEP||| 로 구분해서 보내준 4개 항목을 자름
                        parts = [p.strip() for p in ai_report.split('|||SEP|||')]
                        
                        # 각 항목의 제목 텍스트 찌꺼기를 정규식으로 안전하게 제거
                        import re
                        insider_text = re.sub(r'\*\*\[.*?\]\*\*', '', parts[0]).strip() if len(parts) > 0 else "No data"
                        inst_text = re.sub(r'\*\*\[.*?\]\*\*', '', parts[1]).strip() if len(parts) > 1 else "No data"
                        senate_text = re.sub(r'\*\*\[.*?\]\*\*', '', parts[2]).strip() if len(parts) > 2 else "No data"
                        ftd_text = re.sub(r'\*\*\[.*?\]\*\*', '', parts[3]).strip() if len(parts) > 3 else "No data"

                    # 1. 내부자 거래 카드 (기본 닫힘으로 변경)
                    with st.expander(get_text('expander_insider'), expanded=False):
                        st.markdown(f"<div style='font-size:0.95rem; color:#d32f2f; font-weight:600; margin-bottom:5px;'>CEO/Executives Flow</div>", unsafe_allow_html=True)
                        st.markdown(f"<div style='background-color:#fff3f3; padding:15px; border-radius:8px; border-left: 4px solid #d32f2f; color:#333; line-height:1.6;'>{insider_text}</div>", unsafe_allow_html=True)
                        
                    # 2. 고래(기관) 매집 카드 (기본 닫힘)
                    with st.expander(get_text('expander_institutional'), expanded=False):
                        st.markdown(f"<div style='font-size:0.95rem; color:#004e92; font-weight:600; margin-bottom:5px;'>Wall Street Whales</div>", unsafe_allow_html=True)
                        st.markdown(f"<div style='background-color:#f4f9ff; padding:15px; border-radius:8px; border-left: 4px solid #004e92; color:#333; line-height:1.6;'>{inst_text if inst_text else 'Analyzing institutional data...'}</div>", unsafe_allow_html=True)
                    
                    # 3. 🚨 [NEW] 상원의원 거래 카드 (기본 닫힘)
                    with st.expander(get_text('expander_senate'), expanded=False):
                        st.markdown(f"<div style='font-size:0.95rem; color:#6a11cb; font-weight:600; margin-bottom:5px;'>US Politicians Trades</div>", unsafe_allow_html=True)
                        st.markdown(f"<div style='background-color:#f3e8ff; padding:15px; border-radius:8px; border-left: 4px solid #6a11cb; color:#333; line-height:1.6;'>{senate_text}</div>", unsafe_allow_html=True)

                    # 4. 🚨 [NEW] 공매도 미결제 약정 (Short Squeeze) 카드 (기본 닫힘)
                    with st.expander(get_text('expander_ftd'), expanded=False):
                        st.markdown(f"<div style='font-size:0.95rem; color:#e67e22; font-weight:600; margin-bottom:5px;'>Short Squeeze Warning (FTD)</div>", unsafe_allow_html=True)
                        st.markdown(f"<div style='background-color:#fff3e0; padding:15px; border-radius:8px; border-left: 4px solid #e67e22; color:#333; line-height:1.6;'>{ftd_text}</div>", unsafe_allow_html=True)
                        
                    # 5. 다국어 출처 캡션 적용
                    st.caption(get_text('caption_smart_money_source'))

                else:
                    # 프리미엄 플러스가 아닌 일반/프리미엄 유저에게 보여주는 락업 UI
                    st.markdown("""
                        <div style="background-color: rgba(255,255,255,0.7); padding: 50px; text-align: center; backdrop-filter: blur(5px); border: 1px dashed #ccc; border-radius: 10px;">
                            <h3 style="color: #333;">🔒 SmartMoney Only</h3>
                            <p style="color: #666; font-size: 1.05rem;">월가 내부자 거래, 기관 매집, 국회의원 거래 및 숏스퀴즈 추적 리포트는 <b>프리미엄 플러스</b> 등급부터 열람 가능합니다.</p>
                        </div>
                    """, unsafe_allow_html=True)

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

draw_footer()
                
                        
        
                
                
                
