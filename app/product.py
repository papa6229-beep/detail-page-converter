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
#:
#: **여는 글자에 맞는 닫는 글자만 본다.** 예전에는 `[…]` 와 `(…)` 를 둘 다 받으려고
#: 두 닫는 글자를 함께 막아 뒀는데(`[^\])]`), 그러면 이름 안의 괄호가 말머리의 끝이
#: 되어 `[유니 다이아몬드 (화이트)]` 가 `유니 다이아몬드 (화이트` 로 잘렸다.
#: 엑셀에는 괄호까지 붙은 이름으로 있으므로 그대로 대조가 실패한다.
TAG_RE = re.compile(r"^\s*(?:\[\s*([^\]]{1,24}?)\s*\]|\(\s*([^)]{1,24}?)\s*\))\s*")
#: 접두 번호 `01. ` `#001 ` — 엑셀 옵션값과 캡션 양쪽에 붙어 있다. 벗겨야 서로 맞는다 (7장).
#: `#` 형은 779행에서 2492321 하나뿐이지만(`#001 고백편` ← `고백편`) 규칙은 같은 자리다.
ORDINAL_RE = re.compile(r"^\s*(?:#\s*\d+|\d+\s*[.)])\s*")


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

    def _split_head(self) -> tuple[str, str]:
        """캡션을 소제목 + 본문으로 가른다 (6.2 다섯째 레버).

        두 가지를 조심한다.

        **대괄호 말머리 안의 마침표는 문장 끝이 아니다.** `[01. 츤데레 바니· 03. 덜렁이
        바니] 두 모델은…` 이 `03.` 에서 두 동강 나서 소제목이 `[01. 츤데레 바니· 03`,
        본문이 `덜렁이 바니] 두 모델은…` 으로 나왔다.

        **별표는 화면에 안 나오는 표시다. 길이를 잴 때 세지 않는다.** 6~60자라는
        한도를 별표까지 세어 재는 바람에, 모델이 어디를 강조했느냐에 따라 소제목이
        생겼다 없어졌다 했다 — 2497526 에서 1번 옵션만 굵게 나온 것이 그 때문이다.
        """
        text = self.caption.strip()
        m = TAG_RE.match(text) or re.match(r"^\s*[\[(][^\])]{0,60}[\])]\s*", text)
        start = m.end() if m else 0
        for hit in re.finditer(r"[.。](\s|$)", text[start:]):
            seg = text[: start + hit.start()]
            n = len(seg) - 2 * seg.count("**")  # 별표를 뺀 눈에 보이는 길이
            if n < 6:
                continue
            if n > 60:
                break
            head = seg.strip()
            return head, text[start + hit.start() + 1 :].strip()
        return "", text

    @property
    def head(self) -> str:
        return self._split_head()[0]

    @property
    def body(self) -> str:
        return self._split_head()[1]


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
    #: 엑셀을 읽었는가. **"옵션이 0개"와 "모른다"는 다른 말이다** —
    #: 엑셀이 0개라고 했으면 그것은 사실이고, 그때 대괄호 말머리는 옵션명이 아니라
    #: 세트 구성품 이름이다. 엑셀 없이 URL 하나로 돌릴 때는 알 길이 없으므로 믿는다.
    options_known: bool = False
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
    inside = m.group(1) if m.group(1) is not None else m.group(2)
    # 닛포리 캡션은 `[01. 키타노 미나]`, 엑셀 옵션값은 `키타노 미나` 다.
    # 접두 번호를 양쪽에서 똑같이 벗겨야 대조가 된다. 안 벗기면 옵션이 하나도 안 붙는다.
    #
    # **벗겨서 빈 값이 되면 그건 번호가 아니라 이름이다.** 2489395 의 옵션은
    # `#1` `#2` `#3` 자체가 이름이다. 벗기면 태그가 사라진다.
    bare = ORDINAL_RE.sub("", inside).strip()
    return (bare or inside.strip()), caption[m.end() :].strip()


def apply_tags(units: list[Unit], option_values: list[str] | None = None) -> None:
    """캡션 접두어를 옵션 태그로 옮긴다.

    엑셀 옵션값이 있으면 대조해서 확인한다. 판정이 아니라 관측이다.

    **빈 리스트와 `None` 은 다른 말이다.** 빈 리스트는 엑셀이 "옵션이 없다"고
    말해 준 것이고, `None` 은 엑셀이 없어 모른다는 뜻이다(URL 하나로 돌릴 때).
    예전에는 둘 다 "모른다"로 읽고 말머리를 그대로 믿었다. 그래서 맨즈맥스
    4종 BOX 세트에서 구성품 이름이 옵션 카드가 되고, `촉촉 홀 사용법 2STEP`
    까지 5번 옵션으로 올라갔다. 한 박스에 든 세트는 옵션이 아니라 **1상품**이다.
    """
    if option_values is not None and not option_values:
        return  # 엑셀이 옵션이 없다고 했다 — 말머리는 세트 구성품 이름이다

    def flat(s: str) -> str:
        return re.sub(r"\s+", "", s).lower()

    known = {flat(v): v for v in (option_values or [])}
    for u in units:
        tag, rest = split_tag(u.caption)
        if not tag:
            continue
        if known:
            tag = _match(flat(tag), known)
            if not tag:
                continue  # 옵션값에 없는 접두어는 태그가 아니라 그냥 말머리다
        u.option_tag, u.caption = tag, rest


def _match(tag: str, known: dict[str, str]) -> str:
    """말머리를 엑셀 옵션값에 대어 본다. **붙으면 엑셀 쪽 이름으로 돌려준다.**

    사장님 말: "옵션은 엑셀대로 가."

    같은 옵션을 상세페이지와 엑셀이 다르게 적어 놓은 것이 779행에 흔하다.
    한쪽이 다른 쪽을 **그대로 품고 앞에서부터 겹치는** 것이 대부분이다 —

        루미카              ← 루미카(핑크)              페이지가 색을 뺐다
        능숙한 입술(소프트)    ← 능숙한 입술               페이지가 경도를 더 적었다
        슬림 타입(오렌지      ← 슬림 타입(오렌지)          말머리 괄호가 잘렸다

    그래서 **앞머리가 겹치면 같은 것으로 본다. 단, 걸리는 옵션이 딱 하나일 때만.**
    둘 이상 걸리면 어느 쪽인지 모르는 것이므로 안 붙인다 —
    `멜티` 는 `멜티 관통` 과 `멜티 비관통` 둘 다에 걸린다.

    779행 실측: 어긋난 말머리 80개 중 **30개가 붙고 2개는 애매해서 안 붙는다.**
    붙은 30개는 전부 맞다. 나머지 48개는 애초에 옵션명이 아니거나(`사용 예시`
    `일본 직수입`) 표기가 아주 다르다(`하시모토 아레나` ← `하시모토 아리나`).
    그건 앞머리로 안 걸리므로 **틀리게 붙는 일이 없다.**
    """
    if tag in known:
        return known[tag]
    hits = [v for k, v in known.items() if k.startswith(tag) or tag.startswith(k)]
    return hits[0] if len(hits) == 1 else ""
