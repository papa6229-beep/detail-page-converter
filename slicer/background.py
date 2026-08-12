"""배경색 구간 분리 — DESIGN.md 4.4 결함 1번.

기존 구현은 배경을 **흰색으로 못박아** 판정했다. 그래서 텐가 하단 흑백 섹션에서
"배경인 행"이 하나도 나오지 않아 구간 전체가 한 덩이로 뭉쳤다.

여기서는 배경색을 상수로 두지 않고 **페이지 여백에서 관측**한다.

  배경(substrate) = 그 행의 좌우 바깥 여백 색

여백을 쓰는 이유가 있다. 패널 안쪽이 검다고 해서 그 구간의 배경이 검은 것은 아니다.
텐가 하단이 정확히 그 경우다 — 검은 것은 사진(콘텐츠)이고 페이지 바탕은 끝까지 흰색이다.
행 전체의 최빈색으로 배경을 잡으면 검은 사진에 속아 사진을 배경으로 오인하고 깎아낸다.
반대로 페이지 자체가 어두운 섹션이라면 여백까지 어두우므로 그때는 제대로 어둡게 잡힌다.

즉 이 모듈이 답하는 질문은 "이 픽셀이 어두운가"가 아니라
**"이 픽셀이 이 구간의 바탕과 같은가"** 이다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: JPEG 압축 잡음을 흡수하는 색 허용 오차(채널당).
DEFAULT_TOL = 14


@dataclass(frozen=True)
class Section:
    """배경색이 일정한 세로 구간."""

    y0: int
    y1: int
    bg: tuple[int, int, int]

    @property
    def h(self) -> int:
        return self.y1 - self.y0 + 1

    @property
    def is_dark(self) -> bool:
        return sum(self.bg) / 3 < 128


def bg_mask(sub: np.ndarray, bg, tol: int = DEFAULT_TOL) -> np.ndarray:
    """sub 의 각 픽셀이 배경색 bg 와 같은지."""
    diff = np.abs(sub.astype(np.int16) - np.asarray(bg, dtype=np.int16))
    return (diff <= tol).all(axis=-1)


def margin_colors(arr: np.ndarray, margin: int | None = None, agree: float = 0.6, tol: int = DEFAULT_TOL):
    """각 행의 좌우 바깥 여백 색을 관측한다.

    여백 픽셀들이 서로 충분히(agree 이상) 일치할 때만 그 행의 배경색으로 인정하고,
    아니면 None 을 돌려준다(테두리·본문이 여백까지 침범한 행).
    """
    h, w, _ = arr.shape
    if margin is None:
        margin = max(3, w // 64)
    margin = min(margin, max(1, w // 2))

    ring = np.concatenate([arr[:, :margin], arr[:, w - margin :]], axis=1).astype(np.int16)
    med = np.median(ring, axis=1).astype(np.int16)  # 행별 여백 중앙값
    close = (np.abs(ring - med[:, None, :]) <= tol).all(axis=-1)
    frac = close.mean(axis=1)

    out: list[tuple[int, int, int] | None] = []
    for y in range(h):
        out.append(tuple(int(v) for v in med[y]) if frac[y] >= agree else None)
    return out


def find_sections(
    arr: np.ndarray,
    tol: int = DEFAULT_TOL,
    min_height: int = 24,
    margin: int | None = None,
) -> list[Section]:
    """페이지를 배경색이 일정한 세로 구간들로 나눈다 (4.4 고칠 순서 1번).

    배경색이 페이지 내내 같으면 구간은 하나로 나온다. 그것이 정상이며,
    텐가가 바로 그 경우다 — 어두운 것은 배경이 아니라 패널이다.
    """
    h = arr.shape[0]
    colors = margin_colors(arr, margin=margin, tol=tol)

    # 관측 실패한 행은 직전 행 값으로 메운다. 맨 앞이 비면 뒤에서 당겨온다.
    filled: list[tuple[int, int, int] | None] = list(colors)
    last = None
    for y in range(h):
        if filled[y] is None:
            filled[y] = last
        else:
            last = filled[y]
    first = next((c for c in filled if c is not None), (255, 255, 255))
    filled = [c if c is not None else first for c in filled]

    # 같은 색이 이어지는 구간으로 묶는다.
    runs: list[list] = []
    for y, c in enumerate(filled):
        if runs and max(abs(a - b) for a, b in zip(runs[-1][2], c)) <= tol:
            runs[-1][1] = y
        else:
            runs.append([y, y, c])

    # 너무 짧은 구간은 독립된 배경 구간이 아니라 잡음이다. 이웃에 흡수시킨다.
    merged: list[list] = []
    for run in runs:
        if merged and (run[1] - run[0] + 1) < min_height:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    while len(merged) > 1 and (merged[0][1] - merged[0][0] + 1) < min_height:
        merged[1][0] = merged[0][0]
        merged.pop(0)

    return [Section(y0=r[0], y1=r[1], bg=tuple(int(v) for v in r[2])) for r in merged]
