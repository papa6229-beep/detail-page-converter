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
#: 접두 번호 `01. ` — 엑셀 옵션값과 캡션 양쪽에 붙어 있다. 벗겨야 서로 맞는다 (7장).
ORDINAL_RE = re.compile(r"^\s*\d+\s*[.)]\s*")


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
    #: options 와 같은 자리의 원본 옵션 번호. 없던 자리는 빈 칸.
    option_numbers: list[str] = field(default_factory=list)
    specs: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class Lead:
    """본문 맨 위에 직접 타이핑돼 있던 한 줄."""

    text: str
    strong: bool = False


@dataclass
class Product:
    meta: Meta = field(default_factory=Meta)
    lead: str = ""
    #: 첫 이미지 위의 타이핑 구간. 거의 모든 원본에 있다.
    intro: list[Lead] = field(default_factory=list)
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

    @property
    def option_groups(self) -> list[tuple[str, list[Unit]]]:
        """옵션 이름 → 그 옵션에 딸린 유닛들. 문서에 나온 순서대로.

        옵션 하나에 유닛이 몇 개든 상관없다. 텐가는 옵션마다 1장, 닛포리는
        배우 한 명당 6장이다. 세는 것이지 판정하는 것이 아니므로 같은 코드로 된다.
        """
        order: list[str] = []
        bucket: dict[str, list[Unit]] = {}
        for u in self.units:
            if not u.option_tag:
                continue
            if u.option_tag not in bucket:
                order.append(u.option_tag)
                bucket[u.option_tag] = []
            bucket[u.option_tag].append(u)
        return [(tag, bucket[tag]) for tag in order]

    @property
    def orphan_options(self) -> list[str]:
        """엑셀에는 있는데 딸린 이미지가 하나도 없는 옵션."""
        have = {t for t, _ in self.option_groups}
        return [o for o in self.meta.options if o not in have]

    def option_number(self, tag: str, fallback: int) -> str:
        """그 옵션이 **몇 번**인지. 손님이 주문할 때 고르는 그 번호다.

        엑셀에 `01. 키타노 미나` 라고 적혀 있었으면 그 번호를 그대로 쓴다.
        번호가 없던 원본이면 나온 순서로 매긴다. 어느 쪽이든 이름 앞에 번호가 붙는다.
        """
        try:
            i = self.meta.options.index(tag)
        except ValueError:
            i = -1
        if 0 <= i < len(self.meta.option_numbers) and self.meta.option_numbers[i]:
            return self.meta.option_numbers[i]
        return str((i if i >= 0 else fallback) + 1)

    @property
    def body_units(self) -> list[Unit]:
        """옵션 카드로 안 가는 유닛 전부. 캡션이 없어도 버리지 않는다.

        3.1 — 캡션 없는 이미지는 풀블리드로 크게. 없는 것은 유닛이 아니라 캡션이다.
        빠뜨리면 사람이 캡션을 안 채웠을 때 그림까지 조용히 사라진다. 실제로 그랬다.
        """
        return [u for u in self.units if not u.option_tag]


def split_tag(caption: str) -> tuple[str, str]:
    """`[웨이비 2] 상하좌우로…` → ("웨이비 2", "상하좌우로…")

    태그를 본문에 남겨두면 출력 쪽 제목과 겹친다 (7장).
    """
    m = TAG_RE.match(caption or "")
    if not m:
        return "", (caption or "").strip()
    # 닛포리 캡션은 `[01. 키타노 미나]`, 엑셀 옵션값은 `키타노 미나` 다.
    # 접두 번호를 양쪽에서 똑같이 벗겨야 대조가 된다. 안 벗기면 옵션이 하나도 안 붙는다.
    return ORDINAL_RE.sub("", m.group(1)).strip(), caption[m.end() :].strip()


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
