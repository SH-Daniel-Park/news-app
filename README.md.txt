# 📰 뉴스 키워드 검색기

이 앱은 키워드를 입력하면 여러 뉴스 소스에서 기사를 모아 보여주고, 본문까지 확인할 수 있는 웹앱입니다.

## 기능
- NewsAPI, Google News RSS, 한국 주요 언론사 RSS 수집
- 기사 중복 제거
- 기사 본문 크롤링 (newspaper3k)
- CSV 다운로드

## 설치 및 실행
```bash
pip install -r requirements.txt
streamlit run news_ui.py
