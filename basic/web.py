"""기본형 전용 화면. 단순형 화면(app/static/index.html)과 따로 산다.

    /basic                  화면
    /api/basic/excel        엑셀 올리기 → 상품 목록
    /api/basic/convert      상품 하나 변환 → out/basic_<상품번호>/index.html
    /basic/out/<상품번호>     미리보기
    /basic/out/<상품번호>/file  내려받기

단순형에서 빌려 쓰는 것은 **읽기 전용 세 가지**뿐이다 — 엑셀 파서(app.excel),
상세설명 파서(app.source), 받아 두기(app.convert.fetch), 키 찾기(app.llm).
단순형의 변환·배치·렌더는 부르지 않는다. 여기 것은 basic/ 파이프라인이다.

app.server 를 가져오지 않는다. server 가 이쪽을 붙이므로 서로 가져오면 원이 된다.
"""
from __future__ import annotations

import os
import re
import traceback
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from app import convert as _convert
from app import excel as _excel
from app import llm as _llm
from app import source as _source

from . import body, read_text, render

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
    """(쓸 본문 이미지, 뺀 것과 이유).

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


class ConvertReq(BaseModel):
    sheet: str
    row: int
    #: 켜면 AI 를 안 부르고 글자 자리에 조각 이미지를 그대로 둔다.
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
        raise HTTPException(400, "쓸 본문 이미지가 없다 (공통 장식·gif 를 빼고 나니 0장)")

    out = OUT / f"basic_{row.code}"
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    try:
        # 1) 받아 두기 — 단순형과 같은 통을 쓴다. 같은 그림을 두 번 받지 않는다.
        files = []
        for n, url in enumerate(urls):
            data = _convert.fetch(url, CACHE)
            f = out / f"src_{n:02d}{Path(url.split('?')[0]).suffix.lower() or '.jpg'}"
            f.write_bytes(data)
            files.append(f)

        # 2) 밴드로 자르고 섹션으로 묶는다
        pieces = []
        for n, f in enumerate(files):
            pieces += body.read_image(f, assets, prefix=f"i{n}_")
        crops = [p for p in pieces if p.crop and p.kind != body.BADGE]

        # 3) 글자 읽기 — 키는 단순형이 쓰는 방법 그대로 서버가 찾는다
        key = "" if req.raw else _llm.key_from_env()
        texts: dict[str, str] = {}
        note = ""
        if key:
            texts = read_text.read(key, [assets / p.crop for p in crops])
            note = f"{_llm.label(key)} 로 글자 조각 {len(crops)}개를 읽었다"
        else:
            note = ("키가 없어 글자를 안 읽었다 — 글자 자리에 원본 조각을 그대로 두었다."
                    " ANTHROPIC_API_KEY 나 OPENAI_API_KEY 를 넣고 다시 돌리면 채워진다.")
        for i, p in enumerate(crops):
            p.text = texts.get(str(i), texts.get(p.crop, ""))

        # 4) 렌더
        secs = body.sections(pieces)
        html = ('<!doctype html><meta charset="utf-8">'
                '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/'
                'pretendard@v1.3.9/dist/web/static/pretendard.min.css">'
                + render.render(secs, assets))
        (out / "index.html").write_text(html, encoding="utf-8", newline="\n")
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"변환 실패: {e}") from e

    log = [f"밴드 {len(pieces)}개 → 섹션 {len(secs)}개 · 읽을 조각 {len(crops)}개"]
    log += [f"  y={p.y:5d} h={p.h:4d} {p.kind:6} [{p.band_kind}] {p.why}" for p in pieces]
    (out / "log.txt").write_text("\n".join(log), encoding="utf-8")

    return {"ok": True, "code": row.code, "name": row.name,
            "used": urls, "skipped": skipped,
            "bands": len(pieces), "sections": len(secs), "crops": len(crops),
            "read": bool(key), "note": note,
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
.todo{background:#fff8e6;border:1px solid #f0dCa0;border-radius:10px;padding:12px 14px;margin-top:14px;font-size:14px;color:#7a5d00}
.todo b{color:#5c4600}
label.file{display:inline-block;border:1px dashed #c9ccd6;border-radius:8px;padding:14px 18px;cursor:pointer;background:#fafbfc;font-size:14px}
label.file:hover{background:#f2f4f7}
input[type=file]{display:none}
table{width:100%;border-collapse:collapse;margin-top:6px;font-size:14px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #eef0f4;vertical-align:middle}
th{font-size:12px;letter-spacing:.06em;color:#8a90a0;font-weight:700;text-transform:uppercase}
td.nm{max-width:520px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
button{font:inherit;font-weight:700;border:0;border-radius:8px;padding:8px 14px;cursor:pointer;background:#1a2440;color:#fff}
button:disabled{opacity:.45;cursor:default}
button.ghost{background:#eef0f4;color:#1a2440}
.msg{margin-top:12px;font-size:14px;color:#4a4f5c;white-space:pre-wrap}
.err{color:#b42318}
.chk{font-size:13px;color:#6b7280;margin-left:12px}
.links a{display:inline-block;margin-right:10px}
details{margin-top:8px}
summary{cursor:pointer;font-size:13px;color:#6b7280}
pre{font-size:12px;color:#6b7280;white-space:pre-wrap;margin-top:6px;line-height:1.6}
</style>
<div class="wrap">
  <h1>기본형 변환기</h1>
  <div class="sub">본문 이미지를 밴드로 잘라 섹션으로 다시 짠다. 단순형과 따로 돈다.</div>

  <div class="todo"><b>지금은 본문만 변환됩니다.</b> 메인(대표 이미지·상단 히어로)은 아직입니다.</div>

  <div class="card">
    <label class="file">엑셀 올리기 <input type="file" id="f" accept=".xlsx,.xls"></label>
    <label class="chk"><input type="checkbox" id="raw"> 글자는 원본 조각 그대로 (AI 안 부름)</label>
    <div class="msg" id="m"></div>
  </div>

  <div class="card" id="listCard" style="display:none">
    <table>
      <thead><tr><th>상품번호</th><th>상품명</th><th>본문</th><th></th><th></th></tr></thead>
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
          links.innerHTML = `<a href="${d2.url}" target="_blank">미리보기</a>
            <a href="${d2.url}/file">HTML 내려받기</a>`;
          const det = document.createElement('details');
          det.innerHTML = `<summary>섹션 ${d2.sections}개 · 밴드 ${d2.bands}개 · ${Math.round(d2.bytes/1024)}KB</summary>
            <pre>${d2.note}\n\n쓴 것:\n  ${d2.used.join('\n  ')}${d2.skipped.length ? '\n\n뺀 것:\n  ' + d2.skipped.join('\n  ') : ''}</pre>`;
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
