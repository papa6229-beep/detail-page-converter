"""통이미지 분할기 — DESIGN.md 4.4 "고칠 순서" 세 단계를 순서대로 밟는다.

    1. 배경색 구간을 먼저 나눈다 (밝음/어두움) → 구간마다 배경색을 따로 잡는다
    2. 각 구간에서 2열인지 보고 세로로 가른다
    3. 열별로 간격 이중구조를 적용해 캡션을 귀속시킨다

1·2번이 통째로 빠져 있어 텐가에서 캡션이 한 칸 밀렸다. 이제 셋 다 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .background import DEFAULT_TOL, Section, bg_mask, find_sections
from .gaps import GapSplit, group_by_gaps, split_gaps
from .geometry import Rect, union_all
from .layout import COL, ROW, CutConfig, Node, Scan, build_columns, line_flags, rule_gaps, rule_rows, trim


@dataclass
class Unit:
    """정규형의 유닛 하나. 이미지 + (있으면) 캡션."""

    rect: Rect
    parts: list[Rect]
    image: Rect
    captions: list[Rect] = field(default_factory=list)
    section: int = 0
    #: 문서 안에서의 열 번호(0부터). 2열 구간에서 좌/우를 구별한다.
    column: int = 0

    @property
    def has_caption(self) -> bool:
        return bool(self.captions)


@dataclass
class SliceResult:
    sections: list[Section]
    units: list[Unit]
    panels: list[Rect]
    #: 잉크(배경이 아닌) 픽셀 중 조각 안에 들어간 비율. 불변식 ①.
    ink_coverage: float
    gap_stats: list[GapSplit] = field(default_factory=list)
    column_counts: list[int] = field(default_factory=list)

    @property
    def n_units(self) -> int:
        return len(self.units)


def _bands(node: Node) -> tuple[list[Rect], list[int]]:
    """칸을 세로 순서의 밴드 목록으로 편다."""
    rects = [c.rect for c in node.children] if node.children else [node.rect]
    gaps = [rects[i + 1].y0 - rects[i].y1 - 1 for i in range(len(rects) - 1)]
    return rects, gaps


def _split_at_rules(bands: list[Rect], gaps: list[int], hard: list[bool]):
    """괘선이 낀 간격에서 밴드 목록을 끊어 (밴드들, 간격들) 묶음으로 내놓는다."""
    cur_b, cur_g = [bands[0]], []
    for band, gap, is_rule in zip(bands[1:], gaps, hard):
        if is_rule:
            yield cur_b, cur_g
            cur_b, cur_g = [band], []
        else:
            cur_b.append(band)
            cur_g.append(gap)
    yield cur_b, cur_g


def image_floor(bands: list[Rect]) -> int:
    """이 칸에서 '이미지'라고 부를 최소 높이.

    임계값을 사람이 정하지 않는다. 밴드 높이도 간격과 똑같이 두 무리로 갈린다 —
    캡션 글줄은 11px 언저리에 몰려 있고 이미지는 136px 위다. 그 사이가 비어 있다.
    """
    gs = split_gaps([b.h for b in bands])
    return gs.threshold if gs.separated else 0


def _merge_imageless(groups: list[list[Rect]], floor: int) -> list[list[Rect]]:
    """이미지가 없는 묶음은 유닛이 아니다. 이웃에 되돌린다.

    불변식 ⑤(캡션 수 ≤ 이미지 수)를 묶는 단계에서 바로 지키는 것이다.
    텐가 오른쪽 4번째 칸은 사진이 위에서 끝나 이미지↔캡션 간격이 31px 로 벌어지는데,
    간격만 보면 캡션 두 줄이 제 이미지에서 떨어져 나가 홀로 유닛이 된다.
    "이미지가 없는 유닛은 없다"는 것만 알면 저절로 제자리로 돌아간다.
    """
    while len(groups) > 1:
        for i, g in enumerate(groups):
            if any(r.h > floor for r in g):
                continue
            if i == 0:
                j = 1
            elif i == len(groups) - 1:
                j = i - 1
            else:
                prev_gap = g[0].y0 - groups[i - 1][-1].y1
                next_gap = groups[i + 1][0].y0 - g[-1].y1
                j = i - 1 if prev_gap <= next_gap else i + 1
            groups[j] = sorted(groups[j] + g, key=lambda r: (r.y0, r.x0))
            groups.pop(i)
            break
        else:
            break
    return groups


def reading_order(units: list["Unit"]) -> list["Unit"]:
    """유닛을 읽는 순서(위→아래, 왼→오른쪽)로 늘어놓는다.

    정규형의 units[] 는 **순서가 있는 배열**이다. 3.1 의 광고 구간 판정도,
    7장의 옵션 태그 대응도 순서에 기댄다. 2열 구간을 열별로 훑고 나면
    왼쪽 6개 다음에 오른쪽 6개가 오므로, 여기서 문서 순서로 되돌려야 한다.
    """
    rows: list[list[Unit]] = []
    for u in sorted(units, key=lambda v: (v.rect.y0, v.rect.x0)):
        for row in rows:
            if u.rect.y0 <= min(v.rect.y1 for v in row):
                row.append(u)
                break
        else:
            rows.append([u])
    return [u for row in rows for u in sorted(row, key=lambda v: v.rect.x0)]


def _classify(parts: list[Rect]) -> tuple[Rect, list[Rect]]:
    """가장 넓은 조각이 이미지, 나머지가 캡션.

    캡션이 무엇인지 판정하지 않는다. 면적 순서를 볼 뿐이다.
    """
    image = max(parts, key=lambda r: r.area)
    captions = [r for r in parts if r is not image]
    return image, captions


def slice_image(
    arr: np.ndarray,
    tol: int = DEFAULT_TOL,
    cfg: CutConfig | None = None,
    min_gap_ratio: float = 2.0,
) -> SliceResult:
    """통이미지 한 장을 유닛 배열로 환원한다."""
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError("RGB 배열이어야 한다")
    cfg = cfg or CutConfig(tol=tol)

    # 1. 배경색 구간
    sections = find_sections(arr, tol=tol)

    units: list[Unit] = []
    panels: list[Rect] = []
    gap_stats: list[GapSplit] = []
    column_counts: list[int] = []

    for si, sec in enumerate(sections):
        rect = Rect(0, sec.y0, arr.shape[1] - 1, sec.y1)

        # 칸의 기하를 잡는 데만 쓰는, 구간 전체 폭의 괘선 마스크.
        # 반드시 **여백을 벗긴** 사각형에서 재야 한다. 테두리 바깥 흰 여백까지 넣고
        # 재면 표 가로선이 "흰색 + 주황 + 흰색"이 되어 단색으로 보이지 않고,
        # 괘선이 하나도 검출되지 않는다.
        scan = Scan(arr, sec.bg, cfg)
        content = trim(arr, rect, sec.bg, cfg, scan)
        if content is None:
            continue
        rules = rule_rows(arr, content, sec.bg, cfg, scan)

        # 2. 세로로 가른다 — 칸 단위로 내려간다
        cells = build_columns(arr, rect, sec.bg, cfg, scan=scan)
        for cell in cells:
            panels.extend(leaf.rect for leaf in cell.leaves())
            column_counts.append(cell.col_total)

            # 3. 칸 안에서 간격 이중구조로 캡션을 귀속시킨다
            bands, gaps = _bands(cell)
            bands = [b for b in bands if b is not None]
            if not bands:
                continue
            if len(gaps) != len(bands) - 1:
                gaps = []
                for a, b in zip(bands, bands[1:]):
                    gaps.append(b.y0 - a.y1 - 1)

            # 표 선이 낀 자리는 칸 경계다. 그 안에서만 간격 이중구조를 본다.
            floor = image_floor(bands)
            for cell_bands, cell_gaps in _split_at_rules(
                bands, gaps, rule_gaps(rules, content.y0, bands)
            ):
                groups, gs = group_by_gaps(cell_bands, cell_gaps, min_ratio=min_gap_ratio)
                gap_stats.append(gs)

                for group in _merge_imageless(groups, floor):
                    image, captions = _classify(group)
                    units.append(
                        Unit(
                            rect=union_all(group),
                            parts=list(group),
                            image=image,
                            captions=captions,
                            section=si,
                            column=cell.col_index,
                        )
                    )

    return SliceResult(
        sections=sections,
        units=reading_order(units),
        panels=panels,
        ink_coverage=ink_coverage(arr, sections, panels, tol, cfg),
        gap_stats=gap_stats,
        column_counts=column_counts,
    )


def _widen(mask: np.ndarray) -> np.ndarray:
    """마스크를 양쪽으로 1px 넓힌다."""
    out = mask.copy()
    out[:-1] |= mask[1:]
    out[1:] |= mask[:-1]
    return out


def ink_coverage(
    arr: np.ndarray,
    sections: list[Section],
    panels: list[Rect],
    tol: int,
    cfg: CutConfig | None = None,
) -> float:
    """불변식 ① — 콘텐츠 픽셀이 전부 어느 조각엔가 들어갔는가.

    조각이 다 살아 있는지 보는 검사다. 1.0 이면 잃어버린 콘텐츠가 없다.

    표 괘선과 테두리는 세지 않는다. 그건 콘텐츠가 아니라 원본 페이지의 집기이고,
    분할기는 그걸 일부러 구분자로 소비한다. 빼지 않으면 표 형식 원본은
    영원히 2% 쯤 모자란 것으로 나와 진짜 잘림과 구별되지 않는다.
    """
    cfg = cfg or CutConfig(tol=tol)
    ink = np.zeros(arr.shape[:2], dtype=bool)
    for sec in sections:
        rect = Rect(0, sec.y0, arr.shape[1] - 1, sec.y1)
        ink[sec.y0 : sec.y1 + 1] = ~bg_mask(rect.crop(arr), sec.bg, tol)

        content = trim(arr, rect, sec.bg, cfg)
        if content is None:
            continue
        # 축마다 재는 범위가 다르다. 가로 괘선은 바깥 여백을 뺀 폭에서 재야 단색으로
        # 보이고, 세로 테두리는 그 여백 **바깥**에 있어 폭을 전부 봐야 잡힌다.
        # 둘 다 content 로 재면 x=13·635 의 테두리가 콘텐츠로 남아 영원히 미달이 난다.
        col_scope = Rect(0, content.y0, arr.shape[1] - 1, content.y1)
        _, row_rule = line_flags(content.crop(arr), sec.bg, ROW, cfg)
        _, col_rule = line_flags(col_scope.crop(arr), sec.bg, COL, cfg)

        # 괘선 양옆의 안티에일리어싱 한 픽셀도 괘선의 일부다.
        ink[content.y0 : content.y1 + 1, content.x0 : content.x1 + 1] &= ~_widen(row_rule)[:, None]
        ink[col_scope.y0 : col_scope.y1 + 1] &= ~_widen(col_rule)[None, :]

    total = int(ink.sum())
    if total == 0:
        return 1.0

    covered = np.zeros_like(ink)
    for r in panels:
        covered[r.y0 : r.y1 + 1, r.x0 : r.x1 + 1] = True
    return float((ink & covered).sum() / total)
