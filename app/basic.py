"""기본형 — 잘 만들어진 원본을 뜯어서 우리 디자인으로 다시 세운다.

단순형과 **전제가 반대다.**

    단순형   원본이 허접하다 → 원본 이미지를 손대지 않고 순서대로 싣는다
    기본형   원본이 이미 완성된 디자인이다 → 그대로 실으면 남의 쇼핑몰처럼 보인다

사장님 말: *"기존 기본형의 디자인 냄새가 아예 없어야 한다."*

그래서 여기서는 원본을 **재료로만** 쓴다. 컬러 배경 위에 얹힌 원본 대표컷을 버리고,
페이지 어딘가에 있는 **흰 바탕 제품 단독컷**을 찾아 새 대표컷으로 세운다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from slicer import Rect, slice_image

#: 대표컷이 되려면 이만한 크기는 돼야 한다. 페이지 폭에 대한 비율로 잰다 —
#: px 로 못박으면 폭이 다른 원본에서 그대로 어긋난다.
MIN_SIDE_FRAC = 0.25
#: 글자꼴 덩어리를 셀 때 이 크기로 줄여서 본다. 글자가 뭉개지지 않으면서 빠르다.
CC_SCALE = 200


@dataclass
class Shot:
    """대표컷 후보 한 장과, 그것을 두고 잰 값들."""

    rect: Rect
    white: float      #: 흰 바탕이 차지하는 비율
    color: float      #: 유채색 화소 비율 — 컬러 배경·배너를 가른다
    ink: float        #: 어두운 화소 비율 — 제품이 화면을 얼마나 채우는가
    letters: int      #: 글자꼴 작은 덩어리 개수 — 검은 본문 글이 구워져 있는가
    design: float     #: 유채색이 가장 빽빽한 가로 띠 — 분홍 제목·컬러 배경이 있는가
    solo: float       #: 가장 큰 덩어리가 어두운 화소에서 차지하는 몫 — 제품이 하나인가
    area: int

    @property
    def size(self) -> tuple[int, int]:
        return self.rect.x1 - self.rect.x0 + 1, self.rect.y1 - self.rect.y0 + 1

    @property
    def product_pixels(self) -> float:
        """제품이 실제로 찍힌 넓이. **화면 크기가 아니라 제품 크기다.**

        충전 케이블 컷은 726×774 로 크지만 제품이 흰 바탕에 조그맣게 놓여 있어
        잉크가 8% 뿐이다. 제품 단독컷은 608×455 로 작아도 31% 를 채운다.
        큰 것을 고르면 케이블을 대표컷으로 쓴다.
        """
        return self.area * self.ink


def _stats(arr: np.ndarray, r: Rect) -> Shot:
    """조각 하나를 재기만 한다. 판정은 여기서 하지 않는다."""
    crop = arr[r.y0 : r.y1 + 1, r.x0 : r.x1 + 1].astype(np.int32)
    lum = (crop[..., 0] * 299 + crop[..., 1] * 587 + crop[..., 2] * 114) // 1000
    sat = crop.max(2) - crop.min(2)
    white = float((lum >= 232).mean())
    tint = (sat >= 45) & (lum < 245)
    color = float(tint.mean())
    ink = float(((lum < 115) & (sat < 40)).mean())
    letters, solo = _blobs(lum)
    area = (r.x1 - r.x0 + 1) * (r.y1 - r.y0 + 1)
    return Shot(r, white, color, ink, letters, _densest(tint), solo, area)


def _densest(mask: np.ndarray) -> float:
    """유채색이 **가장 빽빽하게 몰린 가로 띠**의 밀도.

    조각 전체 비율로는 못 잡는다. `03 제품 사이즈` 분홍 제목은 699×1823 조각에서
    전체의 1.3% 밖에 안 되어 묽어지지만, 그 제목이 놓인 줄만 보면 32% 다.
    **디자인 글은 넓게 흩어지지 않고 한 띠에 몰려 있다** — 그게 사진과 다른 점이다.

    핑거위글 실측: 깨끗한 사진 0.4~4.2% ↔ 디자인 글이 박힌 것 23~100%.
    """
    rows = mask.mean(1)
    k = max(1, len(rows) // 60)  # 제목은 한 줄이 아니라 띠다. 조각 높이의 1/60 로 묶는다
    if len(rows) < k:
        return float(rows.max()) if len(rows) else 0.0
    return float(np.convolve(rows, np.ones(k) / k, mode="valid").max())


def _blobs(lum: np.ndarray) -> tuple[int, float]:
    """어두운 덩어리를 세어 두 가지를 돌려준다.

        글자꼴 개수   작은 덩어리가 몇 개인가 — 글이 구워져 있으면 수십 개다
        한 덩어리 몫   가장 큰 덩어리가 어두운 화소의 얼마인가 — 제품이 하나인가

    **글자를 높이나 비율로 가르면 안 된다.** 여러 줄짜리 문단은 사진만큼 높고,
    가로로 긴 사진은 글줄만큼 납작하다. 개수는 그런 것에 안 흔들린다.

    **한 덩어리 몫**은 대표컷이 누끼컷인지를 가른다 — 제품 셋이 쌓인 사이즈 구간은
    36%, 손이 제품을 든 컷은 49%, 제품 단독컷은 100% 였다.

    scipy 가 없어도 된다. 200px 로 줄여 놓고 줄 단위 구간을 이어붙이면 한 번에 끝난다.
    """
    h, w = lum.shape
    if min(h, w) < 8:
        return 0, 0.0
    step = max(1, max(h, w) // CC_SCALE)
    small = lum[::step, ::step]
    dark = small < 160
    if not dark.any():
        return 0, 0.0

    # 같은 줄에서 이어진 구간(run)을 먼저 뽑고, 위아래 줄의 run 끼리 이어 붙인다.
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    prev: list[tuple[int, int, int]] = []
    sizes: dict[int, int] = {}
    nid = 0
    for y in range(dark.shape[0]):
        row = dark[y]
        if not row.any():
            prev = []
            continue
        edges = np.flatnonzero(np.diff(np.concatenate(([0], row.view(np.int8), [0]))))
        cur = []
        for s, e in zip(edges[::2], edges[1::2]):
            parent[nid] = nid
            sizes[nid] = int(e - s)
            for ps, pe, pid in prev:
                if s < pe and ps < e:  # 위 줄의 구간과 겹치면 같은 덩어리
                    union(pid, nid)
            cur.append((int(s), int(e), nid))
            nid += 1
        prev = cur

    total: dict[int, int] = {}
    for i, n in sizes.items():
        total[find(i)] = total.get(find(i), 0) + n
    if not total:
        return 0, 0.0
    biggest = max(total.values())
    # 가장 큰 덩어리에 견주어 **작은** 것만 글자로 센다. 절대 크기로 자르면
    # 큰 그림에서는 제품의 그림자 조각이, 작은 그림에서는 글자가 새어 나간다.
    letters = sum(1 for n in total.values() if 2 <= n <= max(6, biggest * 0.12))
    return letters, biggest / sum(total.values())


def shots(arr: np.ndarray) -> list[Shot]:
    """통이미지 한 장에서 대표컷 후보를 전부 재서 돌려준다."""
    w = arr.shape[1]
    floor = int(w * MIN_SIDE_FRAC)
    out = []
    for u in slice_image(arr).units:
        r = u.rect
        if min(r.x1 - r.x0 + 1, r.y1 - r.y0 + 1) < floor:
            continue
        out.append(_stats(arr, r))
    return out


def pick_hero(cands: list[Shot]) -> Shot | None:
    """대표컷 하나를 고른다. 판정하지 않고 **그 페이지 안에서 견준다.**

    원본 대표컷은 못 쓴다 — 기본형 원본은 하나같이 컬러 배경 위에 제품을 얹어
    놓아서, 그대로 가져오면 새 쇼핑몰에 남의 디자인이 따라 들어온다.
    그래서 페이지 어딘가의 **흰 바탕 제품 단독컷**을 찾아 세운다.

    먼저 `pick_photos` 로 쓸 만한 사진만 남긴다(디자인 글·글 구간·상자 제외).
    거기서 **제품이 한 덩어리로 찍힌 것**만 추리고, 남은 것 중 제품이 가장 크게
    찍힌 것을 쓴다. 화면이 큰 것이 아니다 — 충전 케이블 컷(726×774)이 제품
    단독컷(608×455)보다 크지만 제품은 훨씬 작다.

    **깨끗함은 그 페이지 안에서만 뜻이 있다.** 상품 둘을 재보면 절대값으로는
    못 가른다 —

        핑거위글  제품 단독컷 글자꼴 0·0·2   거치대+리모컨 23   ← 23 을 빼야 한다
        글랜스    제품 단독컷 글자꼴 11·17·22                  ← 22 를 넣어야 한다

    같은 숫자가 두 답을 낸다. 그래서 그 페이지에서 가장 깨끗한 컷을 바닥으로
    삼고 거기서 얼마까지 봐줄지로 정한다.

    **흰 바탕 비율은 안 본다.** 분할기가 이미 내용에 딱 맞게 잘라내므로, 그 값은
    배경이 아니라 실루엣이 얼마나 들쭉날쭉한가를 잰다. 잣대가 아니다.

    두 컷이 똑같이 깨끗하면 어느 쪽을 골라도 된다 — 핑거위글에는 608×455 와
    697×360 이 둘 다 제품 단독컷이었다. 잘린 폭이 달라도 HERO 자리에 넣을 때
    다시 여백을 잡으므로 결과가 같다.

    **여기 숫자들은 아직 상품 둘에서 나왔다.** 사례가 늘면 다시 잰다.
    """
    photos = [c for c in pick_photos(cands) if c.solo >= SOLO]
    if not photos:
        return None
    # **깨끗함은 그 페이지 안에서만 뜻이 있다.** 절대값으로는 못 가른다 —
    # 핑거위글에서는 글자꼴 23(거치대+리모컨)을 빼야 하는데, 글랜스에서는
    # 22(금색 캡 접사)를 넣어야 그나마 후보가 생긴다. 같은 숫자가 두 답을 낸다.
    floor = min(c.letters for c in photos)
    clean = [c for c in photos if c.letters <= floor + CLEAN_ROOM]
    return max(clean, key=lambda c: c.product_pixels)


#: 강조색. 고도몰 생성기의 기본값을 그대로 쓴다 (`DEFAULT_THEME_COLOR`).
ACCENT = "#E11D48"

#: 이 CSS 도 **남의 페이지 안에서 산다** (#18). 선택자는 전부 `.gpage` 로 시작한다.
#: 치수는 눈대중이 아니라 `PreviewGodo.tsx` 에 박힌 값을 그대로 옮겼다 —
#: 폭 800 · Pretendard · 좌우 여백 50 · 메인이미지 700 · 제목 52px · 섹션제목 72px.
CSS = """
.gpage{--accent:#E11D48;--ink:#111827;--mute:#6b7280;--soft:#9ca3af;--body:#4b5563;
 --plate:#f3f4f6;--line:#e5e7eb;
 width:800px;max-width:100%;margin:0 auto;background:#fff;color:var(--ink);
 font-family:"Pretendard","Pretendard Variable",-apple-system,BlinkMacSystemFont,
 "Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",system-ui,sans-serif;
 -webkit-font-smoothing:antialiased;word-break:keep-all;overflow-wrap:break-word}
.gpage,.gpage *{box-sizing:border-box}
.gpage p,.gpage h1,.gpage h2{margin:0}
.gpage img{display:block;width:100%;height:auto}
.gpage .dot{display:inline-block;border-radius:50%;flex:none;background:var(--accent)}
.gpage .hero{padding:56px 50px}
.gpage .hero__maker{text-align:right;margin-bottom:12px;font-size:24px;font-weight:900;letter-spacing:-.025em}
.gpage .hero__wrap{position:relative}
.gpage .hero__main{width:700px;margin:0 auto;border:1px solid var(--line);overflow:hidden}
.gpage .hero__name{margin-top:32px;font-size:52px;line-height:1.05;font-weight:900;
 letter-spacing:-.025em;max-width:460px;white-space:pre-line}
.gpage .hero__en{margin-top:4px;font-size:20px;font-weight:500;letter-spacing:.15em;
 color:var(--soft);text-transform:uppercase}
.gpage .specs{margin-top:40px;display:flex;flex-direction:column;gap:16px}
.gpage .specs__row{display:flex;gap:16px}
.gpage .spec{width:145px;flex:none;min-width:0}
.gpage .spec__k{display:flex;align-items:center;gap:6px;font-size:14px;font-weight:700;
 color:var(--mute);white-space:nowrap}
.gpage .spec__rule{height:2px;background:var(--ink);margin:8px 0}
.gpage .spec__v{font-size:15px;font-weight:900;line-height:1.375}
/* 패키지는 히어로 오른쪽 아래에 얹는다. 생성기에서는 마우스로 옮기지만 여기서는
   기본 자리(x 468 · y 430 · 210×250)를 그대로 쓴다 — 원본에 없으면 아예 안 그린다. */
.gpage .pkg{position:absolute;left:468px;top:430px;width:210px;height:250px;
 display:flex;flex-direction:column;z-index:2}
.gpage .pkg__box{flex:1;border:2px solid var(--ink);border-bottom:0;background:#fff;
 display:flex;align-items:center;justify-content:center;overflow:hidden}
.gpage .pkg__box img{width:100%;height:100%;object-fit:contain;padding:8px}
.gpage .pkg__bar{background:var(--ink);color:#fff;text-align:center;font-weight:900;
 font-size:14px;letter-spacing:.025em;padding:8px 0}
.gpage .sec{padding:56px 50px;position:relative}
.gpage .sec__h{margin-top:16px;font-size:72px;line-height:.9;font-weight:900;letter-spacing:-.05em}
.gpage .sec__sub{margin-top:12px;font-size:18px;font-weight:700;color:var(--mute)}
.gpage .keys{position:relative;margin-top:10px;min-height:440px}
.gpage .keys__list{position:absolute;right:0;top:0;width:360px;display:flex;
 flex-direction:column;gap:52px}
.gpage .key{background:var(--plate);border-radius:12px;padding:16px 20px}
.gpage .key__t{display:flex;align-items:center;gap:8px;margin-bottom:6px;
 font-size:18px;font-weight:900}
.gpage .key__d{font-size:14px;font-weight:500;color:var(--body);line-height:1.375}
.gpage .keys__fig{position:absolute;left:0;top:0;width:320px;height:380px}
.gpage .keys__fig img{width:100%;height:100%;object-fit:contain}
.gpage .rule{margin:0 50px;height:1px;background:var(--ink)}
.gpage .pt__t{display:flex;align-items:center;gap:8px;margin-top:12px;font-size:24px;font-weight:900}
.gpage .pt{display:flex;flex-direction:column;gap:52px;margin-top:10px}
.gpage .pt__b{display:flex;flex-direction:column;gap:16px}
.gpage .pt__d{font-size:16px;font-weight:500;color:var(--body);line-height:1.625;
 max-width:420px;white-space:pre-line}
.gpage .pt__d--bar{border-left:4px solid var(--accent);border-radius:999px 0 0 999px;
 padding:2px 0 2px 16px;max-width:436px}
.gpage .pt__f{margin:0;border:1px solid var(--line);overflow:hidden}
.gpage .sec--size{background:#f9fafb}
.gpage .sec__h--flat{margin-top:0}
.gpage .size__n{display:flex;align-items:center;gap:8px;margin-top:8px;font-size:16px;
 font-weight:700;color:var(--mute)}
.gpage .size__w{display:flex;justify-content:center;margin-top:32px}
.gpage .size__pill{display:inline-flex;align-items:center;gap:16px;padding:16px 40px;
 border-radius:999px;border:2px solid var(--accent);background:#fff}
.gpage .size__w span{display:inline-block}
.gpage .size__wk{font-size:14px;font-weight:700;color:var(--soft);letter-spacing:.2em;
 text-transform:uppercase}
.gpage .size__wv{font-size:24px;font-weight:900;margin-left:16px}
.gpage .size__w{align-items:center}
.gpage .size__f{margin:32px 0 0;border:1px solid var(--line);background:#fff;overflow:hidden}
.gpage .band{border-top:1px solid #d1d5db;border-bottom:1px solid #d1d5db;padding:16px 0;
 overflow:hidden;white-space:nowrap;text-align:center;color:var(--soft);
 font-size:14px;font-weight:500;letter-spacing:.25em;text-transform:uppercase}
.gpage .foot{padding:64px 0;text-align:center;background:var(--ink)}
.gpage .foot__b{font-size:24px;font-weight:900;color:var(--accent)}
.gpage .foot__c{margin-top:12px;color:#6b7280;font-size:12px;letter-spacing:.2em;font-weight:500}
@media (max-width:800px){
 .gpage .hero,.gpage .sec{padding-left:22px;padding-right:22px}
 .gpage .hero__main{width:100%}
 .gpage .hero__name{font-size:34px;max-width:100%}
 .gpage .sec__h{font-size:44px}
 .gpage .pkg{position:static;width:160px;height:190px;margin:24px 0 0 auto}
 .gpage .keys{min-height:0}
 .gpage .keys__list,.gpage .keys__fig{position:static;width:100%;gap:16px}
 .gpage .keys__fig{height:260px;margin-bottom:16px}
 .gpage .rule{margin:0 22px}
 .gpage .sec__h{font-size:44px}}
"""


@dataclass
class Page:
    """기본형 한 장이 채워야 하는 칸. **고도몰 생성기의 칸과 같은 이름**이다.

    사장님이 항목을 다섯으로 줄여 고정하셨다 — `타입 · 재질 · 치수 · 무게 · 전원`.
    원본 요약정보에는 `특징` `색상` `메이커` 도 있지만 쓰지 않는다.
    브랜드는 우상단에 따로 박히고, `특징` 은 KEY FEATURE 부제로 간다.

    비어 있는 칸은 **그리지 않는다.** 없는 것을 지어내지 않는 것이 이 프로젝트의
    규칙이고, 여기서는 화면에서도 그렇게 한다.
    """

    name_kr: str = ""
    name_en: str = ""
    maker: str = ""
    #: `타입` `재질` `치수` `무게` `전원` `특징` — 원본이 적어 놓은 그대로
    spec: dict[str, str] = field(default_factory=dict)
    #: KEY FEATURE 세 칸 — (제목, 한 줄 설명)
    keys: list[tuple[str, str]] = field(default_factory=list)
    main: Path | None = None
    package: Path | None = None
    feature: Path | None = None
    #: POINT 01 · 02 — (구간 제목, [(설명, 그림)] 최대 3덩어리)
    #: 고도몰 생성기가 정한 칸 수다. 원본의 특징 구간이 몇 덩어리든 여기 여섯에 담긴다.
    point1: tuple[str, list[tuple[str, Path | None]]] = ("", [])
    point2: tuple[str, list[tuple[str, Path | None]]] = ("", [])
    #: 사이즈 도해. 무게는 그림 위에 알약 모양으로 얹힌다.
    size: Path | None = None


#: 사장님이 고정한 다섯 항목. 1행 셋, 2행 둘 — 2행을 왼쪽에 두는 것은
#: 오른쪽 패키지 상자에 안 가리게 하려는 것이다 (`PreviewGodo.tsx` 주석).
SPEC_ROWS = (("타입", "재질", "치수"), ("무게", "전원"))
#: 치수는 읽지 않는다. 옵션마다 다르고 그림에서 재면 부정확하다 — 고정값이다.
SIZE_FIXED = "상세페이지 참조"


def render_page(page: Page) -> str:
    """기본형 한 장을 HTML 로. 단순형 렌더러와 **완전히 따로** 둔다.

    고도몰 쪽 보고서의 금지선 5번과 같은 이유다 — *"기본형과 단순형의 렌더러를
    합치지 말 것. 격리가 회귀 0을 만든 장치다."* 우리도 단순형 49개를 지켜야 한다.
    """
    from .render import data_uri, esc

    def dot(px: int) -> str:
        return f'<span class="dot" style="width:{px}px;height:{px}px"></span>'

    def img(path: Path | None, alt: str) -> str:
        return f'<img src="{data_uri(path)}" alt="{esc(alt)}">' if path else ""

    out = [f"<style>{CSS}</style>", '<div class="gpage">']

    # ① HERO — 제조사 우상단 · 누끼컷 700 중앙 · 상품명 · 영문명 · 스펙 · 패키지
    out.append('<header class="hero">')
    if page.maker:
        out.append(f'<p class="hero__maker">{esc(page.maker)}</p>')
    out.append('<div class="hero__wrap">')
    if page.main:
        out.append(f'<div class="hero__main">{img(page.main, page.name_kr)}</div>')
    out.append(f'<h1 class="hero__name">{esc(page.name_kr)}</h1>')
    if page.name_en:
        out.append(f'<p class="hero__en">{esc(page.name_en)}</p>')

    rows = [[(k, page.spec[k]) for k in row if page.spec.get(k)] for row in SPEC_ROWS]
    if any(rows):
        out.append('<div class="specs">')
        for row in rows:
            if not row:
                continue
            out.append('<div class="specs__row">')
            for k, v in row:
                out.append(
                    f'<div class="spec"><p class="spec__k">{esc(k)}{dot(9)}</p>'
                    f'<div class="spec__rule"></div>'
                    f'<p class="spec__v">{esc(v)}</p></div>'
                )
            out.append("</div>")
        out.append("</div>")

    if page.package:
        out.append(
            f'<div class="pkg"><div class="pkg__box">{img(page.package, "패키지")}</div>'
            f'<div class="pkg__bar">package desing</div></div>'
        )
    out.append("</div></header>")

    # ② KEY FEATURE — 좌 이미지 · 우 세 칸. 부제는 요약정보의 `특징`.
    out.append('<section class="sec">')
    out.append(dot(22))
    out.append('<h2 class="sec__h">KEY<br>FEATURE</h2>')
    if page.spec.get("특징"):
        out.append(f'<p class="sec__sub">{esc(page.spec["특징"])}</p>')
    out.append('<div class="keys">')
    out.append('<div class="keys__list">')
    for title, desc in page.keys[:3]:
        out.append(f'<div class="key"><p class="key__t">{dot(12)}{esc(title)}</p>')
        if desc:
            out.append(f'<p class="key__d">{esc(desc)}</p>')
        out.append("</div>")
    out.append("</div>")
    if page.feature:
        out.append(f'<div class="keys__fig">{img(page.feature, page.name_kr)}</div>')
    out.append("</div></section>")

    # ③ 영문명 띠 — 구간을 가르는 장식이다. KEY FEATURE 아래와 SIZE 위 두 곳.
    band = f'<div class="band">{esc("  ·  ".join([page.name_en] * 6))}</div>' if page.name_en else ""
    out.append(band)

    # ④ POINT 01 · 02 — 제목 · 부제 · (설명 + 그림) 덩어리들
    for n, (title, blocks) in (("01", page.point1), ("02", page.point2)):
        blocks = [(d, i) for d, i in blocks if d or i]
        if not (title or blocks):
            continue
        if n == "02":
            out.append('<div class="rule"></div>')
        out.append('<section class="sec">')
        out.append(dot(22))
        out.append(f'<h2 class="sec__h">Point {n}</h2>')
        if title:
            out.append(f'<p class="pt__t">{esc(title)}{dot(12)}</p>')
        out.append('<div class="pt">')
        for i, (desc, im) in enumerate(blocks):
            out.append('<div class="pt__b">')
            if desc:
                # 첫 덩어리 위에는 제목이 있어 그냥 글이고, 아래 덩어리들은 허전해서
                # 강조색 세로 막대를 붙인다 (생성기의 그 콜아웃).
                cls = "pt__d" if i == 0 else "pt__d pt__d--bar"
                out.append(f'<p class="{cls}">{esc(desc)}</p>')
            if im:
                out.append(f'<figure class="pt__f">{img(im, title or page.name_kr)}</figure>')
            out.append("</div>")
        out.append("</div></section>")

    # ⑤ SIZE — 무게 알약이 그림 **위**에 온다 (사장님 확정 사항)
    if page.size or page.spec.get("무게"):
        out.append(band)
        out.append('<section class="sec sec--size">')
        out.append('<h2 class="sec__h sec__h--flat">SIZE</h2>')
        out.append(f'<p class="size__n">측정 방법에 따라 약간의 오차가 있을 수 있습니다{dot(12)}</p>')
        if page.spec.get("무게"):
            out.append(
                f'<div class="size__w"><span class="size__pill">'
                f'<span class="size__wk">Weight</span>'
                f'<span class="size__wv">{esc(page.spec["무게"])}</span></span></div>'
            )
        if page.size:
            out.append(f'<figure class="size__f">{img(page.size, "사이즈")}</figure>')
        out.append("</section>")

    out.append(
        '<footer class="foot"><p class="foot__b">GODO MALL</p>'
        '<p class="foot__c">COPYRIGHT © GODO MALL. ALL RIGHTS RESERVED.</p></footer>'
    )
    out.append("</div>")
    return "\n".join(x for x in out if x)


#: 대표컷이 되려면 제품이 한 덩어리로 찍혀 있어야 한다. 실측 —
#: 제품 셋이 쌓인 사이즈 구간 36% · 손이 든 컷 49% ↔ 제품 단독컷 95~100%.
SOLO = 0.9
#: 그 페이지에서 가장 깨끗한 컷보다 이만큼까지는 같이 본다. 딱 하나만 남기면
#: 워터마크 하나로 답이 뒤집힌다.
CLEAN_ROOM = 10

#: 원본 디자인의 색 글씨·배경이 박혀 있다고 보는 자리. 핑거위글 실측 —
#: 깨끗한 사진 0.4·0.6·0.6·4.2% ↔ 디자인이 박힌 것 23·31·31·32·38·61·62·100%.
#: **8.8% 와 22.9% 사이가 통째로 비어 있어** 어디에 그어도 답이 같다.
DESIGN_INK = 0.15

#: 글 구간과 사진을 가르는 자리. 핑거위글 조각 열넷에서 **23 과 51 사이가 비어 있다** —
#: 사진 쪽은 0·0·0·2·2·2·7·14·22·23, 글 구간 쪽은 51·53·89·125.
TEXT_BAND = 40


def pick_photos(cands: list[Shot]) -> list[Shot]:
    """POINT 칸에 쓸 사진들. 대표컷보다 잣대가 헐거워야 한다.

    깨끗한 누끼컷은 한 페이지에 두세 장뿐이라 여섯 칸을 못 채운다. POINT 사진은
    손이 들고 있어도, 거치대에 얹혀 있어도, 작은 주석이 붙어 있어도 쓸 수 있다.
    **못 쓰는 것은 세 가지뿐이다.**

        글 구간이다      원본 디자인의 글이 통째로 딸려 온다 (글자꼴 51개 이상)
        컬러 배경·배너다  원본 쇼핑몰의 색이 따라 들어온다
        상자다          제 네모를 꽉 채운 검은 덩어리 — 패키지 자리로 간다

    순서는 원본 그대로 둔다. 사장님이 *"동일한 사진 배치순을 쓰지 않고 변화를 줄
    수 있으면 주는걸로"* 하셨지만, 그건 **무엇이 더 적절한지 알 때** 할 일이다.
    사례가 하나뿐인 지금 순서를 흔들면 근거 없이 흔드는 것이다.
    """
    return [
        c
        for c in cands
        if c.design < DESIGN_INK and c.letters < TEXT_BAND and 0.03 <= c.ink <= 0.75
    ]


#: 모델에게 주는 지시. **자르기는 수학, 이해는 AI** — 조각은 우리가 냈고,
#: 어느 조각이 어느 자리에 어울리는지는 모델이 정한다.
#:
#: 사장님 말: *"각 설명에 어울리는 이미지를 골라서 쓰라는거야... 융통성이라고."*
PROMPT = """쇼핑몰 상세페이지를 새 디자인으로 다시 짓는다. 원본에서 **재료만** 가져온다.

원본은 이미 완성된 디자인이라 그대로 옮기면 남의 쇼핑몰이 따라온다.
그림은 골라서 쓰고, 글은 원본이 적어 둔 사실에서만 가져온다.

**보내는 것**

    상품명 · 브랜드 · 원본에 직접 타이핑돼 있던 글 전문
    번호가 붙은 밴드 그림들. 번호 옆 괄호가 그 밴드의 종류다.
    첫 밴드들이 원본 맨 위(대표컷·요약정보·3줄설명·패키지)다.

**할 일 넷**

1. **요약정보** — 원본 맨 위 표에 적힌 그대로 옮긴다.
   `타입` `재질` `무게` `전원` 넷만. 없으면 빈 칸으로 둔다.
   **치수는 옮기지 마라** — 옵션마다 달라 따로 처리한다.

2. **핵심특징 3개** — 원본의 3줄 설명을 바탕으로 짧은 제목과 한 줄 설명을 짓는다.
   3줄이 모자라면 요약정보나 설명 글에서 보탠다. **없는 사실을 지어내지 마라.**
   제목은 한눈에 읽히게 짧게, 설명은 한 줄로.

3. **그림 고르기** — 자리마다 **가장 어울리는 것**을 고른다. 이것이 가장 중요하다.

    main      대표컷. 배경색이 깔린 컷보다 **깨끗한 제품 단독컷**이 어울린다.
              깨끗한 컷이 없으면 그때는 차선을 고르고 `notes` 에 적어라.
    feature   핵심특징 옆에 놓일 컷. 대표컷과 다른 것으로.
    package   패키지 상자가 찍힌 컷. 없으면 비워라.
    size      치수선·수치가 그려진 도해. 없으면 비워라.

4. **Point 01 · 02** — 설명과 그림을 짝지어 최대 3덩어리씩.
   **설명에 어울리는 그림을 붙여라.** 전원 이야기면 케이블이 보이는 컷,
   촉감 이야기면 표면이 보이는 컷. 아무 컷이나 순서대로 붙이지 마라.
   설명은 원본 글에 적힌 사실로만 쓴다.

**밴드 종류와 쓰는 법**

    (PHOTO)    제품컷. 그림 자리에 먼저 쓴다
    (MIXED)    제품에 주석이 붙은 것. 차선으로 쓴다
    (UNKNOWN)  애매한 것. 다른 후보가 없을 때만 쓴다
    (TEXT)     글만 박힌 것. **읽는 근거로만** 쓰고 그림 자리에는 절대 넣지 마라.
               넣으면 같은 문장이 설명으로도 나오고 그림으로도 나와 두 번 실린다.
    (PROMO)    쇼핑몰 홍보 움짤. 아무 자리에도 넣지 말고 근거로도 쓰지 마라.

  Point 블록의 번호는 **그 설명이 가리키는 실제 제품 밴드**여야 한다.
  설명 원문이 박힌 (TEXT) 밴드가 아니다.

**지킬 것**

  · 그림 번호는 **한 번씩만** 쓴다. 같은 컷을 두 자리에 넣지 마라.
  · 쓸 그림이 모자라면 덩어리 수를 줄여라. 억지로 채우지 마라.
  · 원본과 **같은 순서로 늘어놓지 않으면 좋다.** 다만 이건 바람일 뿐이다 —
    어울리는 그림을 고르는 것이 순서보다 앞선다. 쓸 컷이 적으면 원본 순서라도 괜찮다.
  · 가장 중요한 대목 한 군데를 `**이렇게**` 감싼다. 두 낱말 이상, 뜻이 되는 덩어리로.

**돌려줄 것 — JSON 하나. 다른 말은 붙이지 마라.**

```json
{"spec":{"타입":"","재질":"","무게":"","전원":""},
 "keys":[{"t":"제목","d":"한 줄 설명"},{"t":"","d":""},{"t":"","d":""}],
 "main":0,"feature":1,"package":null,"size":null,
 "point1":{"title":"","blocks":[{"i":2,"d":"설명"}]},
 "point2":{"title":"","blocks":[]},
 "notes":["깨끗한 누끼컷이 없어 차선을 썼다"]}
```
"""


def parts_for(name: str, brand: str, typed: str, cuts: list[Path],
              kinds: list[str]) -> list[tuple[str, str]]:
    """모델에 보낼 것을 순서대로 쌓는다 — 글 먼저, 그다음 번호·종류·그림.

    **차단이 아니라 순위다.** 처음에는 쓸 만한 것만 골라 보냈는데, 밴드 21개 중
    3개만 남아서 그림 자리가 거의 비었다. 저쪽 방식은 전부 보내고 종류만 붙인다 —

        (PHOTO)    제품컷. 먼저 쓴다
        (MIXED)    제품에 주석이 붙은 것. 차선
        (UNKNOWN)  애매한 것. 다른 후보가 없을 때만
        (TEXT)     글만 박힌 것. **읽는 근거로만** 쓰고 그림 자리에는 못 넣는다
        (PROMO)    바나나몰 홍보 움짤. 아무 데도 못 넣고 근거로도 안 쓴다

    제품컷을 TEXT 로 오판하지 않는 것이 최우선이라 애매하면 MIXED·UNKNOWN 으로
    남는다. 그러면 모델이 보고 판단할 기회가 있다.
    """
    import base64
    import io

    from PIL import Image

    head = [("text", PROMPT), ("text", f"상품명: {name}\n브랜드: {brand}\n\n원본에 타이핑돼 있던 글:\n{typed}")]
    head.append(("text", f"밴드 {len(cuts)}장을 위에서 아래 순서로 봅니다. 괄호 안이 그 밴드의 종류입니다."))
    for i, p in enumerate(cuts):
        kind = kinds[i] if i < len(kinds) else UNKNOWN_KIND
        head.append(("text", f"[{i}]({kind})" + (" · 원본 맨 위" if i == 0 else "")))
        # 보내기 전에 줄인다. 토큰도 아끼고 전송도 안정된다 — 읽을 글자는 살아 있다.
        with Image.open(p) as im:
            im = im.convert("RGB")
            if max(im.size) > SEND_PX:
                s = SEND_PX / max(im.size)
                im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
        head.append(("image", base64.b64encode(buf.getvalue()).decode()))
    return head


#: 라벨을 못 받았을 때의 기본값. 차단하지 않는다.
UNKNOWN_KIND = "UNKNOWN"
#: 모델에 보낼 때 긴 변을 이만큼으로 줄인다.
SEND_PX = 900


def take(reply: str, cuts: list[Path], kinds: list[str],
         hashes: list[int] | None = None) -> tuple[Page, list[str]]:
    """모델이 돌려준 것을 받는다. **그대로 믿지 않는다** (저쪽의 Layer C).

    막는 것은 셋뿐이다 —

        TEXT · PROMO 밴드를 그림 자리에 넣었다   → 그 자리를 비운다
        같은 밴드를 두 자리에 넣었다             → 뒤엣것을 비운다
        같은 사진이 다른 밴드로 또 들어왔다        → dHash 로 알아보고 비운다

    **잘못된 사진보다 빈 칸이 안전하다.** 손님은 이 그림을 보고 주문한다.
    다만 **캡션은 그림과 따로 산다** — 그림이 비어도 설명은 그대로 남긴다.
    """
    import json
    import re

    from .bands import DUP_HAMMING, hamming

    m = re.search(r"\{[\s\S]*\}", reply or "")
    if not m:
        return Page(), ["모델이 JSON 을 안 돌려줬다"]
    try:
        got = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return Page(), [f"JSON 을 못 읽었다: {e}"]

    notes = [str(x) for x in got.get("notes") or []]
    hashes = hashes or []
    used: list[int] = []

    def cut(v, why: str) -> Path | None:
        if not isinstance(v, int) or not (0 <= v < len(cuts)):
            return None
        kind = kinds[v] if v < len(kinds) else UNKNOWN_KIND
        if kind in ("TEXT", "PROMO"):
            notes.append(f"{why}: [{v}] 는 {kind} 라 그림으로 못 씀")
            return None
        if v in used:
            notes.append(f"{why}: [{v}] 는 이미 다른 자리에 썼다")
            return None
        h = hashes[v] if v < len(hashes) else 0
        for u in used:
            if hamming(h, hashes[u] if u < len(hashes) else 0) <= DUP_HAMMING:
                notes.append(f"{why}: [{v}] 는 [{u}] 와 같은 사진이다")
                return None
        used.append(v)
        return cuts[v]

    spec = {k: str(v).strip() for k, v in (got.get("spec") or got.get("summary") or {}).items() if str(v).strip()}
    spec["치수"] = SIZE_FIXED
    keys = [
        (str(k.get("t") or k.get("title") or "").strip(), str(k.get("d") or k.get("desc") or "").strip())
        for k in (got.get("keys") or got.get("keyFeatures") or [])
        if isinstance(k, dict) and str(k.get("t") or k.get("title") or "").strip()
    ][:3]

    page = Page(spec=spec, keys=keys)
    # 자리 순서가 곧 우선권이다. 특징·사이즈·패키지를 먼저 잡고 대표컷이 그 나머지에서
    # 고르게 한다 — 저쪽도 같은 순서다(feature → size → package → main).
    page.feature = cut(got.get("feature"), "특징컷")
    page.size = cut(got.get("size"), "사이즈")
    page.package = cut(got.get("package"), "패키지")
    page.main = cut(got.get("main"), "대표컷")

    # 대표컷이 비면 페이지가 통째로 무너진다. 모델 픽이 거부되면 **남은 것 중에서
    # 다시 고른다** — 저쪽도 후보풀에서 최고점을 다시 뽑는다(`selectHeroIndex`).
    if page.main is None:
        quiet: list[str] = []          # 후보를 훑는 동안의 메모는 남기지 않는다
        for want in ("PHOTO", "MIXED", "UNKNOWN"):
            for i, kind in enumerate(kinds):
                if kind != want:
                    continue
                keep, notes = notes, quiet
                spare = cut(i, "대표컷 대신")
                notes = keep
                if spare is not None:
                    page.main = spare
                    notes.append(f"모델이 고른 대표컷을 못 써서 [{i}] 로 대신했다")
                    break
            if page.main is not None:
                break
        if page.main is None:
            notes.append("대표컷 후보가 없다 — 손으로 지정해야 한다")

    for slot in ("point1", "point2"):
        p = got.get(slot) or {}
        blocks = []
        for b in (p.get("blocks") or [])[:3]:
            if not isinstance(b, dict):
                continue
            # 캡션은 그림과 따로 산다. 그림을 못 써도 설명은 남긴다.
            blocks.append((str(b.get("d") or b.get("caption") or "").strip(),
                           cut(b.get("i") if "i" in b else b.get("index"), f"{slot} 그림")))
        setattr(page, slot, (str(p.get("title", "")).strip(), blocks))
    return page, notes



def is_promo(arr: np.ndarray, url: str = "") -> bool:
    """바나나몰이 직접 찍어 붙인 홍보 움짤인가.

    사장님 말: *"파란색 외곽테두리에 들어가있는 움짤은 다 사용하지 않을 예정"* —
    파란 테두리에 바나나몰이라고 써 있기 때문이다.

    색을 못박지 않고 **네 변에 같은 띠가 둘러져 있는가**로 센다. 실측 —
    홍보 GIF 는 네 변 파랑 80~86%, 상품 이미지는 네 변 모두 0%.
    """
    if not url.lower().endswith(".gif"):
        return False
    h, w, _ = arr.shape
    if w / max(1, h) < 1.2:  # 홍보 움짤은 가로형이다
        return False
    t = max(4, int(min(h, w) * 0.015))
    a = arr.astype(np.int32)

    def blue(x: np.ndarray) -> float:
        r, g, b = x[..., 0], x[..., 1], x[..., 2]
        return float(((b > 120) & (b > r + 35) & (b > g + 25)).mean())

    return min(blue(a[:t]), blue(a[-t:]), blue(a[:, :t]), blue(a[:, -t:])) >= 0.5


#: HERO 자리는 폭 700 한 칸이다. 세로로 긴 컷을 그대로 넣으면 화면을 다 잡아먹고,
#: 가로로 넓은 컷을 넣으면 배너처럼 납작해진다. 그래서 **다시 앉힌다.**
#: 값은 고도몰 생성기(`basicAssetNormalize.ts`)에 박힌 것을 그대로 옮겼다.
HERO_W = 1000          #: 다시 앉힐 캔버스의 폭
HERO_FILL = 0.86       #: 제품이 캔버스에서 차지할 몫
HERO_MAX = 1.25        #: 세로가 가로의 이만큼을 넘으면 거기서 멈춘다 (4:5)
HERO_MIN = 0.45        #: 너무 납작하면 배너로 보인다. 여기까지만 눕힌다


def reframe(src: Path, out: Path, bg: tuple[int, int, int] = (255, 255, 255)) -> Path:
    """대표컷을 HERO 자리에 맞게 다시 앉힌다.

    분할기는 내용에 딱 맞게 자르므로 조각의 비율이 제각각이다. 559×866 짜리
    세로 컷을 폭 700 자리에 그대로 넣으면 1085px 짜리 기둥이 된다.

    **원본 이미지를 고치는 것이 아니다** — 잘라 둔 조각을 우리 자리에 앉히는 것이다.
    제품은 그대로 두고 둘레의 여백만 새로 잡는다.
    """
    from PIL import Image

    with Image.open(src) as im:
        im = im.convert("RGB")
        arr = np.asarray(im)

    # 제품이 실제로 놓인 자리부터 찾는다. 조각에 남은 바깥 여백은 버린다.
    a = arr.astype(np.int32)  # uint8 로 곱하면 넘친다
    lum = (a[..., 0] * 299 + a[..., 1] * 587 + a[..., 2] * 114) // 1000
    solid = lum < 232
    ys, xs = np.where(solid.any(1)), np.where(solid.any(0))
    if not len(ys[0]) or not len(xs[0]):
        return src
    y0, y1 = int(ys[0][0]), int(ys[0][-1])
    x0, x1 = int(xs[0][0]), int(xs[0][-1])
    body = Image.fromarray(arr[y0 : y1 + 1, x0 : x1 + 1])

    # 캔버스 비율 — **제품 비율을 그대로 두되 양 끝만 막는다.**
    # 정사각으로 강요하면 가로로 넓은 제품이 흰 여백에 파묻혀 작아진다.
    # 고치려는 것은 그게 아니라 세로로 긴 컷이 기둥이 되는 것이다 —
    # 글랜스 559×866 을 폭 700 에 그대로 넣으면 1085px 짜리 기둥이 됐다.
    ratio = body.height / max(1, body.width)
    hw = min(max(ratio, HERO_MIN), HERO_MAX)
    canvas = Image.new("RGB", (HERO_W, int(HERO_W * hw)), bg)

    room = (int(canvas.width * HERO_FILL), int(canvas.height * HERO_FILL))
    s = min(room[0] / body.width, room[1] / body.height)
    body = body.resize((max(1, int(body.width * s)), max(1, int(body.height * s))), Image.LANCZOS)
    canvas.paste(body, ((canvas.width - body.width) // 2, (canvas.height - body.height) // 2))
    canvas.save(out, quality=92)
    return out
