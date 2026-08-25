"""860px 한 줄 세로 배치. 섹션마다 같은 구조."""
from __future__ import annotations

import base64
import html
import re
from pathlib import Path

from .body import BODY, PHOTO, SUB, Section

CSS = """
.bpage{max-width:860px;margin:0 auto;font-family:Pretendard,-apple-system,'Malgun Gothic',sans-serif;color:#2b2f3a;-webkit-font-smoothing:antialiased}
.bpage *{box-sizing:border-box;margin:0}
.bpage .sec{padding:56px 24px 48px;border-top:1px solid #e6e8ee}
.bpage .sec:first-child{border-top:0}
.bpage .no{font-size:13px;font-weight:800;letter-spacing:.22em;color:#1a2440;opacity:.55}
.bpage h2{font-size:28px;font-weight:800;letter-spacing:-.02em;color:#1a2440;margin:8px 0 22px;line-height:1.25}
.bpage h3{font-size:19px;font-weight:800;letter-spacing:-.01em;color:#1a2440;margin:26px 0 10px;line-height:1.35}
.bpage h3:first-child{margin-top:0}
.bpage figure{margin:0 0 18px;text-align:center}
.bpage figure img{max-width:100%;height:auto;display:inline-block}
.bpage figcaption{text-align:left;max-width:640px;margin:10px auto 0;font-size:14.5px;line-height:1.75;color:#4a4f5c}
.bpage p{font-size:16px;line-height:1.9;margin:6px 0 14px}
.bpage p+p{margin-top:0}
.bpage strong{font-weight:800;color:#1a2440}
/* 못 읽은 글자 조각은 **그림 그대로** 보여준다. 예전엔 점선 상자에 담았는데,
   본문 곳곳에 네모 테두리가 떠서 디자인이 깨져 보인다는 말을 계속 들었다.
   테두리는 우리가 그린 것이지 원본에 있던 것이 아니다. */
.bpage .unread{display:block;max-width:100%}
.bpage .unread img{max-width:100%;display:block}
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
    """빈 줄로 문단을 가른다. 문단 안의 줄바꿈은 붙인다(사진 폭에 맞춘 줄바꿈은 뜻이 없다)."""
    paras = [re.sub(r"\s*\n\s*", " ", t).strip() for t in re.split(r"\n\s*\n", text.strip())]
    return "".join(f"<p>{_emph(t)}</p>" for t in paras if t)


def _text_or_crop(piece, assets: Path, tag: str = "p") -> str:
    if piece.text.strip():
        return _paras(piece.text) if tag == "p" else _emph(piece.text.strip())
    if piece.crop:
        return f'<span class="unread" title="읽기 전 — 원본 글자 조각"><img src="{_uri(assets / piece.crop)}"></span>'
    return ""


def render(secs: list[Section], assets: Path, embed: bool = True) -> str:
    def src(name: str) -> str:
        return _uri(assets / name) if embed else name

    out = [f'<style>{CSS}</style>', '<div class="bpage">']
    for s in secs:
        out.append('<section class="sec">')
        out.append(f'<div class="no">{s.number:02d}</div>')
        if s.title:
            t = _text_or_crop(s.title, assets, tag="h2")
            out.append(f"<h2>{t}</h2>")
        for it in s.items:
            if it.kind == PHOTO:
                cap = ""
                if it.crop:
                    cap = f"<figcaption>{_text_or_crop(it, assets)}</figcaption>"
                out.append(f'<figure><img src="{src(it.file)}" alt="">{cap}</figure>')
            elif it.kind == SUB:
                # 섹션을 못 연 제목. 층을 지키려고 h3 로 들어간다 (body.sections 참고).
                out.append(f"<h3>{_text_or_crop(it, assets, tag='h3')}</h3>")
            elif it.kind == BODY:
                out.append(_text_or_crop(it, assets))
        out.append("</section>")
    out.append("</div>")
    return "\n".join(out)
