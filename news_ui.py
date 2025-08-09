# -*- coding: utf-8 -*-
import io
import json
import pandas as pd
import streamlit as st

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

# --- 입력 영역 (좌측 사이드바) -------------------------------------------------
with st.sidebar:
    st.header("검색 설정")
    query = st.text_input("검색 키워드", placeholder="예) 재정정책, 반도체, 환율 급등")
    max_results = st.slider("최대 기사 수", 10, 300, 60, step=10)
    newsapi_key = st.text_input("NewsAPI 키 (선택)", type="password")

    st.markdown("---")
    st.subheader("RSS 소스")
    use_default_rss = st.checkbox(
        "샘플 기본 RSS 사용",
        True,
        help="운영 시에는 최신 RSS 주소를 feeds.txt로 관리하는 것을 권장합니다."
    )
    uploaded_feeds = st.file_uploader("feeds.txt 업로드 (줄당 하나의 RSS URL)", type=["txt"])

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

# --- 수집 실행 ----------------------------------------------------------------
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
        st.info("관련 기사를 찾지 못했습니다. 키워드를 바꿔보거나 결과 수를 늘려보세요.")
        st.stop()

    # 언론사 필터 UI (수집 결과 기반)
    publishers = sorted(list({(it.get("publisher") or extract_domain(it["link"]) or "").strip()
                              for it in raw if it.get("link")}))
    with st.expander("언론사/도메인 필터"):
        allow = st.multiselect(
            "포함할 언론사 또는 도메인 선택 (미선택 시 전체)",
            options=publishers, default=[]
        )

    filtered = filter_by_publishers(raw, allow_publishers=allow)

    if not filtered:
        st.info("필터 조건에 맞는 기사가 없습니다. 필터를 비우거나 변경해 보세요.")
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

    # 표로 표시 -----------------------------------------------------------------
    df = pd.DataFrame(enriched)

    # 표시용 열 정리
    display_cols = ["title", "publisher", "published_at", "link"]
    if do_summarize:
        display_cols.append("summary")
    if do_keywords:
        display_cols.append("keywords")

    st.success(f"총 {len(df)}건의 기사를 확보했습니다.")

    # 🔗 링크를 클릭 가능하게: LinkColumn 사용 (한 번 클릭으로 새 탭 이동)
    st.dataframe(
        df[display_cols],
        use_container_width=True,
        height=520,
        column_config={
            "link": st.column_config.LinkColumn(
                "링크",
                display_text="바로가기"
            ),
            "title": st.column_config.TextColumn("제목", width="large"),
            "publisher": st.column_config.TextColumn("언론사"),
            "published_at": st.column_config.TextColumn("발행시각"),
            # summary/keywords는 자동 렌더링
        }
    )

    # 상세 보기 -----------------------------------------------------------------
    st.markdown("### 세부 기사 보기")
    titles = ["(선택)"] + df["title"].tolist()
    sel = st.selectbox("본문/요약/키워드를 확인할 기사", options=titles, index=0)
    if sel != "(선택)":
        row = df[df["title"] == sel].iloc[0]
        st.markdown(f"**언론사**: {row.get('publisher','')}  |  **발행**: {row.get('published_at','')}")
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

    # CSV 다운로드 ---------------------------------------------------------------
    st.markdown("---")
    st.subheader("결과 다운로드")
    csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "CSV로 다운로드",
        data=csv_bytes,
        file_name=f"{query}_news.csv",
        mime="text/csv",
        use_container_width=True,
    )

else:
    st.info("좌측 사이드바에서 키워드를 입력하고 **수집 시작**을 눌러주세요.")
