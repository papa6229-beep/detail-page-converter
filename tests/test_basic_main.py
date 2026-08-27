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


def facts(**kw) -> main.Facts:
    """밴드 하나에 대해 모델이 말한 사실. 안 준 것은 **흰 바탕 제품 단독컷**."""
    d = dict(products=1, white_bg=True, text=False, hand=False, full=True, box="no")
    d.update(kw)
    return main.Facts(**d)


def page(**bands):
    """`b0=facts(...)` 꼴로 페이지 하나 — (facts, kinds, hashes)."""
    got = {int(k[1:]): v for k, v in bands.items()}
    n = max(got) + 1 if got else 0
    kinds = ["PHOTO"] * n
    # dHash 는 64비트다. 서로 다른 사진은 수십 비트가 다르다.
    hashes = [0x0F0F0F0F0F0F0F0F ^ (i * 0x1111111111111111) for i in range(n)]
    return got, kinds, hashes


# ── 모델은 사실만, 고르는 것은 코드 ──────────────────────────────────────

def test_parse_facts_reads_one_line_per_band():
    got = main.parse_facts(["0:0,white,text,nohand,crop,nobox",
                            "7:1,white,notext,nohand,full,nobox",
                            "9:6,color,notext,hand,full,boxmain",
                            "27:1,white,notext,nohand,full,boxbg"])
    assert got[0].products == 0 and got[0].text and not got[0].full
    assert got[7].products == 1 and got[7].white_bg and got[7].full and got[7].box == "no"
    assert got[9].products == 6 and not got[9].white_bg and got[9].hand and got[9].box == "main"
    assert got[27].box == "bg"          # 상자가 뒤에 있는 것과 상자컷은 다르다


def test_parse_facts_survives_a_broken_line():
    """줄 하나가 깨져도 그 밴드만 잃는다 — 답 전체가 버려지지 않는다."""
    got = main.parse_facts(["0:1,white,notext,nohand,full,nobox", "쓰레기", "", "2:1,white"])
    assert set(got) == {0, 2}


def test_hero_is_white_notext_nohand_and_one_product():
    f, kinds, hashes = page(b0=facts(white_bg=False), b1=facts(text=True),
                            b2=facts(hand=True), b3=facts(products=0), b4=facts())
    hero, _feat, _pkg, _n = main.choose(f, kinds, hashes, options=1)
    assert hero == 4


def test_hero_accepts_all_options_in_one_shot():
    """옵션이 여섯이면 **여섯이 다 보이는 컷**도 대표컷이다 (다일레이터).

    여섯 중 셋만 모인 컷은 안 된다 — 손님이 구성을 잘못 읽는다.
    """
    f, kinds, hashes = page(b0=facts(products=3), b1=facts(products=6), b2=facts(products=1))
    hero, _f, _p, _n = main.choose(f, kinds, hashes, options=6)
    assert hero == 1                      # 셋짜리는 건너뛰고 여섯짜리를 쓴다
    hero1, _f1, _p1, _n1 = main.choose(f, kinds, hashes, options=1)
    assert hero1 == 2                     # 옵션이 하나면 하나짜리만 맞다


def test_hero_takes_the_earlier_band_when_several_fit():
    """여럿이면 **원본 순서상 앞의 것**. 넓이나 점수로 고르지 않는다."""
    f, kinds, hashes = page(b3=facts(), b9=facts(), b20=facts())
    hero, _f, _p, _n = main.choose(f, kinds, hashes, options=1)
    assert hero == 3


def test_hero_blank_says_why():
    f, kinds, hashes = page(b0=facts(white_bg=False), b1=facts(text=True))
    hero, _f, _p, notes = main.choose(f, kinds, hashes, options=1)
    assert hero == -1
    assert any("대표컷 빈칸" in n for n in notes)


def test_feature_skips_hero_and_allows_more_products():
    f, kinds, hashes = page(b0=facts(), b1=facts(products=3), b2=facts())
    hero, feat, _p, _n = main.choose(f, kinds, hashes, options=1)
    assert hero == 0 and feat == 1        # 키피쳐는 제품이 여럿이어도 된다


def test_feature_allows_a_hand_only_when_nothing_else_is_left():
    f, kinds, hashes = page(b0=facts(), b1=facts(hand=True))
    hero, feat, _p, notes = main.choose(f, kinds, hashes, options=1)
    assert hero == 0 and feat == 1
    assert any("손이 나온 것을 썼다" in n for n in notes)


def test_feature_skips_the_same_photo_as_hero():
    f = {0: facts(), 1: facts(), 2: facts()}
    kinds = ["PHOTO"] * 3
    hashes = [0b1010, 0b1010, 0xF0F0F0F0F0F0F0F0]      # 0 과 1 은 같은 사진
    hero, feat, _p, _n = main.choose(f, kinds, hashes, options=1)
    assert hero == 0 and feat == 2


def test_package_is_chosen_before_feature():
    """상자컷도 흰 바탕 제품컷이라 키피쳐가 먼저 집어 가면 상자 자리가 빈다.

    벨벳키스에서 실제로 그랬다 — 상자가 하나뿐인데 키피쳐가 가져갔다.
    """
    f, kinds, hashes = page(b0=facts(), b1=facts(box="main"))
    hero, feat, pkg, _n = main.choose(f, kinds, hashes, options=1)
    assert hero == 0 and pkg == 1 and feat == -1


def test_hero_needs_the_whole_product():
    """제품 **일부만** 크게 찍은 접사는 대표컷이 아니다.

    글랜스 대표컷이 원형 접사로 잡히던 것이 이 사실이 없어서였다.
    접사는 키피쳐로는 쓴다.
    """
    f, kinds, hashes = page(b0=facts(full=False), b1=facts(full=True))
    hero, feat, _p, _n = main.choose(f, kinds, hashes, options=1)
    assert hero == 1 and feat == 0


def test_hero_is_never_a_box_shot():
    """상자컷은 패키지 자리 것이다.

    상자 앞면에 제품 그림이 박혀 있어 "제품 1개 · 전체" 로도 읽히는데, 그것을
    대표컷으로 세우면 손님이 상자 사진을 제품 사진으로 본다(핑거위글).
    """
    f, kinds, hashes = page(b0=facts(box="main"), b1=facts())
    hero, _feat, pkg, _n = main.choose(f, kinds, hashes, options=1)
    assert hero == 1 and pkg == 0


def test_package_ignores_a_box_in_the_background():
    """제품이 주인공이고 상자가 뒤에 있으면 상자컷이 아니다 (유컵스)."""
    f, kinds, hashes = page(b0=facts(), b1=facts(box="bg"))
    _h, _f, pkg, notes = main.choose(f, kinds, hashes, options=1)
    assert pkg == -1
    assert any("패키지 빈칸" in n for n in notes)


def test_package_blank_when_no_box():
    f, kinds, hashes = page(b0=facts(), b1=facts())
    _h, _f, pkg, notes = main.choose(f, kinds, hashes, options=1)
    assert pkg == -1
    assert any("패키지 빈칸" in n for n in notes)


def test_text_and_promo_bands_are_never_used():
    f = {0: facts(), 1: facts(), 2: facts()}
    kinds = ["TEXT", "PROMO", "PHOTO"]
    hashes = [1, 2, 4]
    hero, _feat, _pkg, _n = main.choose(f, kinds, hashes, options=1)
    assert hero == 2


def test_take_reads_facts_and_chooses(tmp_path):
    cuts = [tmp_path / f"b{i}.jpg" for i in range(4)]
    for c in cuts:
        c.write_bytes(b"x")
    reply = json.dumps({"타입": "바이브레이터", "key1_t": "제목", "key1_d": "설명",
                        "facts": ["0:0,white,text,nohand,crop,nobox",
                                  "1:1,color,notext,nohand,full,nobox",
                                  "2:1,white,notext,nohand,full,nobox",
                                  "3:1,white,notext,nohand,full,boxmain"],
                        "body_start": 2})
    got, notes = main.take(reply, cuts, ["PHOTO"] * 4, [1, 2, 4, 8], options=1)
    assert got.spec["타입"] == "바이브레이터" and got.spec["치수"] == main.SIZE_FIXED
    assert got.keys == [("제목", "설명")]
    assert (got.main_band, got.package_band) == (2, 3)
    assert got.body_start == 2


def test_take_without_facts_leaves_everything_blank(tmp_path):
    cuts = [tmp_path / "b0.jpg"]
    cuts[0].write_bytes(b"x")
    got, notes = main.take(json.dumps({"body_start": 0}), cuts, ["PHOTO"], [1])
    assert (got.main_band, got.feature_band, got.package_band) == (-1, -1, -1)
    assert any("사실을 안 줬다" in n for n in notes)


def test_take_rejects_body_start_out_of_range(tmp_path):
    cuts = [tmp_path / "b0.jpg"]
    cuts[0].write_bytes(b"x")
    page_, notes = main.take(json.dumps({"body_start": 99}), cuts, ["PHOTO"], [0])
    assert page_.body_start == -1                              # 예비 규칙으로 넘긴다
    assert any("범위 밖" in n for n in notes)


def test_prompt_asks_for_facts_not_judgement():
    """모델은 사실만 말한다. 고르는 규칙은 코드에 있다."""
    for want in ("<제품 개수>", "white|color", "text|notext", "hand|nohand",
                 "full|crop", "boxmain|boxbg|nobox", "밴드 **전부**", "판단하지 마라"):
        assert want in main.PROMPT, want
    # 예전처럼 후보를 고르라고 하지 않는다
    assert '"main":[' not in main.PROMPT


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


def test_option_count_ignores_bundles():
    """묶음 옵션은 빼고 센다 — 유컵스 `퍼플+그린+블루` 는 제품 종류가 아니다."""
    from basic import web

    class Row:
        option_values = ["그린", "퍼플", "블루", "퍼플+그린+블루"]

    assert web.option_count(Row()) == 3

    class Empty:
        option_values = []

    assert web.option_count(Empty()) == 1



# ── 본문 — 모델이 말한 대로 놓기만 한다 ────────────────────────────────

def bp(kind: str, text: str = "", n: int = 0):
    from basic import body
    return body.Piece(kind, n, file=f"band_{n:03d}.jpg", text=text)


def test_body_kinds_are_read_one_line_each():
    from basic import read_text
    kinds, texts = read_text.parse(json.dumps({
        "kinds": ["0:title", "1:body", "2:photo", "3:shot", "4:decor", "5:쓰레기"],
        "texts": {"0": "제품특징", "1": "설명 글"}}))
    assert kinds == {0: "title", 1: "body", 2: "photo", 3: "shot", 4: "decor"}
    assert texts == {0: "제품특징", 1: "설명 글"}


def test_unspoken_bands_become_photos():
    """모델이 빠뜨린 밴드는 **사진으로 둔다.**

    버리면 원본에 있던 그림이 조용히 사라진다. 사진으로 두면 최악이라도 원본이
    실린다 — 글이 그림으로 실릴 뿐 없어지지는 않는다.
    """
    from basic import body
    got = body.pieces_from({0: "title"}, {0: "제목"}, ["a.jpg", "b.jpg", "c.jpg"])
    assert [p.kind for p in got] == ["title", "photo", "photo"]
    assert got[0].text == "제목"


def test_only_titles_and_bodies_carry_text():
    from basic import body
    got = body.pieces_from({0: "photo", 1: "shot"}, {0: "새는 글", 1: "새는 글"}, ["a", "b"])
    assert all(not p.text for p in got)


def test_title_opens_a_section():
    from basic import body
    secs = body.sections([bp(body.TITLE, "가", 0), bp(body.BODY, "글", 1),
                          bp(body.PHOTO, n=2), bp(body.TITLE, "나", 3), bp(body.PHOTO, n=4)])
    assert [s.number for s in secs] == [1, 2]
    assert secs[0].title.text == "가" and secs[1].title.text == "나"


def test_decor_is_dropped():
    from basic import body
    secs = body.sections([bp(body.DECOR, n=0), bp(body.PHOTO, n=1)])
    assert len(secs) == 1 and len(secs[0].items) == 1


def test_photo_after_body_opens_only_when_no_title():
    """제목이 하나도 없는 페이지면 "설명 뒤 사진" 이 연다."""
    from basic import body
    none = [bp(body.BODY, "글", 0), bp(body.PHOTO, n=1), bp(body.BODY, "글", 2), bp(body.PHOTO, n=3)]
    assert len(body.sections(none)) == 3       # 설명 뒤 사진이 나올 때마다 연다
    # 제목이 하나라도 있으면 그 규칙은 안 쓴다 — 사진이 섹션을 열지 않는다
    withtitle = [bp(body.TITLE, "가", 0)] + none
    assert len(body.sections(withtitle)) == 1


def test_mostly_shots_means_do_not_cut():
    """글자 박힌 사진이 3분의 2를 넘으면 본문을 통째로 싣는다."""
    from basic import body
    many = [bp(body.SHOT, n=i) for i in range(6)] + [bp(body.PHOTO, n=6)]
    assert body.mostly_shots(many)
    few = [bp(body.SHOT, n=0)] + [bp(body.PHOTO, n=i) for i in range(1, 6)]
    assert not body.mostly_shots(few)


def test_render_has_no_dashed_box():
    """점선 네모는 없앤다 — 테두리는 우리가 그린 것이지 원본에 있던 것이 아니다."""
    from basic import render
    assert "dashed" not in render.CSS


def test_render_falls_back_to_the_original_band(tmp_path):
    """글을 못 받았으면 **원본 밴드를 그대로** 싣는다."""
    from basic import body, render
    (tmp_path / "band_000.jpg").write_bytes(b"x")
    html = render.render([body.Section(1, title=bp(body.TITLE, "", 0))], tmp_path, embed=False)
    assert 'class="asis"' in html and "band_000.jpg" in html


def test_render_keeps_line_breaks_inside_a_paragraph():
    """표처럼 항목이 나열된 글은 줄이 곧 뜻이다 — 붙이면 어느 값이 어느 옵션인지 모른다."""
    from basic import body, render
    sec = body.Section(1, items=[bp(body.BODY, "A타입 10cm\nB타입 9cm", 0)])
    html = render.render([sec], Path("."), embed=False)
    assert "A타입 10cm<br>B타입 9cm" in html


def test_plain_en_strips_outer_parens():
    from basic import web
    assert web.plain_en("(Finger Wiggle Prostate Massager)") == "Finger Wiggle Prostate Massager"
    assert web.plain_en("Glans Penis Trainer") == "Glans Penis Trainer"
    assert web.plain_en("명기(名器) 시리즈") == "명기(名器) 시리즈"   # 안쪽 괄호는 그대로
