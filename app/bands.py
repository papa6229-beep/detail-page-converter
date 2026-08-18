"""기본형 밴드 — 고도몰 생성기의 픽셀 계층을 그대로 옮긴 것.

**왜 우리 분할기를 안 쓰는가.**

우리 분할기는 단순형용이다 — 배경을 관측하고, 열을 나누고, 간격 분포를 본다.
같은 원본(핑거위글)을 저쪽은 **밴드 21개**로, 우리는 **조각 14개**로 가른다.

그런데 저쪽이 쌓아 둔 임계값(`largestCC 0.08` `smallCC 12` …)은 **저쪽 21밴드를
재서 나온 값**이다. 다른 조각 위에 갖다 대면 아무 뜻이 없다. 그래서 여기서는
조각 내는 방식부터 저쪽 것을 쓴다. 그래야 그 숫자들이 전부 그대로 쓰인다.

분할기가 둘이 되지만 그게 맞다 — 단순형 49개를 건드리지 않는다.

    출처: godo/src/components/detailBuilder/services/
          flowImageSplitter.ts  (splitImageByWhitespace)
          basicBandTagger.ts    (지표 6개 + dHash + classifyBand)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: 여백 분할 — `splitImageByWhitespace` 의 기본값 그대로.
WHITE_THR = 232      #: 이 밝기 이상이면 '흰 배경' 화소
WHITE_FRAC = 0.98    #: 행이 '빈 행'이 되려면 흰 화소가 이만큼
MIN_GAP = 40         #: 분할로 인정할 최소 여백 높이
MIN_SEG = 48         #: 유지할 최소 조각 높이 (구분선·잡음 제거)
SAMPLE_COLS = 64     #: 행마다 몇 열을 찍어 볼지

#: 밴드 태거 임계값 — `TAGGER_THRESHOLDS` 그대로.
TEXT_MAX_LARGEST_CC = 0.08
TEXT_MIN_SMALL_CC = 12
TEXT_MAX_COLOR = 0.10
TEXT_MIN_WHITE = 0.55
TEXT_MAX_ROW_DARK = 0.45
SUBJECT_MIN_LARGEST_CC = 0.12
SUBJECT_MIN_ROW_DARK = 0.30
MIXED_MIN_SMALL_CC = 20
PHOTO_MIN_COLOR = 0.15
CC_MAX_DIM = 200

#: 같은 사진인지 보는 거리. 실측 — 같은 사진 0~3 ↔ 다른 사진 27 이상.
DUP_HAMMING = 10

PHOTO, TEXT, MIXED, UNKNOWN = "PHOTO", "TEXT", "MIXED", "UNKNOWN"


def _lum(a: np.ndarray) -> np.ndarray:
    """`0.299R + 0.587G + 0.114B`. 저쪽과 같은 식이라야 같은 값이 나온다."""
    f = a.astype(np.float64)
    return f[..., 0] * 0.299 + f[..., 1] * 0.587 + f[..., 2] * 0.114


def _sat(a: np.ndarray) -> np.ndarray:
    f = a.astype(np.int32)
    return f.max(2) - f.min(2)


def blank_rows(arr: np.ndarray) -> np.ndarray:
    """행마다 '빈 행'인지.

    **최소 밝기가 아니라 비율로 본다.** 여백을 가로지르는 얇은 선이나 워터마크
    한 점에도 깨지면 여백 런이 잘게 쪼개진다. 비율이면 어두운 이물 2% 까지는
    봐주고 실제 구간 여백을 온전한 런으로 잡는다.
    """
    h, w, _ = arr.shape
    step = max(1, w // SAMPLE_COLS)
    cols = arr[:, ::step, :]
    return (_lum(cols) >= WHITE_THR).mean(1) >= WHITE_FRAC


def split_bands(arr: np.ndarray) -> list[tuple[int, int]]:
    """통이미지를 밴드로 가른다. `(위, 높이)` 목록을 위에서 아래 순서로.

    연속된 빈 행이 `MIN_GAP` 이상이면 그 **런의 한가운데**에서 끊는다.
    맨 위와 맨 아래 가장자리 여백은 컷으로 쓰지 않는다 — 거기서 끊으면
    빈 조각이 하나 생긴다.
    """
    h = arr.shape[0]
    blank = blank_rows(arr)

    cuts: list[int] = []
    start = -1
    for y in range(h + 1):
        is_blank = bool(blank[y]) if y < h else False
        if is_blank:
            if start < 0:
                start = y
        elif start >= 0:
            if y - start >= MIN_GAP and start > 0 and y < h:
                cuts.append((start + y) // 2)
            start = -1

    out: list[tuple[int, int]] = []
    edges = [0, *cuts, h]
    for top, bot in zip(edges, edges[1:]):
        while top < bot and blank[top]:
            top += 1
        while bot > top and blank[bot - 1]:
            bot -= 1
        if bot - top >= MIN_SEG:
            out.append((top, bot - top))
    return out or [(0, h)]


@dataclass
class Band:
    """밴드 하나와 그 위에서 잰 값들. 이름과 뜻을 저쪽과 똑같이 둔다."""

    y: int
    height: int
    width: int
    white: float
    color: float
    ink: float
    mean_sat: float
    max_row_dark: float   #: 행별 어두운 비율의 최대값 — 피사체가 가로로 넓게 놓였나
    largest_cc: float     #: 가장 큰 연결요소 면적 / **밴드 면적**
    small_cc: int         #: 글자꼴 작은 덩어리 개수
    ncomp: int
    fill_ratio: float     #: 전경이 제 bbox 를 채우는 비율 — 사각 상자는 높다
    dhash: int = 0
    kind: str = UNKNOWN
    why: str = ""
    rect: tuple[int, int, int, int] = field(default=(0, 0, 0, 0))


def measure(arr: np.ndarray, y: int, height: int) -> Band:
    """밴드 하나를 잰다. 재기만 하고 판정하지 않는다."""
    from PIL import Image

    crop = arr[y : y + height]
    h, w, _ = crop.shape
    step = max(1, w // SAMPLE_COLS)
    cols = crop[:, ::step, :]
    lum, sat = _lum(cols), _sat(cols)

    white = float((lum >= 232).mean())
    ink = float(((lum < 115) & (sat < 40) & (lum < 232)).mean())
    color = float(((sat >= 45) & (lum < 245)).mean())
    mean_sat = float(sat.mean())
    max_row_dark = float((lum < 140).mean(1).max()) if h else 0.0

    # 연결요소는 줄여서 본다. 저쪽은 캔버스로 부드럽게 줄이므로 여기서도 같은
    # 방식을 쓴다 — 최근접으로 뽑으면 글자가 끊겨 덩어리 개수가 달라진다.
    scale = min(1.0, CC_MAX_DIM / max(w, h))
    tw, th = max(1, round(w * scale)), max(1, round(h * scale))
    small = np.asarray(Image.fromarray(crop).resize((tw, th), Image.BILINEAR))
    slum, ssat = _lum(small), _sat(small)
    fg = (slum < 200) | ((ssat >= 45) & (slum < 245))

    largest_cc = small_cc = ncomp = 0
    fill_ratio = 0.0
    if fg.any():
        ys, xs = np.where(fg.any(1))[0], np.where(fg.any(0))[0]
        bbox = (ys[-1] - ys[0] + 1) * (xs[-1] - xs[0] + 1)
        fill_ratio = float(fg.sum() / bbox) if bbox else 0.0
        sizes = _components(fg)
        if sizes:
            ncomp = len(sizes)
            biggest = max(sizes)
            largest_cc = biggest / (tw * th)
            cap = max(6, biggest * 0.15)
            small_cc = sum(1 for v in sizes if 3 <= v <= cap)

    return Band(y, height, w, white, color, ink, mean_sat, max_row_dark,
                largest_cc, small_cc, ncomp, fill_ratio, _dhash(crop),
                rect=(0, y, w, height))


def _components(fg: np.ndarray) -> list[int]:
    """4-이웃 연결요소 크기 목록. 줄 단위 구간을 이어붙여 센다 (scipy 없이)."""
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
    for row in fg:
        if not row.any():
            prev = []
            continue
        edges = np.flatnonzero(np.diff(np.concatenate(([0], row.view(np.int8), [0]))))
        cur = []
        for s, e in zip(edges[::2], edges[1::2]):
            parent[nid] = nid
            sizes[nid] = int(e - s)
            for ps, pe, pid in prev:
                if s < pe and ps < e:
                    union(pid, nid)
            cur.append((int(s), int(e), nid))
            nid += 1
        prev = cur

    total: dict[int, int] = {}
    for i, n in sizes.items():
        total[find(i)] = total.get(find(i), 0) + n
    return list(total.values())


def _dhash(crop: np.ndarray) -> int:
    """9×8 그레이스케일 difference hash. 같은 사진이 두 밴드에 들어가는 것을 막는다."""
    from PIL import Image

    g = np.asarray(Image.fromarray(crop).convert("L").resize((9, 8), Image.BILINEAR), dtype=np.int32)
    bits = (g[:, :8] < g[:, 1:]).flatten()
    out = 0
    for b in bits:
        out = (out << 1) | int(b)
    return out


def hamming(a: int, b: int) -> int:
    """두 dHash 사이의 거리. 하나라도 없으면 **비교 불가 = 다름**(64)."""
    if not a or not b:
        return 64
    return bin(a ^ b).count("1")


def classify(m: Band) -> tuple[str, str]:
    """지표 → 종류. **제품컷을 TEXT 로 오판하지 않는 것이 최우선.**

    애매하면 MIXED 나 UNKNOWN 으로 둔다. 차단이 아니라 **순위**다 —
    이미지 자리는 PHOTO 우선, MIXED 차선, UNKNOWN 은 다른 후보가 없을 때.
    TEXT 만 이미지 자리에 못 들어간다.
    """
    if (
        m.largest_cc < TEXT_MAX_LARGEST_CC
        and m.small_cc >= TEXT_MIN_SMALL_CC
        and m.color < TEXT_MAX_COLOR
        and m.white >= TEXT_MIN_WHITE
        and m.max_row_dark < TEXT_MAX_ROW_DARK
    ):
        return TEXT, f"글자만 — 큰덩어리 {m.largest_cc:.3f} · 글자꼴 {m.small_cc}"

    subject = m.largest_cc >= SUBJECT_MIN_LARGEST_CC or m.max_row_dark >= SUBJECT_MIN_ROW_DARK
    if subject and m.small_cc >= MIXED_MIN_SMALL_CC:
        return MIXED, f"제품+주석 — 큰덩어리 {m.largest_cc:.3f} · 글자꼴 {m.small_cc}"
    if subject or m.color >= PHOTO_MIN_COLOR:
        return PHOTO, f"제품컷 — 큰덩어리 {m.largest_cc:.3f} · 가로점유 {m.max_row_dark:.2f}"
    return UNKNOWN, f"애매 — 큰덩어리 {m.largest_cc:.3f} · 글자꼴 {m.small_cc}"


def read(arr: np.ndarray) -> list[Band]:
    """통이미지 한 장 → 잰 밴드 목록. 이것 하나가 기본형 픽셀 계층의 전부다."""
    out = []
    for y, h in split_bands(arr):
        b = measure(arr, y, h)
        b.kind, b.why = classify(b)
        out.append(b)
    return out
