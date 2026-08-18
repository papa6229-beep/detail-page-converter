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


def test_옵션값의_물류용_코드는_떼고_이름은_지킨다():
    """엑셀 옵션값 892개 중 532개(60%)에 모델코드·바코드가 붙어 있다.

    그래서 상세페이지 말머리 `[부부장 유아]` 와 글자로 대조하면 하나도 안 맞는다 —
    실물 49개에서 옵션 상품 17개가 전부 사진 없는 빈 카드로 나왔다.
    """
    from app.excel import strip_codes

    assert strip_codes(["웨이비2 (EGG-013) (DJ)", "복시(EGG-014)"]) == ["웨이비2", "복시"]
    assert strip_codes(["부부장 유아 - OH-3650/4570099420325"]) == ["부부장 유아"]
    assert strip_codes(["청어알 천장(4582236080170)"]) == ["청어알 천장"]
    # 코드 쪽에 소문자가 섞여도 뒤가 바코드면 코드다
    assert strip_codes(["귀두 맥스 - solvemen029/4580490010322"]) == ["귀두 맥스"]
    # 이름 사이에 낀 코드도 뗀다. 뒤의 이름 괄호는 지킨다
    assert strip_codes(["유니 다이아몬드 (UNI-002) (화이트)"]) == ["유니 다이아몬드 (화이트)"]

    # 이름인 것은 안 뗀다
    지킴 = ["A-10 사이클론", "3구 램프(그린)", "텐가 - 201 텐가 오리지널 버큠 컵", "블랙 - XL"]
    assert strip_codes(지킴) == 지킴

    # 꼬리가 옵션을 가르는 유일한 표시면 아예 안 뗀다 — 겹침으로 드러난다
    사이즈 = ["블랙(L)", "블랙(XL)"]
    assert strip_codes(사이즈) == 사이즈, "떼면 둘이 같아지는데 뗐다"
    assert strip_codes(["(EGG-013)"]) == ["(EGG-013)"], "떼면 빈 값이 되는데 뗐다"


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


def test_말머리_안의_마침표는_문장_끝이_아니다():
    """`[01. 츤데레 바니· 03. 덜렁이 바니] 두 모델은…` 이 `03.` 에서 두 동강 났다.

    소제목이 `[01. 츤데레 바니· 03`, 본문이 `덜렁이 바니] 두 모델은…` 으로 나왔다.
    """
    u = Unit(caption="[01. 츤데레 바니· 03. 덜렁이 바니] 두 모델은 따스함이 느껴집니다. 표면은 매끄럽습니다.")
    assert u.head == "[01. 츤데레 바니· 03. 덜렁이 바니] 두 모델은 따스함이 느껴집니다"
    assert u.body == "표면은 매끄럽습니다."


def test_강조_별표는_소제목_길이에_세지_않는다():
    """별표는 화면에 안 나오는 표시인데 6~60자 한도에 같이 세고 있었다.

    그래서 모델이 어디를 강조했느냐에 따라 소제목이 생겼다 없어졌다 했다 —
    2497526 에서 1번 옵션만 굵게 나온 것이 그 때문이다.
    """
    원본 = "유아 타입에 비해 조금 더 날렵하고 물결치는 듯한 웨이브 형상이 특징인 모델입니다. 손가락을 대기 편해"
    강조 = 원본.replace("웨이브 형상", "**웨이브 형상**")
    assert Unit(caption=원본).head, "원본이 소제목이 안 됐다"
    assert Unit(caption=강조).head == Unit(caption=원본).head.replace("웨이브 형상", "**웨이브 형상**")
    assert Unit(caption=강조).body == Unit(caption=원본).body


def test_옵션_태그는_캡션_접두어에서_온다():
    assert split_tag("[웨이비 2] 물결이 얽힌 형태.") == ("웨이비 2", "물결이 얽힌 형태.")
    assert split_tag("(웨이비 2) 물결이 얽힌 형태.") == ("웨이비 2", "물결이 얽힌 형태.")
    assert split_tag("접두어 없는 캡션") == ("", "접두어 없는 캡션")


def test_말머리_안의_괄호에서_잘리지_않는다():
    """여는 글자에 맞는 닫는 글자만 봐야 한다.

    `[…]` 와 `(…)` 를 둘 다 받으려고 두 닫는 글자를 함께 막아 뒀더니(`[^\\])]`),
    이름 안의 괄호가 말머리의 끝이 되어 잘렸다. 엑셀에는 괄호까지 붙은 이름으로
    있으므로 그대로 대조가 실패한다. 본문도 `] 물결 형태.` 처럼 시작했다.
    """
    assert split_tag("[웨이브 (WAV)] 물결 형태.") == ("웨이브 (WAV)", "물결 형태.")
    assert split_tag("[유니 다이아몬드 (화이트)] 설명.") == ("유니 다이아몬드 (화이트)", "설명.")
    # 말머리가 너무 길면 말머리가 아니다 (24자)
    긴것 = "[아주 긴 말머리인데 스물네 글자를 넘겨서 말머리로 안 잡혀야 하는 경우] 본문"
    assert split_tag(긴것) == ("", 긴것)


def test_엑셀_옵션값에_없는_말머리는_태그가_아니다():
    units = [Unit(caption="[주의] 사용 전 확인하세요."), Unit(caption="[웨이비 2] 물결.")]
    apply_tags(units, ["웨이비 2", "보쿠"])
    assert units[0].option_tag == "" and units[0].caption.startswith("[주의]")
    assert units[1].option_tag == "웨이비 2"


def test_앞머리가_겹치면_같은_옵션으로_본다():
    """같은 옵션을 상세페이지와 엑셀이 다르게 적어 놓은 것이 779행에 흔하다.

    한쪽이 다른 쪽을 그대로 품고 앞에서부터 겹치는 것이 대부분이라
    앞머리로 대면 붙는다. 붙으면 **엑셀 쪽 이름**을 쓴다 — "옵션은 엑셀대로 가".

    실측: 어긋난 말머리 80개 중 30개가 붙고, 붙은 30개는 전부 맞다.
    """
    units = [Unit(caption="[루미카] 핑크 몸체."), Unit(caption="[능숙한 입술(소프트)] 부드럽다.")]
    apply_tags(units, ["루미카(핑크)", "미사토(블랙)", "능숙한 입술", "어리숙한 입술"])
    assert units[0].option_tag == "루미카(핑크)", "페이지가 색을 뺐을 뿐 같은 옵션이다"
    assert units[1].option_tag == "능숙한 입술", "페이지가 경도를 더 적었을 뿐이다"


def test_두_옵션에_걸리는_앞머리는_안_붙인다():
    """`멜티` 는 `멜티 관통` 과 `멜티 비관통` 둘 다에 걸린다. 어느 쪽인지 모른다.

    모르는 것을 찍어서 붙이면 손님이 다른 물건을 주문한다. 안 붙이는 편이 낫다.
    """
    units = [Unit(caption="[멜티] 말랑한 소재.")]
    apply_tags(units, ["멜티 관통", "멜티 비관통", "스플래시 관통"])
    assert units[0].option_tag == "" and units[0].caption.startswith("[멜티]")


def test_말머리의_번호는_모양이_달라도_벗긴다():
    """`01.` `#001` 둘 다 번호다. 벗겨야 엑셀 옵션값과 맞는다 (2492321).

    단, **벗겨서 빈 값이 되면 그건 번호가 아니라 이름이다** — 2489395 의
    옵션은 `#1` `#2` `#3` 자체가 이름이다.
    """
    assert split_tag("[#001 고백편] 설명.") == ("고백편", "설명.")
    assert split_tag("[01. 고백편] 설명.") == ("고백편", "설명.")
    assert split_tag("[#1] 설명.") == ("#1", "설명."), "이름까지 벗겨 버렸다"


def test_엑셀이_옵션_0개라고_하면_세트_상품이다():
    """맨즈맥스 4종 BOX — 한 박스에 다른 종류 넷이 든 **1상품**이다.

    구성품마다 설명이 있고 말머리도 붙어 있지만 엑셀에는 옵션이 없다. 예전에는
    빈 리스트를 "모른다"로 읽고 말머리를 그대로 믿어서, 구성품이 옵션 카드가 되고
    `촉촉 홀 사용법 2STEP` 까지 5번 옵션으로 올라갔다.
    """
    def units():
        return [Unit(caption="[웨이브] 물결 형태."),
                Unit(caption="[도트] 알갱이 형태."),
                Unit(caption="[촉촉 홀 사용법 2STEP] 사용 방법 안내.")]

    세트 = units()
    apply_tags(세트, [])  # 엑셀이 "옵션 없다" 고 말했다
    assert [u.option_tag for u in 세트] == ["", "", ""]
    assert 세트[0].caption.startswith("[웨이브"), "말머리는 본문에 남는다"

    # 엑셀이 없으면(URL 하나로 돌릴 때) 모르는 것이므로 말머리를 믿는다
    모름 = units()
    apply_tags(모름, None)
    assert [u.option_tag for u in 모름] == ["웨이브", "도트", "촉촉 홀 사용법 2STEP"]


def test_사전_게이트는_이미지_없으면_보류():
    v = gate.pre_gate([], 0, 0)
    assert not v.ok and gate.NO_BODY_IMAGE in v.reasons


def test_사전_게이트는_SI_X_같은_경우를_거른다():
    # 이미지 9장 · 캡션 0 · 옵션 10 — 옵션이 유닛보다 많으면 배분할 수 없다 (7장)
    v = gate.pre_gate([f"u{i}.jpg" for i in range(9)], 0, 10)
    assert not v.ok
    assert gate.OPTION_UNMAPPABLE in v.reasons


def test_캡션_없는_여러_장은_보류시키지_않는다():
    """없는 것은 유닛이 아니라 캡션이다 (3.1).

    글 없이 광고컷만 늘어놓은 원본이 779행에 12개 있다. 그런 페이지는 그림을
    순서대로 크게 싣는 것이 정답이고, 실제로 그렇게 나온다 — 실물 49개에서
    이 규칙이 켠 빨간불 둘(2495239·2495240)은 **둘 다 멀쩡한 결과물**이었다.

    사람이 손댈 것이 없으면 빨간불이 아니다. 적어만 둔다.
    """
    v = gate.pre_gate([f"u{i}.jpg" for i in range(9)], 0, 0)
    assert v.ok, "멀쩡한 광고컷 페이지를 보류시켰다"
    assert any(gate.NO_CAPTION_MULTI_IMG in n for n in v.notes), "적어는 둬야 한다"


def test_문장이_안_끊겼는데_보류시키지_않는다():
    """실물 49개에서 이 규칙은 다섯 상품을 보류시켰고 다섯 다 오경보였다.

    보류는 **사람이 손봐야 한다**는 뜻이어야 한다. 우리 규칙이 예민해서 켜지는
    빨간불이 섞이면 빨간불 전체를 아무도 안 믿게 된다.
    """
    def 판정(caption):
        p = Product(units=[Unit(image="x.jpg", caption=caption, width=400, height=400)])
        return gate.post_check(p, ink_coverage=1.0)

    # 곧은 따옴표로 끝나도 문장은 끝난 것이다 (2494955)
    v = 판정('바디는 슬림하여 딱 맞는 착용감의 비관통 오나홀, "나의 생 삽입 아이돌"')
    assert v.ok and not v.notes, "곧은 따옴표를 문장 끝으로 못 봤다"

    # 마침표 없이 끝나는 것은 한국어 상품 문구에서 흔하다 (2495652·3·4 · 2495671)
    for text in ("리드미컬한 주름이 닿아 밀려오는 자극의 파도를 가져온다",
                 "[01. 순종적인 미니멈 메이드] 단면도를 보시면 알 수 있습니다요"):
        v = 판정(text)
        assert v.ok, f"멀쩡한 문구를 보류시켰다: {text}"
        assert v.notes, "적어는 둬야 한다"
        assert gate.CAPTION_TRUNCATED not in v.reasons


def test_스펙은_캡션에_적힌_숫자만_쓴다():
    p = Product(units=[Unit(caption="무게는 약 40 g이라 가볍고 크기는 약 6cm입니다.")])
    assert render.guess_specs(p) == [("무게", "40", "g"), ("크기", "6", "cm")]
    assert render.guess_specs(Product(units=[Unit(caption="숫자 없는 캡션")])) == []


def test_무엇의_치수인지_적혀_있어야_스펙이다():
    """단위만 보고 숫자를 끌어오면 거짓말을 싣는다.

    `가슴이 79cm의 G컵` 의 79을 제품 크기로 실어 **크기 79cm** 가 나왔다.
    79cm 짜리 오나홀은 없다. 못 싣는 것이 틀리게 싣는 것보다 낫다.
    """
    body = Product(units=[Unit(caption="작고 마른 체형인데 가슴이 79cm의 G컵인 갭 모에")])
    assert render.guess_specs(body) == [], "몸매 치수를 제품 크기로 실었다"
    assert render.guess_specs(Product(units=[Unit(caption="나이 24살 신장 158cm")])) == []

    # 이름도 우리가 붙이지 않고 원본이 쓴 말에서 가져온다
    spec = Product(units=[Unit(caption="각부 치수 (무게 : 372g) 전장 146mm 최대폭 73mm")])
    assert render.guess_specs(spec) == [("무게", "372", "g"), ("길이", "146", "mm"), ("폭", "73", "mm")]

    # 몸무게는 kg 로 적힌다 — 그건 안 받는다
    assert render.guess_specs(Product(units=[Unit(caption="체중 45kg 신장 158cm")])) == []


def test_문장에_적힌_어림수는_스펙이_아니다():
    """`200g대 초반의 볼륨` 에서 200 을 캐 **무게 200g** 을 실었다.

    같은 옵션의 사진에는 `240g` 이라고 찍혀 있었다. 근사도 아니고 틀린 값이다.
    잰 값은 그림에 들어가고, 문장은 느낌을 적는 자리다.
    """
    말 = Product(units=[Unit(caption="200g대 초반의 묵직한 볼륨감을 지녔습니다.")])
    assert render.guess_specs(말) == [], "문장에서 수치를 캤다"
    assert render.guess_specs(Product(units=[Unit(caption="무게 40g대의 가벼움")])) == []
    assert render.guess_specs(Product(units=[Unit(caption="길이 10cm 쯤 됩니다")])) == []
    # 이름표가 붙고 어림말이 없으면 그건 잰 값이다
    assert render.guess_specs(Product(units=[Unit(caption="무게 372g")])) == [("무게", "372", "g")]


def test_타이핑된_글에_적힌_치수도_읽는다():
    """상세페이지의 상당수는 위쪽에 직접 친 글이 상품 정보의 전부다.

    캡션만 보느라 `본체 사이즈(mm): 125 × 60 × 60` 을 통째로 놓치고 있었다 —
    49개 중 10개가 치수를 거기에만 갖고 있다.
    """
    from app.product import Lead

    def specs(text):
        return render.guess_specs(Product(intro=[Lead(text=text)]))

    assert specs("전체 길이 130mm / 최대 폭 65mm\n무게: 230g") == [
        ("길이", "130", "mm"), ("폭", "65", "mm"), ("무게", "230", "g")]

    # 단위를 앞에 괄호로 적고 세 변을 늘어놓는 꼴. 하나만 뽑으면 오해가 된다
    assert specs("본체 크기(mm): 130 × 18 × 18") == [("크기", "130 × 18 × 18", "mm")]
    assert specs("본체 사이즈：60×55×135mm") == [("크기", "60 × 55 × 135", "mm")]

    # 손님이 사는 것은 상품이지 상자가 아니다
    양쪽 = "패키지 사이즈(mm): H185 × W60 × D60\n본체 사이즈(mm): 125 × 60 × 60"
    assert specs(양쪽) == [("크기", "125 × 60 × 60", "mm")]
    # 한 줄에 상품과 상자가 같이 적혀도 상품 쪽은 살린다
    assert specs("중량: 본체 200g / 총중량 230g") == [("무게", "200", "g")]

    # 문장에서 캐지 않는 규칙은 그대로다
    assert specs("200g대 초반의 묵직한 볼륨감") == []


def test_옵션이_있으면_치수를_싣지_않는다():
    """무게도 길이도 옵션마다 다르다. 어느 옵션의 값인지 못 밝히면 안 싣는다.

    닛포리에서 키타노 미나 한 명의 캡션에 있던 `200g대 초반` 이 페이지 맨 위에
    **무게 200g** 으로 올라갔다. 세 배우 전부가 200g 이라는 말이 된다.
    그리고 옵션 수를 유닛 수로 세어 `종류 18종` 이 나왔다 — 배우는 셋이다.
    """
    units = [Unit(caption="200g대 초반의 볼륨.", option_tag=t)
             for t in ("키타노 미나",) * 6 + ("미우라 사쿠라",) * 6 + ("이마이 카호",) * 6]
    p = Product(units=units)
    assert render.guess_specs(p) == [("옵션", "3", "종")], "옵션 수를 유닛 수로 셌다"

    # 옵션이 없으면 지금까지대로 캡션에 적힌 스펙을 캔다
    단품 = Product(units=[Unit(caption="전장 146mm 의 본체입니다.")])
    assert render.guess_specs(단품) == [("길이", "146", "mm")]


def test_손으로_적은_요약은_이름표가_없어도_받는다():
    """치수가 그림 픽셀로만 있는 원본이 흔하다. 사람은 그 화면을 이미 보고 있다."""
    assert render.parse_specs("233g · 12.5cm") == [("무게", "233", "g"), ("길이", "12.5", "cm")]
    assert render.parse_specs("무게 233g, 전장 12.5cm") == [("무게", "233", "g"), ("전장", "12.5", "cm")]
    assert render.parse_specs("") == []
    assert render.parse_specs("상세페이지 참조") == []  # 숫자가 없으면 스펙 칸이 아니다
    assert len(render.parse_specs("1g·2g·3g·4g·5g")) == 4  # 다섯 칸은 한 줄에 안 들어간다


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


def test_짝이_없는_페이지는_글이_위_그림이_아래다(tmp_path: Path):
    """상세페이지의 상당수가 타이핑 글 + 제품컷 몇 장이다.

    글이 정보고 그림은 구색이라, 원본이 놓은 순서를 그대로 따른다. 히어로가 대표컷을
    가져가면 그림이 글보다 위로 올라가고, 남은 광고컷은 페이지 맨 아래로 밀려나
    이어진 한 장이 위아래로 갈라진다(2495089).
    """
    from app.product import Lead

    for n in ("ad0.jpg", "ad1.jpg"):
        (tmp_path / n).write_bytes(_tiny_jpeg())
    p = Product(intro=[Lead(text="원본 맨 위에 타이핑된 설명입니다.")], ad=["ad0.jpg", "ad1.jpg"])
    html = render.render(p, tmp_path, title="짝 없음")
    assert 'class="hero__shot"' not in html, "그림이 글보다 위로 갔다"
    assert html.index('class="intro"') < html.index('class="showcase"'), "글이 그림보다 아래다"
    assert html.count('class="showcase__shot"') == 2, "광고컷이 이어서 안 실렸다"

    # 짝이 있으면 지금까지대로 히어로가 대표컷을 안는다
    (tmp_path / "u.jpg").write_bytes(_tiny_jpeg())
    q = Product(units=[Unit(image="u.jpg", caption="설명이 붙은 그림.")], ad=["ad0.jpg", "ad1.jpg"])
    html2 = render.render(q, tmp_path, title="짝 있음")
    assert 'class="hero__shot"' in html2


def test_배치는_자동_채우기_여부에_흔들리지_않는다(tmp_path: Path):
    """통이미지형은 사람이 채우기 전까지 캡션이 비어 있다.

    캡션이 채워졌는지로 갈랐더니 자동 채우기를 켰느냐에 따라 레이아웃이 뒤집혔다.
    원본에 글자리가 있었다는 증거는 **잘라 둔 캡션 조각**이다 — 변환할 때 정해진다.
    """
    for n in ("ad0.jpg", "u.jpg", "crop.jpg"):
        (tmp_path / n).write_bytes(_tiny_jpeg())

    def sections(caption):
        p = Product(units=[Unit(image="u.jpg", caption=caption, caption_crop="crop.jpg")], ad=["ad0.jpg"])
        return "hero__shot" in render.render(p, tmp_path, title="시험")

    assert sections("") == sections("나중에 채워진 문구입니다."), "채우기 여부로 배치가 바뀐다"


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

    짝이 **대부분**인 페이지다(3/5). 그런 페이지에서 캡션 없는 그림은 캡션이
    없을 뿐 유닛이다. 짝이 어쩌다 하나인 페이지는 다음 시험이 본다.
    """
    import numpy as np
    from PIL import Image

    from app.convert import from_whole_image

    img = np.full((1800, 560, 3), 255, np.uint8)
    img[40:240, 30:530] = 150            # 광고컷
    for top in (300, 900, 1500):         # 그림 + 캡션
        img[top:top + 200, 30:530] = 150
        img[top + 220:top + 230, 30:400] = 110
    img[600:800, 30:530] = 150           # 캡션 없는 그림
    img[1200:1400, 30:530] = 150         # 캡션 없는 그림
    units, ad, _ink, _gaps = from_whole_image("x", Image.fromarray(img), tmp_path)
    assert len(units) == 5, f"캡션 없는 그림이 사라졌다: {len(units)}개"
    assert sum(1 for u in units if u.caption_crop) == 3
    assert ad, "광고 구간이 사라졌다"


def test_짝이_대부분이_아니면_쪼개지_않고_통으로_싣는다(tmp_path: Path):
    """제조사 아트워크 한 장은 글이 그림 안에 박혀 있다. 자를 자리가 없다.

    사장님 말: "이 팬미팅 이런건 쪼개지 말고 그냥 통으로 붙이라니까."

    실측한 것은 **짝의 비율**이다 —

        텐가 12/12 · 버진루프 7/7 · 트리니티 11/16   쪼개는 것이 맞다
        팬미팅 3/8 · 모찌푸요루 1/3 · 밤쉘걸 1/13     통으로 써야 한다

    33% 와 69% 사이가 비어 있어 절반에 그으면 여섯 개가 다 맞는다.
    """
    import numpy as np
    from PIL import Image

    from app.convert import from_whole_image

    img = np.full((1800, 560, 3), 255, np.uint8)
    img[40:240, 30:530] = 150            # 광고컷
    img[300:500, 30:530] = 150           # 딱 하나만 글이 붙었다
    img[520:530, 30:400] = 110
    for top in (600, 900, 1200, 1500):   # 나머지는 그냥 그림
        img[top:top + 200, 30:530] = 150
    units, ad, _ink, _gaps = from_whole_image("x", Image.fromarray(img), tmp_path)
    assert units == [], f"짝이 하나뿐인데 쪼갰다: {len(units)}개"
    assert ad, "통으로 실을 그림마저 사라졌다"


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


def test_옵션에는_번호가_이름_앞에_붙는다(tmp_path: Path):
    """손님이 주문할 때 고르는 것은 **몇 번 옵션인지**다.

    엑셀 원본이 `01. 키타노 미나` 인데 대조하려고 번호를 벗겼다. 벗기는 것은
    맞지만 버리면 안 된다 — 값과 번호를 나란히 들고 간다.
    """
    from app.excel import parse_option
    from app.product import Meta

    opt = parse_option("배우=01. 키타노 미나,02. 미우라 사쿠라")
    assert opt.values == ["키타노 미나", "미우라 사쿠라"]
    assert opt.numbers == ["01", "02"]

    p = _product_with_options(3, lambda i: 1, tmp_path)
    p.meta = Meta(name="시험", options=p.meta.options, option_numbers=["01", "02", "03"])
    html = render.render(p, tmp_path)
    for no, tag in (("01", "옵션00"), ("02", "옵션01"), ("03", "옵션02")):
        assert f'<span class="variant__no">{no}.</span>{tag}' in html, f"{no}. {tag} 가 없다"

    # 원본에 번호가 없으면 나온 순서로 매긴다
    plain = _product_with_options(2, lambda i: 1, tmp_path)
    html = render.render(plain, tmp_path)
    assert '<span class="variant__no">1.</span>옵션00' in html
    assert '<span class="variant__no">2.</span>옵션01' in html


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
    assert "10가지 옵션" in html
    assert html.count('<article class="variant') == 10
    assert html.count('<article class="variant variant--bare">') == 7


def test_키_앞자리로_어디_것인지_가린다():
    """사람에게 고르게 하지 않는다. 고르게 하면 키와 회사가 어긋난다."""
    from app import llm

    assert llm.provider_of("sk-ant-api03-xxxx") == llm.ANTHROPIC
    assert llm.provider_of("sk-proj-xxxx") == llm.OPENAI
    assert llm.provider_of("sk-xxxx") == llm.OPENAI
    assert llm.label("sk-ant-x") == "Anthropic" and llm.label("sk-x") == "OpenAI"


def test_회사마다_보내는_모양이_다르다():
    """다른 곳은 넷뿐이다 — 주소 · 인증 헤더 · 그림 싣는 모양 · 답 꺼내는 자리."""
    import json

    from app import llm

    parts = [("text", "#1"), ("image", "QUJD")]

    url, headers, body = llm.build("sk-ant-key", parts)
    sent = json.loads(body)
    assert url.endswith("/v1/messages") and headers["x-api-key"] == "sk-ant-key"
    assert "anthropic-version" in headers
    img = sent["messages"][0]["content"][1]
    assert img["type"] == "image" and img["source"]["data"] == "QUJD"
    assert sent["max_tokens"] == 8000

    url, headers, body = llm.build("sk-key", parts)
    sent = json.loads(body)
    assert url.endswith("/v1/chat/completions")
    assert headers["authorization"] == "Bearer sk-key"
    img = sent["messages"][0]["content"][1]
    assert img["type"] == "image_url"
    assert img["image_url"]["url"] == "data:image/png;base64,QUJD"
    # 길이 상한은 이름이 바뀌었다. 거부당하면 옛 이름으로 다시 보낸다
    assert sent["max_completion_tokens"] == 8000
    assert json.loads(llm.build("sk-key", parts, legacy_cap=True)[2])["max_tokens"] == 8000


def test_회사마다_답_꺼내는_자리가_다르다():
    from app import llm

    a = {"content": [{"type": "text", "text": '["가", "나"]'}], "stop_reason": "max_tokens"}
    assert llm.extract("sk-ant-x", a) == ('["가", "나"]', "max_tokens")
    assert llm.truncated("sk-ant-x", "max_tokens")

    o = {"choices": [{"message": {"content": '["가", "나"]'}, "finish_reason": "length"}]}
    assert llm.extract("sk-x", o) == ('["가", "나"]', "length")
    assert llm.truncated("sk-x", "length")
    # 조각으로 쪼개 오는 경우도 받아낸다
    o2 = {"choices": [{"message": {"content": [{"type": "text", "text": "가"}, {"text": "나"}]}}]}
    assert llm.extract("sk-x", o2)[0] == "가나"


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


def test_수치가_달라진_문구는_받지_않는다():
    """스펙만은 지켜야 한다. 원본에 없던 숫자가 생기면 그 칸은 통째로 원본을 쓴다."""
    from app.server import guard

    원본 = "전체 길이 12.5cm, 무게 233g 의 묵직한 본체입니다."
    assert guard(원본, "전체 길이 13.5cm, 무게 233g 의 묵직한 본체입니다.") == 원본
    assert guard(원본, "전체 길이 12.5cm, 무게 233g의 묵직한 본체입니다.").startswith("전체 길이 12.5cm")


def test_원본에서_너무_멀어진_문구는_받지_않는다():
    """교정을 시켰는데 새로 써 왔다면 자동 채우기가 원본보다 나빠진 것이다."""
    from app.server import guard

    원본 = "부드러운 돌기가 촘촘히 박혀 있어 자극이 이어집니다."
    멀다 = "촘촘한 돌기가 만들어내는 황홀한 감각의 파도를 온몸으로 느껴 보세요."
    assert guard(원본, 멀다) == 원본
    가깝다 = "부드러운 돌기가 촘촘히 박혀 있어 자극이 이어집니다"
    assert guard(원본, 가깝다) == 가깝다


def test_지어낸_말을_강조하면_강조만_걷는다():
    """문장 전체는 멀쩡한데 강조한 말만 새로 지어냈다 — 그 문장까지 버릴 이유는 없다."""
    from app.server import guard

    원본 = "200g대 초반의 볼륨감이 손에 그대로 전해집니다."
    got = guard(원본, "200g대 초반의 **묵직한 볼륨감**이 손에 그대로 전해집니다.")
    assert "**" not in got and "묵직한" in got

    있는말 = guard(원본, "**200g대 초반의 볼륨감**이 손에 그대로 전해집니다.")
    assert "**200g대 초반의 볼륨감**" in 있는말


def test_한_어절짜리_강조는_별표만_걷는다():
    """실물 49개에서 강조 220개 중 75개가 한 낱말, 그중 33개가 조사로 끝났다.

    `**당신을**` `**공기를**` `**경도에**` — 뜻이 안 되는 토막이라 빨갛게 칠할 값이
    없다. 낱말을 자르지는 않는다. `단면도` `토네이도` 처럼 조사처럼 생긴 낱말 끝을
    떼려 들면 멀쩡한 말이 망가진다. **강조만 없애면** 글은 그대로 남는다.
    """
    from app.server import guard

    원본 = "피스톤 운동을 할 때마다 당신을 꽉꽉 짜내어 줍니다."
    한낱말 = guard(원본, "피스톤 운동을 할 때마다 **당신을** 꽉꽉 짜내어 줍니다.")
    assert 한낱말 == 원본, "글자가 달라졌다 — 강조만 걷어야 한다"

    두낱말 = "피스톤 운동을 할 때마다 **꽉꽉 짜내어** 줍니다."
    assert guard("피스톤 운동을 할 때마다 꽉꽉 짜내어 줍니다.", 두낱말) == 두낱말

    # 그림에서 읽어 온 칸도 같은 규칙을 받는다
    assert "**" not in guard("", "안쪽에서 **공기를** 밀어내듯 쥐면 됩니다.")


def test_그림에서_읽은_칸은_견줄_원본이_없다():
    """통이미지형은 모델이 읽어 온 값이 곧 원본이다. 빈 문자열과 견주면 다 버려진다."""
    from app.server import guard

    읽음 = "네잎 클로버 모양의 구멍 4개소가 조리조리한 자극을 낳습니다."
    assert guard("", 읽음) == 읽음
    assert guard("아무 말", "") == "아무 말"
    assert "**" not in guard("", "짝이 **안 맞는 별표")


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


def test_CSS_는_페이지_밖으로_안_나간다():
    """이 CSS 는 남의 페이지 안에서 산다 — 고도몰 상세설명 칸.

    2496310 을 실제로 올려놓고 재보니 `img{width:100%}` 가 쇼핑몰 로고를 1200px 로
    늘렸고, `body{font-family}` 가 쇼핑몰 글꼴을 바꿨고, 다크모드 규칙이 쇼핑몰
    배경을 #121010 으로 만들었다. 선택자 하나가 밖으로 나가면 상세페이지가 아니라
    쇼핑몰을 고치는 것이 된다.

    사람이 57개를 눈으로 지킬 수 없으므로 여기서 센다.
    """
    import re

    from app.render import CSS

    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    나간것 = [
        s.strip()
        for m in re.finditer(r"(?:^|[{}])\s*([^{}@]+?)\s*\{", css, re.M)
        for s in m.group(1).split(",")
        if s.strip() and not s.strip().startswith(".page")
    ]
    assert not 나간것, f"쇼핑몰까지 잡는 선택자: {나간것}"
    # 다크모드는 뺐다 — 쇼핑몰은 한 가지 모습으로 서 있다
    assert "prefers-color-scheme" not in css and ":root" not in css


def _canvas():
    """기본형 원본을 흉내낸 세로 통이미지 — 대표컷 후보 다섯 가지를 늘어놓는다.

    덩어리 사이는 넉넉히 벌리고(400px) 한 덩어리 안은 좁게(40px) 둔다. 분할기는
    그 간격 차이를 보고 나누므로, 이렇게 두어야 의도한 조각이 나온다.
    """
    import numpy as np

    img = np.full((4400, 800, 3), 255, np.uint8)
    # ① 컬러 배경 위의 제품 — 원본 대표컷이 늘 이 꼴이라 못 쓴다
    img[100:700, 60:740] = (250, 200, 220)
    img[250:550, 200:600] = 30
    # ② 글이 함께 구워진 조각 — 작은 덩어리를 흩어 놓는다
    img[1100:1380, 200:600] = 30
    for r in range(1420, 1660, 40):
        for c in range(80, 720, 26):
            img[r : r + 16, c : c + 14] = 40
    # ③ 제품 둘이 위아래로 — 한 덩어리가 아니다
    _blob(img, 2100, 2280, 250, 550)
    _blob(img, 2320, 2500, 250, 550)
    # ④ 제품 단독컷 (화면은 작아도 제품이 크게 찍힌 것) ← 이것이 답
    _blob(img, 3000, 3400, 150, 650)
    # ⑤ 충전 케이블처럼 가늘고 넓게 퍼진 것 — 화면은 제일 큰데 제품은 제일 작다
    _blob(img, 3800, 4300, 60, 740, thick=0.035)
    return img


def _blob(img, y0, y1, x0, x1, thick=0.18):
    """제품 실루엣 흉내 — 비스듬한 띠.

    네모나 타원으로 그리면 제 네모를 8할 넘게 채워 '상자'로 걸린다. 실물 제품컷은
    실루엣이 들쭉날쭉해 제 네모의 3할쯤만 채운다(핑거위글 단독컷 31%).
    """
    import numpy as np

    h, w = y1 - y0, x1 - x0
    yy, xx = np.ogrid[0:h, 0:w]
    img[y0:y1, x0:x1][np.abs(xx / w - yy / h) < thick] = 30


def test_대표컷은_컬러배경도_글자도_없는_제품_단독컷이다():
    """기본형은 원본 대표컷을 못 쓴다 — 하나같이 컬러 배경 위에 제품을 얹어 놨다.

    사장님 말: "기존 기본형의 디자인 냄새가 아예 없어야 한다."

    그래서 페이지 어딘가의 흰 바탕 제품 단독컷을 찾아 세운다. 핑거위글 실측 —
    컬러배경 유채 43% · 글 섞인 조각 글자꼴 89~125개 · 제품 둘 한덩어리 36~49%
    · 제품 단독컷 한덩어리 100%.
    """
    from app.basic import pick_hero, shots

    got = pick_hero(shots(_canvas()))
    assert got is not None, "대표컷을 하나도 못 골랐다"
    assert 2900 <= got.rect.y0 <= 3100, f"엉뚱한 조각을 골랐다: y0={got.rect.y0} {got.size}"


def test_대표컷은_화면이_아니라_제품이_큰_것으로_고른다():
    """충전 케이블 컷(726×774)이 제품 단독컷(608×455)보다 화면은 크지만
    제품은 훨씬 작다(잉크 8% 대 31%). 크기로 고르면 케이블이 대표컷이 된다."""
    from app.basic import pick_hero, shots

    cands = shots(_canvas())
    답 = [c for c in cands if 2900 <= c.rect.y0 <= 3100]
    큰화면 = [c for c in cands if c.rect.y0 >= 3700]
    assert 답 and 큰화면, f"시험 그림이 두 경우를 다 담고 있지 않다: {[(c.rect.y0, c.size) for c in cands]}"
    assert 큰화면[0].area > 답[0].area, "큰화면 쪽이 더 커야 시험이 성립한다"
    assert 답[0].product_pixels > 큰화면[0].product_pixels, "제품 화소는 답 쪽이 많아야 한다"
    assert pick_hero(cands).rect.y0 == 답[0].rect.y0


def test_기본형_CSS_도_페이지_밖으로_안_나간다():
    """단순형과 같은 불변식 (#18). 기본형도 고도몰 상세설명 칸에 들어간다."""
    import re

    from app.basic import CSS

    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    나간것 = [
        s.strip()
        for m in re.finditer(r"(?:^|[{}])\s*([^{}@]+?)\s*\{", css, re.M)
        for s in m.group(1).split(",")
        if s.strip() and not s.strip().startswith(".gpage")
    ]
    assert not 나간것, f"쇼핑몰까지 잡는 선택자: {나간것}"


def test_기본형은_빈_칸을_그리지_않는다():
    """없는 것을 지어내지 않는 규칙을 화면에서도 지킨다.

    고도몰 스펙은 다섯 칸으로 고정돼 있지만(타입·재질·치수·무게·전원), 원본이
    안 적어 둔 항목은 칸 자체를 안 만든다. 빈 칸을 그리면 손님은 정보가 없는 것이
    아니라 **값이 비어 있는 제품**으로 읽는다.
    """
    from app.basic import Page, render_page

    가득 = render_page(Page(name_kr="가", name_en="A", maker="B",
                          spec={"타입": "t", "재질": "m", "치수": "s", "무게": "w", "전원": "p"}))
    assert 가득.count('class="spec"') == 5
    assert 가득.count('class="specs__row"') == 2

    성긴 = render_page(Page(name_kr="가", spec={"재질": "실리콘"}))
    assert 성긴.count('class="spec"') == 1
    assert 성긴.count('class="specs__row"') == 1, "값 없는 줄까지 그렸다"
    # CSS 에는 규칙이 늘 있으므로 **마크업**을 본다
    assert 'class="hero__maker"' not in 성긴 and 'class="hero__en"' not in 성긴
    assert 'class="pkg"' not in 성긴, "패키지가 없는데 빈 상자를 그렸다"


def test_기본형_KEY_FEATURE_부제는_요약정보의_특징이다():
    """사장님 설명 — 요약정보 `특징` 이 KEY FEATURE 부제로 간다."""
    from app.basic import Page, render_page

    html = render_page(Page(name_kr="가", spec={"특징": "전립선 및 애널 자극 바이브레이터"},
                            keys=[("손가락 튕김 헤드", "헤드로 전립선을 자극")]))
    assert "전립선 및 애널 자극 바이브레이터" in html
    assert "손가락 튕김 헤드" in html
    # `특징` 은 스펙 다섯 칸에는 안 들어간다
    assert 'class="specs"' not in html


def test_원본의_색_글씨가_박힌_조각은_안_쓴다():
    """`03 제품 사이즈` 같은 분홍 제목이 딸려 오면 남의 디자인이 따라 들어온다.

    조각 전체 비율로는 못 잡는다 — 699×1823 조각에서 그 제목은 1.3% 라 묽어진다.
    **디자인 글은 한 띠에 몰려 있다.** 그 띠만 보면 32% 다.
    핑거위글 실측: 깨끗한 사진 0.4~4.2% ↔ 디자인이 박힌 것 23~100%.
    """
    import numpy as np

    from app.basic import pick_photos, shots

    img = np.full((2400, 800, 3), 255, np.uint8)
    # ① 깨끗한 제품컷
    _blob(img, 200, 700, 100, 700)
    # ② 같은 제품컷인데 위에 분홍 제목 띠가 얹혀 있다
    img[1300:1380, 120:680] = (233, 30, 140)
    _blob(img, 1450, 1950, 100, 700)

    got = shots(img)
    깨끗 = [c for c in got if c.rect.y0 < 1000]
    디자인 = [c for c in got if c.rect.y0 >= 1000]
    assert 깨끗 and 디자인, f"시험 그림이 두 경우를 안 담았다: {[(c.rect.y0, c.size) for c in got]}"
    assert 깨끗[0].design < 0.15 <= 디자인[0].design, (
        f"색 띠를 못 쟀다: 깨끗 {깨끗[0].design:.1%} · 디자인 {디자인[0].design:.1%}"
    )
    골른것 = pick_photos(got)
    assert 깨끗[0] in 골른것 and 디자인[0] not in 골른것


def test_길이_있어야_할_주소가_다_붙어_있다():
    """`/api/basic` 을 `if __name__ == "__main__": main()` **뒤에** 붙였다가
    화면에서 `Not Found` 를 맞았다.

    그렇게 실행하면 `main()` 이 서버를 띄우고 멈춰서 그 아래 줄은 영영 안 돈다.
    라우트가 등록될 기회가 없다. 파일이 길어지면 눈으로는 못 지킨다.
    """
    from app.server import app

    붙은것 = {r.path for r in app.routes}
    for 길 in ("/api/excel", "/api/convert", "/api/render", "/api/autofill",
              "/api/basic", "/api/save", "/api/made", "/out/{code}"):
        assert 길 in 붙은것, f"{길} 가 안 붙었다 — main() 뒤에 쓴 것은 아닌가"


def test_홍보_GIF_는_네_변_테두리로_가른다():
    """사장님 말: "파란색 외곽테두리에 들어가있는 움짤은 다 사용하지 않을 예정."

    색을 못박지 않고 네 변에 같은 띠가 둘러져 있는가로 센다. 실측 —
    홍보 GIF 는 네 변 파랑 80~86%, 상품 이미지는 네 변 모두 0%.
    """
    import numpy as np

    from app.basic import is_promo

    홍보 = np.full((450, 800, 3), 255, np.uint8)
    홍보[:, :] = (255, 255, 255)
    홍보[:14] = 홍보[-14:] = (30, 90, 220)
    홍보[:, :14] = 홍보[:, -14:] = (30, 90, 220)
    assert is_promo(홍보, "x.gif")
    assert not is_promo(홍보, "x.jpg"), "gif 가 아니면 홍보 움짤이 아니다"

    상품 = np.full((450, 800, 3), 255, np.uint8)
    assert not is_promo(상품, "x.gif")

    세로 = np.full((800, 450, 3), 255, np.uint8)
    세로[:12] = 세로[-12:] = 세로[:, :12] = 세로[:, -12:] = (30, 90, 220)
    assert not is_promo(세로, "x.gif"), "홍보 움짤은 가로형이다"
