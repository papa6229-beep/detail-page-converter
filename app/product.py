"""정규형 — DESIGN.md 3장.

    Product
    ├ meta    상품명 · 브랜드 · 가격 · 옵션 · 카테고리
    ├ lead    리드 텍스트
    └ units[]  { image, caption?, optionTag? }

원본이 조각형이든 통이미지형이든 여기까지 오면 같은 모양이다.
렌더러는 이 아래만 보고, 어디서 왔는지 모른다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: 캡션 접두어 `[웨이비 2] …` — 7장. 옵션 태그는 여기서 온다.
TAG_RE = re.compile(r"^\s*[\[(]\s*([^\])]{1,24})\s*[\])]\s*")


@dataclass
class Unit:
    """이미지 하나 + (있으면) 캡션."""

    image: str = ""
    caption: str = ""
    option_tag: str = ""
    #: 원본 캡션이 그림 안에 박혀 있던 경우, 사람이 읽을 수 있게 잘라 둔 조각.
    caption_crop: str = ""
    width: int = 0
    height: int = 0

    @property
    def has_caption(self) -> bool:
        return bool(self.caption.strip())

    @property
    def head(self) -> str:
        """캡션 첫 문장 — 소제목으로 승격한다 (6.2 다섯째 레버)."""
        text = self.caption.strip()
        m = re.search(r"^(.{6,60}?)[.。](\s|$)", text)
        return m.group(1).strip() if m else ""

    @property
    def body(self) -> str:
        head = self.head
        return self.caption.strip()[len(head) + 1 :].strip() if head else self.caption.strip()


@dataclass
class Meta:
    code: str = ""
    name: str = ""
    brand: str = ""
    category: str = ""
    price: str = ""
    options: list[str] = field(default_factory=list)
    specs: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class Product:
    meta: Meta = field(default_factory=Meta)
    lead: str = ""
    units: list[Unit] = field(default_factory=list)
    #: 상단 광고 구간 — 캡션 없는 통짜 이미지들 (3.1)
    ad: list[str] = field(default_factory=list)
    adapter: str = ""

    @property
    def captioned(self) -> list[Unit]:
        return [u for u in self.units if u.has_caption]

    @property
    def option_units(self) -> list[Unit]:
        return [u for u in self.units if u.option_tag]

    @property
    def feature_units(self) -> list[Unit]:
        return [u for u in self.units if u.has_caption and not u.option_tag]


def split_tag(caption: str) -> tuple[str, str]:
    """`[웨이비 2] 상하좌우로…` → ("웨이비 2", "상하좌우로…")

    태그를 본문에 남겨두면 출력 쪽 제목과 겹친다 (7장).
    """
    m = TAG_RE.match(caption or "")
    if not m:
        return "", (caption or "").strip()
    return m.group(1).strip(), caption[m.end() :].strip()


def apply_tags(units: list[Unit], option_values: list[str] | None = None) -> None:
    """캡션 접두어를 옵션 태그로 옮긴다.

    엑셀 옵션값이 있으면 대조해서 확인하고, 없으면 접두어를 그대로 믿는다.
    판정이 아니라 관측이다 — 접두어가 있으면 있는 것이다.
    """
    known = {re.sub(r"\s+", "", v).lower() for v in (option_values or [])}
    for u in units:
        tag, rest = split_tag(u.caption)
        if not tag:
            continue
        if known and re.sub(r"\s+", "", tag).lower() not in known:
            continue  # 옵션값에 없는 접두어는 태그가 아니라 그냥 말머리다
        u.option_tag, u.caption = tag, rest
