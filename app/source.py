"""상세설명 HTML에서 소재를 캐낸다 — DESIGN.md 2.3 · 2.4.

이미지 경로는 세 갈래이고, `banana_img/` 를 통째로 버리면 텐가는 소재가 0장이 된다.
버릴 것과 남길 것을 경로로 가른다. 상품번호로 URL을 유추하지 않는다 (2.4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

CDN = "https://cdn-banana.bizhost.kr/"

#: 버리는 경로 — 공용 머리띠·배너·장식 (2.3)
DROP = (
    "banana_img/conf/",
    "banana_img/k/",
    "/conf/img/",
)
#: 남기는 경로 — 상품 이미지 (2.3)
KEEP = (
    "banana_img/product_image/",
    "files/goodsm/",
)


#: 원본에서 강조돼 있던 표시 — 굵게, 색, 형광펜
EMPHASIS_TAGS = ("b", "strong", "em", "u", "mark", "font")
EMPHASIS_STYLE = re.compile(r"(background(-color)?\s*:\s*(?!(transparent|none|#fff|white))|color\s*:|font-weight\s*:\s*(bold|[6-9]00))", re.I)

#: 리드에서 걸러낼 상투구 — 상품 설명이 아니라 쇼핑몰 안내문이다
LEAD_NOISE = re.compile(
    r"(사은품|배송|무통장|입금|적립금|쿠폰|이벤트\s*상품|재고\s*문의|고객센터|카카오톡|반품|교환"
    r"|상품\s*(본)?\s*(내용|상세|정보)\s*(시작|보기)?$|상세\s*정보\s*시작)"
)


@dataclass
class Block:
    """본문 맨 위에 직접 타이핑돼 있던 한 줄."""

    text: str
    strong: bool = False


@dataclass
class Piece:
    """본문에서 뽑은 이미지 하나와 그에 붙어 있던 텍스트."""

    url: str
    caption: str = ""


@dataclass
class Body:
    pieces: list[Piece] = field(default_factory=list)
    lead: str = ""
    #: 첫 이미지보다 위에 직접 타이핑돼 있던 줄들. 90% 원본에 있다.
    lead_blocks: list[Block] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    broken: list[str] = field(default_factory=list)

    @property
    def images(self) -> list[str]:
        return [p.url for p in self.pieces]

    @property
    def n_captions(self) -> int:
        return sum(1 for p in self.pieces if p.caption)


def absolute(src: str, base: str = CDN) -> str:
    src = (src or "").strip().replace("\\", "/")
    if src.startswith("//"):
        return "https:" + src
    if src.startswith(("http://", "https://")):
        return src
    return urljoin(base, src.lstrip("/"))


def is_broken(url: str) -> bool:
    """원본에 섞여 있는 깨진 URL (2.4).

    `saunpumnonex.jpgx.jpg` 처럼 확장자가 두 번 붙은 것, CSS 값 자리에 박힌 경로 등.
    """
    path = urlparse(url).path.lower()
    if re.search(r"\.(jpe?g|png|gif)[^/]*\.(jpe?g|png|gif)$", path):
        return True
    return not re.search(r"\.(jpe?g|png|gif|webp)$", path)


def classify(url: str) -> str:
    low = url.lower()
    if any(d in low for d in DROP):
        return "drop"
    if any(k in low for k in KEEP):
        return "keep"
    return "unknown"


def _clean_lines(s: str) -> str:
    """줄바꿈은 남기고 나머지 공백만 정리한다.

    저자가 `<br>` 로 끊어 놓은 자리는 **뜻으로 끊은 자리**다.
    `…나선을 이루며 돈다 <br> 즉시 필연의 높은 자극…` 을 한 줄로 이어붙이면
    브라우저가 아무 데서나 접어 뜻이 어긋난 자리에서 줄이 바뀐다.
    """
    s = re.sub(r"[^\S\n]+", " ", s or "")
    s = re.sub(r" *\n *", "\n", s)
    return re.sub(r"\n{2,}", "\n", s).strip()


def _clean_text(s: str) -> str:
    s = re.sub(r"[ \s]+", " ", s or "")
    return s.strip()


def parse(html: str, base: str = CDN) -> Body:
    """상세설명 HTML 한 덩이를 조각들로 푼다.

    캡션은 판정하지 않고 **관측한다** (3.1) — 이미지와 같은 껍데기(li·td·div) 안에
    글자가 있으면 그게 캡션이다. 없으면 없는 것이고, 그건 광고컷이라는 뜻이다.
    """
    from bs4 import BeautifulSoup

    out = Body()
    if not (html or "").strip():
        return out
    soup = BeautifulSoup(html, "lxml")

    kept_first = None
    for img in soup.find_all("img"):
        url = absolute(img.get("src") or img.get("data-src") or "", base)
        if not url:
            continue
        if is_broken(url):
            out.broken.append(url)
            continue
        if classify(url) == "drop":
            out.dropped.append(url)
            continue

        caption = ""
        node = img
        for _ in range(4):  # 같은 껍데기를 위로 몇 겹 올라가 본다
            node = node.parent
            if node is None:
                break
            if len(node.find_all("img")) > 1:
                # 이미지가 여럿 든 상자의 글자는 이 이미지 것이 아니다.
                # 예전엔 "첫 이미지가 아닐 때"만 걸러서, 첫 이미지가 본문 전체를
                # 캡션으로 삼켰다. 개수만 보면 된다.
                break
            text = _clean_text(node.get_text(" "))
            if text:
                caption = text
                break
        if kept_first is None:
            kept_first = img
        out.pieces.append(Piece(url=url, caption=caption))

    out.lead_blocks = lead_blocks(soup, kept_first)
    out.lead = " ".join(b.text for b in out.lead_blocks)
    return out


def _block_parent(node):
    """글자 노드가 속한 문단 상자."""
    for anc in node.parents:
        if getattr(anc, "name", None) in ("p", "div", "td", "li", "h1", "h2", "h3", "h4", "center"):
            return anc
    return node.parent


def _is_emphasized(node) -> bool:
    for anc in node.parents:
        name = getattr(anc, "name", None)
        if name in EMPHASIS_TAGS:
            return True
        style = (anc.get("style") or "") if hasattr(anc, "get") else ""
        if style and EMPHASIS_STYLE.search(style):
            return True
        if name in ("p", "div", "td"):
            break  # 문단 상자를 넘어서면 남의 강조다
    return False


def lead_blocks(soup, first_image) -> list[Block]:
    """첫 상품 이미지보다 **위에** 직접 타이핑된 줄들을 순서대로 뽑는다.

    거의 모든 원본이 이미지 앞에 상품명 한 줄, 형광펜 친 한 마디, 설명 문단을
    타이핑해 두었다. 90% 공통이면 그건 변형이 아니라 구조다. 어댑터가 아니라
    파서가 잡아야 한다.

    강조(굵게·색·형광펜)는 **표시만 남긴다.** 원본의 노란 형광펜을 그대로 옮기지
    않는다 — 그건 원본 쇼핑몰의 디자인이고, 우리는 새 디자인으로 다시 칠한다.
    """
    from bs4 import NavigableString

    nodes = list(first_image.find_all_previous(string=True)) if first_image is not None else list(
        soup.find_all(string=True)
    )
    nodes.reverse()

    groups: list[tuple[object, list[NavigableString]]] = []
    for node in nodes:
        if not isinstance(node, NavigableString) or not _clean_text(str(node)):
            continue
        if getattr(node.parent, "name", None) in ("script", "style"):
            continue
        box = _block_parent(node)
        if groups and groups[-1][0] is box:
            groups[-1][1].append(node)
        else:
            groups.append((box, [node]))

    out: list[Block] = []
    for _box, parts in groups:
        # 조각과 조각 사이에 `<br>` 이 있었으면 그 자리에서 줄을 바꾼다.
        # 저자가 뜻으로 끊어 놓은 자리이므로 우리도 지킨다.
        pieces = []
        for i, x in enumerate(parts):
            if i and _br_between(parts[i - 1], x):
                pieces.append("\n")
            # 원문 HTML 자체의 줄바꿈은 편집기가 접은 자리일 뿐이다. 먼저 지운다.
            pieces.append(_clean_text(str(x)))
        text = _clean_lines(" ".join(pieces))
        if len(text) < 2 or LEAD_NOISE.search(text):
            continue
        if any(text == b.text for b in out):
            continue
        out.append(Block(text=text, strong=any(_is_emphasized(x) for x in parts)))
    return out


def _br_between(a, b) -> bool:
    """두 글자 조각 사이에 `<br>` 이 있었는지."""
    node = a.next_element
    while node is not None and node is not b:
        if getattr(node, "name", None) == "br":
            return True
        node = node.next_element
    return False
