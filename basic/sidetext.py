"""사진 옆·아래 구석에 붙은 글자를 사진에서 떼어낸다.

전제: 글자가 **균일한 배경(대개 흰색) 위**에 있다. 사진 픽셀 위에 직접 얹힌 글자는
못 뗀다 — 그런 밴드는 그대로 이미지로 둔다.

두 가지 관측을 합친다. 하나만 쓰면 놓치는 경우가 각각 있었다.
  ① 덩어리 — 배경이 아닌 픽셀을 뭉쳐서, 밀도가 낮고 색이 단조로우면 글자
  ② 글줄   — 어두운 픽셀인데 주변 40px 이 대부분 배경이면 글자 (콜아웃 선이 글자에
             닿아 ①에서 사진과 한 덩어리로 묶인 경우를 잡는다)
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


#: 배경이 이보다 어두우면 흰 바탕이 아니다 — 색 깔린 디자인 배너다.
BG_MIN_LIGHT = 225
#: 배경 색이 이보다 짙으면 흰 바탕이 아니다.
BG_MAX_SAT = 25

#: 글자 상자가 밴드 폭에서 차지해야 할 최소 몫. 글은 가로로 뻗는다.
MIN_TEXT_WIDTH = 0.20
#: 글자 상자가 밴드 넓이에서 차지할 수 있는 최대 몫. 넘으면 사진을 삼킨 것이다.
MAX_TEXT_AREA = 0.30


@dataclass
class Split:
    text_box: tuple[int, int, int, int]   #: (x0, y0, x1, y1) 글자 영역
    photo: np.ndarray                     #: 글자를 배경색으로 덮은 사진 (원본 크기)
    text: np.ndarray                      #: 글자 조각


def _bg(im: np.ndarray):
    return np.median(np.concatenate([im[0], im[-1], im[:, 0], im[:, -1]]), axis=0)


def _by_component(im: np.ndarray) -> tuple[list[tuple[int, int, int, int]], bool]:
    """(글자 상자들, 사진 덩어리가 있었는가)"""
    bg = _bg(im)
    h, w = im.shape[:2]
    m = (np.abs(im.astype(int) - bg).sum(axis=2) > 45).astype(np.uint8) * 255
    big = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, _lab, st, _ = cv2.connectedComponentsWithStats(big)
    out, has_photo = [], False
    for i in range(1, n):
        x, y, ww, hh, a = st[i]
        if a < 2000:
            continue
        fill = (m[y:y + hh, x:x + ww] > 0).mean()
        cs = im[y:y + hh, x:x + ww].reshape(-1, 3).std(axis=0).mean()
        is_photo = fill > 0.5 and (cs > 35 or a > 0.3 * h * w)
        if is_photo:
            has_photo = True
        else:
            out.append((int(x), int(y), int(x + ww), int(y + hh)))
    return out, has_photo


def _strokes(im: np.ndarray, fatten: bool = False) -> np.ndarray:
    """**글자처럼 생긴 픽셀**만 참인 판.

    어둡고, 둘레 40px 이 거의 배경인 픽셀이 글자다. 제품 덩어리는 둘레가 배경이
    아니라서 안 걸리고, 분홍 지시선처럼 밝고 채도 있는 선도 안 걸린다 — 그래서
    글자만 덮어도 **사진이 안 뚫리고 지시선이 남는다.**

    `_by_lines` 가 쓰던 그 계산 그대로다. 이름만 붙여 꺼냈다.
    """
    bg = _bg(im)
    bgm = (np.abs(im.astype(int) - bg).sum(axis=2) < 40).astype(np.float32)
    local = cv2.blur(bgm, (41, 41))
    gray = cv2.cvtColor(im, cv2.COLOR_RGB2GRAY)
    sat = cv2.cvtColor(im, cv2.COLOR_RGB2HSV)[:, :, 1]
    dark = (gray < 140) | ((np.abs(im.astype(int) - bg).sum(axis=2) > 120) & (sat < 90))
    ink = dark & (local > 0.55)
    if not fatten:
        return ink
    return cv2.dilate(ink.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0


def _line_boxes(im: np.ndarray) -> list[tuple[int, int, int, int]]:
    """**글줄 하나하나**의 테두리. 가로로 이은 뒤 글줄답게 생긴 것만 남긴다.

    거르개(넓이 250 넘고, 높이 6~70 이고, 폭 25 넘고)는 `_by_lines` 가 쓰던 그대로다.
    제품 언저리에서 딸려 나온 얇고 긴 조각은 높이에서 걸린다.
    """
    tp = _strokes(im).astype(np.uint8) * 255
    tp = cv2.morphologyEx(tp, cv2.MORPH_CLOSE, np.ones((10, 45), np.uint8))
    n, _lab, st, _ = cv2.connectedComponentsWithStats(tp)
    return [(int(s[0]), int(s[1]), int(s[0] + s[2]), int(s[1] + s[3]))
            for s in (st[i] for i in range(1, n))
            if s[4] > 250 and 6 < s[3] < 70 and s[2] > 25]


def _union(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _by_lines(im: np.ndarray) -> list[tuple[int, int, int, int]]:
    got = _line_boxes(im)
    return [_union(got)] if got else []


def cover(im: np.ndarray, boxes: list[tuple[int, int, int, int]]):
    """모델이 짚어 준 자리의 **글자를 덮은 사진과, 실제로 덮은 자리들.**
    흰 바탕이 아니면 None.

    `split` 과 하는 일은 같다. 다른 것은 **자리를 누가 정하는가**뿐이다.
    `split` 은 픽셀을 재서 글이 어디 있는지 스스로 찾았고, 그래서 글랜스의 금속캡과
    다일레이터의 격자를 글자로 잘못 짚어 사진에 구멍을 냈다. 여기서는 모델이 준
    자리 **안에서만** 본다. 코드가 정하는 것은 "이 안에서 어느 픽셀이 글자꼴인가"
    뿐이고, 그것도 원래 있던 계산(`_strokes`)이다.

    돌려주는 자리는 모델이 준 네모가 아니라 **정말로 지워진 잉크의 테두리**다.
    모델의 네모는 성기다 — "왼쪽 위 4분의 1" 처럼 크게 잡아 준다. 그 네모에 글을
    얹으면 글자가 네모만큼 커진다. 지워진 자리에 얹어야 원래 크기가 나온다.

    흰 바탕 검사는 남겨 둔다. 색이 깔린 광고 배너는 글자가 배경 위에 디자인으로
    얹혀 있어서, 덮으려 들면 그 글자를 **지워 버린다**(유니버셜의 보라·초록 배너가
    반쯤 지워져 나왔다). 그런 밴드는 손대지 않고 통째로 싣는다 — 그래서 None 이다.
    """
    bgc = _bg(im)
    if bgc.mean() < BG_MIN_LIGHT or (bgc.max() - bgc.min()) > BG_MAX_SAT:
        return None
    lines = _line_boxes(im)
    ink = _strokes(im)
    pen = np.ones((5, 5), np.uint8)
    out = im.copy()
    where: list[tuple[int, int, int, int] | None] = []
    for x0, y0, x1, y1 in boxes:
        mine = [L for L in lines
                if x0 <= (L[0] + L[2]) // 2 < x1 and y0 <= (L[1] + L[3]) // 2 < y1]
        pick = np.zeros(ink.shape, bool)
        for a, b, c, d in mine:
            pick[b:d, a:c] = True
        kill = cv2.dilate((ink & pick).astype(np.uint8), pen) > 0
        if not kill.any():
            # 그 안에 **덮을 글자가 없었다.** 색 배지처럼 우리가 못 지우는 글이거나
            # 글이 아니거나다. 얹지 않는다 — 얹으면 원본 위에 겹쳐 두 번 나온다.
            where.append(None)
            continue
        ys, xs = np.where(kill.any(1))[0], np.where(kill.any(0))[0]
        where.append((int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1))
        out[kill] = bgc
    return out, where


def split(im: np.ndarray) -> Split | None:
    """RGB 배열 하나. 글자가 없으면 None."""
    h, w = im.shape[:2]
    # **흰 바탕 위의 글자만 뗀다.** 맨 위 설명의 전제 그대로다. 색이 깔린 광고 배너는
    # 글자가 배경 위에 디자인으로 얹혀 있어서, 떼려 들면 `roi[ink] = bg` 가 그 글자를
    # **지워 버린다** — 유니버셜의 보라·초록 배너 본문이 반쯤 지워져 나왔다.
    # 그런 밴드는 손대지 않고 그림 그대로 둔다.
    bgc = _bg(im)
    if bgc.mean() < BG_MIN_LIGHT or (bgc.max() - bgc.min()) > BG_MAX_SAT:
        return None
    # 임계값들은 폭 500~800px 원본에서 잰 것이다. 폭이 좁은 원본은 키워서 본다.
    k = 2 if w < 600 else 1
    big = cv2.resize(im, (w * k, h * k), interpolation=cv2.INTER_CUBIC) if k > 1 else im
    comp, has_photo = _by_component(big)
    if not has_photo:
        return None                      # 사진이 없는 밴드다. 글자를 지우면 안 된다
    boxes = comp + _by_lines(big)
    if not boxes:
        return None
    boxes = [tuple(v // k for v in b) for b in boxes]
    x0 = max(min(b[0] for b in boxes) - 4, 0)
    y0 = max(min(b[1] for b in boxes) - 4, 0)
    x1 = min(max(b[2] for b in boxes) + 4, w)
    y1 = min(max(b[3] for b in boxes) + 4, h)
    tw, th = x1 - x0, y1 - y0
    # **너무 작으면 글자가 아니다.** 제품 표면의 하이라이트 한 점, 그림자 끄트머리가
    # 자꾸 '캡션'으로 잡혀서 본문 곳곳에 점선 상자가 박혔다. 실측 —
    #
    #     진짜 캡션   폭점유 0.44 · 0.75 · 0.75 · 0.83 · 0.98 · 1.00
    #     헛것        폭점유 0.06 · 0.07 · 0.07
    #
    # 0.07 과 0.44 사이가 통째로 비어 있다. 글은 가로로 뻗는다 — 그것이 사진 얼룩과
    # 다른 점이다.
    if tw < MIN_TEXT_WIDTH * w:
        return None
    # **너무 크면 사진을 통째로 글자로 오해한 것이다.** 다일레이터의 6칸 격자(넓이비
    # 0.426)를 통째로 떼어내는 바람에 남은 사진이 조각조각 깨져 나왔다. 실측 —
    #
    #     진짜 캡션   넓이비 0.132 ~ 0.218
    #     통째로 삼킴 넓이비 0.426
    if tw * th > MAX_TEXT_AREA * h * w:
        return None
    text = im[y0:y1, x0:x1].copy()
    photo = im.copy()
    bg = _bg(im)
    roi = photo[y0:y1, x0:x1]
    ink = cv2.dilate((np.abs(roi.astype(int) - bg).sum(axis=2) > 20).astype(np.uint8),
                     np.ones((5, 5), np.uint8)) > 0
    hsv = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)
    # 채도 있는 밝은 픽셀(살색·제품색)은 사진이다. 글자만 덮는다.
    skin = (hsv[:, :, 1] > 40) & (roi[:, :, 0] > 150)
    roi[ink & ~skin] = bg
    return Split((x0, y0, x1, y1), photo, text)
