"""사각형 좌표. 모든 좌표는 끝값 포함(inclusive)이다."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def w(self) -> int:
        return self.x1 - self.x0 + 1

    @property
    def h(self) -> int:
        return self.y1 - self.y0 + 1

    @property
    def area(self) -> int:
        return self.w * self.h

    def crop(self, arr):
        return arr[self.y0 : self.y1 + 1, self.x0 : self.x1 + 1]

    def size_along(self, axis: int) -> int:
        """axis=0 이면 세로 길이, axis=1 이면 가로 길이."""
        return self.h if axis == 0 else self.w

    def sub(self, axis: int, start: int, end: int) -> "Rect":
        """axis 방향으로 [start, end] 구간만 남긴 사각형. start/end 는 rect 내부 상대 좌표."""
        if axis == 0:
            return Rect(self.x0, self.y0 + start, self.x1, self.y0 + end)
        return Rect(self.x0 + start, self.y0, self.x0 + end, self.y1)

    def union(self, other: "Rect") -> "Rect":
        return Rect(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x0, self.y0, self.x1, self.y1)


def union_all(rects) -> Rect | None:
    rects = list(rects)
    if not rects:
        return None
    out = rects[0]
    for r in rects[1:]:
        out = out.union(r)
    return out
