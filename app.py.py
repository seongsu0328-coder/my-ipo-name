# ... (앞부분 생략: CSS 및 데이터 로직 동일) ...

# --- 화면 4: 상세 리서치 (업종 태그 복구 완료) ---
elif st.session_state.page == 'detail':
    stock = st.session_state.get('selected_stock')
    if stock:
        if st.button("⬅️ 목록으로"): st.session_state.page = 'calendar'; st.rerun()
        st.title(f"🚀 {stock['name']} 상세 리서치")
        cl, cr = st.columns([1, 4])
        with cl:
            logo_url = f"https://logo.clearbit.com/{stock['symbol']}.com"
            try: st.image(logo_url, width=150)
            except: st.info("로고 준비 중")
        with cr:
            st.subheader(f"{stock['name']} ({stock['symbol']})")
            
            # ✨ 복구된 업종 태그 부분
            st.markdown(f"**업종:** <span class='sector-tag'>Technology & Software</span>", unsafe_allow_html=True)
            
            st.divider()
            m1, m2, m3, m4 = st.columns(4)
            p = pd.to_numeric(stock.get('price'), errors='coerce')
            s = pd.to_numeric(stock.get('numberOfShares'), errors='coerce')
            p = 0 if pd.isna(p) else p
            s = 0 if pd.isna(s) else s
            
            m1.metric("공모 희망가", f"${p:,.2f}" if p > 0 else "미정")
            m2.metric("예상 규모", f"${(p*s):,.0f}" if p*s > 0 else "미정")
            m3.metric("유통물량", "분석 중")
            m4.metric("보호예수", "180일")

        # 비즈니스 요약 문구 추가 (가독성 향상)
        st.info(f"💡 **기업 비즈니스 요약:** {stock['name']}은(는) 혁신적인 기술력을 바탕으로 시장 확장을 준비 중인 IPO 유망 기업입니다.")
        
        l1, l2 = st.columns(2)
        l1.link_button("📄 SEC 공식 공시(S-1) 확인", f"https://www.sec.gov/cgi-bin/browse-edgar?company={stock['name'].replace(' ', '+')}", use_container_width=True, type="primary")
        l2.link_button("📈 Yahoo Finance 데이터", f"https://finance.yahoo.com/quote/{stock['symbol']}", use_container_width=True)
        
        # ... (이후 투표 섹션 동일) ...
