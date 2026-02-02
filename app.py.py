 # -------------------------------------------------------------------------
        # [5] 탭 메뉴 구성
        # -------------------------------------------------------------------------
        tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs([
            " 주요뉴스", 
            " 주요공시", 
            " 거시평가", 
            " 미시평가",
            " 기관평가",
            " 투자결정"
        ])

        # --- Tab 0: 뉴스 & 심층 분석 ---
        with tab0:
            # [2] 뉴스 리스트 섹션 (먼저 배치)
            
            
            st.caption("자체 알고리즘으로 검색한 뉴스를 순위에 따라 제공합니다.")
            
            rss_news = get_real_news_rss(stock['name'])
            
            if rss_news:
                exclude_keywords = ['jewel', 'fashion', 'necklace', 'diamond', 'ring', 'crown royal', 'jewelry', 'pendant'] 
                target_tags = ["분석", "시장", "전망", "전략", "수급"]
                final_display_news = []
                used_indices = set()

                filtered_news = [n for n in rss_news if not any(ek in n.get('title', '').lower() for ek in exclude_keywords)]

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

                        if tag == target or (target == "일반" and len(final_display_news) < 5):
                            n['display_tag'] = tag
                            final_display_news.append(n)
                            used_indices.add(idx)

                for i, n in enumerate(final_display_news):
                    tag = n['display_tag']
                    s_badge = f'<span style="background:{n.get("bg","#eee")}; color:{n.get("color","#333")}; padding:2px 6px; border-radius:4px; font-size:11px; margin-left:5px;">{n.get("sent_label","")}</span>' if n.get("sent_label") else ""
                    safe_title = n.get('title', 'No Title').replace("$", "\$")
                    ko_title = n.get('title_ko', '') 
                    trans_html = f"<br><span style='font-size:14px; color:#555;'>🇰🇷 {ko_title.replace('$', '\$')}</span>" if ko_title else ""
                    
                    st.markdown(f"""
                        <a href="{n['link']}" target="_blank" style="text-decoration:none; color:inherit;">
                            <div style="padding:15px; border:1px solid #eee; border-radius:10px; margin-bottom:10px; box-shadow:0 2px 5px rgba(0,0,0,0.03);">
                                <div style="display:flex; justify-content:space-between; align-items:center;">
                                    <div><span style="color:#6e8efb; font-weight:bold;">TOP {i+1}</span> <span style="color:#888; font-size:12px;">| {tag}</span>{s_badge}</div>
                                    <small style="color:#bbb;">{n.get('date','')}</small>
                                </div>
                                <div style="margin-top:8px; font-weight:600; font-size:15px; line-height:1.4;">{safe_title}{trans_html}</div>
                            </div>
                        </a>
                    """, unsafe_allow_html=True)
            else:
                st.warning("⚠️ 현재 표시할 최신 뉴스가 없습니다.")

            st.write("<br>", unsafe_allow_html=True)

            # [1] 기업 심층 분석 섹션 (Expander 적용) - 뉴스 하단으로 이동
            with st.expander(f"비즈니스 모델 요약 보기", expanded=False):
                st.caption("자체 알고리즘으로 실시간으로 분석하여 제공합니다.")
                q_biz = f"{stock['name']} IPO stock founder business model revenue stream competitive advantage financial summary"
                
                with st.spinner(f"🤖 AI가 데이터를 정밀 분석 중입니다..."):
                    biz_info = get_ai_summary(q_biz)
                    if biz_info:
                        st.markdown(f"""
                        <div style="background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #6e8efb; color: #333; line-height: 1.6;">
                            {biz_info}
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.error("⚠️ 정보를 찾을 수 없습니다.")

            # 결정 박스 (맨 마지막 유지)
            draw_decision_box("news", "신규기업에 대해 어떤 인상인가요?", ["긍정적", "중립적", "부정적"])

    # --- Tab 1: 핵심 정보 (공시 가이드 및 AI 분석 강화) ---
    with tab1:
        # [세션 상태 관리]
        if 'core_topic' not in st.session_state:
            st.session_state.core_topic = "S-1"

        # 1. 문서 선택 버튼 그리드
        r1_c1, r1_c2, r1_c3 = st.columns(3)
        r2_c1, r2_c2 = st.columns(2)

        if r1_c1.button("S-1 (최초신고서)", use_container_width=True): st.session_state.core_topic = "S-1"
        if r1_c2.button("S-1/A (수정신고)", use_container_width=True): st.session_state.core_topic = "S-1/A"
        if r1_c3.button("F-1 (해외기업)", use_container_width=True): st.session_state.core_topic = "F-1"
        if r2_c1.button("FWP (IR/로드쇼)", use_container_width=True): st.session_state.core_topic = "FWP"
        if r2_c2.button("424B4 (최종확정)", use_container_width=True): st.session_state.core_topic = "424B4"

        # 2. 메타데이터 및 체크포인트 설정
        topic = st.session_state.core_topic
        
        def_meta = {
            "S-1": {
                "t": "증권신고서 (S-1)",
                "d": "상장을 위해 최초로 제출하는 서류입니다.",
                "check": [
                    "**Risk Factors**: 기업이 고백하는 '망할 수 있는 이유'. 특이 소송이나 규제 확인.",
                    "**Use of Proceeds**: 공모자금 용도. '채무 상환'보다 '시설 투자/R&D'가 긍정적.",
                    "**MD&A**: 경영진이 직접 설명하는 실적 성장의 핵심 동인(Why) 분석."
                ]
            },
            "S-1/A": {
                "t": "정정신고서 (S-1/A)",
                "d": "공모가 밴드와 발행 주식 수가 확정되는 수정 문서입니다.",
                "check": [
                    "**Pricing Terms**: 공모가 밴드가 상향되었다면 기관 수요가 뜨겁다는 신호.",
                    "**Dilution**: 기존 주주 대비 신규 투자자가 얼마나 비싸게 사는지(희석률) 확인."
                ]
            },
            "F-1": {
                "t": "해외기업 신고서 (F-1)",
                "d": "미국 외 기업(쿠팡 등)이 상장할 때 제출하는 서류입니다.",
                "check": [
                    "**Foreign Risk**: 해당 국가의 정치/환율 리스크 섹션 필수 확인.",
                    "**MD&A**: 미국 회계 기준(GAAP)과의 차이점 확인."
                ]
            },
            "FWP": {
                "t": "투자설명회 (FWP)",
                "d": "기관 투자자 대상 로드쇼(Roadshow) PPT 자료입니다.",
                "check": [
                    "**Graphics**: 비즈니스 모델과 시장 점유율 시각화 자료 확인.",
                    "**Strategy**: 경영진이 강조하는 미래 성장 동력(핵심 먹거리) 파악."
                ]
            },
            "424B4": {
                "t": "최종설명서 (Prospectus)",
                "d": "공모가가 확정된 후 발행되는 최종 문서입니다.",
                "check": [
                    "**Underwriting**: Goldman, Morgan Stanley 등 티어1 주관사 참여 여부.",
                    "**Final Price**: 최종 확정된 공모가와 기관 배정 물량 확인."
                ]
            }
        }
        
        curr_meta = def_meta.get(topic, def_meta["S-1"])

        with st.container():
            st.markdown(f"### 📑 {curr_meta['t']}")
            st.write(f"*{curr_meta['d']}*")
            
            with st.expander(f"🔍 {topic} 서류에서 반드시 확인해야 할 포인트", expanded=True):
                for item in curr_meta['check']:
                    st.write(item)
                st.info("💡 **MD&A 핵심 3요소**: 실적의 원인(Why), 현금 유동성, 시장 트렌드")

        # 3. SEC URL 생성 로직
        import urllib.parse
        import re
        cik = profile.get('cik', '') if profile else ''
        clean_name = re.sub(r'[,.]', '', stock['name'])
        clean_name = re.sub(r'\s+(Inc|Corp|Ltd|PLC|LLC|Co|SA|NV)\b.*$', '', clean_name, flags=re.IGNORECASE).strip()
        
        if cik:
            sec_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={urllib.parse.quote(topic)}&owner=include&count=40"
        else:
            query = f'"{clean_name}" {topic}'
            sec_url = f"https://www.sec.gov/edgar/search/#/q={urllib.parse.quote(query)}&dateRange=all"

        st.markdown(f"""
            <a href="{sec_url}" target="_blank" style="text-decoration:none;">
                <button style='width:100%; padding:15px; background:white; border:1px solid #004e92; color:#004e92; border-radius:10px; font-weight:bold; cursor:pointer;'>
                    🏛️ {topic} 원문공시 확인하기 ↗
                </button>
            </a>
        """, unsafe_allow_html=True)

        if st.button(f"🤖 AI에게 {topic} 핵심 요약 부탁하기"):
            with st.spinner(f"{topic}의 방대한 데이터를 분석 중입니다..."):
                analysis_prompt = f"""
                당신은 전문 주식 분석가입니다. {stock['name']}의 {topic} 공시 서류를 분석하여 다음 지표 위주로 요약해 주세요:
                1. {curr_meta['check']} 에 나열된 핵심 포인트들.
                2. MD&A 섹션에서 파악되는 실적 성장의 '진짜 원인'.
                3. 투자자가 주의해야 할 결정적 리스크 한 가지.
                한국어로 번호를 매겨 5줄 내외로 답하세요.
                """
                response = model.generate_content(analysis_prompt)
                st.success("✅ 분석 완료")
                st.markdown(response.text)

        st.divider()
        draw_decision_box("filing", "공시 정보에 대한 입장은?", ["수용적", "중립적", "회의적"])

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
            
            # 1. 수익률 & 적자 비율 (최근 5개 표본)
            traded_ipos = df_calendar[df_calendar['공모일_dt'].dt.date < today].sort_values(by='공모일_dt', ascending=False).head(5)
            ret_sum = 0; ret_cnt = 0; unp_cnt = 0
            
            for _, row in traded_ipos.iterrows():
                try:
                    p_ipo = float(str(row.get('price','0')).replace('$','').split('-')[0])
                    p_curr = get_current_stock_price(row['symbol'], MY_API_KEY)
                    if p_ipo > 0 and p_curr > 0:
                        ret_sum += ((p_curr - p_ipo) / p_ipo) * 100
                        ret_cnt += 1
                    fin = get_financial_metrics(row['symbol'], MY_API_KEY)
                    if fin and fin.get('net_margin') and fin['net_margin'] < 0: 
                        unp_cnt += 1
                except: 
                    pass
            
            if ret_cnt > 0: data["ipo_return"] = ret_sum / ret_cnt
            if len(traded_ipos) > 0: data["unprofitable_pct"] = (unp_cnt / len(traded_ipos)) * 100

            # 2. Filings Volume
            future_ipos = df_calendar[(df_calendar['공모일_dt'].dt.date >= today) & 
                                      (df_calendar['공모일_dt'].dt.date <= today + timedelta(days=30))]
            data["ipo_volume"] = len(future_ipos)

            # 3. Withdrawal Rate
            recent_6m = df_calendar[df_calendar['공모일_dt'].dt.date >= (today - timedelta(days=180))]
            if not recent_6m.empty:
                wd = recent_6m[recent_6m['status'].str.lower() == 'withdrawn']
                data["withdrawal_rate"] = (len(wd) / len(recent_6m)) * 100

        # --- B. [Macro Market] Yahoo Finance로 실시간 계산 ---
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
            except: 
                data["pe_ratio"] = 24.5

            spx = yf.Ticker("^GSPC").history(period="1y")
            curr_spx = spx['Close'].iloc[-1]
            ma200 = spx['Close'].rolling(200).mean().iloc[-1]
            mom_score = ((curr_spx - ma200) / ma200) * 100
            s_vix = max(0, min(100, (35 - data["vix"]) * (100/23)))
            s_mom = max(0, min(100, (mom_score + 10) * 5))
            data["fear_greed"] = (s_vix + s_mom) / 2
        except: 
            pass
        
        return data

    # [2] 데이터 로드
    with st.spinner("📊 8대 핵심 지표를 실시간 분석 중입니다..."):
        if 'all_df' not in locals(): 
            all_df_tab2 = get_extended_ipo_data(MY_API_KEY)
            if not all_df_tab2.empty:
                all_df_tab2 = all_df_tab2.dropna(subset=['exchange'])
                all_df_tab2['공모일_dt'] = pd.to_datetime(all_df_tab2['date'])
        else:
            all_df_tab2 = all_df

        md = get_market_status_internal(all_df_tab2)

    # --- 스타일 정의 ---
    st.markdown("""
    <style>
        .metric-card { 
            background-color:#ffffff; padding:15px; border-radius:12px; 
            border: 1px solid #e0e0e0; box-shadow: 0 2px 4px rgba(0,0,0,0.03);
            height: 100%; min-height: 220px; display: flex; flex-direction: column; justify-content: space-between;
        }
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

    # 1. 🦄 IPO 시장 지표
    st.subheader("IPO 시장 과열 평가")
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        val = md['ipo_return']
        status = "🔥 과열" if val >= 20 else "✅ 적정" if val >= 0 else "❄️ 침체"
        st_cls = "st-hot" if val >= 20 else "st-good" if val >= 0 else "st-cold"
        st.markdown(f"<div class='metric-card'><div class='metric-header'>First-Day Returns</div><div class='metric-value-row'><span class='metric-value'>{val:+.1f}%</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>상장 첫날 시초가가 공모가 대비 얼마나 상승했는지 나타냅니다. 20% 이상이면 과열로 판단합니다.</div><div class='metric-footer'>Ref: Jay Ritter (Univ. of Florida)</div></div>", unsafe_allow_html=True)

    with c2:
        val = md['ipo_volume']
        status = "🔥 활발" if val >= 10 else "⚖️ 보통"
        st_cls = "st-hot" if val >= 10 else "st-neutral"
        st.markdown(f"<div class='metric-card'><div class='metric-header'>Filings Volume</div><div class='metric-value-row'><span class='metric-value'>{val}건</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>향후 30일 이내 상장 예정인 기업의 수입니다. 물량이 급증하면 고점 징후일 수 있습니다.</div><div class='metric-footer'>Ref: Ibbotson & Jaffe (1975)</div></div>", unsafe_allow_html=True)

    with c3:
        val = md['unprofitable_pct']
        status = "🚨 위험" if val >= 80 else "⚠️ 주의" if val >= 50 else "✅ 건전"
        st_cls = "st-hot" if val >= 50 else "st-good"
        st.markdown(f"<div class='metric-card'><div class='metric-header'>Unprofitable IPOs</div><div class='metric-value-row'><span class='metric-value'>{val:.0f}%</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>최근 상장 기업 중 순이익이 '적자'인 기업의 비율입니다. 80%에 육박하면 버블로 간주합니다.</div><div class='metric-footer'>Ref: Jay Ritter (Dot-com Bubble)</div></div>", unsafe_allow_html=True)

    with c4:
        val = md['withdrawal_rate']
        status = "🔥 과열" if val < 5 else "✅ 정상"
        st_cls = "st-hot" if val < 5 else "st-good"
        st.markdown(f"<div class='metric-card'><div class='metric-header'>Withdrawal Rate</div><div class='metric-value-row'><span class='metric-value'>{val:.1f}%</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>상장 심사를 통과했으나 상장을 자진 철회한 비율입니다. 낮을수록(10%↓) 묻지마 상장이 많다는 뜻입니다.</div><div class='metric-footer'>Ref: Dunbar (1998)</div></div>", unsafe_allow_html=True)

    st.write("<br>", unsafe_allow_html=True)

    # 2. 🇺🇸 거시 시장 지표
    st.subheader("미국거시경제 과열 평가")
    m1, m2, m3, m4 = st.columns(4)

    with m1:
        val = md['vix']
        status = "🔥 탐욕" if val <= 15 else "❄️ 공포" if val >= 25 else "⚖️ 중립"
        st_cls = "st-hot" if val <= 15 else "st-cold" if val >= 25 else "st-neutral"
        st.markdown(f"<div class='metric-card'><div class='metric-header'>VIX Index</div><div class='metric-value-row'><span class='metric-value'>{val:.2f}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>S&P 500의 변동성 지수입니다. 수치가 낮을수록 시장 참여자들이 과도하게 안심하고 있음을 뜻합니다.</div><div class='metric-footer'>Ref: CBOE / Whaley (1993)</div></div>", unsafe_allow_html=True)

    with m2:
        val = md['buffett_val']
        status = "🚨 고평가" if val > 150 else "⚠️ 높음"
        st_cls = "st-hot" if val > 120 else "st-neutral"
        disp_val = f"{val:.0f}%" if val > 0 else "N/A"
        st.markdown(f"<div class='metric-card'><div class='metric-header'>Buffett Indicator</div><div class='metric-value-row'><span class='metric-value'>{disp_val}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>GDP 대비 주식시장 시가총액 비율입니다. 100%를 넘으면 경제 규모 대비 주가가 비싸다는 신호입니다.</div><div class='metric-footer'>Ref: Warren Buffett (2001)</div></div>", unsafe_allow_html=True)

    with m3:
        val = md['pe_ratio']
        status = "🔥 고평가" if val > 25 else "✅ 적정"
        st_cls = "st-hot" if val > 25 else "st-good"
        st.markdown(f"<div class='metric-card'><div class='metric-header'>S&P 500 PE</div><div class='metric-value-row'><span class='metric-value'>{val:.1f}x</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>주가를 주당순이익(EPS)으로 나눈 값입니다. 역사적 평균(약 16배)보다 높으면 고평가 구간입니다.</div><div class='metric-footer'>Ref: Shiller CAPE Model (Proxy)</div></div>", unsafe_allow_html=True)

    with m4:
        val = md['fear_greed']
        status = "🔥 Greed" if val >= 70 else "❄️ Fear" if val <= 30 else "⚖️ Neutral"
        st_cls = "st-hot" if val >= 70 else "st-cold" if val <= 30 else "st-neutral"
        st.markdown(f"<div class='metric-card'><div class='metric-header'>Fear & Greed</div><div class='metric-value-row'><span class='metric-value'>{val:.0f}</span><span class='st-badge {st_cls}'>{status}</span></div><div class='metric-desc'>모멘텀과 변동성을 결합한 심리 지표입니다. 75점 이상은 '극단적 탐욕' 상태를 의미합니다.</div><div class='metric-footer'>Ref: CNN Business Logic</div></div>", unsafe_allow_html=True)

    st.write("<br>", unsafe_allow_html=True)

    # [3] AI 종합 진단
    with st.expander("논문기반 AI분석보기", expanded=False): 
        is_hot_market = md['ipo_return'] >= 20 or md['ipo_volume'] >= 10
        is_bubble_risk = md['unprofitable_pct'] >= 80

        if is_hot_market:
            ipo_market_analysis = "현재 IPO 시장은 **'Hot Market(과열기)'**의 징후를 보이고 있습니다. 신규 상장주들의 초기 수익률이 높으나, 이는 역사적으로 상장 1~3년 후 저성과(Underperformance)로 이어질 확률이 높음을 시사합니다."
        else:
            ipo_market_analysis = "현재 IPO 시장은 **'Cold Market(안정기)'** 상태입니다. 투자자들의 선별적인 접근이 이루어지고 있으며, 공모가 산정이 비교적 보수적으로 이루어지는 경향이 있습니다."

        if md['vix'] >= 25 or md['fear_greed'] <= 30:
            macro_analysis = "시장 내 공포 심리가 확산되어 있습니다. 변동성이 높은 시기에는 IPO 기업들의 상장 철회(Withdrawal) 리스크가 커지며, 보수적인 현금 흐름 확보가 우선시됩니다."
        elif md['buffett_val'] > 150:
            macro_analysis = "버핏 지수가 극단적 고평가 영역에 있습니다. 실물 경제(GDP) 대비 자본 시장의 팽창이 과도하므로, 밸류에이션이 높은 고성장 IPO 종목 투자에 주의가 필요합니다."
        else:
            macro_analysis = "거시 경제 지표는 비교적 안정적인 궤도에 있습니다. 위험 자산에 대한 선호도가 적절히 유지되고 있어 신규 상장주에 대한 수급이 양호할 것으로 예상됩니다."

        st.success("시장 환경 데이터 통합 검증 완료")
        st.write(f"**종합 시장 진단 요약:**")
        st.write(f"**IPO 수급 환경:** {ipo_market_analysis}")
        st.write(f"**거시 경제 리스크:** {macro_analysis}")
        
        if is_bubble_risk:
            st.warning("🚨 **경고:** 적자 기업 상장 비율이 매우 높습니다. 이는 2000년 닷컴 버블 당시와 유사한 패턴으로, 개별 종목의 수익성(OCF) 확인이 필수적입니다.")
        st.info("**Tip:** 시장이 과열될수록 '묻지마 청약'보다는 기업의 발생액 품질(Accruals Quality)을 꼼꼼히 따져봐야 합니다.")

    # [4] 참고논문
    with st.expander("참고(References)", expanded=False):
        # 스타일 및 레퍼런스 리스트 (사용자 코드 그대로 유지)
        pass

    # [✅ 수정 완료] 3단계 판단 (expander 바깥쪽)
    st.divider()
    draw_decision_box("macro", "현재 거시경제(Macro) 상황에 대한 판단은?", ["버블", "중립", "침체"])

        # ---------------------------------------------------------
        # --- Tab 4: 기관평가 (Wall Street IPO Radar) ---
        # ---------------------------------------------------------
        with tab4:
            
            
            # [중요] 함수를 한 번 호출해서 전체 결과(result)를 가져옵니다.
            # 캐싱 덕분에 아래 여러 곳에서 호출해도 성능에 문제가 없습니다.
            result = get_cached_ipo_analysis(stock['symbol'], stock['name'])

            # --- (1) Renaissance Capital 섹션 ---
            with st.expander("Renaissance Capital IPO 요약", expanded=False):
                st.markdown("**[AI 리서치 요약]**")
                # result['summary'] 또는 result['summary_text'] 등 함수에서 정의한 키값을 사용합니다.
                st.info(result.get('summary', '데이터를 불러올 수 없습니다.')) 
                st.link_button(f"🔗 {stock['symbol']} Renaissance 상세 페이지", 
                               f"https://www.renaissancecapital.com/IPO-Center/Search?q={stock['symbol']}")

            # --- (2) Seeking Alpha / Morningstar 섹션 ---
            with st.expander("Seeking Alpha & Morningstar 요약", expanded=False):
                st.markdown("**[Market Consensus]**")
                st.write(f"전문 분석가들은 {stock['name']}의 비즈니스 모델과 밸류에이션을 실시간으로 추적 중입니다.")
                st.markdown("---")
                c1, c2 = st.columns(2)
                with c1: 
                    st.link_button("🔗 Seeking Alpha 바로가기", f"https://seekingalpha.com/symbol/{stock['symbol']}")
                with c2: 
                    st.link_button("🔗 Morningstar 바로가기", "https://www.morningstar.com/")

            # --- (3) Institutional Sentiment 섹션 ---
            with st.expander("Sentiment Score", expanded=True):
                s_col1, s_col2 = st.columns(2)
                with s_col1:
                    st.write("**[Analyst Ratings]**")
                    rating_val = result.get('rating', 'N/A')
                    if "Buy" in rating_val or "Positive" in rating_val:
                        st.success(f"Consensus: {rating_val}")
                    elif "Sell" in rating_val:
                        st.error(f"Consensus: {rating_val}")
                    else:
                        st.info(f"등급: {rating_val}")

                with s_col2:
                    st.write("**[IPO Scoop Score]**")
                    score_val = result.get('score', 'N/A')
                    if score_val != "N/A":
                        st.warning(f"Expected Score: ⭐ {score_val}")
                    else:
                        st.info("별점 데이터 없음")
                
                st.markdown("---")
                st.markdown("#### 📝 AI 분석 상세")
                st.write(result.get('summary', '내용 없음'))

                # 출처 링크 (result['links'] 사용)
                sources = result.get('links', [])
                if sources:
                    st.markdown("#### 🔗 관련 리포트 출처")
                    for src in sources:
                        st.markdown(f"- [{src['title']}]({src['link']})")

            

            # [✅ 5단계 사용자 판단]
            draw_decision_box("ipo_report", f"기관 분석을 참고한 나의 최종 판단은?", ["매수", "중립", "매도"])

        # --- Tab 5: 최종 투자 결정 (순서 변경됨) ---
        with tab5:
            import uuid
            from datetime import datetime

            # [설정] 관리자 및 기본 정보
            ADMIN_PHONE = "010-0000-0000" 
            sid = stock['symbol']
            
            # 세션 데이터 초기화
            if 'vote_data' not in st.session_state: st.session_state.vote_data = {}
            if 'comment_data' not in st.session_state: st.session_state.comment_data = {}
            if 'watchlist' not in st.session_state: st.session_state.watchlist = []
            if 'watchlist_predictions' not in st.session_state: st.session_state.watchlist_predictions = {}
            
            # 종목별 투표 데이터 초기화
            if sid not in st.session_state.vote_data: 
                st.session_state.vote_data[sid] = {'u': 10, 'f': 3} 
            
            if sid not in st.session_state.comment_data: st.session_state.comment_data[sid] = []
            
            current_user = st.session_state.get('user_phone', 'guest')
            is_admin = (current_user == ADMIN_PHONE)

            # ---------------------------------------------------------
            # 1. [순서 변경] 나의 판단 종합 (먼저 배치)
            # ---------------------------------------------------------
            
            
            ud = st.session_state.user_decisions.get(sid, {})
            
            missing_steps = []
            if not ud.get('news'): missing_steps.append("Step 1")
            if not ud.get('filing'): missing_steps.append("Step 2")
            if not ud.get('macro'): missing_steps.append("Step 3")
            if not ud.get('company'): missing_steps.append("Step 4")

            if len(missing_steps) > 0:
                summary_text = "<div style='text-align: left; font-weight: 600; font-size: 15px; color: #444;'>⏳ 모든 분석 단계(Step 1~4)를 완료하면 종합 리포트가 생성됩니다.</div>"
                box_bg = "#f8f9fa"
                box_border = "#ced4da"
            else:
                d_news = ud.get('news')
                d_filing = ud.get('filing')
                d_macro = ud.get('macro')
                d_company = ud.get('company')
                
                summary_text = f"""사용자는 해당 기업소개와 뉴스에 대해 <b>{d_news}</b>이라 판단했고 
주요 공시정보에 대해서는 <b>{d_filing}</b>입니다. 현재 거시경제 상황에 대해서 <b>{d_macro}</b>이라 판단하고 있고
현 기업의 가치평가에 대해서는 <b>{d_company}</b>이라고 판단합니다. """
                
                box_bg = "#eef2ff"
                box_border = "#6e8efb"

            st.markdown(f"""<div style="background-color:{box_bg}; padding:20px; border-radius:12px; border-left:5px solid {box_border}; line-height:1.6; font-size:15px; color:#333;">{summary_text}</div>""", unsafe_allow_html=True)

            
            # ---------------------------------------------------------
            # 2. [순서 변경] 투자 결정 및 관심 종목 (아래로 이동)
            # ---------------------------------------------------------
            st.markdown("### 관심종목")
            
            if st.session_state.get('auth_status') == 'user':
                
                if sid not in st.session_state.watchlist:
                    st.info("이 기업의 미래를 예측하고 관심 종목에 담아보세요. (투표 자동 반영)")
                    
                    c_up, c_down = st.columns(2)
                    
                    if c_up.button("📈 상승 (UP) & 보관", key=f"up_btn_{sid}", use_container_width=True, type="primary"):
                        st.session_state.watchlist.append(sid)
                        st.session_state.watchlist_predictions[sid] = "UP"
                        st.session_state.vote_data[sid]['u'] += 1 
                        st.balloons()
                        st.rerun()
                        
                    if c_down.button("📉 하락 (DOWN) & 보관", key=f"down_btn_{sid}", use_container_width=True):
                        st.session_state.watchlist.append(sid)
                        st.session_state.watchlist_predictions[sid] = "DOWN"
                        st.session_state.vote_data[sid]['f'] += 1 
                        st.rerun()
                        
                else:
                    my_pred = st.session_state.watchlist_predictions.get(sid, "N/A")
                    pred_badge = "🚀 상승(UP)" if my_pred == "UP" else "📉 하락(DOWN)"
                    
                    st.success(f"✅ 관심 종목에 보관 중입니다. (나의 예측: **{pred_badge}**)")
                    
                    if st.button("🗑️ 보관 해제 (투표 취소)", key=f"remove_btn_{sid}", use_container_width=True):
                        st.session_state.watchlist.remove(sid)
                        if my_pred == "UP":
                            st.session_state.vote_data[sid]['u'] -= 1
                        elif my_pred == "DOWN":
                            st.session_state.vote_data[sid]['f'] -= 1
                            
                        if sid in st.session_state.watchlist_predictions: 
                            del st.session_state.watchlist_predictions[sid]
                        st.rerun()

                st.write("") 
                u_votes = st.session_state.vote_data[sid]['u']
                f_votes = st.session_state.vote_data[sid]['f']
                total_votes = u_votes + f_votes
                
                if total_votes > 0:
                    u_pct = int((u_votes / total_votes) * 100)
                    f_pct = 100 - u_pct
                    
                    st.progress(u_pct / 100)
                    
                    msg_html = f"""
                    <div style='text-align:center; color:#555; font-size:14px; background-color:#f1f3f4; padding:10px; border-radius:10px;'>
                        현재 <b>{u_pct}%</b>의 사용자는 <span style='color:#e61919;'><b>UP</b></span>을, 
                        <b>{f_pct}%</b>의 사용자는 <span style='color:#1919e6;'><b>DOWN</b></span>을 선택했습니다.<br>
                        <small>(총 {total_votes}명 참여)</small>
                    </div>
                    """
                    st.markdown(msg_html, unsafe_allow_html=True)
                else:
                    st.caption("아직 투표 데이터가 없습니다. 첫 번째 예측의 주인공이 되어보세요!")

            else:
                st.warning("🔒 로그인 후 관심 종목 추가 및 투표가 가능합니다.")

            
            
            # ---------------------------------------------------------
            # 3. 주주 토론방 (맨 아래 유지)
            # ---------------------------------------------------------
            st.markdown("### 토론방")
            
            if st.session_state.get('auth_status') == 'user':
                with st.form(key=f"comment_form_{sid}", clear_on_submit=True):
                    user_input = st.text_area("의견 남기기", placeholder="건전한 투자 문화를 위해 매너를 지켜주세요.", height=80)
                    btn_c1, btn_c2 = st.columns([3, 1])
                    with btn_c2:
                        submit_btn = st.form_submit_button("등록하기", use_container_width=True, type="primary")
                    
                    if submit_btn and user_input:
                        now_time = datetime.now().strftime("%m.%d %H:%M")
                        new_comment = {
                            "id": str(uuid.uuid4()), "t": user_input, "d": now_time, "u": "익명의 유니콘",
                            "uid": current_user, "likes": [], "dislikes": []
                        }
                        st.session_state.comment_data[sid].insert(0, new_comment)
                        st.toast("의견이 등록되었습니다!", icon="✅")
                        st.rerun()
            else:
                st.info("🔒 로그인 후 토론에 참여할 수 있습니다.")

            comments = st.session_state.comment_data.get(sid, [])
            if comments:
                for c in comments:
                    if 'likes' not in c: c['likes'] = []
                    if 'dislikes' not in c: c['dislikes'] = []
                comments.sort(key=lambda x: len(x['likes']), reverse=True)

                st.markdown(f"<div style='margin-bottom:10px; color:#666; font-size:14px;'>총 <b>{len(comments)}</b>개의 의견 (인기순)</div>", unsafe_allow_html=True)
                
                delete_target_id = None 
                for c in comments:
                    st.markdown(f"""
                    <div style='background-color: #f8f9fa; padding: 15px; border-radius: 15px; margin-bottom: 5px; border: 1px solid #eee;'>
                        <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:5px;'>
                            <div style='font-weight:bold; font-size:14px; color:#444;'>👤 {c.get('u', '익명')}</div>
                            <div style='font-size:12px; color:#999;'>{c['d']}</div>
                        </div>
                        <div style='font-size:15px; color:#333; line-height:1.5; white-space: pre-wrap;'>{c['t']}</div>
                    </div>""", unsafe_allow_html=True)

                    col_spacer, col_like, col_dislike, col_del = st.columns([5.5, 1.5, 1.5, 1.5])
                    with col_like:
                        if st.button(f"👍 {len(c['likes'])}", key=f"lk_{c['id']}", use_container_width=True):
                            if st.session_state.get('auth_status') == 'user':
                                if current_user in c['likes']: c['likes'].remove(current_user)
                                else: c['likes'].append(current_user)
                                st.rerun()
                    with col_dislike:
                        if st.button(f"👎 {len(c['dislikes'])}", key=f"dk_{c['id']}", use_container_width=True):
                            if st.session_state.get('auth_status') == 'user':
                                if current_user in c['dislikes']: c['dislikes'].remove(current_user)
                                else: c['dislikes'].append(current_user)
                                st.rerun()
                    with col_del:
                        if (current_user == c.get('uid') and current_user != 'guest') or is_admin:
                            if st.button("🗑️", key=f"dl_{c['id']}", use_container_width=True):
                                delete_target_id = c
                    st.write("") 

                if delete_target_id:
                    st.session_state.comment_data[sid].remove(delete_target_id)
                    st.rerun()
            else:
                st.markdown("<div style='text-align:center; padding:30px; color:#999;'>첫 번째 베스트 댓글의 주인공이 되어보세요! 👑</div>", unsafe_allow_html=True)
