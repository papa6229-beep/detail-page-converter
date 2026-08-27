"""기본형 **메인 섹션** — 잘 만들어진 원본을 뜯어 우리 디자인으로 다시 세운다.

`origin/legacy/basic-before-rewind` 의 `app/basic.py` 에서 메인 부분만 옮겼다.
옮기지 않은 것: Point 01·02 재구성 · SIZE · 본문. **본문은 basic/body.py 가 맡는다.**

단순형과 전제가 반대다.

    단순형   원본이 허접하다 → 원본 이미지를 손대지 않고 순서대로 싣는다
    기본형   원본이 이미 완성된 디자인이다 → 그대로 실으면 남의 쇼핑몰처럼 보인다

그래서 원본을 **재료로만** 쓴다. 컬러 배경 위에 얹힌 원본 대표컷을 버리고,
페이지 어딘가의 **흰 바탕 제품 단독컷**을 찾아 새 대표컷으로 세운다.

legacy 는 조각을 `slicer.slice_image` 로 냈지만 여기서는 `basic/bands.py` 밴드를
쓴다 — legacy 도 마지막엔 밴드로 갔고, 무엇보다 단순형 분할기를 안 건드린다.
"""

from __future__ import annotations

import base64
import html
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from . import bands as B

#: 글자꼴 덩어리를 셀 때 이 크기로 줄여서 본다. 글자가 뭉개지지 않으면서 빠르다.
CC_SCALE = 200


@dataclass
class Rect:
    """조각 하나의 자리. legacy 는 slicer.Rect 를 썼다 — 여기서는 밴드 안의 알맹이."""

    x0: int
    y0: int
    x1: int
    y1: int


#: 알맹이 둘레에 남길 여유. 피사체 크기에 대한 비율이다.
#: 연한 그림자·바닥면은 배경과 거의 같은 밝기라 전경으로 안 잡힌다 — 딱 맞게
#: 자르면 다일레이터 대표컷 밑의 그림자가 뭉텅 잘려 제품이 공중에 뜬다.
#: 여유는 **밴드 원본 픽셀로 채운다** — 흰 바탕이면 흰색이 따라온다.
MARGIN = 0.06


#: 배경색에서 이만큼 벗어나야 전경으로 본다.
BG_NEAR = 60
#: 테두리에서 이만큼을 차지하면 그것도 배경색이다.
BG_SHARE = 0.12


#: 테두리 색이 이보다 밝고 무채색이면 "흰 바탕" 으로 본다.
WHITE_RING = 232


def _white_ring(ring: np.ndarray) -> bool:
    """테두리가 통째로 흰 바탕인가 — 그러면 잘라 낼 것이 없다."""
    q = ring.astype(np.int32)
    return bool(q.min(axis=1).mean() >= WHITE_RING)


def _off_background(crop: np.ndarray, ring: np.ndarray) -> np.ndarray:
    """화소마다 **가장 가까운 배경색과의 거리**. 배경 위면 작다.

    배경을 색 **하나**로 보면 안 된다. 죠우무의 패키지 밴드는 테두리 절반이 파란
    사선 띠, 절반이 흰 여백이라 중앙값이 그 사이(215·219·253)에 떨어졌다. 그러면
    흰 여백조차 배경에서 75 만큼 벗어난 것이 되어 **밴드 전체가 한 덩어리**가 됐다.
    테두리에서 제 몫을 차지하는 색은 **전부** 배경으로 본다.
    """
    q = (ring.astype(np.int32) // 24) * 24
    uniq, counts = np.unique(q.reshape(-1, 3), axis=0, return_counts=True)
    keep = uniq[counts >= BG_SHARE * len(q)]
    if not len(keep):
        keep = np.median(ring.astype(np.int32), axis=0)[None, :]
    px = crop.astype(np.int32)
    best = None
    for c in keep:
        d = np.abs(px - c).sum(axis=2)
        best = d if best is None else np.minimum(best, d)
    return best


def _content_rect(arr: np.ndarray, y: int, height: int) -> Rect | None:
    """밴드 안에서 **배경색이 아닌 제일 큰 덩어리**의 자리를 집는다.

    배경은 흰색이라고 못박지 않는다. 테두리 한 겹의 중앙값을 배경으로 보고, 거기서
    벗어난 화소를 전경으로 센다. 그래야 **색 배경 위에 놓인 상자**도 상자만 잡힌다 —
    죠우무의 패키지 밴드는 상자 왼쪽에 파란 사선 띠, 오른쪽에 캡션이 같이 있어서,
    전부를 감싸면 테두리 색비율이 0.31 이 되어 상자가 통째로 떨어졌다.

    둘레에 `MARGIN` 만큼 여유를 준다. 자른 자리는 밴드에서 그대로 떠 오므로
    배경이 희면 흰색이, 색이면 그 색이 따라온다.
    """
    import cv2

    from . import sidetext

    crop = arr[y : y + height]
    h, w = crop.shape[:2]
    if h < 4 or w < 4:
        return None
    whole = Rect(0, y, w - 1, y + h - 1)
    t = max(2, min(6, h // 8, w // 8))
    ring = np.concatenate([crop[:t].reshape(-1, 3), crop[-t:].reshape(-1, 3),
                           crop[:, :t].reshape(-1, 3), crop[:, -t:].reshape(-1, 3)])

    # **흰 바탕이고 라벨도 없으면 자르지 않는다.** 자를 것이 없기 때문이다.
    # 자르면 오히려 잃는다 — 흰 제품은 흰 배경과 잘 안 갈려서 "제일 큰 덩어리" 가
    # 제품의 한 조각만 잡는다(유컵스의 흰 링 셋 중 하나만 남았다).
    # 자르는 것은 **색 배경이 깔렸거나 라벨이 붙었을 때**뿐이다 — 그때는 떼어낼
    # 것이 실제로 있다(죠우무 패키지의 파란 사선 띠와 캡션).
    if _white_ring(ring) and sidetext.split(crop) is None:
        return whole

    fg = (_off_background(crop, ring) > BG_NEAR).astype(np.uint8)
    if not fg.any():
        return whole

    # 큰 덩어리 하나만 남긴다. 잔글씨·얇은 띠가 붙어 오지 않게 살짝 이어 붙여 센다.
    step = max(1, max(h, w) // 400)
    small = fg[::step, ::step]
    small = cv2.morphologyEx(small, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _lab, st, _c = cv2.connectedComponentsWithStats(small)
    if n <= 1:
        return whole
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    x0, y0, bw, bh = (int(st[i, cv2.CC_STAT_LEFT]), int(st[i, cv2.CC_STAT_TOP]),
                      int(st[i, cv2.CC_STAT_WIDTH]), int(st[i, cv2.CC_STAT_HEIGHT]))
    x0, y0, bw, bh = x0 * step, y0 * step, bw * step, bh * step

    pad = int(round(max(bw, bh) * MARGIN))
    x1, y1 = min(w - 1, x0 + bw - 1 + pad), min(h - 1, y0 + bh - 1 + pad)
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    if x1 <= x0 or y1 <= y0:
        return whole
    return Rect(x0, y + y0, x1, y + y1)


def rects(arr: np.ndarray, offset: int = 0) -> dict[int, Rect]:
    """밴드 번호 → 알맹이 자리. **재는 일은 여기서 끝났다.**

    예전에는 밴드마다 열 가지 값을 재서 코드가 등급을 매기고 골랐다. 상품이 늘
    때마다 잣대가 어긋났다 — 무늬 있는 제품에서 글자꼴이 60~76 개로 세어지고,
    파란 제품에서 `ink` 가 0 이 되고, 페이지 바닥에 색이 깔리면 `design` 이 전부
    1.0 에 붙었다. **픽셀로 "무엇이 찍혔는가" 를 재려던 것이 잘못이다.**

    지금은 모델이 밴드마다 **사실만** 말하고(제품 개수·흰 바탕인가·글자·손·상자),
    코드는 그 사실로 고른다. 여기 남은 일은 **자리 찾기** 하나뿐이다.
    """
    out: dict[int, Rect] = {}
    for i, b in enumerate(B.read(arr)):
        r = _content_rect(arr, b.y, b.height)
        if r is not None:
            out[offset + i] = r
    return out


# ── 대표컷·키피쳐·패키지 고르기 ─────────────────────────────────────────
#
# **모델은 사실만 말하고, 고르는 것은 코드다.**
#
# 모델이 밴드마다 다섯 가지를 답한다 — 제품이 몇 개 보이는가 · 배경이 흰가 ·
# 글자가 박혔는가 · 손이나 몸이 나오는가 · 상자가 보이는가. 판단이 아니라 사실이다.
# 그 사실로 자리를 고르는 규칙은 코드에 있고, 읽으면 그대로 이해된다.
#
#     대표컷  흰 바탕 · 글자 없음 · 손 없음 · 제품이 1개이거나 옵션 수와 같음
#     키피쳐  대표컷 빼고 · 흰 바탕 · 글자 없음 · 제품 1개 이상
#             그런 것이 없으면 손이 나와도 쓴다
#     패키지  상자가 보임. 없으면 빈칸
#
# 여럿이면 **원본 순서상 앞의 것**을 쓴다. 넓이나 점수로 고르지 않는다 —
# 그렇게 고르던 시절에 파우치컷이 제품 단독컷을 이겼다.

#: 같은 사진으로 볼 dHash 거리. 대표컷과 키피쳐가 같은 사진이면 두 번 실린다.
#: 실측 — 정말 같은 컷 1 ↔ 서로 다른 컷 10·10·11·12·12·12·12·12.
SAME_PHOTO = 5


@dataclass
class Facts:
    """밴드 하나에 대해 모델이 말한 사실."""

    products: int = 0      #: 제품이 몇 개 보이는가 (0 이면 제품이 안 보인다)
    white_bg: bool = False
    text: bool = False
    hand: bool = False     #: 손·신체가 나오는가
    box: bool = False      #: 판매용 상자가 보이는가


def parse_facts(raw) -> dict[int, Facts]:
    """모델이 준 밴드별 사실을 읽는다.

    모양은 **글자 한 줄**이다 — `"7:1,white,notext,nohand,nobox"`. 중첩을 안 쓰는
    이유는 모델이 배열의 닫는 대괄호를 자꾸 빠뜨려 답이 통째로 버려졌기 때문이다
    (글랜스·다일레이터). 줄 하나가 깨져도 그 밴드만 잃는다.
    """
    got: dict[int, Facts] = {}
    if isinstance(raw, dict):
        raw = [f"{k}:{v}" for k, v in raw.items()]
    if isinstance(raw, str):
        raw = raw.replace(";", "\n").splitlines()
    for line in raw or []:
        text = str(line).strip()
        if not text or ":" not in text:
            continue
        head, _, tail = text.partition(":")
        try:
            n = int(re.sub(r"[^0-9]", "", head))
        except ValueError:
            continue
        words = [w.strip().lower() for w in re.split(r"[,\s]+", tail) if w.strip()]
        f = Facts()
        for w in words:
            if w.isdigit():
                f.products = int(w)
            elif w in ("white", "흰바탕", "흰색"):
                f.white_bg = True
            elif w in ("text", "글자"):
                f.text = True
            elif w in ("hand", "손"):
                f.hand = True
            elif w in ("box", "상자"):
                f.box = True
        got[n] = f
    return got


def _usable(n: int, kinds: list[str], facts: dict[int, Facts]) -> bool:
    """밴드 자체가 그림으로 쓸 수 있는 것인가."""
    return 0 <= n < len(kinds) and kinds[n] not in ("TEXT", "PROMO") and n in facts


def choose(facts: dict[int, Facts], kinds: list[str], hashes: list[int],
           options: int = 1) -> tuple[int, int, int, list[str]]:
    """(대표컷, 키피쳐, 패키지, 메모). **사실만 보고 코드가 고른다.**

    `options` 는 엑셀 옵션 열에서 온 옵션 수다. 그림에서 세지 않는다 — 엑셀이
    말해 주는 사실이 있는데 픽셀로 짐작할 이유가 없다.
    """
    notes: list[str] = []
    order = sorted(n for n in facts if _usable(n, kinds, facts))

    def same_photo(a: int, b: int) -> bool:
        ha = hashes[a] if a < len(hashes) else 0
        hb = hashes[b] if b < len(hashes) else 0
        return B.hamming(ha, hb) <= SAME_PHOTO

    def first(test) -> int:
        return next((n for n in order if test(facts[n])), -1)

    hero = first(lambda f: f.white_bg and not f.text and not f.hand
                 and (f.products == 1 or (options > 1 and f.products == options)))
    if hero < 0:
        notes.append(f"대표컷 빈칸 — 흰 바탕·글자 없음·손 없음·제품 1개 또는 {options}개인 밴드가 없다")

    # 패키지를 **키피쳐보다 먼저** 고른다. 상자컷도 흰 바탕 제품컷이라 키피쳐
    # 조건에 걸리는데, 키피쳐가 먼저 집어 가면 상자 자리가 빈다(벨벳키스에서 그랬다).
    # 상자로 쓸 수 있는 밴드는 흔치 않고, 키피쳐로 쓸 밴드는 대개 여럿이다.
    pkg = next((n for n in order if facts[n].box and n != hero), -1)
    if pkg < 0:
        notes.append("패키지 빈칸 — 상자가 보이는 밴드가 없다")

    def feature_ok(n: int, allow_hand: bool) -> bool:
        f = facts[n]
        if n in (hero, pkg) or (hero >= 0 and same_photo(n, hero)):
            return False
        return f.white_bg and not f.text and f.products >= 1 and (allow_hand or not f.hand)

    feat = next((n for n in order if feature_ok(n, False)), -1)
    if feat < 0:
        feat = next((n for n in order if feature_ok(n, True)), -1)
        if feat >= 0:
            notes.append(f"키피쳐 [{feat}] — 손 없는 컷이 없어 손이 나온 것을 썼다")
    if feat < 0:
        notes.append("키피쳐 빈칸 — 흰 바탕 제품컷이 대표컷 말고는 없다")

    notes.append(f"옵션 {options}개 · 사실을 받은 밴드 {len(order)}개")
    for slot, n in (("대표컷", hero), ("키피쳐", feat), ("패키지", pkg)):
        if n >= 0:
            f = facts[n]
            notes.append(f"{slot} = 밴드 [{n}] (제품 {f.products}개"
                         f"{' · 흰 바탕' if f.white_bg else ' · 색 바탕'}"
                         f"{' · 손' if f.hand else ''}{' · 상자' if f.box else ''})")
    return hero, feat, pkg, notes


#: 강조색. 고도몰 생성기의 기본값을 그대로 쓴다 (`DEFAULT_THEME_COLOR`).
ACCENT = "#E11D48"

#: 이 CSS 도 **남의 페이지 안에서 산다**. 선택자는 전부 `.gpage` 로 시작한다.
#: legacy 는 폭 800(메인이미지 700)이었다. 본문(`.bpage`)이 860 이라 **여기도 860**
#: 으로 맞춘다 — 한 파일에 위아래로 붙는데 폭이 다르면 층이 어긋나 보인다.
#: 안쪽 치수는 legacy 비율 그대로 옮겼다(좌우 여백 50 → 알맹이 760).
CSS = """
.gpage{--accent:#E11D48;--ink:#111827;--mute:#6b7280;--soft:#9ca3af;--body:#4b5563;
 --plate:#f3f4f6;--line:#e5e7eb;
 width:860px;max-width:100%;margin:0 auto;background:#fff;color:var(--ink);
 font-family:"Pretendard","Pretendard Variable",-apple-system,BlinkMacSystemFont,
 "Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",system-ui,sans-serif;
 -webkit-font-smoothing:antialiased;word-break:keep-all;overflow-wrap:break-word}
.gpage,.gpage *{box-sizing:border-box}
.gpage p,.gpage h1,.gpage h2{margin:0}
.gpage img{display:block;width:100%;height:auto}
.gpage .dot{display:inline-block;border-radius:50%;flex:none;background:var(--accent)}
.gpage .hero{padding:56px 50px}
.gpage .hero__maker{text-align:right;margin-bottom:12px;font-size:24px;font-weight:900;letter-spacing:-.025em}
.gpage .hero__wrap{position:relative}
.gpage .hero__main{width:100%;margin:0 auto;border:1px solid var(--line);overflow:hidden}
.gpage .hero__name{margin-top:32px;font-size:52px;line-height:1.05;font-weight:900;
 letter-spacing:-.025em;max-width:500px;white-space:pre-line}
.gpage .hero__en{margin-top:4px;font-size:20px;font-weight:500;letter-spacing:.15em;
 color:var(--soft);text-transform:uppercase}
.gpage .specs{margin-top:40px;display:flex;flex-direction:column;gap:16px}
.gpage .specs__row{display:flex;gap:16px}
.gpage .spec{width:155px;flex:none;min-width:0}
.gpage .spec__k{display:flex;align-items:center;gap:6px;font-size:14px;font-weight:700;
 color:var(--mute);white-space:nowrap}
.gpage .spec__rule{height:2px;background:var(--ink);margin:8px 0}
.gpage .spec__v{font-size:15px;font-weight:900;line-height:1.375}
/* 패키지는 히어로 오른쪽 아래에 얹는다. legacy 기본 자리(x 468 · 700 기준)를
   760 알맹이에 맞춰 옮겼다. 원본에 없으면 아예 안 그린다. */
.gpage .pkg{position:absolute;left:508px;top:430px;width:228px;height:270px;
 display:flex;flex-direction:column;z-index:2}
.gpage .pkg__box{flex:1;border:2px solid var(--ink);border-bottom:0;background:#fff;
 display:flex;align-items:center;justify-content:center;overflow:hidden}
.gpage .pkg__box img{width:100%;height:100%;object-fit:contain;padding:8px}
.gpage .pkg__bar{background:var(--ink);color:#fff;text-align:center;font-weight:900;
 font-size:14px;letter-spacing:.025em;padding:8px 0}
.gpage .sec{padding:56px 50px;position:relative}
.gpage .sec__h{margin-top:16px;font-size:72px;line-height:.9;font-weight:900;letter-spacing:-.05em}
.gpage .sec__sub{margin-top:12px;font-size:18px;font-weight:700;color:var(--mute)}
.gpage .keys{position:relative;margin-top:10px;min-height:440px}
.gpage .keys__list{position:absolute;right:0;top:0;width:390px;display:flex;
 flex-direction:column;gap:52px}
.gpage .key{background:var(--plate);border-radius:12px;padding:16px 20px}
.gpage .key__t{display:flex;align-items:center;gap:8px;margin-bottom:6px;
 font-size:18px;font-weight:900}
.gpage .key__d{font-size:14px;font-weight:500;color:var(--body);line-height:1.375}
.gpage .keys__fig{position:absolute;left:0;top:0;width:340px;height:380px}
.gpage .keys__fig img{width:100%;height:100%;object-fit:contain}
.gpage .band{border-top:1px solid #d1d5db;border-bottom:1px solid #d1d5db;padding:16px 0;
 overflow:hidden;white-space:nowrap;text-align:center;color:var(--soft);
 font-size:14px;font-weight:500;letter-spacing:.25em;text-transform:uppercase}
@media (max-width:860px){
 .gpage .hero,.gpage .sec{padding-left:22px;padding-right:22px}
 .gpage .hero__name{font-size:34px;max-width:100%}
 .gpage .sec__h{font-size:44px}
 .gpage .pkg{position:static;width:160px;height:190px;margin:24px 0 0 auto}
 .gpage .keys{min-height:0}
 .gpage .keys__list,.gpage .keys__fig{position:static;width:100%;gap:16px}
 .gpage .keys__fig{height:260px;margin-bottom:16px}}
"""


@dataclass
class Page:
    """기본형 **메인**이 채워야 하는 칸. 고도몰 생성기의 칸과 같은 이름이다.

    사장님이 항목을 다섯으로 줄여 고정하셨다 — `타입 · 재질 · 치수 · 무게 · 전원`.
    브랜드는 우상단에 따로 박히고, `특징` 은 KEY FEATURE 부제로 간다.

    비어 있는 칸은 **그리지 않는다.** 없는 것을 지어내지 않는 것이 이 프로젝트의
    규칙이고, 여기서는 화면에서도 그렇게 한다.

    Point 01·02 와 SIZE 는 여기 없다 — 그 자리는 본문(basic/body.py)이 맡는다.
    """

    name_kr: str = ""
    name_en: str = ""
    maker: str = ""
    spec: dict[str, str] = field(default_factory=dict)
    #: KEY FEATURE 세 칸 — (제목, 한 줄 설명)
    keys: list[tuple[str, str]] = field(default_factory=list)
    main: Path | None = None
    package: Path | None = None
    feature: Path | None = None
    #: 원본 메인섹션이 끝나고 본문이 시작되는 첫 밴드 번호
    body_start: int = 0
    #: 세운 밴드 번호들. 보고용 — 어느 컷을 세웠는지 사람이 봐야 한다.
    main_band: int = -1
    feature_band: int = -1
    package_band: int = -1


#: 사장님이 고정한 다섯 항목. 1행 셋, 2행 둘 — 2행을 왼쪽에 두는 것은
#: 오른쪽 패키지 상자에 안 가리게 하려는 것이다.
SPEC_ROWS = (("타입", "재질", "치수"), ("무게", "전원"))
#: 치수는 읽지 않는다. 옵션마다 다르고 그림에서 재면 부정확하다 — 고정값이다.
SIZE_FIXED = "상세페이지 참조"


def esc(s: str) -> str:
    return html.escape(str(s or ""))


def data_uri(path: Path) -> str:
    ext = Path(path).suffix.lstrip(".").lower()
    mime = "image/png" if ext == "png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def render_page(page: Page) -> str:
    """메인 섹션을 HTML 로. 단순형 렌더러와 **완전히 따로** 둔다.

    고도몰 쪽 보고서의 금지선 5번과 같은 이유다 — *"기본형과 단순형의 렌더러를
    합치지 말 것. 격리가 회귀 0을 만든 장치다."* 우리도 단순형 49개를 지켜야 한다.

    legacy 의 ① HERO 와 ② KEY FEATURE 만 옮겼다. ④ Point · ⑤ SIZE 는 본문이
    맡으므로 안 그린다. legacy 의 ⑥ GODO MALL 푸터도 안 그린다 — 본문이 아래에
    이어 붙으므로 페이지 한가운데에 남의 상호가 박히면 안 된다.
    ③ 영문명 띠는 남겼다. 메인과 본문 사이의 이음매 노릇을 한다.
    """

    def dot(px: int) -> str:
        return f'<span class="dot" style="width:{px}px;height:{px}px"></span>'

    def img(path: Path | None, alt: str) -> str:
        return f'<img src="{data_uri(path)}" alt="{esc(alt)}">' if path else ""

    out = [f"<style>{CSS}</style>", '<div class="gpage">']

    # ① HERO — 제조사 우상단 · 누끼컷 중앙 · 상품명 · 영문명 · 스펙 · 패키지
    out.append('<header class="hero">')
    if page.maker:
        out.append(f'<p class="hero__maker">{esc(page.maker)}</p>')
    out.append('<div class="hero__wrap">')
    if page.main:
        out.append(f'<div class="hero__main">{img(page.main, page.name_kr)}</div>')
    out.append(f'<h1 class="hero__name">{esc(page.name_kr)}</h1>')
    if page.name_en:
        out.append(f'<p class="hero__en">{esc(page.name_en)}</p>')

    rows = [[(k, page.spec[k]) for k in row if page.spec.get(k)] for row in SPEC_ROWS]
    if any(rows):
        out.append('<div class="specs">')
        for row in rows:
            if not row:
                continue
            out.append('<div class="specs__row">')
            for k, v in row:
                out.append(
                    f'<div class="spec"><p class="spec__k">{esc(k)}{dot(9)}</p>'
                    f'<div class="spec__rule"></div>'
                    f'<p class="spec__v">{esc(v)}</p></div>'
                )
            out.append("</div>")
        out.append("</div>")

    if page.package:
        out.append(
            f'<div class="pkg"><div class="pkg__box">{img(page.package, "패키지")}</div>'
            f'<div class="pkg__bar">package desing</div></div>'
        )
    out.append("</div></header>")

    # ② KEY FEATURE — 좌 이미지 · 우 세 칸. 부제는 요약정보의 `특징`.
    out.append('<section class="sec">')
    out.append(dot(22))
    out.append('<h2 class="sec__h">KEY<br>FEATURE</h2>')
    if page.spec.get("특징"):
        out.append(f'<p class="sec__sub">{esc(page.spec["특징"])}</p>')
    out.append('<div class="keys">')
    out.append('<div class="keys__list">')
    for title, desc in page.keys[:3]:
        out.append(f'<div class="key"><p class="key__t">{dot(12)}{esc(title)}</p>')
        if desc:
            out.append(f'<p class="key__d">{esc(desc)}</p>')
        out.append("</div>")
    out.append("</div>")
    if page.feature:
        out.append(f'<div class="keys__fig">{img(page.feature, page.name_kr)}</div>')
    out.append("</div></section>")

    # ③ 영문명 띠 — 메인과 본문 사이의 이음매
    if page.name_en:
        out.append(f'<div class="band">{esc("  ·  ".join([page.name_en] * 6))}</div>')

    out.append("</div>")
    return "\n".join(x for x in out if x)


#: 모델에게 주는 지시. **자르기는 수학, 이해는 AI** — 조각은 우리가 냈고,
#: 어느 조각이 어느 자리에 어울리는지는 모델이 정한다.
#:
#: legacy 에서 Point 01·02 를 뺐다(본문이 맡는다). 대신 **메인이 어디서 끝나는가**
#: 를 묻는다 — 그 한 숫자가 메인과 본문을 가른다.
PROMPT = """쇼핑몰 상세페이지를 새 디자인으로 다시 짓는다. 원본에서 **재료만** 가져온다.

원본은 이미 완성된 디자인이라 그대로 옮기면 남의 쇼핑몰이 따라온다.
그림은 골라서 쓰고, 글은 원본이 적어 둔 사실에서만 가져온다.

**보내는 것**

    상품명 · 브랜드 · 원본에 직접 타이핑돼 있던 글 전문
    번호가 붙은 밴드 그림들. 번호 옆 괄호가 그 밴드의 종류다.
    첫 밴드들이 원본 맨 위(대표컷·요약정보·3줄요약·패키지)다.

**할 일 넷**

1. **요약정보** — 원본 맨 위 표에 적힌 그대로 옮긴다.
   `타입` `재질` `무게` `전원` 넷만. 없으면 빈 칸으로 둔다.
   **치수는 옮기지 마라** — 옵션마다 달라 따로 처리한다.

2. **핵심특징 3개** — 원본의 3줄 설명을 바탕으로 짧은 제목과 한 줄 설명을 짓는다.
   3줄이 모자라면 요약정보나 설명 글에서 보탠다. **없는 사실을 지어내지 마라.**
   제목은 한눈에 읽히게 짧게, 설명은 한 줄로.

3. **밴드마다 사실을 적는다** — 고르는 것은 우리가 한다. 너는 **본 것만** 말하라.
   판단하지 마라. "대표컷으로 좋다" 같은 말은 필요 없다.

   밴드 **전부**에 대해 한 줄씩, 아래 모양 그대로 적는다.

       "<번호>:<제품 개수>,<white|color>,<text|notext>,<hand|nohand>,<box|nobox>"

       제품 개수   그 밴드에 **제품이 몇 개 보이는가**. 같은 제품이 여러 각도로
                   찍혔으면 보이는 개수 그대로. 제품이 안 보이면 0.
                   (글자만 있는 띠, 배너, 표 → 0)
       white       배경이 **흰색·거의 흰색**이면 white, 색이 깔렸으면 color.
       text        밴드 안에 **글자**가 박혀 있으면 text, 없으면 notext.
                   제품·상자에 인쇄된 상표는 글자로 치지 않는다. 설명·라벨·치수만.
       hand        **사람의 손이나 몸**이 나오면 hand, 아니면 nohand.
       box         **판매용 종이·플라스틱 상자**가 화면에서 **뚜렷하게** 보이면 box.
                   상자가 화면의 한 귀퉁이에 살짝 걸쳐 있거나 제품 뒤로 조금
                   비치는 정도면 **nobox** 다. 상자가 주인공인 컷만 box 다.
                   **천 파우치·주머니·케이블·설명서는 상자가 아니다** — nobox.
                   상자 사진이 아예 없는 원본이 흔하다. 없으면 다 nobox 로 둬라.

   보기 — `"16:1,white,notext,nohand,nobox"` 는 16번 밴드에 제품 하나가 흰
   바탕에 놓였고 글자도 손도 상자도 없다는 뜻이다.

4. **메인과 본문의 경계** — `body_start` 에 숫자 하나.

   원본 맨 위의 **메인섹션**은 보통 이렇게 생겼다.

       대표컷 → 요약정보 표 → 3줄요약(큰 색 글씨) → 패키지 상자

   그 메인섹션이 끝나고 **본문**(제품특징 · Point · 기능 설명)이 시작되는
   **첫 밴드 번호**를 적어라. 그 번호의 밴드부터가 본문이다.
   메인섹션이 아예 없으면 0 을 적어라.

**밴드 종류와 쓰는 법**

    (PHOTO)    제품컷. 그림 자리에 먼저 쓴다
    (MIXED)    제품에 주석이 붙은 것. 차선으로 쓴다
    (UNKNOWN)  애매한 것. 다른 후보가 없을 때만 쓴다
    (TEXT)     글만 박힌 것. **읽는 근거로만** 쓰고 그림 자리에는 절대 넣지 마라.
    (PROMO)    쇼핑몰 홍보 움짤. 아무 자리에도 넣지 말고 근거로도 쓰지 마라.

**지킬 것**

  · 그림 번호는 **한 번씩만** 쓴다. 같은 컷을 두 자리에 넣지 마라.
  · 쓸 그림이 모자라면 비워라. 억지로 채우지 마라.

**돌려줄 것 — JSON 하나. 다른 말은 붙이지 마라.**

```json
{"타입":"","재질":"","무게":"","전원":"",
 "key1_t":"제목","key1_d":"한 줄 설명",
 "key2_t":"","key2_d":"",
 "key3_t":"","key3_d":"",
 "facts":["0:0,white,text,nohand,nobox",
          "1:1,color,notext,nohand,nobox",
          "2:6,white,notext,nohand,nobox"],
 "body_start":7,
 "notes":[]}
```

`facts` 에는 **밴드를 하나도 빼지 말고 전부** 넣는다. 번호는 0 부터 차례대로다.
빠뜨린 밴드는 우리가 아예 못 쓴다.

**중괄호를 또 만들지 마라.** `facts` 와 `notes` 만 배열이고, 그 안에는
**글자 한 줄씩**만 들어간다. 배열 안에 `{` 를 쓰지 마라.
"""

#: 라벨을 못 받았을 때의 기본값. 차단하지 않는다.
UNKNOWN_KIND = "UNKNOWN"
#: 모델에 보낼 때 긴 변을 이만큼으로 줄인다.
SEND_PX = 900


def parts_for(name: str, brand: str, typed: str, cuts: list[Path],
              kinds: list[str]) -> list[tuple[str, str]]:
    """모델에 보낼 것을 순서대로 쌓는다 — 글 먼저, 그다음 번호·종류·그림.

    **차단이 아니라 순위다.** 처음에는 쓸 만한 것만 골라 보냈는데, 밴드 21개 중
    3개만 남아서 그림 자리가 거의 비었다. 전부 보내고 종류만 붙인다.

    제품컷을 TEXT 로 오판하지 않는 것이 최우선이라 애매하면 MIXED·UNKNOWN 으로
    남는다. 그러면 모델이 보고 판단할 기회가 있다.
    """
    head: list[tuple[str, str]] = [
        ("text", PROMPT),
        ("text", f"상품명: {name}\n브랜드: {brand}\n\n원본에 타이핑돼 있던 글:\n{typed}"),
        ("text", f"밴드 {len(cuts)}장을 위에서 아래 순서로 봅니다. 괄호 안이 그 밴드의 종류입니다."),
    ]
    for i, p in enumerate(cuts):
        kind = kinds[i] if i < len(kinds) else UNKNOWN_KIND
        head.append(("text", f"[{i}]({kind})" + (" · 원본 맨 위" if i == 0 else "")))
        # 보내기 전에 줄인다. 토큰도 아끼고 전송도 안정된다 — 읽을 글자는 살아 있다.
        with Image.open(p) as im:
            im = im.convert("RGB")
            if max(im.size) > SEND_PX:
                s = SEND_PX / max(im.size)
                im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
        head.append(("image", base64.b64encode(buf.getvalue()).decode()))
    return head


def take(reply: str, cuts: list[Path], kinds: list[str],
         hashes: list[int] | None = None,
         options: int = 1) -> tuple[Page, list[str]]:
    """모델이 돌려준 것을 받는다. **모델은 사실만 말하고 고르는 것은 코드다.**

    `options` 는 엑셀 옵션 열에서 온 옵션 수다(없으면 1). 그림에서 세지 않는다.
    """
    m = re.search(r"\{[\s\S]*\}", reply or "")
    if not m:
        return Page(), ["모델이 JSON 을 안 돌려줬다"]
    try:
        got = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return Page(), [f"JSON 을 못 읽었다: {e}"]

    notes = [str(x) for x in got.get("notes") or []]
    hashes = hashes or []

    spec = {k: str(v).strip() for k, v in (got.get("spec") or {}).items() if str(v).strip()}
    for k in ("타입", "재질", "무게", "전원", "특징"):
        if str(got.get(k, "")).strip():
            spec[k] = str(got[k]).strip()
    spec["치수"] = SIZE_FIXED

    keys = [(str(got.get(f"key{n}_t", "")).strip(), str(got.get(f"key{n}_d", "")).strip())
            for n in (1, 2, 3)]
    keys = [(t, d) for t, d in keys if t][:3]

    page = Page(spec=spec, keys=keys)
    facts = parse_facts(got.get("facts"))
    if not facts:
        notes.append("모델이 밴드 사실을 안 줬다 — 세 자리가 다 빈다")
    mi, fi, pi, pick_notes = choose(facts, kinds, hashes, options)
    notes += pick_notes
    page.main = cuts[mi] if 0 <= mi < len(cuts) else None
    page.feature = cuts[fi] if 0 <= fi < len(cuts) else None
    page.package = cuts[pi] if 0 <= pi < len(cuts) else None
    page.main_band, page.feature_band, page.package_band = mi, fi, pi

    bs = got.get("body_start")
    page.body_start = bs if isinstance(bs, int) and 0 <= bs < len(cuts) else -1
    if page.body_start < 0 and bs is not None:
        notes.append(f"body_start 가 범위 밖이다: {bs!r}")
    return page, notes


def is_promo(arr: np.ndarray, url: str = "") -> bool:
    """바나나몰이 직접 찍어 붙인 홍보 움짤인가.

    색을 못박지 않고 **네 변에 같은 띠가 둘러져 있는가**로 센다. 실측 —
    홍보 GIF 는 네 변 파랑 80~86%, 상품 이미지는 네 변 모두 0%.
    """
    if not url.lower().endswith(".gif"):
        return False
    h, w, _ = arr.shape
    if w / max(1, h) < 1.2:  # 홍보 움짤은 가로형이다
        return False
    t = max(4, int(min(h, w) * 0.015))
    a = arr.astype(np.int32)

    def blue(x: np.ndarray) -> float:
        r, g, b = x[..., 0], x[..., 1], x[..., 2]
        return float(((b > 120) & (b > r + 35) & (b > g + 25)).mean())

    return min(blue(a[:t]), blue(a[-t:]), blue(a[:, :t]), blue(a[:, -t:])) >= 0.5


#: HERO 자리는 한 칸이다. 세로로 긴 컷을 그대로 넣으면 화면을 다 잡아먹고,
#: 가로로 넓은 컷을 넣으면 배너처럼 납작해진다. 그래서 **다시 앉힌다.**
HERO_W = 1000          #: 다시 앉힐 캔버스의 폭
HERO_FILL = 0.86       #: 제품이 캔버스에서 차지할 몫
HERO_MAX = 1.25        #: 세로가 가로의 이만큼을 넘으면 거기서 멈춘다 (4:5)
HERO_MIN = 0.45        #: 너무 납작하면 배너로 보인다. 여기까지만 눕힌다


def reframe(src: Path, out: Path, bg: tuple[int, int, int] = (255, 255, 255)) -> Path:
    """대표컷을 HERO 자리에 맞게 다시 앉힌다.

    조각의 비율이 제각각이다. 559×866 짜리 세로 컷을 그대로 넣으면 기둥이 된다
    (legacy ⓔ). **원본 이미지를 고치는 것이 아니다** — 잘라 둔 조각을 우리 자리에
    앉히는 것이다. 제품은 그대로 두고 둘레의 여백만 새로 잡는다.
    """
    with Image.open(src) as im:
        im = im.convert("RGB")
        arr = np.asarray(im)

    # 제품이 실제로 놓인 자리부터 찾는다. 조각에 남은 바깥 여백은 버린다.
    a = arr.astype(np.int32)  # uint8 로 곱하면 넘친다
    lum = (a[..., 0] * 299 + a[..., 1] * 587 + a[..., 2] * 114) // 1000
    solid = lum < 232
    ys, xs = np.where(solid.any(1)), np.where(solid.any(0))
    if not len(ys[0]) or not len(xs[0]):
        return src
    y0, y1 = int(ys[0][0]), int(ys[0][-1])
    x0, x1 = int(xs[0][0]), int(xs[0][-1])
    body = Image.fromarray(arr[y0 : y1 + 1, x0 : x1 + 1])

    # 캔버스 비율 — **제품 비율을 그대로 두되 양 끝만 막는다.**
    ratio = body.height / max(1, body.width)
    hw = min(max(ratio, HERO_MIN), HERO_MAX)
    canvas = Image.new("RGB", (HERO_W, int(HERO_W * hw)), bg)

    room = (int(canvas.width * HERO_FILL), int(canvas.height * HERO_FILL))
    s = min(room[0] / body.width, room[1] / body.height)
    body = body.resize((max(1, int(body.width * s)), max(1, int(body.height * s))), Image.LANCZOS)
    canvas.paste(body, ((canvas.width - body.width) // 2, (canvas.height - body.height) // 2))
    canvas.save(out, quality=92)
    return out
