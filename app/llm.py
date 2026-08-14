"""문구를 읽고 다듬는 곳에만 붙는 얇은 어댑터.

변환기에서 모델을 쓰는 곳은 **한 군데**뿐이다 — 그림에 박힌 글자를 읽고 문구를
다듬는 자동채우기. 분할도 배치도 렌더도 API 를 쓰지 않는다. 그래서 회사를 갈아
끼우는 일이 이 파일 하나로 끝난다.

키 앞자리로 어디 것인지 안다. 사람이 고르게 하지 않는다 — 고르게 하면 키와
회사를 어긋나게 넣는 일이 반드시 생긴다.

    sk-ant-…   Anthropic
    그 밖       OpenAI

보내는 것과 받는 것이 회사마다 다르다. 다른 곳은 여기 네 가지뿐이다.

    주소 · 인증 헤더 · 그림을 싣는 모양 · 답을 꺼내는 자리
"""

from __future__ import annotations

import json
import os

ANTHROPIC = "anthropic"
OPENAI = "openai"

#: 회사마다의 기본 모델. `CONVERTER_MODEL` 로 덮어쓸 수 있다.
DEFAULT_MODEL = {
    ANTHROPIC: "claude-sonnet-5",
    OPENAI: "gpt-4o",
}

#: 환경변수에서 키를 찾을 때 보는 이름
ENV_KEYS = {ANTHROPIC: "ANTHROPIC_API_KEY", OPENAI: "OPENAI_API_KEY"}


def provider_of(key: str) -> str:
    """키 앞자리로 어디 것인지 가린다."""
    return ANTHROPIC if (key or "").strip().startswith("sk-ant-") else OPENAI


def key_from_env() -> str:
    """환경변수에 넣어 둔 키. 둘 다 있으면 Anthropic 을 먼저 본다."""
    for name in (ENV_KEYS[ANTHROPIC], ENV_KEYS[OPENAI]):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def model_for(provider: str) -> str:
    return os.environ.get("CONVERTER_MODEL", "").strip() or DEFAULT_MODEL[provider]


def build(key: str, parts: list[tuple[str, str]], max_tokens: int = 8000, legacy_cap: bool = False):
    """(주소, 헤더, 보낼 바이트) 를 만든다.

    parts 는 ("text", 글) 과 ("image", base64 PNG) 가 순서대로 섞인 목록이다.
    순서가 곧 뜻이다 — `#1` 다음에 그 그림, `#2` 다음에 그 그림.

    legacy_cap 은 OpenAI 쪽에서만 쓴다. 길이 상한 이름이 `max_completion_tokens`
    로 바뀌었는데 옛 모델은 그 이름을 모르고, 새 모델은 옛 이름을 거부한다.
    한쪽으로 보내 보고 거부당하면 다른 이름으로 다시 보낸다(server 쪽에서 처리).
    """
    provider = provider_of(key)
    model = model_for(provider)

    if provider == ANTHROPIC:
        content = [
            {"type": "text", "text": value}
            if kind == "text"
            else {"type": "image",
                  "source": {"type": "base64", "media_type": "image/png", "data": value}}
            for kind, value in parts
        ]
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": content}]}
        return (
            "https://api.anthropic.com/v1/messages",
            {"content-type": "application/json", "x-api-key": key,
             "anthropic-version": "2023-06-01"},
            json.dumps(body).encode(),
        )

    content = [
        {"type": "text", "text": value}
        if kind == "text"
        else {"type": "image_url", "image_url": {"url": "data:image/png;base64," + value}}
        for kind, value in parts
    ]
    body = {"model": model, "messages": [{"role": "user", "content": content}]}
    body["max_tokens" if legacy_cap else "max_completion_tokens"] = max_tokens
    return (
        "https://api.openai.com/v1/chat/completions",
        {"content-type": "application/json", "authorization": f"Bearer {key}"},
        json.dumps(body).encode(),
    )


def extract(key: str, payload: dict) -> tuple[str, str]:
    """답에서 (글, 멈춘 이유) 를 꺼낸다. 잘렸으면 이유가 그걸 말해 준다."""
    if provider_of(key) == ANTHROPIC:
        text = "".join(
            b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"
        )
        return text.strip(), str(payload.get("stop_reason") or "")

    choices = payload.get("choices") or [{}]
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):  # 조각으로 쪼개 오는 경우
        content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    return str(content or "").strip(), str(choices[0].get("finish_reason") or "")


def truncated(key: str, stop: str) -> bool:
    return stop in ("max_tokens", "length")


def label(key: str) -> str:
    return "Anthropic" if provider_of(key) == ANTHROPIC else "OpenAI"
