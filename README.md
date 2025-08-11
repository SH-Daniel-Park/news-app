# 🌐 키워드 웹 검색/요약 대시보드 (울트라라이트)

의존성을 최소화하여 Streamlit Cloud에서 설치 실패를 최대한 피한 버전입니다.
- 본문 수집/요약/형태소 분석 기능은 기본 비활성화 (필요 시 표준/고정 버전 사용)
- DuckDuckGo 검색 + 결과 표/CSV + 링크 표시

## 실행
```bash
pip install -r requirements.txt
streamlit run news_ui.py
```

## 배포
- `requirements.txt`와 `news_ui.py`를 레포 **루트**에 두고 배포하세요.
- 실패 시 Logs에서 첫 오류 줄(패키지명/버전)을 알려주시면 맞춤 조정해 드립니다.
