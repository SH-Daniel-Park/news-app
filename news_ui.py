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
    do_summarize = st.checkbox("요약 생성", Tru_
