"""Vercel 서버리스 함수 — 단일 URL(블로그/카페/YouTube) 즉시 분석.

GET /api/analyze?url=<게시글 URL>
→ {platform, title, date, author, url, engagement, engagement_label,
    metrics:{...}, sentiment}

키는 Vercel 환경변수(NAVER_CLIENT_ID/SECRET, YOUTUBE_API_KEY)에서 읽는다.
YouTube만 키 필요, 네이버 공감/댓글(likeit·cafe-articleapi)은 키 불필요.
"""

from http.server import BaseHTTPRequestHandler
import datetime
import json
import os
import re
import urllib.parse
import urllib.request

POS = ["좋", "만족", "추천", "친절", "도움", "감사", "성공", "안정", "든든", "최고",
       "괜찮", "편하", "탄탄", "장점", "수월", "정착", "꿀", "대박"]
NEG = ["사기", "별로", "후회", "실망", "압박", "손해", "환수", "주의", "조심", "빡",
       "힘들", "그만", "퇴사", "단점", "문제", "강요", "허위"]


def _get(url, ref=None, limit=None):
    h = {"User-Agent": "Mozilla/5.0", "Referer": ref or "https://naver.com"}
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=8) as r:
        raw = r.read(limit) if limit else r.read()
    return raw.decode("utf-8", "ignore")


def _clean(t):
    t = re.sub(r"<[^>]+>", "", t or "")
    for a, b in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")]:
        t = t.replace(a, b)
    return t.strip()


def _sentiment_gemini(text, key):
    body = {
        "systemInstruction": {"parts": [{"text":
            "글이 '메리츠 파트너스'에 보이는 태도를 긍정/중립/부정으로 분류. "
            "문맥·반어·부정문 고려. 라벨만 반환."}]},
        "contents": [{"parts": [{"text": text[:500]}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {"type": "STRING", "enum": ["긍정", "중립", "부정"]},
            "temperature": 0,
        },
    }
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"gemini-2.5-flash:generateContent?key={key}")
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
    lab = json.loads(r["candidates"][0]["content"]["parts"][0]["text"])
    return lab if lab in ("긍정", "중립", "부정") else "중립"


def _sentiment(text):
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        try:
            return _sentiment_gemini(text, key)
        except Exception:
            pass
    p = sum(text.count(w) for w in POS)
    n = sum(text.count(w) for w in NEG)
    return "부정" if n > p else "긍정" if p > n else "중립"


def _yt_comments(vid, key, limit=20):
    try:
        u = "https://www.googleapis.com/youtube/v3/commentThreads?" + urllib.parse.urlencode(
            {"key": key, "part": "snippet", "videoId": vid, "maxResults": limit,
             "order": "relevance", "textFormat": "plainText"})
        d = json.loads(_get(u))
        out = []
        for it in d.get("items", []):
            s = it["snippet"]["topLevelComment"]["snippet"]
            out.append({"author": _clean(s.get("authorDisplayName", "")),
                        "text": _clean(s.get("textDisplay", "")),
                        "likes": int(s.get("likeCount", 0) or 0)})
        return out
    except Exception:
        return []  # 댓글 사용중지 등


def _youtube(vid):
    key = os.environ.get("YOUTUBE_API_KEY", "")
    u = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(
        {"key": key, "part": "snippet,statistics", "id": vid})
    it = json.loads(_get(u))["items"]
    if not it:
        raise ValueError("영상을 찾을 수 없습니다")
    sn, st = it[0]["snippet"], it[0].get("statistics", {})
    likes, cmts = int(st.get("likeCount", 0) or 0), int(st.get("commentCount", 0) or 0)
    views = int(st.get("viewCount", 0) or 0)
    title = _clean(sn.get("title", ""))
    return {
        "platform": "YouTube", "title": title,
        "date": (sn.get("publishedAt", "") or "")[:10] or None,
        "author": _clean(sn.get("channelTitle", "")),
        "engagement": likes + cmts, "engagement_label": "좋아요+댓글",
        "metrics": {"조회수": views, "좋아요": likes, "댓글": cmts},
        "sentiment": _sentiment(title + " " + _clean(sn.get("description", ""))),
        "comments": _yt_comments(vid, key),
    }


def _blog(bid, log):
    q = urllib.parse.quote(f"BLOG[{bid}_{log}]")
    likes = 0
    try:
        r = _get(f"https://blog.like.naver.com/v1/search/contents?suffix=BLOG&q={q}",
                 ref=f"https://blog.naver.com/{bid}/{log}")
        reactions = json.loads(r).get("contents", [{}])[0].get("reactions", [])
        likes = sum(int(x.get("count", 0) or 0) for x in reactions)
    except Exception:
        pass
    title, date = f"블로그 {bid}", None
    try:
        html = _get(f"https://blog.naver.com/PostView.naver?blogId={bid}&logNo={log}")
        m = re.search(r'og:title"?\s*content="([^"]+)"', html)
        if m:
            title = _clean(m.group(1))
        d = (re.search(r"se_publishDate[^>]*>\s*(20\d\d)\.\s*(\d{1,2})\.\s*(\d{1,2})", html)
             or re.search(r"(20\d\d)\.\s?(\d{1,2})\.\s?(\d{1,2})\.", html))
        if d:
            date = f"{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}"
    except Exception:
        pass
    return {
        "platform": "네이버 블로그", "title": title, "date": date, "author": bid,
        "engagement": likes, "engagement_label": "공감수",
        "metrics": {"공감": likes}, "sentiment": _sentiment(title),
        "comments": [],  # 네이버 블로그 댓글 API 미지원
    }


def _cafe(name, art):
    clubid = None
    try:
        html = _get(f"https://cafe.naver.com/{name}", limit=90000)
        m = re.search(r"club(?:id|Id)[\"'=: ]+(\d+)", html) or re.search(r'"cafeId":(\d+)', html)
        if m:
            clubid = m.group(1)
    except Exception:
        pass
    title, date, cmts, reads, comments = f"카페 {name}", None, 0, 0, []
    if clubid:
        try:
            r = _get(f"https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/{clubid}/articles/{art}",
                     ref=f"https://cafe.naver.com/{name}/{art}")
            res = json.loads(r).get("result", {})
            a = res.get("article", {})
            title = _clean(a.get("subject") or a.get("title") or title)
            cmts = int(a.get("commentCount", 0) or 0)
            reads = int(a.get("readCount", 0) or 0)
            ts = a.get("writeDate")
            if ts:
                date = datetime.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
            for c in (res.get("comments", {}) or {}).get("items", [])[:20]:
                comments.append({
                    "author": _clean((c.get("writer") or {}).get("nick") or c.get("writerNick") or ""),
                    "text": _clean(c.get("content") or ""),
                    "likes": int(c.get("likeCount", 0) or 0)})
        except Exception:
            pass
    return {
        "platform": "네이버 카페", "title": title, "date": date, "author": name,
        "engagement": cmts, "engagement_label": "댓글수",
        "metrics": {"댓글": cmts, "조회수": reads}, "sentiment": _sentiment(title),
        "comments": comments,
    }


def analyze(url):
    url = (url or "").strip()
    if not url:
        raise ValueError("URL을 입력하세요")

    # YouTube
    m = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([\w-]{11})", url)
    if m:
        return {**_youtube(m.group(1)), "url": url}

    # 네이버 블로그 — 경로형(/id/logno) 또는 쿼리형(?logNo=), m.blog 포함
    m = re.search(r"blog\.naver\.com/([^/?#]+)/(\d+)", url)
    if m:
        return {**_blog(m.group(1), m.group(2)), "url": url}
    mid = re.search(r"blog\.naver\.com/([^/?#]+)", url)
    mlog = re.search(r"[?&]logNo=(\d+)", url, re.I)
    if mid and mlog:
        return {**_blog(mid.group(1), mlog.group(1)), "url": url}

    # 네이버 카페 — 경로형 또는 쿼리형(?articleid=)
    m = re.search(r"cafe\.naver\.com/([^/?#]+)/(\d+)", url)
    if m:
        return {**_cafe(m.group(1), m.group(2)), "url": url}
    mcid = re.search(r"cafe\.naver\.com/([^/?#]+)", url)
    mart = re.search(r"[?&]articleid=(\d+)", url, re.I)
    if mcid and mart:
        return {**_cafe(mcid.group(1), mart.group(1)), "url": url}

    raise ValueError("지원하지 않는 URL (네이버 블로그·카페 또는 YouTube만 가능)")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = urllib.parse.urlparse(self.path).query
        url = urllib.parse.parse_qs(qs).get("url", [""])[0]
        try:
            result, code = analyze(url), 200
        except Exception as e:
            result, code = {"error": str(e)}, 400
        body = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
