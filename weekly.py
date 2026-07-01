"""주간 리포트 생성 — 지난주(월~일) 요약을 web/reports.json 에 누적.

수집기가 매 실행 시 호출한다. 완료된 주(月요일 기준)가 아직 기록에 없으면 추가한다.
최초엔 최근 몇 주를 백필해 바로 볼 내용을 만든다. Gemini 불필요(기존 감성 사용).

단독 실행: python weekly.py  → web/data.json 을 읽어 web/reports.json 갱신
"""

from __future__ import annotations

import datetime
import json
import os
from collections import Counter

_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(_DIR, "web", "data.json")
REPORTS_PATH = os.path.join(_DIR, "web", "reports.json")
BACKFILL_WEEKS = 8


def _monday_of(d: datetime.date) -> datetime.date:
    return d - datetime.timedelta(days=d.weekday())


def week_label(monday: datetime.date) -> str:
    w = (monday.day - 1) // 7 + 1
    return f"{monday.year}년 {monday.month}월 {w}주차"


def _in(records, s, e):
    return [m for m in records if m.get("date") and s <= m["date"] <= e]


def build_report(records, start: datetime.date, end: datetime.date, prev_total: int) -> dict:
    s, e = start.isoformat(), end.isoformat()
    wk = _in(records, s, e)
    total = len(wk)
    sent = Counter(m["sentiment"] for m in wk)
    ch = Counter(m["channel"] for m in wk)
    kw = Counter(m["keyword"] for m in wk if m.get("keyword") and m["keyword"] != "기타")
    top = sorted(wk, key=lambda m: m.get("engagement", 0) or 0, reverse=True)[:3]
    wow = None if not prev_total else round((total - prev_total) / prev_total * 100, 1)
    pos, neg = sent.get("긍정", 0), sent.get("부정", 0)
    wow_txt = ""
    if wow is not None:
        wow_txt = f" (전주 대비 {'+' if wow >= 0 else ''}{wow}%)"
    summary = (f"'메리츠 파트너스' 언급 {total}건{wow_txt}. "
               f"긍정 {pos}건·부정 {neg}건. "
               f"주요 채널 {ch.most_common(1)[0][0] if ch else '-'}.")
    return {
        "week": week_label(start), "start": s, "end": e,
        "total": total, "wow": wow,
        "sentiment": {k: sent.get(k, 0) for k in ["긍정", "중립", "부정"]},
        "channels": ch.most_common(6),
        "keywords": kw.most_common(6),
        "top_posts": [{
            "title": (m.get("title") or "")[:90], "platform": m["channel"],
            "engagement": m.get("engagement", 0) or 0, "url": m.get("url", ""),
            "sentiment": m["sentiment"],
        } for m in top],
        "summary": summary,
    }


def update_weekly_reports(records, today: datetime.date | None = None) -> int:
    today = today or datetime.date.today()
    reports = []
    if os.path.exists(REPORTS_PATH):
        with open(REPORTS_PATH, encoding="utf-8") as f:
            reports = json.load(f)
    have = {r["start"] for r in reports}
    cur_mon = _monday_of(today)
    added = 0
    for k in range(1, BACKFILL_WEEKS + 1):
        mon = cur_mon - datetime.timedelta(days=7 * k)
        if mon.isoformat() in have:
            continue
        sun = mon + datetime.timedelta(days=6)
        pmon, psun = mon - datetime.timedelta(days=7), mon - datetime.timedelta(days=1)
        prev_total = len(_in(records, pmon.isoformat(), psun.isoformat()))
        rep = build_report(records, mon, sun, prev_total)
        if rep["total"] == 0:
            continue  # 데이터 없던 주는 건너뜀
        reports.append(rep)
        added += 1
    reports.sort(key=lambda r: r["start"], reverse=True)
    with open(REPORTS_PATH, "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False)
    return added


if __name__ == "__main__":
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    n = update_weekly_reports(data["mentions"])
    print(f"[weekly] {n}개 주간 리포트 추가 → {REPORTS_PATH}")
