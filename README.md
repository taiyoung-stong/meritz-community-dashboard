# 메리츠 파트너스 · 커뮤니티 반응 대시보드

온라인 커뮤니티에서 "메리츠 파트너스" 키워드 언급을 수집·집계하는 Streamlit 대시보드.

- **게시글 탐색** — 개별 반응 검색·정렬·필터
- **인사이트 분석** — 언급량 추이·채널/감성 분포·연관 키워드·반응량

## 데이터 소스
- 네이버 검색 API (블로그·카페·뉴스)
- YouTube Data API v3 (영상·댓글)
- 키 미설정 시 샘플 데이터로 동작

## 로컬 실행
```bash
python -m venv .venv && .venv/Scripts/activate   # (Windows)
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## 시크릿 설정
`.streamlit/secrets.toml` (또는 Streamlit Cloud의 Secrets)에 아래를 등록:
```toml
NAVER_CLIENT_ID = "..."
NAVER_CLIENT_SECRET = "..."
YOUTUBE_API_KEY = "..."
```

> 감성·연관 키워드는 규칙기반(추정). engagement는 YouTube만 제공.
