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


def test_저자가_그은_가로선에서_유닛이_갈린다():
    """트리니티 — 간격만으로는 안 갈리는 원본.

    그림→문구 간격이 문구→다음 그림 간격보다 넓은 줄이 하나만 섞여도 간격의
    이중구조가 무너진다. 실제 원본에서 사진 다섯 장과 그 문구가 유닛 하나로 뭉쳤다.
    가르는 것은 저자가 그은 선이다.
    """
    from .fixtures import ruled_column

    result = slice_image(ruled_column(rows=4))
    ruled = [u for u in result.units if u.rect.y0 >= 460]  # 맨 위 통짜 이미지는 뺀다
    assert len(ruled) == 4, [u.rect for u in result.units]
    assert all(u.has_caption for u in ruled)
    assert all(len(u.parts) == 2 for u in ruled), "그림과 문구가 한 덩어리로 뭉쳤다"


def test_구획선은_본문_단_폭에만_그어져도_보인다():
    """페이지 전체 폭을 요구하면 트리니티의 선을 하나도 못 본다."""
    from .fixtures import ruled_column

    img = ruled_column(rows=3)
    assert img.shape[1] == 650  # 선은 x 60..560 에만 있다
    assert len([u for u in slice_image(img).units if u.rect.y0 >= 460]) == 3


def test_사진의_아랫변은_구획선이_아니다():
    """구획선은 여백 **속에** 놓인다. 한쪽만 보면 사진 아랫변도 통과한다.

    실제로 텐가 왼쪽 칸의 콜라주가 그 한 줄 때문에 위아래로 쪼개졌다.
    """
    from .fixtures import collage_unit

    result = slice_image(collage_unit())
    assert len(result.units) == 1, [u.rect for u in result.units]
    assert result.units[0].has_caption


def test_그림_안쪽의_균일한_줄은_구분선이_아니다():
    """살색 사진 안에서 우연히 균일한 2px 세로줄이 잡혀 폭 52px 조각이 떨어져 나갔다.

    저자가 그은 선이라면 옆에 여백이 있다. 그림 속의 줄은 콘텐츠에 딱 붙어 있다.
    """
    from .fixtures import ruled_column

    plain = slice_image(ruled_column(rows=3))
    lined = slice_image(ruled_column(rows=3, gutter=300))
    assert [u.rect.as_tuple() for u in lined.units] == [u.rect.as_tuple() for u in plain.units]


def test_RGB가_아니면_거부한다():
    import numpy as np

    try:
        slice_image(np.zeros((10, 10), dtype=np.uint8))
    except ValueError:
        return
    raise AssertionError("RGB 아닌 입력을 통과시켰다")
