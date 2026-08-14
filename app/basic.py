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
    letters: int      #: 글자꼴 작은 덩어리 개수 — 글이 구워져 있는가
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
    color = float(((sat >= 45) & (lum < 245)).mean())
    ink = float(((lum < 115) & (sat < 40)).mean())
    letters, solo = _blobs(lum)
    area = (r.x1 - r.x0 + 1) * (r.y1 - r.y0 + 1)
    return Shot(r, white, color, ink, letters, solo, area)


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

    거르는 것은 넷이다. 핑거위글 조각 여덟 개로 잰 값을 함께 적는다.

        유채색이 많다      컬러 배경·배너다        모델컷 28%·원본 대표컷 43% ↔ 나머지 0~6%
        글자꼴이 많다      글이 구워져 있다        제품특징 89·포인트 125·패키지 14 ↔ 나머지 0~2
        여러 덩어리다      제품이 하나가 아니다     사이즈 36%·손에 든 컷 49% ↔ 단독컷 100%
        제 네모를 꽉 채운다  상자다, 제품이 아니다    패키지 상자 92% ↔ 제품컷 8~37%

    남은 것 중 **제품이 가장 크게 찍힌 것**을 쓴다. 화면이 큰 것이 아니다 —
    충전 케이블 컷(726×774)이 제품 단독컷(608×455)보다 크지만 제품은 훨씬 작다.

    **흰 바탕 비율은 안 본다.** 분할기가 이미 내용에 딱 맞게 잘라내므로, 그 값은
    배경이 아니라 실루엣이 얼마나 들쭉날쭉한가를 잰다. 잣대가 아니다.

    두 컷이 똑같이 깨끗하면 어느 쪽을 골라도 된다 — 핑거위글에는 608×455 와
    697×360 이 둘 다 제품 단독컷이었다. 잘린 폭이 달라도 HERO 자리에 넣을 때
    다시 여백을 잡으므로 결과가 같다.

    **여기 숫자들은 아직 핑거위글 하나에서 나왔다.** 다른 기본형을 받으면 다시 잰다.
    """
    if not cands:
        return None
    # 이 페이지에서 '유채색이 많다'가 얼마인지부터 관측한다.
    mid = float(np.median([c.color for c in cands]))
    ceiling = max(0.15, mid * 2)
    clean = [
        c
        for c in cands
        if c.color < ceiling and c.letters <= 6 and c.solo >= 0.9 and 0.03 <= c.ink <= 0.75
    ]
    if not clean:
        return None
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
 .gpage .keys__fig{height:260px;margin-bottom:16px}}
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

    # ③ 영문명 띠 — 구간을 가르는 장식이다
    if page.name_en:
        out.append(f'<div class="band">{esc("  ·  ".join([page.name_en] * 6))}</div>')

    out.append(
        '<footer class="foot"><p class="foot__b">GODO MALL</p>'
        '<p class="foot__c">COPYRIGHT © GODO MALL. ALL RIGHTS RESERVED.</p></footer>'
    )
    out.append("</div>")
    return "\n".join(x for x in out if x)
