# -*- coding: utf-8 -*-
import pandas as pd
import streamlit as st
import datetime as dt

from news_aggregator import (
    search_web,
    dedupe_and_sort,
    enrich_with_content,
    filter_by_domains,
)

st.set_page_config(page_title="🌐 키워드 웹 검색/요약 대시보드 (울트라라이트)", layout="wide")

st.title("🌐 키워드 웹 검색/요약 대시보드 (울트라라이트)")
st.caption("의존성을 최소화한 배포용 버전입니다. 본문 수집은 비활성화되어 있습니다.")

with st.sidebar:
    st.header("검색 설정")
    query = st.text_input("검색 키워드", placeholder="예) 생성형 AI 보안 가이드, 반도체 시장 전망")
    max_results = st.slider("최대 결과 수", 10, 300, 60, step=10)

    st.markdown("---")
    st.subheader("기간")
    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("시작일", value=None)
    with col2:
        date_to = st.date_input("종료일", value=None)

    st.markdown("---")
    st.subheader("콘텐츠 처리")
    do_fetch_text = st.checkbox("페이지 본문 수집", False, help="울트라라이트 버전에서는 비활성화됨")
    do_summarize = st.checkbox("요약 생성", False, help="본문 수집이 꺼져 있으면 요약도 생성되지 않습니다")
    summary_len = st.slider("요약 문장 수", 2, 6, 3, disabled=not do_summarize)
    do_keywords = st.checkbox("키워드(형태소) 추출", False, help="본문 수집이 꺼져 있으면 키워드도 생성되지 않습니다")

    st.markdown("---")
    run = st.button("🔎 웹 검색 시작", use_container_width=True)

if run:
    if not query.strip():
        st.warning("키워드를 입력하세요.")
        st.stop()

    if date_from and date_to and date_from > date_to:
        st.warning("시작일이 종료일보다 늦습니다.")
        st.stop()

    with st.spinner("웹을 검색하고 있습니다..."):
        raw = search_web(
            query=query,
            max_results=max_results,
            date_from=date_from or None,
            date_to=date_to or None,
        )

    if not raw:
        st.info("검색 결과가 없습니다. 키워드를 바꾸거나 기간을 넓혀보세요.")
        st.stop()

    merged = dedupe_and_sort(raw)

    domains = sorted(list({(it.get("domain") or "").strip() for it in merged if it.get("domain")}))
    with st.expander("도메인 필터"):
        allow = st.multiselect("포함할 도메인 선택 (미선택 시 전체)", options=domains, default=[])

    filtered = filter_by_domains(merged, allow_domains=allow)
    if not filtered:
        st.info("필터 조건에 맞는 결과가 없습니다.")
        st.stop()

    df = pd.DataFrame(filtered)
    display_cols = ["title", "domain", "published_at", "link"]
    st.success(f"총 {len(df)}건의 결과를 확보했습니다.")

    # 링크는 'https://...' 형식의 문자열로 그대로 표시
    df_display = df[display_cols].copy()
    if "link" in df_display.columns:
        df_display["link"] = df_display["link"].astype(str)

    st.dataframe(df_display, use_container_width=True, height=520)

    st.markdown("### 세부 보기 (울트라라이트: 본문/요약/키워드 비활성)")
    titles = ["(선택)"] + df["title"].tolist()
    sel = st.selectbox("항목 선택", options=titles, index=0)
    if sel != "(선택)":
        row = df[df["title"] == sel].iloc[0]
        st.markdown(f"**도메인**: {row.get('domain','')}  |  **시각**: {row.get('published_at','')}")
        st.markdown(f"**원문 링크**: {row.get('link','')}")

    st.markdown("---")
    st.subheader("결과 다운로드")
    csv_bytes = df_display.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("CSV로 다운로드", data=csv_bytes, file_name=f"{query}_web.csv", mime="text/csv", use_container_width=True)

else:
    st.info("좌측 사이드바에서 키워드와 기간을 설정하고 **웹 검색 시작**을 눌러주세요.")
