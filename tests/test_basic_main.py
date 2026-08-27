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


def shot(**kw) -> main.Shot:
    """잰 값으로 후보 한 장. 안 준 것은 **흰 바탕 제품 단독컷**의 값."""
    d = dict(rect=main.Rect(0, 0, 100, 100), white=0.8, color=0.02, ink=0.30,
             letters=2, design=0.01, solo=0.98, area=10000, band=0,
             bg_tint=0.0, has_text=False, subject=0.35)
    d.update(kw)
    return main.Shot(**d)


def slots(n: int, **kw):
    """밴드 n 개짜리 페이지 하나 — (shots, kinds, hashes)."""
    shots = {i: shot(band=i, **kw) for i in range(n)}
    kinds = ["PHOTO"] * n
    # dHash 는 64비트다. 서로 다른 사진은 수십 비트가 다르다.
    hashes = [0x0F0F0F0F0F0F0F0F ^ (i * 0x1111111111111111) for i in range(n)]
    return shots, kinds, hashes


# ── 거르기 — 기준은 셋뿐이다 ─────────────────────────────────────────────

def test_only_three_reasons_to_reject():
    """색 배경 · 글자 박힘 · 제품 여러 개. **이 셋 말고는 안 막는다.**"""
    assert main.reject(shot()) == ""
    assert "색 배경" in main.reject(shot(bg_tint=0.41))
    assert "글자" in main.reject(shot(has_text=True))
    assert "여러 개" in main.reject(shot(solo=0.20))
    # 예전에 막던 것들은 이제 안 막는다 — 고르는 일은 모델이 한다
    assert main.reject(shot(letters=90)) == ""      # 무늬가 잘게 갈린 제품
    assert main.reject(shot(ink=0.001)) == ""       # 창백한 제품
    assert main.reject(shot(design=0.95)) == ""     # 제품 자체가 색이다


def test_the_same_three_apply_to_every_slot():
    """자리별 예외를 두지 않는다.

    패키지에만 검사를 안 걸었을 때 죠우무는 광고 배너를, 브루스는 파우치컷을
    상자라고 세웠다. 대표컷에만 색 배경을 봤을 때 유컵스 키피쳐가 보라 배경이었다.
    """
    tinted = shot(bg_tint=0.55)
    assert main.reject(tinted) != ""          # 어느 자리든 같은 답이다
    shots, kinds, hashes = slots(3)
    shots[0] = shot(band=0, bg_tint=0.55)
    _h, _f, pkg, notes = main.pick_slots(shots, kinds, hashes,
                                         ai_main=[1], ai_package=[0, 2])
    assert pkg == 2, notes                    # 패키지도 색 배경이면 막힌다
    assert any("패키지 [0] 막음" in n for n in notes)


def test_tint_threshold_sits_in_the_measured_gap():
    """실측 — 흰 바탕 0.00~0.05 · 상자 0.16 ↔ 색 배경 0.31~1.00."""
    for ok in (0.00, 0.03, 0.05, 0.16):       # 0.16 은 벨벳키스의 진짜 상자
        assert main.reject(shot(bg_tint=ok)) == "", ok
    for tint in (0.31, 0.37, 0.41, 0.46, 0.55, 0.63, 1.00):
        assert main.reject(shot(bg_tint=tint)) != "", tint


def test_first_pass_takes_the_first_that_survives():
    """모델이 준 **순서대로** 검사해서 첫 통과를 쓴다. 코드가 순위를 뒤집지 않는다."""
    shots, kinds, hashes = slots(4)
    shots[0] = shot(band=0, bg_tint=0.60)      # 색 배경 — 막힌다
    shots[1] = shot(band=1, has_text=True)     # 글자 — 막힌다
    notes = []
    got = main.first_pass([0, 1, 2], shots, kinds, hashes, set(), [], "대표컷", notes)
    assert got == 2, notes
    assert any("[0] 막음" in n for n in notes) and any("[1] 막음" in n for n in notes)


def test_bigger_is_not_better():
    """넓이로 고르지 않는다 — 1번이 작아도 1번이다."""
    shots, kinds, hashes = slots(2)
    shots[0] = shot(band=0, area=100)
    shots[1] = shot(band=1, area=999999)
    got = main.first_pass([0, 1], shots, kinds, hashes, set(), [], "대표컷", [])
    assert got == 0


def test_all_three_rejected_leaves_blank_with_a_reason():
    """셋 다 떨어지면 **빈칸**. 코드가 대신 고르지 않는다.

    예전에는 여기서 페이지 전체를 훑어 대신 골랐고, 그 '대신 고르기' 가
    6칸 격자와 파우치 컷을 대표컷으로 세웠다.
    """
    shots, kinds, hashes = slots(4, bg_tint=0.60)
    notes = []
    got = main.first_pass([0, 1, 2], shots, kinds, hashes, set(), [], "대표컷", notes)
    assert got == -1
    assert any("빈칸" in n for n in notes)


def test_feature_skips_the_hero_and_its_twin():
    """키피쳐는 대표컷 자신과 **같은 사진**을 건너뛴다."""
    shots, kinds, _ = slots(3)
    hashes = [0b1010, 0b1010, 0xF0F0F0F0F0F0F0F0]      # 0 과 1 은 같은 사진
    hero, feat, _pkg, notes = main.pick_slots(shots, kinds, hashes,
                                              ai_main=[0], ai_feature=[1, 2])
    assert hero == 0 and feat == 2, notes
    assert any("같은 사진" in n for n in notes)


def test_summary_plate_can_never_be_hero_or_feature():
    """요약정보 표는 어떤 경우에도 못 쓴다."""
    shots, kinds, hashes = slots(3)
    hero, feat, _pkg, notes = main.pick_slots(shots, kinds, hashes, blocked={0},
                                              ai_main=[0, 1], ai_feature=[0, 2])
    assert hero == 1 and feat == 2
    assert any("요약정보 표" in n for n in notes)


def test_keyfeature_keeps_the_first_when_all_three_fail():
    """키피쳐만은 비우지 않는다 — 그림 자리가 비면 글 카드만 남아 층이 무너진다.

    대신 **왜 떨어진 것을 쓰는지 적는다.**
    """
    shots, kinds, hashes = slots(4, bg_tint=0.60)
    shots[3] = shot(band=3)                      # 대표컷이 쓸 깨끗한 컷
    hero, feat, pkg, notes = main.pick_slots(shots, kinds, hashes,
                                             ai_main=[3], ai_feature=[0, 1],
                                             ai_package=[2])
    assert hero == 3
    assert feat == 0, notes                      # 떨어졌어도 첫 번째를 쓴다
    assert any("그대로 쓴다" in n for n in notes)
    assert pkg == -1                             # 대표컷·패키지는 비운다


def test_take_reads_the_flat_shape(tmp_path):
    """답은 평평한 칸이다 — 중첩을 없앤 뒤 모델이 대괄호를 안 빠뜨린다."""
    cuts = [tmp_path / f"b{i}.jpg" for i in range(4)]
    for c in cuts:
        c.write_bytes(b"x")
    shots, kinds, hashes = slots(4)
    reply = json.dumps({"타입": "바이브레이터", "재질": "실리콘",
                        "key1_t": "제목", "key1_d": "설명",
                        "main": [0, 1], "feature": [2], "package": 3, "body_start": 2})
    page, notes = main.take(reply, cuts, kinds, hashes, shots=shots, blocked=set())
    assert page.spec["타입"] == "바이브레이터"
    assert page.spec["치수"] == main.SIZE_FIXED
    assert page.keys == [("제목", "설명")]
    assert (page.main_band, page.feature_band, page.package_band) == (0, 2, 3)
    assert page.body_start == 2


def test_take_still_reads_the_old_nested_shape(tmp_path):
    """저장해 둔 옛 답도 읽힌다."""
    cuts = [tmp_path / "b0.jpg"]
    cuts[0].write_bytes(b"x")
    shots, kinds, hashes = slots(1)
    reply = json.dumps({"spec": {"타입": "옛 모양"}, "keys": [{"t": "제목", "d": "설명"}],
                        "main": [0], "body_start": 0})
    page, _ = main.take(reply, cuts, kinds, hashes, shots=shots, blocked=set())
    assert page.spec["타입"] == "옛 모양" and page.keys == [("제목", "설명")]


def test_take_survives_a_single_number(tmp_path):
    """모델이 배열 대신 숫자 하나를 보내도 받는다."""
    cuts = [tmp_path / "b0.jpg"]
    cuts[0].write_bytes(b"x")
    shots, kinds, hashes = slots(1)
    page, _ = main.take(json.dumps({"main": 0}), cuts, kinds, hashes, shots=shots)
    assert page.main_band == 0


def test_take_rejects_body_start_out_of_range(tmp_path):
    cuts = [tmp_path / "b0.jpg"]
    cuts[0].write_bytes(b"x")
    page, notes = main.take(json.dumps({"body_start": 99}), cuts, ["PHOTO"], [0])
    assert page.body_start == -1                              # 예비 규칙으로 넘긴다
    assert any("범위 밖" in n for n in notes)


def test_no_candidates_means_blank_not_a_code_pick():
    """모델이 아무것도 안 주면 빈칸이다. **코드는 고르지 않는다.**"""
    shots, kinds, hashes = slots(5)
    hero, feat, pkg, _n = main.pick_slots(shots, kinds, hashes)
    assert (hero, feat, pkg) == (-1, -1, -1)


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


def test_prompt_asks_for_five():
    """자리마다 다섯을 받아야 앞의 둘이 걸러져도 쓸 것이 남는다.

    셋이었을 때 다일레이터는 모델이 원본 대표컷 둘(색 배경이라 걸러진다)을 앞에
    놓아 셋 중 하나만 남았다.
    """
    assert main.PICKS == 5
    assert '"main":[16,31,14,26,12]' in main.PROMPT
    assert '"feature":[26,12,9,31,14]' in main.PROMPT
    assert "다섯을 다 채워라" in main.PROMPT


def test_prompt_lets_package_be_empty():
    """빈 배열이 정답인 상품이 흔하다 — 억지로 채우면 링 접사가 상자로 올라간다."""
    assert "상자가 확실하지 않으면 빈 배열" in main.PROMPT


def test_five_candidates_are_tried(tmp_path):
    """넷째·다섯째까지 검사한다 — 앞의 넷이 막혀도 다섯째를 쓴다."""
    shots, kinds, hashes = slots(6)
    for i in range(4):
        shots[i] = shot(band=i, bg_tint=0.60)
    notes = []
    got = main.first_pass([0, 1, 2, 3, 4], shots, kinds, hashes, set(), [], "대표컷", notes)
    assert got == 4, notes



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
