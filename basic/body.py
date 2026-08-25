"""본문 밴드들을 섹션으로 묶는다. 판정은 최소로, 순서는 원본 그대로.

    섹션 = 번호 + (제목) + 사진들(각각 캡션 가능) + 설명

새 섹션이 시작되는 자리:
    · 배지(남색 알약 라벨)나 제목 밴드가 나오면
    · 제목이 한 번도 없는 페이지면, 설명 뒤에 다시 사진이 나오는 자리
그 밖의 밴드는 열려 있는 섹션에 붙는다. 사진 19장이면 19장 다 실린다 — 고르지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from . import bands as B
from . import sidetext

BADGE, TITLE, BODY, PHOTO, FOOT = "badge", "title", "body", "photo", "foot"

#: 제목이라 부를 최대 높이. 글줄 하나~둘. 본문 설명은 이보다 길다.
TITLE_MAX_H = 95


@dataclass
class Piece:
    kind: str                 #: badge | title | body | photo
    y: int
    h: int
    file: str = ""            #: 사진 파일 (photo)
    crop: str = ""            #: 글자 조각 파일 (title/body/캡션) — 읽기 대상
    text: str = ""            #: 읽은 글 (읽기 전엔 빈 칸)
    band_kind: str = ""
    why: str = ""


@dataclass
class Section:
    number: int
    title: Piece | None = None
    items: list[Piece] = field(default_factory=list)   #: 사진·설명을 원본 순서대로

    @property
    def photos(self):
        return [p for p in self.items if p.kind == PHOTO]

    @property
    def bodies(self):
        return [p for p in self.items if p.kind == BODY]


def _dark_box(crop: np.ndarray):
    """어두운 픽셀의 상자·채움 비율·글줄들의 높이. 배지(꽉 찬 알약)·제목(굵은 한 줄)·설명(여러 줄)을 가른다."""
    lum = crop.astype(np.float32) @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    dark = lum < 170
    if not dark.any():
        return None
    ys, xs = np.where(dark)
    bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    rows = dark.any(axis=1)
    runs, start = [], None
    for y, r in enumerate(rows):
        if r and start is None:
            start = y
        if not r and start is not None:
            runs.append(y - start); start = None
    if start is not None:
        runs.append(len(rows) - start)
    return bw, bh, float(dark.sum() / (bw * bh)), runs


def _role(b: B.Band, crop: np.ndarray) -> str:
    """밴드 하나의 역할. 종류(PHOTO/TEXT…)는 이미 붙어 있고, 여기선 자리를 정한다."""
    W = crop.shape[1]
    box = _dark_box(crop)
    if b.white < 0.12 and b.height < 160:
        return FOOT                               # 어두운 띠(푸터·저작권) — 버린다
    if box and box[1] <= 70 and box[0] < 0.5 * W and box[2] > 0.55:
        return BADGE                              # 좁고 꽉 찬 어두운 상자 = 라벨 알약
    if b.kind == B.TEXT:
        return BODY
    if box and b.white > 0.6 and b.color < 0.2 and box[2] < 0.5:
        lines = [r for r in box[3] if r >= 6]
        if lines and max(lines) <= 70:            # 글줄 높이 안쪽 — 사진은 한 덩이가 훨씬 크다
            if len(lines) == 1 and lines[0] >= 22 and b.height <= TITLE_MAX_H:
                return TITLE                      # 굵은 한 줄
            return BODY
    return PHOTO


def _split_badge(arr: np.ndarray, b: B.Band) -> list[B.Band]:
    """밴드 맨 위에 라벨 알약이 붙어 있으면 떼어 낸다 (배지↔제목 간격이 여백 기준보다 좁은 원본)."""
    crop = arr[b.y:b.y + b.height]
    lum = crop.astype(np.float32) @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    rows = (lum < 170).any(axis=1)
    if not rows.any() or rows[0]:
        pass
    ys = np.where(rows)[0]
    if not len(ys):
        return [b]
    top = ys[0]
    end = top
    while end < len(rows) and rows[end]:
        end += 1
    if end - top > 70 or end - top < 14 or end >= b.height - 8:
        return [b]
    head = crop[top:end]
    box = _dark_box(head)
    if not (box and box[0] < 0.5 * crop.shape[1] and box[2] > 0.55):
        return [b]
    cut = end
    while cut < b.height and not rows[cut]:
        cut += 1
    a = B.measure(arr, b.y, cut); a.kind, a.why = B.classify(a)
    c = B.measure(arr, b.y + cut, b.height - cut); c.kind, c.why = B.classify(c)
    return [a, c]


def _merge_text(pieces_raw):
    """글줄 사이에서 갈린 글자 밴드를 도로 붙인다. 붙은 것은 body 다."""
    out = []
    for b, crop, role in pieces_raw:
        if out and role == BODY and out[-1][2] == BODY:
            pb, pc, pr = out[-1]
            gap = b.y - (pb.y + pb.height)
            if gap <= 60:
                merged = np.concatenate([pc, np.full((gap, pc.shape[1], 3), 255, np.uint8), crop])
                nb = B.Band(pb.y, b.y + b.height - pb.y, pb.width, pb.white, pb.color, pb.ink,
                            pb.mean_sat, pb.max_row_dark, pb.largest_cc, pb.small_cc + b.small_cc,
                            pb.ncomp, pb.fill_ratio, pb.dhash, kind=pb.kind, why=pb.why)
                out[-1] = (nb, merged, BODY)
                continue
        out.append((b, crop, role))
    return out


def _save(arr: np.ndarray, out: Path, name: str, upscale: int = 1) -> str:
    im = Image.fromarray(arr)
    if upscale > 1:
        im = im.resize((im.width * upscale, im.height * upscale), Image.LANCZOS)
    im.save(out / name, quality=92)
    return name


def read_image(path: Path, out: Path, prefix: str = "") -> list[Piece]:
    """이미지 한 장 → 조각 목록(원본 순서)."""
    arr = np.asarray(Image.open(path).convert("RGB"))
    out.mkdir(parents=True, exist_ok=True)
    pieces: list[Piece] = []
    raw = []
    for b in B.read(arr):
        for bb in _split_badge(arr, b):
            crop = arr[bb.y:bb.y + bb.height]
            raw.append((bb, crop, _role(bb, crop)))
    for i, (b, crop, role) in enumerate(_merge_text(raw)):
        if role == FOOT:
            continue
        nm = f"{prefix}{i:02d}"
        if role == BADGE:
            pieces.append(Piece(BADGE, b.y, b.height, crop=_save(crop, out, f"{nm}_badge.png", 2),
                                band_kind=b.kind, why=b.why))
        elif role in (TITLE, BODY):
            pieces.append(Piece(role, b.y, b.height, crop=_save(crop, out, f"{nm}_{role}.png", 2),
                                band_kind=b.kind, why=b.why))
        else:
            sp = sidetext.split(crop)
            if sp is None:
                pieces.append(Piece(PHOTO, b.y, b.height, file=_save(crop, out, f"{nm}_photo.jpg"),
                                    band_kind=b.kind, why=b.why))
            else:
                pieces.append(Piece(PHOTO, b.y, b.height, file=_save(sp.photo, out, f"{nm}_photo.jpg"),
                                    crop=_save(sp.text, out, f"{nm}_caption.png", 2),
                                    band_kind=b.kind, why=b.why + " · 옆글자 떼어냄"))
    return pieces


def sections(pieces: list[Piece]) -> list[Section]:
    has_title = any(p.kind in (TITLE, BADGE) for p in pieces)
    secs: list[Section] = []
    cur: Section | None = None

    def new() -> Section:
        s = Section(len(secs) + 1)
        secs.append(s)
        return s

    for p in pieces:
        if p.kind == BADGE:
            cur = new()                     # 배지는 섹션 시작 신호. 글은 안 쓴다(상품명 반복)
            continue
        if p.kind == TITLE:
            if cur is not None and cur.title is not None and not cur.items:
                p.kind = BODY               # 제목 바로 뒤의 제목 = 부제. 섹션을 또 열지 않는다
                cur.items.append(p)
                continue
            if cur is None or cur.title is not None or cur.items:
                cur = new()
            cur.title = p
            continue
        if cur is None:
            cur = new()
        if (not has_title and p.kind == PHOTO and cur.bodies):
            cur = new()                     # 제목 없는 페이지: 설명 뒤 사진 = 다음 섹션
        cur.items.append(p)
    return [s for s in secs if s.title or s.items]
