"""기본형 전용 화면. 단순형 화면(app/static/index.html)과 따로 산다.

    /basic                  화면
    /api/basic/excel        엑셀 올리기 → 상품 목록
    /api/basic/convert      상품 하나 변환 → out/basic_<상품번호>/index.html
    /basic/out/<상품번호>     미리보기
    /basic/out/<상품번호>/file  내려받기

흐름 — **상품당 AI 2콜.**

    엑셀 행 → 상세 이미지(gif·공통장식 제외)
      → bands.read 로 전부 밴드로 자른다 (번호는 이미지를 넘어서 이어진다)
      → 【1콜】 main.parts_for + PROMPT → main.take
                spec · keys · main · feature · package · body_start
      → 메인  = main.render_page
      → 본문  = body_start 이후 밴드만 body.sections
      → 【2콜】 read_text — **본문 글자 조각만.** 메인 것은 1콜에서 이미 나왔다
      → 한 파일: 메인 HTML + 본문 HTML (둘 다 폭 860)

단순형에서 빌려 쓰는 것은 **읽기 전용 다섯**뿐이다 — 엑셀 파서(app.excel),
상세설명 파서(app.source), 받아 두기(app.convert.fetch), 상품명 가르기
(app.render.split_name), 키 찾기(app.llm). 단순형의 변환·배치·렌더는 안 부른다.

app.server 를 가져오지 않는다. server 가 이쪽을 붙이므로 서로 가져오면 원이 된다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import traceback
import urllib.request
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from PIL import Image
from pydantic import BaseModel

from app import convert as _convert
from app import excel as _excel
from app import llm as _llm
from app import render as _apprender
from app import source as _source

from collections import Counter
from dataclasses import dataclass

from . import bands as B
from . import blobs, body, boundary, main, read_text, render

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parent.parent
WORK = Path(os.environ.get("CONVERTER_WORK", ROOT / "work"))
CACHE = WORK / "_cache"
OUT = ROOT / "out"

router = APIRouter()

#: 올린 엑셀. 단순형의 SHEETS 와 섞지 않는다 — 화면이 둘이면 통도 둘이다.
SHEETS: dict[str, "_excel.Sheet"] = {}

#: 움직이는 그림은 본문 조각으로 못 쓴다. 밴드로 자르면 첫 장만 남아 뜻이 깨진다.
SKIP_EXT = (".gif",)


def body_images(row) -> tuple[list[str], list[str]]:
    """(쓸 이미지, 뺀 것과 이유).

    공통 장식·배너는 app.source 가 이미 걷어낸다(`banana_img/conf/` 따위).
    여기서 더 빼는 것은 gif 뿐이다.
    """
    parsed = _source.parse(row.body)
    use, skipped = [], []
    for url in parsed.images:
        if Path(url.split("?")[0]).suffix.lower() in SKIP_EXT:
            skipped.append(f"{url}  ← 움직이는 그림")
            continue
        use.append(url)
    skipped += [f"{u}  ← 공통 장식" for u in parsed.dropped]
    skipped += [f"{u}  ← 깨진 주소" for u in parsed.broken]
    return use, skipped


def plain_en(name: str) -> str:
    """영문명의 **바깥 괄호**만 벗긴다 — `(Finger Wiggle …)` → `Finger Wiggle …`.

    상품명에서 갈라 온 영문명은 괄호째 딸려 온다. 그대로 띠에 늘어놓으면
    `(Pretty Love Bruse)  ·  (Pretty Love Bruse)  ·  …` 가 되어 괄호만 눈에 띈다.
    안쪽 괄호는 건드리지 않는다 — 이름의 일부일 수 있다.
    """
    t = (name or "").strip()
    while len(t) > 1 and t.startswith("(") and t.endswith(")"):
        t = t[1:-1].strip()
    return t


def option_count(row) -> int:
    """옵션이 몇 개인 상품인가. **엑셀이 말해 주는 사실**이다.

    그림에서 세지 않는다 — 엑셀 옵션 열에 답이 적혀 있는데 픽셀로 짐작할 이유가
    없다. 대표컷이 "제품 1개 또는 옵션 수와 같음" 이어야 하는데, 다일레이터는
    옵션이 여섯이라 여섯이 다 보이는 컷이거나 하나짜리 단독컷이어야 한다.
    묶음 옵션은 빼고 센다. 유컵스 옵션 열은 `그린 · 퍼플 · 블루 · 퍼플+그린+블루`
    로 넷인데, 마지막은 셋을 묶어 파는 것이라 **제품 종류는 셋**이다. 상세페이지에
    나란히 놓인 것도 셋이다. 묶음까지 세면 "옵션 수와 같은 컷" 이 영영 없다.
    옵션 열이 비면 1 로 본다.
    """
    single = {v.strip() for v in (getattr(row, "option_values", []) or [])
              if v.strip() and "+" not in v}
    return max(1, len(single))


def typed_text(row) -> str:
    """원본에 직접 타이핑돼 있던 글. 모델에게 **읽는 근거**로 준다."""
    parsed = _source.parse(row.body)
    lines = [b.text for b in parsed.lead_blocks if b.text.strip()]
    lines += [p.caption for p in parsed.pieces if p.caption.strip()]
    return "\n".join(lines).strip()


#: 같은 입력이면 같은 답이 나오게 못박는 값. `seed` 는 OpenAI 가 받는다.
PIN = {"temperature": 0, "top_p": 1, "seed": 7}


def _pin(payload: bytes) -> bytes:
    """모델 답을 **되풀이 가능하게** 만든다.

    기본값으로 부르면 같은 밴드를 넣어도 대표컷이 돌릴 때마다 바뀐다(유컵스에서
    실제로 그랬다). 그러면 기준선이 잴 수 있는 것이 없다 — 우리가 코드를 고쳐서
    바뀐 건지 모델이 흔들린 건지 못 가른다.

    `app/llm.py` 는 안 건드린다. 어댑터가 만들어 준 몸통에 값만 얹는다 —
    회사가 바뀌어도 어댑터 한 파일로 끝나는 구조를 깨지 않으려고.
    """
    try:
        body = json.loads(payload)
    except json.JSONDecodeError:
        return payload
    body.update(PIN)
    return json.dumps(body).encode()


def _facts_of(reply: str):
    """모델 답에서 `facts` 만 꺼낸다. 빈칸을 메울 때 다시 고르려고."""
    m = re.search(r"\{[\s\S]*\}", reply or "")
    if not m:
        return []
    try:
        return json.loads(m.group(0)).get("facts") or []
    except json.JSONDecodeError:
        return []


#: 대표컷·키피쳐가 빈칸이면 이 순서로 조건을 하나씩 푼다.
#: 다 만족하는 밴드가 없다고 빈칸으로 두면, 모델 답이 조금만 달라져도 페이지가
#: 통째로 무너진다(다일레이터가 실제로 그랬다). **자리는 반드시 찬다.**
RELAX = ("옵션 수", "전체 보임", "손 없음")


def _loosen(facts: dict[int, "main.Facts"], step: str) -> dict[int, "main.Facts"]:
    """조건 하나를 푼 사실 사본. **원본은 안 건드린다.**

    `main.py` 는 얼려 둔 파일이라 `choose` 에 손대지 않는다. 대신 **사실을 풀어서**
    같은 `choose` 를 다시 부른다 — 옵션 수를 풀려면 제품 개수를 1로, 전체 보임을
    풀려면 full 을 참으로, 손 없음을 풀려면 hand 를 거짓으로 적어 준다.
    고르는 규칙은 그대로 두고 **입력만** 느슨해지는 셈이다.
    """
    import copy

    got = copy.deepcopy(facts)
    for f in got.values():
        if step == "옵션 수" and f.products >= 1:
            f.products = 1
        elif step == "전체 보임":
            f.full = True
        elif step == "손 없음":
            f.hand = False
    return got


def choose_never_blank(facts, kinds, hashes, options):
    """(대표컷, 키피쳐, 패키지, 메모). **대표컷·키피쳐는 빈칸으로 두지 않는다.**"""
    hero, feat, pkg, notes = main.choose(facts, kinds, hashes, options)
    loose = facts
    for step in RELAX:
        if hero >= 0 and feat >= 0:
            break
        loose = _loosen(loose, step)
        h2, f2, _p2, _n2 = main.choose(loose, kinds, hashes, options)
        if hero < 0 and h2 >= 0:
            hero = h2
            notes.append(f"대표컷 — 조건 「{step}」 을 풀고 다시 골랐다 → 밴드 [{hero}]")
        if feat < 0 and f2 >= 0 and f2 != hero:
            feat = f2
            notes.append(f"키피쳐 — 조건 「{step}」 을 풀고 다시 골랐다 → 밴드 [{feat}]")
    if hero < 0:
        notes.append("대표컷 — 조건을 다 풀어도 쓸 밴드가 없다")
    if feat < 0:
        notes.append("키피쳐 — 조건을 다 풀어도 쓸 밴드가 없다")
    return hero, feat, pkg, notes


#: 덩어리에 그리는 빨간 네모와 번호표. 번호는 크게 그린다 — 작게 그렸더니 모델이
#: 옆 번호로 잘못 읽어 글이 한 칸씩 밀렸다.
MARK_RED, MARK_PEN, MARK_TAG = (220, 0, 0), 2, 24
#: 글자 크기를 되짚는 값. 한글 글자는 제 크기의 이만큼만 잉크로 채운다.
#: 잰 잉크 높이를 이것으로 나눠야 원본과 같은 크기가 된다.
INK_FILL = 0.72


def _tag_font():
    from PIL import ImageFont

    for name in ("malgunbd.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, MARK_TAG)
        except OSError:
            continue
    return ImageFont.load_default()


def blob_sheet(band: Path, found: list, dest_dir: Path) -> Path:
    """덩어리마다 **빨간 네모와 번호**를 그린 그림. 모델에게 이것을 보여 준다."""
    from PIL import ImageDraw

    im = Image.open(band).convert("RGB")
    d = ImageDraw.Draw(im)
    font = _tag_font()
    for b in found:
        x0, y0, x1, y1 = b.box
        d.rectangle([x0 - 1, y0 - 1, x1, y1], outline=MARK_RED, width=MARK_PEN)
        tx, ty = max(0, x0 - MARK_TAG - 6), max(0, y0 - 2)
        d.rectangle([tx, ty, tx + MARK_TAG + 4, ty + MARK_TAG + 4],
                    fill=(255, 255, 255), outline=MARK_RED, width=2)
        d.text((tx + 4, ty + 1), str(b.n), fill=MARK_RED, font=font)
    f = dest_dir / f"{band.stem}.jpg"
    im.save(f, quality=92)
    return f


def wrap_of(b, found: list) -> list:
    """그 덩어리를 **감싼 상자·테두리·배지**. 글자와 함께 덮는다.

    글자를 두른 네모나 알약 배지는 글자와 붙어 있지 않아 따로 덩어리가 된다.
    글자만 덮고 테두리를 남기면 빈 네모가 떠 있게 된다.
    """
    return [o for o in found if o.n != b.n and (b.inside(o) or o.inside(b))]


def relabel(key: str, body_files: list[Path], kinds_of: dict, assets: Path,
            notes: list[str]):
    """사진에 박힌 글을 **덮고 그 자리에 다시 쓴다.** `(밴드 파일, {밴드: [Mark…]})`.

    묻는 것은 하나뿐이다 — **이 덩어리가 글자냐 아니냐.** 지울지 말지는 안 묻는다.
    그건 아래 순서가 정한다.

        ① 덩어리로 나눈다 (`blobs.split` — 1px 깎아 지시선을 끊고 되돌린다)
        ② 모델에게 번호마다 글자냐고 묻는다
        ③ 글자라고 한 덩어리 중 **제자리에 다른 덩어리 픽셀이 있는 것**은 건너뛴다
           — 제품 사진 위에 얹힌 글이다. 덮으면 사진이 뚫린다
        ④ 남은 것을 감싼 상자·테두리·배지까지 배경색으로 덮고, 그 자리와 잉크 높이를
           적어 둔다. 덮은 자리에 우리 폰트로 그 글을 다시 쓴다

    지시선은 어느 덩어리에도 안 속하므로 덮이지 않는다. 규칙을 따로 안 써도 남는다.
    """
    files = list(body_files)
    shots = [n for n, k in kinds_of.items() if k == body.SHOT and 0 <= n < len(files)]
    if not shots or not key:
        if shots:
            notes.append(f"글이 박힌 밴드 {len(shots)}장은 안 물어봤다 — 키가 없다")
        return files, {}

    # 번호를 그린 그림은 **물어보는 데만** 쓴다. 결과에 섞이면 빨간 네모가 페이지에
    # 그대로 실린다. 딴 방에 그렸다가 묻고 나서 방째로 버린다.
    ask_dir = assets / "_ask"
    ask_dir.mkdir(parents=True, exist_ok=True)
    seen: dict[int, tuple] = {}
    sheets = []
    for n in shots:
        arr = np.asarray(Image.open(files[n]).convert("RGB"))
        bg = blobs.modal_color(arr)
        lab, found = blobs.split(arr, bg)
        if found:
            seen[n] = (arr, bg, lab, found)
            sheets.append((n, blob_sheet(files[n], found, ask_dir)))
    if not sheets:
        shutil.rmtree(ask_dir, ignore_errors=True)
        return files, {}

    said = read_text.read_blobs(key, sheets)
    shutil.rmtree(ask_dir, ignore_errors=True)
    marks: dict[int, list] = {}
    done = skipped = 0
    for n, (arr, bg, lab, found) in seen.items():
        words = said.get(n, {})
        letters = [b for b in found if b.n in words]
        rest = [b for b in found if b.n not in words]
        photos = [b for b in found if blobs.is_photo(arr, lab, b)]
        # **덮은 자리만 목록에 들어간다.** 덮기와 다시 쓰기를 따로 판정하면, 못 덮은
        # 자리에도 새 글자가 그려져 원본 글자와 겹친다. 목록은 하나뿐이다.
        covered = []
        for b in letters:
            ink = blobs.ink_height(lab, b)
            if b in photos:
                skipped += 1          # 제품 사진이다. 모델이 뭐라 했든 안 건드린다
                continue
            if not blobs.fits(b, words[b.n], ink):
                skipped += 1          # 그 자리에 안 들어가는 글이다 — 번호를 잘못 짚었다
                continue
            wrap = wrap_of(b, found)
            box = blobs.union([b.box, *(w.box for w in wrap)])
            others = [o for o in rest if o not in wrap] + [p for p in photos if p is not b]
            if blobs.sits_on(lab, box, others):
                skipped += 1          # 남의 픽셀이 그 안에 있다. 칠하면 그것까지 지워진다
                continue
            covered.append((box, words[b.n], ink))
        if not covered:
            continue
        flat = blobs.cover(arr, [c[0] for c in covered], bg)
        f = assets / f"{files[n].stem}_flat.jpg"
        Image.fromarray(flat).save(f, quality=92)
        files[n] = f
        marks[n] = [body.Mark(x0, y0, x1 - x0, y1 - y0, text, ink)
                    for (x0, y0, x1, y1), text, ink in covered]
        done += 1
    if done:
        notes.append(f"사진에 박혀 있던 글 {sum(len(v) for v in marks.values())}덩어리를 "
                     f"밴드 {done}장에서 덮고 제자리에 다시 썼다")
    if skipped:
        notes.append(f"글 {skipped}덩어리는 제품 사진 위에 놓여 있다 — 손대지 않았다")
    return files, marks


def refine(key: str, body_files: list[Path], kinds_of: dict, texts_of: dict,
           assets: Path, notes: list[str]):
    """모델 답을 한 번 더 다듬는다. 하는 일은 **하나**뿐이다 —
    `title` 이라고 해 놓고 글을 안 준 밴드를 다시 묻는다. 그래도 없으면
    `pieces_from` 이 그림으로 싣는다.

    **사진에 글이 박힌 밴드는 손대지 않는다.** 자르지도 덮지도 않고 통째로 싣는다.
    여기서 세 가지를 해 봤고 셋 다 원본보다 나빴다.

        가로 되자르기   글이 사진 밑에 붙은 밴드를 촘촘한 여백으로 갈랐다.
                      갈리지 않는 밴드가 더 많았고, 갈린 곳은 지시선이 끊겼다.
        세로 되자르기   글이 사진 옆에 있는 밴드를 세로로 갈랐다.
                      핑거위글 버튼 도해가 반으로 갈려 분홍 지시선과 라벨이 갈라졌다.
        덮고 다시 얹기  글자 픽셀을 배경색으로 덮고 그 자리에 읽은 글을 얹었다.
                      문단은 글줄이 세로로 이어져 한 덩어리가 되는데, 글줄을 고르는
                      거르개가 높이 70을 넘는 덩어리를 버려서 **문단이 통째로 안
                      잡혔다.** 남은 것은 제품 위 부스러기 둘뿐이었고, 거기를 덮고
                      거기에 5px 짜리 글을 얹었다 — 본문은 그대로인데 사진만
                      지저분해졌다.

    셋 다 공통점이 있다. **원본은 사진과 글을 한 덩어리로 짜 놓은 디자인**인데,
    우리가 그 덩어리를 반쯤 뜯으면 뜯긴 자국만 남는다. 통째로 실으면 손님은 원본
    그대로를 본다. 그 글이 우리 글이 아니라는 것 말고는 잃는 것이 없다.
    """
    ask = [n for n, k in kinds_of.items()
           if k == body.TITLE and not texts_of.get(n, "").strip()]
    if not ask:
        return list(body_files), dict(kinds_of), dict(texts_of)

    kinds, texts = dict(kinds_of), dict(texts_of)
    if key:
        notes.append(f"글 없는 제목 {len(ask)}장을 다시 물었다")
        k2, t2 = read_text.read(key, [body_files[n] for n in ask])
        for j, n in enumerate(ask):
            if j in k2:
                kinds[n] = k2[j]
            if j in t2:
                texts[n] = t2[j]
    else:
        notes.append(f"글 없는 제목 {len(ask)}장은 다시 못 물었다 — 키가 없다")
    return list(body_files), kinds, texts


def ask_model(key: str, parts, timeout: int = 240, tries: int = 2) -> str:
    """모델에 물어본다. **JSON 이 깨져 오면 한 번 더 부른다.**

    다일레이터에서 모델이 `keys` 배열의 닫는 괄호를 빼먹고 보냈다. 그러면 답이
    통째로 버려져 대표컷·키피쳐·패키지가 전부 빈칸이 된다. 고쳐 쓰려 들면
    (괄호를 우리가 채워 넣으면) 무엇을 고쳤는지 모르게 되니, 그냥 다시 묻는다.
    """
    url, headers, payload = _llm.build(key, parts, max_tokens=4000)
    payload = _pin(payload)
    text = ""
    for n in range(tries):
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            got = json.loads(r.read())
        text, _stop = _llm.extract(key, got)
        m = re.search(r"\{[\s\S]*\}", text or "")
        if m:
            try:
                json.loads(m.group(0))
                return text
            except json.JSONDecodeError:
                pass
        print(f"[basic] 모델 답의 JSON 이 깨졌다 — 다시 묻는다 ({n + 1}/{tries})", flush=True)
    return text


class ConvertReq(BaseModel):
    sheet: str
    row: int
    #: 켜면 AI 를 아예 안 부른다 — 경계는 예비 규칙, 글자는 원본 조각 그대로.
    raw: bool = False


@router.post("/api/basic/excel")
async def api_basic_excel(file: UploadFile):
    try:
        sheet = _excel.load(await file.read())
    except Exception as e:
        raise HTTPException(400, f"엑셀을 읽지 못했다: {e}") from e
    key = f"b{len(SHEETS)}_{re.sub(r'[^A-Za-z0-9]', '', file.filename or 'x')[:20]}"
    SHEETS[key] = sheet
    rows = []
    for i, r in enumerate(sheet.rows):
        use, skipped = body_images(r)
        rows.append({"i": i, "code": r.code, "name": r.name,
                     "images": len(use), "skipped": len(skipped)})
    return {"sheet": key, "rows": rows, "missing": getattr(sheet, "missing", [])}


def cut_bands(files: list[Path], assets: Path):
    """이미지들을 순서대로 밴드로 자른다. **번호는 이미지를 넘어서 이어진다.**

    돌려주는 것 넷 — (밴드+이미지번호, 밴드 그림 파일, 종류, dHash).
    종류는 `bands.classify` 가 붙인 것에 홍보 움짤 판정을 얹는다.
    """
    entries: list[boundary.Entry] = []
    cuts: list[Path] = []
    kinds: list[str] = []
    hashes: list[int] = []
    for gi, f in enumerate(files):
        arr = np.asarray(Image.open(f).convert("RGB"))
        promo = main.is_promo(arr, f.name)
        for b in B.read(arr):
            n = len(cuts)
            path = assets / f"band_{n:03d}.jpg"
            Image.fromarray(arr[b.y : b.y + b.height]).save(path, quality=90)
            entries.append(boundary.Entry(b, gi))
            cuts.append(path)
            kinds.append("PROMO" if promo else b.kind)
            hashes.append(b.dhash)
    return entries, cuts, kinds, hashes


def rects_by_band(files: list[Path], entries: list[boundary.Entry]) -> dict[int, main.Rect]:
    """밴드 번호 → 알맹이 자리. 자르는 데만 쓴다 — 재서 고르는 일은 없어졌다."""
    got: dict[int, main.Rect] = {}
    off = 0
    for gi, f in enumerate(files):
        n = sum(1 for e in entries if e.image == gi)
        got.update(main.rects(np.asarray(Image.open(f).convert("RGB")), offset=off))
        off += n
    return got


def crop_slot(cuts: list[Path], entries: list[boundary.Entry],
              shots: dict[int, main.Rect], band: int, dest: Path) -> Path | None:
    """밴드에서 **알맹이만** 잘라 낸다. 세 자리 모두 같은 방식이다.

    밴드는 늘 폭 전체라 라벨 띠·배경 띠가 같이 딸려 온다. 죠우무의 패키지 자리에
    광고 배너의 좌우 색띠가 통째로 들어간 것이 이것 때문이었다. 대표컷만 `reframe`
    이 알맹이를 찾아 다시 앉히고 있었고, 키피쳐·패키지는 밴드째 쓰고 있었다.
    """
    if band < 0 or band >= len(cuts):
        return None
    src = cuts[band]
    r = shots.get(band)
    if r is None:
        return src
    top = entries[band].band.y
    with Image.open(src) as im:
        im = im.convert("RGB").crop((r.x0, max(0, r.y0 - top), r.x1 + 1, r.y1 - top + 1))
        im.save(dest, quality=92)
    return dest


@router.post("/api/basic/convert")
def api_basic_convert(req: ConvertReq):
    sheet = SHEETS.get(req.sheet)
    if sheet is None or not (0 <= req.row < len(sheet.rows)):
        raise HTTPException(400, "먼저 엑셀을 올려야 한다")
    row = sheet.rows[req.row]
    if not row.code:
        raise HTTPException(400, "상품번호가 없는 행이다")

    urls, skipped = body_images(row)
    if not urls:
        raise HTTPException(400, "쓸 이미지가 없다 (공통 장식·gif 를 빼고 나니 0장)")

    out = OUT / f"basic_{row.code}"
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []

    try:
        # ① 받아 두기 — 단순형과 같은 통. 같은 그림을 두 번 받지 않는다.
        files = []
        for n, url in enumerate(urls):
            data = _convert.fetch(url, CACHE)
            f = out / f"src_{n:02d}{Path(url.split('?')[0]).suffix.lower() or '.jpg'}"
            f.write_bytes(data)
            files.append(f)

        # ② 밴드로 자른다 (AI 0콜)
        entries, cuts, kinds, hashes = cut_bands(files, assets)

        # ③ 【1콜】 메인 — spec · keys · 그림 셋 · body_start
        key = "" if req.raw else _llm.key_from_env()
        _tags, name_kr, name_en = _apprender.split_name(row.name)
        page = main.Page(name_kr=name_kr or row.name, name_en=plain_en(name_en),
                         maker=row.brand or row.maker)
        shots = rects_by_band(files, entries)
        opts = option_count(row)
        if key:
            reply = ask_model(key, main.parts_for(row.name, page.maker, typed_text(row), cuts, kinds))
            got, ai_notes = main.take(reply, cuts, kinds, hashes, options=opts)
            if got.main_band < 0 or got.feature_band < 0:
                h, fe, _pk, more = choose_never_blank(
                    main.parse_facts(_facts_of(reply)), kinds, hashes, opts)
                got.main_band = h if got.main_band < 0 else got.main_band
                got.feature_band = fe if got.feature_band < 0 else got.feature_band
                got.main = cuts[got.main_band] if 0 <= got.main_band < len(cuts) else None
                got.feature = cuts[got.feature_band] if 0 <= got.feature_band < len(cuts) else None
                ai_notes += [n for n in more if "조건" in n]
            got.name_kr, got.name_en, got.maker = page.name_kr, page.name_en, page.maker
            head, page, notes = notes, got, ai_notes
            notes[:0] = head
            notes.insert(0, f"{_llm.label(key)} 1콜 — 밴드 {len(cuts)}장을 보냈다")
        else:
            notes.append("키가 없어 AI 를 안 불렀다 — 메인 스펙·핵심특징은 비고, 경계는 예비 규칙으로 잡는다")
            page.body_start = -1

        # ④ 경계 — 모델 답이 없거나 범위 밖이면 예비 규칙
        fallback, why = boundary.find_body_start(entries)
        if page.body_start < 0:
            page.body_start = fallback
            notes.append(why)
            source_of_start = "예비 규칙"
        else:
            source_of_start = "AI"
            notes.append(f"{why} (AI 는 {page.body_start} 라고 했다)")

        # **코드는 고르지 않는다.** 모델이 후보를 줘야 자리가 찬다.
        # 키가 없으면 대표컷·키피쳐는 빈칸이다. 예전에는 여기서 코드가 페이지를
        # 훑어 대신 골랐는데, 그 '대신 고르기' 가 6칸 격자를 대표컷으로 세웠다.
        if page.main is None:
            notes.append("대표컷이 비었다 — 모델 후보가 없거나 셋 다 떨어졌다")

        # ⑤ 세 자리 모두 알맹이만 자른다. 대표컷은 그 위에 HERO 자리 재배치까지.
        page.feature = crop_slot(cuts, entries, shots, page.feature_band, assets / "feature.jpg")
        page.package = crop_slot(cuts, entries, shots, page.package_band, assets / "package.jpg")
        cut_main = crop_slot(cuts, entries, shots, page.main_band, assets / "main_cut.jpg")
        if cut_main is not None:
            page.main = main.reframe(cut_main, assets / "hero.jpg")

        # ⑥ 본문 — body_start 이후 밴드. **자르기는 이미 끝났다.**
        body_files = [cuts[n] for n in range(page.body_start, len(cuts))]

        # ⑦ 【2콜】 본문 밴드마다 **무엇인지와 글**을 받는다
        if key and body_files:
            kinds_of, texts_of = read_text.read(key, body_files)
            if kinds_of:
                notes.append(f"{_llm.label(key)} 2콜 — 본문 밴드 {len(body_files)}장의 "
                             "종류와 글을 받았다")
            else:
                notes.append("본문 답을 못 읽었다 — 밴드를 사진으로 두고 그대로 싣는다")
        else:
            kinds_of, texts_of = {}, {}
            if body_files:
                notes.append(f"본문 밴드 {len(body_files)}장은 안 물어봤다 — 그대로 싣는다")

        body_files, kinds_of, texts_of = refine(
            key, body_files, kinds_of, texts_of, assets, notes)
        body_files, marks_of = relabel(key, body_files, kinds_of, assets, notes)
        pieces = body.pieces_from(kinds_of, texts_of, [f.name for f in body_files],
                                  marks_of)
        seen = Counter(p.kind for p in pieces)
        notes.append("본문 종류 — " + " · ".join(
            f"{k} {seen[k]}" for k in ("title", "body", "photo", "shot", "decor") if seen[k]))

        # ⑧ 한 파일 — 메인 + 본문. 둘 다 폭 860.
        if body.mostly_shots(pieces):
            notes.append("본문의 3분의 2 넘게 **글자가 박힌 사진**이다 — "
                         "자르지 않고 원본을 통째로 싣는다")
            body_html = render.render_whole(files)
            secs = []
        else:
            secs = body.sections(pieces)
            body_html = render.render(secs, assets)
        html = ('<!doctype html><meta charset="utf-8">'
                '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/'
                'pretendard@v1.3.9/dist/web/static/pretendard.min.css">'
                + main.render_page(page) + body_html)
        (out / "index.html").write_text(html, encoding="utf-8", newline="\n")
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"변환 실패: {e}") from e

    log = [f"밴드 {len(cuts)}개 · body_start {page.body_start}({source_of_start})"
           f" → 본문 밴드 {len(pieces)}개 · 섹션 {len(secs)}개"]
    log += [f"  [{i:3}] img{e.image} y={e.band.y:6d} h={e.band.height:5d} {k:8}"
            f"{'  ← 본문 시작' if i == page.body_start else ''}"
            for i, (e, k) in enumerate(zip(entries, kinds))]
    (out / "log.txt").write_text("\n".join(log), encoding="utf-8")

    return {"ok": True, "code": row.code, "name": row.name,
            "used": urls, "skipped": skipped,
            "bands": len(cuts), "body_start": page.body_start,
            "body_start_from": source_of_start, "fallback_body_start": fallback,
            "sections": len(secs), "crops": sum(1 for x in pieces if x.text.strip()),
            "spec": page.spec, "keys": [list(k) for k in page.keys],
            "hero": bool(page.main), "hero_band": page.main_band,
            "feature": bool(page.feature), "feature_band": page.feature_band,
            "package_band": page.package_band, "notes": notes,
            "bytes": len(html.encode()), "url": f"/basic/out/{row.code}"}


def _made(code: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", code or ""):
        raise HTTPException(404, "없는 상품번호")
    path = OUT / f"basic_{code}" / "index.html"
    if not path.exists():
        raise HTTPException(404, f"{code} 는 아직 안 만들었습니다.")
    return path


@router.get("/basic/out/{code}", response_class=HTMLResponse)
def basic_preview(code: str):
    return _made(code).read_text(encoding="utf-8")


@router.get("/basic/out/{code}/file")
def basic_download(code: str):
    return FileResponse(_made(code), filename=f"basic_{code}.html", media_type="text/html")


PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8">
<title>기본형 변환기</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<style>
*{box-sizing:border-box;margin:0}
body{font-family:Pretendard,-apple-system,'Malgun Gothic',sans-serif;color:#2b2f3a;background:#f6f7f9;padding:28px 20px 60px}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:24px;font-weight:800;color:#1a2440;letter-spacing:-.02em}
.sub{margin-top:6px;color:#6b7280;font-size:14px}
.card{background:#fff;border:1px solid #e6e8ee;border-radius:12px;padding:20px;margin-top:18px}
label.file{display:inline-block;border:1px dashed #c9ccd6;border-radius:8px;padding:14px 18px;cursor:pointer;background:#fafbfc;font-size:14px}
label.file:hover{background:#f2f4f7}
input[type=file]{display:none}
table{width:100%;border-collapse:collapse;margin-top:6px;font-size:14px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #eef0f4;vertical-align:middle}
th{font-size:12px;letter-spacing:.06em;color:#8a90a0;font-weight:700;text-transform:uppercase}
td.nm{max-width:460px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
button{font:inherit;font-weight:700;border:0;border-radius:8px;padding:8px 14px;cursor:pointer;background:#1a2440;color:#fff}
button:disabled{opacity:.45;cursor:default}
.msg{margin-top:12px;font-size:14px;color:#4a4f5c;white-space:pre-wrap}
.err{color:#b42318}
.chk{font-size:13px;color:#6b7280;margin-left:12px}
.links a{display:inline-block;margin-right:10px}
.tag{display:inline-block;border-radius:999px;padding:2px 9px;font-size:12px;font-weight:700;
 background:#eef2ff;color:#3730a3;margin-right:6px}
.tag--fb{background:#fff7ed;color:#9a3412}
details{margin-top:8px}
summary{cursor:pointer;font-size:13px;color:#6b7280}
pre{font-size:12px;color:#6b7280;white-space:pre-wrap;margin-top:6px;line-height:1.6}
</style>
<div class="wrap">
  <h1>기본형 변환기</h1>
  <div class="sub">원본을 재료로만 쓴다 — 메인은 새로 세우고, 본문은 밴드로 다시 짠다. 단순형과 따로 돈다.</div>

  <div class="card">
    <label class="file">엑셀 올리기 <input type="file" id="f" accept=".xlsx,.xls"></label>
    <label class="chk"><input type="checkbox" id="raw"> AI 안 부르기 (경계는 예비 규칙 · 글자는 원본 조각)</label>
    <div class="msg" id="m"></div>
  </div>

  <div class="card" id="listCard" style="display:none">
    <table>
      <thead><tr><th>상품번호</th><th>상품명</th><th>이미지</th><th></th><th></th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </div>
</div>
<script>
const $ = s => document.querySelector(s);
let sheet = '';

async function post(url, data) {
  const r = await fetch(url, {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(data)});
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || r.statusText);
  return d;
}

$('#f').onchange = async e => {
  const file = e.target.files[0];
  if (!file) return;
  $('#m').className = 'msg'; $('#m').textContent = '읽는 중…';
  const fd = new FormData(); fd.append('file', file);
  try {
    const r = await fetch('/api/basic/excel', {method:'POST', body:fd});
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || r.statusText);
    sheet = d.sheet;
    $('#m').textContent = `상품 ${d.rows.length}개`;
    $('#listCard').style.display = '';
    $('#rows').innerHTML = '';
    for (const row of d.rows) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${row.code || '—'}</td>
        <td class="nm" title="${row.name.replace(/"/g,'&quot;')}">${row.name}</td>
        <td>${row.images}장${row.skipped ? ` <span style="color:#8a90a0">(뺀 것 ${row.skipped})</span>` : ''}</td>
        <td><button ${row.images ? '' : 'disabled'}>기본형 변환</button></td>
        <td class="links"></td>`;
      const btn = tr.querySelector('button');
      const links = tr.querySelector('.links');
      btn.onclick = async () => {
        btn.disabled = true; btn.textContent = '변환 중…';
        links.innerHTML = '';
        try {
          const d2 = await post('/api/basic/convert', {sheet, row: row.i, raw: $('#raw').checked});
          btn.textContent = '다시 변환';
          const fb = d2.body_start_from === 'AI' ? '' : ' tag--fb';
          links.innerHTML = `<a href="${d2.url}" target="_blank">미리보기</a>
            <a href="${d2.url}/file">HTML 내려받기</a>
            <div style="margin-top:6px">
              <span class="tag${fb}">body_start ${d2.body_start} · ${d2.body_start_from}</span>
              <span class="tag">예비 규칙 ${d2.fallback_body_start}</span>
              <span class="tag${d2.hero ? '' : ' tag--fb'}">${d2.hero ? '대표컷 [' + d2.hero_band + ']' : '대표컷 없음'}</span>
              <span class="tag${d2.feature ? '' : ' tag--fb'}">${d2.feature ? '키피쳐 [' + d2.feature_band + ']' : '키피쳐 없음'}</span>
              <span class="tag">${d2.package_band >= 0 ? '패키지 [' + d2.package_band + ']' : '패키지 없음'}</span>
            </div>`;
          const det = document.createElement('details');
          const spec = Object.entries(d2.spec || {}).map(([k, v]) => `  ${k}: ${v}`).join('\\n');
          const keys = (d2.keys || []).map(k => `  · ${k[0]} — ${k[1]}`).join('\\n');
          det.innerHTML = `<summary>밴드 ${d2.bands}개 · 본문 섹션 ${d2.sections}개 · ${Math.round(d2.bytes/1024)}KB</summary>
            <pre>AI notes:\\n  ${(d2.notes||[]).join('\\n  ')}\\n\\n요약정보:\\n${spec || '  (없음)'}\\n\\n핵심특징:\\n${keys || '  (없음)'}\\n\\n쓴 것:\\n  ${d2.used.join('\\n  ')}${d2.skipped.length ? '\\n\\n뺀 것:\\n  ' + d2.skipped.join('\\n  ') : ''}</pre>`;
          links.appendChild(det);
        } catch (err) {
          btn.textContent = '기본형 변환';
          links.innerHTML = `<span class="err">${err.message}</span>`;
        }
        btn.disabled = false;
      };
      $('#rows').appendChild(tr);
    }
  } catch (err) {
    $('#m').className = 'msg err'; $('#m').textContent = err.message;
  }
};
</script>
</html>"""


@router.get("/basic", response_class=HTMLResponse)
def basic_page():
    return PAGE
