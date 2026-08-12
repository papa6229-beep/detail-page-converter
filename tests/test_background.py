"""배경색 구간 분리 — DESIGN.md 4.4 결함 1번."""

import numpy as np

from slicer import slice_image
from slicer.background import find_sections
from slicer.layout import CutConfig

from .fixtures import dark_section_page, two_column_grid


def test_어두운_구간을_따로_잡는다():
    sections = find_sections(dark_section_page())
    assert len(sections) == 2
    assert not sections[0].is_dark
    assert sections[1].is_dark
    assert sections[1].y0 == 320


def test_어두운_구간_안에서도_밴드가_갈린다():
    """결함 1번 그대로의 회귀 시험.

    배경을 흰색으로 못박으면 이 구간에서는 '배경인 행'이 하나도 안 나와
    전부 한 덩이로 뭉친다. 구간마다 배경색을 따로 잡으면 갈린다.
    """
    result = slice_image(dark_section_page())
    dark = [u for u in result.units if u.rect.y0 >= 320]
    parts = [p for u in dark for p in u.parts]
    assert len(parts) == 3, f"어두운 구간이 한 덩이로 뭉쳤다: {parts}"
    assert len(dark) == 2, [u.rect for u in dark]
    assert dark[0].has_caption, "어두운 구간에서 캡션이 귀속되지 않았다"


def test_어두운_패널은_배경이_아니다():
    """검은 사진이 있다고 그 구간의 배경이 검은 것은 아니다.

    여백이 아니라 행 전체의 최빈색으로 배경을 잡으면 사진에 속아
    검은 부분을 배경으로 오인하고 깎아낸다. 면적이 사라진다.
    """
    img = two_column_grid(rows=2, dark_rows=1)
    sections = find_sections(img)
    assert len(sections) == 1
    assert not sections[0].is_dark

    result = slice_image(img)
    black = (img.reshape(-1, 3) == 0).all(axis=1).sum()
    covered = np.zeros(img.shape[:2], dtype=bool)
    for p in result.panels:
        covered[p.y0 : p.y1 + 1, p.x0 : p.x1 + 1] = True
    kept = (covered.reshape(-1) & (img.reshape(-1, 3) == 0).all(axis=1)).sum()
    assert kept == black, f"검은 패널 면적이 깎였다: {kept}/{black}"


def test_잉크_보존():
    result = slice_image(two_column_grid(rows=3))
    assert result.ink_coverage > 0.99, result.ink_coverage


def test_배경_허용오차를_넓게_잡아도_결과가_흔들리지_않는다():
    img = two_column_grid(rows=3)
    counts = {
        tol: len(slice_image(img, tol=tol, cfg=CutConfig(tol=tol)).units) for tol in (8, 14, 20)
    }
    assert len(set(counts.values())) == 1, counts
