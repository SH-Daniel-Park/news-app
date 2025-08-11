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
    st.subheader("PDF 한글 폰트(선택) 업로드")
    pdf_font_file = st.file_uploader("NotoSansKR 등 .ttf/.otf 업로드하면 PDF 한글 표시가 좋습니다.", type=["ttf", "otf"])

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

    # 화면 표시는 URL 제외
    display_cols = ["title", "publisher", "published_at"]
    if do_summarize:
        display_cols.append("summary")
    if do_keywords:
        display_cols.append("keywords")

    st.success(f"총 {len(df)}건의 기사를 확보했습니다.")
    st.dataframe(df[display_cols], use_container_width=True, height=520)

    # 내부 링크 시리즈(엑셀/PDf에서 제목 하이퍼링크 생성용)
    link_series = df["link"] if "link" in df.columns else pd.Series([""] * len(df))

    # ---------------- Excel 다운로드 (URL 컬럼 제외, 제목만 클릭 가능) ----------------
    from io import BytesIO

    df_excel = df[display_cols].copy()  # URL 안 넣음

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
            df_excel.to_excel(writer, index=False, sheet_name="results")
            ws = writer.sheets["results"]

            cols = list(df_excel.columns)
            title_idx = cols.index("title") if "title" in cols else None

            if title_idx is not None:
                if engine == "xlsxwriter":
                    for r, (title, url) in enumerate(zip(df_excel["title"], link_series), start=1):
                        if pd.notna(url) and str(url).strip().startswith("http"):
                            ws.write_url(r, title_idx, str(url), string=str(title))
                else:
                    from openpyxl.styles import Font
                    for r, (title, url) in enumerate(zip(df_excel["title"], link_series), start=2):
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

    # ---------------- PDF 다운로드 (URL 컬럼 제외, 제목만 링크) ---------
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except Exception:
        st.error("PDF 생성을 위해 reportlab 패키지가 필요합니다. requirements.txt에 reportlab을 추가하세요.")
    else:
        base_font_name = "Helvetica"
        if pdf_font_file is not None:
            try:
                font_bytes = pdf_font_file.read()
                font_name = "UserKoreanFont"
                import tempfile
                with tempfile.NamedTemporaryFile(delete=False, suffix="."+pdf_font_file.name.split(".")[-1]) as tf:
                    tf.write(font_bytes)
                    tmp_font_path = tf.name
                pdfmetrics.registerFont(TTFont(font_name, tmp_font_path))
                base_font_name = font_name
            except Exception:
                st.warning("업로드한 폰트를 등록하지 못했습니다. 기본 폰트로 진행합니다. (한글 표시가 깨질 수 있음)")

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            name="TitleLink",
            parent=styles["Normal"],
            fontName=base_font_name,
            fontSize=10,
            textColor=colors.HexColor("#1155cc"),
            underlineProportion=0.08,
            leading=14,
        )
        cell_style = ParagraphStyle(
            name="Cell",
            parent=styles["Normal"],
            fontName=base_font_name,
            fontSize=9,
            leading=12,
        )

        rows = []
        header = ["제목", "언론사", "발행시각"]  # URL 컬럼 제외
        rows.append(header)

        for idx, row in df.iterrows():
            title = str(row.get("title", ""))
            url = str(row.get("link", "")) if pd.notna(row.get("link")) else ""
            pub = str(row.get("publisher", ""))
            when = str(row.get("published_at", ""))

            if url.startswith("http"):
                title_para = Paragraph(f'<link href="{url}">{title}</link>', title_style)
            else:
                title_para = Paragraph(title, cell_style)

            pub_para = Paragraph(pub, cell_style)
            when_para = Paragraph(when, cell_style)

            rows.append([title_para, pub_para, when_para])

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=25, rightMargin=25, topMargin=20, bottomMargin=20)
        tbl = Table(rows, repeatRows=1, colWidths=[320, 160, 160])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f1f3f4")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#202124")),
            ("FONTNAME", (0,0), (-1,-1), base_font_name),
            ("FONTSIZE", (0,0), (-1,0), 10),
            ("FONTSIZE", (0,1), (-1,-1), 9),
            ("ALIGN", (2,1), (2,-1), "CENTER"),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#fafafa")]),
            ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#dfe1e5")),
        ]))

        story = [tbl]
        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()

        st.download_button(
            "PDF로 다운로드",
            data=pdf_bytes,
            file_name=f"{query}_results.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    # -------------------------------------------------------------------

else:
    st.info("좌측에서 키워드를 입력 후 수집 시작을 눌러주세요.")
