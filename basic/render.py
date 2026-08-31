"""860px 한 줄 세로 배치. 섹션마다 같은 구조."""
from __future__ import annotations

import base64
import html
import re
from pathlib import Path

from .body import BODY, IMAGES, Section

CSS = """
.bpage{max-width:860px;margin:0 auto;font-family:Pretendard,-apple-system,'Malgun Gothic',sans-serif;color:#2b2f3a;-webkit-font-smoothing:antialiased}
.bpage *{box-sizing:border-box;margin:0}
.bpage .sec{padding:56px 24px 48px;border-top:1px solid #e6e8ee}
.bpage .sec:first-child{border-top:0}
.bpage .no{font-size:13px;font-weight:800;letter-spacing:.22em;color:#1a2440;opacity:.55}
.bpage h2{font-size:28px;font-weight:800;letter-spacing:-.02em;color:#1a2440;margin:8px 0 22px;line-height:1.25}
.bpage figure{margin:0 0 18px;text-align:center}
.bpage figure img{max-width:100%;height:auto;display:inline-block}
/* 사진에서 덮은 자리에 그 글을 우리 폰트로 다시 쓴다. 자리는 덮을 때 적어 둔
   상자 그대로고, 글자 크기는 **원본 글자의 실제 높이**다 — 상자에 꽉 채우면
   원본보다 커져서 아래 줄과 겹친다. `cqw` 는 좁은 화면에서 같이 줄어들라고 얹는다. */
.bpage .lay{position:relative;display:inline-block;max-width:100%;container-type:inline-size}
.bpage .lay img{width:100%}
.bpage .lay .mk{position:absolute;margin:0;text-align:left;line-height:1.35;
  color:#2b2f3a;white-space:pre-wrap;overflow-wrap:break-word}
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



#: 한글 글자는 제 크기의 이만큼만 잉크로 채운다. 잰 잉크 높이를 이것으로 나눠야
#: 원본과 같은 크기로 앉는다. 잉크 높이를 그대로 쓰면 눈에 띄게 작아진다.
INK_FILL = 0.72
#: 글자 하나가 차지하는 폭을 글자 크기의 몇 배로 볼까. 한글은 네모라 1, 로마자는 좁다.
WIDE, NARROW = 1.0, 0.55


def _em(text: str) -> float:
    """가장 긴 줄이 글자 크기의 몇 배로 뻗는가."""
    lines = text.splitlines() or [""]
    return max(sum(WIDE if ord(c) > 0x2000 else NARROW for c in ln) for ln in lines) or 1.0


def fit(mark) -> float:
    """덮은 자리에 다시 쓸 **글자 크기(px)**.

    **폭이 답이다** — 상자 폭을 글자 수로 나눈 것이 원본 글자 크기다. 잉크 높이는
    위쪽 상한으로만 쓴다. 높이만 보면 밑줄이 글자에 붙은 줄에서 두 배가 나온다
    (실측: 폭으로 16px, 높이로 36px, 원본은 16px).
    """
    lines = len(mark.text.splitlines()) or 1
    tall = (mark.ink or mark.h) / INK_FILL
    return max(1.0, min(mark.w / _em(mark.text) * lines, tall))


def _size(path: Path):
    """그림의 픽셀 크기. 못 열면 None — 그러면 글은 안 쓰고 원본만 싣는다."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


def _shot(piece, url: str, assets: Path) -> str:
    """사진 하나. 덮은 자리가 있으면 **그 자리에 그 글을 다시 쓴다.**"""
    plain = f'<img src="{url}" alt="">'
    size = _size(assets / piece.file) if piece.marks else None
    if not size:
        return plain
    w, h = size
    # 폭을 **바깥에서** 준다. `container-type` 은 안쪽 내용에서 폭을 못 받아,
    # 안 주면 상자가 0px 이 되고 `cqw` 로 잰 글자가 0px 이 된다.
    out = [f'<span class="lay" style="width:{w}px">{plain}']
    for m in piece.marks:
        f = fit(m)
        out.append(f'<p class="mk" style="left:{m.x / w * 100:.2f}%;'
                   f'top:{m.y / h * 100:.2f}%;width:{m.w / w * 100:.2f}%;'
                   f'font-size:{f:.1f}px;font-size:{f / w * 100:.2f}cqw">'
                   f"{_emph(m.text)}</p>")
    return "".join(out) + "</span>"


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
                out.append(f"<figure>{_shot(it, src(it.file), assets)}</figure>")
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
