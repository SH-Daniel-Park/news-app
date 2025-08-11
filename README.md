# 🌐 키워드 웹 검색/요약 대시보드 (Streamlit)

이 버전은 Streamlit Cloud 배포 시 `lxml`/`newspaper3k` ImportError를 피하기 위해
- Python 버전: **3.11** (runtime.txt)
- `lxml==4.9.3` 등 호환 버전 고정
- `newspaper3k` 불가 시에도 앱이 죽지 않도록 **안전 가드**를 추가
했습니다.

## 실행
```bash
pip install -r requirements.txt
streamlit run news_ui.py
```

## 배포 설정
- Repository: <your-id>/news-app
- Branch: main
- Main file path: news_ui.py
