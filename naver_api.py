"""네이버 검색 API 수집 모듈 (블로그·카페·뉴스).

키 발급: https://developers.naver.com/apps  →  애플리케이션 등록  →
사용 API '검색' 추가  →  Client ID / Client Secret 획득.

mentions 스키마(date, channel, sentiment, title, snippet, url, author,
engagement, keyword)에 맞춰 DataFrame을 반환한다.

정확도 메모
- 카페 검색 결과는 작성일을 제공하지 않아 '수집일'로 채운다(추이 해석 시 주의).
- 좋아요·댓글 수(engagement)는 검색 API에서 제공하지 않아 0으로 둔다(YouTube 단계에서 확보).
- 감성은 규칙기반 분류(추정). 정밀 분석은 LLM 단계에서 교체.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime
from email.utils import parsedate_to_datetime

import pandas as pd

KEYWORD = "메리츠 파트너스"

ENDPOINTS = {
    "네이버 블로그": "https://openapi.naver.com/v1/search/blog.json",
    "네이버 카페": "https://openapi.naver.com/v1/search/cafearticle.json",
    "네이버 뉴스": "https://openapi.naver.com/v1/search/news.json",
}

# 규칙기반 감성 사전 (추정)
POS_WORDS = [
    "좋", "만족", "추천", "친절", "도움", "감사", "성공", "안정", "든든",
    "최고", "괜찮", "편하", "탄탄", "장점", "수월", "정착",
]
NEG_WORDS = [
    "사기", "별로", "후회", "실망", "압박", "손해", "환수", "주의", "조심",
    "빡", "힘들", "그만", "퇴사", "단점", "문제", "강요", "허위", "조심하",
]

_TAG_RE = re.compile(r"<[^>]+>")
_KW_RE = re.compile(r"(정착지원금|위촉|수수료|교육|리크루팅|자유출퇴근|인센티브|시책|연봉|후기|현실|수당|GA)")


def _clean(text: str) -> str:
    text = _TAG_RE.sub("", text or "")
    for a, b in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")]:
        text = text.replace(a, b)
    return text.strip()


def _classify_sentiment(text: str) -> str:
    pos = sum(text.count(w) for w in POS_WORDS)
    neg = sum(text.count(w) for w in NEG_WORDS)
    if neg > pos:
        return "부정"
    if pos > neg:
        return "긍정"
    return "중립"


def _extract_keyword(text: str) -> str:
    m = _KW_RE.search(text)
    return m.group(1) if m else "기타"


def _parse_date(item: dict, channel: str):
    if channel == "네이버 블로그" and item.get("postdate"):
        return datetime.strptime(item["postdate"], "%Y%m%d")
    if channel == "네이버 뉴스" and item.get("pubDate"):
        try:
            return parsedate_to_datetime(item["pubDate"]).replace(tzinfo=None)
        except Exception:
            pass
    # 카페 등 날짜 미제공 → 가짜 날짜를 만들지 않고 '미확인'(NaT) 처리
    return pd.NaT


_BLOG_LINK = re.compile(r"blog\.naver\.com/([^/?]+)/(\d+)")


def _blog_like_count(link: str) -> int:
    """블로그 글 1건의 공감수(좋아요)를 네이버 likeit API로 가져온다.

    검색 API엔 없지만, 글마다 이 내부 API를 호출하면 실제 공감수를 얻을 수 있다.
    실패 시 0.
    """
    m = _BLOG_LINK.search(link or "")
    if not m:
        return 0
    bid, log = m.group(1), m.group(2)
    q = urllib.parse.quote(f"BLOG[{bid}_{log}]")
    url = f"https://blog.like.naver.com/v1/search/contents?suffix=BLOG&q={q}"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": f"https://blog.naver.com/{bid}/{log}",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
        reactions = data.get("contents", [{}])[0].get("reactions", [])
        return sum(int(r.get("count", 0) or 0) for r in reactions)
    except Exception:
        return 0


def _attach_blog_engagement(df: pd.DataFrame) -> pd.DataFrame:
    """블로그 행에 공감수를 engagement로 채운다(병렬 호출)."""
    blog_mask = df["channel"] == "네이버 블로그"
    links = df.loc[blog_mask, "url"].tolist()
    if not links:
        return df
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        counts = list(ex.map(_blog_like_count, links))
    df.loc[blog_mask, "engagement"] = counts
    return df


def _request(url: str, client_id: str, client_secret: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_naver_mentions(
    client_id: str,
    client_secret: str,
    query: str = KEYWORD,
    sources: list[str] | None = None,
    max_per_source: int = 300,
) -> pd.DataFrame:
    """네이버 검색 API로 mentions DataFrame을 수집한다."""
    sources = sources or list(ENDPOINTS.keys())
    rows: list[dict] = []

    # 정확 구문 매칭(따옴표)으로 일반 '메리츠' 뉴스 혼입을 줄인다.
    exact_query = f'"{query}"'

    for channel in sources:
        endpoint = ENDPOINTS[channel]
        start = 1
        while start <= min(max_per_source, 1000):
            params = urllib.parse.urlencode(
                {"query": exact_query, "display": 100, "start": start, "sort": "date"}
            )
            data = _request(f"{endpoint}?{params}", client_id, client_secret)
            items = data.get("items", [])
            if not items:
                break
            for it in items:
                title = _clean(it.get("title", ""))
                desc = _clean(it.get("description", ""))
                blob = f"{title} {desc}"
                date_known = (
                    (channel == "네이버 블로그" and bool(it.get("postdate")))
                    or (channel == "네이버 뉴스" and bool(it.get("pubDate")))
                )
                rows.append(
                    {
                        "date": _parse_date(it, channel),
                        "date_known": date_known,
                        "channel": channel,
                        "sentiment": _classify_sentiment(blob),
                        "title": title,
                        "snippet": desc,
                        "url": it.get("link") or it.get("originallink") or "",
                        "author": it.get("bloggername") or it.get("cafename") or "",
                        "engagement": 0,
                        "keyword": _extract_keyword(blob),
                    }
                )
            start += 100

    if not rows:
        return pd.DataFrame(
            columns=["date", "date_known", "channel", "sentiment", "title",
                     "snippet", "url", "author", "engagement", "keyword"]
        )

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    # 관련성 필터: 제목·본문에 '메리츠 … 파트너스'가 함께 등장하는 행만 유지
    rel = re.compile(r"메리츠\s*파트너스")
    blob = (df["title"].fillna("") + " " + df["snippet"].fillna(""))
    df = df[blob.str.contains(rel)]

    df = df.drop_duplicates(subset=["url"]).sort_values("date").reset_index(drop=True)
    df = _attach_blog_engagement(df)  # 블로그 공감수 채우기
    return df
