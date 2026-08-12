"""세로 절단 — DESIGN.md 4.4 결함 2번."""


from slicer import slice_image
from slicer.geometry import Rect
from slicer.layout import CutConfig, build_columns, gutter_extents, trim

from .fixtures import WHITE, box, page, two_column_grid


def _extents(img):
    cfg = CutConfig()
    rect = trim(img, Rect(0, 0, img.shape[1] - 1, img.shape[0] - 1), WHITE, cfg)
    return rect, gutter_extents(img, rect, WHITE, cfg)


def test_고랑의_세로_구간을_잰다():
    """열 구분선이 페이지 중간부터 시작해도 찾아야 한다.

    페이지 전체 높이를 훑는 고랑만 찾으면 여기서 하나도 안 나오고,
    2열 구간이 발견되지 않는다. 그것이 결함 2번이다.
    """
    img = two_column_grid(rows=3)
    rect, extents = _extents(img)
    assert len(extents) == 1
    y0, y1 = extents[0]
    # 고랑은 상단 광고 블록이 끝나는 자리(y=300)부터 페이지 끝까지 이어진다.
    assert 300 <= rect.y0 + y0 <= 335, rect.y0 + y0
    assert rect.y0 + y1 >= img.shape[0] - 60, rect.y0 + y1


def test_가로_괘선이_고랑을_끊지_않는다():
    """표 가로선이 고랑을 가로지른다. 배경만 보면 고랑이 칸마다 토막난다."""
    rect, extents = _extents(two_column_grid(rows=3))
    y0, y1 = extents[0]
    assert y1 - y0 > 600, f"고랑이 토막났다: {y1 - y0}px"


def test_열이_없으면_열을_만들지_않는다():
    img = page(600, 500)
    box(img, 40, 40, 560, 300, (120, 120, 120))
    box(img, 40, 320, 560, 340, (120, 120, 120))
    _, extents = _extents(img)
    assert extents == []


def test_글줄은_열로_쪼개지_않는다():
    """글자 사이 여백은 열 여백과 너비로 구별되지 않는다. 모양으로 구별한다."""
    img = page(600, 120)
    for x in range(40, 560, 24):  # 글자처럼 늘어선 덩어리
        box(img, x, 50, x + 14, 70, (60, 60, 60))
    cells = build_columns(img, Rect(0, 0, 599, 119), WHITE, CutConfig())
    assert len(cells) == 1, f"글줄이 {len(cells)}조각으로 부서졌다"


def test_칸_경계가_좌우로_갈린다():
    cells = build_columns(
        two_column_grid(rows=3), Rect(0, 0, 599, 1089), WHITE, CutConfig()
    )
    grid = [c for c in cells if c.rect.y0 > 320]
    assert grid, "2열 구간의 칸을 못 찾았다"
    assert {c.col_total for c in grid} == {2}
    assert {c.col_index for c in grid} == {0, 1}
    for c in grid:
        assert c.rect.x1 < 300 or c.rect.x0 > 300, f"칸이 열 구분선을 넘었다: {c.rect}"


def test_괘선_두께_상한이_단색_콘텐츠를_지킨다():
    """가로로 꽉 찬 단색 띠(텐가의 빨간 배너)는 구분자가 아니라 콘텐츠다."""
    img = page(600, 400)
    box(img, 20, 40, 580, 150, (200, 30, 30))
    box(img, 20, 200, 580, 360, (120, 120, 120))
    result = slice_image(img)
    banner = [u for u in result.units if u.rect.y0 < 160]
    assert banner and banner[0].rect.h > 100, "단색 배너가 구분자로 먹혔다"
