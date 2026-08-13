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


def test_캡션이_없다고_유닛을_버리지_않는다(tmp_path: Path):
    """캡션 붙은 유닛만 내보냈더니 트리니티에서 큰 그림들이 통째로 사라졌다.

    3.1 — 없는 것은 유닛이 아니라 캡션이다.
    """
    import numpy as np
    from PIL import Image

    from app.convert import from_whole_image

    img = np.full((1200, 560, 3), 255, np.uint8)
    img[40:240, 30:530] = 150            # 광고컷
    img[300:500, 30:530] = 150           # 그림 + 캡션
    img[520:530, 30:400] = 110
    img[600:800, 30:530] = 150           # 캡션 없는 그림
    img[900:1100, 30:530] = 150          # 캡션 없는 그림
    units, ad, _ink, _gaps = from_whole_image("x", Image.fromarray(img), tmp_path)
    assert len(units) == 3, f"캡션 없는 그림이 사라졌다: {len(units)}개"
    assert sum(1 for u in units if u.caption_crop) == 1
    assert ad, "광고 구간이 사라졌다"


def test_그림_옆_글줄은_캡션이고_딱_붙은_글자는_그림이다(tmp_path: Path):
    """캡션이 그림 오른쪽에 놓이는 원본이 있다(트리니티 중간).

    멀찍이 떨어진 글줄은 캡션으로 떼어내고, 치수 표시처럼 딱 붙은 글자는
    그림의 일부로 남긴다. 거리는 그 조각의 키로 잰다 — px 를 못박지 않는다.
    """
    from PIL import Image

    from app.convert import from_whole_image

    from .fixtures import photo_with_side_text

    units, _ad, _ink, _gaps = from_whole_image("x", Image.fromarray(photo_with_side_text()), tmp_path)
    photo = units[-1]
    assert photo.caption_crop, "옆에 놓인 글줄을 캡션으로 못 봤다"
    # 사진은 x 150..360, 딱 붙은 치수 글자는 x 120..145, 캡션은 x 450..610
    assert photo.width >= 360 - 120 + 1, f"딱 붙은 글자가 떨어져 나갔다: 폭 {photo.width}"
    assert photo.width < 610 - 120, f"캡션까지 그림에 붙어 왔다: 폭 {photo.width}"


def test_사진_위에_얹힌_라벨_줄은_그림에서_뗀다(tmp_path: Path):
    """캡션이 아래로 정해지면 위에 얹힌 글줄은 갈 곳이 없어 그림에 구워진다.

    트리니티의 사진마다 위에 `모에 구멍 트리니티` 라벨과 밑줄이 그렇게 남았다.
    높이만 보면 안 된다 — 텐가 첫 칸 위의 라벨은 252×48 이라 얇아도 납작하지 않고,
    잘라내면 광고 구간의 라벨 줄이 사라진다. **글줄은 납작하다.**
    """
    from PIL import Image

    from app.convert import from_whole_image

    from .fixtures import labelled_column

    units, _ad, _ink, _gaps = from_whole_image("x", Image.fromarray(labelled_column(rows=3)), tmp_path)
    assert len(units) == 3, [f"{u.width}x{u.height}" for u in units]
    for u in units:
        assert u.caption_crop
        assert u.height <= 210, f"라벨 줄이 그림에 붙어 왔다: 높이 {u.height}"


def test_배경을_지운_조각은_카드로_둘러_준다(tmp_path: Path):
    """검은 띠 위에 흰 사각형이 덩그러니 뜨는 것을 막는다.

    흰 네모를 잘라내려 들지 않는다 — 원본 이미지는 손대지 않는다. 조각이 두르고
    있는 색을 관측해서 같은 색으로 여백을 두르면 그게 카드가 된다.
    """
    import numpy as np
    from PIL import Image

    white = np.full((60, 60, 3), 255, np.uint8)
    white[20:40, 20:40] = (200, 60, 60)
    Image.fromarray(white).save(tmp_path / "cut.jpg", quality=95)
    assert render.plate_color(tmp_path / "cut.jpg") == "#FFFFFF"

    p = _product_with_options(1, lambda i: 1, tmp_path)
    p.units[0].image = "cut.jpg"
    html = render.render(p, tmp_path)
    assert 'variant__fig--card" style="background:#FFFFFF"' in html

    # 가장자리까지 그림이 꽉 찬 조각은 손대지 않는다
    noisy = np.random.default_rng(0).integers(0, 255, (60, 60, 3), dtype=np.uint8)
    Image.fromarray(noisy).save(tmp_path / "full.jpg", quality=95)
    assert render.plate_color(tmp_path / "full.jpg") == "#000"


def test_상품명은_특징_한글명_외국어명_세_줄로_갈린다():
    """원본 상품명은 상세페이지용이 아니라 물류용이다.

    브랜드·모델번호·브랜드 약자가 뒤에 줄줄이 붙어 제목이 세 줄을 잡아먹는다.
    브랜드는 이미 제목 위에 실리고, 모델번호는 창고에서 쓰는 것이다.
    """
    cases = {
        "[일본 직수입] AV 미니 명기 미우라 사쿠라(AVミニ名器 水卜さくら) - 니포리기프트 (OH-3037)(NPR)":
            (["일본 직수입"], "AV 미니 명기 미우라 사쿠라", "(AVミニ名器 水卜さくら)"),
        # 대괄호는 여러 개 붙는다
        "[초보자세트][일본 직수입] AV 미니 명기(AVミニ名器) - 니포리기프트 (OH-3036)(NPR)":
            (["초보자세트", "일본 직수입"], "AV 미니 명기", "(AVミニ名器)"),
        # 하이픈 없이 코드 괄호만 붙기도 한다
        "[독일 직수입] 롬프 스위치 X(ROMP Switch X) (LVH)":
            (["독일 직수입"], "롬프 스위치 X", "(ROMP Switch X)"),
        # 괄호도 대괄호도 없으면 한 줄 그대로
        "텐가 에그 실키2": ([], "텐가 에그 실키2", ""),
    }
    for name, want in cases.items():
        assert render.split_name(name) == want, name


def test_상품명을_가르다가_글자를_잃지_않는다():
    """맨 끝 괄호만 뗀다. 첫 괄호를 외국어명으로 잡으면 뒷말이 통째로 사라진다."""
    # `시리즈 2` 가 남아야 한다
    assert render.split_name("명기(名器) 시리즈 2(メイキシリーズ) - 텐가") == (
        [], "명기(名器) 시리즈 2", "(メイキシリーズ)")
    # 끝 괄호에 한글이 있으면 외국어명이 아니다. 못 가르는 편이 잃는 것보다 낫다
    tags, korean, alt = render.split_name("버진 루프(ヴァージンループ) 2세대(신형) - 라이드재팬")
    assert alt == "" and "2세대(신형)" in korean
    # 띄어쓴 외국어명을 모델번호로 오인해 잘라내면 안 된다
    assert render.split_name("상품명(FOREIGN NAME) (OH-3037)(NPR)")[2] == "(FOREIGN NAME)"


def _product_with_options(n_options: int, per_option, tmp_path: Path) -> Product:
    """옵션 n개, 옵션마다 사진 per_option(i)장짜리 상품을 만든다."""
    from app.product import Meta

    names = [f"옵션{i:02d}" for i in range(n_options)]
    units = []
    for i, tag in enumerate(names):
        for j in range(per_option(i)):
            fn = f"o{i:02d}_{j:02d}.jpg"
            (tmp_path / fn).write_bytes(_tiny_jpeg())
            units.append(Unit(image=fn, caption=f"[{tag}] 설명 {j}."))
    apply_tags(units, names)
    return Product(meta=Meta(name="시험", options=names), units=units)


def test_옵션은_몇_개든_사진이_몇_장이든_묶인다(tmp_path: Path):
    """옵션 개수와 옵션당 사진 수는 상품마다 다르다. 세는 것이지 판정이 아니다.

    0개·1개·10개 옵션에, 옵션당 0·1·10·20·30장을 섞어 넣는다. 어느 조합이든
    묶임의 개수가 옵션의 개수와 같아야 하고, 사진은 한 장도 새거나 겹치지 않아야 한다.
    """
    cases = [
        (0, lambda i: 1),                       # 옵션 없음
        (1, lambda i: 1),                       # 옵션 하나 · 사진 하나
        (6, lambda i: 1),                       # 텐가꼴
        (3, lambda i: 6),                       # 닛포리꼴
        (10, lambda i: 30),                     # 많이
        (10, lambda i: [0, 1, 10, 20, 30][i % 5]),  # 제각각 (사진 0장 섞임)
    ]
    for n, per in cases:
        p = _product_with_options(n, per, tmp_path)
        expect = [f"옵션{i:02d}" for i in range(n) if per(i)]
        got = [t for t, _ in p.option_groups]
        assert got == expect, f"{n}개/{per(0)}장: 묶임이 {got}"
        for tag, us in p.option_groups:
            assert len(us) == per(int(tag[-2:])), f"{tag} 의 사진 수가 {len(us)}"
        # 사진 0장인 옵션은 사라지지 않고 고아 옵션으로 남는다
        assert p.orphan_options == [f"옵션{i:02d}" for i in range(n) if not per(i)]
        # 태그 붙은 유닛은 본문으로 새지 않는다
        assert p.body_units == []
        assert sum(len(us) for _t, us in p.option_groups) == len(p.units)


def test_옵션_사진이_많아도_카드는_옵션_수만큼만(tmp_path: Path):
    """옵션 3개에 사진이 18장이면 카드는 18칸이 아니라 3칸이어야 한다.

    사진 수만큼 카드를 찍으면 같은 옵션이 여섯 번씩 늘어서서 가이드 구실을 못 한다.
    """
    p = _product_with_options(3, lambda i: 6, tmp_path)
    html = render.render(p, tmp_path)
    assert html.count('<article class="variant') == 3, "카드가 옵션 수와 다르다"
    # 카드에 실리는 것은 옵션명이다. 장수는 살 때 쓸모가 없다
    for tag in ("옵션00", "옵션01", "옵션02"):
        assert f'</span>{tag}</p>' in html, f"카드에 옵션명 {tag} 이 없다"
    assert "사진 6장" not in html
    # 카드에 못 실은 나머지 사진은 옵션별 상세 구간에 전부 나온다
    assert html.count('class="optset__item"') == 18, "사진이 새어 나갔다"


def test_옵션마다_사진이_한_장이면_상세_구간을_만들지_않는다(tmp_path: Path):
    """텐가꼴 — 카드 한 판이면 충분한데 같은 그림을 아래에 또 깔면 중복이다."""
    p = _product_with_options(6, lambda i: 1, tmp_path)
    html = render.render(p, tmp_path)
    assert html.count('<article class="variant') == 6
    assert '<div class="optset">' not in html


def test_사진_없는_옵션도_개수에_넣는다(tmp_path: Path):
    """엑셀이 옵션 10개라 했으면 10가지다. 설명 이미지 유무로 옵션이 사라지면 거짓말이 된다."""
    p = _product_with_options(10, lambda i: 1 if i < 3 else 0, tmp_path)
    html = render.render(p, tmp_path)
    assert "10가지 종류" in html
    assert html.count('<article class="variant') == 10
    assert html.count('<article class="variant variant--bare">') == 7


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


def test_닛포리_옵션_태그의_접두_번호를_벗긴다():
    """캡션은 `[01. 키타노 미나]`, 엑셀 옵션값은 `키타노 미나` 다 (7장).

    양쪽에서 똑같이 벗기지 않으면 대조가 실패해 옵션 가이드가 통째로 안 생긴다.
    """
    from app.excel import parse_option

    opt = parse_option("배우=01. 키타노 미나,02. 미우라 사쿠라")
    assert opt.values == ["키타노 미나", "미우라 사쿠라"]
    assert split_tag("[01. 키타노 미나] 청순한 외모.")[0] == "키타노 미나"

    units = [Unit(caption="[01. 키타노 미나] 청순한 외모."), Unit(caption="[02. 미우라 사쿠라] 설명.")]
    apply_tags(units, opt.values)
    assert [u.option_tag for u in units] == ["키타노 미나", "미우라 사쿠라"]


def test_캡션이_이미지_위에_있어도_찾는다(tmp_path: Path):
    """4.3 — 캡션이 이미지 위인지 아래인지는 디자인마다 다르다.

    뒤에 붙은 것만 찾다가, 캡션이 위에 오는 원본에서 캡션 0개로 읽혔다.
    그러면 유닛이 전부 광고컷으로 넘어가 페이지가 통짜 이미지 나열이 된다.
    """
    import numpy as np
    from PIL import Image

    from app.convert import from_whole_image

    img = np.full((900, 560, 3), 255, np.uint8)
    y = 40
    for _ in range(4):
        img[y : y + 12, 30:400] = 110       # 캡션이 먼저
        img[y + 22 : y + 170, 30:530] = 150  # 그 아래 이미지
        y += 210
    units, ad, _ink, _gaps = from_whole_image("x", Image.fromarray(img), tmp_path)
    assert len(units) == 4, f"캡션을 못 찾아 유닛이 {len(units)}개"
    assert all(u.caption_crop for u in units)
    assert ad == [], "캡션을 못 찾아 광고컷으로 넘어갔다"


def test_캡션_방향은_페이지마다_하나로_정한다(tmp_path: Path):
    """유닛마다 따로 판단하면 조각 하나에 끌려 전체가 뒤집힌다.

    텐가에서 광고컷 맨 위의 2px 잔여 조각을 캡션으로 읽는 바람에 광고 구간이
    통째로 사라지고 유닛이 12개에서 13개로 늘었다.
    """
    import numpy as np
    from PIL import Image

    from app.convert import from_whole_image

    img = np.full((760, 560, 3), 255, np.uint8)
    img[20:22, 30:530] = 200               # 광고컷 위의 얇은 잔여 띠
    img[30:250, 30:530] = 160              # 광고컷 그림
    y = 300
    for _ in range(2):                      # 아래에는 캡션이 그림 밑에 붙는 유닛들
        img[y : y + 150, 30:530] = 150
        img[y + 160 : y + 172, 30:400] = 110
        y += 210
    units, ad, _ink, _gaps = from_whole_image("x", Image.fromarray(img), tmp_path)
    assert len(units) == 2, f"광고컷이 유닛으로 새어 들어왔다: {len(units)}개"
    assert ad, "광고 구간이 사라졌다"


def _tiny_jpeg() -> bytes:
    import io

    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 200, 200)).save(b, "JPEG")
    return b.getvalue()
