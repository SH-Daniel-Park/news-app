# -*- coding: utf-8 -*-
import pandas as pd
import streamlit as st
import datetime as dt

from news_aggregator import (
    search_web,
    dedupe_and_sort,
    filter_by_domains,
)

st.set_page_config(page_title="🌐 키워드 웹 검색/요약 대시보드 (RL Fix)", layout="wide")

st.title("🌐 키워드 웹 검색/요약 대시보드 (RL Fix)")
st.caption("DuckDuckGo 레이트리밋을 지수 백오프로 완화하고, Bing API(선택)를 폴백으로 지원합니다.")

with st.sidebar:
    st.header("검색 설정")
    query = st.text_input("검색 키워드", placeholder="예) 생성형 AI 보안 가이드, 반도체 시장 전망")
    max_results = st.slider("최대 결과 수", 10, 100, 40, step=10,
                            help="레이트리밋 완화를 위해 40~50 이하를 권장")

    st.markdown("---")
    st.subheader("기간")
    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("시작일", value=None)
    with col2:
        date_to = st.date_input("종료일", value=None)

    st.markdown("---")
    st.subheader("엔진")
    engine = st.selectbox("검색 엔진", options=["DuckDuckGo(무료)", "Bing(안정/키필요)"], index=0)
    bing_api_key = ""
    if engine.startswith("Bing"):
        bing_api_key = st.text_input("Bing API 키", type="password",
                                     help="Azure Bing Web Search API 키 입력 시 보다 안정적으로 작동합니다.")

    st.markdown("---")
    run = st.button("🔎 웹 검색 시작", use_container_width=True)

# 결과 캐시 (쿼리/기간/엔진별 15분 캐시)
@st.cache_data(show_spinner=False, ttl=900)
def _cached_search(query, max_results, date_from, date_to, engine, bing_api_key):
    eng = "bing" if engine.startswith("Bing") else "duckduckgo"
    return search_web(
        query=query,
        max_results=max_results,
        date_from=date_from or None,
        date_to=date_to or None,
        engine=eng,
        bing_api_key=bing_api_key or None,
    )

if run:
    if not query.strip():
        st.warning("키워드를 입력하세요.")
        st.stop()

    if date_from and date_to and date_from > date_to:
        st.warning("시작일이 종료일보다 늦습니다.")
        st.stop()

    with st.spinner("웹을 검색하고 있습니다..."):
        raw = _cached_search(query, max_results, date_from, date_to, engine, bing_api_key)

    if not raw:
        st.info("검색 결과가 없습니다. 키워드를 바꾸거나 기간을 넓혀보세요.\n\nBing API 키 사용도 고려해 보세요.")
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

    # URL은 'https://...' 문자열로 그대로 표시
    df_display = df[display_cols].copy()
    if "link" in df_display.columns:
        df_display["link"] = df_display["link"].astype(str)
    st.dataframe(df_display, use_container_width=True, height=520)

    st.markdown("---")
    st.subheader("결과 다운로드")
    csv_bytes = df_display.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("CSV로 다운로드", data=csv_bytes, file_name=f"{query}_web.csv",
                       mime="text/csv", use_container_width=True)

else:
    st.info("좌측 사이드바에서 키워드/기간을 설정하고 **웹 검색 시작**을 눌러주세요.\n\n"
            "레이트리밋이 잦다면 결과 수를 줄이거나, Bing API 키를 사용해 보세요.")
