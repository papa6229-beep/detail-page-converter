"""본문 밴드를 섹션으로 **놓는다**. 판정은 여기 없다.

    섹션 = 번호 + 제목 + (설명·사진들)

밴드가 무엇인지는 모델이 말해 준다(`read_text`). 여기서 하는 일은 그 말대로
줄 세우는 것뿐이다 — 제목이 나오면 새 섹션을 열고, 설명은 문단으로, 사진은
그대로, 글자 박힌 사진은 통째로, 장식은 버린다.

**예전에는 여기서 픽셀로 판정했다.** 밴드의 어두운 덩어리를 세어 제목인지 설명인지
가르고(`_role`), 알약 배지를 떼어내고(`_split_badge`), 사진 옆 글자를 잘라내고
(`sidetext`), 페이지마다 제목의 급을 매겼다(머리띠 > 배지 > 굵은 한 줄). 상품이
하나 늘 때마다 그 잣대가 어긋났고, 어긋나는 방식이 매번 달랐다. 전부 지웠다.

`sidetext` 모듈은 남아 있지만 본문은 안 쓴다 — 메인이 알맹이를 자를 때 라벨이
있는지 물어보는 데 쓴다(`main._content_rect`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: 모델이 말해 주는 종류. `read_text` 와 같은 이름을 쓴다.
TITLE, BODY, PHOTO, SHOT, DECOR = "title", "body", "photo", "shot", "decor"


@dataclass
class Piece:
    """본문 밴드 하나."""

    kind: str
    band: int              #: 본문 안에서 몇 번째 밴드인가 (0 부터)
    file: str = ""         #: 밴드 그림 파일 이름
    text: str = ""         #: 제목·설명이면 모델이 읽은 글


@dataclass
class Section:
    number: int
    title: Piece | None = None
    items: list[Piece] = field(default_factory=list)   #: 설명·사진을 원본 순서대로

    @property
    def photos(self):
        return [p for p in self.items if p.kind in (PHOTO, SHOT)]

    @property
    def bodies(self):
        return [p for p in self.items if p.kind == BODY]


def pieces_from(kinds: dict[int, str], texts: dict[int, str], files: list[str]) -> list[Piece]:
    """모델이 말한 것을 조각으로. 말 안 해 준 밴드는 **사진으로 둔다.**

    빠뜨린 밴드를 버리면 원본에 있던 그림이 조용히 사라진다. 사진으로 두면
    최악이라도 원본이 실린다 — 글이 그림으로 실릴 뿐 없어지지는 않는다.
    """
    out = []
    for i, f in enumerate(files):
        kind = kinds.get(i, PHOTO)
        out.append(Piece(kind, i, file=f, text=texts.get(i, "") if kind in (TITLE, BODY) else ""))
    return out


def sections(pieces: list[Piece]) -> list[Section]:
    """조각들을 섹션으로 묶는다.

    제목이 새 섹션을 연다. **제목이 하나도 없는 페이지**면 "설명 뒤에 다시 나오는
    사진" 이 연다 — 그 자리가 사람 눈에도 구간이 바뀌는 자리다.
    """
    has_title = any(p.kind == TITLE for p in pieces)
    secs: list[Section] = []
    cur: Section | None = None

    def new() -> Section:
        s = Section(len(secs) + 1)
        secs.append(s)
        return s

    for p in pieces:
        if p.kind == DECOR:
            continue
        if p.kind == TITLE:
            if cur is None or cur.title is not None or cur.items:
                cur = new()
            cur.title = p
            continue
        if cur is None:
            cur = new()
        if not has_title and p.kind in (PHOTO, SHOT) and cur.bodies:
            cur = new()
        cur.items.append(p)
    return [s for s in secs if s.title or s.items]


#: 글자 박힌 사진이 본문의 이만큼을 넘으면 **자르지 않는다.**
#: 그런 원본은 디자이너가 사진과 글을 한 덩어리로 짜 놓은 것이라, 밴드로 갈라
#: 다시 세우면 얻는 것보다 잃는 것이 많다(유컵스). 통째로 싣고 그 사실을 적는다.
MOSTLY_SHOT = 2 / 3


def mostly_shots(pieces: list[Piece]) -> bool:
    """본문이 통째로 실려야 하는 원본인가."""
    usable = [p for p in pieces if p.kind != DECOR]
    if not usable:
        return False
    return sum(1 for p in usable if p.kind == SHOT) / len(usable) >= MOSTLY_SHOT
