# -*- coding: utf-8 -*-
import io
import json
import pandas as pd
import streamlit as st
import datetime as dt

from news_aggregator import (
    collect_articles,
    enrich_with_content,
    filter_by_publishers,
    extract_domain,
    DEFAULT_RSS_FEEDS,
)

st.set_page_config(page_title="📰 뉴스 키워드 수집/요약 대시보드", layout="wide")
st.title("📰 뉴스 키워드 수집/요약 대시보드")
st.caption("키워드로 여러 언론 기사를 모아보고, 본문/요약/키워드를 함께 확인하세요.")

# --------------------------- 사이드바 ---------------------------
with st.sidebar:
    st.header("검색 설정")
    query = st.text_input("검색 키워드", placeholder="예) 재정정책, 반도체, 환율 급등")
    max_results = st.slider("최대 기사 수", 10, 300, 60, step=10)
    newsapi_key = st.text_input("NewsAPI 키 (선택)", type="password")

    st.markdown("---")
    st.subheader("기간(선택)")
    use_date_range = st.toggle("기간 필터 사용", value=False)
    start_date = end_date = None
    if use_date_range:
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("시작일", value=dt.date.today())
        with col2:
            end_date = st.date_input("종료일", value=dt.date.today())

    st.markdown("---")
    st.subheader("RSS 소스")
    use_default_rss = st.checkbox("샘플 기본 RSS 사용", True)
    uploaded_feeds = st.file_uploader("feeds.txt 업로드", type=["txt"])

    rss_feeds = []
    if use_default_rss:
        rss_feeds.extend(DEFAULT_RSS_FEEDS)
    if uploaded_feeds is not None:
        try:
            txt = uploaded_feeds.read().decode("utf-8", errors="ignore")
            for line in txt.splitlines():
                url = line.strip()
                if url and not url.startswith("#"):
                    rss_feeds.append(url)
        except Exception:
            st.warning("feeds.txt를 읽는 중 문제가 발생했습니다.")

    st.markdown("---")
    st.subheader("콘텐츠 처리")
    do_fetch_text = st.checkbox("기사 본문 수집 (크롤링)", True)
    do_summarize = st.checkbox("요약 생성", True)
    summary_len = st.slider("요약 문장 수", 2, 6, 3)
    do_keywords = st.checkbox("키워드(형태소) 추출", True)

    st.markdown("---")
    run = st.button("🔎 수집 시작", use_container_width=True)

# --------------------------- 실행 ---------------------------
if run:
    if not query.strip():
        st.warning("키워드를 입력하세요.")
        st.stop()

    with st.spinner("기사를 수집하고 있습니다..."):
        raw = collect_articles(
            query=query,
            max_results=max_results,
            newsapi_key=newsapi_key.strip() or None,
            rss_feeds=rss_feeds if rss_feeds else None,
        )

    if not raw:
        st.info("관련 기사를 찾지 못했습니다.")
        st.stop()

    publishers = sorted(list({(it.get("publisher") or extract_domain(it.get("link","")) or "").strip()
                              for it in raw if it.get("link")}))
    with st.expander("언론사/도메인 필터"):
        allow = st.multiselect("포함할 언론사/도메인", options=publishers, default=[])

    filtered = filter_by_publishers(raw, allow_publishers=allow)

    # 기간 필터
    def parse_date_iso(s):
        try:
            return pd.to_datetime(s, utc=True).date()
        except Exception:
            return None

    if use_date_range and (start_date or end_date):
        if start_date and end_date and end_date < start_date:
            start_date, end_date = end_date, start_date
        tmp = []
        for it in filtered:
            d = parse_date_iso(it.get("published_at"))
            ok = True
            if start_date and d and d < start_date:
                ok = False
            if end_date and d and d > end_date:
                ok = False
            if ok:
                tmp.append(it)
        filtered = tmp

    if not filtered:
        st.info("필터 조건에 맞는 기사가 없습니다.")
        st.stop()

    # 본문/요약/키워드
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

    df = pd.DataFrame(enriched)
    display_cols = ["title", "publisher", "published_at", "link"]
    if do_summarize:
        display_cols.append("summary")
    if do_keywords:
        display_cols.append("keywords")

    st.success(f"총 {len(df)}건의 기사를 확보했습니다.")
    st.dataframe(df[display_cols], use_container_width=True, height=520)

    # ---------------- Excel 다운로드 (제목만 클릭 가능) ----------------
    from io import BytesIO

    # 엑셀 데이터 준비: URL 컬럼을 명확히 'url'로
    df_excel = df.copy()
    if "link" in df_excel.columns:
        df_excel.rename(columns={"link": "url"}, inplace=True)

    # 엔진 선택
    engine = None
    try:
        import xlsxwriter
        engine = "xlsxwriter"
    except Exception:
        try:
            import openpyxl
            engine = "openpyxl"
        except Exception:
            engine = None

    if engine is None:
        st.error("xlsxwriter 또는 openpyxl이 필요합니다. requirements.txt에 추가 후 배포하세요.")
    else:
        output = BytesIO()
        with pd.ExcelWriter(output, engine=engine) as writer:
            # 데이터 먼저 기록 (TITLE은 화면과 동일)
            df_excel.to_excel(writer, index=False, sheet_name="results")
            ws = writer.sheets["results"]

            cols = list(df_excel.columns)
            title_idx = cols.index("title") if "title" in cols else None
            url_idx   = cols.index("url")   if "url" in cols else None

            # 제목만 클릭 가능하게 (url은 그대로 문자열 보존)
            if url_idx is not None and title_idx is not None:
                if engine == "xlsxwriter":
                    # xlsxwriter는 0-based, row 0은 헤더
                    for r, (title, url) in enumerate(zip(df_excel["title"], df_excel["url"]), start=1):
                        if pd.notna(url) and str(url).strip().startswith("http"):
                            ws.write_url(r, title_idx, str(url), string=str(title))
                else:
                    # openpyxl은 1-based
                    from openpyxl.styles import Font
                    for r, (title, url) in enumerate(zip(df_excel["title"], df_excel["url"]), start=2):
                        if pd.notna(url) and str(url).strip().startswith("http"):
                            cell = ws.cell(row=r, column=title_idx + 1)
                            cell.value = str(title)
                            cell.hyperlink = str(url)
                            cell.font = Font(color="0000EE", underline="single")

        output.seek(0)
        st.download_button(
            "엑셀(.xlsx)로 다운로드",
            data=output.getvalue(),
            file_name=f"{query}_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    # -------------------------------------------------------------------

else:
    st.info("좌측에서 키워드를 입력 후 수집 시작을 눌러주세요.")
