"""YouTube Data API v3 수집 모듈 (영상 + 댓글).

키 발급: https://console.cloud.google.com  →  프로젝트 생성  →
'YouTube Data API v3' 사용 설정  →  사용자 인증 정보 → API 키.

영상과 댓글을 모두 '커뮤니티 반응'으로 수집한다. 네이버와 달리
좋아요·댓글 수(engagement)를 제공한다.

mentions 스키마(date, date_known, channel, sentiment, title, snippet,
url, author, engagement, keyword)에 맞춰 DataFrame을 반환한다.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

import pandas as pd

KEYWORD = "메리츠 파트너스"
API = "https://www.googleapis.com/youtube/v3"

# naver_api와 동일한 규칙기반 감성/키워드 로직 재사용
from naver_api import _classify_sentiment, _clean, _extract_keyword  # noqa: E402

_REL = re.compile(r"메리츠\s*파트너스")


def _get(path: str, params: dict) -> dict:
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _iso(dt: str) -> pd.Timestamp:
    return pd.to_datetime(dt).tz_localize(None)


def _search_videos(api_key: str, query: str, max_videos: int) -> list[str]:
    """검색어 관련 영상 ID 목록."""
    ids: list[str] = []
    page = None
    while len(ids) < max_videos:
        params = {
            "key": api_key, "part": "id", "q": query, "type": "video",
            "maxResults": 50, "order": "date",
        }
        if page:
            params["pageToken"] = page
        data = _get("search", params)
        ids += [it["id"]["videoId"] for it in data.get("items", [])
                if it.get("id", {}).get("videoId")]
        page = data.get("nextPageToken")
        if not page:
            break
    return ids[:max_videos]


def _video_details(api_key: str, video_ids: list[str]) -> list[dict]:
    """영상 메타 + 통계 (관련성 필터 적용)."""
    rows: list[dict] = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        data = _get("videos", {
            "key": api_key, "part": "snippet,statistics", "id": ",".join(chunk),
        })
        for it in data.get("items", []):
            sn = it.get("snippet", {})
            stt = it.get("statistics", {})
            title = _clean(sn.get("title", ""))
            desc = _clean(sn.get("description", ""))
            if not _REL.search(f"{title} {desc}"):
                continue
            likes = int(stt.get("likeCount", 0) or 0)
            comments = int(stt.get("commentCount", 0) or 0)
            rows.append({
                "date": _iso(sn.get("publishedAt")),
                "date_known": True,
                "channel": "YouTube",
                "sentiment": _classify_sentiment(f"{title} {desc}"),
                "title": title,
                "snippet": desc[:200],
                "url": f"https://www.youtube.com/watch?v={it['id']}",
                "author": _clean(sn.get("channelTitle", "")),
                "engagement": likes + comments,
                "keyword": _extract_keyword(f"{title} {desc}"),
                "_video_id": it["id"],
            })
    return rows


def _comments(api_key: str, video_id: str, video_url: str, limit: int) -> list[dict]:
    """영상의 상위 댓글 (반응)."""
    rows: list[dict] = []
    page = None
    while len(rows) < limit:
        params = {
            "key": api_key, "part": "snippet", "videoId": video_id,
            "maxResults": 100, "order": "relevance", "textFormat": "plainText",
        }
        if page:
            params["pageToken"] = page
        try:
            data = _get("commentThreads", params)
        except Exception:
            break  # 댓글 사용 중지된 영상 등
        for it in data.get("items", []):
            c = it["snippet"]["topLevelComment"]["snippet"]
            text = _clean(c.get("textDisplay", ""))
            rows.append({
                "date": _iso(c.get("publishedAt")),
                "date_known": True,
                "channel": "YouTube 댓글",
                "sentiment": _classify_sentiment(text),
                "title": text[:80],
                "snippet": text[:300],
                "url": video_url,
                "author": _clean(c.get("authorDisplayName", "")),
                "engagement": int(c.get("likeCount", 0) or 0),
                "keyword": _extract_keyword(text),
            })
        page = data.get("nextPageToken")
        if not page:
            break
    return rows[:limit]


def fetch_youtube_mentions(
    api_key: str,
    query: str = KEYWORD,
    max_videos: int = 60,
    comments_per_video: int = 80,
) -> pd.DataFrame:
    """YouTube 영상 + 댓글을 mentions DataFrame으로 수집."""
    video_ids = _search_videos(api_key, query, max_videos)
    videos = _video_details(api_key, video_ids)

    rows: list[dict] = []
    for v in videos:
        vid = v.pop("_video_id")
        rows.append(v)
        rows += _comments(api_key, vid, v["url"], comments_per_video)

    cols = ["date", "date_known", "channel", "sentiment", "title", "snippet",
            "url", "author", "engagement", "keyword"]
    if not rows:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows)[cols]
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(subset=["url", "title"]).reset_index(drop=True)
    return df
