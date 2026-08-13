"""어댑터 분기와 변환 — DESIGN.md 3.2 · 4장.

    엑셀 ─┬─ meta
          ├─ lead
          └─ units[] ← 어댑터가 갈리는 유일한 지점
                       ├ 조각형   : HTML 파싱
                       └ 통이미지형: 분할
                                ↓
                        렌더러 · 디자인 (불변)

어댑터 선택은 판정이 아니라 **세기**다 — 상품 이미지가 2장 이상이면 조각형, 1장이면 통이미지형.
"""

from __future__ import annotations

import hashlib
import io
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from slicer import slice_image
from slicer.geometry import Rect
from slicer.layout import ROW, CutConfig, Scan, runs_of, trim

from . import gate, source
from .product import Lead, Meta, Product, Unit, apply_tags

UA = "Mozilla/5.0 (compatible; detail-page-converter/1.0)"


@dataclass
class Work:
    """변환 한 건의 결과와 그 부산물."""

    product: Product
    verdict: gate.Verdict
    ink_coverage: float | None = None
    #: 사람이 읽고 문구를 입력할 수 있게 잘라 둔 캡션 조각 (통이미지형에서만).
    notes: list[str] = field(default_factory=list)


def fetch(url: str, cache: Path) -> bytes:
    """이미지를 받는다. 같은 URL은 다시 받지 않는다."""
    cache.mkdir(parents=True, exist_ok=True)
    key = cache / (hashlib.sha1(url.encode()).hexdigest() + Path(url).suffix[:5])
    if key.exists():
        return key.read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    key.write_bytes(data)
    return data


def _save(im: Image.Image, out: Path, name: str, quality: int = 90) -> str:
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    im.save(path, "JPEG", quality=quality, optimize=True, progressive=True)
    return name


def _ad_blocks(arr: np.ndarray, im: Image.Image, y_end: int, bg, cfg, out: Path) -> list[str]:
    """상단 광고 구간을 통짜 블록으로 자른다.

    3.1 — 캡션 없는 이미지는 풀블리드로 크게. 조각으로 쪼갤 이유가 없다.
    그래서 여기서는 **저자가 그어 놓은 가로 괘선에서만** 끊는다.
    비전에게 되묶어 달라고 물을 일 자체가 사라진다.
    """
    if y_end <= 8:
        return []
    scan = Scan(arr, bg, cfg)
    region = trim(arr, Rect(0, 0, arr.shape[1] - 1, y_end - 1), bg, cfg, scan)
    if region is None:
        return []

    sep, rules = scan.axis_flags(region, ROW)
    blank = sep & ~rules  # 배경만 있는 행

    def _breathes(s: int, e: int, need: int = 8) -> bool:
        """구획선은 여백 속에 놓인다.

        콘텐츠에 딱 붙은 1px 단색 행은 저자가 그은 구획선이 아니라 사진 가장자리다.
        텐가 상단에서 그런 줄 하나(y=307)가 광고컷을 첫 줄과 라벨로 갈라놓았다.
        """
        up = 0
        while s - 1 - up >= 0 and blank[s - 1 - up]:
            up += 1
        down = 0
        while e + 1 + down < len(blank) and blank[e + 1 + down]:
            down += 1
        return max(up, down) >= need

    cuts = [
        region.y0 + s
        for s, e in runs_of(rules)
        if 0 < s and e < region.h - 1 and _breathes(s, e)
    ]
    edges = [region.y0] + cuts + [region.y1 + 1]

    names = []
    for i, (a, b) in enumerate(zip(edges, edges[1:])):
        if b - a < 40:
            continue
        crop = im.crop((region.x0, a, region.x1 + 1, b))
        names.append(_save(crop, out, f"ad_{i:02d}.jpg"))
    return names


def from_whole_image(url: str, im: Image.Image, out: Path) -> tuple[list[Unit], list[str], float, list]:
    """통이미지형 — 분할기로 유닛 배열을 얻는다."""
    arr = np.asarray(im.convert("RGB"))
    result = slice_image(arr)
    cfg = CutConfig()
    bg = result.sections[0].bg if result.sections else (255, 255, 255)

    def split_parts(u):
        """유닛을 그림 부분과 캡션 글줄로 가른다.

        기준은 **그 유닛 자신의 그림 높이**다. 페이지 전체의 높이 분포로 임계값을
        잡으려다 실패했다 — 광고 구간에 1~2px 잔여 조각이 섞여 있어 분포의 가장 큰
        틈이 엉뚱한 바닥에 생겼다. 유닛 안에서 재면 그런 잡음이 끼지 않는다.

        뒤에 붙은 것만 캡션으로 본다. 텐가 오른쪽 첫 칸의 `약 40g` 주석은
        그림 **앞**에 있어 그림의 일부로 남는다.
        """
        parts = sorted(u.parts, key=lambda p: p.y0)
        thin = max(2, int(0.3 * max(p.h for p in parts)))
        caps: list = []
        while len(parts) > 1 and parts[-1].h <= thin:
            caps.insert(0, parts.pop())
        return parts, caps

    # 첫 캡션이 나오는 지점부터 설명 구간, 그 위가 상단 광고 구간 (3.1)
    prepared = [(u, *split_parts(u)) for u in result.units]
    with_cap = [(u, p, c) for u, p, c in prepared if c]
    first = with_cap[0][0].rect.y0 if with_cap else arr.shape[0]
    ad = _ad_blocks(arr, im, first, bg, cfg, out)

    units: list[Unit] = []
    for i, (u, parts, caps) in enumerate(with_cap):
        art_y1 = parts[-1].y1

        art = im.crop((u.rect.x0, u.rect.y0, u.rect.x1 + 1, art_y1 + 1))
        name = _save(art, out, f"unit_{i:02d}.jpg")

        crop_name = ""
        if caps:
            top, bot = caps[0].y0, caps[-1].y1
            strip = im.crop((u.rect.x0, top, u.rect.x1 + 1, bot + 1))
            strip = strip.resize((strip.width * 3, strip.height * 3), Image.LANCZOS)
            crop_name = f"cap_{i:02d}.png"
            strip.save(out / crop_name)

        units.append(Unit(image=name, caption_crop=crop_name, width=art.width, height=art.height))

    return units, ad, result.ink_coverage, result.gap_stats


def from_pieces(body: source.Body, cache: Path, out: Path) -> tuple[list[Unit], list[str]]:
    """조각형 — HTML이 이미 답을 갖고 있다. 픽셀을 보지 않는다 (3.1)."""
    units, ad = [], []
    lead_run = True
    for i, piece in enumerate(body.pieces):
        try:
            data = fetch(piece.url, cache)
            im = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            continue
        if piece.caption:
            lead_run = False
        if lead_run and not piece.caption:
            ad.append(_save(im, out, f"ad_{i:02d}.jpg"))
            continue
        name = _save(im, out, f"unit_{i:02d}.jpg")
        units.append(Unit(image=name, caption=piece.caption, width=im.width, height=im.height))
    return units, ad


def convert(row, workdir: Path, cache: Path) -> Work:
    """엑셀 한 행을 정규형 Product 로."""
    out = workdir
    out.mkdir(parents=True, exist_ok=True)

    body = source.parse(row.body)
    keep = [p for p in body.pieces if source.classify(p.url) != "drop"]
    body.pieces = keep

    opts = row.option_values
    verdict = gate.pre_gate(body.images, body.n_captions, len(opts))
    product = Product(
        meta=Meta(
            code=row.code, name=row.name, brand=row.brand, category=row.category,
            price=row.price, options=opts,
        ),
        lead=body.lead,
        intro=[Lead(text=b.text, strong=b.strong) for b in body.lead_blocks],
    )
    if not verdict.ok and gate.NO_BODY_IMAGE in verdict.reasons:
        return Work(product=product, verdict=verdict)

    ink = None
    gaps = []
    # 어댑터 선택은 세기로 (3.2)
    if len(body.images) >= 2:
        product.adapter = "조각형"
        product.units, product.ad = from_pieces(body, cache, out)
    else:
        product.adapter = "통이미지형"
        url = body.images[0]
        im = Image.open(io.BytesIO(fetch(url, cache))).convert("RGB")
        product.units, product.ad, ink, gaps = from_whole_image(url, im, out)

    apply_tags(product.units, opts)
    post = gate.post_check(product, ink_coverage=ink, gap_stats=gaps)
    for r in verdict.reasons:
        post.fail(r)
    post.notes = verdict.notes + post.notes
    return Work(product=product, verdict=post, ink_coverage=ink)


def convert_url(url: str, workdir: Path, cache: Path, meta: Meta | None = None) -> Work:
    """엑셀 없이 통이미지 URL 하나만으로 — 지금 바로 시험해 보기 위한 입구."""
    out = workdir
    out.mkdir(parents=True, exist_ok=True)
    im = Image.open(io.BytesIO(fetch(url, cache))).convert("RGB")
    product = Product(meta=meta or Meta(), adapter="통이미지형")
    product.units, product.ad, ink, gaps = from_whole_image(url, im, out)
    apply_tags(product.units, product.meta.options)
    return Work(product=product, verdict=gate.post_check(product, ink, gaps), ink_coverage=ink)
