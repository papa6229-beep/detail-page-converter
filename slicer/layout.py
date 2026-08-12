"""세로 절단 — DESIGN.md 4.4 결함 2번.

기존 구현은 **가로 스캔만** 했다. 2열 구간에서는 좌우 칸이 같은 행을 공유하므로
가로 스캔만으로는 어느 캡션이 어느 이미지 것인지 알 수 없다. 그래서 캡션이 한 칸 밀렸다.

방향을 하나 더 주면 되지만, **순서가 중요하다.** 텐가의 2열 구간은 좌우 칸의
이미지 아래끝이 y=1623 으로 정확히 같아서, 가로로 먼저 자르면 페이지 전체 폭을
가로지르는 "이미지 줄"과 "캡션 줄"로 갈린다. 조각은 다 살아 있지만 좌우가 섞여
짝을 지을 수 없게 된다 — 불변식 ①은 통과하고 ⑥만 걸리는, 바로 그 실패다.

그래서 DESIGN.md 4.4 의 순서를 그대로 따른다.

    1. 배경색 구간          background.find_sections
    2. 구간 → 밴드 → **열**  이 모듈
    3. 열 안에서 다시 밴드   이 모듈, 그다음 gaps 로 귀속

단계를 셋으로 못박은 것은 소심해서가 아니다. 무한히 교대로 자르면 캡션 글줄이
글자 덩어리로 부서진다. 글자 사이 여백(최대 12px)과 3열 광고컷의 열 여백(13px)은
너비만으로 구별되지 않기 때문에, 깊이로 끊는 것이 유일하게 안전한 방법이다.
정규형이 요구하는 깊이도 딱 여기까지다 — 구간 · 열 · 밴드.

구분자는 두 종류다.

    배경 줄  — 그 줄이 전부 배경색           (칸 사이 여백)
    괘선     — 그 줄이 단색이고 아주 얇음     (텐가의 주황 표 선)

괘선을 인정하지 않으면 표 형식 원본에서 칸이 갈리지 않는다. 두께 상한을 두는 것은
텐가 상단의 빨간 `TENGA EGG 2018` 띠(96px) 같은 단색 콘텐츠를 구분자로 먹지 않기 위해서다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .background import DEFAULT_TOL, bg_mask
from .geometry import Rect

ROW, COL = 0, 1


@dataclass(frozen=True)
class CutConfig:
    tol: int = DEFAULT_TOL
    #: 구분자로 인정할 단색 괘선의 최대 두께(px).
    max_rule: int = 6
    #: 이보다 얇은 조각은 이웃에 흡수시킨다.
    min_panel: int = 8
    #: 한 줄에서 무시할 이물 픽셀 비율.
    #:
    #: 괘선 양옆에는 JPEG 안티에일리어싱이 한두 픽셀 반드시 낀다. 줄 전체가
    #: 배경/단색이어야 한다고 엄격하게 보면 그 한 픽셀 때문에 표 선이 구분자로
    #: 인정되지 않고 2열 구간이 통째로 안 갈린다. 실제로 그렇게 깨졌다.
    outlier_frac: float = 0.01
    #: 고랑으로 인정할 최소 세로 길이(구간 높이 대비).
    min_gutter_frac: float = 0.5
    #: 이보다 납작한 사각형은 글줄로 보고 열을 찾지 않는다.
    max_line_aspect: float = 8.0
    #: 열이 하나뿐인 밴드를 몇 겹까지 더 파고들지.
    max_rounds: int = 2


@dataclass
class Node:
    """절단 결과의 한 조각.

    kind 는 column 또는 leaf 다. 'column' 이 곧 칸이고, 캡션 귀속은 그 안에서 일어난다.
    """

    rect: Rect
    kind: str = "leaf"
    axis: int | None = None
    children: list["Node"] = field(default_factory=list)
    #: 자식 사이 간격(px). len(children) - 1 개.
    gaps: list[int] = field(default_factory=list)
    #: 이 칸이 속한 밴드에서 몇 번째 열인지.
    col_index: int = 0
    col_total: int = 1

    @property
    def is_leaf(self) -> bool:
        return not self.children

    def leaves(self) -> list["Node"]:
        if self.is_leaf:
            return [self]
        return [leaf for c in self.children for leaf in c.leaves()]


def runs_of(mask) -> list[tuple[int, int]]:
    """True 가 연속된 구간들을 [start, end] 로.

    파이썬 반복문으로 돌면 고랑 검출에서만 200만 번을 돈다. 경계는 차분의
    부호가 바뀌는 자리이므로 numpy 로 한 번에 찾는다.
    """
    m = np.asarray(mask, dtype=bool)
    if m.size == 0:
        return []
    d = np.diff(m.view(np.int8))
    starts = np.flatnonzero(d == 1) + 1
    ends = np.flatnonzero(d == -1)
    if m[0]:
        starts = np.concatenate(([0], starts))
    if m[-1]:
        ends = np.concatenate((ends, [m.size - 1]))
    return list(zip(starts.tolist(), ends.tolist()))


def _spread(lines: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """|lines - ref| 를 uint8 그대로 계산한다.

    int16 으로 올려서 빼면 배열을 통째로 한 벌 더 만든다. 원본 크기에서
    이 업캐스트 하나가 분할기 시간의 큰 몫을 차지했다.
    """
    return np.maximum(lines, ref) - np.minimum(lines, ref)


def line_flags(sub: np.ndarray, bg, axis: int, cfg: CutConfig):
    """axis 방향 각 줄이 구분자인지, 그리고 그 줄이 괘선인지.

    axis=ROW 면 줄은 가로줄(행), axis=COL 이면 세로줄(열)이다.
    """
    lines = sub if axis == ROW else sub.transpose(1, 0, 2)  # (n, k, 3) uint8
    n, k, _ = lines.shape
    keep = 1.0 - cfg.outlier_frac
    tol = cfg.tol

    # 줄 대부분은 콘텐츠라 배경도 괘선도 아니다. 그런 줄까지 전 픽셀을 훑는 것은
    # 낭비이므로, 고르게 뽑은 표본으로 먼저 걸러내고 살아남은 줄만 제대로 센다.
    # 표본 기준을 실제 기준(99%)보다 느슨한 90% 로 두어야 통과할 줄을 놓치지 않는다.
    sidx = np.linspace(0, k - 1, min(k, 64)).astype(np.intp)
    samp = lines[:, sidx]

    def _confirm(cand: np.ndarray, ref) -> np.ndarray:
        """표본을 통과한 줄만 전체 픽셀로 확인한다."""
        out = np.zeros(n, dtype=bool)
        idxs = np.flatnonzero(cand)
        if idxs.size:
            r = ref if ref.ndim == 1 else ref[idxs][:, None, :]
            out[idxs] = (_spread(lines[idxs], r) <= tol).all(axis=2).mean(axis=1) >= keep
        return out

    bg_arr = np.asarray(bg, dtype=lines.dtype)
    is_bg = _confirm((_spread(samp, bg_arr) <= tol).all(axis=2).mean(axis=1) >= 0.9, bg_arr)

    # 줄의 대표색. 전체 중앙값(partition)은 O(k log k) 라 비싸고, 여기서 필요한 것은
    # "이 줄이 단색인가"뿐이므로 표본의 중앙값으로 충분하다.
    ref = np.median(samp, axis=1).astype(lines.dtype)  # (n, 3)
    near = (_spread(samp, ref[:, None, :]) <= tol).all(axis=2).mean(axis=1) >= 0.9
    uniform = _confirm(near & ~is_bg, ref) & ~is_bg

    rule = np.zeros(n, dtype=bool)
    for s, e in runs_of(uniform):
        if e - s + 1 <= cfg.max_rule:  # 얇은 단색 = 괘선, 두꺼우면 콘텐츠
            rule[s : e + 1] = True
    return is_bg | rule, rule


class Scan:
    """한 번의 분할 동안 줄 판정 결과를 기억한다.

    밴드를 자르고 여백을 벗기고 다시 자르는 과정에서 **같은 사각형을 같은 방향으로**
    몇 번씩 다시 훑게 된다. 텐가 원본에서 462번 중 대부분이 그런 재계산이었다.
    사각형과 방향만 같으면 답도 같으므로 그냥 기억해 두면 된다.
    """

    __slots__ = ("arr", "bg", "cfg", "_memo")

    def __init__(self, arr: np.ndarray, bg, cfg: CutConfig):
        self.arr = arr
        self.bg = tuple(int(v) for v in bg)
        self.cfg = cfg
        self._memo: dict = {}

    def axis_flags(self, rect: Rect, axis: int):
        """축 하나만 필요할 때 다른 축까지 훑지 않는다."""
        key = (rect.as_tuple(), axis)
        hit = self._memo.get(key)
        if hit is None:
            hit = line_flags(rect.crop(self.arr), self.bg, axis, self.cfg)
            self._memo[key] = hit
        return hit

    def flags(self, rect: Rect):
        return self.axis_flags(rect, ROW), self.axis_flags(rect, COL)


def _as_scan(scan, arr, bg, cfg) -> Scan:
    return scan if scan is not None else Scan(arr, bg, cfg)


def absorb_small(parts: list[tuple[int, int]], min_size: int) -> list[tuple[int, int]]:
    """min_size 보다 얇은 조각을 **가까운 쪽** 이웃에 흡수시킨다.

    그냥 버리면 불변식 ①(면적 보존)이 깨진다. 얇은 조각도 잉크는 잉크다.
    """
    out = [list(p) for p in parts]
    while len(out) > 1:
        for i, (s, e) in enumerate(out):
            if e - s + 1 >= min_size:
                continue
            prev_gap = s - out[i - 1][1] if i > 0 else None
            next_gap = out[i + 1][0] - e if i + 1 < len(out) else None
            if prev_gap is None:
                j = i + 1
            elif next_gap is None:
                j = i - 1
            else:
                j = i - 1 if prev_gap <= next_gap else i + 1
            out[j] = [min(s, out[j][0]), max(e, out[j][1])]
            out.pop(i)
            break
        else:
            break
    return [tuple(p) for p in out]


def trim(arr: np.ndarray, rect: Rect, bg, cfg: CutConfig, scan: Scan | None = None) -> Rect | None:
    """사각형 가장자리의 배경·괘선을 벗긴다. 통째로 배경이면 None.

    두 축을 한 번에 재서 적용한다. 한 축씩 벗기고 다시 훑으면 줄어드는 사각형마다
    전체를 다시 계산하게 되는데, 그게 분할기 시간의 3분의 2였다.
    """
    scan = _as_scan(scan, arr, bg, cfg)
    for _ in range(4):  # 보통 한두 바퀴에 멈춘다
        (row_sep, _r), (col_sep, _c) = scan.flags(rect)
        rows, cols = runs_of(~row_sep), runs_of(~col_sep)
        if not rows or not cols:
            return None
        y0, y1 = rows[0][0], rows[-1][1]
        x0, x1 = cols[0][0], cols[-1][1]
        nxt = Rect(rect.x0 + x0, rect.y0 + y0, rect.x0 + x1, rect.y0 + y1)
        if nxt == rect:
            break
        rect = nxt
    return rect


def split_axis(
    arr: np.ndarray, rect: Rect, bg, cfg: CutConfig, axis: int, scan: Scan | None = None
) -> tuple[list[Rect], list[int]]:
    """rect 를 axis 방향 구분자에서 자른다."""
    sep, _ = _as_scan(scan, arr, bg, cfg).axis_flags(rect, axis)
    parts = runs_of(~sep)
    if not parts:
        return [], []

    kept = absorb_small(parts, cfg.min_panel)
    rects = [rect.sub(axis, s, e) for s, e in kept]
    gaps = [kept[i + 1][0] - kept[i][1] - 1 for i in range(len(kept) - 1)]
    return rects, gaps


def gutter_extents(
    arr: np.ndarray, rect: Rect, bg, cfg: CutConfig, scan: Scan | None = None
) -> list[tuple[int, int]]:
    """세로 여백(고랑)이 **세로로 어디까지 뻗는지** 관측한다.

    여기가 결함 2번의 급소다. 텐가의 열 구분선은 y=1323 부터 시작한다. 페이지 전체
    높이를 훑는 고랑을 찾으면 하나도 안 나오고, 그래서 2열 구간이 발견되지 않는다.
    반대로 고랑의 **세로 구간**을 먼저 재면 "여기부터 아래가 2열"이 그냥 읽힌다.

    2열인지 판정하지 않는다. 고랑이 어디서 어디까지인지 잴 뿐이다.
    돌려주는 것은 열이 갈리는 y 구간들이다.
    """
    sub = rect.crop(arr)
    _, row_rule = _as_scan(scan, arr, bg, cfg).axis_flags(rect, ROW)

    # 고랑을 가로지르는 얇은 가로 괘선은 고랑을 끊지 않는다. 이걸 빼먹으면
    # 텐가의 고랑이 표 가로선마다 토막나 한 칸 높이(345px)로만 잡히고,
    # 2열 구간을 통째로 보지 못한다.
    free = bg_mask(sub, bg, cfg.tol) | row_rule[:, None]

    h, w = free.shape
    floor = max(cfg.min_panel, int(cfg.min_gutter_frac * h))

    spans: list[tuple[int, int] | None] = []
    for x in range(w):
        rs = runs_of(free[:, x])
        if not rs:
            spans.append(None)
            continue
        s, e = max(rs, key=lambda r: r[1] - r[0])
        spans.append((s, e) if e - s + 1 >= floor else None)

    # 고랑 한가운데 그어진 얇은 괘선(텐가의 주황 선)은 고랑을 끊지 않는다.
    ok = np.array([s is not None for s in spans])
    for s, e in runs_of(~ok):
        if s > 0 and e < w - 1 and e - s + 1 <= cfg.max_rule:
            ok[s : e + 1] = True

    extents: list[tuple[int, int]] = []
    for xa, xb in runs_of(ok):
        if xa == 0 or xb == w - 1:  # 바깥 여백이지 고랑이 아니다
            continue
        if xb - xa + 1 < cfg.min_panel:
            continue
        # 고랑의 세로 범위는 **다수결**로 정한다. 열 하나하나의 교집합으로 잡으면
        # 잡음 낀 열 한 줄이 범위를 통째로 잘라먹어, 허용 오차를 조금만 움직여도
        # 고랑이 있다가 없어진다(tol 6·10·14 에서는 잡히고 8 에서는 사라졌다).
        vote = free[:, xa : xb + 1].mean(axis=1) >= 0.5
        candidates = runs_of(vote)
        if not candidates:
            continue
        y0, y1 = max(candidates, key=lambda r: r[1] - r[0])
        if y1 - y0 + 1 >= floor:
            extents.append((y0, y1))
    return extents


def bands_from_gutters(
    arr: np.ndarray, rect: Rect, bg, cfg: CutConfig, scan: Scan | None = None
) -> list[Rect]:
    """고랑의 세로 구간 경계에서 밴드를 나눈다.

    고랑이 없거나 사각형 전체를 덮으면 밴드는 하나다.
    """
    extents = gutter_extents(arr, rect, bg, cfg, scan)
    if not extents:
        return [rect]

    n = rect.h
    cuts = {0, n}
    for y0, y1 in extents:
        cuts.add(y0)
        cuts.add(min(y1 + 1, n))
    edges = sorted(cuts)
    bands = [rect.sub(ROW, a, b - 1) for a, b in zip(edges, edges[1:]) if b - a >= cfg.min_panel]
    return bands or [rect]


def rule_rows(arr: np.ndarray, rect: Rect, bg, cfg: CutConfig, scan: Scan | None = None) -> np.ndarray:
    """구간 **전체 폭**을 가로지르는 얇은 괘선의 행 마스크.

    DESIGN.md 3.1 은 라인 검출로 유닛을 판정하지 말라고 한다. 옳다 — 그리고
    여기서도 그러지 않는다. 이 마스크가 하는 일은 4.4 의 2단계, **칸의 기하**를
    잡는 것뿐이다. 무엇이 유닛인지는 여전히 캡션과 간격이 정한다.

    폭 전체를 요구하는 것이 핵심이다. 텐가 왼쪽 두 번째 칸 안에는 사진 콜라주를
    가르는 얇은 선이 있는데, 그건 칸 경계가 아니라 그림의 일부다. 페이지를 가로지르는
    표 선만이 칸을 가른다. 칸 폭에서 재면 둘이 구별되지 않는다.
    """
    _, rule = _as_scan(scan, arr, bg, cfg).axis_flags(rect, ROW)
    return rule


def rule_gaps(rules: np.ndarray, origin: int, bands: list[Rect]) -> list[bool]:
    """밴드 사이 여백에 구간 전체 폭의 괘선이 들어 있는지."""
    out: list[bool] = []
    for a, b in zip(bands, bands[1:]):
        s, e = a.y1 + 1 - origin, b.y0 - 1 - origin
        out.append(bool(rules[max(s, 0) : e + 1].any()) if e >= s else False)
    return out


def _has_columns(rect: Rect, cfg: CutConfig) -> bool:
    """줄글 한 줄은 열을 갖지 않는다.

    글자 사이 여백(텐가 캡션에서 최대 12px)은 3열 광고컷의 열 여백(13px)과
    너비만으로 구별되지 않는다. 대신 모양으로 구별된다 — 폭에 비해 터무니없이
    납작한 사각형은 레이아웃이 아니라 글줄이다. 여기서 끊지 않으면 캡션이
    글자 덩어리로 부서진다.
    """
    return rect.w <= cfg.max_line_aspect * rect.h


def build_columns(
    arr: np.ndarray,
    rect: Rect,
    bg,
    cfg: CutConfig | None = None,
    depth: int = 0,
    scan: Scan | None = None,
) -> list[Node]:
    """구간 하나를 칸(column) 목록으로 환원한다.

    밴드 → 열 → 밴드. 열이 하나뿐인 밴드는 한 겹 더 들어가 본다
    (텐가 상단 광고컷의 3열 그리드가 그렇게 잡힌다).
    """
    cfg = cfg or CutConfig()
    scan = _as_scan(scan, arr, bg, cfg)
    rect = trim(arr, rect, bg, cfg, scan)
    if rect is None:
        return []

    out: list[Node] = []
    for band in bands_from_gutters(arr, rect, bg, cfg, scan):
        band = trim(arr, band, bg, cfg, scan)
        if band is None:
            continue

        if _has_columns(band, cfg):
            cols, _ = split_axis(arr, band, bg, cfg, COL, scan)
        else:
            cols = [band]

        if len(cols) <= 1 and depth < cfg.max_rounds:
            # 열이 하나로 보여도 한 겹 아래에 열이 숨어 있을 수 있다
            # (텐가 상단 광고컷의 3열 그리드가 그렇다).
            # 다만 **정말 열이 나왔을 때만** 그 분해를 받아들인다. 그러지 않으면
            # 세로로 [이미지][캡션] 이 쌓인 1열 원본이 밴드마다 따로 놀아
            # 짝을 지을 기회 자체가 사라진다.
            subs, _ = split_axis(arr, band, bg, cfg, ROW, scan)
            if len(subs) > 1:
                deeper = [c for s in subs for c in build_columns(arr, s, bg, cfg, depth + 1, scan)]
                if any(c.col_total > 1 for c in deeper):
                    out.extend(deeper)
                    continue

        total = len(cols)
        for i, col in enumerate(cols):
            col = trim(arr, col, bg, cfg, scan)
            if col is None:
                continue
            subs, _ = split_axis(arr, col, bg, cfg, ROW, scan)
            subs = [t for t in (trim(arr, s, bg, cfg, scan) for s in subs) if t is not None]
            if not subs:
                subs = [col]
            out.append(
                Node(
                    rect=col,
                    kind="column",
                    axis=ROW if len(subs) > 1 else None,
                    children=[Node(rect=s, kind="leaf") for s in subs],
                    col_index=i,
                    col_total=total,
                )
            )
    return out
