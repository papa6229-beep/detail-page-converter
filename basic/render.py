"""860px 한 줄 세로 배치. 섹션마다 같은 구조."""
from __future__ import annotations

import base64
import html
import re
from pathlib import Path

from .body import BODY, IMAGES, SIDE, Section

CSS = """
.bpage{max-width:860px;margin:0 auto;font-family:Pretendard,-apple-system,'Malgun Gothic',sans-serif;color:#2b2f3a;-webkit-font-smoothing:antialiased}
.bpage *{box-sizing:border-box;margin:0}
.bpage .sec{padding:56px 24px 48px;border-top:1px solid #e6e8ee}
.bpage .sec:first-child{border-top:0}
.bpage .no{font-size:13px;font-weight:800;letter-spacing:.22em;color:#1a2440;opacity:.55}
.bpage h2{font-size:28px;font-weight:800;letter-spacing:-.02em;color:#1a2440;margin:8px 0 22px;line-height:1.25}
.bpage figure{margin:0 0 18px;text-align:center}
.bpage figure img{max-width:100%;height:auto;display:inline-block}
/* 사진 옆 흰 바탕에 붙어 있던 글을 떼어 여기로 옮긴다. 원본에서 그 글은 사진에
   딸린 설명이었으니 본문 문단으로 세우지 않고 사진 아래에 붙여 둔다. */
.bpage figcaption{text-align:left;margin-top:10px}
.bpage figcaption p{font-size:15px;line-height:1.75;color:#4a5063;margin:0 0 6px}
.bpage p{font-size:16px;line-height:1.9;margin:6px 0 14px}
.bpage p+p{margin-top:0}
.bpage strong{font-weight:800;color:#1a2440}
/* 못 읽은 글은 **원본 밴드를 그대로** 싣는다. 예전에는 점선 네모에 담았는데,
   본문 곳곳에 네모 테두리가 떠서 디자인이 깨져 보인다는 말을 계속 들었다.
   테두리는 우리가 그린 것이지 원본에 있던 것이 아니다. */
.bpage .asis{display:block;max-width:100%;margin:0 auto 18px}
.bpage .whole{display:block;max-width:100%;margin:0 auto}
"""


def _uri(path: Path) -> str:
    ext = path.suffix.lstrip(".").lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def _emph(text: str) -> str:
    """`**강조**` → <strong>. 나머지는 이스케이프."""
    parts = re.split(r"(\*\*.+?\*\*)", text)
    out = []
    for p in parts:
        if p.startswith("**") and p.endswith("**"):
            out.append("<strong>" + html.escape(p[2:-2]) + "</strong>")
        else:
            out.append(html.escape(p))
    return "".join(out)


def _paras(text: str) -> str:
    """빈 줄로 문단을 가른다.

    문단 **안**의 줄바꿈은 `<br>` 로 살린다. 사진 폭에 맞춘 줄바꿈은 뜻이 없지만,
    표처럼 항목이 나열된 글(`A타입 길이 10cm / B타입 …`)은 줄이 곧 뜻이다.
    한 줄로 붙이면 어느 값이 어느 옵션인지 알 수 없게 된다.
    """
    out = []
    for chunk in re.split(r"\n\s*\n", text.strip()):
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        if lines:
            out.append("<p>" + "<br>".join(_emph(ln) for ln in lines) + "</p>")
    return "".join(out)


def render(secs: list[Section], assets: Path, embed: bool = True) -> str:
    """섹션들을 HTML 로. **놓기만 한다** — 무엇인지는 이미 정해져 왔다."""
    def src(name: str) -> str:
        return _uri(assets / name) if embed else name

    def as_is(p, cls: str = "asis") -> str:
        """글을 못 받았으면 원본 밴드를 그대로 싣는다."""
        return f'<img class="{cls}" src="{src(p.file)}" alt="">' if p.file else ""

    out = [f"<style>{CSS}</style>", '<div class="bpage">']
    for s in secs:
        out.append('<section class="sec">')
        out.append(f'<div class="no">{s.number:02d}</div>')
        if s.title is not None:
            out.append(f"<h2>{_emph(s.title.text.strip())}</h2>" if s.title.text.strip()
                       else as_is(s.title))
        for it in s.items:
            if it.kind in IMAGES:
                cap = (f"<figcaption>{_paras(it.text)}</figcaption>"
                       if it.kind == SIDE and it.text.strip() else "")
                out.append(f'<figure><img src="{src(it.file)}" alt="">{cap}</figure>')
            elif it.kind == BODY:
                out.append(_paras(it.text) if it.text.strip() else as_is(it))
        out.append("</section>")
    out.append("</div>")
    return "\n".join(x for x in out if x)


def render_whole(files: list[Path]) -> str:
    """본문을 **자르지 않고** 원본 이미지 그대로 싣는다.

    글자 박힌 사진이 본문의 대부분인 원본은 디자이너가 사진과 글을 한 덩어리로
    짜 놓은 것이다. 밴드로 갈라 다시 세우면 얻는 것보다 잃는 것이 많다.
    """
    out = [f"<style>{CSS}</style>", '<div class="bpage">', '<section class="sec">']
    out += [f'<img class="whole" src="{_uri(f)}" alt="">' for f in files]
    out += ["</section>", "</div>"]
    return "\n".join(out)
