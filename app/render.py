"""렌더러 — DESIGN.md 6장. 폭 800px.

조건부 섹션 골격이다. 없는 것은 그리지 않는다. 판정하지 않고 **세기만 한다** —
옵션 태그가 붙은 유닛이 있으면 옵션 가이드가 생기고, 없으면 안 생긴다.
반복문이 0번 도는 것이지 예외가 아니다 (3장).

    ① 히어로        항상
    ② 스펙 요약     스펙 있을 때
    ③ 리드 문단     카피 있을 때
    ④ 옵션 가이드   옵션 태그 붙은 유닛이 있을 때   ← 검은 밴드
    ⑤ 광고컷        캡션 없는 통짜 이미지가 있을 때
    ⑥ 디테일        캡션 붙은 유닛
    ⑦ 푸터          항상
"""

from __future__ import annotations

import base64
import html
import re
from pathlib import Path

WIDTH = 800

#: 옵션 칩 색. 원본에서 뽑을 수 없을 때만 쓰는 예비값이다.
FALLBACK_CHIPS = ["#519FAA", "#C2594D", "#8BB93E", "#DB7568", "#1567B1", "#916E53"]


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _plain(text: str) -> str:
    """alt 속성에는 별표를 남기지 않는다."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", str(text or ""))


def emphasize(text: str) -> str:
    """`**여기**` 로 표시된 곳을 강조로 바꾼다.

    원본의 노란 형광펜을 그대로 옮기지 않는다. 그건 원본 쇼핑몰의 디자인이고,
    우리는 같은 자리를 우리 색으로 다시 칠한다.
    """
    out = esc(text)
    return re.sub(r"\*\*(.+?)\*\*", r'<b class="em">\1</b>', out)


def data_uri(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def chip_color(path: Path, fallback: str) -> str:
    """조각에서 가장 튀는 색을 뽑아 칩으로 쓴다.

    임의로 고른 색을 쓰지 않는다. 텐가의 여섯 칩은 전부 실제 EGG 캡에서 나왔다.
    """
    try:
        import numpy as np
        from PIL import Image

        a = np.asarray(Image.open(path).convert("RGB").resize((64, 64))).reshape(-1, 3).astype(int)
        mx, mn = a.max(1), a.min(1)
        sat = mx - mn
        good = sat > 60
        if good.sum() < 24:
            return fallback
        pick = a[good][np.argsort(sat[good])[-good.sum() // 4 :]].mean(0).astype(int)
        return "#%02X%02X%02X" % tuple(pick)
    except Exception:
        return fallback


CSS = """
:root{--ground:#FFFFFF;--ink:#16110F;--muted:#78706C;--rule:#E8E2DF;--accent:#D0020F;
 --plate:#F4F0EE;--plate-soft:#FBF9F8;--band:#0C0A09;--band-ink:#F3EFED;--band-muted:#9A918D}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --ground:#121010;--ink:#F2EDEB;--muted:#9C938F;--rule:#2E2A28;--accent:#FF4757;
 --plate:#EFEBE9;--plate-soft:#171414;--band:#000000;--band-ink:#F3EFED;--band-muted:#8E8481}}
:root[data-theme="dark"]{--ground:#121010;--ink:#F2EDEB;--muted:#9C938F;--rule:#2E2A28;
 --accent:#FF4757;--plate:#EFEBE9;--plate-soft:#171414;--band:#000000;--band-ink:#F3EFED;--band-muted:#8E8481}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
 font-family:"Pretendard","Pretendard Variable",-apple-system,BlinkMacSystemFont,
 "Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",system-ui,sans-serif;
 -webkit-font-smoothing:antialiased;
 word-break:keep-all;overflow-wrap:break-word}
img{display:block;width:100%;height:auto}
p{margin:0}
.page{width:800px;max-width:100%;margin:0 auto}
.label{font-size:13px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);margin:0}
.em{color:var(--accent);font-weight:800}
.band .em{color:#FF6B76}
.hero{padding:72px 40px 32px;border-bottom:1px solid var(--rule)}
.hero__brand{color:var(--accent)}
.hero__title{margin:18px 0 0;font-size:48px;line-height:1.04;font-weight:800;letter-spacing:-.035em;text-wrap:balance}
.hero__title em{font-style:normal;display:block;color:var(--muted);font-weight:700;font-size:.55em;margin-top:8px}
.hero__lead{margin-top:20px;max-width:34em;font-size:16px;line-height:1.8;color:var(--muted)}
.hero__shot{margin:36px 0 0;background:var(--plate)}
.specs{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));border-bottom:1px solid var(--rule)}
.spec{padding:28px 0 30px 24px;border-left:1px solid var(--rule)}
.spec:first-child{border-left:0;padding-left:40px}
.spec__k{font-size:13px;font-weight:700;letter-spacing:.1em;color:var(--muted)}
.spec__v{margin-top:10px;font-size:38px;font-weight:800;letter-spacing:-.03em;font-variant-numeric:tabular-nums;line-height:1}
.spec__u{font-size:16px;font-weight:700;color:var(--muted);margin-left:4px}
.intro{padding:52px 40px 8px}
.intro__tag{margin-top:6px;font-size:31px;line-height:1.35;font-weight:800;letter-spacing:-.03em;text-wrap:balance}
.intro__p{margin-top:16px;font-size:17px;line-height:1.9;color:var(--muted);max-width:38em}
.lead{padding:44px 40px 56px}
.lead__text{font-size:20px;line-height:1.78;font-weight:500;max-width:31em;text-wrap:pretty}
.band{background:var(--band);color:var(--band-ink);padding:64px 40px 68px}
.band .label{color:var(--band-muted)}
.band__title{margin:16px 0 0;font-size:44px;font-weight:800;letter-spacing:-.035em;line-height:1.1}
.band__note{margin-top:14px;font-size:16px;line-height:1.7;color:var(--band-muted);max-width:36em}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:36px 22px;margin-top:44px}
.grid--wide{grid-template-columns:repeat(2,1fr)}
.variant__fig{margin:0;background:#000}
.variant__name{margin-top:16px;font-size:17px;font-weight:800;letter-spacing:-.01em;
 display:flex;align-items:center;gap:8px}
.variant__chip{width:11px;height:11px;border-radius:50%;background:var(--chip);flex:none;
 box-shadow:0 0 0 3px color-mix(in srgb,var(--chip) 22%,transparent)}
.variant__body{margin-top:12px;font-size:14px;line-height:1.75;color:var(--band-muted)}
.showcase{padding:60px 40px 0}
.showcase__shot{margin:24px 0 0;background:var(--plate)}
.features{padding:56px 40px 72px}
.features__title{margin:16px 0 40px;font-size:44px;font-weight:800;letter-spacing:-.035em;line-height:1.1}
.feature__solo{margin:0 0 24px;background:var(--plate)}
.feature{display:grid;grid-template-columns:320px 1fr;gap:36px;align-items:center;
 padding:34px 0;border-top:1px solid var(--rule)}
.feature--flip{grid-template-columns:1fr 320px}
.feature--flip .feature__fig{order:2}
.feature__fig{margin:0;background:var(--plate)}
.feature__head{margin:0;font-size:22px;line-height:1.35;font-weight:800;letter-spacing:-.02em;text-wrap:balance}
.feature__body{margin-top:14px;font-size:16px;line-height:1.85;color:var(--muted)}
.feature__body--solo{margin-top:0;font-size:17px;color:var(--ink);font-weight:500}
.foot{border-top:1px solid var(--rule);padding:56px 40px 64px;background:var(--plate-soft)}
.foot__row{display:grid;grid-template-columns:repeat(3,1fr);gap:30px;margin-top:28px}
.foot__h{font-size:16px;font-weight:800;letter-spacing:-.01em}
.foot__p{margin-top:10px;font-size:14px;line-height:1.8;color:var(--muted)}
@media (max-width:800px){
 .page{width:100%}
 .hero{padding:52px 22px 26px}.hero__title{font-size:34px}
 .spec,.spec:first-child{padding-left:22px}
 .intro,.lead,.band,.showcase,.features,.foot{padding-inline:22px}
 .intro__tag{font-size:23px}
 .band__title,.features__title,.compare__title{font-size:31px}
 .spec__v{font-size:30px}
 .grid,.grid--wide{grid-template-columns:repeat(2,1fr)}
 .feature,.feature--flip{grid-template-columns:1fr;gap:18px}
 .feature--flip .feature__fig{order:0}
 .foot__row{grid-template-columns:1fr}}
"""

#: 공통 푸터 (6.1 ⑦). **상품마다 달라지는 말을 여기 두면 안 된다.**
#: 처음엔 "겉면 절취선을 따라 필름을 제거한 뒤"라고 적어 뒀는데, 그건 텐가에만
#: 맞는 말이라 다른 1000개에 붙으면 전부 거짓이 된다. 어느 상품에나 참인 말만 둔다.
#: 쇼핑몰 정책이 정해지면 이 표를 그 문구로 갈아끼우면 된다.
FOOTER = [
    ("보관", "직사광선과 고온다습한 곳을 피해 서늘한 곳에 보관하세요."),
    ("위생", "개봉 후에는 위생상 교환·반품이 어렵습니다. 받으신 즉시 상태를 확인해 주세요."),
    ("주의", "성인용 제품입니다. 손상되거나 변형된 제품은 사용하지 마세요."),
]


def split_lead(lead: str) -> tuple[str, str]:
    """리드를 히어로용 첫 문장과 나머지로 가른다."""
    text = (lead or "").strip()
    if not text:
        return "", ""
    m = re.search(r"^(.{6,90}?[.。])\s+(.+)$", text, re.S)
    return (m.group(1).strip(), m.group(2).strip()) if m else (text, "")


def _squeeze(name: str, blocks):
    """제목과 같은 줄은 뺀다. 같은 말을 두 번 싣지 않는다."""
    key = re.sub(r"[\s\[\]()]", "", (name or "")).lower()
    out = []
    for b in blocks:
        text = re.sub(r"[\s\[\]()]", "", b.text).lower()
        if key and (text == key or (len(text) >= 4 and text in key) or (len(key) >= 4 and key in text)):
            continue
        out.append(b)
    return out


def _spec_row(specs) -> str:
    if not specs:
        return ""
    cells = "".join(
        f'<div class="spec"><p class="spec__k">{esc(k)}</p>'
        f'<p class="spec__v">{esc(v)}<span class="spec__u">{esc(u)}</span></p></div>'
        for k, v, u in specs
    )
    return f'<section class="specs">{cells}</section>'


def render(product, assets: Path, title: str | None = None) -> str:
    """정규형 Product 를 800px 상세페이지 HTML 로."""
    m = product.meta
    ad = [assets / a for a in product.ad if (assets / a).exists()]
    options = product.option_units
    body = product.body_units

    name = title or m.name or "상세페이지"
    sub = m.brand or m.category

    parts = [f"<title>{esc(name)}</title>", f"<style>{CSS}</style>", '<div class="page">']

    # ① 히어로
    parts.append('<header class="hero">')
    if sub:
        parts.append(f'<p class="label hero__brand">{esc(sub)}</p>')
    parts.append(f'<h1 class="hero__title">{esc(name)}')
    if m.code:
        parts.append(f"<em>No. {esc(m.code)}</em>")
    parts.append("</h1>")
    hero_lead, rest_lead = split_lead(product.lead)
    if hero_lead:
        parts.append(f'<p class="hero__lead">{emphasize(hero_lead)}</p>')
    if ad:
        parts.append(f'<figure class="hero__shot"><img src="{data_uri(ad[0])}" alt="{esc(name)}"></figure>')
    parts.append("</header>")

    # ①-b 인트로 — 원본 맨 위에 직접 타이핑돼 있던 구간 (거의 모든 원본에 있다)
    intro = [b for b in getattr(product, "intro", []) if b.text.strip()]
    # 상품명 줄은 이미 제목으로 썼다. 두 번 싣지 않는다.
    squeezed = _squeeze(name, intro)
    if squeezed:
        # 크게 세울 줄은 **하나만** 고른다. 원본에서 강조돼 있던 짧은 줄이 그것이다.
        # 둘 이상을 크게 세우면 큰 덩어리가 되어 오히려 안 읽힌다.
        tag = next((b for b in squeezed if b.strong and len(b.text) <= 70), None)
        if tag is None and squeezed and len(squeezed[0].text) <= 70:
            tag = squeezed[0]
        parts.append('<section class="intro">')
        for blk in squeezed:
            cls = "intro__tag" if blk is tag else "intro__p"
            parts.append(f'<p class="{cls}">{emphasize(blk.text)}</p>')
        parts.append("</section>")

    # ② 스펙 요약
    parts.append(_spec_row(m.specs))

    # ③ 리드 문단 — 히어로가 첫 문장을 가져갔으므로 그 나머지만. 같은 글을 두 번 싣지 않는다.
    if rest_lead:
        parts.append(f'<section class="lead"><p class="lead__text">{emphasize(rest_lead)}</p></section>')

    # ④ 옵션 가이드
    if options:
        wide = "" if len(options) >= 5 else " grid--wide"
        parts.append('<section class="band">')
        parts.append(f'<p class="label">{len(options)} Options</p>')
        parts.append(f'<h2 class="band__title">{len(options)}가지 종류</h2>')
        parts.append('<p class="band__note">겉모습은 같지만 안쪽이 다릅니다. 종류에 따라 감각이 갈립니다.</p>')
        parts.append(f'<div class="grid{wide}">')
        for i, u in enumerate(options):
            src = assets / u.image
            chip = chip_color(src, FALLBACK_CHIPS[i % len(FALLBACK_CHIPS)])
            parts.append('<article class="variant">')
            parts.append(f'<figure class="variant__fig"><img src="{data_uri(src)}" alt="{esc(u.option_tag)}"></figure>')
            parts.append(f'<p class="variant__name"><span class="variant__chip" style="--chip:{chip}"></span>{esc(u.option_tag)}</p>')
            if u.caption:
                parts.append(f'<p class="variant__body">{emphasize(u.caption)}</p>')
            parts.append("</article>")
        parts.append("</div></section>")

    # ⑤ 남은 광고컷
    for i, a in enumerate(ad[1:]):
        parts.append('<section class="showcase">')
        parts.append(f'<figure class="showcase__shot"><img src="{data_uri(a)}" alt="{esc(name)} 안내 {i + 2}"></figure>')
        parts.append("</section>")

    # ⑥ 디테일 — 좌우 교차 (6.2 셋째 레버)
    if body:
        parts.append('<section class="features">')
        if any(u.has_caption for u in body):
            parts.append('<p class="label">Features</p>')
            parts.append('<h2 class="features__title">특징</h2>')
        for n, u in enumerate(body):
            if not u.has_caption:
                # 캡션이 없으면 그림만 크게. 버리지 않는다.
                parts.append(
                    f'<figure class="feature__solo">'
                    f'<img src="{data_uri(assets / u.image)}" alt="{esc(name)}">'
                    f"</figure>"
                )
                continue
            flip = " feature--flip" if n % 2 else ""
            # 6.2 다섯째 레버 — 첫 문장을 소제목으로. 단, 문장이 하나뿐이면
            # 승격해 봐야 본문이 사라지고 긴 제목만 남는다. 그때는 그냥 본문으로 둔다.
            head, text = (u.head, u.body) if (u.head and u.body) else ("", u.caption.strip())
            parts.append(f'<article class="feature{flip}">')
            parts.append(f'<figure class="feature__fig"><img src="{data_uri(assets / u.image)}" alt="{esc(_plain(head or u.caption[:40]))}"></figure>')
            parts.append('<div class="feature__text">')
            if head:
                parts.append(f'<h3 class="feature__head">{emphasize(head)}</h3>')
            if text:
                cls = "feature__body" if head else "feature__body feature__body--solo"
                parts.append(f'<p class="{cls}">{emphasize(text)}</p>')
            parts.append("</div></article>")
        parts.append("</section>")

    # ⑦ 푸터
    parts.append('<footer class="foot"><p class="label">Notice</p><div class="foot__row">')
    for h, p in FOOTER:
        parts.append(f'<div><p class="foot__h">{esc(h)}</p><p class="foot__p">{esc(p)}</p></div>')
    parts.append("</div></footer></div>")

    return "\n".join(x for x in parts if x)


def guess_specs(product) -> list[tuple[str, str, str]]:
    """캡션에 적힌 수치를 스펙으로 끌어올린다 (6.1 ②).

    원본에 없던 구조를 추가하는 것이 가장 강한 차별화인데, 없는 값을 지어내면 안 된다.
    그래서 **캡션에 실제로 적힌 숫자만** 쓴다.
    """
    text = " ".join(u.caption for u in product.units)
    out: list[tuple[str, str, str]] = []
    # `\b` 를 쓰면 안 된다 — 한글도 단어 문자라 "40 g이라" 에서 경계가 성립하지 않는다.
    for pat, key, unit in ((r"약?\s*(\d+(?:\.\d+)?)\s*g(?![A-Za-z])", "무게", "g"),
                           (r"약?\s*(\d+(?:\.\d+)?)\s*cm(?![A-Za-z])", "크기", "cm")):
        m = re.search(pat, text)
        if m:
            out.append((key, m.group(1), unit))
    if product.option_units:
        out.append(("종류", str(len(product.option_units)), "종"))
    elif product.meta.options:
        out.append(("옵션", str(len(product.meta.options)), "종"))
    return out
