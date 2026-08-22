"""일본어 스크립트 번역 — 구조 계층만.

번역 품질은 모델이 하는 일이라 여기서 검사할 수 없다. **모양이 안 깨지는 것**은
전부 우리 코드가 하는 일이고, 그것만 여기서 못박는다.

게임 스크립트는 줄 하나가 곧 명령이다. 줄이 하나 늘거나 태그가 한 글자 달라지면
안 돌아간다.
"""

from __future__ import annotations

from app import jp

#: 사장님이 주신 실제 파일 앞부분. CRLF · 전각 공백 · 태그 · 주석이 다 들어 있다.
샘플 = (
    "//【対魔忍】秋山凜子　Ｈ１\r\n"
    "<BGM_PLAY>bgm721,1000\r\n"
    "<BG>black,NONE\r\n"
    "//【黒画面】\r\n"
    "<VOICE_PLAY>chr_0001_1_0000_r18\r\n"
    "<NAME_PLATE>凜子\r\n"
    "「……ほ、本当だな？\r\n"
    "　本当の本当に、こんな……コトでッ！？」\r\n"
    "<PAUSE>\r\n"
    "<NAME_PLATE>俺\r\n"
)


def test_아무것도_안_옮기면_원문_그대로다():
    """제일 중요한 검사다. 구조 계층이 한 글자라도 흘리면 여기서 걸린다."""
    lines = jp.parse(샘플)
    assert jp.build(lines, {}) == 샘플
    assert len(lines) == 10


def test_줄끝을_먼저_떼어_낸다():
    """`\\r` 이 몸통에 딸려 가면 번역 결과에 섞여 들어가고 파일이 깨진다."""
    ln = jp.cut("「本当だな？\r\n")
    assert (ln.head, ln.body, ln.eol) == ("", "「本当だな？", "\r\n")
    # 마지막 줄은 줄끝이 없다
    assert jp.cut("끝").eol == ""
    # LF 만 쓰는 파일도 그대로
    assert jp.cut("あ\n").eol == "\n"


def test_태그와_들여쓰기는_건드리지_않는다():
    가른것 = {ln.head: ln.body for ln in jp.parse(샘플)}
    assert "<BGM_PLAY>" in 가른것 and 가른것["<BGM_PLAY>"] == "bgm721,1000"
    assert 가른것["<NAME_PLATE>"] == "俺"
    assert 가른것["//"] == "【黒画面】"
    # 이어지는 대사 줄의 **전각 공백**이 앞부분으로 떨어져 나와야 한다
    assert "　" in 가른것
    assert 가른것["　"].startswith("本当の本当に")


def test_일본어가_없는_줄은_번역_대상이_아니다():
    쓸것 = [ln.body for ln in jp.parse(샘플) if ln.target]
    assert "bgm721,1000" not in 쓸것, "태그 파라미터를 번역하려 했다"
    assert "black,NONE" not in 쓸것
    assert "chr_0001_1_0000_r18" not in 쓸것
    assert "凜子" in 쓸것, "화자 이름은 화면에 뜨므로 번역해야 한다"
    assert "【黒画面】" in 쓸것

    # 전각 기호·전각 숫자만 있는 줄도 번역할 것이 없다
    assert not jp.cut("「……！？」").target
    assert not jp.cut("<PAUSE>").target


def test_화자_이름은_나온_차례대로_한_번씩():
    """같은 이름이 파일 안에서 매번 달리 번역되면 안 된다. 먼저 모아 한 번에 정한다."""
    assert jp.names(jp.parse(샘플)) == ["凜子", "俺"]


def test_옮긴_것을_제자리에_끼운다():
    lines = jp.parse(샘플)
    got = jp.build(lines, {5: "린코", 6: "「……저, 정말이지?"})
    assert "<NAME_PLATE>린코\r\n" in got
    assert "「……저, 정말이지?\r\n" in got
    # 손 안 댄 줄은 그대로
    assert "<BGM_PLAY>bgm721,1000\r\n" in got
    assert "　本当の本当に、こんな……コトでッ！？」\r\n" in got
    # 줄 수는 안 변한다
    assert got.count("\r\n") == 샘플.count("\r\n")


def test_개수가_안_맞으면_통째로_버린다():
    """반만 쓰면 **줄이 밀려 대사가 다른 화자에게 붙는다.** 그건 못 쓰는 결과물이다."""
    assert jp.take('["가","나","다"]', 3) == ["가", "나", "다"]
    assert jp.take('["가","나"]', 3) is None
    assert jp.take('["가","나","다","라"]', 3) is None
    assert jp.take("이건 JSON 이 아니다", 3) is None
    assert jp.take('```json\n["가"]\n```', 1) == ["가"], "코드펜스를 못 벗겼다"


def test_인코딩은_서버에서_굽고_못_적은_글자를_센다():
    """`Blob` 은 charset 을 뭐라 적어 줘도 UTF-8 로만 쓴다 — 브라우저에 못 맡긴다."""
    글 = "린코「정말이야?」\r\n"
    for enc in jp.ENCODINGS:
        데이터, 잃음 = jp.encode(글, enc)
        assert 잃음 == 0, enc
        assert 데이터.decode(enc) == 글
    assert jp.encode(글, "utf-8-sig")[0].startswith(b"\xef\xbb\xbf")

    # cp949 에 없는 글자는 세어서 알린다 — 조용히 뭉개면 어디가 깨졌는지 못 찾는다.
    # `対` 는 사장님 파일 **첫 줄**에 있는 글자이고 cp949 에 없다. 번역이 한 묶음
    # 실패해서 일본어가 남으면 여기서 잡힌다.
    _데이터, 잃음 = jp.encode("//【対魔忍】", "cp949")
    assert 잃음 == 1
    assert jp.encode("凜子", "cp949")[1] == 0, "한자라고 다 못 쓰는 것은 아니다"


def test_읽을_때_인코딩을_알아서_가린다():
    for enc in ("utf-8", "utf-8-sig", "cp932"):
        글, 무엇 = jp.decode("凜子「本当だな？」\r\n".encode(enc))
        assert 글 == "凜子「本当だな？」\r\n", enc
        assert 무엇 in jp.READ_ORDER


def test_빈_파일도_안_터진다():
    assert jp.build(jp.parse(""), {}) == ""
    assert jp.names(jp.parse("")) == []


def test_번역_모델은_값과_속도를_보고_고른_것이고_환경변수로_바꾼다():
    """사장님 지시 — *"openai의 api키로 사용할 수 있는 모델중 가격, 속도 성능 모드
    가장 합리적인 모델로 번역할 수 있게"*

    이 일은 어려운 추론이 아니다 — 일본어 한 줄을 한국어 한 줄로 옮기고, 받은
    개수만큼 JSON 배열로 돌려주면 된다. 그래서 제일 비싼 등급은 필요 없다.
    다만 **개수를 맞추는 지시**는 지켜야 해서 제일 싼 등급도 곤란하다.

    ⚠️ **값은 내가 재 본 것이 아니다.** 회사가 값이나 모델을 바꾸면 틀린다.
    그래서 코드를 안 고치고 바꿀 수 있게 환경변수로 열어 둔다.
    """
    import json
    import os

    from app import jp, llm

    assert jp.MODEL_OPENAI == "gpt-4.1-mini"

    os.environ.pop("JP_MODEL", None)
    assert jp.model_for("sk-테스트") == "gpt-4.1-mini"
    # 클로드 키면 여기서 안 정한다 — `llm` 의 기본 모델로 간다
    assert jp.model_for("sk-ant-테스트") == ""

    # 환경변수가 이긴다
    os.environ["JP_MODEL"] = "gpt-4.1"
    try:
        assert jp.model_for("sk-테스트") == "gpt-4.1"
    finally:
        os.environ.pop("JP_MODEL", None)

    # 실제로 그 모델로 나가는가
    parts = jp.line_parts(["「本当だな？"], {"凜子": "린코"})
    _url, _h, body = llm.build("sk-테스트", parts, model=jp.model_for("sk-테스트"))
    got = json.loads(body)
    assert got["model"] == "gpt-4.1-mini"
    # 지시문은 **최상위 system** 으로 간다 — 사용자 차례에 섞으면 모델이 덜 지킨다
    assert [m["role"] for m in got["messages"]] == ["system", "user"]
    assert got["messages"][0]["content"].startswith("일본어 게임 스크립트를 한국어로")


def test_번역기를_붙여도_단순형_요청은_그대로다():
    """`llm.build` 에 `system` 과 `model` 을 더했다. **단순형은 둘 다 안 쓴다.**

    안 쓰면 예전과 **바이트까지 같아야** 한다 — 그것이 "털끝 하나 안 닿는다" 다.
    """
    import json

    from app import llm

    parts = [("text", "설명 문장"), ("image", "iVBORw0KGgo=")]
    for key in ("sk-ant-테스트", "sk-테스트"):
        _u, _h, body = llm.build(key, parts, max_tokens=8000)
        got = json.loads(body)
        assert "system" not in got, key
        assert [m["role"] for m in got["messages"]] == ["user"], key
        assert got["model"] == llm.model_for(llm.provider_of(key))
