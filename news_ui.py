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

st.set_page_config(page_title="🌐 키워드 웹 검색/요약 대시보드", layout="wide")

st.title("🌐 키워드 웹 검색/요약 대시보드")
st.caption("키워드와 기간을 입력해 일반 웹에서 자료를 모으고, 본문/요약/키워드를 확인하세요.")

# --- 입력 영역 (사이드바) ------------------------------------------------------
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
    st.subheader("검색 엔진")
    engine = st.selectbox("엔진 선택", options=["DuckDuckGo(기본)"], index=0,
                          help="기본은 무료/키 불필요. 원하면 Google/Bing도 확장 가능.")

    st.markdown("---")
    st.subheader("콘텐츠 처리")
    do_fetch_text = st.checkbox("페이지 본문 수집 (크롤링)", True)
    do_summarize = st.checkbox("요약 생성", True)
    summary_len = st.slider("요약 문장 수", 2, 6, 3)
    do_keywords = st.checkbox("키워드(형태소) 추출", True)

    st.markdown("---")
    run = st.button("🔎 웹 검색 시작", use_container_width=True)

# --- 실행 ----------------------------------------------------------------------
if run:
    if not query.strip():
        st.warning("키워드를 입력하세요.")
        st.stop()

    # 날짜 검증
    if date_from and date_to and date_from > date_to:
        st.warning("시작일이 종료일보다 늦습니다. 확인해주세요.")
        st.stop()

    with st.spinner("웹을 검색하고 있습니다..."):
        raw = search_web(
            query=query,
            max_results=max_results,
            date_from=date_from if date_from else None,
            date_to=date_to if date_to else None,
            engine="duckduckgo",
        )

    if not raw:
        st.info("검색 결과가 없습니다. 키워드를 바꾸거나 기간을 넓혀보세요.")
        st.stop()

    merged = dedupe_and_sort(raw)

    # 도메인 필터 UI
    domains = sorted(list({(it.get("domain") or "").strip() for it in merged if it.get("domain")}))
    with st.expander("도메인 필터"):
        allow = st.multiselect(
            "포함할 도메인 선택 (미선택 시 전체)",
            options=domains, default=[]
        )

    filtered = filter_by_domains(merged, allow_domains=allow)
    if not filtered:
        st.info("필터 조건에 맞는 결과가 없습니다. 필터를 비우거나 변경해 보세요.")
        st.stop()

    # 본문/요약/키워드 추가
    if do_fetch_text or do_summarize or do_keywords:
        with st.spinner("본문/요약/키워드를 생성 중입니다..."):
            enriched = enrich_with_content(
                filtered,
                do_fetch_text=do_fetch_text,
                do_summarize=do_summarize,
                do_keywords=do_keywords,
                summary_sentences=summary_len,
            )
    else:
        enriched = filtered

    # 표 표시 ---------------------------------------------------------------
    df = pd.DataFrame(enriched)
    display_cols = ["title", "domain", "published_at", "link"]
    if do_summarize:
        display_cols.append("summary")
    if do_keywords:
        display_cols.append("keywords")

    st.success(f"총 {len(df)}건의 결과를 확보했습니다.")

    # 링크 클릭 가능 (한 번 클릭으로 새 탭 이동)
    # 링크를 'https://...' 문자열로 표에 직접 포함
    df_display = df[display_cols].copy()
    # 링크 열이 존재하면, 문자열 그대로 (https://...) 형식
    if "link" in df_display.columns:
        df_display["link"] = df_display["link"].astype(str)
    st.dataframe(
        df_display,
        use_container_width=True,
        height=520
    )

    # 상세 보기 --------------------------------------------------------------
    st.markdown("### 세부 보기")
    titles = ["(선택)"] + df["title"].tolist()
    sel = st.selectbox("본문/요약/키워드를 확인할 항목", options=titles, index=0)
    if sel != "(선택)":
        row = df[df["title"] == sel].iloc[0]
        st.markdown(f"**도메인**: {row.get('domain','')}  |  **시각**: {row.get('published_at','')}")
        st.markdown(f"**원문 링크**: {row.get('link','')}")
        if do_fetch_text:
            st.markdown("#### 본문")
            st.write(row.get("content", "") or "본문을 수집하지 못했습니다.")
        if do_summarize:
            st.markdown("#### 요약")
            st.write(row.get("summary", "") or "-")
        if do_keywords:
            st.markdown("#### 키워드")
            kw = row.get("keywords", []) or []
            st.write(", ".join(kw) if kw else "-")

    # CSV 다운로드 -----------------------------------------------------------
    st.markdown("---")
    st.subheader("결과 다운로드")
    csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "CSV로 다운로드",
        data=csv_bytes,
        file_name=f"{query}_web.csv",
        mime="text/csv",
        use_container_width=True,
    )

else:
    st.info("좌측 사이드바에서 키워드와 기간을 설정하고 **웹 검색 시작**을 눌러주세요.")
