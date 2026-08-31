"""메인 섹션이 **어디서 끝나는지**를 모델 없이 찾는 예비 규칙.

AI 답(`body_start`)이 없거나 범위 밖일 때만 쓴다. 기본 경로는 모델이다 —
이건 모델이 침묵했을 때 페이지가 통째로 무너지지 않게 하는 안전망이다.

규칙은 원본 메인섹션의 생김새를 그대로 따라간다.

    대표컷 → 요약정보 표 → **3줄요약(큰 색 글씨)** → 패키지 상자 ┃ 여기서 끝

3줄요약을 찾고, 그 뒤에 패키지 블록이 붙어 있으면 그것까지 메인으로 본다.
못 찾으면 `body_start = 0` 으로 두고 왜 못 찾았는지 적는다 — 조용히 찍지 않는다.

임계값은 실물 두 상품의 밴드 60개를 재서 골랐다. 아래 `_THREE_LINE` 주석 참고.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import bands as B


@dataclass
class Entry:
    """밴드 하나와, 그것이 몇 번째 원본 이미지에서 나왔는지."""

    band: B.Band
    image: int


#: 3줄요약을 가르는 자리. 실측 (핑거위글 35밴드 · 브루스 25밴드) —
#:
#:                       color   글자꼴   큰덩어리   높이
#:   3줄요약  핑거위글     0.354     41     0.027    182
#:   3줄요약  브루스       0.214     62     0.016    147
#:   ─────────────────────────────────────────────────────
#:   상품명   핑거위글     0.226      2     0.055     44   ← 글자꼴이 가른다
#:   상품명   브루스       0.152      0     0.018     34
#:   요약정보 브루스       0.891      9     0.972    291   ← 글자꼴·큰덩어리가 가른다
#:   제품특징 머리띠       0.189      9     0.096     93   ← 글자꼴이 가른다
#:
#: **글자꼴 개수가 축이다.** 3줄요약은 세 줄이라 글자가 41·62개, 제목·머리띠는
#: 한 줄이라 0~9개다. 24 와 41 사이가 비어 있어 어디에 그어도 답이 같다.
COLOR_MIN = 0.10      #: 여러 색 — 원본은 3줄요약을 색 글씨로 박는다
LETTERS_MIN = 25      #: 많은 글자 — 세 줄이면 수십 개다
BLOB_MAX = 0.10       #: 큰 덩어리가 이보다 크면 사진이다
HEIGHT_MAX = 320      #: 세 줄 남짓. 이보다 높으면 글 구간이 아니라 그림이다

#: 요약정보 표 — 색 판 위에 표가 통째로 얹혀 한 덩어리로 잡힌다(브루스 0.972/0.98).
#: 핑거위글은 표가 사진과 한 밴드로 붙어 있어 안 잡힌다. 못 잡아도 된다 —
#: 위 글자꼴 잣대가 제목도 표도 이미 걸러낸다. 잡히면 훑기 시작점만 앞당긴다.
PLATE_BLOB = 0.90
PLATE_FILL = 0.90
PLATE_LOOK = 8        #: 표는 맨 위에 있다. 여기까지만 찾는다

#: 패키지 상자 — 제 네모를 꽉 채운 덩어리(핑거위글 0.97).
PKG_FILL = 0.90
#: 패키지 밑에 붙는 캡션(상품명·`Package Design`). 낮고 글이다.
CAP_HEIGHT = 100
CAP_BLOB = 0.10


def _is_three_line(b: B.Band) -> bool:
    """큰 글씨 + 여러 색 + 여러 줄 = 3줄요약."""
    return (
        b.color >= COLOR_MIN
        and b.small_cc >= LETTERS_MIN
        and b.largest_cc < BLOB_MAX
        and b.height <= HEIGHT_MAX
    )


def _is_plate(b: B.Band) -> bool:
    """색 판 위에 통째로 얹힌 요약정보 표."""
    return b.largest_cc >= PLATE_BLOB and b.fill_ratio >= PLATE_FILL


def summary_bands(entries: list[Entry]) -> set[int]:
    """요약정보 표가 든 밴드 번호들.

    **대표컷·feature 로 절대 못 쓰는 자리다.** 원본 메인섹션의 표를 대표컷으로
    세우면 새 페이지에 남의 디자인이 통째로 따라 들어온다 — 기본형이 피하려는
    바로 그것이다(legacy ⓖ).
    """
    return {i for i, e in enumerate(entries[:PLATE_LOOK]) if _is_plate(e.band)}


def _after_summary(entries: list[Entry]) -> int:
    """요약정보 표를 찾으면 그 다음부터 훑는다. 못 찾으면 처음부터."""
    for i, e in enumerate(entries[:PLATE_LOOK]):
        if _is_plate(e.band):
            return i + 1
    return 0


def _skip_package(entries: list[Entry], j: int) -> int:
    """3줄요약 바로 뒤에 패키지 블록이 붙어 있으면 그것까지 메인으로 본다.

    패키지는 상자 사진 한 장으로 끝나지 않는다 — 밑에 상품명과 `Package Design`
    캡션이 따라붙는다(핑거위글 밴드 4·5·6). 그 캡션까지 메인이다.

    **같은 원본 이미지 안에서만** 딸려 온다고 본다. 이미지가 바뀌면 거기서 멈춘다 —
    핑거위글의 다음 이미지 첫 밴드는 `01 제품특징` 머리띠라, 이미지 경계를 안 보면
    메인 뒤 첫 밴드를 통째로 삼킨다.
    """
    if j >= len(entries) or entries[j].band.fill_ratio < PKG_FILL:
        return j
    img = entries[j].image
    j += 1
    while (
        j < len(entries)
        and entries[j].image == img
        and entries[j].band.height <= CAP_HEIGHT
        and entries[j].band.largest_cc < CAP_BLOB
    ):
        j += 1
    return j


def find_body_start(entries: list[Entry]) -> tuple[int, str]:
    """(메인이 끝나는 밴드 번호, 사람이 읽을 한 줄).

    못 찾으면 0 을 돌려준다 — 메인을 비운다. 잘못 세우는 것보다 안 세우는 쪽이
    덜 나쁘다. 왜 못 찾았는지는 말한다.
    """
    if not entries:
        return 0, "예비 규칙: 밴드가 없다"
    start = _after_summary(entries)
    for i in range(start, len(entries)):
        if _is_three_line(entries[i].band):
            j = _skip_package(entries, i + 1)
            tail = f" · 패키지 블록 [{i + 1}…{j - 1}] 까지 메인" if j > i + 1 else ""
            return j, f"예비 규칙: 3줄요약 [{i}] 뒤 → body_start {j}{tail}"
    return 0, "예비 규칙: 3줄요약(큰 색 글씨 여러 줄)을 못 찾았다 — body_start 0 으로 둔다"
