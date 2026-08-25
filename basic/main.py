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

#: 대표컷이 되려면 이만한 크기는 돼야 한다. 페이지 폭에 대한 비율로 잰다 —
#: px 로 못박으면 폭이 다른 원본에서 그대로 어긋난다.
MIN_SIDE_FRAC = 0.25
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
    #: **테두리 한 겹의 채도.** 배경이 흰가 · 옅은 색인가 · 진한 색인가를 가른다.
    #: 밝은 쪽 40% 로 재던 것을 바꿨다 — 다일레이터처럼 제품 자체가 옅은 보라·연두면
    #: 제품 화소가 '배경' 에 섞여 들어와 흰 바탕인데도 23 이 나온다. 테두리는 안 섞인다.
    bg_sat: float = 0.0
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
    letters, solo = _blobs(lum)
    area = (r.x1 - r.x0 + 1) * (r.y1 - r.y0 + 1)
    # 배경은 **테두리 한 겹**으로 본다. 제품은 가운데에 있고 테두리는 바닥이다.
    t = max(2, min(6, crop.shape[0] // 8, crop.shape[1] // 8))
    edge = np.concatenate([crop[:t].reshape(-1, 3), crop[-t:].reshape(-1, 3),
                           crop[:, :t].reshape(-1, 3), crop[:, -t:].reshape(-1, 3)])
    med = np.median(edge, axis=0)
    bg_sat = float(med.max() - med.min())
    subject = float(((lum < 232) | (sat >= 45)).mean())
    return Shot(r, white, color, ink, letters, _densest(tint), solo, area, band,
                bg_sat=bg_sat, subject=subject)


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


def _content_rect(arr: np.ndarray, y: int, height: int) -> Rect | None:
    """밴드 안에서 **알맹이가 놓인 자리**만 집는다.

    밴드는 늘 폭 전체다. 그대로 재면 옆 여백이 값을 묽게 만들어, 제품이 작게
    놓인 컷과 크게 놓인 컷이 같아 보인다. legacy 의 분할기는 내용에 딱 맞게
    잘라 줬으므로, 여기서는 그 자리를 우리가 찾는다.
    """
    crop = arr[y : y + height].astype(np.int32)
    lum = (crop[..., 0] * 299 + crop[..., 1] * 587 + crop[..., 2] * 114) // 1000
    sat = crop.max(2) - crop.min(2)
    solid = (lum < 232) | (sat >= 45)
    if not solid.any():
        return None
    ys = np.where(solid.any(1))[0]
    xs = np.where(solid.any(0))[0]
    return Rect(int(xs[0]), y + int(ys[0]), int(xs[-1]), y + int(ys[-1]))


def shots(arr: np.ndarray, offset: int = 0) -> list[Shot]:
    """통이미지 한 장에서 대표컷 후보를 전부 재서 돌려준다.

    legacy 는 `slicer.slice_image` 를 썼다. 여기서는 밴드를 쓰고, 밴드 안의
    알맹이 자리를 따로 찾아 잰다.

    `offset` 은 이 이미지의 첫 밴드가 몇 번인가 — 상품 이미지가 여러 장이면
    밴드 번호가 이미지를 넘어서 이어지므로, 돌려주는 `Shot.band` 도 그 번호여야
    한다. **대표컷은 페이지 전체에서 찾는다** — 핑거위글은 깨끗한 단독컷이
    둘째 이미지에 있어서, 첫 이미지만 보면 하나도 못 고른다.
    """
    from . import sidetext

    w = arr.shape[1]
    floor = int(w * MIN_SIDE_FRAC)
    out = []
    for i, b in enumerate(B.read(arr)):
        r = _content_rect(arr, b.y, b.height)
        if r is None:
            continue
        if min(r.x1 - r.x0 + 1, r.y1 - r.y0 + 1) < floor:
            continue
        sh = _stats(arr, r, offset + i)
        # 글자가 박혀 있는가 — 밴드 종류와 `sidetext` 에게 **직접** 묻는다.
        sh.has_text = b.kind == B.MIXED or sidetext.split(arr[b.y:b.y + b.height]) is not None
        out.append(sh)
    return out


#: 대표컷이 되려면 제품이 한 덩어리로 찍혀 있어야 한다. 실측 —
#: 제품 셋이 쌓인 사이즈 구간 36% · 손이 든 컷 49% ↔ 제품 단독컷 95~100%.
SOLO = 0.9
#: 그 페이지에서 가장 깨끗한 컷보다 이만큼까지는 같이 본다. 딱 하나만 남기면
#: 워터마크 하나로 답이 뒤집힌다.
CLEAN_ROOM = 10
#: 원본 디자인의 색 글씨·배경이 박혀 있다고 보는 자리. 핑거위글 실측 —
#: 깨끗한 사진 0.4·0.6·0.6·4.2% ↔ 디자인이 박힌 것 23·31·31·32·38·61·62·100%.
DESIGN_INK = 0.15
#: 글 구간과 사진을 가르는 자리. 핑거위글 조각 열넷에서 **23 과 51 사이가 비어 있다**.
TEXT_BAND = 40


def pick_photos(cands: list[Shot]) -> list[Shot]:
    """쓸 만한 사진들. 대표컷보다 잣대가 헐거워야 한다.

    **못 쓰는 것은 세 가지뿐이다.**

        글 구간이다      원본 디자인의 글이 통째로 딸려 온다 (글자꼴 51개 이상)
        컬러 배경·배너다  원본 쇼핑몰의 색이 따라 들어온다
        상자다          제 네모를 꽉 채운 검은 덩어리 — 패키지 자리로 간다
    """
    return [
        c
        for c in cands
        if c.design < DESIGN_INK and c.letters < TEXT_BAND and 0.03 <= c.ink <= 0.75
    ]


def usable_photo(s: Shot) -> bool:
    """feature 자리에 쓸 수 있는가 — **느슨하게.** legacy 의 `pick_photos` 그대로.

    손이 들고 있어도, 거치대에 얹혀 있어도, 작은 주석이 붙어 있어도 쓴다.
    못 쓰는 것은 셋뿐이다 — 글 구간 · 컬러 배경/배너 · 제 네모를 꽉 채운 상자.
    """
    return s.design < DESIGN_INK and s.letters < TEXT_BAND and 0.03 <= s.ink <= 0.75


def clean_hero(s: Shot) -> bool:
    """대표컷 자리에 쓸 수 있는가 — **깐깐하게.**

    `pick_hero` 가 보는 것과 같은 잣대다: 유채색 배경이 없고(design), 큰 글자가
    구워져 있지 않고(letters), 제품이 화면을 적당히 채우며(ink), **한 덩어리**로
    찍혀 있어야 한다(solo). 모델이 골랐어도 이걸 못 넘으면 안 쓴다 —
    원본 대표컷은 하나같이 컬러 배경 위에 얹혀 있어서, 그대로 가져오면 새
    쇼핑몰에 남의 디자인이 따라 들어온다(legacy ⓖ).
    """
    return usable_photo(s) and s.solo >= SOLO


def why_not_hero(s: Shot) -> str:
    """못 넘은 까닭을 사람 말로. 조용히 버리지 않는다."""
    bad = []
    if s.design >= DESIGN_INK:
        bad.append(f"유채색 배경 {s.design:.2f}")
    if s.letters >= TEXT_BAND:
        bad.append(f"큰 글자 {s.letters}개")
    if not (0.03 <= s.ink <= 0.75):
        bad.append(f"제품 크기 {s.ink:.2f}")
    if s.solo < SOLO:
        bad.append(f"제품이 하나가 아님 {s.solo:.2f}")
    return " · ".join(bad) or "알 수 없음"


def pick_hero(cands: list[Shot]) -> Shot | None:
    """대표컷 하나를 고른다. 판정하지 않고 **그 페이지 안에서 견준다.**

    원본 대표컷은 못 쓴다 — 기본형 원본은 하나같이 컬러 배경 위에 제품을 얹어
    놓아서, 그대로 가져오면 새 쇼핑몰에 남의 디자인이 따라 들어온다.

    **깨끗함은 그 페이지 안에서만 뜻이 있다.** 상품 둘을 재보면 절대값으로는
    못 가른다 —

        핑거위글  제품 단독컷 글자꼴 0·0·2   거치대+리모컨 23   ← 23 을 빼야 한다
        글랜스    제품 단독컷 글자꼴 11·17·22                  ← 22 를 넣어야 한다

    같은 숫자가 두 답을 낸다. 그래서 그 페이지에서 가장 깨끗한 컷을 바닥으로
    삼고 거기서 얼마까지 봐줄지로 정한다.
    """
    photos = [c for c in pick_photos(cands) if c.solo >= SOLO]
    if not photos:
        return None
    floor = min(c.letters for c in photos)
    clean = [c for c in photos if c.letters <= floor + CLEAN_ROOM]
    return max(clean, key=lambda c: c.product_pixels)


def pick_hero_relaxed(cands: list[Shot]) -> Shot | None:
    """**페이지 전체에 원본 디자인 색이 깔려 있을 때**의 차선.

    브루스를 재보니 밴드 열아홉 장이 전부 `design` 0.38~1.00 이었다 — 보라 그라데
    이션이 페이지 바닥에 통째로 깔려 있어서, 그 잣대로는 **아무것도 못 가른다.**
    깨끗한 컷이 없는 게 아니라 그 페이지에 흰 바탕이 없는 것이다.

    그래서 `design` 하나만 뺀다. 나머지는 그대로 — 제품이 한 덩어리로 찍혔고
    (solo), 글이 적고(letters), 화면을 적당히 채워야(ink) 한다. 그 다음은
    `pick_hero` 와 같은 상대 잣대다.

    이걸 안 두면 `product_pixels` 만 보고 고르게 되는데, 브루스에서는 그러면
    구성품 컷(글자 68개 · 121k)이 제품 단독컷(글자 13개 · 121k)을 근소하게
    이겨서 파우치와 케이블과 분홍 캡션이 대표컷으로 올라간다.
    """
    photos = [c for c in cands
              if c.letters < TEXT_BAND and 0.03 <= c.ink <= 0.75 and c.solo >= SOLO]
    if not photos:
        return None
    floor = min(c.letters for c in photos)
    clean = [c for c in photos if c.letters <= floor + CLEAN_ROOM]
    return max(clean, key=lambda c: c.product_pixels)


# ── 등급 ────────────────────────────────────────────────────────────────
#
#   A  배경이 비어 있음(흰색) · 글자 없음 · 제품 하나        누끼 단독컷
#   B  배경에 옅은 색 · 손이 잡음 · 거치대 등 소품            누끼 연출컷
#   C  그 밖 (색 배경 진함 · 글자 박힘 · 여러 제품)
#
# **글자 수는 그 페이지 안에서만 뜻이 있다.** 절대값으로 자르면 못 가른다 —
#
#     핑거위글 누끼컷  0 · 0        거치대컷 24     ← 24 를 빼야 한다
#     다일레이터 누끼컷 6            평범한 제품컷 58·69·73·76
#                                    ← 무늬가 잘게 갈려 글자처럼 세어진다
#
# 같은 숫자가 두 답을 낸다. 그래서 그 페이지에서 가장 적은 것을 바닥으로 삼는다.
# B 는 글자 수를 아예 안 본다 — `has_text`(밴드 종류·sidetext)가 직접 말해 주므로
# 무늬를 글자로 오해할 일이 없다.
#
#: 배경이 "비어 있다"고 볼 테두리 채도. 흰 바탕 0~5, 진한 색 배경 10 위.
A_BG_SAT = 6.0
#: 바닥에서 이만큼까지는 "글자 없음" 으로 본다.
A_LETTER_ROOM = 8
#: 배경에 색이 깔려도 **옅으면** 연출컷. 브루스 보라(46)·다일레이터 초록(46)부터는 C.
B_BG_SAT = 8.0
#: 손이 잡거나 소품이 끼면 덩어리가 갈린다. 제품 둘까지 내려가면 C.
B_SOLO = 0.60


def letter_floor(cands) -> int:
    """그 페이지에서 가장 적은 글자 수. 없으면 0."""
    got = [c.letters for c in cands]
    return min(got) if got else 0


def grade(s: Shot, floor: int = 0) -> str:
    """후보 한 장의 등급. `floor` 는 그 페이지의 글자 수 바닥."""
    if s.has_text:
        return "C"                                    # 글자가 박혀 있다
    if s.bg_sat > B_BG_SAT:
        return "C"                                    # 색 배경이 진하다
    if s.solo < B_SOLO:
        return "C"                                    # 제품이 여럿이다
    # `design`(유채색이 가장 빽빽한 가로 띠)은 여기서 안 본다. 그것은 **배경에 색이
    # 깔렸는가**를 재려던 것인데, 제품 자체가 색이면(브루스 보라 0.68 · 다일레이터
    # 0.89) 제품을 배경으로 오해한다. 배경은 테두리(`bg_sat`)가 본다.
    if (s.bg_sat <= A_BG_SAT and s.solo >= SOLO
            and s.letters <= floor + A_LETTER_ROOM
            and 0.03 <= s.ink <= 0.75):
        return "A"
    return "B"


def pick_slots(shots: dict[int, Shot], kinds: list[str], hashes: list[int],
               blocked: set[int] | frozenset = frozenset(),
               ai_main=None, ai_feature=None) -> tuple[int, int, list[str]]:
    """대표컷과 키피쳐를 **같은 흐름으로** 고른다. (대표컷 밴드, 키피쳐 밴드, 메모)

    후보는 페이지 전체의 PHOTO·MIXED 밴드. 요약정보 표·TEXT·PROMO 는 뺀다.

        대표컷   A 에서만. A 가 없으면 B 에서 고르고 적는다
        키피쳐   대표컷을 뺀 나머지에서 A → B 순. C 는 안 쓴다
                 대표컷과 dHash 가 같으면 건너뛴다 — 같은 사진이 두 번 실린다

    **AI 픽은 먼저 검사하는 후보일 뿐이다.** 통과하면 쓰고, 떨어지면 코드가 고른다.
    전에는 대표컷에만 재선택이 있고 키피쳐엔 없어서, 모델이 침묵하거나 픽이
    떨어지면 KEY FEATURE 가 통째로 비었다.
    """
    notes: list[str] = []
    pool = {b: sh for b, sh in shots.items()
            if b < len(kinds) and kinds[b] in ("PHOTO", "MIXED") and b not in blocked}
    floor = letter_floor(pool.values())
    graded = {b: grade(sh, floor) for b, sh in pool.items()}

    def best(want: str, skip: set[int]) -> int | None:
        got = [b for b, g in graded.items() if g == want and b not in skip]
        return max(got, key=lambda b: pool[b].subject_pixels) if got else None

    def same_photo(a: int, b: int) -> bool:
        ha = hashes[a] if a < len(hashes) else 0
        hb = hashes[b] if b < len(hashes) else 0
        return B.hamming(ha, hb) <= B.DUP_HAMMING

    def ai_ok(pick, want: tuple[str, ...], why: str, skip: dict[int, str]) -> int | None:
        if not isinstance(pick, int):
            return None
        if pick not in pool:
            notes.append(f"{why}: AI 픽 [{pick}] 은 후보가 아니다"
                         f"({'요약정보 표' if pick in blocked else kinds[pick] if pick < len(kinds) else '범위 밖'})")
            return None
        if pick in skip:
            notes.append(f"{why}: AI 픽 [{pick}] 은 {skip[pick]}")
            return None
        if graded[pick] not in want:
            notes.append(f"{why}: AI 픽 [{pick}] 은 {graded[pick]}등급이라 떨어졌다 — {why_not_hero(pool[pick])}")
            return None
        return pick

    # ── 대표컷 ──
    hero = ai_ok(ai_main, ("A",), "대표컷", {})
    if hero is None:
        hero = best("A", set())
        if hero is not None and ai_main is not None:
            notes.append(f"대표컷을 A등급에서 다시 골랐다 — 밴드 [{hero}]")
    if hero is None:
        hero = best("B", set())
        if hero is not None:
            notes.append(f"A등급(누끼 단독컷)이 없어 B등급 밴드 [{hero}] 로 세웠다")
    if hero is None:
        hero = best("C", set())
        if hero is not None:
            notes.append(f"A·B 가 하나도 없어 C등급 밴드 [{hero}] 로 세웠다 — 눈으로 봐야 한다")

    # ── 키피쳐 ── 대표컷 자신과, 대표컷과 **같은 사진**인 밴드는 건너뛴다
    skip: dict[int, str] = {}
    if hero is not None:
        skip[hero] = "대표컷으로 이미 썼다"
        for b in pool:
            if b != hero and same_photo(b, hero):
                skip[b] = f"대표컷 [{hero}] 과 같은 사진이다"
    feat = ai_ok(ai_feature, ("A", "B"), "키피쳐", skip)
    if feat is None:
        feat = best("A", set(skip)) or best("B", set(skip))
        if feat is not None and ai_feature is not None:
            notes.append(f"키피쳐를 다시 골랐다 — 밴드 [{feat}]")
    if feat is None:
        notes.append("키피쳐 후보(A·B)가 없다 — 비워 둔다")

    for slot, b in (("대표컷", hero), ("키피쳐", feat)):
        if b is not None:
            notes.append(f"{slot} = 밴드 [{b}] · {graded[b]}등급")
    return (hero if hero is not None else -1,
            feat if feat is not None else -1,
            notes)


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
    #: 대표컷·키피쳐로 세운 밴드 번호와 등급. 보고용 — 사람이 봐야 한다.
    main_band: int = -1
    main_grade: str = ""
    feature_band: int = -1
    feature_grade: str = ""


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

3. **그림 고르기** — 자리마다 **가장 어울리는 것**을 고른다.

    main      대표컷. 배경색이 깔린 컷보다 **깨끗한 제품 단독컷**이 어울린다.
              깨끗한 컷이 없으면 그때는 차선을 고르고 `notes` 에 적어라.
    feature   핵심특징 옆에 놓일 컷. 대표컷과 다른 것으로.
    package   패키지 상자가 찍힌 컷. 없으면 비워라.

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
{"spec":{"타입":"","재질":"","무게":"","전원":""},
 "keys":[{"t":"제목","d":"한 줄 설명"},{"t":"","d":""},{"t":"","d":""}],
 "main":0,"feature":1,"package":null,
 "body_start":7,
 "notes":["깨끗한 누끼컷이 없어 차선을 썼다"]}
```
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
    """모델이 돌려준 것을 받는다. **그대로 믿지 않는다.**

    막는 것은 셋뿐이다 —

        TEXT · PROMO 밴드를 그림 자리에 넣었다   → 그 자리를 비운다
        같은 밴드를 두 자리에 넣었다             → 뒤엣것을 비운다
        같은 사진이 다른 밴드로 또 들어왔다        → dHash 로 알아보고 비운다

    **잘못된 사진보다 빈 칸이 안전하다.** 손님은 이 그림을 보고 주문한다.
    다만 대표컷만은 예외다 — 비면 페이지가 통째로 무너지므로 다시 고른다.

    대표컷과 키피쳐는 `pick_slots` 가 등급(A·B·C)으로 고른다. **모델 픽은 먼저
    검사하는 후보일 뿐이다** — 통과하면 쓰고 떨어지면 코드가 고른다. 모델은 원본
    대표컷(컬러 배경 위의 컷)을 곧잘 고르는데 그건 우리가 피하려던 바로 그것이다.
    `blocked` 는 어떤 경우에도 못 쓰는 밴드 — 요약정보 표가 든 자리다.
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
    used: list[int] = []

    def cut(v, why: str) -> int | None:
        """쓸 수 있으면 밴드 번호를, 못 쓰면 None. 막을 때마다 까닭을 적는다."""
        if not isinstance(v, int) or not (0 <= v < len(cuts)):
            return None
        kind = kinds[v] if v < len(kinds) else UNKNOWN_KIND
        if kind in ("TEXT", "PROMO"):
            notes.append(f"{why}: [{v}] 는 {kind} 라 그림으로 못 씀")
            return None
        if v in blocked:
            notes.append(f"{why}: [{v}] 는 원본 요약정보 표가 든 밴드라 못 씀")
            return None
        if v in used:
            notes.append(f"{why}: [{v}] 는 이미 다른 자리에 썼다")
            return None
        h = hashes[v] if v < len(hashes) else 0
        for u in used:
            if B.hamming(h, hashes[u] if u < len(hashes) else 0) <= B.DUP_HAMMING:
                notes.append(f"{why}: [{v}] 는 [{u}] 와 같은 사진이다")
                return None
        used.append(v)
        return v

    spec = {k: str(v).strip() for k, v in (got.get("spec") or got.get("summary") or {}).items()
            if str(v).strip()}
    spec["치수"] = SIZE_FIXED
    keys = [
        (str(k.get("t") or k.get("title") or "").strip(),
         str(k.get("d") or k.get("desc") or "").strip())
        for k in (got.get("keys") or got.get("keyFeatures") or [])
        if isinstance(k, dict) and str(k.get("t") or k.get("title") or "").strip()
    ][:3]

    page = Page(spec=spec, keys=keys)
    pi = cut(got.get("package"), "패키지")
    page.package = cuts[pi] if pi is not None else None

    # 대표컷과 키피쳐는 **같은 흐름**으로 고른다. AI 픽은 먼저 검사하는 후보일 뿐이다.
    mi, fi, slot_notes = pick_slots(shots or {}, kinds, hashes, blocked,
                                    ai_main=got.get("main"), ai_feature=got.get("feature"))
    notes += slot_notes
    page.main = cuts[mi] if 0 <= mi < len(cuts) else None
    page.feature = cuts[fi] if 0 <= fi < len(cuts) else None
    page.main_band, page.feature_band = mi, fi
    page.main_grade = grade(shots[mi]) if shots and mi in shots else ""
    page.feature_grade = grade(shots[fi]) if shots and fi in shots else ""
    if page.main is None:
        notes.append("대표컷 후보가 없다 — 손으로 지정해야 한다")

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
