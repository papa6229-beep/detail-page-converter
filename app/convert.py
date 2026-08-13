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
from slicer.gaps import split_gaps
from slicer.geometry import Rect, union_all
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


def _distance(a: Rect, b: Rect) -> int:
    """두 사각형 사이의 거리. 겹치면 0."""
    dx = max(a.x0 - b.x1, b.x0 - a.x1, 0)
    dy = max(a.y0 - b.y1, b.y0 - a.y1, 0)
    return dx + dy


def from_whole_image(url: str, im: Image.Image, out: Path) -> tuple[list[Unit], list[str], float, list]:
    """통이미지형 — 분할기로 유닛 배열을 얻는다."""
    arr = np.asarray(im.convert("RGB"))
    result = slice_image(arr)
    cfg = CutConfig()
    bg = result.sections[0].bg if result.sections else (255, 255, 255)

    def _thin(parts) -> int:
        """그 유닛 안에서 '글줄'이라 부를 높이.

        페이지 전체의 높이 분포로 임계값을 잡으려다 실패했다 — 광고 구간에
        1~2px 잔여 조각이 섞여 있어 분포의 가장 큰 틈이 엉뚱한 바닥에 생겼다.
        유닛 안에서 재면 그런 잡음이 끼지 않는다.
        """
        return max(2, int(0.3 * max(p.h for p in parts)))

    def _tail(parts):
        out = []
        rest = list(parts)
        while len(rest) > 1 and rest[-1].h <= _thin(parts):
            out.insert(0, rest.pop())
        return rest, out

    def _head(parts):
        out = []
        rest = list(parts)
        # 2px 짜리 잔여 조각은 글줄이 아니다. 위쪽을 볼 때는 특히 조심해야 한다 —
        # 광고컷 맨 위에 낀 얇은 띠를 캡션으로 오해하면 광고 구간 전체가 사라진다.
        while len(rest) > 1 and 6 <= rest[0].h <= _thin(parts):
            out.append(rest.pop(0))
        return rest, out

    # 캡션이 그림 위인지 아래인지는 **페이지마다 하나로 정해져 있다** (4.3).
    # 유닛마다 따로 판단하면 광고컷 조각 하나에 끌려 전체가 뒤집힌다. 실제로 그랬다 —
    # 텐가에서 2px 조각 하나를 캡션으로 읽어 광고 구간이 통째로 날아갔다.
    # 그러니 페이지 전체를 한 번 보고 어느 쪽인지 정한 다음, 그 쪽으로만 가른다.
    below = sum(1 for u in result.units if _tail(sorted(u.parts, key=lambda p: p.y0))[1])
    above = sum(1 for u in result.units if _head(sorted(u.parts, key=lambda p: p.y0))[1])
    caption_side = _tail if below or not above else _head

    def _strip_headings(rest):
        """캡션 **반대쪽** 끝에 붙은 납작한 글줄은 그림이 아니다.

        캡션은 페이지가 정한 한쪽에서만 나온다. 그러면 반대쪽에 붙은 글줄은
        갈 곳이 없어 그림에 그대로 구워진다 — 트리니티의 사진마다 위에 얹힌
        `모에 구멍 트리니티` 라벨과 그 밑줄이 그랬다.

        높이만 보면 안 된다. 텐가 첫 칸 위의 `SILKY Ⅱ [シルキー2]` 라벨은
        252×48 이라 얇지만 납작하지 않고, 잘라내면 광고 구간의 라벨 줄이 사라진다.
        **글줄은 납작하다** — 이미 열을 찾을 때 쓰는 바로 그 잣대다.
        """
        thin = _thin(rest)
        take = (lambda xs: xs[0]) if caption_side is _tail else (lambda xs: xs[-1])
        while len(rest) > 1:
            edge = take(rest)
            if not (6 <= edge.h <= thin and edge.w > CutConfig().max_line_aspect * edge.h):
                break
            rest = rest[1:] if caption_side is _tail else rest[:-1]
        return rest

    def split_parts(u):
        rest, caps = caption_side(sorted(u.parts, key=lambda p: p.y0))
        return _strip_headings(rest), caps

    # 첫 캡션이 나오는 지점부터 설명 구간, 그 위가 상단 광고 구간 (3.1)
    prepared = [(u, *split_parts(u)) for u in result.units]
    with_cap = [(u, p, c) for u, p, c in prepared if c]
    first = with_cap[0][0].rect.y0 if with_cap else arr.shape[0]
    ad = _ad_blocks(arr, im, first, bg, cfg, out)

    # 광고 구간 아래는 **캡션이 있든 없든 전부 유닛이다.**
    # 예전에는 캡션이 붙은 것만 내보냈다. 텐가는 열두 개가 모두 캡션을 가져서
    # 티가 안 났지만, 트리니티에서는 1777px 짜리 사진을 비롯해 큰 그림들이
    # 통째로 사라졌다. 없는 것은 유닛이 아니라 캡션이다 (3.1).
    main = [t for t in prepared if t[0].rect.y0 >= first]
    if not main:
        return [], ad, result.ink_coverage, result.gap_stats

    # 페이지 안에서 '그림'이라 부를 크기. 정하는 것이 아니라 세는 것이다 —
    # 높이 분포가 두 무리로 갈리면 그 사이가 경계고, 안 갈리면 전부 그림이다.
    scale = split_gaps([t[0].rect.h for t in main])
    floor = scale.threshold if scale.separated else 0
    solid = [t for t in main if t[0].rect.h > floor]
    scraps = [t for t in main if t[0].rect.h <= floor]
    if not solid:
        solid, scraps = main, []

    #: 유닛마다 {빨아들일 사각형들, 캡션이 될 사각형들}
    absorbed: dict[int, list[Rect]] = {i: [] for i in range(len(solid))}
    extra_caps: dict[int, list[Rect]] = {i: [] for i in range(len(solid))}
    # 유닛의 '그림'은 가장 넓은 조각이다. 붙일 곳을 고를 때는 유닛 사각형이 아니라
    # 이 그림과 **같은 줄에 놓였는지**로 본다. 사각형으로 보면 위 구간의 라벨 줄까지
    # 끌어와 그림 폭이 두 배가 된다 — 텐가 첫 유닛이 그렇게 망가졌다.
    arts = [max(p, key=lambda r: r.area) for _u, p, _c in solid]
    for su, _p, _c in scraps:
        beside = [k for k, a in enumerate(arts) if su.rect.y0 <= a.y1 and a.y0 <= su.rect.y1]
        if not beside:
            continue  # 어느 그림과도 줄이 겹치지 않으면 붙일 곳이 없다
        j = min(beside, key=lambda k: _distance(arts[k], su.rect))
        art = arts[j]
        # 그림 옆에 **멀찍이** 떨어져 있으면 그건 캡션이다(트리니티 중간의
        # `"모에 구멍 트리니티" 정면 사진`). 딱 붙어 있으면 그림의 일부다
        # (치수선의 `72mm` 처럼). 거리는 그 조각의 키로 잰다 — px 를 못박지 않는다.
        gap = max(art.x0 - su.rect.x1, su.rect.x0 - art.x1, 0)
        (extra_caps if gap > su.rect.h else absorbed)[j].append(su.rect)

    # 한 줄에 나란히 놓인, 캡션 없는 것들은 **원본에서 한 줄이었다.**
    # 따로 떼면 아이콘 네 개가 페이지 폭짜리 그림 네 장이 된다. 붙여 두면
    # 저자가 늘어놓은 그대로 한 줄로 실린다. 캡션이 붙은 것은 건드리지 않는다 —
    # 텐가의 2열 그리드는 좌우가 각각 제 캡션을 가진 별개의 유닛이다.
    # 위아래는 **남은 조각**이 정한다. 유닛 사각형으로 잡으면 떼어낸 라벨 줄이
    # 그림에 그대로 남는다. 좌우는 유닛 폭을 살린다.
    boxes = [union_all([Rect(u.rect.x0, p[0].y0, u.rect.x1, p[-1].y1)] + absorbed[i])
             for i, (u, p, _c) in enumerate(solid)]
    rows: list[list[int]] = []
    for i, (_u, _p, caps) in enumerate(solid):
        prev = rows[-1][-1] if rows else None
        same_row = (
            prev is not None
            and not caps and not extra_caps[i]
            and not solid[prev][2] and not extra_caps[prev]
            and boxes[i].y0 <= boxes[prev].y1 and boxes[prev].y0 <= boxes[i].y1
        )
        rows[-1].append(i) if same_row else rows.append([i])

    merged = []
    for row in rows:
        head = row[0]
        u, parts, caps = solid[head]
        merged.append((u, parts, caps, union_all([boxes[i] for i in row]),
                       [b for i in row for b in extra_caps[i]]))

    units: list[Unit] = []
    for i, (u, parts, caps, art_box, side_caps) in enumerate(merged):
        art = im.crop((art_box.x0, art_box.y0, art_box.x1 + 1, art_box.y1 + 1))
        name = _save(art, out, f"unit_{i:02d}.jpg")

        crop_name = ""
        cap_boxes = list(caps) + side_caps
        if cap_boxes:
            box = union_all(cap_boxes)
            # 캡션이 유닛 폭 안에 있으면 폭을 그대로 살린다 — 글줄 앞뒤 여백이
            # 있어야 사람도 모델도 읽기 좋다.
            x0, x1 = (u.rect.x0, u.rect.x1) if box.x0 >= u.rect.x0 and box.x1 <= u.rect.x1 else (box.x0, box.x1)
            strip = im.crop((x0, box.y0, x1 + 1, box.y1 + 1))
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
            price=row.price, options=opts, option_numbers=row.option_numbers,
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


#: 붙임장 한 칸의 변 길이. 320 이면 500px 원본의 큼직한 빨간 치수 글씨가 살아남는다.
SHEET_CELL = 320
SHEET_COLS = 3
SHEET_MAX = 12


def contact_sheet(paths: list[Path], cell: int = SHEET_CELL, cols: int = SHEET_COLS) -> bytes:
    """상품 사진들을 한 장에 모아 붙인다.

    치수가 그림 픽셀로만 있는 원본이 흔하다. 그걸 읽으려면 사진을 모델에 보내야 하는데,
    여섯 장을 따로 보내면 여섯 장 값을 문다. **한 장으로 붙이면 넓이만큼만** 문다 —
    320px 칸으로 줄이니 여섯 장이 두 장 값도 안 된다. 올려보내는 덩어리도 하나다.

    번호는 굳이 안 적는다. 어느 칸에서 읽었는지는 우리가 쓸 데가 없다.
    """
    paths = paths[:SHEET_MAX]
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, max(rows, 1) * cell), "white")
    for i, p in enumerate(paths):
        with Image.open(p) as im:
            im = im.convert("RGB")
            im.thumbnail((cell, cell), Image.LANCZOS)
            x = (i % cols) * cell + (cell - im.width) // 2
            y = (i // cols) * cell + (cell - im.height) // 2
            sheet.paste(im, (x, y))
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=80)
    return buf.getvalue()
