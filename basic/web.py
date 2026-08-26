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

from . import bands as B
from . import body, boundary, main, read_text, render

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


def typed_text(row) -> str:
    """원본에 직접 타이핑돼 있던 글. 모델에게 **읽는 근거**로 준다."""
    parsed = _source.parse(row.body)
    lines = [b.text for b in parsed.lead_blocks if b.text.strip()]
    lines += [p.caption for p in parsed.pieces if p.caption.strip()]
    return "\n".join(lines).strip()


def model_hero_pick(reply: str):
    """모델이 대표컷으로 뭘 골랐는지만 꺼낸다. 탈락 여부를 보고하려고.

    답이 깨져 있어도 여기서 터지면 안 된다 — 그건 `take` 가 이미 다룬다.
    """
    m = re.search(r"\{[\s\S]*\}", reply or "")
    if not m:
        return None
    try:
        return json.loads(m.group(0)).get("main")
    except (json.JSONDecodeError, AttributeError):
        return None


def ask_model(key: str, parts, timeout: int = 240, tries: int = 2) -> str:
    """모델에 물어본다. **JSON 이 깨져 오면 한 번 더 부른다.**

    다일레이터에서 모델이 `keys` 배열의 닫는 괄호를 빼먹고 보냈다. 그러면 답이
    통째로 버려져 대표컷·키피쳐·패키지가 전부 빈칸이 된다. 고쳐 쓰려 들면
    (괄호를 우리가 채워 넣으면) 무엇을 고쳤는지 모르게 되니, 그냥 다시 묻는다.
    """
    url, headers, payload = _llm.build(key, parts, max_tokens=4000)
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


def body_pieces(files: list[Path], entries: list[boundary.Entry], start: int, assets: Path) -> list:
    """`start` 번 밴드부터를 본문으로 보고 조각을 낸다.

    밴드 번호를 (이미지, y) 로 바꿔서 자른다. `body.read_image` 는 밴드를 다시
    읽어 배지를 떼고 글줄을 붙이므로 **조각 번호와 밴드 번호가 다르다.** 그래서
    번호가 아니라 **자리(y)** 로 가른다 — 조각의 y 는 밴드의 y 와 같은 자다.
    """
    if start >= len(entries):
        return []
    edge_img, edge_y = entries[start].image, entries[start].band.y
    out = []
    for gi, f in enumerate(files):
        if gi < edge_img:
            continue
        pieces = body.read_image(f, assets, prefix=f"i{gi}_")
        if gi == edge_img:
            pieces = [p for p in pieces if p.y >= edge_y]
        out += pieces
    return out


def shots_by_band(files: list[Path], entries: list[boundary.Entry]) -> dict[int, main.Shot]:
    """밴드 번호 → 그 밴드를 잰 값. **밴드 폭 전체가 아니라 알맹이로 잰다.**

    밴드는 늘 폭 전체라 그대로 재면 옆 여백이 값을 묽게 만들어, 컬러 배경이
    깔린 컷도 깨끗해 보인다. `main.shots` 가 `_content_rect` 로 알맹이를 집는다.
    """
    got: dict[int, main.Shot] = {}
    off = 0
    for gi, f in enumerate(files):
        n = sum(1 for e in entries if e.image == gi)
        for sh in main.shots(np.asarray(Image.open(f).convert("RGB")), offset=off):
            got[sh.band] = sh
        off += n
    return got


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
        shots = shots_by_band(files, entries)
        blocked = boundary.summary_bands(entries)
        if blocked:
            notes.append(f"요약정보 표가 든 밴드 {sorted(blocked)} — 대표컷·feature 에서 뺀다")
        if key:
            reply = ask_model(key, main.parts_for(row.name, page.maker, typed_text(row), cuts, kinds))
            got, ai_notes = main.take(reply, cuts, kinds, hashes, shots=shots, blocked=blocked)
            got.name_kr, got.name_en, got.maker = page.name_kr, page.name_en, page.maker
            head, page, notes = notes, got, ai_notes
            notes[:0] = head
            notes.insert(0, f"{_llm.label(key)} 1콜 — 밴드 {len(cuts)}장을 보냈다")
            ai_pick = model_hero_pick(reply)
            if isinstance(ai_pick, int) and ai_pick != page.main_band:
                notes.append(f"AI 대표컷 픽 [{ai_pick}] 은 탈락 — 세운 것은 [{page.main_band}]")
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

        # ⑤ 대표컷 다시 앉히기
        if page.main is not None:
            page.main = main.reframe(page.main, assets / "hero.jpg")

        # ⑥ 본문 — body_start 이후 밴드만
        pieces = body_pieces(files, entries, page.body_start, assets)
        crops = [p for p in pieces if p.crop and p.kind != body.BADGE]

        # ⑦ 【2콜】 본문 글자 읽기 — 메인 것은 이미 1콜에서 나왔다
        if key and crops:
            texts = read_text.read(key, [assets / p.crop for p in crops])
            notes.append(f"{_llm.label(key)} 2콜 — 본문 글자 조각 {len(crops)}개를 읽었다")
        else:
            texts = {}
            if crops:
                notes.append(f"본문 글자 조각 {len(crops)}개는 안 읽었다 — 원본 조각을 그대로 둔다")
        for i, p in enumerate(crops):
            p.text = texts.get(str(i), texts.get(p.crop, ""))

        # ⑧ 한 파일 — 메인 + 본문. 둘 다 폭 860.
        secs = body.sections(pieces)
        html = ('<!doctype html><meta charset="utf-8">'
                '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/'
                'pretendard@v1.3.9/dist/web/static/pretendard.min.css">'
                + main.render_page(page)
                + render.render(secs, assets))
        (out / "index.html").write_text(html, encoding="utf-8", newline="\n")
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"변환 실패: {e}") from e

    log = [f"밴드 {len(cuts)}개 · body_start {page.body_start}({source_of_start})"
           f" → 본문 조각 {len(pieces)}개 · 섹션 {len(secs)}개"]
    log += [f"  [{i:3}] img{e.image} y={e.band.y:6d} h={e.band.height:5d} {k:8}"
            f"{'  ← 본문 시작' if i == page.body_start else ''}"
            for i, (e, k) in enumerate(zip(entries, kinds))]
    (out / "log.txt").write_text("\n".join(log), encoding="utf-8")

    return {"ok": True, "code": row.code, "name": row.name,
            "used": urls, "skipped": skipped,
            "bands": len(cuts), "body_start": page.body_start,
            "body_start_from": source_of_start, "fallback_body_start": fallback,
            "sections": len(secs), "crops": len(crops),
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
