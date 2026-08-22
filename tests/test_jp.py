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


def _가짜_LM_스튜디오():
    """LM Studio 흉내를 내는 서버. `/v1/models` 와 `/v1/chat/completions` 만 낸다.

    진짜 번역 대신 앞에 표시만 붙여 돌려준다 — 여기서 볼 것은 번역 품질이 아니라
    **개수와 순서와 모양**이다.
    """
    import json
    import re
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj):
            b = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path.endswith("/models"):
                self._send({"data": [{"id": "gemma-3-12b-it"}]})

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["content-length"])))
            H.받은것.append(req)
            본문 = req["messages"][-1]["content"]
            글 = 본문[0]["text"] if isinstance(본문, list) else 본문
            줄 = re.findall(r"^\d+\. (.*)$", 글, re.M)
            self._send({"choices": [{"message": {"content":
                        json.dumps(["옮김:" + x for x in 줄], ensure_ascii=False)}}]})

    H.받은것 = []
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, H.받은것


def test_내_컴퓨터의_LM_스튜디오로_번역한다():
    """사장님 지시 — *"내 여기 컴퓨터에 LM 스튜디오와 로컬 a.i 젬마 모델이 설치되어
    있거든? 그걸로 번역하게 만들어보자. 지금의 오픈 api가 아니라."*

    LM Studio 는 OpenAI 와 **똑같은 모양의 서버**를 연다. 그래서 갈아 끼울 것이
    주소 하나뿐이다. 키도 안 본다.
    """
    import asyncio
    import base64
    import os

    from app import jp
    from app.server import api_translate, translate_local

    srv, 받은것 = _가짜_LM_스튜디오()
    os.environ["LM_BASE"] = f"http://127.0.0.1:{srv.server_port}/v1"
    try:
        # ① 화면이 켜질 때 — **뭐가 올라와 있는지 물어본다.** 사람이 안 적는다
        got = translate_local()
        assert got["ready"] and got["models"] == ["gemma-3-12b-it"], got
        assert got["chunk"] == jp.local_chunk()

        # ② 실제 번역 — 태그·들여쓰기·줄끝이 한 글자도 안 바뀌어야 한다
        원본 = ("<BGM_PLAY>bgm721,1000\r\n"
               "<NAME_PLATE>凜子\r\n"
               "//【対魔忍】\r\n"
               "「本当だな？\r\n"
               "　こんな……」\r\n"
               "<SE_PLAY>se01\r\n")

        class F:
            filename = "script.txt"

            async def read(self):
                return 원본.encode("cp932")

        d = asyncio.run(api_translate(F(), key="", enc="utf-8", where="local", model=""))
        out = base64.b64decode(d["b64"]).decode("utf-8")

        assert d["where"] == "내 컴퓨터" and d["model"] == "gemma-3-12b-it"
        assert d["enc_in"] == "cp932", "Shift-JIS 를 못 읽었다"
        assert (d["lines"], d["targets"], d["done"], d["failed"]) == (6, 4, 4, 0), d
        assert out == ("<BGM_PLAY>bgm721,1000\r\n"
                       "<NAME_PLATE>옮김:凜子\r\n"
                       "//옮김:【対魔忍】\r\n"
                       "옮김:「本当だな？\r\n"
                       "　옮김:こんな……」\r\n"
                       "<SE_PLAY>se01\r\n"), repr(out)

        # ③ 보낸 모양 — 주소·모델·지시문 자리
        보냄 = 받은것[-1]
        assert 보냄["model"] == "gemma-3-12b-it"
        assert [m["role"] for m in 보냄["messages"]] == ["system", "user"]
        # 내 컴퓨터 서버는 옛 이름만 안다
        assert "max_tokens" in 보냄 and "max_completion_tokens" not in 보냄
    finally:
        os.environ.pop("LM_BASE", None)
        srv.shutdown()


def test_LM_스튜디오가_꺼져_있으면_그렇다고_말한다():
    """켜는 법까지 적어 준다. *"안 됩니다"* 만 뜨면 무엇을 해야 할지 모른다."""
    import asyncio
    import os

    import pytest
    from fastapi import HTTPException

    from app.server import api_translate, translate_local

    os.environ["LM_BASE"] = "http://127.0.0.1:9/v1"   # 아무도 안 듣는 포트
    try:
        assert translate_local()["ready"] is False

        class F:
            filename = "a.txt"

            async def read(self):
                return "「本当だな？\n".encode()

        with pytest.raises(HTTPException) as e:
            asyncio.run(api_translate(F(), key="", enc="utf-8", where="local", model=""))
        assert "LM Studio" in e.value.detail and "Start Server" in e.value.detail
    finally:
        os.environ.pop("LM_BASE", None)


def test_내_컴퓨터_모델의_군말을_걷어내고_배열만_꺼낸다():
    """⚠️ **회사 API 는 시키면 JSON 만 내놓는데 로컬 모델은 군말을 붙인다.**

    사장님 화면에서 `전체 1줄 중 일본어 1줄, 옮김 0줄 · 원문 유지 1줄` 이 나왔다.
    파일도 잘 읽었고 지시도 갔는데 **답을 우리가 못 읽은 것**이다.

    `supergemma4` 는 Reasoning 이 붙은 모델이라 생각을 먼저 적는다. 예전 코드는
    첫 `[` 부터 마지막 `]` 까지를 통째로 집어서, 군말에 대괄호가 하나라도 있으면
    엉뚱한 덩어리를 집었다.
    """
    from app.jp import take

    assert take('네, 옮겼습니다:\n["안녕"]', 1) == ["안녕"]
    assert take('```json\n["안녕"]\n```', 1) == ["안녕"]
    assert take("<think>이건 [주의] 대사군</think>\n[\"안녕\"]", 1) == ["안녕"]
    # 군말 속 `[1]` 이 개수만 우연히 맞는 경우 — **글자로 된 것**을 고른다
    assert take('참고 [1] 을 보면… 결과: ["안녕"]', 1) == ["안녕"]
    assert take('["가","나"]', 2) == ["가", "나"]

    # 개수가 다르면 안 쓴다. 줄이 밀리는 것보다 원문이 낫다
    assert take('["안녕","또"]', 1) is None
    assert take("죄송합니다 번역할 수 없습니다", 1) is None


def test_못_읽은_답을_화면에_보여_준다():
    """실패했을 때 **모델이 뭐라고 답했는지** 안 보여 주면 원인을 못 짚는다.

    군말을 붙였는지, 개수를 틀렸는지, 아예 거절했는지가 갈리지 않는다.
    """
    import asyncio
    import json
    import os
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from app.server import api_translate

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj):
            b = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            self._send({"data": [{"id": "gemma"}]})

        def do_POST(self):
            self.rfile.read(int(self.headers["content-length"]))
            self._send({"choices": [{"message": {"content": "죄송합니다, 번역할 수 없습니다."}}]})

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["LM_BASE"] = f"http://127.0.0.1:{srv.server_port}/v1"
    try:
        class F:
            filename = "a.txt"

            async def read(self):
                return "「本当だな？\n".encode()

        d = asyncio.run(api_translate(F(), key="", enc="utf-8", where="local", model=""))
        assert (d["done"], d["failed"]) == (0, 1)
        assert d["sample"] == "죄송합니다, 번역할 수 없습니다.", d["sample"]
    finally:
        os.environ.pop("LM_BASE", None)
        srv.shutdown()


def test_줄_안쪽_명령과_변수는_모델에게_안_보낸다():
    """사장님 지시 — *"텍스트에 무슨 기호건 괄호건 막 있어도 그런건 다 그대로
    유지하고 딱 일본어 부분만 한글로 변환하는거?"*

    ⚠️ **절반만 지키고 있었다.** 줄 바깥(태그·들여쓰기·줄끝)은 코드가 지키는데,
    줄 **안쪽**의 `[r]` `%name%` `\\n` 은 모델에게 보내 놓고 *"그대로 둬라"* 고
    **부탁만** 했다. 부탁은 보장이 아니다 — 가려서 보내고 되돌린다.
    """
    from app.jp import HOLE, mask, unmask

    for 원문, 가릴것 in [
        ("「……ほ、本当だな？[r]", ["[r]"]),
        (r"%name%は「こんな……」と言った。\n", ["%name%", r"\n"]),
        ("本当に<r>そうなのか？", ["<r>"]),
        ('[ruby text="りんこ"]凜子[endruby]が来た！', ["[endruby]"]),
    ]:
        가린것, 보관 = mask(원문)
        assert 보관 == 가릴것, (원문, 보관)
        for x in 가릴것:
            assert x not in 가린것, f"{x} 가 모델에게 그대로 간다"
        assert unmask(가린것, 보관) == 원문

    # **일본어가 든 덩어리는 안 가린다** — 그건 명령이 아니라 옮길 글이다
    assert mask("【対魔忍】秋山凜子　Ｈ１")[1] == []
    assert mask('[ruby text="りんこ"]')[1] == [], "일본어가 든 대괄호를 가렸다"

    # 모델이 표시를 지우거나 바꾸면 **되돌릴 수 없다** → 그 줄은 원문 유지
    assert unmask("표시가 사라진 번역", ["[r]"]) is None
    assert unmask(f"{HOLE}9{HOLE} 번호가 바뀜", ["[r]"]) is None


def test_기호가_잔뜩인_스크립트를_끝까지_돌려_본다():
    """가린 것 · 안 가린 것 · 안 보낸 것이 **한 파일에서 동시에** 맞아야 한다."""
    import asyncio
    import base64
    import json
    import os
    import re
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from app.server import api_translate

    바꿈 = {"本当だな": "정말이야", "こんな": "이런", "と言った": "라고 말했다",
           "が来た": "가 왔다", "対魔忍": "대마인", "秋山凜子": "아키야마 린코",
           "凜子": "린코", "は": "는"}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _s(self, o):
            b = json.dumps(o).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            self._s({"data": [{"id": "supergemma4-26b"}]})

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["content-length"])))
            본문 = req["messages"][-1]["content"]
            글 = 본문[0]["text"] if isinstance(본문, list) else 본문
            out = []
            for x in re.findall(r"^\d+\. (.*)$", 글, re.M):
                for a, b in 바꿈.items():
                    x = x.replace(a, b)
                out.append(x)
            # 진짜 Reasoning 모델처럼 생각과 군말을 붙여 돌려준다
            self._s({"choices": [{"message": {"content":
                     "<think>대사니까 반말로 [주의]</think>\n네:\n"
                     + json.dumps(out, ensure_ascii=False)}}]})

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["LM_BASE"] = f"http://127.0.0.1:{srv.server_port}/v1"
    try:
        원본 = ("<BGM_PLAY>bgm721,1000\r\n"
               "<NAME_PLATE>凜子\r\n"
               "//【対魔忍】秋山凜子　Ｈ１\r\n"
               "　「……ほ、本当だな？[r]\r\n"
               "\t%name%は「こんな……」と言った。\\n\r\n"
               "@wait time=500\r\n")

        class F:
            filename = "script.txt"

            async def read(self):
                return 원본.encode("utf-8")

        d = asyncio.run(api_translate(F(), key="", enc="utf-8", where="local", model=""))
        out = base64.b64decode(d["b64"]).decode()
        assert (d["targets"], d["done"], d["failed"]) == (4, 4, 0), d
        assert out == ("<BGM_PLAY>bgm721,1000\r\n"          # 일본어 없음 — 안 보냄
                       "<NAME_PLATE>린코\r\n"                # 태그는 그대로
                       "//【대마인】아키야마 린코　Ｈ１\r\n"      # 【】· 전각공백 그대로
                       "　「……ほ、정말이야？[r]\r\n"           # 전각 들여쓰기 · [r] 그대로
                       "\t%name%는「이런……」라고 말했다。\\n\r\n"  # \t · %name% · \n 그대로
                       "@wait time=500\r\n"), repr(out)     # 일본어 없음 — 안 보냄
    finally:
        os.environ.pop("LM_BASE", None)
        srv.shutdown()
