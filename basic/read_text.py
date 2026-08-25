"""글자 조각을 읽는다 — 상품당 AI 1콜. 단순형의 app.llm 어댑터를 그대로 빌려 쓴다.

읽기만 시킨다. 고쳐 쓰라고 하지 않는다. 강조는 **원본에서 색이 다르거나 굵은 글자**만
`**…**` 로 표시하게 한다 — 모델이 고르는 것이 아니라 원본을 옮기는 것이다.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.request
from pathlib import Path

PROMPT = """아래는 상품 상세페이지 이미지에서 잘라낸 글자 조각들이다. 번호 순서대로 **있는 그대로** 읽어라.

규칙
- 글자를 고치거나 보태거나 요약하지 마라. 오타도 그대로 둔다.
- 줄바꿈: 한 문단 안의 줄바꿈은 붙여서 한 줄로. 문단이 나뉘는 자리(빈 줄, 들여쓰기, 명백히 다른 단락)에만 빈 줄 하나.
- 강조: 원본에서 **글자색이 다르거나 굵은** 낱말·구절만 `**이렇게**` 감싼다. 원본에 강조가 없으면 감싸지 마라. 네가 고르지 마라.
- 읽을 수 없으면 "" 로.

돌려줄 것 — JSON 하나. 다른 말은 붙이지 마라.
{"texts": {"0": "…", "1": "…"}}
"""


def _png_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def _llm():
    """단순형의 어댑터를 가져온다. 저장소 뿌리를 길에 넣는 일은 여기 한 군데뿐이다."""
    import sys
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from app import llm
    return llm


def key_from_env() -> str:
    """--key 를 안 줬을 때 쓸 키. 없으면 빈 글자."""
    return _llm().key_from_env()


def read(key: str, crops: list[Path], timeout: int = 120) -> dict[str, str]:
    """crops 순서대로 읽어 {index: text}."""
    llm = _llm()

    parts: list[tuple[str, str]] = [("text", PROMPT)]
    for i, c in enumerate(crops):
        parts.append(("text", f"[{i}]"))
        parts.append(("image", _png_b64(c)))
    url, headers, body = llm.build(key, parts, max_tokens=6000)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.loads(r.read())
    text, _stop = llm.extract(key, payload)
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0)) if m else {}
    return {str(k): str(v) for k, v in (data.get("texts") or {}).items()}
