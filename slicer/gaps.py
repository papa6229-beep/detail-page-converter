"""간격 이중구조로 유닛을 묶는다 — DESIGN.md 4.3.

캡션이 이미지 위인지 아래인지는 디자인마다 다르다. 규칙으로 박으면 깨진다.
대신 **간격이 두 무리로 갈린다**는 성질을 쓴다. 좁은 간격은 한 유닛 안(이미지↔캡션),
넓은 간격은 유닛 경계다.

임계값을 사람이 정하지 않는다. 그 이미지 안의 간격 분포에서 가장 크게 벌어지는
자리를 찾아 거기를 자른다. 페이지마다 여백 크기가 달라도 "이 페이지 안에서
좁냐 넓냐"는 항상 갈린다.

갈라지지 않을 수도 있다. 간격이 다 고만고만하면 유닛은 하나다.
그때 억지로 자르지 않는 것이 중요하다 — 텐가의 칸 하나가 정확히 그 경우로,
`[이미지] 6px [캡션] 4px [캡션] 4px [캡션]` 이라 최대/최소 비가 1.5배에 그친다.
유닛 경계는 이미 표 괘선이 만들어 줬으므로 칸 안에서 또 자를 이유가 없다.
"""

from __future__ import annotations

from dataclasses import dataclass

#: 비를 잴 때 더하는 완충값. 1px 미만의 차이가 큰 비로 증폭되는 것을 막는다.
SMOOTH = 2


@dataclass(frozen=True)
class GapSplit:
    """간격 분포를 좁은 무리와 넓은 무리로 가른 결과."""

    #: 이 값 이하의 간격은 유닛 안. None 이면 전부 한 유닛.
    threshold: int | None
    #: 두 무리 사이가 벌어진 정도(넓은쪽 최소 / 좁은쪽 최대).
    ratio: float
    narrow: tuple[int, ...]
    wide: tuple[int, ...]

    @property
    def separated(self) -> bool:
        return self.threshold is not None


def split_gaps(gaps, min_ratio: float = 2.0) -> GapSplit:
    """간격 목록을 좁은 무리 / 넓은 무리로 가른다.

    min_ratio 는 "두 무리라고 부를 만큼 벌어졌는가"의 기준이다.
    벌어짐이 이보다 작으면 무리가 하나라고 보고 threshold=None 을 돌려준다.
    """
    gaps = [int(g) for g in gaps]
    if len(gaps) < 2:
        return GapSplit(None, 1.0, tuple(gaps), ())

    uniq = sorted(set(gaps))
    if len(uniq) == 1:
        return GapSplit(None, 1.0, tuple(gaps), ())

    best_ratio = 1.0
    best_thr = None
    for lo, hi in zip(uniq, uniq[1:]):
        # 완충값을 더해서 잰다. 그냥 hi/lo 로 재면 0px 과 1px 처럼 둘 다 사실상
        # 붙어 있는 값이 무한대 비를 내고, 아무 의미 없는 자리에서 갈라진다.
        ratio = (hi + SMOOTH) / (lo + SMOOTH)
        if ratio > best_ratio:
            best_ratio, best_thr = ratio, lo

    if best_thr is None or best_ratio < min_ratio:
        return GapSplit(None, best_ratio, tuple(gaps), ())

    narrow = tuple(g for g in gaps if g <= best_thr)
    wide = tuple(g for g in gaps if g > best_thr)
    return GapSplit(best_thr, best_ratio, narrow, wide)


def group_by_gaps(items, gaps, min_ratio: float = 2.0):
    """items 를 간격이 넓은 자리에서 끊어 묶음 목록으로.

    items 는 순서대로 놓인 조각들이고 gaps 는 그 사이 간격(len(items) - 1 개)이다.
    """
    items = list(items)
    if not items:
        return [], GapSplit(None, 1.0, (), ())
    if len(items) == 1:
        return [items], GapSplit(None, 1.0, (), ())

    if len(gaps) != len(items) - 1:
        raise ValueError(f"간격 개수가 맞지 않는다: items={len(items)} gaps={len(gaps)}")

    gs = split_gaps(gaps, min_ratio=min_ratio)
    if not gs.separated:
        return [items], gs

    groups = [[items[0]]]
    for item, gap in zip(items[1:], gaps):
        if gap > gs.threshold:
            groups.append([item])
        else:
            groups[-1].append(item)
    return groups, gs
