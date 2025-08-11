# 🌐 키워드 웹 검색/요약 대시보드 (Streamlit)

키워드와 기간을 입력하면 일반 웹을 검색하여 자료를 모으고,
선택 시 본문을 스크래핑하여 요약과 한글 키워드를 추출해 보여줍니다.

## 설치
```bash
pip install -r requirements.txt
```

## 실행
```bash
streamlit run news_ui.py
```
브라우저가 자동으로 열리지 않으면 `http://localhost:8501` 접속.

## 기능
- DuckDuckGo 기반 일반 웹 검색 (무료/키 불필요)
- 기간(시작/종료일) 필터
- 도메인 필터
- 본문 수집(newspaper3k) → 요약(TFIDF) → 한글 키워드(kiwipiepy) 추출
- 결과 테이블, 클릭 가능한 링크, CSV 다운로드

## 배포(Streamlit Cloud)
1) 이 폴더를 GitHub에 업로드 (예: `username/web-search-app`)
2) https://share.streamlit.io/deploy → **New app**
   - Repository: `username/web-search-app`
   - Branch: `main`
   - Main file path: `news_ui.py`
3) Deploy → 제공된 URL로 접속
