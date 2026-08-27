"""본문 밴드를 섹션으로 **놓는다**. 판정은 여기 없다.

    섹션 = 번호 + 제목 + (설명·사진들)

밴드가 무엇인지는 모델이 말해 준다(`read_text`). 여기서 하는 일은 그 말대로
줄 세우는 것뿐이다.

**지키는 것은 셋뿐이다.**

    ㉠ 원본 밴드는 하나도 버리지 않는다. 글자로 바뀐 것 말고는 전부 사진으로 싣는다.
    ㉡ 사진에 글이 박혀 있으면 **자르지도 덮지도 않고 통째로** 싣는다. 그 글은
       그림 안에서 제자리를 지킨다. 손대면 잃는 것이 얻는 것보다 컸다.
    ㉢ 섹션은 원본대로. 제목이 새 섹션을 연다. 사진도 설명도 없는 섹션은 만들지 않는다.

**예전에는 여기서 픽셀로 판정했다.** 밴드의 어두운 덩어리를 세어 제목인지 설명인지
가르고(`_role`), 알약 배지를 떼어내고(`_split_badge`), 페이지마다 제목의 급을 매겼다.
상품이 하나 늘 때마다 그 잣대가 어긋났고, 어긋나는 방식이 매번 달랐다. 전부 지웠다.

**버리는 길도 지웠다.** 장식은 이제 버리는 것이 아니라 "구간을 열지 않는 그림" 이다.
버리는 길이 하나라도 있으면, 모델이 그 이름을 잘못 붙이는 순간 원본이 소리 없이
사라진다 — 벨벳키스의 `SIZE & INFO` 배지가 그렇게 없어졌다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: 모델이 말해 주는 종류. `read_text` 와 같은 이름을 쓴다.
TITLE, BODY, PHOTO, SHOT, DECOR = "title", "body", "photo", "shot", "decor"

#: 사진처럼 실리는 것들. 이 중 `DECOR` 만 **구간을 열지 못한다.**
IMAGES = (PHOTO, SHOT, DECOR)
#: 구간의 내용이 되는 것들. 이것이 하나도 없으면 구간이 아니다.
CONTENT = (BODY, PHOTO, SHOT)



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
        return [p for p in self.items if p.kind in IMAGES]

    @property
    def bodies(self):
        return [p for p in self.items if p.kind == BODY]

    @property
    def has_content(self) -> bool:
        """장식 말고 진짜 내용이 있는가."""
        return any(p.kind in CONTENT for p in self.items)


def pieces_from(kinds: dict[int, str], texts: dict[int, str], files: list[str]) -> list[Piece]:
    """모델이 말한 것을 조각으로. **밴드는 하나도 안 버린다.**

    말 안 해 준 밴드는 사진으로 둔다. 빠뜨린 밴드를 버리면 원본에 있던 그림이
    조용히 사라진다. 사진으로 두면 최악이라도 원본이 실린다.
    """
    out = []
    for i, f in enumerate(files):
        kind = kinds.get(i, PHOTO)
        # 글은 **글이 되는 것에만** 딸린다. 글자 박힌 사진(shot)에 글을 달면
        # 그림 안에 있는 글이 우리 글로 또 나와 **두 번 읽힌다.**
        text = texts.get(i, "") if kind in (TITLE, BODY) else ""
        # **글 없는 제목은 제목이 아니다.** 번호만 붙은 빈 제목이 되어 구간 번호가
        # 꼬인다. 다시 물어도 글이 없으면 **그림으로** 싣는다 — 버리지 않는다.
        if kind == TITLE and not text.strip():
            kind = DECOR
        out.append(Piece(kind, i, file=f, text=text))
    return out


def sections(pieces: list[Piece]) -> list[Section]:
    """조각들을 섹션으로 묶는다. **원본 순서 그대로.**

    제목이 새 섹션을 연다. 단 **내용 없는 섹션은 만들지 않는다** — 제목이 연달아
    나오면(죠우무의 `포인트` 머리 두 겹) 머리는 하나뿐이고, 나머지는 그 자리에
    원본 그림으로 들어간다. 버리지 않는다.

    머리가 되는 것은 **내용에 가장 가까운 제목**, 곧 마지막 것이다. 앞엣것은 대개
    상품명을 되풀이하는 띠다 — 죠우무는 `젊은 유부녀의 엉덩이` 띠 다음에 `사이즈`
    가 온다. 앞엣것을 머리로 삼으면 구간 이름이 죄다 상품명이 되어 버린다.

    **제목이 하나도 없는 페이지**면 "설명 뒤에 다시 나오는 사진" 이 연다 —
    그 자리가 사람 눈에도 구간이 바뀌는 자리다.
    """
    has_title = any(p.kind == TITLE for p in pieces)
    secs: list[Section] = []
    cur: Section | None = None

    def new() -> Section:
        s = Section(len(secs) + 1)
        secs.append(s)
        return s

    def as_image(p: Piece) -> Piece:
        """제목 자리를 못 얻은 조각 — 원본 그림으로 싣는다. 글은 그림 안에 있다."""
        return Piece(DECOR, p.band, file=p.file)

    for p in pieces:
        if p.kind == TITLE:
            if cur is None or cur.has_content:
                cur = new()
            elif cur.title is not None:
                cur.items.append(as_image(cur.title))   # 앞 제목은 그림으로 남는다
            cur.title = p
            continue
        if cur is None:
            cur = new()
        if not has_title and p.kind in (PHOTO, SHOT) and cur.bodies:
            cur = new()
        cur.items.append(p)

    out: list[Section] = []
    for s in secs:
        if s.items:
            out.append(s)
        elif s.title is not None and out:
            # 뒤에 아무것도 안 오는 꼬리 제목. 구간을 못 되니 앞 구간에 그림으로 붙인다.
            out[-1].items.append(as_image(s.title))
    for n, s in enumerate(out, 1):
        s.number = n
    return out


#: 글자 박힌 사진이 본문의 이만큼을 넘으면 **자르지 않는다.**
#: 그런 원본은 디자이너가 사진과 글을 한 덩어리로 짜 놓은 것이라, 밴드로 갈라
#: 다시 세우면 얻는 것보다 잃는 것이 많다(유컵스). 통째로 싣고 그 사실을 적는다.
MOSTLY_SHOT = 2 / 3


def mostly_shots(pieces: list[Piece]) -> bool:
    """본문이 통째로 실려야 하는 원본인가."""
    if not pieces:
        return False
    return sum(1 for p in pieces if p.kind == SHOT) / len(pieces) >= MOSTLY_SHOT
