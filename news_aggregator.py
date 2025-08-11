# -*- coding: utf-8 -*-
"""
일반 웹 검색 수집/정제/요약/형태소 분석 유틸리티
- 기본 엔진: DuckDuckGo(무료, 키 불필요)  → 키워드 & 기간 필터 지원
- (선택) Google CSE / Bing API 확장 가능 (키 입력 시)
- 도메인 필터
- 본문 스크래핑(newspaper3k, 실패 시 빈 문자열)
- 간단 요약(TF-IDF 문장선정) + 한글 형태소(kiwipiepy) 기반 키워드 추출
"""

from __future__ import annotations
import re
import html
import hashlib
import datetime as dt
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from dateutil import parser as dtparser
from duckduckgo_search import DDGS  # pip install duckduckgo_search
import requests

# 본문 추출
try:
    from newspaper import Article
except Exception:
    Article = None  # graceful fallback

# 요약/키워드
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
except Exception:
    TfidfVectorizer = None
import numpy as np

try:
    from kiwipiepy import Kiwi
    _kiwi = Kiwi()
except Exception:
    _kiwi = None  # 선택 기능

USER_AGENT = "Mozilla/5.0 (compatible; WebAggregator/1.0; +https://example.com)"
REQUEST_TIMEOUT = 12

def _http_get(url: str) -> requests.Response:
    return requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)

def normalize_url(url: str) -> str:
    """URL 정규화 (스킴/호스트 소문자 + 트래킹 파라미터 제거)"""
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

def item_hash(title: str, link: str) -> str:
    return hashlib.sha1((title or "" + "|" + normalize_url(link or "")).encode("utf-8")).hexdigest()

# ------------------------------------------------------------------------------
# 웹 검색 (DuckDuckGo 기본)
# ------------------------------------------------------------------------------

def _timelimit_from_dates(date_from: dt.date | None, date_to: dt.date | None) -> str | None:
    """
    DuckDuckGo의 timelimit(d, w, m, y) 근사치 계산.
    정확한 날짜 범위가 필요한 경우, timelimit으로 1차 제한 후 결과의 date를 2차 필터링.
    """
    if not date_from:
        return None
    delta = dt.date.today() - date_from
    days = delta.days
    if days <= 1:
        return "d"
    if days <= 7:
        return "w"
    if days <= 31:
        return "m"
    return "y"

def search_web_duckduckgo(query: str, max_results: int = 50,
                          date_from: dt.date | None = None,
                          date_to: dt.date | None = None):
    """
    DuckDuckGo 웹 검색 (일반 페이지).
    반환 필드: title, link, snippet, domain, published_at(있을 때)
    """
    timelimit = _timelimit_from_dates(date_from, date_to)
    out = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, safesearch="moderate", timelimit=timelimit, max_results=max_results):
            title = html.unescape(r.get("title") or "")
            link = normalize_url(r.get("href") or "")
            body = r.get("body") or ""
            date_str = r.get("date") or ""  # 있을 수도, 없을 수도
            dt_parsed = parse_date(date_str)
            rec = {
                "id": item_hash(title, link),
                "title": title,
                "link": link,
                "snippet": body,
                "domain": extract_domain(link),
                "published_at": to_iso(dt_parsed) if dt_parsed else None,
                "source": "duckduckgo",
            }
            out.append(rec)

    # 2차 필터: 명시적 날짜가 있으면 범위로 거르기
    if date_from or date_to:
        def in_range(rec):
            if not (date_from or date_to):
                return True
            d = parse_date(rec.get("published_at"))
            if not d:
                return True  # 날짜 없으면 일단 통과
            d_date = d.date()
            if date_from and d_date < date_from:
                return False
            if date_to and d_date > date_to:
                return False
            return True
        out = [x for x in out if in_range(x)]
    return out

# ------------------------------------------------------------------------------
# (선택) Google CSE / Bing API 확장 포인트
# ------------------------------------------------------------------------------

def search_web(query: str, max_results: int = 50,
               date_from: dt.date | None = None,
               date_to: dt.date | None = None,
               engine: str = "duckduckgo",
               **kwargs):
    """
    엔진 선택 래퍼. 현재는 duckduckgo만 기본 구현.
    필요 시 engine='google'/'bing' 처리 분기 추가 가능.
    """
    engine = (engine or "duckduckgo").lower()
    if engine == "duckduckgo":
        return search_web_duckduckgo(query, max_results=max_results,
                                     date_from=date_from, date_to=date_to)
    # TODO: google / bing 구현 시 kwargs(api_key 등) 활용
    return search_web_duckduckgo(query, max_results=max_results,
                                 date_from=date_from, date_to=date_to)

# ------------------------------------------------------------------------------
# 중복/정렬/필터
# ------------------------------------------------------------------------------

def dedupe_and_sort(items: list[dict]):
    """URL+제목 기반 중복 제거, (가능하면) 최신순 정렬"""
    uniq = {}
    for it in items:
        key = (normalize_url(it.get("link") or ""), (it.get("title") or "").strip().lower())
        if key not in uniq:
            uniq[key] = it
    arr = list(uniq.values())

    def _ts(x):
        d = parse_date(x.get("published_at"))
        return d.timestamp() if d else 0.0

    arr.sort(key=_ts, reverse=True)
    return arr

def filter_by_domains(items: list[dict], allow_domains: list[str] | None):
    """허용 도메인만 남김 (소문자 비교)"""
    if not allow_domains:
        return items
    allow = {d.lower().strip() for d in allow_domains if d.strip()}
    out = []
    for it in items:
        dom = (it.get("domain") or "").lower()
        if dom in allow:
            out.append(it)
    return out

# ------------------------------------------------------------------------------
# 본문/요약/키워드
# ------------------------------------------------------------------------------

def fetch_full_text(url: str) -> str:
    """일반 웹 페이지 본문 추출 시도"""
    try:
        if Article is None:
            return ""
        art = Article(url, language='ko')
        art.download()
        art.parse()
        text = (art.text or "").strip()
        return text
    except Exception:
        return ""

def _sent_tokenize_ko(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    sents = re.split(r"(?<=[\.!?]|다\.)\s+", text)
    return [s.strip() for s in sents if len(s.strip()) >= 10]

def summarize_text(text: str, max_sentences: int = 3) -> str:
    if not text:
        return ""
    sents = _sent_tokenize_ko(text)
    if not sents:
        return text[:200] + ("..." if len(text) > 200 else "")
    if TfidfVectorizer is None:
        # 간단한 대체: 앞에서부터 문장 몇 개 반환
        return " ".join(sents[:max_sentences])
    vect = TfidfVectorizer(max_features=5000)
    X = vect.fit_transform(sents)
    scores = np.asarray(X.sum(axis=1)).ravel()
    idx = np.argsort(-scores)[:max_sentences]
    idx_sorted = sorted(idx)
    return " ".join(sents[i] for i in idx_sorted)

_KO_STOPWORDS = set("""
그리고 그러나 하지만 또한 또는 그래서 이런 저런 그냥 매우 너무 상당히 더욱 더욱이 바로 이미 또한
이것 그것 저것 여기 저기 우리 여러분 등의 등 등등 변화 대한 관련 관련해 대해서 경우 통해 대해
""".split())

def extract_keywords_ko(text: str, top_k: int = 20) -> list[str]:
    if not text:
        return []
    if _kiwi is None:
        words = re.findall(r"[가-힣A-Za-z0-9]{2,}", text)
        freq = {}
        for w in words:
            wl = w.lower()
            if wl in _KO_STOPWORDS:
                continue
            freq[wl] = freq.get(wl, 0) + 1
        return [w for w, _ in sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:top_k]]

    tokens = _kiwi.tokenize(text)
    freq = {}
    for t in tokens:
        if t.tag in ("NNG", "NNP"):
            w = t.form.lower()
            if w in _KO_STOPWORDS or len(w) <= 1:
                continue
            freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:top_k]]

def enrich_with_content(items: list[dict], do_fetch_text=True, do_summarize=True, do_keywords=True,
                        summary_sentences=3):
    """본문/요약/키워드 추가"""
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
