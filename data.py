"""데이터 레이어 — 커뮤니티 반응 수집·적재 경계.

지금은 합성(샘플) 데이터를 생성한다. 실데이터 연결 시 ``load_mentions()`` 만
교체하면 된다(네이버 검색 API → YouTube API → 크롤링 → Google Sheets 순).

mentions 스키마 (1행 = 1개 반응)
    date        : 작성일 (datetime)
    channel     : 수집 채널
    sentiment   : 긍정 / 중립 / 부정
    title       : 글/댓글 제목 또는 요약
    snippet     : 본문 일부
    url         : 원본 링크
    author      : 작성자/닉네임
    engagement  : 좋아요+댓글 등 반응 수
    keyword     : 대표 연관 키워드
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

KEYWORD = "메리츠 파트너스"

# 수집 채널 (가중치 = 언급량 비중)
CHANNELS = {
    "네이버 블로그": 0.30,
    "네이버 카페": 0.24,
    "네이버 뉴스": 0.08,
    "YouTube": 0.14,
    "디시인사이드": 0.09,
    "보배드림": 0.05,
    "인스타그램": 0.06,
    "X(트위터)": 0.04,
}

SENTIMENTS = ["긍정", "중립", "부정"]

# 보험설계사 모집(리크루팅) 맥락의 연관 키워드 + 채널/감성 성향
KEYWORDS = [
    "정착지원금", "위촉", "수수료", "교육", "리크루팅", "자유출퇴근",
    "인센티브", "시책", "연봉", "후기", "현실", "영업관리자", "GA", "수당",
]

# 감성별 제목 템플릿 (샘플 표현)
TITLE_TEMPLATES = {
    "긍정": [
        "{kw} 받고 메리츠 파트너스 정착 후기 (3개월차)",
        "메리츠 파트너스 교육 시스템 생각보다 탄탄하네요",
        "메리츠 파트너스 자유출퇴근 진짜라 만족 중",
        "이직 고민하다 메리츠 파트너스 왔는데 수당 괜찮음",
        "메리츠 파트너스 시책 챙겨주는 거 인정",
    ],
    "중립": [
        "메리츠 파트너스 {kw} 어떻게 되는지 아시는 분?",
        "메리츠 파트너스 vs 다른 GA 비교 질문드려요",
        "메리츠 파트너스 위촉 절차 정리해봤습니다",
        "메리츠 파트너스 설명회 다녀온 후기(정보)",
        "메리츠 파트너스 {kw} 조건 문의",
    ],
    "부정": [
        "메리츠 파트너스 {kw} 생각보다 빡세요 현실 공유",
        "메리츠 파트너스 영업 압박 있나요? 걱정됨",
        "메리츠 파트너스 수수료 구조 잘 알아보고 가세요",
        "메리츠 파트너스 {kw} 환수 조건 주의",
    ],
}


def _seeded_rng(seed_text: str) -> np.random.Generator:
    import hashlib

    seed = int(hashlib.sha256(seed_text.encode()).hexdigest(), 16) % 2**32
    return np.random.default_rng(seed)


def generate_sample_mentions(days: int = 90, n: int = 640) -> pd.DataFrame:
    """합성 커뮤니티 반응 데이터 생성 (결정적)."""
    rng = _seeded_rng(KEYWORD)

    end = date.today()
    start = end - timedelta(days=days - 1)
    all_dates = pd.date_range(start=start, end=end, freq="D")

    # 시간에 따라 언급량이 완만히 증가 + 주말 약간 하락 + 캠페인 스파이크 2회
    base = np.linspace(0.7, 1.4, len(all_dates))
    weekend = np.where(all_dates.dayofweek >= 5, 0.75, 1.0)
    spike = np.ones(len(all_dates))
    spike[int(len(all_dates) * 0.45)] = 2.6  # 캠페인/이슈 스파이크
    spike[int(len(all_dates) * 0.80)] = 2.1
    weights = base * weekend * spike
    weights = weights / weights.sum()

    day_idx = rng.choice(len(all_dates), size=n, p=weights)
    dates = all_dates[day_idx]

    channels = rng.choice(
        list(CHANNELS.keys()), size=n, p=list(CHANNELS.values())
    )

    # 채널별 감성 성향 (커뮤/익명일수록 부정 비중↑, 블로그/뉴스는 긍정·중립↑)
    sentiment_bias = {
        "네이버 블로그": [0.55, 0.35, 0.10],
        "네이버 카페": [0.40, 0.42, 0.18],
        "네이버 뉴스": [0.45, 0.48, 0.07],
        "YouTube": [0.42, 0.38, 0.20],
        "디시인사이드": [0.22, 0.40, 0.38],
        "보배드림": [0.25, 0.42, 0.33],
        "인스타그램": [0.62, 0.30, 0.08],
        "X(트위터)": [0.38, 0.37, 0.25],
    }
    sentiments = np.array(
        [rng.choice(SENTIMENTS, p=sentiment_bias[c]) for c in channels]
    )

    keywords = rng.choice(KEYWORDS, size=n)
    engagement = rng.integers(0, 320, size=n) + rng.integers(0, 40, size=n)

    titles, snippets, urls, authors = [], [], [], []
    for i in range(n):
        tmpl = TITLE_TEMPLATES[sentiments[i]]
        title = rng.choice(tmpl).format(kw=keywords[i])
        titles.append(title)
        snippets.append(
            f"...{KEYWORD} 관련해서 {keywords[i]} 부분을 중심으로 의견을 남겼습니다..."
        )
        urls.append(f"https://example.com/{channels[i]}/{i}")
        authors.append(f"user_{rng.integers(1000, 9999)}")

    df = pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "date_known": True,
            "channel": channels,
            "sentiment": sentiments,
            "title": titles,
            "snippet": snippets,
            "url": urls,
            "author": authors,
            "engagement": engagement,
            "keyword": keywords,
        }
    )
    return df.sort_values("date").reset_index(drop=True)


def _secret(*names: str) -> str | None:
    """st.secrets → 환경변수 순으로 값을 찾는다."""
    import os

    for name in names:
        try:
            import streamlit as st

            val = st.secrets.get(name)
            if val:
                return val
        except Exception:
            pass
        val = os.environ.get(name)
        if val:
            return val
    return None


def load_mentions() -> pd.DataFrame:
    """대시보드 데이터 진입점.

    네이버·YouTube API 키가 있으면 각각 수집해 합치고, 아무 키도 없으면
    샘플을 반환한다. 추후 크롤링·Google Sheets 적재본도 여기서 합친다.
    """
    frames: list[pd.DataFrame] = []
    sources: list[str] = []

    # 1) 네이버 (블로그·카페·뉴스)
    cid, secret = _secret("NAVER_CLIENT_ID"), _secret("NAVER_CLIENT_SECRET")
    if cid and secret:
        try:
            from naver_api import fetch_naver_mentions

            ndf = fetch_naver_mentions(cid, secret, query=KEYWORD)
            if not ndf.empty:
                frames.append(ndf)
                sources.append(f"네이버 {len(ndf):,}건")
        except Exception as exc:
            print(f"[naver_api] 수집 실패: {exc}")

    # 2) YouTube (영상 + 댓글)
    yt_key = _secret("YOUTUBE_API_KEY")
    if yt_key:
        try:
            from youtube_api import fetch_youtube_mentions

            ydf = fetch_youtube_mentions(yt_key, query=KEYWORD)
            if not ydf.empty:
                frames.append(ydf)
                sources.append(f"YouTube {len(ydf):,}건")
        except Exception as exc:
            print(f"[youtube_api] 수집 실패: {exc}")

    if frames:
        df = pd.concat(frames, ignore_index=True)
        df = df.drop_duplicates(subset=["url", "title"]).reset_index(drop=True)
        df.attrs["source"] = "실데이터 · " + " + ".join(sources) + " (감성 추정)"
        return df

    df = generate_sample_mentions()
    df.attrs["source"] = "샘플 데이터"
    return df
