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


@dataclass
class Piece:
    """본문에서 뽑은 이미지 하나와 그에 붙어 있던 텍스트."""

    url: str
    caption: str = ""


@dataclass
class Body:
    pieces: list[Piece] = field(default_factory=list)
    lead: str = ""
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
            if node.find("img") is not img and len(node.find_all("img")) > 1:
                break  # 이미지가 여럿이면 그 글자는 이 이미지 것이 아니다
            text = _clean_text(node.get_text(" "))
            if text:
                caption = text
                break
        out.pieces.append(Piece(url=url, caption=caption))

    # 리드 — 이미지에 붙지 않은 첫 문단
    for p in soup.find_all(["p", "div"]):
        if p.find("img"):
            continue
        text = _clean_text(p.get_text(" "))
        if len(text) >= 12:
            out.lead = text
            break

    return out
