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

    저자가 끊어 놓은 줄(`\n`)은 지킨다. 뜻으로 끊은 자리라, 브라우저가 폭에 맞춰
    아무 데서나 접게 두면 `…나선을 이루며 / 돈다 즉시…` 처럼 어긋난다.
    """
    out = esc(text)
    out = re.sub(r"\*\*(.+?)\*\*", r'<b class="em">\1</b>', out)
    return out.replace("\n", "<br>")


def data_uri(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def natural_width(path: Path) -> int:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.width
    except Exception:
        return 0


def page_scaler(widths):
    """페이지 전체를 **한 배율로** 늘린다.

    조각마다 폭을 꽉 채우면, 원본에서 손톱만 하던 아이콘 네 개가 페이지 폭짜리
    그림이 된다 — 트리니티 하단의 아이콘 줄이 실제로 그렇게 나왔다.
    원본에서 제일 넓은 것이 800px 이 되도록 맞추고, 나머지는 그 비율로 따라간다.
    커지는 것은 그림이지 배치가 아니다.
    """
    widest = max([w for w in widths if w], default=0)
    if not widest:
        return lambda w: ""
    ratio = WIDTH / widest

    def style(w: int) -> str:
        if not w or w >= widest:
            return ""
        return f' style="max-width:{round(w * ratio)}px;margin-inline:auto"'

    return style


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


def plate_color(path: Path, fallback: str = "#000") -> str:
    """조각이 **제 배경으로 두르고 있는 색**을 그대로 돌려준다.

    옵션 카드를 검은 띠 위에 얹는데, 원본이 배경을 지운 누끼컷이면 흰 사각형이
    검은 바탕에 덩그러니 뜬다. 흰 네모를 잘라내려 들 일이 아니다 — 원본 이미지는
    손대지 않는다. 조각이 두르고 있는 색을 깔아 주면 경계가 사라진다.

    색은 판정하지 않고 **가장자리에서 관측한다** (4.4 의 배경 관측과 같은 방식).
    가장자리가 한 가지 색으로 고르지 않으면 배경이 아니라 그림이 꽉 찬 것이므로
    그때는 손대지 않는다.
    """
    try:
        import numpy as np
        from PIL import Image

        a = np.asarray(Image.open(path).convert("RGB"))
        edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]).astype(int)
        ref = np.median(edge, axis=0)
        if (np.abs(edge - ref).max(axis=1) <= 12).mean() < 0.9:
            return fallback
        return "#%02X%02X%02X" % tuple(int(v) for v in ref)
    except Exception:
        return fallback


def _is_light(hexcolor: str) -> bool:
    """그 색이 밝은 쪽인가. 검은 띠 위에서 카드로 둘러야 할지 가른다."""
    try:
        r, g, b = (int(hexcolor[i : i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return False
    return (r * 299 + g * 587 + b * 114) / 1000 > 170


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
.hero__tags{margin-top:14px;display:flex;flex-wrap:wrap;gap:6px}
.hero__tag{font-size:12.5px;font-weight:700;letter-spacing:-.01em;padding:5px 10px;
 border:1px solid var(--rule);border-radius:999px;color:var(--muted);white-space:nowrap}
.hero__title{margin:14px 0 0;font-size:48px;line-height:1.06;font-weight:800;letter-spacing:-.035em;text-wrap:balance}
.hero__alt{display:block;margin-top:10px;font-size:.42em;font-weight:700;line-height:1.4;
 color:var(--muted);letter-spacing:-.01em}
.hero__title em{font-style:normal;display:block;color:var(--muted);font-weight:700;font-size:.28em;
 margin-top:14px;letter-spacing:.04em}
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
.variant__fig--card{padding:16px;border-radius:3px}
.variant__name{margin-top:16px;font-size:21px;font-weight:800;letter-spacing:-.02em;
 display:flex;align-items:center;gap:9px;line-height:1.25}
.variant__chip{width:11px;height:11px;border-radius:50%;background:var(--chip);flex:none;
 box-shadow:0 0 0 3px color-mix(in srgb,var(--chip) 22%,transparent)}
.variant__no{color:var(--band-muted);font-variant-numeric:tabular-nums;flex:none}
.optset__no{color:var(--muted);font-variant-numeric:tabular-nums}
.variant__body{margin-top:12px;font-size:14px;line-height:1.75;color:var(--band-muted)}
.variant--bare{display:flex;align-items:center;min-height:74px;padding:18px 18px;
 border:1px solid color-mix(in srgb,var(--band-ink) 22%,transparent);border-radius:2px}
.variant--bare .variant__name{margin-top:0}
.optset{padding:8px 0 40px;border-top:1px solid var(--rule)}
.optset:first-of-type{border-top:0}
.optset__name{margin:24px 0 20px;font-size:28px;font-weight:800;letter-spacing:-.025em;
 display:flex;align-items:center;gap:12px}
.optset__chip{width:13px;height:13px;border-radius:50%;background:var(--chip);flex:none;
 box-shadow:0 0 0 3px color-mix(in srgb,var(--chip) 22%,transparent)}
.optset__grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:24px 20px}
.optset__item{margin:0}
.optset__item img{background:var(--plate);border-radius:2px}
.optset__item figcaption{margin-top:10px;font-size:13.5px;line-height:1.7;color:var(--muted)}
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


#: 상품명 맨 앞의 대괄호 묶음 — `[초보자세트][일본 직수입]` 처럼 여러 개 붙는다
BRACKETS_RE = re.compile(r"^\s*((?:\[[^\]]*\]\s*)+)")
TAIL_PAREN_RE = re.compile(r"\(([^()]*)\)\s*$")
HANGUL_RE = re.compile(r"[가-힣]")
#: 모델번호·브랜드 약자 — `(OH-3036)` `(NPR)` `(LVH)`. 창고에서 물건 찾을 때 쓰는 표시다.
#: 띄어쓰기가 없고, 숫자가 섞였거나 아주 짧다. 이 선을 넓히면 `(ROMP Switch X)` 같은
#: 진짜 외국어명까지 물류 표시로 오인해 잘라버린다.
CODE_RE = re.compile(r"^(?=.*\d)[A-Z0-9][A-Z0-9\-.]{0,11}$|^[A-Z]{2,4}$")


def split_name(name: str) -> tuple[list[str], str, str]:
    """상품명을 특징 · 한글명 · 외국어명 세 줄로 가른다.

    원본 상품명은 상세페이지용이 아니라 **물류용**이다. 브랜드명, 모델번호,
    브랜드 약자가 뒤에 줄줄이 붙는다. 그대로 제목에 실으면 세 줄을 잡아먹는다.

        [일본 직수입] AV 미니 명기 미우라 사쿠라(AVミニ名器 水卜さくら) - 니포리기프트 (OH-3037)(NPR)
        └── 특징 ──┘ └──── 한글명 ────┘ └──── 외국어명 ────┘ └────── 버린다 ──────┘

    브랜드는 이미 제목 위에 따로 실린다. 모델번호는 창고에서 물건 찾을 때 쓰는 것이다.

    자리로만 가른다 — 특정 브랜드 이름이나 약자 목록을 적어두지 않는다.
    그런 표를 만들면 새 브랜드가 들어올 때마다 고쳐야 한다.

      · 맨 앞 대괄호들      → 특징
      · ` - ` 뒤            → 버린다 (브랜드·모델번호 자리)
      · 끝에 붙은 코드 괄호  → 버린다 (`(NPR)` `(OH-3036)` `(LVH)`)
      · **맨 끝 괄호**      → 외국어명. 그 앞이 한글명

    끝에서부터 본다. 첫 괄호를 외국어명으로 잡으면 `명기(名器) 시리즈 2(メイキシリーズ)`
    에서 `시리즈 2` 가 통째로 사라진다. 맨 끝만 떼면 무엇도 조용히 없어지지 않는다.

    괄호 안에 한글이 있으면 외국어명이 아니라 상품명의 일부다. 그때는 세 줄로 안 가른다 —
    나누지 못하는 것보다 글자를 잃는 쪽이 나쁘다.
    """
    text = (name or "").strip()
    m = BRACKETS_RE.match(text)
    tags = re.findall(r"\[([^\]]*)\]", m.group(1)) if m else []
    tags = [t.strip() for t in tags if t.strip()]
    rest = (text[m.end():] if m else text).strip()

    rest = re.split(r"\s+[-–—]\s+", rest)[0].strip()
    while True:
        mm = TAIL_PAREN_RE.search(rest)
        if not (mm and CODE_RE.match(mm.group(1).strip())):
            break
        rest = rest[: mm.start()].strip()

    mm = TAIL_PAREN_RE.search(rest)
    if mm and not HANGUL_RE.search(mm.group(1)):
        korean = rest[: mm.start()].strip(" -–—·,")
        if korean:
            return tags, korean, mm.group(0)
    return tags, rest, ""


def split_lead(lead: str) -> tuple[str, str]:
    """리드를 히어로용 첫 문장과 나머지로 가른다."""
    text = (lead or "").strip()
    if not text:
        return "", ""
    m = re.search(r"^(.{6,90}?[.。])\s+(.+)$", text, re.S)
    return (m.group(1).strip(), m.group(2).strip()) if m else (text, "")


def _same_thing(name: str, text: str) -> bool:
    """그 줄이 사실상 상품명인가."""
    key = re.sub(r"[\s\[\]()]", "", (name or "")).lower()
    text = re.sub(r"[\s\[\]()]", "", text or "").lower()
    if not key or not text:
        return False
    return text == key or (len(text) >= 4 and text in key) or (len(key) >= 4 and key in text)


def _squeeze(name: str, blocks):
    """제목과 같은 줄은 뺀다. 같은 말을 두 번 싣지 않는다."""
    return [b for b in blocks if not _same_thing(name, b.text)]


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
    # 옵션은 **세는 것**이다. 사진이 몇 장 딸렸는지로 옵션의 존재가 갈리지 않는다.
    #  · 사진 0장  → 이름만 있는 칩 카드 (엑셀에는 있는데 설명 이미지가 없는 옵션)
    #  · 사진 1장  → 카드 한 판으로 끝 (텐가)
    #  · 사진 N장  → 카드는 한눈에 보는 용도, 자세한 건 옵션별 구간으로 (닛포리)
    # 어느 쪽도 상품마다 손볼 일이 없다. 개수만 보고 갈린다.
    groups = product.option_groups
    cards = groups + [(tag, []) for tag in product.orphan_options]
    detailed = any(len(us) > 1 for _t, us in groups)
    body = product.body_units
    # 통짜로 싣는 그림들은 한 배율로 늘린다. 원본의 크기 관계를 지킨다.
    fit = page_scaler([natural_width(p) for p in ad] + [u.width for u in body])

    full = title or m.name or "상세페이지"
    tags, name, alt = split_name(full)
    sub = m.brand or m.category

    parts = [f"<title>{esc(name)}</title>", f"<style>{CSS}</style>", '<div class="page">']

    # ① 히어로
    parts.append('<header class="hero">')
    if sub:
        parts.append(f'<p class="label hero__brand">{esc(sub)}</p>')
    if tags:
        chips = "".join(f'<span class="hero__tag">{esc(t)}</span>' for t in tags)
        parts.append(f'<p class="hero__tags">{chips}</p>')
    parts.append(f'<h1 class="hero__title">{esc(name)}')
    if alt:
        parts.append(f'<span class="hero__alt">{esc(alt)}</span>')
    if m.code:
        parts.append(f"<em>No. {esc(m.code)}</em>")
    parts.append("</h1>")
    hero_lead, rest_lead = split_lead(product.lead)
    # 리드 첫 줄이 상품명을 그대로 다시 적어둔 것이면 건너뛴다. 원본은 이미지 위에
    # 상품명을 한 번 더 타이핑해 두는 일이 잦아서, 그대로 두면 제목 바로 밑에 같은
    # 말이 또 실린다.
    while hero_lead and _same_thing(full, hero_lead):
        hero_lead, rest_lead = split_lead(rest_lead)
    if hero_lead:
        parts.append(f'<p class="hero__lead">{emphasize(hero_lead)}</p>')
    if ad:
        parts.append(f'<figure class="hero__shot"><img src="{data_uri(ad[0])}" alt="{esc(name)}"{fit(natural_width(ad[0]))}></figure>')
    parts.append("</header>")

    # ①-b 인트로 — 원본 맨 위에 직접 타이핑돼 있던 구간 (거의 모든 원본에 있다)
    intro = [b for b in getattr(product, "intro", []) if b.text.strip()]
    # 상품명 줄은 이미 제목으로 썼다. 두 번 싣지 않는다.
    # 원본 맨 위 타이핑 줄은 상품명을 통째로 다시 적어둔 경우가 많다. 자른 뒤가
    # 아니라 **자르기 전 원문**과 대조해야 그 줄이 걸린다.
    squeezed = _squeeze(full, intro)
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
    if cards:
        wide = "" if len(cards) >= 5 else " grid--wide"
        parts.append('<section class="band">')
        parts.append(f'<p class="label">{len(cards)} Options</p>')
        parts.append(f'<h2 class="band__title">{len(cards)}가지 종류</h2>')
        parts.append('<p class="band__note">종류에 따라 형태와 감각이 갈립니다.</p>')
        parts.append(f'<div class="grid{wide}">')
        for i, (tag, us) in enumerate(cards):
            fallback = FALLBACK_CHIPS[i % len(FALLBACK_CHIPS)]
            src = (assets / us[0].image) if us else None
            chip = chip_color(src, fallback) if src else fallback
            parts.append(f'<article class="variant{"" if us else " variant--bare"}">')
            if src:
                # 조각이 두르고 있는 색을 관측해서 그대로 깐다. 배경을 지운 누끼컷이면
                # 흰 사각형이 검은 띠 위에 덩그러니 뜨는데, 같은 색으로 여백을 둘러
                # **카드처럼 보이게** 하면 그게 의도한 모양이 된다. 흰 네모를 잘라내려
                # 들지 않는다 — 원본 이미지는 손대지 않는다.
                plate = plate_color(src)
                card = " variant__fig--card" if _is_light(plate) else ""
                parts.append(
                    f'<figure class="variant__fig{card}" style="background:{plate}">'
                    f'<img src="{data_uri(src)}" alt="{esc(tag)}"></figure>'
                )
            # 카드에서 사람이 알아야 하는 것은 **몇 번 옵션인지와 그 이름**이다.
            # 장수는 살 때 쓸모가 없다. 주문할 때 고르는 건 번호와 이름이다.
            parts.append(
                f'<p class="variant__name"><span class="variant__chip" style="--chip:{chip}"></span>'
                f'<span class="variant__no">{esc(product.option_number(tag, i))}.</span>{esc(tag)}</p>'
            )
            if us and us[0].caption:
                parts.append(f'<p class="variant__body">{emphasize(us[0].caption)}</p>')
            parts.append("</article>")
        parts.append("</div></section>")

    # ⑤ 남은 광고컷
    for i, a in enumerate(ad[1:]):
        parts.append('<section class="showcase">')
        parts.append(f'<figure class="showcase__shot"><img src="{data_uri(a)}" alt="{esc(name)} 안내 {i + 2}"{fit(natural_width(a))}></figure>')
        parts.append("</section>")

    # ④-b 옵션별 상세 — 옵션 하나에 사진이 여럿일 때만 (닛포리류)
    if detailed:
        parts.append('<section class="features">')
        parts.append('<p class="label">By Option</p>')
        parts.append('<h2 class="features__title">종류별로 보기</h2>')
        for n, (tag, us) in enumerate(groups):
            parts.append('<div class="optset">')
            chip = FALLBACK_CHIPS[n % len(FALLBACK_CHIPS)]
            if us:
                chip = chip_color(assets / us[0].image, chip)
            parts.append(
                f'<h3 class="optset__name"><span class="optset__chip" style="--chip:{chip}"></span>'
                f'<span class="optset__no">{esc(product.option_number(tag, n))}.</span>{esc(tag)}</h3>'
            )
            parts.append('<div class="optset__grid">')
            for u in us:
                parts.append('<figure class="optset__item">')
                parts.append(f'<img src="{data_uri(assets / u.image)}" alt="{esc(tag)}">')
                if u.caption:
                    parts.append(f'<figcaption>{emphasize(u.caption)}</figcaption>')
                parts.append("</figure>")
            parts.append("</div></div>")
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
                    f'<img src="{data_uri(assets / u.image)}" alt="{esc(name)}"{fit(u.width)}>'
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


#: 수치 앞에 붙어 있어야 하는 말 → 스펙 이름. 원본이 **무엇의 치수인지 말해 준 것**만 싣는다.
SPEC_WORDS = {
    "무게": "무게", "중량": "무게",
    "전장": "길이", "전체길이": "길이", "길이": "길이", "높이": "높이",
    "최대폭": "폭", "폭": "폭", "너비": "폭",
    "지름": "지름", "직경": "지름", "두께": "두께",
    "크기": "크기", "사이즈": "크기", "용량": "용량",
}
#: 숫자와 그 말 사이에 끼어도 되는 글자 수. `무게는 약 40 g` 정도가 들어간다.
SPEC_GAP = 8
SPEC_RE = re.compile(
    r"(" + "|".join(sorted(SPEC_WORDS, key=len, reverse=True)) + r")"
    r"[^.。]{0," + str(SPEC_GAP) + r"}?(\d+(?:\.\d+)?)\s*(mm|cm|m|kg|g|ml|l)(?![A-Za-z])"
)


def guess_specs(product) -> list[tuple[str, str, str]]:
    """캡션에 적힌 수치를 스펙으로 끌어올린다 (6.1 ②).

    원본에 없던 구조를 추가하는 것이 가장 강한 차별화인데, 없는 값을 지어내면 안 된다.
    그래서 **캡션에 실제로 적힌 숫자만** 쓴다.

    숫자만 보면 안 된다. 단위만 보고 `cm` 를 크기로 삼았더니, 미우라 사쿠라 페이지에서
    `가슴이 79cm의 G컵` 의 79을 끌어와 **제품 크기가 79cm** 라고 실었다. 79cm 짜리
    오나홀은 없다. 지어낸 것보다 나쁠 것도 없는 거짓말이다.

    그래서 **원본이 무엇의 치수인지 말해 준 것만** 싣는다. 이름도 우리가 붙이지 않고
    원본이 쓴 말에서 가져온다 — `전장 146mm` 는 길이고, `가슴이 79cm` 는 우리 쪽
    어휘에 없으니 스펙이 아니다. 못 싣는 것이 틀리게 싣는 것보다 낫다.
    """
    text = " ".join(u.caption for u in product.units)
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for word, value, unit in SPEC_RE.findall(text):
        key = SPEC_WORDS[word]
        if key in seen:
            continue
        seen.add(key)
        out.append((key, value, unit))
    if product.option_units:
        out.append(("종류", str(len(product.option_units)), "종"))
    elif product.meta.options:
        out.append(("옵션", str(len(product.meta.options)), "종"))
    return out
