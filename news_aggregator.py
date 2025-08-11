# -*- coding: utf-8 -*-
"""
울트라라이트 웹 검색/요약 유틸
- 의존성 최소화: newspaper3k / lxml / sklearn / kiwipiepy 제거
- DuckDuckGo 검색만 사용 (duckduckgo_search)
- 요약: 간단 요약(앞 문장 n개)
- 키워드: 단순 빈도 기반
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

USER_AGENT = "Mozilla/5.0 (compatible; WebAggregator/ultralite; +https://example.com)"
REQUEST_TIMEOUT = 12

def _http_get(url: str) -> requests.Response:
    return requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)

def normalize_url(url: str) -> str:
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

# ----------------------------------------------------------------------------
# DuckDuckGo 검색
# ----------------------------------------------------------------------------
def _timelimit_from_dates(date_from: dt.date | None, date_to: dt.date | None) -> str | None:
    if not date_from:
        return None
    days = (dt.date.today() - date_from).days
    if days <= 1:
        return "d"
    if days <= 7:
        return "w"
    if days <= 31:
        return "m"
    return "y"

def search_web(query: str, max_results: int = 50,
               date_from: dt.date | None = None,
               date_to: dt.date | None = None):
    timelimit = _timelimit_from_dates(date_from, date_to)
    out = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, safesearch="moderate", timelimit=timelimit, max_results=max_results):
            title = html.unescape(r.get("title") or "")
            link = normalize_url(r.get("href") or "")
            body = r.get("body") or ""
            date_str = r.get("date") or ""
            dt_parsed = parse_date(date_str)
            out.append({
                "id": item_hash(title, link),
                "title": title,
                "link": link,
                "snippet": body,
                "domain": extract_domain(link),
                "published_at": to_iso(dt_parsed) if dt_parsed else None,
                "source": "duckduckgo",
            })
    # 2차 날짜 필터
    if date_from or date_to:
        def in_range(rec):
            if not (date_from or date_to):
                return True
            d = parse_date(rec.get("published_at"))
            if not d:
                return True
            d = d.date()
            if date_from and d < date_from: return False
            if date_to and d > date_to: return False
            return True
        out = [x for x in out if in_range(x)]
    # 정렬
    out.sort(key=lambda x: parse_date(x.get("published_at")) or dt.datetime.min, reverse=True)
    return out

# ----------------------------------------------------------------------------
# 본문/요약/키워드 (경량)
# ----------------------------------------------------------------------------
def fetch_full_text(url: str) -> str:
    # 울트라라이트: 본문 수집 비활성화 (빈 문자열 반환)
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
        return ""
    return " ".join(sents[:max_sentences])

_KO_STOPWORDS = set("""
그리고 그러나 하지만 또한 또는 그래서 이런 저런 그냥 매우 너무 상당히 더욱 더욱이 바로 이미 또한
이것 그것 저것 여기 저기 우리 여러분 등의 등 등등 변화 대한 관련 관련해 대해서 경우 통해 대해
""".split())

def extract_keywords_ko(text: str, top_k: int = 20) -> list[str]:
    if not text:
        return []
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", text)
    freq = {}
    for w in words:
        wl = w.lower()
        if wl in _KO_STOPWORDS:
            continue
        freq[wl] = freq.get(wl, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:top_k]]

def enrich_with_content(items: list[dict], do_fetch_text=True, do_summarize=True, do_keywords=True,
                        summary_sentences=3):
    enriched = []
    for it in items:
        rec = dict(it)
        text = ""
        if do_fetch_text:
            text = fetch_full_text(rec["link"])  # 현재는 항상 ""
            rec["content"] = text
        if do_summarize:
            rec["summary"] = summarize_text(text, max_sentences=summary_sentences) if text else ""
        if do_keywords:
            rec["keywords"] = extract_keywords_ko(text, top_k=20) if text else []
        enriched.append(rec)
    return enriched

def dedupe_and_sort(items: list[dict]):
    uniq = {}
    for it in items:
        key = (normalize_url(it.get("link") or ""), (it.get("title") or "").strip().lower())
        if key not in uniq:
            uniq[key] = it
    arr = list(uniq.values())
    arr.sort(key=lambda x: parse_date(x.get("published_at")) or dt.datetime.min, reverse=True)
    return arr

def filter_by_domains(items: list[dict], allow_domains: list[str] | None):
    if not allow_domains:
        return items
    allow = {d.lower().strip() for d in allow_domains if d.strip()}
    return [it for it in items if (it.get("domain","").lower() in allow)]
