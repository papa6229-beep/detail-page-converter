"""본문 밴드마다 **사실과 글**을 받는다 — 상품당 AI 1콜.

**자르기는 기계, 판단은 AI, 코드는 배치만.**

예전에는 픽셀로 제목·배지·옆글자를 판정했다. 밴드의 어두운 덩어리를 세고, 글줄
높이를 재고, 색 머리띠를 찾고, 사진 옆 글자를 떼어냈다. 상품이 하나 늘 때마다
그 잣대가 어긋났고, 어긋나는 방식이 매번 달랐다 — 무늬 있는 제품에서는 글자꼴이
60개로 세어지고, 광고 배너에서는 떼어낸 글자가 지워져 유령이 남았다.

지금은 **모델이 밴드를 보고 말한다.** 이건 제목이다, 이건 설명이고 글은 이렇다,
이건 사진이다, 이건 글자가 박힌 사진이라 통째로 써야 한다, 이건 장식이다.
코드는 그 말대로 놓기만 한다.

**아무것도 버리지 않는다.** 장식이라는 말도 "버려라" 가 아니라 "구간을 열지 마라"
라는 뜻이다 — 그림은 그대로 실린다. 예전에는 장식을 버렸고, 그래서 벨벳키스의
`SIZE & INFO` 배지가 페이지에서 통째로 사라졌다. 모델이 그 밴드를 title 이 아니라
decor 라고 불렀으니 "제목이면 글이 있어야 한다" 는 규칙은 볼 기회조차 없었다.
**버리는 길이 있으면 어떤 규칙도 그 앞을 못 막는다.** 그 길을 없앴다.

읽기는 읽기만 시킨다. 고쳐 쓰라고 하지 않는다. 강조는 **원본에서 색이 다르거나
굵은 글자**만 `**…**` 로 표시하게 한다 — 모델이 고르는 것이 아니라 원본을 옮기는 것이다.
"""
from __future__ import annotations

import base64
import io
import json
import re
import urllib.request
from pathlib import Path

#: 모델에 보낼 때 긴 변을 이만큼으로 줄인다. 글자는 살아 있고 전송은 안정된다.
SEND_PX = 900

PROMPT = """상품 상세페이지의 **본문**을 밴드로 잘라 번호 순서대로 보낸다.
밴드마다 **무엇인지** 말하고, 글이면 **그대로 읽어라.**

**먼저 이 순서로 물어라. 처음 "그렇다" 가 나오는 데서 멈춘다.**

    ① 이 밴드에 **제품 사진이 없고 글자뿐인가?**
       → 그렇다면 title 이나 body 다. **절대 photo 가 아니다.**
         한 줄짜리 머리글이면 title, 문단이면 body.
    ② 사진이 있는데 그 위나 옆에 **설명·라벨·번호·치수가 박혀 있는가?**
       → 그렇다면 shot 이다. 분홍 알약 라벨 하나만 얹혀 있어도 shot 이다.
    ③ 그 밖의 사진 → photo. 글자 없는 알약·구분선·푸터뿐이면 decor.

shot 밴드의 글은 여기서 읽지 않는다. **그 글은 따로 물어본다** — 우리가 글줄 자리를
짚어 보여 주고 그 안의 글만 읽힌다. 여기서는 shot 이라고 말해 주기만 하면 된다.

**종류 다섯 — 하나만 고른다**

    title   **제목**이다. 구간의 머리다. `01 제품특징` 처럼 번호가 붙어 있어도,
            색 판 위에 얹혀 있어도, 그림처럼 그려져 있어도 제목이면 title 이다.
    body    **설명 글**이다. 문단으로 읽힐 글이 밴드의 주인공이다.
    photo   **사진**이다. 글자가 **정말로 없는** 것만 photo 다. 워터마크와 제품에
            인쇄된 상표는 글자로 안 친다. 그 밖의 글자가 한 줄이라도 얹혀 있으면
            photo 가 아니라 shot 이다.
    shot    **글자가 박힌 사진**이다 — 광고컷, 치수 도해, 표, 번호가 그려진 그림,
            사진 위에 설명이 얹힌 것. **떼어낼 수 없는 한 덩어리**다.
            애매하면 shot 으로 둬라. photo 로 잘못 부르면 **그 글이 우리 페이지에서
            영영 안 읽히고**, body 로 잘못 부르면 그림이 사라진다. shot 은 통째로
            실리니 잃는 것이 없다.
    decor   **장식**이다 — 빈 알약, 구분선, 푸터, 상품명 반복 띠.
            **버리지 않는다.** 원본 그림 그대로 실린다. 다만 **새 구간을 열지 않는다** —
            장식만 있는 구간은 만들지 않는다는 뜻이다.
            **띠나 배지 안에 글이 있으면 장식이 아니라 제목이다.** 분홍 띠에
            `프리티 러브 브루스의 포인트!` 라고 쓰여 있으면 그건 title 이다.
            글이 한 글자라도 읽히면 decor 가 아니다.
            **테두리 상자 안의 짧은 글은 제목/소제목이다.**

**글 읽기 — title·body 만**

  · 글자를 고치거나 보태거나 요약하지 마라. 오타도 그대로 둔다.
  · 한 문단 안의 줄바꿈은 붙여서 한 줄로. 문단이 나뉘는 자리에만 빈 줄 하나.
  · 표처럼 항목이 나열된 글(`A타입 길이 10cm / B타입 …`)은 **줄을 살려라.**
    한 줄로 붙이면 어느 값이 어느 옵션인지 알 수 없게 된다.
  · 강조: 원본에서 **글자색이 다르거나 굵은** 낱말·구절만 `**이렇게**` 감싼다.
    원본에 강조가 없으면 감싸지 마라. 네가 고르지 마라.
  · 제목에 큰 번호(01, 02 …)나 영문 부제(`PRODUCT FEATURES`)가 같이 있으면
    **한글 제목만** 적는다. 번호는 우리가 따로 붙인다.
  · **shot·photo·decor 는 `texts` 를 비운다.** shot 의 글은 따로 물어본다.
  · **title 이라고 했으면 글을 반드시 적어라.** 글 없는 title 은 우리가 못 쓴다 —
    번호만 붙은 빈 제목이 되어 구간 번호가 꼬인다. 못 읽겠으면 title 이라 하지 마라.

**돌려줄 것 — JSON 하나. 다른 말은 붙이지 마라.**

```json
{"kinds":["0:title","1:body","2:photo","3:shot","4:decor"],
 "texts":{"0":"제품특징","1":"본문 설명 글"}}
```

`kinds` 에는 **밴드를 하나도 빼지 말고 전부** 넣는다. 번호는 0 부터 차례대로다.
`kinds` 는 짧은 글 배열이고 `texts` 는 번호→글 이다. **그 안에 또 중괄호를 만들지 마라.**
"""

MARK_PROMPT = """사진에 글이 박힌 밴드다. **글줄마다 빨간 네모와 번호**를 그려 두었다.
네모 **안의 글만 그대로 읽어라.**

우리는 이 그림을 자르지 않는다. 네모 안의 글자 픽셀을 배경색으로 덮고, 덮은 그
자리에 네가 읽은 글을 다시 얹는다. 그래서 **네모 하나에 글 하나**여야 한다.

  · 네모 밖은 읽지 마라. 옆 네모의 글을 끌어오지 마라.
  · **네모 하나에 글줄이 둘 이상 들어 있으면 전부 읽고 줄바꿈을 살려라.**
    한 줄만 읽고 넘어가면 나머지 줄이 우리 페이지에서 사라진다.
  · 글자를 고치거나 보태거나 요약하지 마라. 오타도 그대로 둔다.
  · **네모가 글을 온전히 감싸고 있을 때만 읽어라.** 글자의 일부만 걸쳐 있거나,
    네모 안이 글이 아니면(제품 무늬·워터마크·지시선·색 배지) **그 번호를 빼고**
    답한다. 지어내지 마라 — 빠진 자리는 우리가 원본 그대로 둔다.
  · 강조: 원본에서 **글자색이 다르거나 굵은** 낱말만 `**이렇게**` 감싼다.
  · 빨간 네모와 번호는 우리가 그린 것이다. 그건 읽지 마라.

**돌려줄 것 — JSON 하나. 다른 말은 붙이지 마라.**

```json
{"lines":["0-1|전원 버튼을 길게 누르면 전원이 켜지고","0-2|버튼을 한번 더 길게 누르면",
          "1-1|무게: 약 97g"]}
```

한 줄은 `밴드번호-네모번호|글` 이다. 밴드번호는 우리가 `[3]` 처럼 붙여 보낸 번호,
네모번호는 그림에 그려 둔 번호다. **그 안에 또 중괄호를 만들지 마라.**
"""

TITLE, BODY, PHOTO, SHOT, DECOR = "title", "body", "photo", "shot", "decor"
KINDS = (TITLE, BODY, PHOTO, SHOT, DECOR)


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


def _shrunk_b64(path: Path) -> str:
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        if max(im.size) > SEND_PX:
            s = SEND_PX / max(im.size)
            im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def parse(reply: str) -> tuple[dict[int, str], dict[int, str]]:
    """모델 답 → ({밴드: 종류}, {밴드: 글}).

    줄 하나가 깨져도 그 밴드만 잃는다. 답 전체를 버리지 않는다.
    """
    m = re.search(r"\{[\s\S]*\}", reply or "")
    if not m:
        return {}, {}
    try:
        got = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}, {}

    kinds: dict[int, str] = {}
    for line in got.get("kinds") or []:
        text = str(line).strip()
        head, _, tail = text.partition(":")
        digits = re.sub(r"[^0-9]", "", head)
        word = tail.strip().lower()
        if digits and word in KINDS:
            kinds[int(digits)] = word

    texts: dict[int, str] = {}
    for k, v in (got.get("texts") or {}).items():
        digits = re.sub(r"[^0-9]", "", str(k))
        if digits and str(v).strip():
            texts[int(digits)] = str(v)
    return kinds, texts


def parse_marks(reply: str) -> dict[int, dict[int, str]]:
    """모델 답 → {밴드: {네모번호: 글}}. 안 준 네모는 없는 채로 둔다."""
    m = re.search(r"\{[\s\S]*\}", reply or "")
    if not m:
        return {}
    try:
        got = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    out: dict[int, dict[int, str]] = {}
    for line in got.get("lines") or []:
        head, _, text = str(line).partition("|")
        nums = re.findall(r"\d+", head)
        if len(nums) == 2 and text.strip():
            out.setdefault(int(nums[0]), {})[int(nums[1])] = text.strip()
    return out


def read_marks(key: str, shots: list[tuple[int, Path]], timeout: int = 240,
               tries: int = 2) -> dict[int, dict[int, str]]:
    """**네모를 그려 둔** 밴드를 보내고 네모마다 글을 받는다.

    자리를 모델에게 물어보지 않는다 — 자리는 우리가 픽셀에서 이미 알고 있고, 그것을
    그림에 그려서 보여 준다. 모델이 하는 일은 **그 네모 안을 읽는 것**뿐이다.
    """
    llm = _llm()
    parts: list[tuple[str, str]] = [("text", MARK_PROMPT)]
    parts.append(("text", f"글줄 네모를 그려 둔 밴드 {len(shots)}장을 보냅니다."))
    for n, path in shots:
        parts.append(("text", f"[{n}]"))
        parts.append(("image", _shrunk_b64(path)))

    url, headers, payload = llm.build(key, parts, max_tokens=8000)
    from .web import _pin

    payload = _pin(payload)
    for n in range(tries):
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            got = json.loads(r.read())
        text, _stop = llm.extract(key, got)
        lines = parse_marks(text)
        if lines:
            return lines
        print(f"[basic] 네모 글을 못 읽었다 — 다시 묻는다 ({n + 1}/{tries})", flush=True)
    return {}


def read(key: str, bands: list[Path], timeout: int = 240,
         tries: int = 2) -> tuple[dict[int, str], dict[int, str]]:
    """본문 밴드를 보내고 (종류, 글) 을 받는다. 번호는 `bands` 안에서의 자리다."""
    llm = _llm()
    parts: list[tuple[str, str]] = [("text", PROMPT)]
    parts.append(("text", f"본문 밴드 {len(bands)}장을 위에서 아래 순서로 보냅니다."))
    for i, b in enumerate(bands):
        parts.append(("text", f"[{i}]"))
        parts.append(("image", _shrunk_b64(b)))

    url, headers, payload = llm.build(key, parts, max_tokens=8000)
    from .web import _pin  # 같은 입력이면 같은 답이 나오게 못박는다

    payload = _pin(payload)
    for n in range(tries):
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            got = json.loads(r.read())
        text, _stop = llm.extract(key, got)
        kinds, texts = parse(text)
        if kinds:
            return kinds, texts
        print(f"[basic] 본문 답을 못 읽었다 — 다시 묻는다 ({n + 1}/{tries})", flush=True)
    return {}, {}
