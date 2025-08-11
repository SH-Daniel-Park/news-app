# -*- coding: utf-8 -*-
"""
뉴스 수집/정제/요약/형태소 분석 유틸리티
- Google News RSS + (선택) NewsAPI + (선택) 사용자 RSS 목록
- 언론사(도메인) 필터
- 본문 스크래핑(newspaper3k)
- 간단 요약(TF-IDF 문장선정) + 한글 형태소(kiwipiepy) 기반 키워드 추출
"""

from __future__ import annotations
import re
import time
import math
import json
import html
import hashlib
import datetime as dt
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import requests
import feedparser
from dateutil import parser as dtparser

# 본문 추출
# from newspaper import Article
# 
# 본문 추출: trafilatura 우선, 실패 시 간단 백업 절차
try:
    import trafilatura
    _has_trafilatura = True
except Exception:
    _has_trafilatura = False

from bs4 import BeautifulSoup
try:
    from readability import Document  # 백업용
except Exception:
    Document = None



# 요약/키워드
from sklearn.feature_extraction.text import TfidfVectorizer
import numpy as np

try:
    # 순수 파이썬, 설치 간편
    from kiwipiepy import Kiwi
    _kiwi = Kiwi()
except Exception:
    _kiwi = None  # 선택 기능 (설치 안 되어도 앱은 동작)


USER_AGENT = "Mozilla/5.0 (compatible; NewsAggregator/1.0; +https://example.com)"
REQUEST_TIMEOUT = 12

def _http_get(url: str) -> requests.Response:
    return requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)

def normalize_url(url: str) -> str:
    """URL 정규화 (스킴/호스트 소문자, 트래킹 파라미터 제거 등)"""
    try:
        p = urlparse(url)
        q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith(("utm_", "fbclid", "gclid", "icid"))]
        p2 = p._replace(
            scheme=p.scheme.lower() or "https",
            netloc=p.netloc.lower(),
            path=re.sub(r"/+$", "", p.path or ""),
            query=urlencode(q, doseq=True),
            fragment=""
        )
        return urlunparse(p2)
    except Exception:
        return url

def extract_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""

def parse_date(s):
    if not s:
        return None
    try:
        return dtparser.parse(s)
    except Exception:
        return None

def to_iso(ts):
    if isinstance(ts, dt.datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        return ts.astimezone(dt.timezone.utc).isoformat()
    return None



# --- 날짜 범위 필터링 (yymmdd ~ yymmdd, KST 기준) ------------------------------
import datetime as dt

def _parse_yymmdd(s: str) -> dt.datetime | None:
    try:
        d = dt.datetime.strptime(s.strip(), "%y%m%d")
        KST = dt.timezone(dt.timedelta(hours=9))
        return d.replace(tzinfo=KST)
    except Exception:
        return None

def filter_by_date_range(items: list[dict], start_yymmdd: str | None, end_yymmdd: str | None):
    """
    yymmdd ~ yymmdd 기간(KST)으로 기사 목록 필터
    - start_yymmdd만 주면 해당 날짜 00:00 이후
    - end_yymmdd만 주면 해당 날짜 23:59:59까지
    - 둘 다 없으면 원본 반환
    """
    if not start_yymmdd and not end_yymmdd:
        return items

    KST = dt.timezone(dt.timedelta(hours=9))
    start_kst = _parse_yymmdd(start_yymmdd) if start_yymmdd else None
    end_kst = _parse_yymmdd(end_yymmdd) if end_yymmdd else None
    if end_kst:
        end_kst = end_kst.replace(hour=23, minute=59, second=59, microsecond=999999)

    out = []
    for it in items:
        ts = parse_date(it.get("published_at"))
        if not ts:
            continue
        ts_kst = ts.astimezone(KST) if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc).astimezone(KST)
        if start_kst and ts_kst < start_kst:
            continue
        if end_kst and ts_kst > end_kst:
            continue
        out.append(it)
    return out
# -------------------------------------------------------------------------------

def item_hash(title: str, link: str) -> str:
    return hashlib.sha1((title or "" + "|" + normalize_url(link or "")).encode("utf-8")).hexdigest()

# --- 수집기들 -----------------------------------------------------------------

def search_google_news_rss(query: str, max_results: int = 50, lang="ko", region="KR"):
    """
    Google News RSS 기반 수집 (여러 언론사 기사 집계)
    - 장점: 별도 키 불필요, 다양한 매체
    - 단점: 품질/양은 시점에 따라 변동
    """
    # Google News RSS 검색 쿼리
    rss_url = (
        "https://news.google.com/rss/search?"
        f"q={requests.utils.quote(query)}&hl={lang}&gl={region}&ceid={region}:{lang}"
    )
    feed = feedparser.parse(rss_url)
    items = []
    for e in feed.entries[:max_results]:
        title = html.unescape(getattr(e, "title", "") or "")
        link = normalize_url(getattr(e, "link", "") or "")
        published = parse_date(getattr(e, "published", "") or "") or parse_date(getattr(e, "updated", "") or "")
        source_title = getattr(getattr(e, "source", None), "title", None) or ""
        publisher = source_title.strip() or extract_domain(link)
        items.append({
            "id": item_hash(title, link),
            "title": title,
            "link": link,
            "publisher": publisher,
            "published_at": to_iso(published),
            "source": "google_news_rss",
        })
    return items

def search_newsapi(query: str, api_key: str, max_results: int = 50, lang="ko"):
    """
    NewsAPI 수집 (선택)
    - https://newsapi.org
    - 무료 플랜 제약이 있으니 필요 시만 사용
    """
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "language": lang,
        "pageSize": min(100, max_results),
        "sortBy": "publishedAt",
    }
    headers = {"X-Api-Key": api_key}
    r = _http_get(url=url, )
    r = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    items = []
    for a in data.get("articles", [])[:max_results]:
        title = a.get("title") or ""
        link = normalize_url(a.get("url") or "")
        published = parse_date(a.get("publishedAt") or "")
        publisher = (a.get("source") or {}).get("name") or extract_domain(link)
        items.append({
            "id": item_hash(title, link),
            "title": html.unescape(title),
            "link": link,
            "publisher": publisher,
            "published_at": to_iso(published),
            "source": "newsapi",
        })
    return items

def fetch_from_rss_feeds(query: str, feeds: list[str], max_per_feed: int = 20):
    """
    사용자 제공 RSS 피드에서 키워드 매칭(제목/요약에 포함)으로 수집
    """
    items = []
    q = query.lower()
    for feed_url in feeds:
        try:
            fp = feedparser.parse(feed_url)
            for e in fp.entries[:max_per_feed]:
                title = html.unescape(getattr(e, "title", "") or "")
                summary = html.unescape(getattr(e, "summary", "") or "")
                if q not in (title + " " + summary).lower():
                    continue
                link = normalize_url(getattr(e, "link", "") or "")
                published = parse_date(getattr(e, "published", "") or "") or parse_date(getattr(e, "updated", "") or "")
                publisher = extract_domain(link) or (getattr(fp.feed, "title", "") or "").strip()
                items.append({
                    "id": item_hash(title, link),
                    "title": title,
                    "link": link,
                    "publisher": publisher,
                    "published_at": to_iso(published),
                    "source": "rss",
                })
        except Exception:
            continue
    return items

# 기본 RSS (샘플) — 실제 운영 시 최신 주소를 feeds.txt로 교체/보강하세요.
DEFAULT_RSS_FEEDS = [
    # 아래 목록은 예시입니다. 언론사 RSS 주소는 변동될 수 있으므로 feeds.txt로 관리 권장.
    "https://www.hankyung.com/feed/all",  # 한국경제 (예시)
    "https://www.mk.co.kr/rss/30000001/", # 매일경제 (예시)
    "https://www.koreatimes.co.kr/www/rss/rss.xml",  # 코리아타임스 (예시)
    "https://www.koreaherald.com/rss/020000000000.xml",  # 코리아헤럴드 (예시)
]

def dedupe_and_merge(list_of_lists: list[list[dict]]):
    """리스트 병합 + 중복 제거(정규화 URL/제목 기준) + 최신순 정렬"""
    merged = {}
    for lst in list_of_lists:
        for it in lst:
            key = normalize_url(it.get("link") or "") or it.get("id")
            title = (it.get("title") or "").strip().lower()
            dedupe_key = f"{key}::{title}"
            if dedupe_key not in merged:
                merged[dedupe_key] = it
    arr = list(merged.values())

    def _ts(x):
        d = parse_date(x.get("published_at"))
        # 없으면 최신으로 가정하지 않도록 아주 오래전 날짜 부여
        return d.timestamp() if d else 0.0

    arr.sort(key=_ts, reverse=True)
    return arr

# --- 본문/요약/키워드 ----------------------------------------------------------
def fetch_full_text(url: str) -> str:
    """
    기사 본문 텍스트 크롤링
    - 1순위: trafilatura (안정/정확)
    - 백업: requests + readability-lxml + BeautifulSoup
    """
    # 1) trafilatura 시도
    if _has_trafilatura:
        try:
            downloaded = trafilatura.fetch_url(url, no_ssl=True, user_agent=USER_AGENT, timeout=REQUEST_TIMEOUT)
            if downloaded:
                text = trafilatura.extract(
                    downloaded,
                    include_comments=False,
                    include_tables=False,
                    favor_recall=False,
                    url=url,
                )
                if text and text.strip():
                    return text.strip()
        except Exception:
            pass

    # 2) 백업: requests + readability + BS4
    try:
        r = _http_get(url)
        r.raise_for_status()
        html_txt = r.text
        if Document is not None:
            try:
                doc = Document(html_txt)
                content_html = doc.summary()
                soup = BeautifulSoup(content_html, "html.parser")
                text = soup.get_text("\n", strip=True)
                if text and len(text) > 120:  # 너무 짧으면 실패로 간주
                    return text
            except Exception:
                pass

        # 최후: 전체 HTML에서 텍스트만 추출
        soup = BeautifulSoup(html_txt, "html.parser")
        text = soup.get_text("\n", strip=True)
        return text[:5000]  # 너무 길어지는 것 방지
    except Exception:
        return ""

#def fetch_full_text(url: str) -> str:
#    """
#    기사 본문 텍스트 크롤링 (newspaper3k)
#    """
#    try:
#        art = Article(url, language='ko')
#        art.download()
#        art.parse()
#        text = (art.text or "").strip()
#        return text
#    except Exception:
#        return ""

#def _sent_tokenize_ko(text: str) -> list[str]:
    # 매우 단순한 한국어 문장분리 (정확도보다 경량 선호)
#    text = re.sub(r"\s+", " ", text).strip()
#    sents = re.split(r"(?<=[\.!?]|다\.)\s+", text)
    # 너무 짧은 문장 제거
#    return [s.strip() for s in sents if len(s.strip()) >= 10]

def _sent_tokenize_ko(text: str) -> list[str]:
    # 매우 단순한 한국어 문장분리 (정확도보다 경량 선호)
    text = re.sub(r"\s+", " ", text).strip()
    MARK = "§¶§"  # 거의 안 나올 구분자
    # 문장 끝 패턴 뒤에 구분자 삽입
    text = re.sub(r"(다\.|[.!?])\s+", r"\1" + MARK, text)
    sents = [s.strip() for s in text.split(MARK)]
    # 너무 짧은 문장 제거
    return [s for s in sents if len(s) >= 10]



def summarize_text(text: str, max_sentences: int = 3) -> str:
    if not text:
        return ""
    sents = _sent_tokenize_ko(text)
    if not sents:
        return text[:200] + ("..." if len(text) > 200 else "")
    # TF-IDF로 각 문장 점수 → 상위 문장 조합
    vect = TfidfVectorizer(max_features=5000)
    X = vect.fit_transform(sents)
    scores = np.asarray(X.sum(axis=1)).ravel()
    idx = np.argsort(-scores)[:max_sentences]
    idx_sorted = sorted(idx)  # 원문 순서 유지
    return " ".join(sents[i] for i in idx_sorted)

_KO_STOPWORDS = set("""
그리고 그러나 하지만 또한 또는 그래서 이런 저런 그냥 매우 너무 상당히 더욱 더욱이 바로 이미 또한
이것 그것 저것 여기 저기 우리 여러분 등의 등 등등 변화 대한 관련 관련해 대해서 경우 통해 대해
""".split())

def extract_keywords_ko(text: str, top_k: int = 20) -> list[str]:
    if not text:
        return []
    if _kiwi is None:
        # 형태소 분석기가 없으면 단어 빈도 기반(띄어쓰기)
        words = re.findall(r"[가-힣A-Za-z0-9]{2,}", text)
        freq = {}
        for w in words:
            wl = w.lower()
            if wl in _KO_STOPWORDS:
                continue
            freq[wl] = freq.get(wl, 0) + 1
        return [w for w, _ in sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:top_k]]

    # 명사/고유명사 위주 추출
    tokens = _kiwi.tokenize(text)
    freq = {}
    for t in tokens:
        if t.tag in ("NNG", "NNP"):  # 일반명사/고유명사
            w = t.form.lower()
            if w in _KO_STOPWORDS or len(w) <= 1:
                continue
            freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:top_k]]

# --- 파이프라인 ---------------------------------------------------------------

def collect_articles(
    query: str,
    max_results: int = 50,
    newsapi_key: str | None = None,
    rss_feeds: list[str] | None = None,
):
    """
    수집 파이프라인: GoogleNewsRSS → NewsAPI(선택) → 사용자 RSS(선택)
    """
    results = []
    remain = max_results

    # Google News RSS
    g = search_google_news_rss(query, max_results=remain)
    results.append(g)
    remain = max(0, remain - len(g))

    # NewsAPI (선택)
    if remain > 0 and newsapi_key:
        try:
            n = search_newsapi(query, newsapi_key, max_results=remain)
            results.append(n)
            remain = max(0, remain - len(n))
        except Exception:
            pass

    # 사용자 RSS (선택)
    if remain > 0 and rss_feeds:
        r = fetch_from_rss_feeds(query, rss_feeds, max_per_feed=20)
        results.append(r)

    merged = dedupe_and_merge(results)
    return merged

def enrich_with_content(items: list[dict], do_fetch_text=True, do_summarize=True, do_keywords=True,
                        summary_sentences=3):
    """
    기사 본문/요약/키워드 추가
    """
    enriched = []
    for it in items:
        rec = dict(it)
        text = ""
        if do_fetch_text:
            text = fetch_full_text(rec["link"])
            rec["content"] = text
        if do_summarize:
            rec["summary"] = summarize_text(text, max_sentences=summary_sentences) if text else ""
        if do_keywords:
            rec["keywords"] = extract_keywords_ko(text, top_k=20) if text else []
        enriched.append(rec)
    return enriched

def filter_by_publishers(items: list[dict], allow_publishers: list[str] | None):
    """
    allow_publishers: 허용할 언론사/도메인 목록 (소문자 비교)
    """
    if not allow_publishers:
        return items
    allow = {p.lower().strip() for p in allow_publishers if p.strip()}
    out = []
    for it in items:
        pub = (it.get("publisher") or "").lower()
        dom = extract_domain(it.get("link") or "")
        if pub in allow or dom in allow:
            out.append(it)
    return out
