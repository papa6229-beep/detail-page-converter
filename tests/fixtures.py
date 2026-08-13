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


def ruled_column(rows: int = 4, gutter: int = 0) -> np.ndarray:
    """트리니티꼴 — 1열에 [이미지][문구] 가 반복되고 **그 사이마다 저자가 가로선**.

    간격만으로는 안 갈린다. 그림→문구 간격이 문구→다음 그림 간격보다 넓은 줄이
    섞여 있어서, 실제 원본에서 사진 다섯 장이 유닛 하나로 뭉쳤다.
    가르는 것은 저자가 그은 선이다.

    선은 **본문 단 폭에만** 그어진다(x 60..560). 페이지 폭을 요구하면 못 본다.
    """
    between = 50  # 유닛과 유닛 사이
    img = page(650, 460 + rows * (200 + 57 + 10 + between))
    # 페이지 어딘가에 본문 단보다 넓은 것이 하나라도 있으면, 구획선은 더 이상
    # '구간 전체 폭'을 채우지 않는다. 트리니티가 그렇다 — 맨 위 통짜 이미지가
    # x 30..636 이라, x 62..562 인 구획선이 하나도 안 보였다.
    box(img, 20, 40, 630, 240, GRAY)
    y = 460
    for r in range(rows):
        # 첫 칸만 그림 아래 여백이 넓다 — **유닛 사이 간격보다도 넓다.**
        # 이 한 줄이 간격의 이중구조를 무너뜨린다. 실제 트리니티가 57 대 50 이었다.
        pad = 57 if r == 0 else 21
        box(img, 60, y, 560, y + 200, GRAY)
        if gutter and r == 1:  # 그림 안쪽의 균일한 세로줄 — 구분선이 아니다
            box(img, 60 + gutter, y, 60 + gutter + 1, y + 200, (150, 150, 150))
        y += 200 + pad
        box(img, 60, y, 380, y + 10, GRAY)  # 문구 한 줄
        y += 10 + between // 2
        box(img, 60, y, 560, y, ORANGE)  # 저자가 그은 구획선
        y += between - between // 2
    return img


def collage_unit() -> np.ndarray:
    """유닛 하나 안에 사진이 두 장 놓인 콜라주 (텐가 왼쪽 칸).

    위 사진의 아랫변은 단색이고 그 아래는 여백이다. 한쪽만 보면 구획선처럼
    보이지만 위가 사진에 딱 붙어 있으니 그림의 가장자리다. 실제 텐가에서
    이 한 줄(y=1824) 때문에 콜라주가 위아래로 쪼개졌다.
    """
    img = page(650, 560)
    # 사진은 얼룩덜룩해야 한다. 통짜 단색으로 두면 사진 전체가 '단색 줄'로 묶여
    # 두께 상한에 걸리는 바람에, 아랫변만 단색인 진짜 사진의 상황이 재현되지 않는다.
    box(img, 60, 40, 560, 240, GRAY)
    box(img, 60, 252, 560, 400, GRAY)
    img[40:241:2, 60:561:2] = (90, 90, 90)
    img[252:401:2, 60:561:2] = (90, 90, 90)
    box(img, 60, 239, 560, 240, (219, 221, 223))  # 사진 아랫변 — 단색
    box(img, 60, 420, 380, 431, GRAY)             # 캡션
    return img


def photo_with_side_text() -> np.ndarray:
    """사진 왼쪽에 치수 글자가 딱 붙고, 오른쪽 멀찍이 설명 한 줄.

    딱 붙은 것은 그림의 일부이고, 멀찍이 떨어진 것은 캡션이다.
    """
    img = page(650, 700)
    box(img, 60, 20, 560, 140, GRAY)         # 위 유닛의 그림
    box(img, 60, 150, 380, 161, GRAY)        # 그 캡션
    box(img, 60, 180, 560, 180, ORANGE)      # 구획선

    box(img, 150, 200, 360, 420, GRAY)       # 사진
    box(img, 120, 380, 145, 395, GRAY)       # 딱 붙은 치수 글자 (그림의 일부)
    box(img, 450, 300, 610, 311, GRAY)       # 멀찍이 떨어진 설명 한 줄 (캡션)
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
