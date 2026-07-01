"""LLM 감성분석 — Claude로 문맥 기반 긍정/중립/부정 분류.

규칙기반(단어 매칭)의 오분류(자사 긍정글이 '단점'·'주의' 같은 단어로 부정 처리되는 등)를
문맥·반어·부정문까지 고려해 정확히 분류한다.

- 모델: claude-opus-4-8 (구조화 출력으로 라벨 배열 강제)
- 25건씩 묶어 호출(호출 수 절감)
- 실패/키 없음 시 예외 → 호출부에서 규칙기반 폴백
"""

from __future__ import annotations

import anthropic

MODEL = "claude-opus-4-8"
CHUNK = 25
LABELS = {"긍정", "중립", "부정"}

SYSTEM = (
    "너는 한국어 커뮤니티 반응의 감성 분석기다. 각 글이 '메리츠 파트너스'(보험설계사 "
    "모집·부업 플랫폼)에 대해 보이는 태도를 긍정/중립/부정 중 하나로 분류한다.\n"
    "- 문맥·반어·부정문을 고려한다. 예: '별로 안 나쁘다'=긍정, '좋다고?(비꼼)'=부정.\n"
    "- '단점', '주의', '수수료' 같은 단어가 있어도 글 전체 태도가 우호적이면 긍정이다.\n"
    "- 정보성·질문·중립 서술은 중립.\n"
    "- 홍보/후기라도 실제로 우호적이면 긍정으로 본다.\n"
    "입력 순서와 동일한 순서로 라벨만 반환한다."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {"type": "string", "enum": ["긍정", "중립", "부정"]},
        }
    },
    "required": ["labels"],
    "additionalProperties": False,
}


def _classify_chunk(client: anthropic.Anthropic, texts: list[str]) -> list[str]:
    numbered = "\n".join(f"{i+1}. {t[:300]}" for i, t in enumerate(texts))
    import json

    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": f"다음 {len(texts)}개 글의 감성을 순서대로 분류하라.\n\n{numbered}",
        }],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    labels = json.loads(text)["labels"]
    # 길이 불일치 방어
    if len(labels) != len(texts):
        labels = (labels + ["중립"] * len(texts))[: len(texts)]
    return [l if l in LABELS else "중립" for l in labels]


def classify(texts: list[str]) -> list[str]:
    """텍스트 리스트 → 감성 라벨 리스트(같은 순서). ANTHROPIC_API_KEY 필요."""
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수
    out: list[str] = []
    for i in range(0, len(texts), CHUNK):
        out += _classify_chunk(client, texts[i : i + CHUNK])
    return out
