# -*- coding: utf-8 -*-
"""
웹 검색/요약 유틸 (Rate limit 대응 포함)
- 기본: DuckDuckGo (무료, 키 불필요) + 지수 백오프/재시도
- 옵션: Bing Web Search API (안정적, 유료 키 필요)
- 최소 의존성: streamlit, pandas, requests, dateutil, duckduckgo_search
"""

from __future__ import annotations
import re
import html
import time
import math
import hashlib
import datetime as dt
from typing import Optional, List
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from dateutil import parser as dtparser
from duckduckgo_search import DDGS, exceptions as ddg_exc
import requests

USER_AGENT = "Mozilla/5.0 (compatible; WebAggregator/rlfix; +https://example.com)"
REQUEST_TIMEOUT = 12

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

# ------------------------------------------------------------------------------
# DuckDuckGo with backoff
# ------------------------------------------------------------------------------

def _timelimit_from_dates(date_from: dt.date | None, date_to: dt.date | None) -> Optional[str]:
    if not date_from:
        return None
    days = (dt.date.today() - date_from).days
    if days <= 1: return "d"
    if days <= 7: return "w"
    if days <= 31: return "m"
    return "y"

def _ddg_text_with_backoff(keywords: str, max_results: int, timelimit: Optional[str],
                           max_attempts: int = 5, base_delay: float = 1.5):
    """
    DDG 호출 시 Rate limit(429) 대응: 지수 백오프 + 랜덤 지터.
    """
    attempt = 0
    last_err = None
    while attempt < max_attempts:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(
                    keywords, safesearch="moderate",
                    timelimit=timelimit, max_results=max_results
                ))
            return results
        except (ddg_exc.RatelimitException, ddg_exc.TimeoutException) as e:
            last_err = e
            delay = base_delay * (2 ** attempt) + (0.2 * attempt)
            time.sleep(delay)
            attempt += 1
        except Exception as e:
            last_err = e
            break
    # 실패 시 빈 리스트 반환 (상위에서 Bing 등으로 폴백 가능)
    return []

def search_web_duckduckgo(query: str, max_results: int = 50,
                          date_from: dt.date | None = None,
                          date_to: dt.date | None = None):
    # DDG는 큰 max_results에서 레이트리밋이 늘 발생 → 안전한 상한 적용
    safe_max = max(10, min(max_results, 50))
    timelimit = _timelimit_from_dates(date_from, date_to)

    rows = _ddg_text_with_backoff(query, safe_max, timelimit)
    out = []
    for r in rows:
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
            if not (date_from or date_to): return True
            d = parse_date(rec.get("published_at"))
            if not d: return True
            d = d.date()
            if date_from and d < date_from: return False
            if date_to and d > date_to: return False
            return True
        out = [x for x in out if in_range(x)]
    # 정렬
    out.sort(key=lambda x: parse_date(x.get("published_at")) or dt.datetime.min, reverse=True)
    return out

# ------------------------------------------------------------------------------
# Optional: Bing Web Search API (stable, paid/free tier)
# ------------------------------------------------------------------------------

def search_web_bing(query: str, api_key: str, max_results: int = 30,
                    date_from: dt.date | None = None, date_to: dt.date | None = None,
                    mkt: str = "ko-KR"):
    if not api_key:
        return []
    url = "https://api.bing.microsoft.com/v7.0/search"
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    params = {
        "q": query,
        "mkt": mkt,
        "count": min(50, max_results),
        "textDecorations": False,
        "textFormat": "Raw",
        # freshness: 'Day' | 'Week' | 'Month' — 근사치로만 적용
    }
    # freshness 힌트
    if date_from:
        days = (dt.date.today() - date_from).days
        if days <= 1: params["freshness"] = "Day"
        elif days <= 7: params["freshness"] = "Week"
        else: params["freshness"] = "Month"

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    web_pages = (data.get("webPages") or {}).get("value") or []
    out = []
    for it in web_pages[:max_results]:
        title = it.get("name") or ""
        link = normalize_url(it.get("url") or "")
        snippet = it.get("snippet") or ""
        date_hint = it.get("dateLastCrawled") or ""
        dt_parsed = parse_date(date_hint)
        out.append({
            "id": item_hash(title, link),
            "title": title,
            "link": link,
            "snippet": snippet,
            "domain": extract_domain(link),
            "published_at": to_iso(dt_parsed) if dt_parsed else None,
            "source": "bing",
        })
    # 정렬
    out.sort(key=lambda x: parse_date(x.get("published_at")) or dt.datetime.min, reverse=True)
    return out

# ------------------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------------------

def search_web(query: str, max_results: int = 50,
               date_from: dt.date | None = None,
               date_to: dt.date | None = None,
               engine: str = "duckduckgo",
               bing_api_key: str | None = None):
    engine = (engine or "duckduckgo").lower()
    if engine == "bing" and bing_api_key:
        return search_web_bing(query, api_key=bing_api_key, max_results=max_results,
                               date_from=date_from, date_to=date_to)
    # 기본: DDG
    return search_web_duckduckgo(query, max_results=max_results,
                                 date_from=date_from, date_to=date_to)

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
