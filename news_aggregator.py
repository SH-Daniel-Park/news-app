#!/usr/bin/env python3
"""
news_aggregator.py

설명 (한국어):
키워드(또는 키워드 리스트)를 입력하면 여러 뉴스 소스(NewsAPI, Google News RSS, 사용자 지정 RSS 피드들)에서 관련 기사를 모아
중복 제거 후 정렬하여 출력하는 파이썬 프로그램입니다.

특징:
- NewsAPI (선택 사항): API 키를 넣으면 NewsAPI에서 기사 검색.
- Google News RSS: 키워드 검색을 RSS로 가져와서 기사 수집.
- 사용자 지정 RSS 피드: 사용자가 목록에 원하는 언론사 RSS를 추가 가능.
- 중복 제거: URL과 제목 유사도로 중복 제거.
- 출력: JSON, CSV 또는 콘솔 출력 가능.

사용법:
1) 필요한 패키지 설치:
   pip install -r requirements.txt
   requirements.txt 내용:
     requests
     feedparser
     python-dateutil

2) 실행 예시:
   python news_aggregator.py --query "재정정책" --max 50 --out results.json
   또는 NewsAPI 키 사용:
   python news_aggregator.py --query "코로나" --newsapi-key YOUR_KEY --out results.csv

주의:
- 일부 국내 언론사의 RSS URL은 변경될 수 있습니다. 필요하면 RSS 목록을 수정하세요.
- NewsAPI는 유료 요금제/요청 제한이 있습니다.

"""

import argparse
import requests
import feedparser
import json
import csv
import time
from datetime import datetime
from dateutil import parser as dateparser
from urllib.parse import quote_plus
from difflib import SequenceMatcher


# ----------------------------- 설정 (원하면 수정) -----------------------------
# 기본 RSS 피드 예시 (한국 주요 언론 — URL은 변동될 수 있으니 필요하면 수정)
DEFAULT_RSS_FEEDS = {
    "chosun": "http://www.chosun.com/site/data/rss/rss.xml",
    "joongang": "https://joongang.joins.com/rss/article/list.xml",
    "donga": "http://rss.donga.com/total.xml",
    "hani": "http://www.hani.co.kr/rss/" ,
    "yonhap": "https://www.yna.co.kr/rss/" ,
    "kbs": "http://feeds.kbs.co.kr/news",
    # 더 추가 가능
}

# Google News RSS 템플릿 (지역 및 언어 옵션 포함)
GOOGLE_NEWS_RSS_TEMPLATE = "https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"

SIMILARITY_THRESHOLD = 0.85  # 제목 유사도 임계값 (중복 판단)

# ----------------------------- 유틸리티 함수 -----------------------------

def similar(a: str, b: str) -> float:
    """두 문자열의 유사도 비율(0~1) 반환"""
    return SequenceMatcher(None, a, b).ratio()


def normalize_text(s: str) -> str:
    if not s:
        return ""
    return ' '.join(s.replace('\n', ' ').split()).strip().lower()


# ----------------------------- 수집 함수들 -----------------------------

def search_google_news_rss(query: str, max_results=50):
    """Google News RSS를 사용해 결과를 가져옴"""
    url = GOOGLE_NEWS_RSS_TEMPLATE.format(query=quote_plus(query))
    print(f"[GoogleNewsRSS] fetching: {url}")
    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries[:max_results]:
        title = entry.get('title', '')
        link = entry.get('link', '')
        summary = entry.get('summary', '')
        published = entry.get('published', entry.get('updated', ''))
        try:
            published_parsed = dateparser.parse(published) if published else None
        except Exception:
            published_parsed = None
        articles.append({
            'source': 'google_news_rss',
            'title': title,
            'link': link,
            'summary': summary,
            'published': published_parsed.isoformat() if published_parsed else None,
        })
    return articles


def fetch_from_rss_feeds(query: str, feeds: dict, max_per_feed=20):
    """주어진 RSS 피드 목록을 순회하며 query가 제목/요약에 포함된 항목을 수집"""
    found = []
    for name, url in feeds.items():
        try:
            print(f"[RSS] fetching {name} -> {url}")
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                title = entry.get('title', '')
                summary = entry.get('summary', '')
                link = entry.get('link', '')
                combined_text = (title + ' ' + summary).lower()
                if query.lower() in combined_text:
                    published = entry.get('published', entry.get('updated', ''))
                    try:
                        published_parsed = dateparser.parse(published) if published else None
                    except Exception:
                        published_parsed = None
                    found.append({
                        'source': name,
                        'title': title,
                        'link': link,
                        'summary': summary,
                        'published': published_parsed.isoformat() if published_parsed else None,
                    })
            time.sleep(0.2)  # 간단한 지연
        except Exception as e:
            print(f"  [WARN] RSS fetch error for {name}: {e}")
    return found


def search_newsapi(query: str, api_key: str, max_results=50):
    """NewsAPI.org를 사용해 기사 수집 (api_key 필요)"""
    if not api_key:
        return []
    url = 'https://newsapi.org/v2/everything'
    params = {
        'q': query,
        'pageSize': min(100, max_results),
        'language': 'ko',
        'sortBy': 'publishedAt',
        'apiKey': api_key,
    }
    print(f"[NewsAPI] querying NewsAPI for '{query}'")
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        articles = []
        for it in data.get('articles', [])[:max_results]:
            published = it.get('publishedAt')
            articles.append({
                'source': it.get('source', {}).get('name', 'newsapi'),
                'title': it.get('title'),
                'link': it.get('url'),
                'summary': it.get('description'),
                'published': published,
            })
        return articles
    except Exception as e:
        print(f"  [WARN] NewsAPI error: {e}")
        return []


# ----------------------------- 결과 통합 / 정렬 / 중복제거 -----------------------------

def dedupe_and_merge(lists_of_articles):
    merged = []
    seen_urls = set()

    for lst in lists_of_articles:
        for a in lst:
            if not a.get('link'):
                # 링크 없으면 제목으로 판단
                identifier = normalize_text(a.get('title', ''))
            else:
                identifier = a.get('link')

            if identifier in seen_urls:
                continue

            # 제목 유사도 기준으로 중복 검사
            is_dup = False
            for ex in merged:
                t1 = normalize_text(ex.get('title', ''))
                t2 = normalize_text(a.get('title', ''))
                if t1 and t2 and similar(t1, t2) >= SIMILARITY_THRESHOLD:
                    is_dup = True
                    # 더 최신 정보가 있으면 병합
                    try:
                        p_old = dateparser.parse(ex.get('published')) if ex.get('published') else None
                        p_new = dateparser.parse(a.get('published')) if a.get('published') else None
                        if p_new and (not p_old or p_new > p_old):
                            ex.update(a)
                    except Exception:
                        pass
                    break
            if is_dup:
                continue

            merged.append(a)
            if a.get('link'):
                seen_urls.add(a.get('link'))

    # 날짜순 정렬 (최신 -> 오래된)
    def sort_key(x):
        try:
            return dateparser.parse(x.get('published')) if x.get('published') else datetime.min
        except Exception:
            return datetime.min

    merged.sort(key=sort_key, reverse=True)
    return merged

# --------------- 함수 추가 -----------

#from newspaper3k import Article

def fetch_full_text(url):
    """기사 본문 텍스트 크롤링"""
    try:
        article = Article(url, language='ko')
        article.download()
        article.parse()
        return article.text
    except Exception as e:
        print(f"[WARN] 본문 수집 실패: {e}")
        return ""

# ----------------------------- 출력 함수 -----------------------------

def save_json(path, articles):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(articles)} articles to {path}")


def save_csv(path, articles):
    keys = ['source', 'title', 'link', 'summary', 'published']
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for a in articles:
            w.writerow({k: a.get(k, '') for k in keys})
    print(f"Saved {len(articles)} articles to {path}")


def print_console(articles, limit=20):
    for i, a in enumerate(articles[:limit]):
        print('-' * 80)
        print(f"[{i+1}] {a.get('title')}")
        print(f"source: {a.get('source')}")
        print(f"published: {a.get('published')}")
        print(f"link: {a.get('link')}")
        s = a.get('summary') or ''
        print(f"summary: {s[:400]}{'...' if len(s)>400 else ''}")
    print('-' * 80)
    print(f"Displayed {min(limit, len(articles))} of {len(articles)} articles")


# ----------------------------- 메인 -----------------------------

def main():
    p = argparse.ArgumentParser(description='키워드로 여러 언론사 기사를 모아오는 도구')
    p.add_argument('--query', '-q', required=True, help='검색 키워드 (따옴표 권장)')
    p.add_argument('--newsapi-key', help='(선택) NewsAPI.org API 키')
    p.add_argument('--max', type=int, default=100, help='최대 기사 수(전체)')
    p.add_argument('--out', help='출력 파일 (json/csv). 없으면 콘솔로 출력')
    p.add_argument('--feeds', help='사용자 RSS 피드 파일(.txt) — 각 줄에 name|url', default=None)
    args = p.parse_args()

    q = args.query
    results = []
    remaining = args.max

    # 1) NewsAPI (선택)
    if args.newsapi_key:
        na = search_newsapi(q, args.newsapi_key, max_results=remaining)
        results.append(na)
        remaining = max(0, remaining - len(na))

    # 2) Google News RSS
    if remaining > 0:
        g = search_google_news_rss(q, max_results=remaining)
        results.append(g)
        remaining = max(0, remaining - len(g))

    # 3) 사용자 또는 기본 RSS 피드
    feeds = DEFAULT_RSS_FEEDS.copy()
    if args.feeds:
        try:
            with open(args.feeds, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '|' in line:
                        name, url = line.split('|', 1)
                        feeds[name.strip()] = url.strip()
        except Exception as e:
            print(f"[WARN] feeds file error: {e}")
    if remaining > 0 and feeds:
        rr = fetch_from_rss_feeds(q, feeds, max_per_feed=20)
        results.append(rr)

    merged = dedupe_and_merge(results)

    # 출력
    if args.out:
        if args.out.lower().endswith('.json'):
            save_json(args.out, merged)
        elif args.out.lower().endswith('.csv'):
            save_csv(args.out, merged)
        else:
            print_console(merged)
    else:
        print_console(merged)


if __name__ == '__main__':
    main()
