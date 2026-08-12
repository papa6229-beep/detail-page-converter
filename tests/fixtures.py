"""합성 원본. 실제 파일 없이도 두 결함을 재현할 수 있어야 한다."""

from __future__ import annotations

import numpy as np

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
ORANGE = (240, 150, 60)
GRAY = (120, 120, 120)


def page(w: int, h: int, bg=WHITE) -> np.ndarray:
    return np.full((h, w, 3), bg, dtype=np.uint8)


def box(img: np.ndarray, x0: int, y0: int, x1: int, y1: int, color) -> None:
    img[y0 : y1 + 1, x0 : x1 + 1] = color


def cell(img, x0, y0, x1, *, image_h=170, lines=2, ink=GRAY, line_w=None):
    """이미지 한 덩이 + 캡션 글줄 몇 개. 아래끝 y 를 돌려준다."""
    box(img, x0, y0, x1, y0 + image_h, ink)
    y = y0 + image_h + 6
    for i in range(lines):
        box(img, x0, y, x1 if line_w is None else x0 + line_w, y + 10, ink)
        y += 15
    return y - 15 + 10


def two_column_grid(rows: int = 3, dark_rows: int = 0) -> np.ndarray:
    """텐가와 같은 골격.

    위쪽은 1열 광고 구간, 아래쪽은 주황 표 선으로 칸을 나눈 2열 그리드.
    **열 구분선은 페이지 위끝이 아니라 중간부터 시작한다** — 결함 2번의 핵심 조건이다.
    """
    w, h = 600, 340 + rows * 250
    img = page(w, h)

    # 상단 1열 광고 구간
    box(img, 20, 20, 580, 300, GRAY)

    top = 330
    box(img, 10, top, 590, top, ORANGE)  # 2열 구간이 시작되는 가로 괘선
    for r in range(rows):
        y0 = top + r * 250
        y1 = y0 + 250
        box(img, 10, y1, 590, y1, ORANGE)
        box(img, 300, y0, 300, y1, ORANGE)  # 열 구분선 — 여기서부터만 있다

        dark = r >= rows - dark_rows
        ink = WHITE if dark else GRAY
        if dark:  # 패널만 어둡다. 페이지 바탕은 끝까지 흰색이다.
            box(img, 20, y0 + 10, 290, y0 + 180, BLACK)
            box(img, 310, y0 + 10, 580, y0 + 180, BLACK)
            box(img, 60, y0 + 40, 250, y0 + 150, ink)
            box(img, 350, y0 + 40, 540, y0 + 150, ink)
            y = y0 + 186
            for _ in range(2):
                box(img, 20, y, 260, y + 10, GRAY)
                box(img, 310, y, 500, y + 10, GRAY)
                y += 15
        else:
            cell(img, 20, y0 + 10, 290, lines=2, line_w=240)
            cell(img, 310, y0 + 10, 580, lines=3, line_w=200)
    return img


def dark_section_page() -> np.ndarray:
    """페이지 바탕 자체가 어두운 구간이 있는 원본.

    여백까지 어둡다는 점이 위의 '어두운 패널'과 다르다. 이쪽은 배경색이 진짜로 바뀐다.
    """
    img = page(600, 900)
    box(img, 40, 40, 560, 260, GRAY)
    box(img, 40, 280, 400, 300, GRAY)

    box(img, 0, 320, 599, 899, BLACK)  # 여기부터 바탕이 검다
    box(img, 40, 360, 560, 580, (230, 230, 230))
    box(img, 40, 600, 400, 620, (230, 230, 230))
    box(img, 40, 700, 560, 860, (230, 230, 230))
    return img
