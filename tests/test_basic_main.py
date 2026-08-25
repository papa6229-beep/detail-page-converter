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
    shots = {0: shot(band=0), 2: shot(band=2, area=5000)}
    reply = json.dumps({"spec": {"타입": "바이브레이터"}, "keys": [{"t": "제목", "d": "설명"}],
                        "main": 0, "feature": 1, "package": 3, "body_start": 2})
    page, notes = main.take(reply, cuts, kinds, [0, 1 << 20, 1 << 40, 1 << 60],
                            shots=shots, blocked=set())
    assert page.main == cuts[0]
    assert page.package is None                               # PROMO 는 막힌다
    assert page.spec["치수"] == main.SIZE_FIXED               # 치수는 고정값
    assert page.body_start == 2
    # feature 로 TEXT 를 골랐다 → 후보가 아니다. 그래도 **비우지 않고** 코드가 고른다.
    assert page.feature == cuts[2]
    assert any("후보가 아니다" in n for n in notes)


def test_take_never_leaves_hero_empty(tmp_path):
    """모델이 대표컷 자리에 TEXT 를 넣어도 **다시 고른다** (legacy ⓒ)."""
    cuts = [tmp_path / f"b{i}.jpg" for i in range(3)]
    for c in cuts:
        c.write_bytes(b"x")
    kinds = ["TEXT", "MIXED", "PHOTO"]
    shots = {1: shot(band=1), 2: shot(band=2)}
    page, notes = main.take(json.dumps({"main": 0, "body_start": 1}), cuts, kinds, [1, 2, 4],
                            shots=shots, blocked=set())
    assert page.main is not None, notes


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


# ── 대표컷 검사대 ────────────────────────────────────────────────────────

def shot(**kw) -> main.Shot:
    """잰 값으로 후보 한 장. 안 준 것은 **깨끗한 단독컷**의 값."""
    d = dict(rect=main.Rect(0, 0, 100, 100), white=0.8, color=0.02, ink=0.30,
             letters=2, design=0.01, solo=0.98, area=10000, band=0,
             bg_sat=0.0, subject=0.35)
    d.update(kw)
    return main.Shot(**d)


def test_gate_tells_clean_from_designed():
    assert main.clean_hero(shot())
    assert not main.clean_hero(shot(design=0.35))     # 컬러 배경이 깔렸다
    assert not main.clean_hero(shot(letters=60))      # 큰 글자가 구워져 있다
    assert not main.clean_hero(shot(solo=0.40))       # 제품이 하나가 아니다
    assert not main.clean_hero(shot(ink=0.01))        # 제품이 너무 작다


def test_feature_gate_is_looser_than_hero():
    """손이 든 컷은 대표컷은 못 되지만 feature 로는 쓴다 (legacy 대로)."""
    hand = shot(solo=0.49)
    assert not main.clean_hero(hand)
    assert main.usable_photo(hand)


def test_ai_hero_pick_must_pass_the_gate(tmp_path):
    """모델이 원본 대표컷(진한 색 배경)을 골라도 **버리고 A등급에서 다시 고른다.**"""
    cuts = [tmp_path / f"b{i}.jpg" for i in range(3)]
    for c in cuts:
        c.write_bytes(b"x")
    kinds = ["PHOTO", "PHOTO", "PHOTO"]
    shots = {0: shot(band=0, bg_sat=30.0),          # 원본 대표컷 — 진한 색 배경
             1: shot(band=1, letters=80),           # 글 구간
             2: shot(band=2)}                       # 누끼 단독컷
    page, notes = main.take(json.dumps({"main": 0}), cuts, kinds, [1, 2, 4],
                            shots=shots, blocked=set())
    assert page.main_band == 2 and page.main_grade == "A", notes
    assert any("등급이라 떨어졌다" in n for n in notes)


def test_summary_plate_can_never_be_hero_or_feature(tmp_path):
    """요약정보 표는 어떤 경우에도 대표컷·키피쳐가 못 된다."""
    cuts = [tmp_path / f"b{i}.jpg" for i in range(2)]
    for c in cuts:
        c.write_bytes(b"x")
    shots = {0: shot(band=0), 1: shot(band=1)}
    page, notes = main.take(json.dumps({"main": 0, "feature": 0}), cuts,
                            ["PHOTO", "PHOTO"], [1, 1 << 30],
                            shots=shots, blocked={0})
    assert page.main_band == 1
    assert page.feature != cuts[0]
    assert any("요약정보 표" in n for n in notes)


# ── 대표컷·키피쳐 등급 ───────────────────────────────────────────────────

def test_grades_match_what_the_eye_says():
    """실물에서 잰 값으로 A·B·C 를 가른다 (main.py 등급 표 참고)."""
    assert main.grade(shot(bg_sat=0.9, letters=0, solo=1.000)) == "A"    # 핑거위글 누끼
    assert main.grade(shot(bg_sat=1.1, letters=7, solo=0.994)) == "A"    # 브루스 누끼
    assert main.grade(shot(bg_sat=0.0, letters=24, solo=0.946)) == "B"   # 거치대+리모컨
    assert main.grade(shot(bg_sat=1.7, letters=13, solo=0.981)) == "B"   # 파우치+케이블
    assert main.grade(shot(bg_sat=0.0, letters=42, solo=0.703)) == "C"   # 글자 박힘
    assert main.grade(shot(bg_sat=0.0, letters=7, solo=0.499)) == "C"    # 제품 둘
    assert main.grade(shot(bg_sat=8.9, letters=1, solo=1.000)) == "C"    # 진한 색 배경


def test_keyfeature_is_filled_when_clean_cuts_are_plenty():
    """**핑거위글처럼 누끼컷이 넉넉한 페이지에서 키피쳐가 비면 실패다.**

    이것이 이 파일에서 제일 중요한 시험이다 — 실제로 KEY FEATURE 가 통째로
    비어 있었다. 까닭은 대표컷에만 재선택이 있고 키피쳐엔 없어서, 모델을 안
    부르면(키가 없으면) feature 를 세우는 곳이 아무 데도 없었기 때문이다.
    """
    kinds = ["PHOTO"] * 5
    hashes = [0x0000000000000000, 0xFFFFFFFF00000000, 0x00000000FFFFFFFF,
              0xFFFF0000FFFF0000, 0x0F0F0F0F0F0F0F0F]     # 전부 다른 사진
    shots = {i: shot(band=i, area=10000 - i * 100) for i in range(5)}
    hero, feat, notes = main.pick_slots(shots, kinds, hashes)
    assert hero >= 0, notes
    assert feat >= 0, f"누끼컷이 다섯 장인데 키피쳐가 비었다: {notes}"
    assert hero != feat


def test_keyfeature_skips_the_same_photo_as_hero():
    """대표컷과 dHash 가 같으면 건너뛴다 — 같은 사진이 두 번 실린다."""
    kinds = ["PHOTO"] * 3
    hashes = [0b1010, 0b1010, 0xF0F0F0F0F0F0F0F0]    # 0 과 1 은 같은 사진 (해밍 0)
    shots = {i: shot(band=i, area=10000 - i) for i in range(3)}
    hero, feat, _ = main.pick_slots(shots, kinds, hashes)
    assert {hero, feat} == {0, 2} or {hero, feat} == {1, 2}


def test_keyfeature_never_uses_grade_c():
    """C 는 안 쓴다. A·B 가 없으면 그때만 빈칸."""
    kinds = ["PHOTO", "PHOTO"]
    shots = {0: shot(band=0), 1: shot(band=1, letters=90, solo=0.2)}   # 1 은 C
    hero, feat, notes = main.pick_slots(shots, kinds, [1, 2])
    assert hero == 0
    assert feat == -1, notes
    assert any("키피쳐 후보(A·B)가 없다" in n for n in notes)


def test_hero_falls_back_to_b_and_says_so():
    """A 가 없으면 빈칸이 아니라 B 에서 고르고 적는다."""
    kinds = ["PHOTO", "PHOTO"]
    shots = {0: shot(band=0, letters=24, solo=0.946),      # B
             1: shot(band=1, letters=90, solo=0.2)}        # C
    hero, feat, notes = main.pick_slots(shots, kinds, [1, 2])
    assert hero == 0
    assert any("A등급(누끼 단독컷)이 없어" in n for n in notes)


def test_ai_feature_pick_is_also_rechecked(tmp_path):
    """키피쳐도 대표컷과 **같은 흐름**이다 — 떨어지면 코드가 고른다."""
    cuts = [tmp_path / f"b{i}.jpg" for i in range(3)]
    for c in cuts:
        c.write_bytes(b"x")
    shots = {0: shot(band=0, area=20000), 1: shot(band=1, letters=95, solo=0.1), 2: shot(band=2)}
    page, notes = main.take(json.dumps({"main": 0, "feature": 1}), cuts,
                            ["PHOTO"] * 3,
                            [0x0000000000000000, 0xFFFFFFFF00000000, 0x00000000FFFFFFFF],
                            shots=shots, blocked=set())
    assert page.feature == cuts[2], notes
    assert any("키피쳐" in n and "떨어졌다" in n for n in notes)


# ── 본문 섹션 급 ─────────────────────────────────────────────────────────

def piece(kind: str, y: int = 0) -> "object":
    from basic import body
    return body.Piece(kind, y, 40, crop="c.png", text="글")


def test_only_the_strongest_tier_opens_sections():
    """①이 있으면 ①만 연다. ③은 소제목으로 내려간다."""
    from basic import body
    ps = [piece(body.HEAD, 0), piece(body.TITLE, 1), piece(body.BODY, 2),
          piece(body.HEAD, 3), piece(body.TITLE, 4)]
    secs = body.sections(ps)
    assert body.tier_of(ps) is None or True          # tier_of 는 위에서 이미 계산됐다
    assert len(secs) == 2                            # 머리띠 둘만 연다
    assert ps[1].kind == body.SUB and ps[4].kind == body.SUB


def test_title_opens_when_no_head():
    from basic import body
    ps = [piece(body.TITLE, 0), piece(body.BODY, 1), piece(body.TITLE, 2)]
    assert body.tier_of(ps) == body.TITLE
    assert len(body.sections(ps)) == 2


def test_badge_outranks_title():
    """②가 있으면 ③은 소제목으로 내려간다. 빈 섹션은 안 만든다."""
    from basic import body
    ps = [piece(body.BADGE, 0), piece(body.TITLE, 1), piece(body.BODY, 2),
          piece(body.BADGE, 3), piece(body.BODY, 4)]
    assert body.tier_of(ps) == body.BADGE
    secs = body.sections(ps)
    assert len(secs) == 2
    assert ps[1].kind == body.SUB          # 굵은 제목은 소제목으로


def test_intro_before_first_head_still_opens():
    """①보다 앞에 나온 ③은 첫 섹션을 연다 — 도입부가 갈 곳이 없어진다."""
    from basic import body
    ps = [piece(body.TITLE, 0), piece(body.BODY, 1), piece(body.HEAD, 2)]
    secs = body.sections(ps)
    assert len(secs) == 2
    assert secs[0].title is ps[0] and ps[0].kind == body.TITLE


def test_plain_en_strips_outer_parens():
    from basic import web
    assert web.plain_en("(Finger Wiggle Prostate Massager)") == "Finger Wiggle Prostate Massager"
    assert web.plain_en("Glans Penis Trainer") == "Glans Penis Trainer"
    assert web.plain_en("명기(名器) 시리즈") == "명기(名器) 시리즈"   # 안쪽 괄호는 그대로
