"""무료 LLM 감성분석 — Google Gemini (gemini-2.5-flash, 무료 등급).

문맥·반어·부정문을 이해해 긍정/중립/부정을 분류한다(규칙기반 대비 정확).
GEMINI_API_KEY 환경변수 필요. 무료 등급 속도제한 대비 호출 간격·429 재시도 포함.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

MODEL = "gemini-2.5-flash"
CHUNK = 90          # 호출 수 최소화(무료 RPM 대비)
GAP_SEC = 7.0       # 호출 간격 ≤ ~8.5 RPM (무료 10 RPM 이하)
LABELS = {"긍정", "중립", "부정"}

SYSTEM = (
    "각 글이 '메리츠 파트너스'(보험설계사 모집·부업 플랫폼)에 대해 보이는 태도를 "
    "긍정/중립/부정 중 하나로 분류하라. 문맥·반어·부정문을 고려한다. "
    "'단점'·'주의'·'수수료' 같은 단어가 있어도 글 전체가 우호적이면 긍정이다. "
    "정보성·질문·단순 서술은 중립. 입력 순서와 동일한 순서로 라벨 배열만 반환하라."
)
_SCHEMA = {"type": "ARRAY", "items": {"type": "STRING", "enum": ["긍정", "중립", "부정"]}}


def _call(key: str, texts: list[str]) -> list[str]:
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"parts": [{"text": "\n".join(
            f"{i+1}. {t[:300]}" for i, t in enumerate(texts))}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _SCHEMA,
            "temperature": 0,
        },
    }
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{MODEL}:generateContent?key={key}")
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
            txt = r["candidates"][0]["content"]["parts"][0]["text"]
            labels = json.loads(txt)
            if len(labels) != len(texts):
                labels = (labels + ["중립"] * len(texts))[: len(texts)]
            return [l if l in LABELS else "중립" for l in labels]
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(5 * (attempt + 1))  # 속도제한 → 짧은 백오프
                continue
            raise  # 소진 시 상위에서 None 처리(다음 실행 재시도)
    raise RuntimeError("gemini 429 재시도 소진")


def classify(texts: list[str]) -> list:
    """텍스트 → 감성 라벨 리스트(같은 순서). 실패 청크는 None(다음 실행 재시도).

    무료 등급 한도로 일부 청크가 실패해도 성공분은 유지되고 작업은 중단되지 않는다.
    """
    key = os.environ["GEMINI_API_KEY"]
    out: list = []
    for i in range(0, len(texts), CHUNK):
        if i:
            time.sleep(GAP_SEC)
        chunk = texts[i : i + CHUNK]
        try:
            out += _call(key, chunk)
        except Exception as e:
            print(f"[gemini] 청크 실패(스킵, 다음 실행 재시도): {e}", file=sys.stderr)
            out += [None] * len(chunk)
    return out
