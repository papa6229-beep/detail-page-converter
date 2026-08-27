"""기본형 **메인 섹션** — 잘 만들어진 원본을 뜯어 우리 디자인으로 다시 세운다.

`origin/legacy/basic-before-rewind` 의 `app/basic.py` 에서 메인 부분만 옮겼다.
옮기지 않은 것: Point 01·02 재구성 · SIZE · 본문. **본문은 basic/body.py 가 맡는다.**

단순형과 전제가 반대다.

    단순형   원본이 허접하다 → 원본 이미지를 손대지 않고 순서대로 싣는다
    기본형   원본이 이미 완성된 디자인이다 → 그대로 실으면 남의 쇼핑몰처럼 보인다

그래서 원본을 **재료로만** 쓴다. 컬러 배경 위에 얹힌 원본 대표컷을 버리고,
페이지 어딘가의 **흰 바탕 제품 단독컷**을 찾아 새 대표컷으로 세운다.

legacy 는 조각을 `slicer.slice_image` 로 냈지만 여기서는 `basic/bands.py` 밴드를
쓴다 — legacy 도 마지막엔 밴드로 갔고, 무엇보다 단순형 분할기를 안 건드린다.
"""

from __future__ import annotations

import base64
import html
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from . import bands as B

#: 글자꼴 덩어리를 셀 때 이 크기로 줄여서 본다. 글자가 뭉개지지 않으면서 빠르다.
CC_SCALE = 200


@dataclass
class Rect:
    """조각 하나의 자리. legacy 는 slicer.Rect 를 썼다 — 여기서는 밴드 안의 알맹이."""

    x0: int
    y0: int
    x1: int
    y1: int


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
    band: int = -1    #: 몇 번 밴드에서 나왔나
    #: **테두리 한 겹에서 색이 있는 화소의 몫.** 배경에 색이 깔렸는가를 가른다.
    #: 채도의 *중앙값* 으로 재던 것을 *비율* 로 바꿨다 — 죠우무의 파란 그라데이션 컷은
    #: 좌우에 흰 여백이 있어 중앙값이 0 으로 나왔다(막지 못했다). 비율은 0.41 이다.
    bg_tint: float = 0.0
    #: 이 밴드에 **글자가 박혀 있는가.** 덩어리 개수(letters)는 무늬 있는 제품에서
    #: 60~76 까지 뛰어 못 믿는다. 밴드 종류(MIXED)와 `sidetext` 가 직접 말해 준다.
    has_text: bool = False
    #: 배경이 아닌 화소의 몫. 넓이를 잴 때 쓴다 — `ink` 는 **어둡고 채도 낮은** 것만
    #: 세어서 파란 제품을 거의 0 으로 본다(브루스). 색 있는 제품에는 이쪽이 맞다.
    subject: float = 0.0

    @property
    def subject_pixels(self) -> float:
        """제품이 찍힌 넓이 — 색을 안 가린다."""
        return self.area * self.subject

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


def _stats(arr: np.ndarray, r: Rect, band: int = -1) -> Shot:
    """조각 하나를 재기만 한다. 판정은 여기서 하지 않는다."""
    crop = arr[r.y0 : r.y1 + 1, r.x0 : r.x1 + 1].astype(np.int32)
    lum = (crop[..., 0] * 299 + crop[..., 1] * 587 + crop[..., 2] * 114) // 1000
    sat = crop.max(2) - crop.min(2)
    white = float((lum >= 232).mean())
    tint = (sat >= 45) & (lum < 245)
    color = float(tint.mean())
    ink = float(((lum < 115) & (sat < 40)).mean())
    letters, solo_dark = _blobs(lum)
    # **한 덩어리인가**를 두 가지로 재서 **큰 쪽**을 쓴다. 둘 다 한 방향으로 틀린다 —
    #   어두운 화소로 재면   인쇄된 상자·창백한 제품이 잘게 갈린다 (벨벳키스 상자 0.25,
    #                        죠우무 살구색 제품 0.68) → 멀쩡한 것을 막는다
    #   피사체로 재면        나란히 붙은 것들이 한 덩어리로 이어진다 (유컵스 나열 0.64)
    # 큰 쪽을 쓰면 **둘 다 잘게 갈렸다고 할 때만** 막는다. 막는 것은 누가 봐도
    # 여러 개인 것(다일레이터 6칸 격자 0.19)뿐이다 — 애매하면 통과시킨다.
    fg = (lum < 232) | (sat >= 45)
    solo = max(solo_dark, _largest_share(fg))
    area = (r.x1 - r.x0 + 1) * (r.y1 - r.y0 + 1)
    # 배경은 **테두리 한 겹**으로 본다. 제품은 가운데에 있고 테두리는 바닥이다.
    # 중앙값이 아니라 **색이 있는 화소의 몫**을 센다 — 한쪽에만 색이 깔린 컷을
    # 중앙값으로는 못 잡는다.
    t = max(2, min(6, crop.shape[0] // 8, crop.shape[1] // 8))
    edge = np.concatenate([crop[:t].reshape(-1, 3), crop[-t:].reshape(-1, 3),
                           crop[:, :t].reshape(-1, 3), crop[:, -t:].reshape(-1, 3)])
    bg_tint = float(((edge.max(1) - edge.min(1)) >= 40).mean())
    subject = float(((lum < 232) | (sat >= 45)).mean())
    return Shot(r, white, color, ink, letters, _densest(tint), solo, area, band,
                bg_tint=bg_tint, subject=subject)


def _largest_share(fg: np.ndarray) -> float:
    """가장 큰 연결 덩어리가 전경에서 차지하는 몫. 0 이면 전경이 없다."""
    if not fg.any():
        return 0.0
    step = max(1, max(fg.shape) // CC_SCALE)
    sizes = B._components(fg[::step, ::step])
    return max(sizes) / sum(sizes) if sizes else 0.0


def _densest(mask: np.ndarray) -> float:
    """유채색이 **가장 빽빽하게 몰린 가로 띠**의 밀도.

    조각 전체 비율로는 못 잡는다. `03 제품 사이즈` 분홍 제목은 699×1823 조각에서
    전체의 1.3% 밖에 안 되어 묽어지지만, 그 제목이 놓인 줄만 보면 32% 다.
    **디자인 글은 넓게 흩어지지 않고 한 띠에 몰려 있다** — 그게 사진과 다른 점이다.
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
    """
    h, w = lum.shape
    if min(h, w) < 8:
        return 0, 0.0
    step = max(1, max(h, w) // CC_SCALE)
    small = lum[::step, ::step]
    dark = small < 160
    if not dark.any():
        return 0, 0.0

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
    letters = sum(1 for n in total.values() if 2 <= n <= max(6, biggest * 0.12))
    return letters, biggest / sum(total.values())


#: 알맹이 둘레에 남길 여유. 피사체 크기에 대한 비율이다.
#: 연한 그림자·바닥면은 배경과 거의 같은 밝기라 전경으로 안 잡힌다 — 딱 맞게
#: 자르면 다일레이터 대표컷 밑의 그림자가 뭉텅 잘려 제품이 공중에 뜬다.
#: 여유는 **밴드 원본 픽셀로 채운다** — 흰 바탕이면 흰색이 따라온다.
MARGIN = 0.06


#: 배경색에서 이만큼 벗어나야 전경으로 본다.
BG_NEAR = 60
#: 테두리에서 이만큼을 차지하면 그것도 배경색이다.
BG_SHARE = 0.12


#: 테두리 색이 이보다 밝고 무채색이면 "흰 바탕" 으로 본다.
WHITE_RING = 232


def _white_ring(ring: np.ndarray) -> bool:
    """테두리가 통째로 흰 바탕인가 — 그러면 잘라 낼 것이 없다."""
    q = ring.astype(np.int32)
    return bool(q.min(axis=1).mean() >= WHITE_RING)


def _off_background(crop: np.ndarray, ring: np.ndarray) -> np.ndarray:
    """화소마다 **가장 가까운 배경색과의 거리**. 배경 위면 작다.

    배경을 색 **하나**로 보면 안 된다. 죠우무의 패키지 밴드는 테두리 절반이 파란
    사선 띠, 절반이 흰 여백이라 중앙값이 그 사이(215·219·253)에 떨어졌다. 그러면
    흰 여백조차 배경에서 75 만큼 벗어난 것이 되어 **밴드 전체가 한 덩어리**가 됐다.
    테두리에서 제 몫을 차지하는 색은 **전부** 배경으로 본다.
    """
    q = (ring.astype(np.int32) // 24) * 24
    uniq, counts = np.unique(q.reshape(-1, 3), axis=0, return_counts=True)
    keep = uniq[counts >= BG_SHARE * len(q)]
    if not len(keep):
        keep = np.median(ring.astype(np.int32), axis=0)[None, :]
    px = crop.astype(np.int32)
    best = None
    for c in keep:
        d = np.abs(px - c).sum(axis=2)
        best = d if best is None else np.minimum(best, d)
    return best


def _content_rect(arr: np.ndarray, y: int, height: int) -> Rect | None:
    """밴드 안에서 **배경색이 아닌 제일 큰 덩어리**의 자리를 집는다.

    배경은 흰색이라고 못박지 않는다. 테두리 한 겹의 중앙값을 배경으로 보고, 거기서
    벗어난 화소를 전경으로 센다. 그래야 **색 배경 위에 놓인 상자**도 상자만 잡힌다 —
    죠우무의 패키지 밴드는 상자 왼쪽에 파란 사선 띠, 오른쪽에 캡션이 같이 있어서,
    전부를 감싸면 테두리 색비율이 0.31 이 되어 상자가 통째로 떨어졌다.

    둘레에 `MARGIN` 만큼 여유를 준다. 자른 자리는 밴드에서 그대로 떠 오므로
    배경이 희면 흰색이, 색이면 그 색이 따라온다.
    """
    import cv2

    from . import sidetext

    crop = arr[y : y + height]
    h, w = crop.shape[:2]
    if h < 4 or w < 4:
        return None
    whole = Rect(0, y, w - 1, y + h - 1)
    t = max(2, min(6, h // 8, w // 8))
    ring = np.concatenate([crop[:t].reshape(-1, 3), crop[-t:].reshape(-1, 3),
                           crop[:, :t].reshape(-1, 3), crop[:, -t:].reshape(-1, 3)])

    # **흰 바탕이고 라벨도 없으면 자르지 않는다.** 자를 것이 없기 때문이다.
    # 자르면 오히려 잃는다 — 흰 제품은 흰 배경과 잘 안 갈려서 "제일 큰 덩어리" 가
    # 제품의 한 조각만 잡는다(유컵스의 흰 링 셋 중 하나만 남았다).
    # 자르는 것은 **색 배경이 깔렸거나 라벨이 붙었을 때**뿐이다 — 그때는 떼어낼
    # 것이 실제로 있다(죠우무 패키지의 파란 사선 띠와 캡션).
    if _white_ring(ring) and sidetext.split(crop) is None:
        return whole

    fg = (_off_background(crop, ring) > BG_NEAR).astype(np.uint8)
    if not fg.any():
        return whole

    # 큰 덩어리 하나만 남긴다. 잔글씨·얇은 띠가 붙어 오지 않게 살짝 이어 붙여 센다.
    step = max(1, max(h, w) // 400)
    small = fg[::step, ::step]
    small = cv2.morphologyEx(small, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _lab, st, _c = cv2.connectedComponentsWithStats(small)
    if n <= 1:
        return whole
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    x0, y0, bw, bh = (int(st[i, cv2.CC_STAT_LEFT]), int(st[i, cv2.CC_STAT_TOP]),
                      int(st[i, cv2.CC_STAT_WIDTH]), int(st[i, cv2.CC_STAT_HEIGHT]))
    x0, y0, bw, bh = x0 * step, y0 * step, bw * step, bh * step

    pad = int(round(max(bw, bh) * MARGIN))
    x1, y1 = min(w - 1, x0 + bw - 1 + pad), min(h - 1, y0 + bh - 1 + pad)
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    if x1 <= x0 or y1 <= y0:
        return whole
    return Rect(x0, y + y0, x1, y + y1)


def shots(arr: np.ndarray, offset: int = 0) -> list[Shot]:
    """통이미지 한 장에서 대표컷 후보를 전부 재서 돌려준다.

    legacy 는 `slicer.slice_image` 를 썼다. 여기서는 밴드를 쓰고, 밴드 안의
    알맹이 자리를 따로 찾아 잰다.

    `offset` 은 이 이미지의 첫 밴드가 몇 번인가 — 상품 이미지가 여러 장이면
    밴드 번호가 이미지를 넘어서 이어지므로, 돌려주는 `Shot.band` 도 그 번호여야 한다.

    **작다고 건너뛰지 않는다.** 예전에는 폭의 1/4 보다 작은 밴드를 뺐다. 코드가
    대표컷을 직접 고르던 시절의 잣대다. 지금은 모델이 고르므로, 모델이 고른 밴드를
    안 재 놓으면 "너무 작아 후보로 안 쟀다" 는 **네 번째 거르기**가 몰래 생긴다
    (유컵스에서 실제로 그랬다). 거르는 기준은 셋뿐이어야 한다.
    """
    from . import sidetext

    out = []
    for i, b in enumerate(B.read(arr)):
        r = _content_rect(arr, b.y, b.height)
        if r is None:
            continue
        sh = _stats(arr, r, offset + i)
        # 글자가 박혀 있는가 — **잘라 낸 알맹이에게** 묻는다. 밴드째 물으면 옆에
        # 붙은 캡션까지 세어, 알맹이는 깨끗한데 글자가 있다고 막는다(죠우무 상자).
        sh.has_text = sidetext.split(arr[r.y0:r.y1 + 1, r.x0:r.x1 + 1]) is not None
        out.append(sh)
    return out


# ── 대표컷·키피쳐 고르기 ────────────────────────────────────────────────
#
# **코드는 고르지 않는다. 거르기만 한다.**
#
# 모델이 자리마다 후보를 순서대로 준다. 코드는 그 순서대로 검사해서 첫 통과를
# 쓴다. 예전에는 코드가 등급(A·B·C)을 매겨 직접 골랐는데, 상품이 하나 늘 때마다
# 임계값이 늘고 결과는 오히려 나빠졌다 — 무늬 있는 제품에서는 글자꼴이 60~76 개로
# 세어지고, 파란 제품에서는 `ink` 가 0 이 되고, 페이지 바닥에 색이 깔리면
# `design` 이 전부 1.0 에 붙었다. 픽셀로 "무엇이 어울리는가" 를 재려던 것이 잘못이다.
#
# 거르는 기준은 **셋뿐이다.** 늘리지 않는다.
#
#     ① 유채색 배경이 깔림   (대표컷만 — 키피쳐는 연출컷도 쓴다)
#     ② 글자가 박힘
#     ③ 제품이 여러 개
#
# 숫자는 7개 상품(핑거위글·브루스·글랜스·다일레이터·벨벳키스·유컵스·죠우무)의
# 후보 밴드 100장을 재서 골랐다. **веto 다.** 애매하면 통과시킨다 — 고르는 일은
# 모델 몫이고, 여기서 막는 것은 누가 봐도 아닌 것뿐이다.

#: 자리마다 받을 후보 수. 셋이면 모자란다 — 다일레이터는 모델이 원본 대표컷
#: 둘(색 배경이라 걸러진다)을 앞에 놓아 셋 중 하나만 남았고, 그 하나가 여섯 중
#: 셋만 모인 컷이었다. 다섯으로 늘리면 걸러진 뒤에도 고를 것이 남는다.
#: **규칙이 느는 게 아니라 숫자 하나가 바뀌는 것이다.**
PICKS = 5

#: ① 테두리에서 색이 있는 화소의 몫이 이보다 크면 유채색 배경이다. 실측 —
#:     흰 바탕 제품컷   0.00 · 0.00 · 0.00 · 0.00 · 0.00 · 0.00 · 0.00 · 0.03 · 0.04 · 0.05
#:     색 배경         0.31 · 0.37 · 0.41 · 0.46 · 0.47 · 0.53 · 0.55 · 0.59 · 0.63 · 0.95 · 1.00
#: **0.05 와 0.31 사이가 통째로 비어 있다.**
#: 상자컷을 넣고 다시 재니 벨벳키스의 진짜 상자가 0.16 이었다 — 상자는 네모라
#: 제 인쇄색이 테두리에 그대로 닿는다. 배경이 색인 것이 아니라 **피사체가 네모난
#: 것**이다. 그래서 선을 0.25 로 옮겼다. 막아야 할 것들(0.31~1.00)과는 여전히 멀다.
TINTED_BG = 0.25

#: 같은 사진으로 볼 dHash 거리. `bands.DUP_HAMMING`(10) 은 이 자리에 너무 헐겁다 —
#: 글랜스의 상자컷과 접사컷이 10 이라 상자가 "이미 쓴 사진" 으로 막혔다. 실측 —
#:     정말 같은 컷(배경만 다름)   1
#:     서로 다른 컷              10 · 10 · 11 · 12 · 12 · 12 · 12 · 12
#: 1 과 10 사이가 비어 있다. 8×8 dHash 는 흰 바탕 검은 제품끼리 곧잘 붙는다.
SAME_PHOTO = 5

#: ③ 가장 큰 덩어리가 어두운 화소에서 차지하는 몫. 이보다 작으면 제품이 여러 개다.
#: 실측(두 잣대의 큰 쪽) — 6칸 격자 0.19 ↔ 상자·단독컷 0.90 이상.
#: 낮게 잡는다. 여기서 막는 것은 **누가 봐도 여러 개**인 것뿐이다.
MULTI_SOLO = 0.40


def reject(s: Shot) -> str:
    """못 쓰는 까닭 한 줄. 쓸 수 있으면 빈 글자.

    **세 자리에 똑같이 건다.** 자리별 예외를 두지 않는다 — 예외를 하나 두면
    그 자리만 다른 길로 새고, 그 길에서 결함이 나온다. 패키지에만 검사를 안 걸었을
    때 죠우무는 광고 배너를, 브루스는 파우치컷을 상자라고 세웠다.
    """
    if s.bg_tint > TINTED_BG:
        return f"색 배경이 깔렸다 (테두리 색비율 {s.bg_tint:.2f})"
    if s.has_text:
        return "글자가 박혔다"
    if s.solo < MULTI_SOLO:
        return f"제품이 여러 개다 (한 덩어리 몫 {s.solo:.2f})"
    return ""


def first_pass(picks, shots: dict[int, Shot], kinds: list[str], hashes: list[int],
               blocked, used: list[int], slot: str, notes: list[str],
               keep_first: bool = False) -> int:
    """모델이 준 순서대로 검사해서 **첫 통과**를 쓴다. 없으면 -1.

    막을 때마다 왜 막았는지 적는다. 셋 다 떨어지면 빈칸으로 두고 그 사실도 적는다 —
    조용히 비워 두면 화면만 보고는 모델이 안 골랐는지 우리가 막았는지 알 수 없다.

    `keep_first` 는 키피쳐 자리에만 켠다. 대표컷·패키지는 없으면 안 그리면 그만이지만,
    KEY FEATURE 는 그림 자리가 비면 글 카드만 남아 층이 무너진다. 그래서 셋 다
    떨어져도 첫 번째를 쓰되 **왜 떨어진 것을 쓰는지 적는다.**
    """
    if not isinstance(picks, list):
        picks = [picks]
    picks = picks[:PICKS]
    rejected: list[int] = []
    for v in picks:
        if not isinstance(v, int) or not (0 <= v < len(kinds)):
            continue
        kind = kinds[v]
        if kind in ("TEXT", "PROMO"):
            notes.append(f"{slot} [{v}] 막음 — {kind} 밴드다")
            continue
        if v in blocked:
            notes.append(f"{slot} [{v}] 막음 — 원본 요약정보 표가 든 밴드다")
            continue
        if v in used:
            notes.append(f"{slot} [{v}] 막음 — 이미 다른 자리에 썼다")
            continue
        if any(B.hamming(hashes[v] if v < len(hashes) else 0,
                         hashes[u] if u < len(hashes) else 0) <= SAME_PHOTO
               for u in used):
            notes.append(f"{slot} [{v}] 막음 — 이미 쓴 것과 같은 사진이다")
            continue
        sh = shots.get(v)
        if sh is None:
            notes.append(f"{slot} [{v}] 막음 — 너무 작아 후보로 재지 않았다")
            continue
        why = reject(sh)
        if why:
            notes.append(f"{slot} [{v}] 막음 — {why}")
            rejected.append(v)
            continue
        used.append(v)
        return v
    if keep_first and rejected:
        v = rejected[0]
        used.append(v)
        notes.append(f"{slot} 후보가 다 떨어져 첫 번째 [{v}] 를 그대로 쓴다 — 비우면 층이 무너진다")
        return v
    notes.append(f"{slot} 빈칸 — 모델이 준 후보가 다 떨어졌거나 없다")
    return -1


def pick_slots(shots: dict[int, Shot], kinds: list[str], hashes: list[int],
               blocked: set[int] | frozenset = frozenset(),
               ai_main=None, ai_feature=None,
               ai_package=None) -> tuple[int, int, int, list[str]]:
    """(대표컷, 키피쳐, 패키지, 메모). 셋 다 모델이 준 순서대로 검사한 결과다."""
    notes: list[str] = []
    used: list[int] = []
    # 세 자리를 **한 흐름**으로 지난다. 자리별 예외는 프롬프트 한 줄뿐이다.
    # `or []` 를 쓰면 안 된다 — 0번 밴드는 거짓이라 통째로 사라진다.
    hero = first_pass([] if ai_main is None else ai_main,
                      shots, kinds, hashes, blocked, used, "대표컷", notes)
    feat = first_pass([] if ai_feature is None else ai_feature,
                      shots, kinds, hashes, blocked, used, "키피쳐", notes, keep_first=True)
    pkg = first_pass([] if ai_package is None else ai_package,
                     shots, kinds, hashes, blocked, used, "패키지", notes)
    return hero, feat, pkg, notes


#: 강조색. 고도몰 생성기의 기본값을 그대로 쓴다 (`DEFAULT_THEME_COLOR`).
ACCENT = "#E11D48"

#: 이 CSS 도 **남의 페이지 안에서 산다**. 선택자는 전부 `.gpage` 로 시작한다.
#: legacy 는 폭 800(메인이미지 700)이었다. 본문(`.bpage`)이 860 이라 **여기도 860**
#: 으로 맞춘다 — 한 파일에 위아래로 붙는데 폭이 다르면 층이 어긋나 보인다.
#: 안쪽 치수는 legacy 비율 그대로 옮겼다(좌우 여백 50 → 알맹이 760).
CSS = """
.gpage{--accent:#E11D48;--ink:#111827;--mute:#6b7280;--soft:#9ca3af;--body:#4b5563;
 --plate:#f3f4f6;--line:#e5e7eb;
 width:860px;max-width:100%;margin:0 auto;background:#fff;color:var(--ink);
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
.gpage .hero__main{width:100%;margin:0 auto;border:1px solid var(--line);overflow:hidden}
.gpage .hero__name{margin-top:32px;font-size:52px;line-height:1.05;font-weight:900;
 letter-spacing:-.025em;max-width:500px;white-space:pre-line}
.gpage .hero__en{margin-top:4px;font-size:20px;font-weight:500;letter-spacing:.15em;
 color:var(--soft);text-transform:uppercase}
.gpage .specs{margin-top:40px;display:flex;flex-direction:column;gap:16px}
.gpage .specs__row{display:flex;gap:16px}
.gpage .spec{width:155px;flex:none;min-width:0}
.gpage .spec__k{display:flex;align-items:center;gap:6px;font-size:14px;font-weight:700;
 color:var(--mute);white-space:nowrap}
.gpage .spec__rule{height:2px;background:var(--ink);margin:8px 0}
.gpage .spec__v{font-size:15px;font-weight:900;line-height:1.375}
/* 패키지는 히어로 오른쪽 아래에 얹는다. legacy 기본 자리(x 468 · 700 기준)를
   760 알맹이에 맞춰 옮겼다. 원본에 없으면 아예 안 그린다. */
.gpage .pkg{position:absolute;left:508px;top:430px;width:228px;height:270px;
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
.gpage .keys__list{position:absolute;right:0;top:0;width:390px;display:flex;
 flex-direction:column;gap:52px}
.gpage .key{background:var(--plate);border-radius:12px;padding:16px 20px}
.gpage .key__t{display:flex;align-items:center;gap:8px;margin-bottom:6px;
 font-size:18px;font-weight:900}
.gpage .key__d{font-size:14px;font-weight:500;color:var(--body);line-height:1.375}
.gpage .keys__fig{position:absolute;left:0;top:0;width:340px;height:380px}
.gpage .keys__fig img{width:100%;height:100%;object-fit:contain}
.gpage .band{border-top:1px solid #d1d5db;border-bottom:1px solid #d1d5db;padding:16px 0;
 overflow:hidden;white-space:nowrap;text-align:center;color:var(--soft);
 font-size:14px;font-weight:500;letter-spacing:.25em;text-transform:uppercase}
@media (max-width:860px){
 .gpage .hero,.gpage .sec{padding-left:22px;padding-right:22px}
 .gpage .hero__name{font-size:34px;max-width:100%}
 .gpage .sec__h{font-size:44px}
 .gpage .pkg{position:static;width:160px;height:190px;margin:24px 0 0 auto}
 .gpage .keys{min-height:0}
 .gpage .keys__list,.gpage .keys__fig{position:static;width:100%;gap:16px}
 .gpage .keys__fig{height:260px;margin-bottom:16px}}
"""


@dataclass
class Page:
    """기본형 **메인**이 채워야 하는 칸. 고도몰 생성기의 칸과 같은 이름이다.

    사장님이 항목을 다섯으로 줄여 고정하셨다 — `타입 · 재질 · 치수 · 무게 · 전원`.
    브랜드는 우상단에 따로 박히고, `특징` 은 KEY FEATURE 부제로 간다.

    비어 있는 칸은 **그리지 않는다.** 없는 것을 지어내지 않는 것이 이 프로젝트의
    규칙이고, 여기서는 화면에서도 그렇게 한다.

    Point 01·02 와 SIZE 는 여기 없다 — 그 자리는 본문(basic/body.py)이 맡는다.
    """

    name_kr: str = ""
    name_en: str = ""
    maker: str = ""
    spec: dict[str, str] = field(default_factory=dict)
    #: KEY FEATURE 세 칸 — (제목, 한 줄 설명)
    keys: list[tuple[str, str]] = field(default_factory=list)
    main: Path | None = None
    package: Path | None = None
    feature: Path | None = None
    #: 원본 메인섹션이 끝나고 본문이 시작되는 첫 밴드 번호
    body_start: int = 0
    #: 세운 밴드 번호들. 보고용 — 어느 컷을 세웠는지 사람이 봐야 한다.
    main_band: int = -1
    feature_band: int = -1
    package_band: int = -1


#: 사장님이 고정한 다섯 항목. 1행 셋, 2행 둘 — 2행을 왼쪽에 두는 것은
#: 오른쪽 패키지 상자에 안 가리게 하려는 것이다.
SPEC_ROWS = (("타입", "재질", "치수"), ("무게", "전원"))
#: 치수는 읽지 않는다. 옵션마다 다르고 그림에서 재면 부정확하다 — 고정값이다.
SIZE_FIXED = "상세페이지 참조"


def esc(s: str) -> str:
    return html.escape(str(s or ""))


def data_uri(path: Path) -> str:
    ext = Path(path).suffix.lstrip(".").lower()
    mime = "image/png" if ext == "png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def render_page(page: Page) -> str:
    """메인 섹션을 HTML 로. 단순형 렌더러와 **완전히 따로** 둔다.

    고도몰 쪽 보고서의 금지선 5번과 같은 이유다 — *"기본형과 단순형의 렌더러를
    합치지 말 것. 격리가 회귀 0을 만든 장치다."* 우리도 단순형 49개를 지켜야 한다.

    legacy 의 ① HERO 와 ② KEY FEATURE 만 옮겼다. ④ Point · ⑤ SIZE 는 본문이
    맡으므로 안 그린다. legacy 의 ⑥ GODO MALL 푸터도 안 그린다 — 본문이 아래에
    이어 붙으므로 페이지 한가운데에 남의 상호가 박히면 안 된다.
    ③ 영문명 띠는 남겼다. 메인과 본문 사이의 이음매 노릇을 한다.
    """

    def dot(px: int) -> str:
        return f'<span class="dot" style="width:{px}px;height:{px}px"></span>'

    def img(path: Path | None, alt: str) -> str:
        return f'<img src="{data_uri(path)}" alt="{esc(alt)}">' if path else ""

    out = [f"<style>{CSS}</style>", '<div class="gpage">']

    # ① HERO — 제조사 우상단 · 누끼컷 중앙 · 상품명 · 영문명 · 스펙 · 패키지
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

    # ③ 영문명 띠 — 메인과 본문 사이의 이음매
    if page.name_en:
        out.append(f'<div class="band">{esc("  ·  ".join([page.name_en] * 6))}</div>')

    out.append("</div>")
    return "\n".join(x for x in out if x)


#: 모델에게 주는 지시. **자르기는 수학, 이해는 AI** — 조각은 우리가 냈고,
#: 어느 조각이 어느 자리에 어울리는지는 모델이 정한다.
#:
#: legacy 에서 Point 01·02 를 뺐다(본문이 맡는다). 대신 **메인이 어디서 끝나는가**
#: 를 묻는다 — 그 한 숫자가 메인과 본문을 가른다.
PROMPT = """쇼핑몰 상세페이지를 새 디자인으로 다시 짓는다. 원본에서 **재료만** 가져온다.

원본은 이미 완성된 디자인이라 그대로 옮기면 남의 쇼핑몰이 따라온다.
그림은 골라서 쓰고, 글은 원본이 적어 둔 사실에서만 가져온다.

**보내는 것**

    상품명 · 브랜드 · 원본에 직접 타이핑돼 있던 글 전문
    번호가 붙은 밴드 그림들. 번호 옆 괄호가 그 밴드의 종류다.
    첫 밴드들이 원본 맨 위(대표컷·요약정보·3줄요약·패키지)다.

**할 일 넷**

1. **요약정보** — 원본 맨 위 표에 적힌 그대로 옮긴다.
   `타입` `재질` `무게` `전원` 넷만. 없으면 빈 칸으로 둔다.
   **치수는 옮기지 마라** — 옵션마다 달라 따로 처리한다.

2. **핵심특징 3개** — 원본의 3줄 설명을 바탕으로 짧은 제목과 한 줄 설명을 짓는다.
   3줄이 모자라면 요약정보나 설명 글에서 보탠다. **없는 사실을 지어내지 마라.**
   제목은 한눈에 읽히게 짧게, 설명은 한 줄로.

3. **그림 고르기** — 자리마다 **좋은 순서대로 다섯**을 준다. 하나만 주지 마라.
   앞엣것이 막히면 뒤엣것을 쓴다. 그러니 **1번이 가장 좋은 것**이어야 한다.

   네가 준 뒤에 **코드가 한 번 더 거른다.** 아래 셋에 걸리면 그 후보는 버려진다 —
   버려질 것을 앞에 두면 자리 셋을 헛되이 쓰는 것이다.

       · 배경에 색이 깔린 밴드      (원본 맨 위의 대표컷은 대개 여기 걸린다)
       · 글자가 박힌 밴드
       · 제품이 여러 개로 흩어진 밴드

   그러니 **원본의 첫 대표컷을 그대로 1번에 놓지 마라.** 그건 색 배경 위에 있어
   거의 언제나 버려진다. 페이지 아래쪽의 흰 바탕 제품컷을 찾아라.
   **다섯을 다 채워라.** 앞의 둘이 버려져도 뒤에서 쓸 것이 남아야 한다.

    main      대표컷 후보 셋. **흰 바탕에 제품만 놓인 컷**을 찾아라.
              사람(모델)이 나온 컷 · 색 배너 · 글자 띠는 **절대 넣지 마라.**
              그런 컷밖에 없어도 넣지 말고, 흰 바탕 제품컷을 다시 찾아라.
              **손·신체·소품이 없어야 한다** — 손이 잡은 컷, 몸에 댄 컷,
              거치대·파우치·케이블이 같이 찍힌 컷은 대표컷이 아니다(키피쳐로 미뤄라).
              **옵션이 여러 개인 상품이면 먼저 옵션이 몇 개인지 세라.**
              요약정보의 무게·치수가 `130g/140g/190g/220g/235g/245g` 처럼 여러 개면
              그 수가 옵션 수다. 그 수가 **다 보이는** 컷이 1번이다. 그런 컷이
              없으면 옵션 **하나만** 찍힌 단독컷이 1번이다.
              **여섯 중 셋처럼 일부만 모인 컷은 어떤 경우에도 main 에 넣지 마라** —
              손님이 구성을 잘못 읽는다. 그런 컷은 feature 로 미뤄라.
              흰 바탕 컷이 여럿이면 제품이 크게 찍힌 순서로.
    feature   대표컷과 **다른** 제품컷 후보 셋. 손이 잡고 있어도, 거치대에
              얹혀 있어도, 배경에 옅은 색이 깔려 있어도 된다.
              설계도·단면도·치수 도해보다 **실제 제품 사진**이 앞이다.
    package   원본에 `PACKAGE` · `Package Design` 라벨이 붙은 밴드, 또는
              **판매용 상자**가 보이는 밴드.
              **상자가 확실하지 않으면 빈 배열 `[]` 로 둬라. 빈 배열이 정답인
              상품이 흔하다** — 상세페이지에 상자 사진을 안 넣는 원본이 많다.
              제품만 찍힌 컷, 접사컷, 파우치·케이블만 있는 컷, 모델 광고컷은
              상자가 아니다. 억지로 채우지 마라.

4. **메인과 본문의 경계** — `body_start` 에 숫자 하나.

   원본 맨 위의 **메인섹션**은 보통 이렇게 생겼다.

       대표컷 → 요약정보 표 → 3줄요약(큰 색 글씨) → 패키지 상자

   그 메인섹션이 끝나고 **본문**(제품특징 · Point · 기능 설명)이 시작되는
   **첫 밴드 번호**를 적어라. 그 번호의 밴드부터가 본문이다.
   메인섹션이 아예 없으면 0 을 적어라.

**밴드 종류와 쓰는 법**

    (PHOTO)    제품컷. 그림 자리에 먼저 쓴다
    (MIXED)    제품에 주석이 붙은 것. 차선으로 쓴다
    (UNKNOWN)  애매한 것. 다른 후보가 없을 때만 쓴다
    (TEXT)     글만 박힌 것. **읽는 근거로만** 쓰고 그림 자리에는 절대 넣지 마라.
    (PROMO)    쇼핑몰 홍보 움짤. 아무 자리에도 넣지 말고 근거로도 쓰지 마라.

**지킬 것**

  · 그림 번호는 **한 번씩만** 쓴다. 같은 컷을 두 자리에 넣지 마라.
  · 쓸 그림이 모자라면 비워라. 억지로 채우지 마라.

**돌려줄 것 — JSON 하나. 다른 말은 붙이지 마라.**

```json
{"타입":"","재질":"","무게":"","전원":"",
 "key1_t":"제목","key1_d":"한 줄 설명",
 "key2_t":"","key2_d":"",
 "key3_t":"","key3_d":"",
 "main":[16,31,14,26,12],"feature":[26,12,9,31,14],"package":[4],
 "body_start":7,
 "notes":["깨끗한 누끼컷이 없어 차선을 썼다"]}
```

**칸은 이 열여섯 개가 전부다. 안에 또 중괄호나 대괄호를 만들지 마라** —
`notes` 와 `main`·`feature` 만 배열이고, 그 안에는 값만 들어간다.
`main` · `feature` 는 **반드시 배열이고 다섯 칸**이다. 숫자 하나만 주지 마라.
`package` 는 상자가 확실할 때만 채우고, 아니면 `"package":[]` 로 비워라.
"""

#: 라벨을 못 받았을 때의 기본값. 차단하지 않는다.
UNKNOWN_KIND = "UNKNOWN"
#: 모델에 보낼 때 긴 변을 이만큼으로 줄인다.
SEND_PX = 900


def parts_for(name: str, brand: str, typed: str, cuts: list[Path],
              kinds: list[str]) -> list[tuple[str, str]]:
    """모델에 보낼 것을 순서대로 쌓는다 — 글 먼저, 그다음 번호·종류·그림.

    **차단이 아니라 순위다.** 처음에는 쓸 만한 것만 골라 보냈는데, 밴드 21개 중
    3개만 남아서 그림 자리가 거의 비었다. 전부 보내고 종류만 붙인다.

    제품컷을 TEXT 로 오판하지 않는 것이 최우선이라 애매하면 MIXED·UNKNOWN 으로
    남는다. 그러면 모델이 보고 판단할 기회가 있다.
    """
    head: list[tuple[str, str]] = [
        ("text", PROMPT),
        ("text", f"상품명: {name}\n브랜드: {brand}\n\n원본에 타이핑돼 있던 글:\n{typed}"),
        ("text", f"밴드 {len(cuts)}장을 위에서 아래 순서로 봅니다. 괄호 안이 그 밴드의 종류입니다."),
    ]
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


def take(reply: str, cuts: list[Path], kinds: list[str],
         hashes: list[int] | None = None,
         shots: dict[int, Shot] | None = None,
         blocked: set[int] | frozenset = frozenset()) -> tuple[Page, list[str]]:
    """모델이 돌려준 것을 받는다. **코드는 고르지 않고 거르기만 한다.**

    모델이 자리마다 후보를 순서대로 주면(`main`·`feature` 는 셋), `pick_slots` 가
    그 순서대로 검사해 첫 통과를 쓴다. 막는 것은 `reject` 의 셋 + 못 쓰는 밴드
    (TEXT·PROMO·요약정보 표·이미 쓴 것·같은 사진)뿐이다.

    셋 다 떨어지면 **비운다.** 예전에는 대표컷이 비면 코드가 페이지 전체를 훑어
    다시 골랐는데, 그 '다시 고르기' 가 6칸 격자나 파우치 컷을 대표컷으로 세웠다.
    잘못 세우는 것보다 비우고 왜 비었는지 말하는 편이 낫다.
    """
    m = re.search(r"\{[\s\S]*\}", reply or "")
    if not m:
        return Page(), ["모델이 JSON 을 안 돌려줬다"]
    try:
        got = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return Page(), [f"JSON 을 못 읽었다: {e}"]

    notes = [str(x) for x in got.get("notes") or []]
    hashes = hashes or []

    # 답은 **평평한 칸 열여섯**이다. 중첩을 없앤 이유는 모델이 자꾸 `keys` 배열의
    # 닫는 대괄호를 빠뜨려 답 전체가 버려졌기 때문이다(글랜스·다일레이터).
    # 옛 모양(`spec`·`keys` 중첩)도 받아 준다 — 저장해 둔 답이 아직 그 모양일 수 있다.
    nested = got.get("spec") or got.get("summary") or {}
    spec = {k: str(v).strip() for k, v in nested.items() if str(v).strip()}
    for k in ("타입", "재질", "무게", "전원", "특징"):
        if str(got.get(k, "")).strip():
            spec[k] = str(got[k]).strip()
    spec["치수"] = SIZE_FIXED

    keys = [
        (str(k.get("t") or k.get("title") or "").strip(),
         str(k.get("d") or k.get("desc") or "").strip())
        for k in (got.get("keys") or got.get("keyFeatures") or [])
        if isinstance(k, dict) and str(k.get("t") or k.get("title") or "").strip()
    ][:3]
    if not keys:
        keys = [(str(got.get(f"key{n}_t", "")).strip(), str(got.get(f"key{n}_d", "")).strip())
                for n in (1, 2, 3)]
        keys = [(t, d) for t, d in keys if t][:3]

    page = Page(spec=spec, keys=keys)
    mi, fi, pi, slot_notes = pick_slots(
        shots or {}, kinds, hashes, blocked,
        ai_main=got.get("main"), ai_feature=got.get("feature"),
        ai_package=got.get("package"))
    notes += slot_notes
    page.main = cuts[mi] if 0 <= mi < len(cuts) else None
    page.feature = cuts[fi] if 0 <= fi < len(cuts) else None
    page.package = cuts[pi] if 0 <= pi < len(cuts) else None
    page.main_band, page.feature_band, page.package_band = mi, fi, pi

    bs = got.get("body_start")
    page.body_start = bs if isinstance(bs, int) and 0 <= bs < len(cuts) else -1
    if page.body_start < 0 and bs is not None:
        notes.append(f"body_start 가 범위 밖이다: {bs!r}")
    return page, notes


def is_promo(arr: np.ndarray, url: str = "") -> bool:
    """바나나몰이 직접 찍어 붙인 홍보 움짤인가.

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


#: HERO 자리는 한 칸이다. 세로로 긴 컷을 그대로 넣으면 화면을 다 잡아먹고,
#: 가로로 넓은 컷을 넣으면 배너처럼 납작해진다. 그래서 **다시 앉힌다.**
HERO_W = 1000          #: 다시 앉힐 캔버스의 폭
HERO_FILL = 0.86       #: 제품이 캔버스에서 차지할 몫
HERO_MAX = 1.25        #: 세로가 가로의 이만큼을 넘으면 거기서 멈춘다 (4:5)
HERO_MIN = 0.45        #: 너무 납작하면 배너로 보인다. 여기까지만 눕힌다


def reframe(src: Path, out: Path, bg: tuple[int, int, int] = (255, 255, 255)) -> Path:
    """대표컷을 HERO 자리에 맞게 다시 앉힌다.

    조각의 비율이 제각각이다. 559×866 짜리 세로 컷을 그대로 넣으면 기둥이 된다
    (legacy ⓔ). **원본 이미지를 고치는 것이 아니다** — 잘라 둔 조각을 우리 자리에
    앉히는 것이다. 제품은 그대로 두고 둘레의 여백만 새로 잡는다.
    """
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
    ratio = body.height / max(1, body.width)
    hw = min(max(ratio, HERO_MIN), HERO_MAX)
    canvas = Image.new("RGB", (HERO_W, int(HERO_W * hw)), bg)

    room = (int(canvas.width * HERO_FILL), int(canvas.height * HERO_FILL))
    s = min(room[0] / body.width, room[1] / body.height)
    body = body.resize((max(1, int(body.width * s)), max(1, int(body.height * s))), Image.LANCZOS)
    canvas.paste(body, ((canvas.width - body.width) // 2, (canvas.height - body.height) // 2))
    canvas.save(out, quality=92)
    return out
