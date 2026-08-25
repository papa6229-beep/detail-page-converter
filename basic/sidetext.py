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


def _by_lines(im: np.ndarray) -> list[tuple[int, int, int, int]]:
    bg = _bg(im)
    bgm = (np.abs(im.astype(int) - bg).sum(axis=2) < 40).astype(np.float32)
    local = cv2.blur(bgm, (41, 41))
    gray = cv2.cvtColor(im, cv2.COLOR_RGB2GRAY)
    sat = cv2.cvtColor(im, cv2.COLOR_RGB2HSV)[:, :, 1]
    dark = (gray < 140) | ((np.abs(im.astype(int) - bg).sum(axis=2) > 120) & (sat < 90))
    tp = ((dark & (local > 0.55)).astype(np.uint8) * 255)
    tp = cv2.morphologyEx(tp, cv2.MORPH_CLOSE, np.ones((10, 45), np.uint8))
    n, _lab, st, _ = cv2.connectedComponentsWithStats(tp)
    L = [st[i] for i in range(1, n) if st[i][4] > 250 and 6 < st[i][3] < 70 and st[i][2] > 25]
    if not L:
        return []
    return [(int(min(l[0] for l in L)), int(min(l[1] for l in L)),
             int(max(l[0] + l[2] for l in L)), int(max(l[1] + l[3] for l in L)))]


def split(im: np.ndarray) -> Split | None:
    """RGB 배열 하나. 글자가 없으면 None."""
    h, w = im.shape[:2]
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
    # 글자 영역이 밴드의 대부분이면 이건 '사진 옆 글자'가 아니라 그냥 글자 밴드다.
    if (x1 - x0) * (y1 - y0) > 0.6 * h * w:
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
