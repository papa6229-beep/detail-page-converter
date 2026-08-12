"""전체 파이프라인 — 캡션이 제 이미지에 붙는가."""

from slicer import slice_image

from .fixtures import two_column_grid


def _grid_units(result):
    return [u for u in result.units if u.rect.y0 > 320]


def test_칸마다_유닛_하나():
    result = slice_image(two_column_grid(rows=3))
    grid = _grid_units(result)
    assert len(grid) == 6, [u.rect for u in grid]
    assert all(u.has_caption for u in grid)


def test_캡션이_옆칸으로_밀리지_않는다():
    """결함 2번이 만들어낸 증상 그대로의 회귀 시험.

    가로 스캔만 하면 좌우 칸이 한 밴드로 섞여 캡션이 한 칸씩 밀린다.
    조각은 다 살아 있으므로 면적 검사(불변식 ①)로는 잡히지 않는다.
    """
    result = slice_image(two_column_grid(rows=3))
    for u in _grid_units(result):
        for cap in u.captions:
            assert cap.x0 >= u.image.x0 - 2 and cap.x1 <= u.image.x1 + 2, (
                f"캡션이 제 칸을 벗어났다: 이미지 {u.image} 캡션 {cap}"
            )
            assert (cap.x0 < 300) == (u.image.x0 < 300), "캡션이 옆 열로 넘어갔다"


def test_유닛_안_간격이_유닛_사이보다_좁다():
    """불변식 ⑥. 묶음이 틀리면 여기서 걸린다."""
    result = slice_image(two_column_grid(rows=3))
    grid = sorted(_grid_units(result), key=lambda u: (u.column, u.rect.y0))
    inner = [b.y0 - a.y1 - 1 for u in grid for a, b in zip(u.parts, u.parts[1:])]
    between = [
        b.rect.y0 - a.rect.y1 - 1
        for a, b in zip(grid, grid[1:])
        if a.column == b.column and b.rect.y0 > a.rect.y1
    ]
    assert inner and between
    assert max(inner) < min(between), f"유닛 안 {max(inner)} ≥ 유닛 사이 {min(between)}"


def test_읽는_순서로_나온다():
    """옵션 태그는 순서로 대응된다. 열별로 훑은 순서를 그대로 내보내면 안 된다."""
    result = slice_image(two_column_grid(rows=3))
    grid = _grid_units(result)
    assert [u.column for u in grid] == [0, 1, 0, 1, 0, 1]


def test_어두운_칸도_같은_짝을_이룬다():
    result = slice_image(two_column_grid(rows=3, dark_rows=2))
    grid = _grid_units(result)
    assert len(grid) == 6
    assert all(u.has_caption for u in grid)


def test_한_열짜리_원본은_그대로_풀린다():
    """버진루프류 — 통이미지 1장에 [이미지][캡션] 이 세로로 반복."""
    from .fixtures import GRAY, box, page

    img = page(560, 1000)
    y = 30
    for _ in range(4):
        box(img, 30, y, 530, y + 150, GRAY)
        box(img, 30, y + 156, 430, y + 166, GRAY)
        y += 230
    result = slice_image(img)
    assert len(result.units) == 4, [u.rect for u in result.units]
    assert all(u.has_caption for u in result.units)


def test_RGB가_아니면_거부한다():
    import numpy as np

    try:
        slice_image(np.zeros((10, 10), dtype=np.uint8))
    except ValueError:
        return
    raise AssertionError("RGB 아닌 입력을 통과시켰다")
