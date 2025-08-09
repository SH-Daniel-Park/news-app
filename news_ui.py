import streamlit as st
import pandas as pd
from news_aggregator import search_newsapi, search_google_news_rss, fetch_from_rss_feeds, dedupe_and_merge, DEFAULT_RSS_FEEDS, fetch_full_text

st.set_page_config(page_title="뉴스 키워드 검색기", layout="wide")

st.title("📰 뉴스 키워드 검색기")
st.write("키워드를 입력하면 여러 언론사/뉴스 소스에서 기사를 수집하고 본문도 볼 수 있습니다.")

query = st.text_input("검색 키워드 입력", placeholder="예: 재정정책")
max_results = st.slider("최대 기사 수", 10, 200, 50)
newsapi_key = st.text_input("NewsAPI API 키 (선택)", type="password")

if st.button("검색 시작"):
    if not query.strip():
        st.warning("키워드를 입력하세요.")
    else:
        results = []
        remaining = max_results

        if newsapi_key.strip():
            na = search_newsapi(query, newsapi_key, max_results=remaining)
            results.append(na)
            remaining = max(0, remaining - len(na))

        if remaining > 0:
            g = search_google_news_rss(query, max_results=remaining)
            results.append(g)
            remaining = max(0, remaining - len(g))

        if remaining > 0:
            rr = fetch_from_rss_feeds(query, DEFAULT_RSS_FEEDS, max_per_feed=20)
            results.append(rr)

        merged = dedupe_and_merge(results)

        if merged:
            st.success(f"{len(merged)}개의 기사를 찾았습니다.")
            df = pd.DataFrame(merged)
            selected = st.selectbox("본문을 보고 싶은 기사 선택", [""] + df["title"].tolist())

            if selected:
                link = df.loc[df["title"] == selected, "link"].values[0]
                st.markdown(f"[원문 보기]({link})")
                with st.spinner("본문 불러오는 중..."):
                    text = fetch_full_text(link)
                    st.write(text if text else "본문을 불러올 수 없습니다.")

            csv = df.to_csv(index=False, encoding="utf-8-sig")
            st.download_button("CSV로 다운로드", csv, file_name=f"{query}_news.csv", mime="text/csv")

            st.dataframe(df, use_container_width=True)
        else:
            st.warning("관련 기사를 찾지 못했습니다.")
