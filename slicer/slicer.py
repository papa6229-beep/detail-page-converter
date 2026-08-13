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
from .layout import COL, ROW, CutConfig, Node, Scan, build_columns, line_flags, rule_gaps, trim


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
    """괘선이 낀 간격에서 밴드를 끊어 (밴드들, 간격들, 앞이_괘선인가) 로 내놓는다."""
    cur_b, cur_g, started = [bands[0]], [], False
    for band, gap, is_rule in zip(bands[1:], gaps, hard):
        if is_rule:
            yield cur_b, cur_g, started
            cur_b, cur_g, started = [band], [], True
        else:
            cur_b.append(band)
            cur_g.append(gap)
    yield cur_b, cur_g, started


def image_floor(bands: list[Rect]) -> int:
    """이 칸에서 '이미지'라고 부를 최소 높이.

    임계값을 사람이 정하지 않는다. 밴드 높이도 간격과 똑같이 두 무리로 갈린다 —
    캡션 글줄은 11px 언저리에 몰려 있고 이미지는 136px 위다. 그 사이가 비어 있다.
    """
    gs = split_gaps([b.h for b in bands])
    return gs.threshold if gs.separated else 0


#: 캡션이 그림 아래에 붙는 페이지 / 위에 붙는 페이지
BELOW, ABOVE = -1, 1


def caption_direction(plans) -> int:
    """캡션이 그림의 어느 쪽에 붙는 페이지인지 **한 번만** 정한다 (4.3).

    묶음마다 따로 정하면 조각 하나에 끌려 뒤집힌다. 버진루프가 그랬다 —
    액자 위변이 사진에 7px 밖에 안 붙어 구획선으로 안 잡히는 바람에, 캡션 두 줄이
    아래 사진 쪽으로 넘어가 그림에 문구와 선이 그대로 딸려 나왔다.

    페이지 전체로 세면 그런 한 자리는 묻힌다. 이미지 없는 묶음마다 위 그림이
    가까운지 아래 그림이 가까운지 세고, 많은 쪽을 그 페이지의 방향으로 삼는다.

    돌려주는 값이 BELOW 면 캡션은 그림 아래에 붙는다 — 즉 **위쪽 묶음**에 되돌린다.

    증거는 세 가지를 이 순서로 본다. 앞의 것이 갈리면 뒤는 안 본다.

      한 묶음 안   이미 그림과 글줄이 같이 묶인 자리. 글줄이 그림 위인지 아래인지가
                   그대로 답이다. 제일 흔하고 제일 확실하다
      한쪽 끝      칸의 맨 끝에 놓인 글줄은 갈 곳이 한 군데뿐이다
      가운데       양쪽에 그림이 있으면 가까운 쪽. 액자 하나에 뒤집히는 바로 그
                   자리이므로 맨 나중에 본다
    """
    inside = [0, 0]  # [위쪽에 붙는다 → BELOW 표, 아래쪽에 붙는다 → ABOVE 표]
    edge = [0, 0]
    mid = [0, 0]
    for _cell, groups, floor in plans:
        for i, g in enumerate(groups):
            tall = [r for r in g if r.h > floor]
            if tall:
                lo, hi = tall[0].y0, tall[-1].y1
                inside[0] += sum(1 for r in g if r.y1 < lo)
                inside[1] += sum(1 for r in g if r.y0 > hi)
                continue
            has_prev, has_next = i > 0, i + 1 < len(groups)
            if has_prev and has_next:
                before = g[0].y0 - groups[i - 1][-1].y1
                after = groups[i + 1][0].y0 - g[-1].y1
                mid[0] += before < after
                mid[1] += after < before
            elif has_prev:
                edge[0] += 1
            elif has_next:
                edge[1] += 1

    # inside 는 '글줄이 그림 위에 있었다'가 [0], '아래'가 [1] 이다. 아래에 있었다면
    # 그 페이지 캡션은 그림 아래이고, 그건 위쪽 묶음에 되돌린다는 뜻(BELOW)이다.
    for up, down in ((inside[1], inside[0]), (edge[0], edge[1]), (mid[0], mid[1])):
        if up != down:
            return BELOW if up > down else ABOVE
    return BELOW


def _merge_imageless(groups: list[list[Rect]], floor: int, prefer: int = BELOW) -> list[list[Rect]]:
    """이미지가 없는 묶음은 유닛이 아니다. 이웃에 되돌린다.

    불변식 ⑤(캡션 수 ≤ 이미지 수)를 묶는 단계에서 바로 지키는 것이다.

    **경계란 유닛과 유닛을 가르는 것이다.** 한쪽에 이미지가 없으면 그건 경계가 아니다.
    이 한 문장이 표 선과 액자를 갈라 준다 — 표 선은 이미지 있는 칸 둘 사이에 있고,
    액자 아랫변은 이미지와 그 캡션 사이에 끼어 있다. 선을 보고 판정하지 않아도 된다.

    되돌릴 쪽은 **페이지가 정한 캡션 방향**을 따른다. 가까운 쪽을 고르면 액자 하나가
    한 픽셀 차이로 안 잡힐 때 그 자리만 뒤집힌다. 그쪽에 이웃이 없을 때만 반대쪽을 본다.
    """
    while len(groups) > 1:
        for i, g in enumerate(groups):
            if any(r.h > floor for r in g):
                continue
            wanted = i - 1 if prefer == BELOW else i + 1
            other = i + 1 if prefer == BELOW else i - 1
            j = wanted if 0 <= wanted < len(groups) else other
            if not 0 <= j < len(groups):
                break
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

    #: (칸, 묶음들, 이미지 바닥) — 캡션 방향을 페이지 전체로 정한 뒤에 되돌린다
    plans: list[tuple[Node, list[list[Rect]], int]] = []
    sec_of: dict[int, int] = {}

    for si, sec in enumerate(sections):
        rect = Rect(0, sec.y0, arr.shape[1] - 1, sec.y1)

        scan = Scan(arr, sec.bg, cfg)
        content = trim(arr, rect, sec.bg, cfg, scan)
        if content is None:
            continue

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

            # 구획선이 낀 자리에서 먼저 끊고, 그 안에서 간격 이중구조를 본다.
            # 다만 구획선을 **최종 경계로 확정하지는 않는다** — 액자 아랫변처럼
            # 이미지와 그 캡션 사이에 낀 선도 있기 때문이다. 마지막에 한 번 더 본다.
            floor = image_floor(bands)
            groups: list[list[Rect]] = []
            for cell_bands, cell_gaps, _at_rule in _split_at_rules(
                bands, gaps, rule_gaps(arr, bands, sec.bg, cfg, scan)
            ):
                subs, gs = group_by_gaps(cell_bands, cell_gaps, min_ratio=min_gap_ratio)
                gap_stats.append(gs)
                groups.extend(subs)

            sec_of[len(plans)] = si
            plans.append((cell, groups, floor))

    # 캡션 방향은 페이지마다 하나다 (4.3). 다 모은 다음에 한 번 정하고 되돌린다.
    prefer = caption_direction(plans)
    for k, (cell, groups, floor) in enumerate(plans):
        for group in _merge_imageless(groups, floor, prefer):
            image, captions = _classify(group)
            units.append(
                Unit(
                    rect=union_all(group),
                    parts=list(group),
                    image=image,
                    captions=captions,
                    section=sec_of[k],
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
