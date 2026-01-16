# ==========================================
# 화면 3: 캘린더 (가격/공모규모 노출 보완)
# ==========================================
elif st.session_state.page == 'calendar':
    if st.sidebar.button("⬅️ 돌아가기"):
        st.session_state.page = 'stats'
        st.rerun()
    
    st.header("🚀 실시간 유아기 유니콘 캘린더")
    df = get_ipo_data(MY_API_KEY, 30)

    # --- [테스트용 데모 데이터 로직] ---
    # 실제 API에서 가격이 0으로 올 경우를 대비해, 샘플 데이터를 생성하여 표시 여부를 확인합니다.
    if df.empty or (df['price'].fillna(0).astype(float) == 0).all():
        st.info("💡 실시간 확정 가격이 아직 공시되지 않았습니다. (아래는 데이터 구조 예시입니다)")
        demo_data = {
            'name': ['Test Unicorn AI', 'Sample Robotics', 'Future Energy'],
            'symbol': ['UAI', 'SROB', 'FNRG'],
            'price': [15.50, 22.00, 10.00],
            'numberOfShares': [10000000, 5000000, 8000000],
            'exchange': ['NASDAQ', 'NYSE', 'NASDAQ']
        }
        df = pd.DataFrame(demo_data)

    # 1. 데이터 타입 강제 변환 (숫자형으로 변환되지 않으면 계산 시 0이 됨)
    df['price'] = pd.to_numeric(df['price'], errors='coerce').fillna(0)
    df['numberOfShares'] = pd.to_numeric(df['numberOfShares'], errors='coerce').fillna(0)
    
    # 2. 공모규모 계산
    df['공모규모'] = df['price'] * df['numberOfShares']
    
    # 3. 추가 항목 설정
    df['자금용도'] = "공시(S-1) 참조"
    df['보호예수'] = "180일"
    df['언더라이터'] = "IB 주관사"
    df['📄 공시'] = df['symbol'].apply(lambda x: f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={x}")
    df['📊 재무'] = df['symbol'].apply(lambda x: f"https://finance.yahoo.com/quote/{x}/financials")

    # 4. 출력용 데이터프레임 구성 및 컬럼 순서 재배치
    # 가격 -> 주식수 -> 공모규모 -> 자금용도 -> 보호예수 -> 언더라이터 -> 거래소 -> 공시 -> 재무
    result_df = df[['name', 'symbol', 'price', 'numberOfShares', '공모규모', '자금용도', '보호예수', '언더라이터', 'exchange', '📄 공시', '📊 재무']]
    result_df.columns = ['기업명', '티커', '가격($)', '주식수', '공모규모($)', '자금용도', '보호예수', '언더라이터', '거래소', '공시', '재무']

    # 5. 데이터 편집기 출력 (가격이 0인 경우를 고려한 포맷)
    st.data_editor(
        result_df,
        column_config={
            "가격($)": st.column_config.NumberColumn(
                format="$%.2f", 
                help="가격이 0인 경우 아직 공모가가 확정되지 않은 상태입니다."
            ),
            "주식수": st.column_config.NumberColumn(format="%d"),
            "공모규모($)": st.column_config.NumberColumn(
                format="$%d", 
                help="총 공모 규모 (가격 x 주식수)"
            ),
            "공시": st.column_config.LinkColumn(display_text="SEC 확인"),
            "재무": st.column_config.LinkColumn(display_text="재무 확인"),
        },
        hide_index=True,
        use_container_width=True
    )

    st.warning("⚠️ Finnhub 무료 API는 상장 예정 종목의 확정 공모가(Price)를 제공하지 않을 수 있습니다. 0으로 표시될 경우 '공시' 링크를 통해 S-1 서류의 'Expected Price Range'를 확인해 주세요.")
