"""데이터 수집기 — 네이버 + YouTube 반응을 모아 web/public/data.json 으로 저장.

GitHub Actions가 주기적으로 실행한다. 기존 수집 코드(naver_api, youtube_api)를
그대로 재사용한다. 키는 환경변수에서 읽는다.

출력 data.json 구조:
{
  "generated_at": "2026-06-30T08:00:00Z",
  "keyword": "메리츠 파트너스",
  "source": "네이버 890건 + YouTube 296건",
  "mentions": [
    {"date": "2026-06-24" | null, "date_known": true,
     "channel": "...", "sentiment": "긍정|중립|부정",
     "title": "...", "snippet": "...", "url": "...",
     "author": "...", "engagement": 0, "keyword": "..."},
    ...
  ]
}
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

from naver_api import KEYWORD, fetch_naver_mentions

OUT_PATH = os.path.join(os.path.dirname(__file__), "web", "data.json")
SENT_CACHE_PATH = os.path.join(os.path.dirname(__file__), "web", "sentiment_cache.json")


def _apply_llm_sentiment(df: pd.DataFrame) -> pd.DataFrame:
    """URL 캐시를 활용해 새 글만 LLM으로 감성 분류하고 df.sentiment를 갱신.

    GEMINI_API_KEY(무료) 우선, 없으면 ANTHROPIC_API_KEY 사용.
    """
    if os.environ.get("GEMINI_API_KEY"):
        from sentiment_gemini import classify
    else:
        from sentiment_llm import classify

    cache: dict[str, str] = {}
    if os.path.exists(SENT_CACHE_PATH):
        with open(SENT_CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)

    todo = df[~df["url"].isin(cache.keys())]
    if not todo.empty:
        texts = (todo["title"].fillna("") + " " + todo["snippet"].fillna("")).tolist()
        labels = classify(texts)
        for url, lab in zip(todo["url"].tolist(), labels):
            cache[url] = lab
        print(f"[sentiment_llm] 신규 {len(todo)}건 분류 (캐시 총 {len(cache)})")
    else:
        print("[sentiment_llm] 신규 없음 (전부 캐시)")

    df["sentiment"] = df["url"].map(cache).fillna(df["sentiment"])
    # 캐시에서 현재 URL만 유지(무한 증식 방지)
    cache = {u: cache[u] for u in df["url"] if u in cache}
    with open(SENT_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    return df


def main() -> int:
    naver_id = os.environ.get("NAVER_CLIENT_ID")
    naver_secret = os.environ.get("NAVER_CLIENT_SECRET")
    yt_key = os.environ.get("YOUTUBE_API_KEY")

    frames: list[pd.DataFrame] = []
    parts: list[str] = []

    if naver_id and naver_secret:
        ndf = fetch_naver_mentions(naver_id, naver_secret, query=KEYWORD)
        if not ndf.empty:
            frames.append(ndf)
            parts.append(f"네이버 {len(ndf):,}건")
    else:
        print("[warn] NAVER 키 없음 — 네이버 건너뜀", file=sys.stderr)

    if yt_key:
        from youtube_api import fetch_youtube_mentions

        ydf = fetch_youtube_mentions(yt_key, query=KEYWORD)
        if not ydf.empty:
            frames.append(ydf)
            parts.append(f"YouTube {len(ydf):,}건")
    else:
        print("[warn] YOUTUBE 키 없음 — 유튜브 건너뜀", file=sys.stderr)

    if not frames:
        print("[error] 수집된 데이터 없음 (키 확인 필요)", file=sys.stderr)
        return 1

    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["url", "title"]).reset_index(drop=True)

    # LLM 감성분석 (키 있으면) — URL 캐시로 새 글만 분류
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"):
        try:
            df = _apply_llm_sentiment(df)
            parts.append("감성 LLM")
        except Exception as exc:
            print(f"[sentiment_llm] 실패, 규칙기반 유지: {exc}", file=sys.stderr)

    # 직렬화: 날짜 → 'YYYY-MM-DD' 또는 None
    df = df.sort_values("date", na_position="last")
    records = []
    for _, r in df.iterrows():
        d = r["date"]
        records.append(
            {
                "date": None if pd.isna(d) else pd.Timestamp(d).strftime("%Y-%m-%d"),
                "date_known": bool(r["date_known"]),
                "channel": r["channel"],
                "sentiment": r["sentiment"],
                "title": r["title"],
                "snippet": r["snippet"],
                "url": r["url"],
                "author": r["author"],
                "engagement": int(r["engagement"]),
                "keyword": r["keyword"],
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "keyword": KEYWORD,
        "source": " + ".join(parts),
        "count": len(records),
        "mentions": records,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    print(f"[ok] {len(records):,}건 → {OUT_PATH}  ({payload['source']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
