"""기본형 메인 — 경계 규칙과 모델 답 받기.

여기서 지키려는 것 둘.

  ⓐ **경계**  메인이 어디서 끝나는가. 틀리면 본문 첫 제목을 통째로 삼키거나
     (핑거위글의 `01 제품특징`), 원본 메인 디자인이 본문에 딸려 들어온다.
  ⓑ **대표컷**  모델 픽이 거부돼도 비면 안 된다 (legacy ⓒ — 결과가 백지로 나왔다).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from basic import bands as B  # noqa: E402
from basic import boundary, main  # noqa: E402


def band(**kw) -> B.Band:
    """재 놓은 값으로 밴드 하나를 짓는다. 안 준 것은 사진에 가까운 기본값."""
    d = dict(y=0, height=200, width=800, white=0.5, color=0.0, ink=0.2, mean_sat=5.0,
             max_row_dark=0.3, largest_cc=0.30, small_cc=0, ncomp=5, fill_ratio=0.3)
    d.update(kw)
    return B.Band(**d)


#: 실물에서 잰 값 그대로 (핑거위글 35밴드 · 브루스 25밴드 중 경계에 걸린 것들)
THREE_LINE_FW = dict(color=0.354, small_cc=41, largest_cc=0.027, height=182)
THREE_LINE_BR = dict(color=0.214, small_cc=62, largest_cc=0.016, height=147)
TITLE_FW = dict(color=0.226, small_cc=2, largest_cc=0.055, height=44)
TITLE_BR = dict(color=0.152, small_cc=0, largest_cc=0.018, height=34)
PLATE_BR = dict(color=0.891, small_cc=9, largest_cc=0.972, height=291, fill_ratio=0.98)
HEADER_FW = dict(color=0.189, small_cc=9, largest_cc=0.096, height=93)   # `01 제품특징`
PKG_FW = dict(color=0.002, small_cc=0, largest_cc=0.396, height=431, fill_ratio=0.97)


def test_three_line_is_told_from_title_and_plate():
    """3줄요약만 골라내야 한다 — 상품명·요약정보 표·본문 머리띠는 아니다."""
    assert boundary._is_three_line(band(**THREE_LINE_FW))
    assert boundary._is_three_line(band(**THREE_LINE_BR))
    for other in (TITLE_FW, TITLE_BR, PLATE_BR, HEADER_FW):
        assert not boundary._is_three_line(band(**other)), other


def test_fingerwiggle_boundary():
    """핑거위글 — 3줄요약[3] 뒤에 패키지 블록[4·5·6]이 붙는다 → 7."""
    e = [
        boundary.Entry(band(**TITLE_FW), 0),                       # 0 상품명
        boundary.Entry(band(height=33, small_cc=5, largest_cc=0.003), 0),   # 1 영문명
        boundary.Entry(band(height=1087, color=0.551, largest_cc=0.678), 0),  # 2 대표컷+표
        boundary.Entry(band(**THREE_LINE_FW), 0),                  # 3 3줄요약
        boundary.Entry(band(**PKG_FW), 0),                         # 4 패키지 상자
        boundary.Entry(band(height=31, largest_cc=0.046, color=0.140), 0),  # 5 캡션
        boundary.Entry(band(height=81, largest_cc=0.002, color=0.021), 0),  # 6 캡션
        boundary.Entry(band(**HEADER_FW), 1),                      # 7 `01 제품특징` ← 본문
    ]
    got, note = boundary.find_body_start(e)
    assert got == 7, note


def test_package_caption_stops_at_image_edge():
    """캡션 삼키기는 **같은 이미지 안에서만**.

    이미지가 바뀌면 멈춘다. 안 그러면 핑거위글의 본문 첫 제목(`01 제품특징`)이
    낮고 글이라 패키지 캡션으로 오해돼 통째로 사라진다.
    """
    e = [
        boundary.Entry(band(**THREE_LINE_FW), 0),
        boundary.Entry(band(**PKG_FW), 0),
        boundary.Entry(band(**HEADER_FW), 1),   # 다음 이미지 — 삼키면 안 된다
    ]
    got, _ = boundary.find_body_start(e)
    assert got == 2


def test_bruse_boundary():
    """브루스 — 요약정보 표가 한 덩어리로 잡힌다. 패키지는 없다 → 3줄요약 바로 뒤."""
    e = [
        boundary.Entry(band(**TITLE_BR), 0),
        boundary.Entry(band(height=29, largest_cc=0.006), 0),
        boundary.Entry(band(height=736, color=0.396, largest_cc=0.658), 0),
        boundary.Entry(band(**PLATE_BR), 0),                       # 3 요약정보 표
        boundary.Entry(band(height=517, color=0.736, largest_cc=0.740), 0),
        boundary.Entry(band(**THREE_LINE_BR), 0),                  # 5 3줄요약
        boundary.Entry(band(height=813, color=0.188, largest_cc=0.237), 0),  # 6 ← 본문
    ]
    got, note = boundary.find_body_start(e)
    assert got == 6, note


def test_no_three_line_says_so():
    """못 찾으면 0 을 주고 **왜 못 찾았는지 말한다.** 조용히 찍지 않는다."""
    got, note = boundary.find_body_start([boundary.Entry(band(), 0) for _ in range(4)])
    assert got == 0
    assert "못 찾았다" in note


def test_take_blocks_text_and_dupes(tmp_path):
    cuts = [tmp_path / f"b{i}.jpg" for i in range(4)]
    for c in cuts:
        c.write_bytes(b"x")
    kinds = ["PHOTO", "TEXT", "PHOTO", "PROMO"]
    reply = json.dumps({"spec": {"타입": "바이브레이터"}, "keys": [{"t": "제목", "d": "설명"}],
                        "main": 0, "feature": 1, "package": 3, "body_start": 2})
    page, notes = main.take(reply, cuts, kinds, [0, 1 << 20, 1 << 40, 1 << 60])
    assert page.main == cuts[0]
    assert page.feature is None and page.package is None      # TEXT · PROMO 는 막힌다
    assert page.spec["치수"] == main.SIZE_FIXED               # 치수는 고정값
    assert page.body_start == 2
    assert any("TEXT" in n for n in notes) and any("PROMO" in n for n in notes)


def test_take_never_leaves_hero_empty(tmp_path):
    """모델이 대표컷 자리에 TEXT 를 넣어도 **다시 고른다** (legacy ⓒ)."""
    cuts = [tmp_path / f"b{i}.jpg" for i in range(3)]
    for c in cuts:
        c.write_bytes(b"x")
    kinds = ["TEXT", "MIXED", "PHOTO"]
    page, notes = main.take(json.dumps({"main": 0, "body_start": 1}), cuts, kinds, [1, 2, 4])
    assert page.main is not None, notes
    assert any("대신했다" in n for n in notes)


def test_take_rejects_body_start_out_of_range(tmp_path):
    cuts = [tmp_path / "b0.jpg"]
    cuts[0].write_bytes(b"x")
    page, notes = main.take(json.dumps({"body_start": 99}), cuts, ["PHOTO"], [0])
    assert page.body_start == -1                              # 예비 규칙으로 넘긴다
    assert any("범위 밖" in n for n in notes)


def test_render_page_leaves_empty_slots_out():
    """빈 칸은 그리지 않는다. 빈 칸을 그리면 '값이 비어 있는 제품'으로 읽힌다."""
    html = main.render_page(main.Page(name_kr="이름", name_en="NAME"))
    assert "이름" in html and 'class="spec"' not in html and 'class="key"' not in html
    assert 'class="pkg"' not in html


def test_render_page_is_isolated_from_simple():
    """선택자는 전부 `.gpage` 로 시작한다 — 남의 쇼핑몰 안에서 살기 때문이다."""
    bare = [ln.strip() for ln in main.CSS.splitlines() if ln.strip().startswith(".")]
    assert bare and all(ln.startswith(".gpage") for ln in bare), bare[:3]


def test_main_width_matches_body():
    """메인과 본문이 한 파일에 위아래로 붙는다. 폭이 다르면 층이 어긋나 보인다."""
    from basic import render as bodyrender
    assert "width:860px" in main.CSS
    assert "max-width:860px" in bodyrender.CSS
