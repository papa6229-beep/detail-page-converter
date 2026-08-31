"""밴드를 **덩어리**로 나눈다. 판정은 여기 없다 — 글자냐 아니냐는 모델이 말한다.

이 파일이 하는 일은 넷뿐이다.

    ① 배경색을 뽑는다 — **이미지 전체의 최빈색**으로. 테두리로 뽑지 않는다.
    ② 배경이 아닌 픽셀을 **덩어리**로 나눈다 — 1px 깎아 얇은 선을 끊고, 나눈 뒤
       원래 두께로 되돌린다.
    ③ 어떤 덩어리가 **다른 덩어리 위에 놓였는지**를 픽셀로 잰다.
    ④ 덩어리를 배경색으로 덮는다.

무엇을 덮을지는 여기서 안 정한다. 모델이 "이건 글자다" 라고 한 것만 부르는 쪽이
넘겨준다. 예전에는 이 자리에서 코드가 스스로 "이건 캡션이고 저건 사진이다" 를
정했고, 그 잣대가 상품마다 어긋나 글랜스의 금속캡과 다일레이터의 격자에 구멍을 냈다.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

#: 최빈색을 셀 때 색을 이만큼 칸으로 뭉갠다. 사진의 흰 배경은 250~255 로 흩어져 있다.
MODE_STEP = 16
#: 배경과 이만큼 다르면 전경이다. `sidetext._by_component` 가 쓰던 값 그대로.
FG_TOL = 45
#: 글자를 가로로 이어 한 줄로 만드는 폭. 낱말 사이가 이만큼까지 벌어져도 한 줄로 본다.
#: 좁게 잡으면 한 줄이 낱말마다 흩어져 덩어리가 수십 개가 된다(핑거위글 79개).
#: **세로로는 안 잇는다** — 세로로 이으면 얇은 가로선이 굵어져 다음 단계에서 안 끊긴다.
CLOSE_W = 25


@dataclass
class Blob:
    """덩어리 하나."""

    n: int                    #: 번호 (1부터). 모델에게 이 번호로 묻는다
    box: tuple[int, int, int, int]   #: (x0, y0, x1, y1)
    area: int

    @property
    def w(self) -> int:
        return self.box[2] - self.box[0]

    @property
    def h(self) -> int:
        return self.box[3] - self.box[1]

    def inside(self, other: "Blob") -> bool:
        """내 상자가 저쪽 상자 **안에** 들어가는가."""
        a, b = self.box, other.box
        return a[0] >= b[0] and a[1] >= b[1] and a[2] <= b[2] and a[3] <= b[3]


def modal_color(im: np.ndarray) -> np.ndarray:
    """③ **이미지 전체의 최빈색.**

    테두리에서 뽑지 않는다. 옅은 회색 테두리 프레임이 있는 원본에서는 테두리 색이
    배경색이 되고, 그러면 진짜 배경까지 전경으로 잡혀 **이미지 전체가 한 덩어리**가
    된다. 전체를 세면 가장 넓은 면이 이긴다 — 그것이 배경이다.
    """
    q = (im.astype(np.int32) // MODE_STEP)
    key = (q[..., 0] << 16) | (q[..., 1] << 8) | q[..., 2]
    vals, counts = np.unique(key.ravel(), return_counts=True)
    top = vals[counts.argmax()]
    hit = key == top
    return im[hit].reshape(-1, 3).mean(axis=0)


def foreground(im: np.ndarray, bg: np.ndarray) -> np.ndarray:
    """배경과 다른 픽셀."""
    return np.abs(im.astype(int) - bg).sum(axis=2) > FG_TOL


def split(im: np.ndarray, bg: np.ndarray | None = None):
    """① 덩어리로 나눈다. `(라벨 판, 덩어리 목록)`.

    **1px 깎고 → 나누고 → 되돌린다.**

    제품에서 뻗어 나온 지시선이 제품과 배지를 한 덩어리로 이어 붙인다. 그대로 나누면
    "배지" 라는 덩어리가 없고 "제품+선+배지" 라는 덩어리 하나만 생긴다. 1px 깎으면
    얇은 선이 끊어져 셋이 갈라지고, 나눈 뒤 1px 되돌리면 깎인 껍질이 돌아온다.

    **깎여 사라진 얇은 선은 어느 덩어리에도 안 속한다** — 라벨이 0 이다. 그래서
    덮을 때 자동으로 남는다. 남기는 규칙을 따로 쓰지 않아도 그렇게 된다.

    가로로만 먼저 잇는다(`CLOSE_W`). 글자 하나하나가 아니라 **글 한 줄**이 덩어리가
    되게 하려는 것이다. 세로로 이으면 얇은 가로선이 굵어져 안 끊긴다.
    """
    bg = modal_color(im) if bg is None else bg
    fg = foreground(im, bg).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((1, CLOSE_W), np.uint8))

    core = cv2.erode(fg, np.ones((3, 3), np.uint8))          # 1px 깎기
    n, lab = cv2.connectedComponents(core)
    # `dilate` 는 32비트 정수 판을 못 받는다. 16비트로 옮겨 번지게 한다.
    small = np.clip(lab, 0, 65535).astype(np.uint16)
    grown = cv2.dilate(small, np.ones((3, 3), np.uint8))     # 1px 되돌리기
    lab = np.where(core > 0, small, np.where(fg > 0, grown, 0)).astype(np.int32)

    got = []
    for i in range(1, n):
        ys, xs = np.where(lab == i)
        if not len(ys):
            continue
        got.append((i, (int(xs.min()), int(ys.min()),
                        int(xs.max()) + 1, int(ys.max()) + 1), int(len(ys))))

    # **읽는 순서대로 번호를 다시 매긴다** — 위에서 아래로, 같은 높이면 왼쪽부터.
    # 덩어리를 찾은 순서는 뒤죽박죽이라(왼쪽 첫 줄이 2번, 오른쪽 첫 줄이 1번) 모델이
    # 번호를 못 따라온다. 사람이 읽는 차례와 같아야 짚어 준 뜻이 산다.
    got.sort(key=lambda g: (g[1][1], g[1][0]))
    table = np.zeros(n, np.int32)
    for new, (old, _box, _area) in enumerate(got, 1):
        table[old] = new
    lab = table[lab]
    return lab, [Blob(i, box, area) for i, (_old, box, area) in enumerate(got, 1)]


#: 덩어리 안에 뚜렷이 다른 색이 이만큼 넘게 있으면 **사진**이다.
#: 실측(핑거위글) — 글줄 8·8·8·8·10·16 ↔ 제품·손 97·54·25. 그 사이가 비어 있다.
PHOTO_COLORS = 20
#: 색을 셀 때 이만큼 칸으로 뭉갠다. JPEG 잡티로 색이 늘어나는 것을 눌러 준다.
COLOR_STEP = 32


def is_photo(im: np.ndarray, lab: np.ndarray, blob: Blob) -> bool:
    """이 덩어리가 **사진 픽셀**인가. 색이 여럿이면 사진이다.

    글자는 한 색으로 찍힌다 — 테두리가 흐려지며 몇 색이 더 생길 뿐이다. 사진은
    빛과 그림자로 수십 색이 된다.

    이 물음이 왜 필요한가. 모델이 번호를 잘못 짚어 **제품 덩어리를 글자라고**
    답하는 일이 실제로 있었다(핑거위글 밴드 12). 그대로 따르면 제품 사진이 통째로
    배경색에 덮이고 그 자리에 616px 짜리 글자가 앉는다. **제품 사진은 어떤 경우에도
    건드리지 않는다** — 그것을 코드가 지킨다.
    """
    q = im.astype(np.int32) // COLOR_STEP
    key = (q[..., 0] << 10) | (q[..., 1] << 5) | q[..., 2]
    return len(np.unique(key[lab == blob.n])) > PHOTO_COLORS


#: 적힌 글이 그 상자를 이만큼 넘게 넘치면 **번호를 잘못 짚은 것**이다.
OVERFLOW = 2.0
#: 글자 하나가 차지하는 폭을 글자 크기의 몇 배로 볼까. 한글은 네모라 1, 로마자는 좁다.
WIDE, NARROW = 1.0, 0.55


def fits(blob: Blob, text: str, ink: int) -> bool:
    """적힌 글이 그 상자에 들어가는가.

    모델이 번호를 한 칸 밀려 읽으면, 폭 4px 짜리 부스러기에 열두 글자가 배정된다.
    글의 내용을 따지는 것이 아니라 **자릿수를 맞춰 보는 것**이다 — 안 맞으면 그
    짝짓기가 틀린 것이니 그 자리는 건드리지 않는다.
    """
    em = max(1.0, ink / 0.72)
    need = sum(WIDE if ord(c) > 0x2000 else NARROW for c in text) * em
    rows = max(1, int(blob.h / (em * 1.35)))
    return need <= blob.w * rows * OVERFLOW


def union(boxes) -> tuple[int, int, int, int]:
    """상자 여럿을 감싸는 상자 하나."""
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def sits_on(lab: np.ndarray, box: tuple[int, int, int, int],
            others: list[Blob]) -> bool:
    """② 이 자리에 **다른 덩어리의 픽셀이 실제로 있는가.**

    상자가 겹치는지로 보지 않는다. 제품이 기울어 놓이면 그 상자가 넓어져 옆에 나란히
    있는 글까지 상자 안에 들어온다 — 상자로 보면 그 글을 "사진 위" 로 잘못 짚는다.
    상자 안에 **저쪽 픽셀이 한 점이라도 찍혀 있는지**를 본다.

    칠할 자리 그대로를 넣어 물어야 한다. 우리는 이제 상자 안을 통째로 칠하므로,
    그 상자에 남의 픽셀이 있으면 그것까지 지워진다.
    """
    x0, y0, x1, y1 = box
    win = lab[y0:y1, x0:x1]
    return any(bool((win == o.n).any()) for o in others)


def cover(im: np.ndarray, boxes, bg: np.ndarray) -> np.ndarray:
    """④ **상자 안을 통째로** 배경색으로 칠한 사진.

    덩어리 모양대로만 칠하면 글자에 딸린 얇은 밑줄·테두리가 남는다 — 밑줄은 1~2px
    이라 깎기에서 사라져 어느 덩어리에도 안 속하기 때문이다(핑거위글에서 덮은 글
    자리마다 밑줄만 줄줄이 남았다). 상자를 칠하면 그 자리가 깨끗해진다.

    **지시선은 상자 밖을 지나가므로 그대로 남는다.** 상자 안에 남의 픽셀이 있는
    자리는 애초에 부르는 쪽이 걸러 낸다(`sits_on`).
    """
    out = im.copy()
    for x0, y0, x1, y1 in boxes:
        out[y0:y1, x0:x1] = bg
    return out


def ink_height(lab: np.ndarray, blob: Blob) -> int:
    """④ **원본 글자의 실제 높이.** 그 덩어리에서 잉크가 닿은 세로 길이다.

    상자 높이를 그대로 쓰면 안 된다 — 상자에 꽉 채워 쓰면 원본보다 커져서 아래 줄과
    겹친다. 잉크가 닿은 높이가 곧 글자 크기다.

    **잉크 줄이 이어지는 가장 긴 구간**을 잰다. 위아래 끝만 보면 안 된다 — 글 밑에
    밑줄이 그어져 있으면 글자와 밑줄 **사이의 빈 줄까지** 높이에 들어간다. 실측으로
    글자 13px 짜리가 26px 로 재어져 글자가 두 배로 나왔다.
    """
    x0, y0, x1, y1 = blob.box
    on = (lab[y0:y1, x0:x1] == blob.n).any(axis=1)
    best = run = 0
    for v in on:
        run = run + 1 if v else 0
        best = max(best, run)
    return best or blob.h
