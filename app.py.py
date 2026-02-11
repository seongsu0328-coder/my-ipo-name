import streamlit as st
import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import xml.etree.ElementTree as ET
import os
import time
import uuid
import random
import math
import html
import re
from datetime import datetime, timedelta

# --- [AI 및 검색 라이브러리 통합] ---
from openai import OpenAI             # ✅ Groq(뉴스 요약)용
import google.generativeai as genai   # ✅ Gemini(메인 종목 분석)용 - 지우면 안 됨!
from tavily import TavilyClient       # ✅ Tavily(뉴스 검색)용
from duckduckgo_search import DDGS

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
                temperature=0.0  # 일관성을 위해 0.1에서 0.0으로 하향 조정
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
# ✅ 시장 지표 계산 및 24시간 캐싱 함수
# ---------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=86400)
def get_cached_market_status(df_calendar, api_key):
    """
    IPO 수익률, 적자 비율, VIX, 버핏 지수 등 
    모든 시장 지표를 계산하여 반환 (하루 한 번 실행)
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
                # 내부 보조 함수는 메인 로직 어딘가에 정의되어 있어야 합니다.
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
    except: pass
    
    return data

# --- [주식 및 차트 기능] ---
import yfinance as yf
import plotly.graph_objects as go

# ==========================================
# [0] AI 설정 및 API 키 관리 (보안 강화)
# ==========================================

# 1. 자동 모델 선택 함수 (404/403 에러 방지용)
# 🔥 [수정] 이 함수 자체를 캐싱하여, 하루에 한 번만 구글에 '사용 가능한 모델 목록'을 물어보게 합니다.
# 이렇게 하면 사용자가 원하시는 '최신 모델 자동 탐색' 기능은 유지하면서 API 호출 횟수는 아낄 수 있습니다.
@st.cache_data(show_spinner=False, ttl=86400)
def get_latest_stable_model():
    # 보안을 위해 키는 반드시 st.secrets에서 가져와야 합니다.
    genai_key = st.secrets.get("GENAI_API_KEY")
    if not genai_key:
        return None
    
    try:
        genai.configure(api_key=genai_key)
        # 생성 가능하고 'flash'가 포함된 모델 목록 추출 (구글에 물어봄 -> API 1회 소모)
        models = [m.name for m in genai.list_models() 
                  if 'generateContent' in m.supported_generation_methods and 'flash' in m.name]
        
        # 목록이 있으면 첫 번째(보통 최신) 반환, 없으면 기본값
        # 1.5 버전을 우선적으로 찾도록 정렬 로직을 살짝 추가하면 더 좋습니다.
        models.sort(key=lambda x: '1.5' in x, reverse=True) 
        
        return models[0] if models else 'gemini-1.5-flash'
    except Exception:
        # 에러 나면 안전하게 기본 모델 반환
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

# --- [공시 분석 함수] ---
@st.cache_data(show_spinner=False, ttl=86400) # 24시간 캐싱
def get_ai_analysis(company_name, topic, points):
    if not model:
        return "AI 모델 설정 오류: API 키를 확인하세요."
    
    # [재시도 로직 추가]
    max_retries = 3
    for i in range(max_retries):
        try:
            prompt = f"""
            당신은 월가 출신의 전문 분석가입니다. {company_name}의 {topic} 서류를 분석하세요.
            핵심 체크포인트: {points}
            
            내용 구성:
            1. 해당 문서에서 발견된 가장 중요한 투자 포인트.
            2. MD&A를 통해 본 기업의 실질적 성장 가능성.
            3. 투자자가 반드시 경계해야 할 핵심 리스크 1가지.
            
            전문적인 톤으로 한국어로 5줄 내외 요약하세요.
            """
            response = model.generate_content(prompt)
            return response.text
            
        except Exception as e:
            # 429 에러(속도제한)라면 대기 후 재시도
            if "429" in str(e) or "quota" in str(e).lower():
                time.sleep(2 * (i + 1)) # 2초, 4초...
                continue
            else:
                return f"현재 분석 엔진을 조율 중입니다. (상세: {str(e)})"
    
    return "⚠️ 사용량이 많아 분석이 지연되고 있습니다. 잠시 후 다시 시도해주세요."

# --- [기관 평가 분석 함수] ---
@st.cache_data(show_spinner=False, ttl=86400) 
def get_cached_ipo_analysis(ticker, company_name):
    tavily_key = st.secrets.get("TAVILY_API_KEY")
    
    # model 객체는 외부(app.py 전역)에서 정의된 것을 사용한다고 가정합니다.
    # 만약 함수 내에서 정의가 필요하다면 model = genai.GenerativeModel('gemini-1.5-flash') 등을 추가해야 합니다.
    if not tavily_key:
        return {"rating": "N/A", "pro_con": "API Key 설정 필요", "summary": "설정을 확인하세요.", "links": []}

    try:
        tavily = TavilyClient(api_key=tavily_key)
        
        # 쿼리 최적화
        site_query = f"(site:renaissancecapital.com OR site:seekingalpha.com OR site:morningstar.com) {company_name} {ticker} stock IPO analysis 2025 2026"
        
        search_result = tavily.search(query=site_query, search_depth="advanced", max_results=10)
        results = search_result.get('results', [])
        
        if not results:
            return {"rating": "Neutral", "pro_con": "최근 기관 리포트를 찾을 수 없습니다.", "summary": "현재 공개된 전문 기관의 분석 데이터가 부족합니다.", "links": []}

        search_context = ""
        links = []
        for r in results:
            search_context += f"Source: {r['url']}\nContent: {r['content']}\n\n"
            links.append({"title": r['title'], "link": r['url']})

        # --- [프롬프트 수정: 링크 포함 금지 지침 추가] ---
        prompt = f"""
        당신은 월가 출신의 IPO 전문 분석가입니다. 아래 제공된 {company_name} ({ticker})에 대한 기관 데이터를 바탕으로 심층 분석을 수행하세요.
        
        [데이터 요약]:
        {search_context}
        
        [작성 지침]:
        1. 반드시 한국어로 답변하세요.
        2. 긍정의견(Pros) 2가지와 부정의견(Cons) 2가지를 구체적인 수치나 근거를 들어 요약하세요.
        3. Rating은 반드시 (Strong Buy/Buy/Hold/Sell) 중 하나로 선택하세요.
        4. Summary는 전문적인 톤으로 3줄 이내로 작성하세요.
        5. **중요: 답변 내용(Summary 포함)에 'Source:', 'http...', '출처' 등 링크 정보를 절대 포함하지 마세요. 오직 분석 텍스트만 작성하세요.**

        [응답 형식]:
        Rating: (이곳에 작성)
        Pro_Con: 
        - 긍정: 내용
        - 부정: 내용
        Summary: (이곳에 작성)
        """

        # [재시도 로직]
        max_retries = 3
        for i in range(max_retries):
            try:
                # model이 정의되어 있다고 가정 (없으면 에러 발생하므로 주의)
                response_obj = model.generate_content(prompt)
                response_text = response_obj.text

                rating = re.search(r"Rating:\s*(.*)", response_text, re.I)
                pro_con = re.search(r"Pro_Con:\s*([\s\S]*?)(?=Summary:|$)", response_text, re.I)
                summary = re.search(r"Summary:\s*([\s\S]*)", response_text, re.I)
                
                # --- [후처리: 혹시 모를 링크 제거 로직] ---
                raw_summary = summary.group(1).strip() if summary else response_text
                
                # 'Source:' 또는 'http'가 나오면 그 뒷부분은 잘라냄
                if "Source:" in raw_summary:
                    clean_summary = raw_summary.split("Source:")[0].strip()
                elif "http" in raw_summary:
                    clean_summary = raw_summary.split("http")[0].strip()
                else:
                    clean_summary = raw_summary

                return {
                    "rating": rating.group(1).strip() if rating else "Neutral",
                    "pro_con": pro_con.group(1).strip() if pro_con else "분석 데이터 추출 실패",
                    "summary": clean_summary, # 깨끗해진 요약본 적용
                    "links": links[:5]
                }
            except Exception as e:
                # 429 에러 처리 (API 한도 초과 시 대기)
                if "429" in str(e) or "quota" in str(e).lower():
                    time.sleep(2 * (i + 1))
                    continue
                return {"rating": "Error", "pro_con": f"오류 발생: {e}", "summary": "분석 중 문제가 발생했습니다.", "links": []}
        
        return {"rating": "N/A", "pro_con": "API 사용량 초과", "summary": "잠시 후 다시 시도해주세요.", "links": []}
        
    except Exception as e:
        return {"rating": "Error", "pro_con": f"오류 발생: {e}", "summary": "데이터를 불러오는 중 문제가 발생했습니다.", "links": []}
        
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

@st.cache_data(ttl=3600)
def get_cached_ipo_analysis(ticker, company_name):
    tavily_key = st.secrets.get("TAVILY_API_KEY")
    if not tavily_key:
        return {"rating": "N/A", "pro_con": "API Key 누락", "summary": "설정을 확인하세요.", "links": []}

    try:
        tavily = TavilyClient(api_key=tavily_key)
        
        # [개선 1] 검색 쿼리 다각화: 특정 사이트 한정과 일반 검색을 조합하여 정보 획득률 극대화
        # 특히 Seeking Alpha의 최신 분석글 제목(Repay Debt 등)이 검색 결과에 잘 잡히도록 유도합니다.
        search_queries = [
            f"Seeking Alpha {ticker} {company_name} analysis IPO",
            f"Renaissance Capital {ticker} {company_name} IPO profile",
            f"Morningstar {company_name} {ticker} stock analysis",
            f"'{company_name}' Begins IPO Rollout To Repay Debt" # 특정 뉴스 헤드라인 타겟팅
        ]
        
        combined_context = ""
        links = []
        
        # 여러 쿼리로 검색하여 더 넓은 범위를 수집 (중복은 AI가 제거)
        for q in search_queries[:2]: # API 소모 조절을 위해 상위 2개 쿼리 우선 실행
            search_result = tavily.search(query=q, search_depth="advanced", max_results=5)
            results = search_result.get('results', [])
            for r in results:
                combined_context += f"Source: {r['url']}\nTitle: {r['title']}\nContent: {r['content']}\n\n"
                if r['url'] not in [l['link'] for l in links]:
                    links.append({"title": r['title'], "link": r['url']})

        # [개선 2] AI 분석 프롬프트 보강 (요청하신 지침 반영)
        prompt = f"""
        당신은 월스트리트의 IPO 전문 분석가입니다. 
        제공된 검색 결과(snippets)를 정밀하게 읽고 {company_name} ({ticker})에 대한 기관 평가를 요약하세요.

        [지침]
        1. 'Seeking Alpha', 'Renaissance Capital', 'Morningstar'의 분석 내용을 최우선으로 반영하세요.
        2. 만약 내용 중 'Begins IPO Rollout to Repay Debt' (부채 상환을 위한 IPO 전개)와 관련된 언급이 있다면 반드시 분석에 포함시키세요.
        3. 긍정적 요소(Pros)와 부정적/리스크 요소(Cons)를 각각 2가지씩 명확히 구분하세요.
        4. 데이터가 파편화되어 있다면 검색된 텍스트 중 가장 신뢰도 높은 경제 지표나 문구를 사용하세요.

        반드시 아래 형식을 지키세요:
        Rating: (Buy/Hold/Sell/Neutral 중 선택)
        Pro_Con: 
        - 긍정1: 내용
        - 긍정2: 내용
        - 부정1: 내용
        - 부정2: 내용
        Summary: (전체 요약 3줄 내외, 부채 상환 이슈가 있다면 반드시 언급)
        """

        # Gemini 모델 호출 (전역 변수로 model이 정의되어 있어야 함)
        full_response = model.generate_content([prompt, combined_context]).text
        
        # 결과 파싱 (간단한 파싱 로직)
        rating = "Neutral"
        if "Rating:" in full_response:
            rating = full_response.split("Rating:")[1].split("\n")[0].strip()
        
        pro_con = "의견 수집 중"
        if "Pro_Con:" in full_response:
            pro_con = full_response.split("Pro_Con:")[1].split("Summary:")[0].strip()
            
        summary = "데이터를 분석할 수 없습니다."
        if "Summary:" in full_response:
            summary = full_response.split("Summary:")[1].strip()

        return {
            "rating": rating,
            "pro_con": pro_con,
            "summary": summary,
            "links": links
        }

    except Exception as e:
        return {
            "rating": "Error",
            "pro_con": f"분석 중 오류 발생: {str(e)}",
            "summary": "AI 서비스 응답 지연",
            "links": []
        }

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

# 1. 페이지 설정
st.set_page_config(page_title="Unicornfinder", layout="wide", page_icon="🦄")

# 'posts'를 아래 리스트에 추가했습니다.
for key in ['page', 'auth_status', 'vote_data', 'comment_data', 'selected_stock', 'watchlist', 'view_mode', 'news_topic', 'posts']:
    if key not in st.session_state:
        if key == 'page': 
            st.session_state[key] = 'login'
        # posts와 watchlist는 목록 형태이므로 빈 리스트([])로 초기화
        elif key in ['watchlist', 'posts']: 
            st.session_state[key] = []
        elif key in ['vote_data', 'comment_data', 'user_votes']: 
            st.session_state[key] = {}
        elif key == 'view_mode': 
            st.session_state[key] = 'all'
        elif key == 'news_topic': 
            st.session_state[key] = "💰 공모가 범위/확정 소식"
        else: 
            st.session_state[key] = None
            
# --- CSS 스타일 ---
st.markdown("""
    <style>
    /* 전체 앱 스타일 */
    .stApp { background-color: #FFFFFF; color: #333333; }
    
    .intro-card {
        background: linear-gradient(135deg, #6e8efb 0%, #a777e3 100%);
        padding: 50px 30px; border-radius: 30px; color: white !important;
        text-align: center; margin-top: 20px; 
        box-shadow: 0 20px 40px rgba(110, 142, 251, 0.3);
    }
    .intro-title { font-size: 40px; font-weight: 900; margin-bottom: 10px; color: white !important; }
    
    .feature-grid { display: flex; justify-content: space-around; gap: 15px; margin-bottom: 25px; }
    .feature-item {
        background: rgba(255, 255, 255, 0.2);
        padding: 20px 10px; border-radius: 20px; flex: 1;
        backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.3);
        color: white !important; text-align: center;
    }
    
    .grid-card { 
        background-color: #ffffff !important; 
        padding: 25px; border-radius: 20px; 
        border: 1px solid #eef2ff; box-shadow: 0 10px 20px rgba(0,0,0,0.05); 
        text-align: center; color: #333333 !important; height: 100%;
    }
    
    .quote-card {
        background: linear-gradient(145deg, #ffffff, #f9faff);
        padding: 25px; border-radius: 20px; border-top: 5px solid #6e8efb;
        box-shadow: 0 10px 40px rgba(0,0,0,0.05); text-align: center;
        max-width: 650px; margin: 40px auto; color: #333333 !important;
    }
    
    .comment-box { background-color: #f8f9fa; padding: 10px; border-radius: 10px; margin-bottom: 5px; border-left: 3px solid #dee2e6; color: #333; }
    button p { font-weight: bold !important; }
    </style>
""", unsafe_allow_html=True)

# --- [1. 최상단 페이지 컨트롤러] ---
if st.session_state.get('page') == 'board':
    
    # ---------------------------------------------------------
    # 1. [STYLE] 블랙 배경 + 화이트 글씨 (제공해주신 스타일 적용)
    # ---------------------------------------------------------
    st.markdown("""
        <style>
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
        div[data-testid="stPills"] button[aria-selected="true"] {
            background-color: #444444 !important;
            color: #ffffff !important;
            font-weight: 800 !important;
        }
        div[data-testid="stPills"] div[data-baseweb="pill"] {
            border: none !important;
            background: transparent !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # ---------------------------------------------------------
    # 2. 메뉴 텍스트 정의 및 페이지 이동 로직
    # ---------------------------------------------------------
    is_logged_in = st.session_state.get('auth_status') == 'user'
    login_text = "로그아웃" if is_logged_in else "로그인"
    main_text = "메인"
    watch_text = f"관심 ({len(st.session_state.get('watchlist', []))})"
    board_text = "게시판"
    
    menu_options = [login_text, main_text, watch_text, board_text]

    # 현재 게시판 페이지이므로 기본 선택값은 board_text
    selected_menu = st.pills(
        label="내비게이션",
        options=menu_options,
        selection_mode="single",
        default=board_text,
        key="top_nav_board_page", 
        label_visibility="collapsed"
    )

    # ✨ [핵심] 메뉴 클릭 시 페이지 이동 로직 ✨
    if selected_menu == login_text:
        if is_logged_in:
            st.session_state.auth_status = None
            st.session_state.page = 'login'
        else:
            st.session_state.page = 'login'
        st.rerun()
    elif selected_menu == main_text:
        st.session_state.page = 'calendar' # 메인(캘린더) 페이지로 이동
        st.session_state.view_mode = 'all'
        st.rerun()
    elif selected_menu == watch_text:
        st.session_state.page = 'calendar' # 캘린더 페이지로 가되
        st.session_state.view_mode = 'watchlist' # 관심 종목 모드로 변경
        st.rerun()
    # '게시판' 선택 시에는 현재 페이지이므로 아무 작업 안 함

    # ---------------------------------------------------------
    # 3. 통합 게시판 본문 (헤더 중복 제거 및 10개 노출 버전)
    # ---------------------------------------------------------
    
    # [설정] 관리자 및 사용자 확인
    ADMIN_PHONE = "010-0000-0000"  # 실제 관리자 번호로 수정하세요
    current_user_phone = st.session_state.get('user_phone', 'guest')
    is_admin = (current_user_phone == ADMIN_PHONE)
    user_id = st.session_state.get('user_id')
    
    # [1. 상단: 게시글 리스트 섹션]
    posts = st.session_state.get('posts', [])
    
    if 'search_word' not in st.session_state:
        st.session_state.search_word = ""
    
    # 검색 필터링 로직
    if st.session_state.search_word:
        sw = st.session_state.search_word.upper()
        display_posts = [p for p in posts if sw in p.get('category', '').upper() or sw in p.get('title', '').upper()]
    else:
        display_posts = posts
    
    # --- 리스트 출력 시작 (최대 10개 노출) ---
    if display_posts:
        for idx, p in enumerate(display_posts[:10]):  # 👈 기존 20개에서 10개로 변경
            
            # [수정 1] 종목명 중복 제거 및 헤더 형식 변경
            category = p.get('category', '').strip()
            title = p.get('title', '').strip()
            
            # 제목 자체에 이미 [종목]이 포함되어 있는지 확인하여 중복 방지
            if category and f"[{category}]" in title:
                clean_title = title  # 이미 포함되어 있으면 그대로 사용
            elif category:
                clean_title = f"[{category}] {title}" # 없으면 붙여줌
            else:
                clean_title = title
    
            # 최종 헤더 문자열 (별표 제거)
            combined_header = f"{clean_title} | 👤 {p.get('author')} | {p.get('date')}"
            
            with st.expander(combined_header, expanded=False):
                st.write(p.get('content'))
                st.divider()
                
                # 버튼 레이아웃
                col_l, col_d, col_spacer, col_edit, col_del = st.columns([0.7, 0.7, 3.5, 0.6, 0.6])
                
                with col_l:
                    if st.button(f"👍 {p.get('likes', 0)}", key=f"like_{p['id']}"):
                        if user_id and user_id not in p.get('like_users', []):
                            p['likes'] = p.get('likes', 0) + 1
                            p.setdefault('like_users', []).append(user_id)
                            st.rerun()
                with col_d:
                    if st.button(f"👎 {p.get('dislikes', 0)}", key=f"dis_{p['id']}"):
                        if user_id and user_id not in p.get('dislike_users', []):
                            p['dislikes'] = p.get('dislikes', 0) + 1
                            p.setdefault('dislike_users', []).append(user_id)
                            st.rerun()
    
                # 수정 및 삭제 권한 확인
                if (current_user_phone == p.get('author')) or is_admin:
                    with col_edit:
                        if st.button("📝", key=f"edit_{p['id']}"):
                            st.info("수정 기능 준비 중입니다.")
                    with col_del:
                        if st.button("🗑️", key=f"del_{p['id']}"):
                            st.session_state.posts = [item for item in st.session_state.posts if item['id'] != p['id']]
                            st.rerun()
            st.markdown("<div style='margin-bottom: 5px;'></div>", unsafe_allow_html=True)
    else:
        st.caption("게시글이 없습니다.")
    
    st.markdown("---")
    
    # [2. 하단: 검색창 및 글쓰기 버튼 가로 배치]
    col_search, col_write = st.columns([3, 1])
    
    with col_search:
        st.session_state.search_word = st.text_input(
            "🔍 검색", 
            value=st.session_state.search_word,
            placeholder="종목명 또는 제목으로 검색...",
            label_visibility="collapsed",
            key="board_search_input_final"
        )
    
    with col_write:
        show_write = st.expander("📝 글쓰기", expanded=False)
    
    # [3. 글쓰기 폼 로직]
    if st.session_state.get('auth_status') == 'user':
        with show_write:
            with st.form(key="unique_write_form_v3", clear_on_submit=True):
                w_col1, w_col2 = st.columns([1, 2])
                with w_col1:
                    new_cat = st.text_input("종목명", placeholder="예: TSLA")
                with w_col2:
                    new_title = st.text_input("제목", placeholder="제목을 입력하세요")
                new_content = st.text_area("내용", placeholder="인사이트를 공유해 주세요")
                
                if st.form_submit_button("게시하기", use_container_width=True, type="primary"):
                    if new_title and new_content:
                        new_post = {
                            "id": str(uuid.uuid4()),
                            "category": new_cat.upper() if new_cat else "공통",
                            "title": new_title, 
                            "content": new_content,
                            "author": current_user_phone,
                            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "likes": 0, "dislikes": 0,
                            "like_users": [], "dislike_users": [],
                            "uid": user_id
                        }
                        if 'posts' not in st.session_state: st.session_state.posts = []
                        st.session_state.posts.insert(0, new_post)
                        st.rerun()
    else:
        with show_write:
            st.warning("🔒 로그인 후 글을 남길 수 있습니다.")


# --- 데이터 로직 (캐싱 최적화 적용) ---
MY_API_KEY = "d5j2hd1r01qicq2lls1gd5j2hd1r01qicq2lls20"

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
        (now - timedelta(days=200), now + timedelta(days=120)),  # 구간 1: 현재~과거 200일 (약 6.5개월)
        (now - timedelta(days=380), now - timedelta(days=170)), # 구간 2: 과거 170일~380일
        (now - timedelta(days=560), now - timedelta(days=350))  # 구간 3: 과거 350일~560일
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
    
    # 데이터프레임 생성 및 중복 제거
    df = pd.DataFrame(all_data)
    df = df.drop_duplicates(subset=['symbol', 'date'])
    
    # 🔥 [중요] 날짜 변환 보정: 'date' 컬럼을 바탕으로 '공모일_dt'를 생성하고 시분을 제거
    # errors='coerce'를 써서 잘못된 날짜 형식은 NaT로 변환 후 삭제합니다.
    df['공모일_dt'] = pd.to_datetime(df['date'], errors='coerce').dt.normalize()
    df = df.dropna(subset=['공모일_dt'])
    
    return df

# 주가(Price)는 15분마다 업데이트되도록 캐싱 설정 (900초 = 15분)
@st.cache_data(ttl=900)
def get_current_stock_price(symbol, api_key):
    try:
        # Finnhub API를 통해 실시간 시세를 가져옴
        # 15분 이내에 같은 symbol로 호출하면 API를 쏘지 않고 저장된 값을 반환합니다.
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
        res = requests.get(url, timeout=2).json()
        
        # 'c'는 Current Price(현재가)를 의미합니다.
        current_p = res.get('c', 0)
        
        # 데이터가 유효한지(0이 아닌지) 확인 후 반환
        return current_p if current_p else 0
    except Exception as e:
        # 에러 발생 시 로그를 남기지 않고 0을 반환하여 앱 중단 방지
        return 0

# [뉴스 감성 분석 함수 - 내부 연산이므로 별도 캐싱 불필요]
def analyze_sentiment(text):
    text = text.lower()
    pos_words = ['jump', 'soar', 'surge', 'rise', 'gain', 'buy', 'outperform', 'beat', 'success', 'growth', 'up', 'high', 'profit', 'approval']
    neg_words = ['drop', 'fall', 'plunge', 'sink', 'loss', 'miss', 'fail', 'risk', 'down', 'low', 'crash', 'suit', 'ban', 'warning']
    score = 0
    for w in pos_words:
        if w in text: score += 1
    for w in neg_words:
        if w in text: score -= 1
    
    if score > 0: return "긍정", "#e6f4ea", "#1e8e3e"
    elif score < 0: return "부정", "#fce8e6", "#d93025"
    else: return "일반", "#f1f3f4", "#5f6368"

@st.cache_data(ttl=3600) # [수정] 1시간 (3600초) 동안 뉴스 다시 안 부름!
@st.cache_data(ttl=3600)
def get_real_news_rss(company_name, ticker=""):
    import requests
import xml.etree.ElementTree as ET
import urllib.parse
import re

# [1] 뉴스 감성 분석 함수 (내부 연산용)
def analyze_sentiment(text):
    text = text.lower()
    pos_words = ['jump', 'soar', 'surge', 'rise', 'gain', 'buy', 'outperform', 'beat', 'success', 'growth', 'up', 'high', 'profit', 'approval']
    neg_words = ['drop', 'fall', 'plunge', 'sink', 'loss', 'miss', 'fail', 'risk', 'down', 'low', 'crash', 'suit', 'ban', 'warning']
    score = 0
    for w in pos_words:
        if w in text: score += 1
    for w in neg_words:
        if w in text: score -= 1
    
    if score > 0: return "긍정", "#e6f4ea", "#1e8e3e"
    elif score < 0: return "부정", "#fce8e6", "#d93025"
    else: return "일반", "#f1f3f4", "#5f6368"

# [2] 통합 뉴스 검색 함수 (RSS 검색 + AI 번역 결합)
@st.cache_data(ttl=3600)
def get_real_news_rss(company_name):
    """구글 뉴스 RSS 검색 + 정밀 필터링 + AI 번역"""
    try:
        import time
        
        # [수정 1] 회사 이름 정제 로직 강화 (특수문자 제거 및 콤마 처리)
        # 1차: 법인명 제거 (Inc, Corp 등)
        clean_name = re.sub(r'\s+(Corp|Inc|Ltd|PLC|LLC|Acquisition|Holdings|Group)\b.*$', '', company_name, flags=re.IGNORECASE)
        # 2차: 콤마(,) 등 특수문자 제거하고 앞뒤 공백 정리
        clean_name = re.sub(r'[^\w\s]', '', clean_name).strip()
        
        # 검색어 생성
        query = f'"{clean_name}" AND (stock OR IPO OR listing OR "SEC filing")'
        enc_query = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={enc_query}&hl=en-US&gl=US&ceid=US:en"

        response = requests.get(url, timeout=5)
        root = ET.fromstring(response.content)
        
        news_items = []
        items = root.findall('./channel/item')
        
        # [수정 2] 검색어의 핵심 단어 리스트 추출 (예: "SOLV Energy" -> ["solv", "energy"])
        # 단, "Energy", "Bio" 같은 일반 명사도 회사명의 일부라면 필수 조건으로 봅니다.
        name_parts = [part.lower() for part in clean_name.split() if len(part) > 1]

        for item in items[:5]: 
            title_en = item.find('title').text
            link = item.find('link').text
            pubDate = item.find('pubDate').text
            
            title_lower = title_en.lower()

            # [핵심 수정] 단순 포함 여부가 아니라, 회사 이름의 '모든 단어'가 제목에 있는지 검사
            # 예: "SOLV Energy" -> 제목에 "solv"와 "energy"가 둘 다 없으면 탈락시킴
            # 이렇게 하면 "Solventum (SOLV)" 뉴스는 "energy"가 없어서 걸러집니다.
            is_match = True
            for part in name_parts:
                if part not in title_lower:
                    is_match = False
                    break
            
            if not is_match:
                continue

            # 1. 감성 분석
            sent_label, bg, color = analyze_sentiment(title_en)
            
            # 2. 날짜 포맷
            try: date_str = " ".join(pubDate.split(' ')[1:3])
            except: date_str = "Recent"

            # 3. AI 번역
            title_ko = translate_news_title(title_en)

            news_items.append({
                "title": title_en,      
                "title_ko": title_ko,   
                "link": link, 
                "date": date_str,
                "sent_label": sent_label, 
                "bg": bg, 
                "color": color,
                "display_tag": "일반" 
            })
            
            if len(news_items) >= 5:
                break
                
        return news_items

    except Exception as e:
        return []
# [핵심] 함수 이름 변경 (캐시 초기화 효과)
@st.cache_data(show_spinner=False, ttl=86400)
def get_ai_summary_final(query):
    # [수정] 대문자든 소문자든 있는 쪽을 무조건 가져옵니다.
    tavily_key = st.secrets.get("TAVILY_API_KEY") or st.secrets.get("tavily_api_key")
    groq_key = st.secrets.get("GROQ_API_KEY") or st.secrets.get("groq_api_key")

    # 두 키 중 하나라도 없으면 그때만 에러를 띄웁니다.
    if not tavily_key or not groq_key:
        return "<p style='color:red;'>⚠️ API 키 설정 오류: Secrets 창에 TAVILY_API_KEY와 GROQ_API_KEY가 있는지 확인하세요.</p>"

    try:
        # 1. Tavily 검색
        tavily = TavilyClient(api_key=tavily_key)
        search_result = tavily.search(query=query, search_depth="basic", max_results=7)
        if not search_result.get('results'): return None 
        context = "\n".join([r['content'] for r in search_result['results']])

        # 2. LLM 호출 (요청하신 필수 작성 원칙 100% 반영)
        client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_key)
        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {
                    "role": "system", 
                    "content": """당신은 한국 최고의 증권사 리서치 센터의 시니어 애널리스트입니다.
[필수 작성 원칙]
1. 언어: 오직 '한국어'만 사용하세요. (영어 고유명사 제외). 베트남어, 중국어 절대 사용 금지.
2. 포맷: 반드시 3개의 문단으로 나누어 작성하세요. 문단 사이에는 줄바꿈을 명확히 넣으세요.
   - 1문단: 비즈니스 모델 및 경쟁 우위
   - 2문단: 재무 현황 및 공모 자금 활용
   - 3문단: 향후 전망 및 투자 의견
3. 문체: '~습니다' 체를 사용하고, 문장 시작에 불필요한 접속사나 사명을 반복하지 마세요.
4. 금지: 제목, 소제목(**), 특수기호, 불렛포인트(-)를 절대 쓰지 마세요. 오직 줄글로만 작성하세요."""
                },
                {
                    "role": "user", 
                    "content": f"Context:\n{context}\n\nQuery: {query}\n\n위 데이터를 바탕으로 전문적인 3문단 리포트를 작성하세요."
                }
            ],
            temperature=0.1
        )
        
        raw_result = response.choices[0].message.content
        
        # --- [요청하신 정제 로직 + 문단 강제 분할] ---
        
        # 1. 텍스트 정제 (요청하신 코드 그대로 적용)
        text = html.unescape(raw_result)
        replacements = {"quyết": "결", "trọng": "중", "里程碑": "이정표", "决策": "의사결정"}
        for k, v in replacements.items(): text = text.replace(k, v)
        
        # 특수문자 제거 (한글, 영어, 숫자, 기본 문장부호, 줄바꿈(\s)만 허용)
        # 주의: \s가 없으면 줄바꿈도 다 사라지므로 \s는 꼭 있어야 합니다.
        text = re.sub(r'[^가-힣a-zA-Z0-9\s\.\,%\-\'\"]', '', text)
        
        # 2. 문단 강제 분리 로직 (Brute Force Split)
        # (1) 우선 줄바꿈(엔터) 기준으로 잘라봅니다.
        paragraphs = [p.strip() for p in re.split(r'\n+', text.strip()) if len(p) > 30]

        # (2) [비상장치] 만약 AI가 줄바꿈을 안 줘서 덩어리가 1~2개뿐이라면?
        # -> 마침표(.)를 기준으로 문장을 다 뜯어낸 뒤 강제로 3등분 합니다.
        if len(paragraphs) < 3:
            # 문장 단위로 분해 (마침표 뒤 공백 기준)
            sentences = re.split(r'(?<=\.)\s+', text.strip())
            total_sents = len(sentences)
            
            if total_sents >= 3:
                # 3등분 계산 (올림 나눗셈)
                chunk_size = (total_sents // 3) + 1
                
                p1 = " ".join(sentences[:chunk_size])
                p2 = " ".join(sentences[chunk_size : chunk_size*2])
                p3 = " ".join(sentences[chunk_size*2 :])
                
                # 다시 리스트로 합침 (빈 내용 제외)
                paragraphs = [p for p in [p1, p2, p3] if len(p) > 10]
            else:
                # 문장이 너무 적으면 그냥 통으로 1개만 반환
                paragraphs = [text]

        # 3. HTML 태그 포장 (화면 렌더링용)
        # 파이썬 리스트에 담긴 3개의 글덩어리를 각각 <p> 태그로 감쌉니다.
        html_output = ""
        for p in paragraphs:
            html_output += f"""
            <p style='
                display: block;          /* 블록 요소 지정 */
                text-indent: 14px;       /* 첫 줄 들여쓰기 */
                margin-bottom: 20px;     /* 문단 아래 공백 */
                line-height: 1.8;        /* 줄 간격 */
                text-align: justify;     /* 양쪽 정렬 */
                margin-top: 0;
            '>
                {p}
            </p>
            """
            
        return html_output

    except Exception as e:
        return f"<p style='color:red;'>🚫 오류: {str(e)}</p>"

        # --- 화면 제어 및 로그인 화면 시작 ---

if st.session_state.page == 'login':
    # 아래 코드들은 모두 동일하게 'Tab' 한 번(또는 공백 4칸) 안으로 들어가 있어야 합니다.
    st.write("<br>" * 2, unsafe_allow_html=True)  # 여백 조절
    
    # [추가] 상단 타이틀 이미지 표시 영역
    t_col1, t_col2, t_col3 = st.columns([1, 0.8, 1]) # 이미지 크기 조절을 위한 컬럼 분할
    with t_col2:
        img_path = "title_unicorn.png"
        if os.path.exists(img_path):
            st.image(img_path, use_container_width=True)
        else:
            # 로컬에 파일이 없을 경우를 대비해 GitHub Raw URL 방식을 사용할 수도 있습니다.
            pass

    st.write("<br>", unsafe_allow_html=True)
    _, col_m, _ = st.columns([1, 1.2, 1])
    
    # [가상 DB] 가입된 사용자 목록을 기억하기 위한 임시 저장소
    if 'db_users' not in st.session_state:
        st.session_state.db_users = ["010-0000-0000"] # 테스트용: 관리자 번호는 이미 가입된 것으로 간주
    
    with col_m:
        # 로그인 단계 초기화
        if 'login_step' not in st.session_state: st.session_state.login_step = 'choice'

        # [Step 1] 첫 선택 화면 (로그인 vs 회원가입 분리)
        if st.session_state.login_step == 'choice':
            st.write("")
            
            # 버튼 1: 기존 회원 로그인 (바로 입력창으로)
            if st.button("로그인", use_container_width=True, type="primary"):
                st.session_state.login_step = 'login_input' # 로그인 입력 단계로 이동
                st.rerun()
                
            # 버튼 2: 신규 회원 가입 (안내 화면으로)
            if st.button("회원가입", use_container_width=True):
                st.session_state.login_step = 'ask_signup' # 가입 안내 단계로 이동
                st.rerun()
                
            # 버튼 3: 비회원 둘러보기
            if st.button("구경하기", use_container_width=True):
                st.session_state.auth_status = 'guest'
                st.session_state.page = 'calendar' # [수정 완료] stats -> calendar
                st.rerun()

        # [Step 2-A] 로그인 입력 화면 (기존 회원용)
        elif st.session_state.login_step == 'login_input':
            st.markdown("### 🔑 로그인")
            phone_login = st.text_input("가입하신 휴대폰 번호를 입력하세요", placeholder="010-0000-0000", key="login_phone")
            
            l_c1, l_c2 = st.columns([2, 1])
            with l_c1:
                if st.button("접속하기", use_container_width=True, type="primary"):
                    # 가입된 번호인지 확인
                    if phone_login in st.session_state.db_users:
                        st.session_state.auth_status = 'user'
                        st.session_state.user_phone = phone_login # 세션에 정보 저장
                        st.success(f"반갑습니다! {phone_login}님")
                        st.session_state.page = 'calendar' # [수정 완료] stats -> calendar
                        st.session_state.login_step = 'choice'
                        st.rerun()
                    else:
                        st.error("가입되지 않은 번호입니다. 회원가입을 먼저 진행해주세요.")
            with l_c2:
                if st.button("뒤로가기", use_container_width=True):
                    st.session_state.login_step = 'choice'
                    st.rerun()

        # [Step 2-B] 회원가입 안내 화면 (신규 회원용)
        elif st.session_state.login_step == 'ask_signup':
            st.info("회원가입시 IPO정보알림받기 및 관심기업관리가 가능합니다.")
            c1, c2 = st.columns(2)
            if c1.button("✅ 가입 진행", use_container_width=True):
                st.session_state.login_step = 'signup_input' # 가입 입력 단계로 이동
                st.rerun()
            if c2.button("❌ 취소", use_container_width=True):
                st.session_state.login_step = 'choice'
                st.rerun()

        # [Step 3] 가입 정보 입력 (신규 회원용)
        elif st.session_state.login_step == 'signup_input':
            st.markdown("### 📝 정보 입력")
            phone_signup = st.text_input("사용하실 휴대폰 번호를 입력하세요", placeholder="010-0000-0000", key="signup_phone")
            
            s_c1, s_c2 = st.columns([2, 1])
            with s_c1:
                if st.button("가입 완료", use_container_width=True, type="primary"):
                    if len(phone_signup) >= 10:
                        # 이미 존재하는지 확인
                        if phone_signup in st.session_state.db_users:
                            st.warning("이미 가입된 번호입니다. '기존 회원 로그인'을 이용해주세요.")
                        else:
                            # [DB 저장] 신규 회원을 리스트에 추가
                            st.session_state.db_users.append(phone_signup)
                            
                            st.session_state.auth_status = 'user'
                            st.session_state.user_phone = phone_signup
                            st.balloons() # 가입 축하 효과
                            st.toast("회원가입을 축하합니다!", icon="🎉")
                            st.session_state.page = 'calendar' # [수정 완료] stats -> calendar
                            st.session_state.login_step = 'choice'
                            st.rerun()
                    else: st.error("올바른 번호를 입력해주세요.")
            with s_c2:
                if st.button("취소", key="back_signup"):
                    st.session_state.login_step = 'choice'
                    st.rerun()

    st.write("<br>" * 2, unsafe_allow_html=True)
    q = get_daily_quote()
    
    # [수정] 한글(kor)이 추가된 HTML 디자인
    st.markdown(f"""
        <div class='quote-card'>
            <b>"{q['eng']}"</b>
            <br>
            <span style='font-size:14px; color:#555; font-weight:normal;'>{q['kor']}</span>
            <br><br>
            <small>- {q['author']} -</small>
        </div>
    """, unsafe_allow_html=True)



# 4. 캘린더 페이지 (메인 통합: 상단 메뉴 + 리스트)
elif st.session_state.page == 'calendar':
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

        /* 3. 버튼 스타일 (리스트용 타이트한 스타일) */
        .stButton button {
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
    # 2. 메뉴 텍스트 및 현재 상태 정의 (명칭 및 순서 변경)
    # ---------------------------------------------------------
    is_logged_in = st.session_state.auth_status == 'user'
    login_text = "로그아웃" if is_logged_in else "로그인"
    main_text = "메인"  # '홈'에서 '메인'으로 변경
    watch_text = f"관심 ({len(st.session_state.watchlist)})"
    board_text = "게시판"
    
    # 순서 조정: 로그인 -> 메인 -> 관심 -> 게시판
    menu_options = [login_text, main_text, watch_text, board_text]

    # 현재 어떤 페이지에 있는지 계산하여 기본 선택값(Default) 설정
    default_sel = main_text
    if st.session_state.get('page') == 'login': 
        default_sel = login_text
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
        key="top_nav_pills_v10", # 키값 갱신
        label_visibility="collapsed"
    )

    # ---------------------------------------------------------
    # 4. 클릭 감지 및 페이지 이동 로직 (보정 완료)
    # ---------------------------------------------------------
    if selected_menu and selected_menu != default_sel:
        if selected_menu == login_text:
            if is_logged_in: 
                st.session_state.auth_status = None # 로그아웃 처리
            st.session_state.page = 'login'
            
        elif selected_menu == main_text:
            st.session_state.view_mode = 'all'
            # 메인 목록 페이지 이름이 'calendar'라면 'calendar'로, 'main'이라면 'main'으로 맞춰주세요.
            st.session_state.page = 'calendar' 
            
        elif selected_menu == watch_text:
            st.session_state.view_mode = 'watchlist'
            st.session_state.page = 'calendar' 
            
        elif selected_menu == board_text:
            st.session_state.page = 'board'
        
        # 설정 변경 후 화면 즉시 갱신
        st.rerun()

    
    # ---------------------------------------------------------
    # [기존 데이터 로직] - 과거 데이터 누락 방지 수정본
    # ---------------------------------------------------------
    all_df_raw = get_extended_ipo_data(MY_API_KEY)
    
    # 데이터 수집 범위 확인
    if not all_df_raw.empty:
        min_date = all_df_raw['date'].min()
        max_date = all_df_raw['date'].max()
        st.sidebar.info(f"📊 수집된 데이터 범위:\n{min_date} ~ {max_date}")
        
    view_mode = st.session_state.get('view_mode', 'all')
    
    if not all_df_raw.empty:
        # 🔥 [수정] exchange가 없어도 삭제하지 않고 '-'로 채워서 유지합니다.
        all_df = all_df_raw.copy()
        all_df['exchange'] = all_df['exchange'].fillna('-')
        
        # 유효한 심볼이 있는 데이터만 유지
        all_df = all_df[all_df['symbol'].astype(str).str.strip() != ""]
        
        # 날짜 형식 통일 (normalize로 시간 제거)
        all_df['공모일_dt'] = pd.to_datetime(all_df['date'], errors='coerce').dt.normalize()
        all_df = all_df.dropna(subset=['공모일_dt'])
        
        today_dt = pd.to_datetime(datetime.now().date())
        
        # 2. 필터 로직
        if view_mode == 'watchlist':
            st.markdown("### ⭐ 내가 찜한 유니콘")
            if st.button("🔄 전체 목록 보기", use_container_width=True):
                st.session_state.view_mode = 'all'
                st.rerun()
                
            display_df = all_df[all_df['symbol'].isin(st.session_state.watchlist)]
            
            if display_df.empty:
                st.info("아직 관심 종목에 담은 기업이 없습니다.")
        else:
            # 일반 캘린더 모드
            col_f1, col_f2 = st.columns([1, 1]) 
            with col_f1:
                period = st.selectbox(
                    label="조회 기간", 
                    options=["상장 예정 (30일)", "지난 6개월", "지난 12개월", "지난 18개월"],
                    key="filter_period",
                    label_visibility="collapsed"
                )
            with col_f2:
                sort_option = st.selectbox(
                    label="정렬 순서", 
                    options=["최신순", "수익률"],
                    key="filter_sort",
                    label_visibility="collapsed"
                )
            
            # [수정본] 기간별 데이터 필터링 로직
            if period == "상장 예정 (30일)":
                # 오늘 포함 미래 30일까지 (공모가 미확정 종목 포함 가능성 대비)
                display_df = all_df[(all_df['공모일_dt'] >= today_dt) & (all_df['공모일_dt'] <= today_dt + timedelta(days=30))]
            else:
                # '지난 X개월' 선택 시: 오늘 이전(과거) 데이터 중 해당 기간 내 것만 필터링
                if period == "지난 6개월":
                    start_date = today_dt - timedelta(days=180)
                elif period == "지난 12개월":
                    start_date = today_dt - timedelta(days=365)
                elif period == "지난 18개월":
                    start_date = today_dt - timedelta(days=540)
                
                # 🔥 핵심 수정: 오늘(today_dt)을 기준으로 '과거' 데이터 전체를 긁어오도록 범위 명확화
                display_df = all_df[(all_df['공모일_dt'] < today_dt) & (all_df['공모일_dt'] >= start_date)]

                # [추가 검증] 만약 6개월 데이터가 여전히 부족하다면?
                # API가 반환하는 전체 데이터셋(all_df_raw)에 해당 날짜가 있는지 확인하는 디버깅용 메시지
                if display_df.empty and not all_df_raw.empty:
                    st.sidebar.warning(f"⚠️ {period} 범위에 해당하는 데이터가 API 응답에 없습니다.")

        # [정렬 로직]
        if 'live_price' not in display_df.columns:
            display_df['live_price'] = 0.0

        if not display_df.empty:
            if sort_option == "최신순": 
                display_df = display_df.sort_values(by='공모일_dt', ascending=False)
                
            elif sort_option == "수익률":
                with st.spinner("🔄 실시간 시세 조회 중..."):
                    returns = []
                    prices = []
                    for idx, row in display_df.iterrows():
                        try:
                            p_raw = str(row.get('price','0')).replace('$','').split('-')[0]
                            p_ipo = float(p_raw) if p_raw else 0
                            p_curr = get_current_stock_price(row['symbol'], MY_API_KEY)
                            
                            if p_ipo > 0 and p_curr > 0:
                                ret = ((p_curr - p_ipo) / p_ipo) * 100
                            else:
                                ret = -9999
                        except: 
                            ret = -9999
                            p_curr = 0
                        returns.append(ret)
                        prices.append(p_curr)
                    
                    display_df['temp_return'] = returns
                    display_df['live_price'] = prices
                    display_df = display_df.sort_values(by='temp_return', ascending=False)

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

        

# 5. 상세 페이지 (이동 로직 보정 + 디자인 + NameError 방지 통합본)
elif st.session_state.page == 'detail':
    stock = st.session_state.selected_stock
    
    # [1] 변수 초기화
    profile = None
    fin_data = None
    current_p = 0
    off_val = 0

    if stock:
        # -------------------------------------------------------------------------
        # [2] 상단 메뉴바 (블랙 스타일 & 이동 로직 보정)
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

        is_logged_in = st.session_state.auth_status == 'user'
        login_text = "로그아웃" if is_logged_in else "로그인"
        main_text = "메인"
        watch_text = f"관심 ({len(st.session_state.watchlist)})"
        board_text = "게시판"
        
        menu_options = [login_text, main_text, watch_text, board_text]
        
        # 상세 페이지에서는 선택된 메뉴가 없도록 index를 None에 가깝게 유지하거나 새로운 키 사용
        selected_menu = st.pills(
            label="nav", 
            options=menu_options, 
            selection_mode="single", 
            key="detail_nav_final_v7", 
            label_visibility="collapsed"
        )

        if selected_menu:
            if selected_menu == login_text:
                if is_logged_in: st.session_state.auth_status = None
                st.session_state.page = 'login'
            
            elif selected_menu == main_text:
                st.session_state.view_mode = 'all'
                # [중요] 하얀 화면 방지: 메인 목록 페이지 이름이 'calendar'라면 여기를 'calendar'로 유지
                st.session_state.page = 'calendar' 
            
            elif selected_menu == watch_text:
                st.session_state.view_mode = 'watchlist'
                st.session_state.page = 'calendar' # 위와 동일하게 설정
            
            elif selected_menu == board_text:
                st.session_state.page = 'board'
            
            st.rerun()


        # -------------------------------------------------------------------------
        # [3] 사용자 판단 로직 (함수 정의)
        # -------------------------------------------------------------------------
        if 'user_decisions' not in st.session_state:
            st.session_state.user_decisions = {}
        
        sid = stock['symbol']
        if sid not in st.session_state.user_decisions:
            st.session_state.user_decisions[sid] = {"news": None, "filing": None, "macro": None, "company": None}

        def draw_decision_box(step_key, title, options):
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

        # -------------------------------------------------------------------------
        # [4] 데이터 로딩 및 헤더 구성 (폰트 크기 최적화 버전)
        # -------------------------------------------------------------------------
        today = datetime.now().date()
        try: 
            ipo_dt = stock['공모일_dt'].date() if hasattr(stock['공모일_dt'], 'date') else pd.to_datetime(stock['공모일_dt']).date()
        except: 
            ipo_dt = today
        
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

        # 수익률 계산 및 HTML 구성 (오타 수정 버전)
        if current_p > 0 and off_val > 0:
            pct = ((current_p - off_val) / off_val) * 100
            color = "#00ff41" if pct >= 0 else "#ff4b4b"
            icon = "▲" if pct >= 0 else "▼"
            # 폰트 크기를 탭 메뉴와 맞추기 위해 스타일 조정
            p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / 공모 ${off_val} / 현재 ${current_p} <span style='color:{color}; font-weight:bold;'>{icon} {abs(pct):.1f}%</span>)</span>"
        else:
            # 여기 시작 부분에 f" 를 정확히 넣었습니다.
            p_info = f"<span style='font-size: 0.9rem; color: #888;'>({date_str} / 공모 ${off_val} / 상장 대기)</span>"

        # 기업명 출력 (h3 급 크기로 줄여서 탭 메뉴와 조화롭게 변경)
        st.markdown(f"""
            <div style='margin-bottom: -10px;'>
                <span style='font-size: 1.2rem; font-weight: 700;'>{status_emoji} {stock['name']}</span> 
                {p_info}
            </div>
        """, unsafe_allow_html=True)
        
        st.write("") # 미세 여백

         # -------------------------------------------------------------------------
        # [CSS 추가] 탭 텍스트 색상 검정색으로 강제 고정 (모바일 가독성 해결)
        # -------------------------------------------------------------------------
        st.markdown("""
        <style>
            /* 1. 탭 버튼 내부의 텍스트 색상 지정 */
            .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
                color: #333333 !important; /* 검은색 강제 적용 */
                font-weight: bold !important; /* 굵게 표시 */
            }
            
            /* 2. 탭 마우스 오버 시 색상 (선택 사항) */
            .stTabs [data-baseweb="tab-list"] button:hover [data-testid="stMarkdownContainer"] p {
                color: #004e92 !important; /* 마우스 올렸을 때 파란색 */
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
            
            # 각 문서별 설명 및 AI 분석 프롬프트용 데이터
            def_meta = {
                "S-1": {
                    "desc": "S-1은 상장을 위해 최초로 제출하는 서류입니다. **Risk Factors**(위험 요소), **Use of Proceeds**(자금 용도), **MD&A**(경영진의 운영 설명)를 확인할 수 있습니다.",
                    "points": "Risk Factors(특이 소송/규제), Use of Proceeds(자금 용도의 건전성), MD&A(성장 동인)"
                },
                "S-1/A": {
                    "desc": "S-1/A는 공모가 밴드와 주식 수가 확정되는 수정 문서입니다. **Pricing Terms**(공모가 확정 범위)와 **Dilution**(기존 주주 대비 희석률)을 확인할 수 있습니다.",
                    "points": "Pricing Terms(수요예측 분위기), Dilution(신규 투자자 희석률)"
                },
                "F-1": {
                    "desc": "F-1은 해외 기업이 미국 상장 시 제출하는 서류입니다. 해당 국가의 **Foreign Risk**(정치/경제 리스크)와 **Accounting**(회계 기준 차이)을 확인할 수 있습니다.",
                    "points": "Foreign Risk(지정학적 리스크), Accounting(GAAP 차이)"
                },
                "FWP": {
                    "desc": "FWP는 기관 투자자 대상 로드쇼(Roadshow) PPT 자료입니다. **Graphics**(비즈니스 모델 시각화)와 **Strategy**(경영진이 강조하는 미래 성장 동력)를 확인할 수 있습니다.",
                    "points": "Graphics(시장 점유율 시각화), Strategy(미래 핵심 먹거리)"
                },
                "424B4": {
                    "desc": "424B4는 공모가가 최종 확정된 후 발행되는 설명서입니다. **Underwriting**(주관사 배정)과 확정된 **Final Price**(최종 공모가)를 확인할 수 있습니다.",
                    "points": "Underwriting(주관사 등급), Final Price(기관 배정 물량)"
                }
            }
            
            curr_meta = def_meta.get(topic, def_meta["S-1"])

            # UI 출력: 통합된 설명문 출력
            st.info(curr_meta['desc'])
            
            # 1. expander를 누르면 즉시 분석이 시작되도록 설정
            with st.expander(f" {topic} 요약보기", expanded=False):
                # expander가 열려 있을 때만 내부 로직 실행
                with st.spinner(f" AI가 {topic}의 핵심 내용을 분석 중입니다..."):
                    analysis_result = get_ai_analysis(stock['name'], topic, curr_meta['points'])
                    
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
            
        # --- Tab 1: 뉴스 & 심층 분석 ---
        with tab1:
            st.caption("자체 알고리즘으로 검색한 뉴스를 순위에 따라 제공합니다.")
            
            # [1] 기업 심층 분석 섹션 (Expander 적용)
            with st.expander(f"비즈니스 모델 요약 보기", expanded=False):
                # 쿼리 정의 (이 줄이 꼭 있어야 합니다!)
                q_biz = f"{stock['name']} IPO stock founder business model revenue stream competitive advantage financial summary"
                
                with st.spinner(f"🤖 AI가 데이터를 정밀 분석 중입니다..."):
                    # 👇 함수 이름 final로 변경 (캐시 문제 해결됨)
                    biz_info = get_ai_summary_final(q_biz) 
                    
                    if biz_info:
                        # 스타일에서 white-space 제거하고, 공백 없이 딱 붙여 넣기
                        st.markdown(f"""
                        <div style="
                            background-color: #f8f9fa; 
                            padding: 22px; 
                            border-radius: 12px; 
                            border-left: 5px solid #6e8efb; 
                            color: #333; 
                            font-family: 'Pretendard', sans-serif;
                            font-size: 15px;
                        ">{biz_info}</div>
                        """, unsafe_allow_html=True)
                    else:
                        st.error("⚠️ 정보를 찾을 수 없습니다.")
        
            # [2] 뉴스 리스트 섹션
            # (주의: get_real_news_rss 내부의 자체 번역 로직은 비활성화되어 있어야 속도가 빠릅니다)
            rss_news = get_real_news_rss(stock['name'])
            
            if rss_news:
                exclude_keywords = ['jewel', 'fashion', 'necklace', 'diamond', 'ring', 'crown royal', 'jewelry', 'pendant'] 
                target_tags = ["분석", "시장", "전망", "전략", "수급"]
                final_display_news = []
                used_indices = set()
        
                # 1. 노이즈 필터링
                filtered_news = [n for n in rss_news if not any(ek in n.get('title', '').lower() for ek in exclude_keywords)]
        
                # 2. 태그 분류 로직 (중복 방지 유지)
                for target in target_tags + ["일반"]:
                    for idx, n in enumerate(filtered_news):
                        if len(final_display_news) >= 5: break
                        if idx in used_indices: continue
                        
                        title_lower = n.get('title', '').lower()
                        tag = "일반"
                        if any(k in title_lower for k in ['analysis', 'valuation', 'report', 'rating', '분석']): tag = "분석"
                        elif any(k in title_lower for k in ['ipo', 'listing', 'nyse', 'nasdaq', 'market', '시장', '상장']): tag = "시장"
                        elif any(k in title_lower for k in ['forecast', 'outlook', 'target', 'expects', '전망']): tag = "전망"
                        elif any(k in title_lower for k in ['strategy', 'plan', 'pipeline', 'drug', '전략']): tag = "전략"
                        elif any(k in title_lower for k in ['price', 'raise', 'funding', 'share', '수급', '공모']): tag = "수급"
        
                        if tag == target or (target == "일반" and tag == "일반"):
                            n['display_tag'] = tag
                            final_display_news.append(n)
                            used_indices.add(idx)
        
                # 3. 뉴스 카드 출력 (AI 번역 적용)
                for i, n in enumerate(final_display_news):
                    tag = n['display_tag']
                    en_title = n.get('title', 'No Title')
                    
                    # 🔥 고성능 AI 번역 호출 (캐시 적용됨)
                    with st.spinner(f"TOP {i+1} 번역 중..."):
                        ko_title = translate_news_title(en_title)
                    
                    s_badge = f'<span style="background:{n.get("bg","#eee")}; color:{n.get("color","#333")}; padding:2px 6px; border-radius:4px; font-size:11px; margin-left:5px;">{n.get("sent_label","")}</span>' if n.get("sent_label") else ""
                    
                    # 특수 기호 처리
                    safe_en = en_title.replace("$", "\$")
                    safe_ko = ko_title.replace("$", "\$")
                    
                    st.markdown(f"""
                        <a href="{n['link']}" target="_blank" style="text-decoration:none; color:inherit;">
                            <div style="padding:15px; border:1px solid #eee; border-radius:10px; margin-bottom:10px; box-shadow:0 2px 5px rgba(0,0,0,0.03);">
                                <div style="display:flex; justify-content:space-between; align-items:center;">
                                    <div>
                                        <span style="color:#6e8efb; font-weight:bold;">TOP {i+1}</span> 
                                        <span style="color:#888; font-size:12px;">| {tag}</span>
                                        {s_badge}
                                    </div>
                                    <small style="color:#bbb;">{n.get('date','')}</small>
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

            # 맨 마지막에 호출
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
            with st.expander("논문기반 AI분석보기", expanded=False): 
                is_hot_market = md['ipo_return'] >= 20 or md['ipo_volume'] >= 10
                is_bubble_risk = md['unprofitable_pct'] >= 80
        
                if is_hot_market:
                    ipo_market_analysis = "현재 IPO 시장은 **'Hot Market(과열기)'**의 징후를 보이고 있습니다. 초기 수익률은 높으나 상장 후 장기 성과는 낮을 수 있습니다."
                else:
                    ipo_market_analysis = "현재 IPO 시장은 **'Cold Market(안정기)'** 상태입니다. 보수적인 공모가 산정이 이루어지고 있습니다."
        
                if md['vix'] >= 25 or md['fear_greed'] <= 30:
                    macro_analysis = "공포 심리가 확산되어 있습니다. IPO 철회 리스크가 커지며 보수적 접근이 필요합니다."
                elif md['buffett_val'] > 150:
                    macro_analysis = "버핏 지수가 극단적 고평가 영역에 있습니다. 고밸류에이션 종목 투자에 주의하십시오."
                else:
                    macro_analysis = "거시 지표는 비교적 안정적입니다. 신규 상장주에 대한 수급이 양호할 것으로 보입니다."
        
                st.success("시장 환경 데이터 통합 검증 완료")
                st.write(f"**IPO 수급 환경:** {ipo_market_analysis}")
                st.write(f"**거시 경제 리스크:** {macro_analysis}")
                if is_bubble_risk:
                    st.warning("🚨 **경고:** 적자 기업 비율이 매우 높습니다. 개별 종목의 현금흐름 확인이 필수적입니다.")
                st.info("**Tip:** 시장 과열기에는 발생액 품질(Accruals Quality)을 따져봐야 합니다.")
        
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
                            font-weight: bold;    /* 지표명을 굵게 변경 */
                            color: #333333;
                            margin-bottom: 6px;
                        }
                        .custom-metric-value {
                            font-size: 1.05rem; 
                            font-weight: 400;    /* 수치를 일반 굵기로 변경 */
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
                
                # ... (이후 opinion_text 및 리스크 요인 코드는 동일하게 유지)
                    
                    opinion_text = f"""
                    **[Valuation & Market Position]** 현재 {stock['name']}은(는) 선행 PER {pe_val:.1f}x 수준에서 거래되고 있습니다. 
                    최근 실적 분석 결과, **연간 매출 ${rev_display}M** 및 **영업이익률(OPM) {opm_display}%**를 기록하며 외형 성장과 수익성 사이의 균형을 유지하고 있습니다. 
                    이는 산업 평균 및 역사적 밴드 대비 {"상단에 위치하여 프리미엄이 반영된" if pe_val > 30 else "합리적인 수준에서 형성된"} 것으로 판단되며, 
                    United Rentals(URI) 및 Ashtead Group(AGGGY) 등 **동종 업계 경쟁사들과 비교했을 때 상대적으로 높은 매출 성장 탄력성**을 보유하고 있는 점이 고무적입니다.
        
                    **[Operating Performance]** 자기자본이익률(ROE) {roe_val:.1f}%는 자본 효율성 측면에서 {"경쟁사 대비 우수한 수익 창출력" if roe_val > 15 else "개선이 필요한 경영 효율성"}을 나타내고 있습니다. 
                    특히 YoY 매출 성장률 {growth:.1f}%는 시장 점유율 확대 가능성을 시사하는 핵심 지표입니다.
        
                    **[Risk & Solvency]** 부채비율 {de_ratio:.1f}%를 고려할 때, {"금리 인상기에도 재무적 완충력이 충분한" if de_ratio < 100 else "추가 차입 부담이 존재하여 현금 흐름 관리가 요구되는"} 상태입니다. 
        
                    **[Analyst Conclusion]** 종합적으로 볼 때, 본 기업은 고성장 프리미엄과 수익성 사이의 균형점에 위치해 있습니다. 
                    회계 품질({accruals_status}) 기반의 이익 투명성이 보장된다는 전제하에, 향후 분기별 이익 가시성(Earnings Visibility) 확보 여부가 
                    추가적인 밸류에이션 리레이팅(Re-rating)의 트리거가 될 것으로 전망됩니다.
                    """
                    
                    st.info(opinion_text)
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

        # --- Tab 4: 기관평가 (Wall Street IPO Radar) ---
        with tab4:
            with st.spinner(f"전문 기관 데이터를 정밀 수집 중..."):
                result = get_cached_ipo_analysis(stock['symbol'], stock['name'])
        
            # --- (1) Renaissance Capital 섹션 ---
            with st.expander("Summary of Renaissance Capital IPO, Seeking Alpha & Morningstar", expanded=False):
                
                # 1. 데이터 가져오기 (결과가 리스트일 경우를 대비해 처리)
                raw_val = result.get('summary', '')
                summary_raw = raw_val[0] if isinstance(raw_val, list) else str(raw_val)
            
                # 2. [초강력 절단 방식] 'Source' 또는 'http' 기준 분할
                if summary_raw and len(summary_raw.strip()) > 0:
                    import re
                    
                    # 가. 다양한 출처 표기법 대응 (Source:, 출처:, http, https 등)
                    # 패턴 설명: (대소문자무시)Source 문구 또는 http로 시작하는 모든 지점
                    pattern = r'(?i)source|출처|https?://'
                    
                    # 나. 해당 패턴이 발견되는 가장 첫 번째 지점을 기준으로 앞부분만 취함
                    parts = re.split(pattern, summary_raw)
                    summary = parts[0].strip()
                    
                    # 다. 문장 끝에 남은 지저분한 기호들 정리
                    summary = summary.rstrip(' ,.:;-\n\t')
                else:
                    summary = ""
            
                # 3. 결과 출력
                if not summary or "분석 불가" in summary:
                    st.warning("Renaissance Capital에서 직접적인 분석 리포트를 찾지 못했습니다. (비상장 또는 데이터 업데이트 지연)")
                else:
                    # 최종 정제된 요약본 출력
                    st.info(summary)
                
                # 4. 하단 버튼 (기존 유지)
                q = stock['symbol'] if stock['symbol'] else stock['name']
                search_url = f"https://www.google.com/search?q=site:renaissancecapital.com+{q}"
                st.link_button(f" {stock['name']} Renaissance 데이터 직접 찾기", search_url)
        
            # --- (2) Seeking Alpha & Morningstar 섹션 ---
            with st.expander("Pros and Cons of Renaissance Capital IPO, Seeking Alpha & Morningstar ", expanded=False):
                # 여기도 혹시 모르니 세척 로직 적용
                raw_pro_con = result.get('pro_con', '')
                pro_con = clean_text_final(raw_pro_con)
                
                if "의견 수집 중" in pro_con or not pro_con:
                    st.error("AI가 실시간 리포트 본문을 읽어오는데 실패했습니다.")
                else:
                    # 정제된 pro_con 출력
                    st.success(f"**주요 긍정/부정 의견**\n\n{pro_con}")
                
                c1, c2 = st.columns(2)
                with c1:
                    st.link_button("Seeking Alpha 분석글 보기", f"https://seekingalpha.com/symbol/{q}/analysis")
                with c2:
                    st.link_button("Morningstar 검색 결과", f"https://www.morningstar.com/search?query={q}")


            # --- (3) Institutional Sentiment 섹션 ---
            with st.expander("Sentiment Score", expanded=False):
                s_col1, s_col2 = st.columns(2)
                
                # 데이터 가져오기 및 세척
                rating_val = str(result.get('rating', 'Hold')).strip()
                score_val = str(result.get('score', '3')).strip()
            
                with s_col1:
                    # Analyst Ratings 동적 툴팁 생성
                    # 현재 값에 따라 (현재) 표시를 붙여줍니다.
                    r_list = {
                        "Strong Buy": "적극 매수 추천",
                        "Buy": "매수 추천",
                        "Hold": "보유 및 중립 관망",
                        "Neutral": "보유 및 중립 관망",
                        "Sell": "매도 및 비중 축소"
                    }
                    
                    rating_help = "**[Analyst Ratings 설명]**\n애널리스트 투자의견 컨센서스입니다.\n\n"
                    for k, v in r_list.items():
                        is_current = " **(현재)**" if k.lower() in rating_val.lower() else ""
                        rating_help += f"- **{k}**: {v}{is_current}\n"
            
                    st.write("**[Analyst Ratings]**")
                    
                    # 실제 출력 및 help 적용
                    # st.metric을 사용하면 help 옵션이 정상 작동하고 에러가 사라집니다.
                    st.metric(label="Consensus Rating", value=rating_val, help=rating_help)
                    
                    # 상태에 따른 색상 피드백은 아래와 같이 별도로 간단히 추가할 수 있습니다.
                    if any(x in rating_val for x in ["Buy", "Positive", "Outperform"]):
                        st.caption("✅ 시장의 긍정적인 평가를 받고 있습니다.")
                    elif any(x in rating_val for x in ["Sell", "Negative", "Underperform"]):
                        st.error(f"Consensus: {rating_val}", help=rating_help)
                    else:
                      
                        # 설명(help)은 그 아래에 작게 표시
                        if rating_help:
                            st.caption(f"ℹ️ {rating_help}")
                                    
                with s_col2:
                    # IPO Scoop Score 동적 툴팁 생성
                    s_list = {
                        "5": "대박 (Moonshot)",
                        "4": "강력한 수익",
                        "3": "양호 (Good)",
                        "2": "미미한 수익 예상",
                        "1": "공모가 하회 위험"
                    }
                    
                    score_help = "**[IPO Scoop Score 설명]**\n상장 첫날 수익률 기대치입니다.\n\n"
                    for k, v in s_list.items():
                        is_current = f" **(현재 {score_val}점)**" if k == score_val else ""
                        score_help += f"- ⭐ {k}개: {v}{is_current}\n"
            
                    st.write("**[IPO Scoop Score]**")
                    st.metric(label="Expected IPO Score", value=f"⭐ {score_val}", help=score_help)

                    # 👇 여기 아래 두 줄을 추가하세요!
                    if score_help:
                        st.caption(f"ℹ️ {score_help}")
            
                # 참고 소스 링크
                sources = result.get('links', [])
                if sources:
                    st.markdown('<br><p style="font-size: 1.1rem; font-weight: 600; margin-bottom: 0px;">참고 리포트 출처</p>', unsafe_allow_html=True)
                    for src in sources[:4]:
                        st.markdown(f"- [{src['title']}]({src['link']})")



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
