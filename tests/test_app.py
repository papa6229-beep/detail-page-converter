"""변환기 앱 — 엑셀 파싱 · 본문 세정 · 렌더."""

from pathlib import Path

from app import excel, gate, render, source
from app.product import Product, Unit, apply_tags, split_tag


def _xlsx(rows, headers) -> bytes:
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_엑셀은_열_순서가_아니라_이름으로_찾는다():
    data = _xlsx(
        [["2439903", "텐가 에그", "TENGA", "사이즈=1. 웨이비2,2. 보쿠", "<p>x</p>"]],
        ["상품번호", "상품명", "브랜드", "옵션1", "상세설명"],
    )
    sheet = excel.load(data)
    assert sheet.missing == []
    row = sheet.rows[0]
    assert row.code == "2439903" and row.brand == "TENGA"
    # 접두 번호는 벗긴다 (7장)
    assert row.option_values == ["웨이비2", "보쿠"]


def test_열_순서가_뒤바뀌어도_읽는다():
    data = _xlsx([["텐가", "<p>x</p>", "2439903"]], ["상품명", "상세설명", "상품번호"])
    row = excel.load(data).rows[0]
    assert row.code == "2439903" and row.name == "텐가"


def test_못_찾은_헤더를_이름으로_알려준다():
    sheet = excel.load(_xlsx([["a", "b"]], ["엉뚱한열", "다른열"]))
    assert "code" in sheet.missing and "body" in sheet.missing


def test_공용_장식은_버리고_상품_이미지는_남긴다():
    html = """
    <div><img src="/banana_img/conf/img/top.jpg"></div>
    <div><img src="/banana_img/k/kimtop.jpg"></div>
    <div><img src="/banana_img/product_image/man/2439903_detail.jpg"></div>
    <ul><li><img src="/files/goodsm/2478489/a.jpg"><span>캡션이다</span></li></ul>
    """
    body = source.parse(html)
    keep = [p for p in body.pieces if source.classify(p.url) != "drop"]
    assert len(keep) == 2, [p.url for p in keep]
    assert body.dropped and all("conf/" in d or "/k/" in d for d in body.dropped)
    assert keep[1].caption == "캡션이다"


def test_깨진_URL은_소재로_세지_않는다():
    body = source.parse('<img src="/conf/img/saunpumnonex.jpgx.jpg">')
    assert body.pieces == [] and body.broken


def test_상대경로를_CDN에_붙인다():
    assert source.absolute("banana_img/a.jpg").startswith(source.CDN)
    assert source.absolute("https://x.com/a.jpg") == "https://x.com/a.jpg"


def test_옵션_태그는_캡션_접두어에서_온다():
    assert split_tag("[웨이비 2] 물결이 얽힌 형태.") == ("웨이비 2", "물결이 얽힌 형태.")
    assert split_tag("접두어 없는 캡션") == ("", "접두어 없는 캡션")


def test_엑셀_옵션값에_없는_말머리는_태그가_아니다():
    units = [Unit(caption="[주의] 사용 전 확인하세요."), Unit(caption="[웨이비 2] 물결.")]
    apply_tags(units, ["웨이비 2", "보쿠"])
    assert units[0].option_tag == "" and units[0].caption.startswith("[주의]")
    assert units[1].option_tag == "웨이비 2"


def test_사전_게이트는_이미지_없으면_보류():
    v = gate.pre_gate([], 0, 0)
    assert not v.ok and gate.NO_BODY_IMAGE in v.reasons


def test_사전_게이트는_SI_X_같은_경우를_거른다():
    # 이미지 9장 · 캡션 0 · 옵션 10 — 세 숫자가 서로 맞지 않는다 (7장)
    v = gate.pre_gate([f"u{i}.jpg" for i in range(9)], 0, 10)
    assert not v.ok
    assert gate.NO_CAPTION_MULTI_IMG in v.reasons
    assert gate.OPTION_UNMAPPABLE in v.reasons


def test_스펙은_캡션에_적힌_숫자만_쓴다():
    p = Product(units=[Unit(caption="무게는 약 40 g이라 가볍고 크기는 약 6cm입니다.")])
    assert render.guess_specs(p) == [("무게", "40", "g"), ("크기", "6", "cm")]
    assert render.guess_specs(Product(units=[Unit(caption="숫자 없는 캡션")])) == []


def test_리드는_히어로와_본문에_두_번_실리지_않는다():
    head, rest = render.split_lead("첫 문장이다. 나머지 문장이다.")
    assert head == "첫 문장이다." and rest == "나머지 문장이다."
    assert render.split_lead("한 문장뿐이다.") == ("한 문장뿐이다.", "")


def test_없는_섹션은_그리지_않는다(tmp_path: Path):
    p = Product(units=[Unit(image="x.jpg", caption="캡션 하나.")])
    (tmp_path / "x.jpg").write_bytes(_tiny_jpeg())
    html = render.render(p, tmp_path, title="시험")
    assert "class=\"band\"" not in html   # 옵션 태그 없음 → 옵션 가이드 없음
    assert "class=\"specs\"" not in html  # 스펙 없음 → 스펙 줄 없음
    assert "class=\"feature" in html


def test_캡션을_안_채워도_그림은_사라지지_않는다(tmp_path: Path):
    """사람이 캡션 칸을 비워둔 채 변환해도 유닛 12장이 다 나와야 한다.

    캡션 있는 유닛만 그리게 해놨더니 12장이 조용히 사라졌다. 실제로 겪었다.
    3.1 — 캡션 없는 이미지는 버리는 것이 아니라 풀블리드로 크게 놓는다.
    """
    for i in range(12):
        (tmp_path / f"u{i}.jpg").write_bytes(_tiny_jpeg())
    (tmp_path / "ad.jpg").write_bytes(_tiny_jpeg())
    p = Product(units=[Unit(image=f"u{i}.jpg") for i in range(12)], ad=["ad.jpg"])
    html = render.render(p, tmp_path, title="캡션 없음")
    assert html.count("<img ") == 13, "캡션이 없다고 그림을 버렸다"


def test_모델_응답을_여러_모양으로_받아낸다():
    """JSON 배열 하나만 달라고 해도 앞뒤에 말이 붙거나 코드펜스가 씌워져 온다.

    한 가지 모양만 기대했다가 통째로 실패했다. 화면에는 파싱 오류만 떴다.
    """
    from app.server import _parse_captions as parse

    assert parse('["가", "나다라"]') == ["가", "나다라"]
    assert parse('```json\n["가나다", "라마바"]\n```') == ["가나다", "라마바"]
    assert parse("다음과 같습니다:\n[\"가나다\", \"라마바\"]\n이상입니다.") == ["가나다", "라마바"]
    assert parse("1. 첫 캡션입니다\n2. 둘째 캡션입니다") == ["첫 캡션입니다", "둘째 캡션입니다"]
    assert parse("") is None
    assert parse("   ") is None


def test_첫_이미지_위의_타이핑_구간을_뽑는다():
    """거의 모든 원본이 이미지 앞에 상품명·한마디·설명을 타이핑해 뒀다.

    90% 공통이면 변형이 아니라 구조다. 어댑터가 아니라 파서가 잡아야 한다.
    """
    html = """
    <p>[일본 직수입] 텐가 에그 2018 실키2</p>
    <p><span style="background-color:yellow">닭이 먼저? 계란이 먼저?</span></p>
    <p>부드럽고 쫄깃한 소재에 휩싸이는 감촉이 주축이 됩니다.</p>
    <p>특가 / 이벤트 상품 등의 경우 사은품이 제공되지 않습니다.</p>
    <div><img src="/banana_img/product_image/man/a.jpg"></div>
    """
    body = source.parse(html)
    texts = [b.text for b in body.lead_blocks]
    assert texts[0].startswith("[일본 직수입]")
    assert [b.strong for b in body.lead_blocks] == [False, True, False]
    # 쇼핑몰 안내문은 상품 설명이 아니다
    assert not any("사은품" in t for t in texts)


def test_첫_이미지가_본문_전체를_캡션으로_삼키지_않는다():
    """예전엔 '첫 이미지가 아닐 때'만 걸러서, 첫 이미지가 리드 전체를 먹었다."""
    html = """
    <p>맨 위에 타이핑된 긴 설명 문장입니다.</p>
    <div><img src="/banana_img/product_image/man/a.jpg"></div>
    <ul><li><img src="/files/goodsm/1/b.jpg"><span>이건 캡션</span></li></ul>
    """
    body = source.parse(html)
    assert body.pieces[0].caption == ""
    assert body.pieces[1].caption == "이건 캡션"


def test_강조_표시는_HTML로_바뀌고_나머지는_이스케이프된다():
    assert render.emphasize("무게 **40g** 입니다") == '무게 <b class="em">40g</b> 입니다'
    assert "&lt;script&gt;" in render.emphasize("<script>")


def test_푸터에는_상품마다_달라지는_말을_두지_않는다():
    """텐가 전용 문구를 넣어 뒀다가 1000개에 붙으면 전부 거짓이 된다."""
    joined = " ".join(h + p for h, p in render.FOOTER)
    for word in ("절취선", "필름", "에그", "뚜껑"):
        assert word not in joined, f"푸터에 상품 전용 표현이 남아 있다: {word}"


def _tiny_jpeg() -> bytes:
    import io

    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 200, 200)).save(b, "JPEG")
    return b.getvalue()
