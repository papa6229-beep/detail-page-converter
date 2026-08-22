"""일본어 스크립트 번역 — 상세페이지 변환기와 **아무 관계 없다.**

같은 앱 안에서 돌지만 코드가 안 섞인다. 여기서 무엇을 고쳐도 변환기 49개는
안 움직인다. 공용은 `llm.py` 하나뿐이다.

    txt 올리기 → 일본어 부분만 한국어로 → 같은 모양의 txt 내려받기

**모양을 지키는 것이 이 파일의 전부다.** 게임 스크립트는 줄 하나가 곧 명령이라,
줄이 하나 늘거나 태그가 한 글자 달라지면 안 돌아간다. 그래서 —

    자르기는 수학, 번역은 AI

어느 줄의 어디까지가 건드리면 안 되는 부분인지는 **여기서 정하고**, 모델에게는
번역할 글자만 보낸다. 모델은 태그도 들여쓰기도 못 본다.

    <BGM_PLAY>bgm721,1000          태그 · 일본어 없음 → 통째로 안 건드림
    <NAME_PLATE>凜子               태그는 그대로, `凜子` 만 번역
    //【対魔忍】秋山凜子　Ｈ１      `//` 는 그대로, 뒤만 번역
    「……ほ、本当だな？             통째로 번역
    　本当の本当に、こんな……」    앞의 전각 공백은 그대로, 뒤만 번역

**파일이 무슨 모양이든 상관하지 않는다.** 사장님 지시 —

    *"그냥 형태가 json형태건 어쨌건 txt파일이잖아..그러면 그냥 내용에서 나머지
    다 기호며 따옴표며 괄호며 띄어쓰기며 다 그대로 놔두고 (…) 일본어만 한국어로
    번역해서 교체하면 되는것을?"*

그래서 JSON 으로 읽고 다시 굽지 않는다. **글자 자리만 찾아서 바꾼다.** 대본이
한 줄짜리 JSON 덩어리로 와도 똑같이 돈다 —

    sceneData={"0001_1":{"SCRIPTS":{"PART1":{"SCRIPT":["<BGM_PLAY>bgm721,1000",…

`sceneData={` · `{` · `,` · `"SCRIPT"` 는 일본어가 없으니 손도 안 댄다. 따옴표
사이의 `<NAME_PLATE>凜子` 만 골라 `凜子` 를 옮긴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 히라가나 · 가타카나 · 한자 · 반각 가나. **이게 있어야 번역 대상이다.**
#: 전각 기호(`！？…「」　`)나 전각 숫자만 있는 줄은 번역할 것이 없다.
JP = re.compile(r"[぀-ゟ゠-ヿ㐀-䶿一-鿿ｦ-ﾟ]")

#: 줄 맨 앞의 `<TAG>`. 태그 이름은 영문·숫자·밑줄만 — 그래야 `「…」` 를 태그로
#: 잘못 보지 않는다.
TAG = re.compile(r"^(<[A-Za-z_][A-Za-z0-9_]*>)(.*)$", re.S)

#: 들여쓰기로 볼 것. **전각 공백(U+3000)이 핵심**이다 — 대사가 이어지는 줄은
#: 전부 이걸로 시작하고, 이게 사라지면 화면에서 줄이 어긋난다.
INDENT = re.compile(r"^([ \t　]*)(.*)$", re.S)

#: 화자 이름이 붙는 태그. 같은 이름이 파일 안에서 매번 달리 번역되면 안 되므로
#: **먼저 모아서 한 번에 정하고**, 나머지 줄을 옮길 때 그 표를 같이 보낸다.
NAME_TAGS = ("<NAME_PLATE>",)

#: 한 번에 보낼 줄 수. 너무 크면 답이 잘리고, 너무 작으면 앞뒤 맥락이 끊긴다.
CHUNK = 60

#: **내 컴퓨터 모델은 더 잘게 보낸다.** 이 일에서 제일 어려운 지시는 번역이
#: 아니라 *"받은 줄 수와 돌려주는 줄 수를 똑같이 하라"* 인데, 작은 모델일수록
#: 60줄을 세다가 틀린다. 개수가 틀리면 그 묶음은 통째로 원문으로 남는다
#: (`take` 가 `None` 을 돌려준다) — 잘게 보내면 틀려도 잃는 줄이 적다.
#:
#: ⚠️ **20 은 재 본 값이 아니다.** 사장님 컴퓨터의 젬마가 몇 B 짜리인지에 따라
#: 다르다. 원문 유지가 많이 나오면 줄이고, 하나도 안 나오면 올리시면 된다 —
#:
#:     JP_CHUNK=10   더 안전하게 (부르는 횟수가 늘어 느려짐)
#:     JP_CHUNK=40   더 빠르게 (개수 틀릴 위험 커짐)
CHUNK_LOCAL = 20

#: 내 컴퓨터에서 도는 서버 주소. LM Studio 화면의 `Reachable at` 그대로다.
#:
#: ⚠️ **`localhost` 가 아니라 `127.0.0.1` 이라야 한다.** 윈도우는 `localhost` 를
#: IPv6(`::1`)로 먼저 푸는데 LM Studio 는 IPv4 로만 듣는 일이 있다. 그러면
#: 서버가 멀쩡히 켜져 있는데 "안 켜져 있습니다" 가 뜬다. LM Studio 자신도
#: 화면에 `http://127.0.0.1:1234` 라고 적어 준다 — 적힌 대로 쓴다.
LOCAL_BASE = "http://127.0.0.1:1234/v1"

#: 내 컴퓨터 모델에 한 번에 달라고 할 최대 길이.
#:
#: ⚠️ **회사 API 의 8000 을 그대로 쓰면 안 된다.** 내 컴퓨터 서버는 한 요청이
#: 쓸 수 있는 문맥이 정해져 있다 — 사장님 LM Studio 로그에 `n_ctx_slot = 2048`
#: 이 찍혀 있었다(슬롯 4개로 쪼개져 하나당 2048). 그보다 큰 값을 달라고 하면
#: 서버가 거부하거나 답을 잘라 버린다.
#:
#: LM Studio 에서 Context Length 를 올리셨으면 이것도 올리시면 된다 —
#:
#:     JP_MAX_TOKENS=4000
LOCAL_MAX_TOKENS = 1600

#: 내려받을 때 고를 수 있는 인코딩. 원본이 무엇이든 한국어가 들어가므로
#: Shift-JIS 로는 돌려줄 수 없다.
ENCODINGS = ("utf-8", "utf-8-sig", "cp949")

#: 원본을 읽을 때 차례로 시도할 것. 게임 스크립트는 Shift-JIS 인 경우가 흔하다.
READ_ORDER = ("utf-8-sig", "utf-8", "cp932", "euc-jp", "cp949")

#: 번역에 쓸 OpenAI 모델. **여기가 값과 속도를 정하는 자리다.**
#:
#: 이 일은 어려운 추론이 아니다 — 일본어 한 줄을 한국어 한 줄로 옮기고, 받은
#: 개수만큼 JSON 배열로 돌려주면 된다. 그러니 제일 비싼 모델을 쓸 이유가 없다.
#: 대신 **개수를 맞추는 지시**를 잘 지켜야 해서, 제일 싼 등급도 곤란하다.
#: 그 사이가 `mini` 다.
#:
#: ⚠️ **값은 내가 재 본 것이 아니다.** 내가 아는 범위의 판단이고, 회사가 값이나
#: 모델을 바꾸면 틀린다. 바꾸실 때 코드를 안 고쳐도 되게 **환경변수로 연다** —
#:
#:     JP_MODEL=gpt-4.1        더 좋게 (비쌈)
#:     JP_MODEL=gpt-4.1-nano   더 싸게 (개수 안 맞을 위험 커짐)
#:
#: 클로드 키를 쓰시면 이 값은 안 쓰고 `llm.model_for` 의 기본 모델로 간다.
MODEL_OPENAI = "gpt-4.1-mini"


def model_for(key: str) -> str:
    """이 키로 번역할 때 쓸 모델. OpenAI 만 여기서 정하고 나머지는 기본값."""
    import os

    from . import llm

    if llm.provider_of(key) != llm.OPENAI:
        return ""      # 빈 값이면 `llm.build` 가 제 기본 모델을 쓴다
    return os.environ.get("JP_MODEL", "").strip() or MODEL_OPENAI


def local_base() -> str:
    """내 컴퓨터 서버 주소. `LM_BASE` 로 바꿀 수 있다(포트를 옮겼을 때)."""
    import os

    return os.environ.get("LM_BASE", "").strip() or LOCAL_BASE


def local_max_tokens() -> int:
    """내 컴퓨터 모델에 달라고 할 최대 길이. 근거는 `LOCAL_MAX_TOKENS` 위에."""
    import os

    n = os.environ.get("JP_MAX_TOKENS", "").strip()
    return int(n) if n.isdigit() and int(n) > 0 else LOCAL_MAX_TOKENS


def local_chunk() -> int:
    """내 컴퓨터 모델에 한 번에 보낼 줄 수. 근거는 `CHUNK_LOCAL` 위에."""
    import os

    n = os.environ.get("JP_CHUNK", "").strip()
    return int(n) if n.isdigit() and int(n) > 0 else CHUNK_LOCAL


def local_models(base: str = "", timeout: float = 4.0) -> list[str]:
    """LM Studio 에 **뭐가 올라와 있는지 물어본다.** 못 닿으면 빈 목록.

    사람이 모델 이름을 손으로 적게 하지 않는다 — 적게 하면 반드시 오타가 난다.
    LM Studio 는 OpenAI 와 같은 `/v1/models` 를 낸다.
    """
    import json as _json
    import urllib.error
    import urllib.request

    url = (base or local_base()).rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            got = _json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return []
    다 = [str(x.get("id")) for x in (got.get("data") or []) if x.get("id")]
    # 임베딩 모델은 채팅을 못 한다. 자동으로 고를 때 이게 걸리면 번역이 통째로
    # 실패하므로 **뒤로 민다** — 목록에는 남겨서 사장님이 보실 수 있게 한다.
    채팅 = [x for x in 다 if not re.search(r"embed", x, re.I)]
    return 채팅 + [x for x in 다 if x not in 채팅]


@dataclass
class Line:
    """한 줄을 셋으로 가른다 — 건드리지 않을 앞부분 · 번역할 몸통 · 줄끝."""

    head: str      #: `<TAG>` · `//` · 들여쓰기. 그대로 둔다
    body: str      #: 번역할 글자
    eol: str       #: `\r\n` · `\n` · 마지막 줄이면 빈 문자열

    @property
    def target(self) -> bool:
        return bool(JP.search(self.body))

    def with_body(self, text: str) -> str:
        return self.head + text + self.eol


def decode(raw: bytes) -> tuple[str, str]:
    """바이트 → `(글, 무슨 인코딩이었나)`. 못 읽으면 마지막에 손실 허용으로 연다."""
    for enc in READ_ORDER:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8(일부 깨짐)"


def encode(text: str, enc: str) -> tuple[bytes, int]:
    """글 → `(바이트, 그 인코딩으로 못 적은 글자 수)`.

    **브라우저에 맡기지 않는다.** `Blob` 은 charset 을 뭐라 적어 줘도 UTF-8 로만
    쓴다 — `cp949` 를 골라도 조용히 UTF-8 이 나간다.

    `cp949` 에 없는 글자(일부 한자·특수기호)는 `?` 가 되므로 **몇 자가 그렇게
    됐는지 세어서 돌려준다.** 조용히 뭉개면 어디가 깨졌는지 못 찾는다.
    """
    data = text.encode(enc, "replace")
    if data.decode(enc, "replace") == text:
        return data, 0
    잃음 = sum(1 for a, b in zip(text, data.decode(enc, "replace")) if a != b)
    return data, 잃음


def cut(line: str) -> Line:
    """한 줄을 가른다. **줄끝을 먼저 떼어 낸다** — 안 그러면 `\\r` 이 번역에 딸려 간다.

    ⚠️ **`「` 와 `」` 도 몸통에서 떼어 낸다 — 모델에게 안 보낸다.**

    실물에서 모델이 이걸 지웠다. 사장님 파일을 돌려 받은 결과 —

        옮긴 153군데 중 「 」 가 사라진 곳 30군데
        원본 「120 」120  →  받은 것 「105 」104

        원본: 尻孔で感じられるようになったぞ？」
        받음: 항문으로 느낄 수 있게 되었다고?      ← 」 가 없어졌다

    *"기호는 그대로 둬라"* 고 **부탁만** 하고 있었다. 부탁은 보장이 아니다.
    게다가 `「 」` 는 우리가 옮길 곳을 고르는 기준이라(`targets`), 사라지면 다시
    돌려도 그 줄은 영영 안 잡힌다. 안 보내면 못 지운다.
    """
    m = re.match(r"^(.*?)(\r\n|\n|\r|)$", line, re.S)
    text, eol = m.group(1), m.group(2)

    t = TAG.match(text)
    if t:
        head, body = t.group(1), t.group(2)
    elif text.startswith("//"):
        head, body = "//", text[2:]
    else:
        ind = INDENT.match(text)
        head, body = ind.group(1), ind.group(2)

    if body.startswith("「"):
        head, body = head + "「", body[1:]
    if body.endswith("」"):
        body, eol = body[:-1], "」" + eol
    return Line(head, body, eol)


#: 줄 **안쪽**에 박혀 있는 명령·변수·이스케이프. 일본어가 한 글자도 없는
#: 덩어리만 고른다 — 있으면 그건 명령이 아니라 옮길 글이다.
#:
#:     [r] [endruby] [wait 500]     대괄호 명령
#:     <r> <br>                     꺾쇠 명령 (줄 맨 앞 태그는 `TAG` 가 이미 뗐다)
#:     %name% %hero%                변수
#:     \n \t                        이스케이프
#:
#: ⚠️ **이걸 안 가리면 모델이 고친다.** `[r]` 을 `[줄바꿈]` 으로 옮기거나 `%name%`
#: 을 지워 버리면 스크립트가 안 돈다. 그런데 지금까지는 *"기호는 그대로 둬라"* 고
#: **부탁만** 하고 있었다. 부탁은 보장이 아니다 — 가려서 보내고 되돌린다.
INLINE = re.compile(
    r"\\[a-zA-Z]"
    r"|\[[^\[\]]*\]"
    r"|<[^<>]*>"
    r"|%[^%\s]*%"
)

#: 가린 자리에 대신 넣을 표시. **일본어에도 한국어에도 없는 글자**라야 모델이
#: 번역하려 들지 않는다. `\ue000` 부터는 사용자 정의 영역이라 어느 글꼴에도 없다.
HOLE = "\ue000"


def mask(body: str) -> tuple[str, list[str]]:
    """줄 안쪽 명령을 가린다 → `(가린 글, 가린 것들)`.

    일본어가 든 덩어리는 안 가린다 — `【対魔忍】` 같은 것은 옮길 글이다.
    """
    보관: list[str] = []

    def 바꾸기(m: re.Match) -> str:
        if JP.search(m.group(0)):
            return m.group(0)      # 일본어가 들었다 = 명령이 아니라 글이다
        보관.append(m.group(0))
        return f"{HOLE}{len(보관)}{HOLE}"

    return INLINE.sub(바꾸기, body), 보관


def unmask(text: str, 보관: list[str]) -> str | None:
    """가린 것을 되돌린다. **하나라도 사라졌으면 `None`.**

    모델이 표시를 지우거나 번호를 바꿔 놓으면 되돌릴 수가 없다. 그때는 그 줄을
    **원문 그대로** 남긴다 — 명령이 빠진 스크립트는 안 도는 것이라 반쯤 옮긴
    것보다 원문이 낫다.
    """
    if not 보관:
        return text
    남은 = text
    for i, 원래 in enumerate(보관, 1):
        표시 = f"{HOLE}{i}{HOLE}"
        if 표시 not in 남은:
            return None
        남은 = 남은.replace(표시, 원래, 1)
    return None if HOLE in 남은 else 남은


#: 토막을 끊는 자리 — **따옴표와 줄바꿈.** 이 두 글자는 어느 파일에서든 "여기서
#: 한 덩이가 끝난다" 는 뜻이라, 이걸 넘어가서 옮기면 파일이 깨진다.
#:
#: 줄로 나뉜 보통 txt 는 줄바꿈이 끊고, 한 줄짜리 JSON 덩어리는 따옴표가 끊는다.
#: **파일 모양을 알아볼 필요가 없다** — 같은 규칙 하나로 둘 다 된다.
가름 = re.compile(r'(["\r\n]+)')


def parse(text: str) -> list[Line]:
    """글 한 덩이 → 토막 목록. **이어 붙이면 원문 그대로**여야 한다.

    따옴표·줄바꿈으로 끊고, 끊는 글자 자체도 토막 하나로 남겨 둔다. 그래야
    되붙였을 때 한 글자도 안 어긋난다.

        sceneData={   "   <NAME_PLATE>凜子   "   ,   "   <PAUSE>   "   …
        └ 안 건드림 ─┘ ↑  └ 여기만 옮김 ──┘  ↑ └ 안 건드림 ─────────┘
                     끊는 글자도 그대로

    ⚠️ **따옴표를 넘어가면 안 된다.** 대사가 두 토막에 걸쳐 있어도 각각 옮긴다 —

        "「……ほ、本当だな？","本当の本当に、こんな……コトでッ！？」"
                            ↑ 이 `","` 는 그대로 놔둔다. 넘어가서 옮기면 깨진다.
    """
    out = [
        Line(조각, "", "") if i % 2 else cut(조각)
        for i, 조각 in enumerate(가름.split(text))
        if i % 2 or 조각
    ]
    return out or [cut("")]


def targets(lines: list[Line]) -> list[int]:
    """옮길 토막의 자리 번호 — **일본어가 든 것 전부.**

    사장님 지시 — *"다시 규칙을 바꾸자 일본어부분 전체로"*

    그래서 대사도 지문도 화자 이름도 다 옮긴다. `「 」` 를 안 따진다.

        "<NAME_PLATE>凜子"                    ← 옮김
        "緊張しているせいか、目の前で…"        ← 옮김
        "「……ほ、本当だな？"                  ← 옮김
        "<BGM_PLAY>bgm721,1000"               ← 일본어 없음 · 안 건드림

    규칙이 한 줄이다 — **일본어가 들었으면 옮기고, 아니면 놔둔다.**
    """
    return [i for i, ln in enumerate(lines) if ln.target]


def names(lines: list[Line]) -> list[str]:
    """화자 이름을 나온 차례대로, 중복 없이."""
    out: list[str] = []
    for ln in lines:
        if ln.head in NAME_TAGS and ln.target and ln.body not in out:
            out.append(ln.body)
    return out


def build(lines: list[Line], done: dict[int, str]) -> str:
    """번역된 몸통을 제자리에 끼워 되붙인다. 없는 줄은 원문 그대로."""
    return "".join(
        ln.with_body(done.get(i, ln.body)) for i, ln in enumerate(lines)
    )


NAME_PROMPT = """일본어 게임 스크립트에 나오는 화자 이름이다. 한국어로 옮겨라.

- 사람 이름은 **소리 나는 대로** 적는다 (凜子 → 린코, 秋山 → 아키야마).
- 이름이 아니라 대명사·역할이면 뜻으로 옮긴다 (俺 → 나, 女性 → 여자).
- 받은 개수와 돌려주는 개수가 **같아야 한다.** 순서도 그대로.

JSON 배열 하나만 출력하라. 설명도 코드펜스도 붙이지 마라."""

LINE_PROMPT = """일본어 게임 스크립트를 한국어로 옮긴다. **한 줄씩** 옮긴다.

- 받은 줄 수와 돌려주는 줄 수가 **반드시 같아야 한다.** 줄을 합치거나 나누지 마라.
- `「」『』（）…… ！？・` 같은 기호는 **있던 자리에 그대로** 둔다. 한국어 기호로 바꾸지 마라.
- 뜻을 알 수 없는 글자( 로 시작하고 끝나는 것)가 섞여 있으면 **그 자리에 그대로**
  두어라. 지우지도, 옮기지도, 자리를 바꾸지도 마라. 우리가 나중에 되돌린다.
- 한 줄이 문장 중간에서 끊겨 있어도 **그 줄만 옮긴다.** 다음 줄과 합쳐 읽되, 옮긴 것은
  그 줄 몫만 돌려준다.
- 이름은 아래 표를 그대로 쓴다. 표에 없는 이름만 새로 옮긴다.
- 말투는 원문을 따른다. 반말이면 반말, 존대면 존대.
- 없는 말을 보태지 마라. 설명을 덧붙이지 마라.

JSON 배열 하나만 출력하라. 설명도 코드펜스도 붙이지 마라."""


def name_parts(items: list[str]) -> list[tuple[str, str]]:
    """이름 표를 만들기 위한 한 번의 요청."""
    번호 = "\n".join(f"{i + 1}. {x}" for i, x in enumerate(items))
    return [("system", NAME_PROMPT), ("text", 번호)]


def line_parts(items: list[str], table: dict[str, str]) -> list[tuple[str, str]]:
    """줄 묶음 하나를 옮기기 위한 요청. 이름 표를 같이 보낸다."""
    표 = "\n".join(f"{a} → {b}" for a, b in table.items())
    번호 = "\n".join(f"{i + 1}. {x}" for i, x in enumerate(items))
    head = (f"[이름 표]\n{표}\n\n" if 표 else "") + f"[옮길 줄 {len(items)}개]\n{번호}"
    return [("system", LINE_PROMPT), ("text", head)]


#: 생각을 먼저 적고 답을 내놓는 모델들이 쓰는 표시. 그 안은 답이 아니다.
#: (`supergemma4` 처럼 Reasoning 이 붙은 모델이 이렇게 낸다)
THINK = re.compile(r"<(think|thinking|reasoning)>[\s\S]*?</\1>", re.I)


def take(reply: str, n: int) -> list[str] | None:
    """답에서 문자열 배열을 꺼낸다. **개수가 안 맞으면 `None`** — 반만 쓰면 줄이 밀린다.

    줄이 밀리면 대사가 다른 화자에게 붙는다. 그건 못 쓰는 결과물이라,
    부르는 쪽이 이것을 받아 그 묶음을 **원문 그대로** 남긴다.

    ⚠️ **내 컴퓨터 모델은 답 앞뒤에 군말을 붙인다.** 회사 API 는 시키면 JSON 만
    내놓는데, 로컬 모델은 생각을 먼저 적거나(`<think>…</think>`) *"네, 옮겼습니다:"*
    같은 말을 붙인다. 그래서 —

        ① `<think>` 덩어리를 먼저 걷어낸다
        ② 코드펜스를 벗긴다
        ③ **괄호를 세어 가며 진짜 배열을 찾는다.** 예전에는 첫 `[` 부터 마지막
           `]` 까지를 통째로 집었는데, 군말에 대괄호가 하나라도 있으면 엉뚱한
           덩어리를 집어 통째로 실패했다.
    """
    import json

    s = THINK.sub("", reply or "")
    s = re.sub(r"^\s*```(?:json)?", "", s, flags=re.I)
    s = re.sub(r"```\s*$", "", s).strip()

    후보: list[list] = []
    for i, ch in enumerate(s):
        if ch != "[":
            continue
        깊이 = 0
        for j in range(i, len(s)):
            if s[j] == "[":
                깊이 += 1
            elif s[j] == "]":
                깊이 -= 1
                if 깊이 == 0:
                    try:
                        got = json.loads(s[i : j + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(got, list) and len(got) == n:
                        후보.append(got)
                    break
    if not 후보:
        return None
    # 개수가 맞는 것이 여럿이면 **글자로 된 것**을 고른다 — 군말 속의 `[1]` 같은
    # 것이 개수만 우연히 맞는 일이 있다. 그것도 여럿이면 뒤엣것(진짜 답)을 쓴다.
    글자만 = [x for x in 후보 if all(isinstance(v, str) for v in x)]
    고름 = (글자만 or 후보)[-1]
    return [str(x) for x in 고름]
