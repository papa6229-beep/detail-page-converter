"""변환기 웹앱.

    python -m app.server        → http://127.0.0.1:8000

엑셀을 올리거나, 통이미지 URL 하나만 넣어도 돌아간다.
캡션은 잘라낸 원본 조각을 옆에 띄워 놓고 사람이 입력한다.
`ANTHROPIC_API_KEY` 나 `OPENAI_API_KEY` 가 있으면 그 칸을 자동으로 채운다.
"""

from __future__ import annotations

import base64
import difflib
import json
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import convert, excel, jp, llm, render
from .product import Meta, apply_tags

ROOT = Path(__file__).resolve().parent
WORK = Path(os.environ.get("CONVERTER_WORK", ROOT.parent / "work"))
CACHE = WORK / "_cache"

app = FastAPI(title="상세페이지 변환기")


@dataclass
class Job:
    id: str
    dir: Path
    work: object = None
    row: object = None
    sheet_key: str = ""


JOBS: dict[str, Job] = {}
SHEETS: dict[str, excel.Sheet] = {}


def _job() -> Job:
    jid = uuid.uuid4().hex[:12]
    d = WORK / jid
    d.mkdir(parents=True, exist_ok=True)
    job = Job(id=jid, dir=d)
    JOBS[jid] = job
    return job


def _unit_payload(job: Job) -> dict:
    w = job.work
    p = w.product
    return {
        "job": job.id,
        "adapter": p.adapter,
        "ok": w.verdict.ok,
        "reasons": w.verdict.reasons,
        "reason_text": w.verdict.text,
        "notes": w.verdict.notes,
        "ink": w.ink_coverage,
        "meta": asdict(p.meta),
        "ad": p.ad,
        "units": [
            {
                "i": i,
                "image": u.image,
                "caption": u.caption,
                "caption_crop": u.caption_crop,
                "option_tag": u.option_tag,
                "w": u.width,
                "h": u.height,
            }
            for i, u in enumerate(p.units)
        ],
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (ROOT / "static" / "index.html").read_text(encoding="utf-8")


@app.post("/api/excel")
async def api_excel(file: UploadFile):
    try:
        sheet = excel.load(await file.read())
    except Exception as e:  # 파일 형식 문제는 사용자에게 그대로 보여준다
        raise HTTPException(400, f"엑셀을 읽지 못했다: {e}") from e

    key = uuid.uuid4().hex[:8]
    SHEETS[key] = sheet
    rows = []
    from . import gate, source

    for i, r in enumerate(sheet.rows):
        body = source.parse(r.body)
        keep = [p for p in body.pieces if source.classify(p.url) != "drop"]
        v = gate.pre_gate([p.url for p in keep], sum(1 for p in keep if p.caption), len(r.option_values))
        rows.append({
            "i": i, "code": r.code, "name": r.name, "brand": r.brand,
            "images": len(keep), "captions": sum(1 for p in keep if p.caption),
            "options": len(r.option_values),
            "adapter": "조각형" if len(keep) >= 2 else ("통이미지형" if keep else "—"),
            "ok": v.ok, "reason": v.text,
        })
    return {"sheet": key, "headers": sheet.headers, "missing": sheet.missing, "rows": rows}


class ConvertReq(BaseModel):
    sheet: str | None = None
    row: int | None = None
    url: str | None = None
    name: str | None = None
    brand: str | None = None


@app.post("/api/convert")
def api_convert(req: ConvertReq):
    job = _job()
    try:
        if req.url:
            meta = Meta(name=req.name or "", brand=req.brand or "")
            job.work = convert.convert_url(req.url.strip(), job.dir, CACHE, meta)
        else:
            sheet = SHEETS.get(req.sheet or "")
            if sheet is None or req.row is None or req.row >= len(sheet.rows):
                raise HTTPException(400, "먼저 엑셀을 올려야 한다")
            job.row = sheet.rows[req.row]
            job.work = convert.convert(job.row, job.dir, CACHE)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"변환 실패: {e}") from e
    return _unit_payload(job)


class RenderReq(BaseModel):
    job: str
    captions: list[str] = []
    tags: list[str] = []
    name: str | None = None
    brand: str | None = None
    lead: str | None = None
    #: 손으로 적은 요약. 비워 두면 캡션에서 찾은 것만 쓴다.
    specs: str | None = None


@app.post("/api/render")
def api_render(req: RenderReq):
    job = JOBS.get(req.job)
    if job is None or job.work is None:
        raise HTTPException(404, "그 작업을 찾을 수 없다")
    p = job.work.product
    for i, u in enumerate(p.units):
        if i < len(req.captions):
            u.caption = req.captions[i]
        if i < len(req.tags):
            u.option_tag = req.tags[i]
    if not any(req.tags):
        # 엑셀에서 온 상품만 '옵션 0개' 를 사실로 받는다. URL 입구는 모르는 것이다.
        apply_tags(p.units, p.meta.options if p.meta.options_known else None)
    if req.name is not None:
        p.meta.name = req.name
    if req.brand is not None:
        p.meta.brand = req.brand
    if req.lead is not None:
        p.lead = req.lead
    # 사람이 적었으면 그것이 맞다. 그림 속 치수는 우리가 못 읽는다.
    typed = render.parse_specs(req.specs or "")
    p.meta.specs = typed or render.guess_specs(p)

    html = render.render(p, job.dir)
    # 줄바꿈을 OS 에 맡기지 않는다. 윈도우에서 만든 것과 리눅스에서 만든 것이
    # 내용은 같은데 바이트가 달라지면 회차 비교가 통째로 흔들린다.
    (job.dir / "detail.html").write_text(html, encoding="utf-8", newline="\n")
    return {"ok": True, "bytes": len(html.encode()), "url": f"/preview/{job.id}"}


@app.get("/preview/{jid}", response_class=HTMLResponse)
def preview(jid: str):
    path = (JOBS[jid].dir / "detail.html") if jid in JOBS else None
    if not path or not path.exists():
        raise HTTPException(404, "아직 렌더하지 않았다")
    return path.read_text(encoding="utf-8")


@app.get("/download/{jid}")
def download(jid: str):
    path = (JOBS[jid].dir / "detail.html") if jid in JOBS else None
    if not path or not path.exists():
        raise HTTPException(404, "아직 렌더하지 않았다")
    return FileResponse(path, filename=f"detail_{jid}.html", media_type="text/html")


#: 저장된 결과물은 상품번호로 찾는다. 난수 작업번호는 서버 메모리에만 있어서
#: 껐다 켜면 미리보기가 통째로 죽는다 — 파일은 멀쩡한데 링크만 끊긴다. 실제로 겪었다.
def _made(code: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", code or ""):
        raise HTTPException(404, "없는 상품번호")
    path = WORK / "out" / f"{code}.html"
    if not path.exists():
        raise HTTPException(404, f"{code}.html 이 없습니다. 아직 안 만들었거나 초기화되었습니다.")
    return path


@app.get("/api/made")
def api_made():
    """이미 만들어 둔 것 목록. 서버를 껐다 켜도 남아 있다."""
    out = WORK / "out"
    files = sorted(out.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True) if out.exists() else []
    return {"made": [{"code": f.stem, "bytes": f.stat().st_size} for f in files]}


@app.get("/out/{code}", response_class=HTMLResponse)
def made_preview(code: str):
    return _made(code).read_text(encoding="utf-8")


@app.get("/out/{code}/file")
def made_download(code: str):
    return FileResponse(_made(code), filename=f"{code}.html", media_type="text/html")


@app.get("/asset/{jid}/{name}")
def asset(jid: str, name: str):
    job = JOBS.get(jid)
    if job is None:
        raise HTTPException(404, "없는 작업")
    path = (job.dir / name).resolve()
    if job.dir.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "없는 파일")
    return FileResponse(path)


@app.get("/api/autofill/available")
def autofill_available():
    key = llm.key_from_env()
    return {"available": bool(key), "provider": llm.label(key) if key else ""}


def _parse_captions(text: str) -> list[str] | None:
    """모델이 돌려준 글에서 캡션 목록을 꺼낸다.

    JSON 배열 하나만 달라고 해도 앞뒤에 말을 붙이거나 코드펜스를 씌워 올 때가 있다.
    한 가지 모양만 기대하면 그때마다 통째로 실패한다.
    """
    import re as _re

    if not text:
        return None

    fenced = _re.search(r"```(?:json)?\s*(.+?)```", text, _re.S)
    for candidate in (fenced.group(1) if fenced else None, text):
        if not candidate:
            continue
        candidate = candidate.strip()
        for attempt in (candidate, candidate[candidate.find("[") : candidate.rfind("]") + 1]):
            if not attempt.startswith("["):
                continue
            try:
                value = json.loads(attempt)
            except Exception:
                continue
            if isinstance(value, list):
                return [str(v) for v in value]

    # 물건 모양 `{"captions": [...]}` 으로 와도 받는다.
    for attempt in (text[text.find("{") : text.rfind("}") + 1],):
        try:
            value = json.loads(attempt)
        except Exception:
            break
        if isinstance(value, dict) and isinstance(value.get("captions"), list):
            return [str(v) for v in value["captions"]]

    # 배열이 아니면 "1. 캡션" 같은 줄 목록이라도 건진다.
    lines = [
        _re.sub(r"^\s*(?:#?\d+[.)]|[-*])\s*", "", ln).strip().strip('"')
        for ln in text.splitlines()
        if ln.strip()
    ]
    lines = [ln for ln in lines if len(ln) > 4]
    return lines or None


#: 할 일은 **강조**와 **교정** 둘이다. 강조를 먼저 적는다.
#:
#: 앞서 "원본을 그대로 두는 것이 기본" 을 맨 앞에 놓았더니, 항목이 18개인
#: 닛포리에서 모델이 열여덟 개를 통째로 그대로 돌려보냈다. 오타(`벨런스`)도
#: 안 고치고 강조도 하나 안 붙었다. 6개짜리 미우라에서는 잘 되던 것이다 —
#: 항목이 많아지면 **제일 편한 길**로 간다. 그래서 시키는 일을 맨 앞에 놓고,
#: 하지 말 것은 그 아래에 둔다.
PROMPT = """쇼핑몰 상세페이지의 상품 설명이다. #번호 순서대로 주어진다.
그림으로 온 것은 그 안에 적힌 한국어를 읽고, 글자로 온 것은 그대로 받는다.

**항목마다 반드시 두 가지를 한다.**

1. **강조** — 그 항목에서 가장 중요한 대목 한 군데를 `**이렇게**` 별표 두 개로 감싼다.
   항목이 몇 개든 하나도 빠뜨리지 마라. 감싸는 말은 원본에 있는 그대로여야 한다.

   **낱말 하나가 아니라 두 낱말 이상, 뜻이 되는 덩어리를 감싼다.** 손님이 그 대목만
   읽어도 무엇이 좋은지 알 수 있어야 한다. 조사는 감싸는 말 밖에 둔다.

   ```
   나쁘다   피스톤 운동을 할 때마다 **당신을** 꽉꽉 짜내어 줍니다
            안쪽에서 **공기를** 밀어내듯 쥐면
            서로 다른 **경도에** 의한 삽입 피링의 변화
   좋다     피스톤 운동을 할 때마다 **꽉꽉 짜내어** 줍니다
            **경도 차이가 만드는 삽입감의 변화**
   ```
2. **교정** — 오타·맞춤법·띄어쓰기를 바로잡고, 어색하게 끊긴 문장을 맺어 준다
   (예: "…부드러운 질벽" → "…부드러운 질벽입니다")

교정은 **틀린 곳만** 손댄다. 고쳐 쓰는 일이 아니다.

- 원본에 없는 말은 한 단어도 보태지 마라. 더 좋게 들리게 바꾸지 마라
- 요약하지도 늘리지도 마라. 수치와 단위는 한 글자도 건드리지 마라
- 틀린 곳이 없으면 그 항목은 강조만 붙여서 원본 그대로 돌려준다
- `[웨이비 2]` 같은 대괄호 말머리는 위치와 표기를 그대로 남긴다

JSON 배열 하나만 출력하라. 설명도 코드펜스도 붙이지 마라. 항목 수는 받은 수와 같아야 한다.
예: ["양방향으로 당기면 **쭈욱 늘어났다가** 다시 제자리로 돌아옵니다.", "..."]"""


def _ask(key: str, parts: list[tuple[str, str]], max_tokens: int = 8000,
         model: str = "") -> dict:
    """모델에 한 번 물어본다. 회사 차이는 llm 이 다 흡수한다.

    길이 상한의 이름만 예외다. OpenAI 쪽에서 `max_completion_tokens` 로 바뀌었는데
    옛 모델은 그 이름을 모르고 새 모델은 옛 이름을 거부한다. 어느 모델을 쓰실지
    모르니 거부당하면 다른 이름으로 한 번 더 보낸다.
    """
    import urllib.error
    import urllib.request

    for legacy in (False, True):
        url, headers, body = llm.build(key, parts, max_tokens, legacy_cap=legacy,
                                       model=model)
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, data=body, headers=headers), timeout=180
            ) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            retry = not legacy and llm.provider_of(key) == llm.OPENAI and "max_completion_tokens" in detail
            if retry:
                continue
            raise HTTPException(502, f"{llm.label(key)} API 호출 실패 ({e.code}): {detail}") from e
        except Exception as e:
            raise HTTPException(502, f"{llm.label(key)} API 에 닿지 못했습니다: {e}") from e
    raise HTTPException(502, "API 호출에 실패했습니다.")


#: 원본과 이만큼도 안 닮았으면 교정이 아니라 창작이다.
SIMILAR_FLOOR = 0.70

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_MARK_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
_SPACE_RE = re.compile(r"\s+")


def _bare(s: str) -> str:
    """견주기 위한 모양. 별표와 공백은 뜻이 아니다."""
    return _SPACE_RE.sub("", s.replace("**", ""))


def _thin_marks(text: str) -> str:
    """한 어절짜리 강조는 별표만 걷는다. 글은 안 건드린다.

    실물 49개에서 강조 220개 중 75개가 한 낱말이었고 그중 33개는 조사로 끝났다 —
    `**당신을**` `**공기를**` `**경도에**` `**돌기들이**`. 뜻이 안 되는 토막이라
    빨갛게 칠할 값이 없다.

    낱말을 자르지 않는다. `단면도` `토네이도` 처럼 조사처럼 생긴 낱말 끝을 떼려 들면
    멀쩡한 말이 망가진다. **강조만 없애면** 글은 그대로 남으므로 잃는 것이 없다.
    """
    return _MARK_RE.sub(lambda m: m.group(1) if " " not in m.group(1).strip() else m.group(0), text)


def guard(original: str, got: str) -> str:
    """모델이 돌려준 문구를 원본에 비추어 받는다.

    교정만 시켰어도 모델은 이따금 말을 보탠다. 보탠 것을 화면에서 잡아내려면
    사람이 여섯 칸을 다 읽어야 하는데, 그럴 거면 자동으로 채울 이유가 없다.
    그래서 **받은 뒤에 잰다.** 수치가 달라졌거나 원본에서 너무 멀어졌으면
    원본을 그대로 쓴다. 이러면 자동 채우기가 원본보다 나빠지는 일은 없다.

    그림에서 읽어 온 칸은 견줄 원본이 우리에게 없다. 그 읽은 값이 곧 원본이다.
    """
    got = (got or "").strip()
    if not got:
        return original
    if got.count("**") % 2:  # 짝 안 맞는 별표는 화면에 그대로 샌다
        got = got.replace("**", "")
    got = _thin_marks(got)
    original = (original or "").strip()
    if not original:
        return got

    flat, plain = _bare(original), _bare(got)
    if sorted(_NUM_RE.findall(plain)) != sorted(_NUM_RE.findall(flat)):
        return original
    if difflib.SequenceMatcher(None, flat, plain).ratio() < SIMILAR_FLOOR:
        return original
    if any(_bare(m) not in flat for m in _MARK_RE.findall(got)):
        got = _MARK_RE.sub(r"\1", got)  # 지어낸 말을 강조했다 — 강조만 걷는다
    return got


class AutofillReq(BaseModel):
    job: str
    #: 화면에서 넣은 키. 없으면 환경변수를 본다.
    key: str | None = None


@app.post("/api/autofill")
def api_autofill(req: AutofillReq):
    """캡션 조각을 한 번에 보내 읽고 다듬어 온다.

    호출을 유닛마다 쪼개지 않는다. 한 상품에 한 번이면 5~10초 예산에 들어간다.
    """
    key = (req.key or "").strip() or llm.key_from_env()
    if not key:
        raise HTTPException(400, "API 키가 없습니다. 화면 위쪽 키 칸에 넣으세요.")
    job = JOBS.get(req.job)
    if job is None or job.work is None:
        raise HTTPException(404, "그 작업을 찾을 수 없다")

    import base64

    parts: list[tuple[str, str]] = [("text", PROMPT)]
    idx = []
    for i, u in enumerate(job.work.product.units):
        crop = job.dir / u.caption_crop if u.caption_crop else None
        has_crop = bool(crop and crop.exists())
        if not has_crop and not u.caption.strip():
            continue
        idx.append(i)
        parts.append(("text", f"#{len(idx)}"))
        if has_crop:
            parts.append(("image", base64.b64encode(crop.read_bytes()).decode()))
        else:
            parts.append(("text", u.caption.strip()))
    if not idx:
        return {"captions": [], "note": "다듬을 문구가 없습니다."}

    n_img = sum(1 for kind, _ in parts if kind == "image")
    print(f"[autofill] {llm.label(key)} · {len(idx)}칸 고치는 중 (그림에서 읽을 것 {n_img}칸)…")
    out = _ask(key, parts)

    text, stop = llm.extract(key, out)
    got = _parse_captions(text)
    if got is None:
        # 무엇이 왔는지 보여준다. 감추면 고칠 수가 없다.
        print("[autofill] 해석 실패. 받은 값:", repr(text[:600]))
        hint = " (길이 제한에 걸려 잘렸습니다)" if llm.truncated(key, stop) else ""
        raise HTTPException(502, f"읽은 내용을 해석하지 못했습니다{hint}. 받은 값: {text[:160]!r}")

    units = job.work.product.units
    captions = [""] * len(units)
    kept = 0
    for slot, value in zip(idx, got):
        original = units[slot].caption.strip()
        safe = guard(original, str(value))
        if original and safe == original and _bare(safe) != _bare(str(value)):
            kept += 1
        captions[slot] = safe
    # 0 도 찍는다. 아무 줄도 안 뜨는 것과 "0칸 되돌림" 은 보는 사람에게 다른 말이다.
    print(f"[autofill] 끝 · 원본에서 벗어나 되돌린 칸 {kept}개")
    return {"captions": captions, "kept": kept}


class SaveReq(BaseModel):
    job: str


@app.post("/api/save")
def api_save(req: SaveReq):
    """만든 페이지를 상품번호로 한 폴더에 모아 둔다.

    작업 폴더는 이름이 난수라 800개를 돌리고 나면 어느 것이 어느 상품인지 알 수 없다.
    `work/out/2496310.html` 로 떨궈 두면 파일 이름만 보고 찾는다.
    """
    job = JOBS.get(req.job)
    if job is None or job.work is None:
        raise HTTPException(404, "그 작업을 찾을 수 없다")
    src = job.dir / "detail.html"
    if not src.exists():
        raise HTTPException(400, "아직 렌더하지 않았다")
    out = WORK / "out"
    out.mkdir(parents=True, exist_ok=True)
    code = getattr(job.row, "code", "") or job.id
    dst = out / f"{code}.html"
    shutil.copyfile(src, dst)
    return {"ok": True, "code": code, "file": str(dst), "bytes": dst.stat().st_size}


@app.get("/download/batch/all")
def download_all(codes: str = ""):
    """만든 것을 한 덩어리로 내려준다.

    상품 하나에 파일 하나라, 열 개만 돌려도 열 번 내려받게 된다. 폴더가 어디인지
    설명하는 것보다 zip 한 번이 빠르다. HTML 안에 이미지가 통째로 들어 있어서
    (data URI) 파일 하나가 곧 완성된 페이지다 — 따로 챙길 이미지 폴더가 없다.
    """
    import zipfile

    out = WORK / "out"
    files = sorted(out.glob("*.html")) if out.exists() else []
    # 이번에 돌린 것만. 어제 것까지 딸려 오면 무엇이 새로 된 것인지 알 수 없다.
    want = {c for c in (codes or "").split(",") if c.strip()}
    if want:
        files = [f for f in files if f.stem in want]
    if not files:
        raise HTTPException(404, "아직 만든 것이 없다")
    bundle = WORK / "detail_all.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.name)
    return FileResponse(bundle, filename="detail_all.zip", media_type="application/zip")


@app.post("/api/reset")
def reset():
    for job in list(JOBS.values()):
        shutil.rmtree(job.dir, ignore_errors=True)
    JOBS.clear()
    SHEETS.clear()
    return JSONResponse({"ok": True})


@app.post("/api/translate")
async def api_translate(file: UploadFile, key: str = Form(""), enc: str = Form("utf-8")):
    """일본어 스크립트 txt → 한국어 txt. **변환기와 코드가 안 섞인다** (`jp.py` 머리말).

    모양을 지키는 일은 전부 `jp.py` 가 하고, 모델에게는 번역할 글자만 간다.
    묶음 하나가 실패하면 **그 묶음만 원문 그대로** 남기고 계속한다 — 한 군데
    때문에 파일 전체를 못 쓰게 만들지 않는다.
    """
    api = (key or "").strip() or llm.key_from_env()
    if not api:
        raise HTTPException(400, "API 키가 필요합니다")
    if enc not in jp.ENCODINGS:
        raise HTTPException(400, f"모르는 인코딩입니다: {enc}")

    raw = await file.read()
    if not raw.strip():
        raise HTTPException(400, "빈 파일입니다")
    text, enc_in = jp.decode(raw)
    lines = jp.parse(text)
    todo = [i for i, ln in enumerate(lines) if ln.target]
    if not todo:
        raise HTTPException(400, "일본어가 한 글자도 없습니다")

    model = jp.model_for(api)
    done: dict[int, str] = {}
    실패 = 0

    # ① 화자 이름을 먼저 정한다. 같은 이름이 파일 안에서 매번 달리 나오면 안 된다.
    표: dict[str, str] = {}
    이름 = jp.names(lines)
    if 이름:
        got = jp.take(
            llm.extract(api, _ask(api, jp.name_parts(이름), max_tokens=1000, model=model))[0],
            len(이름),
        )
        if got:
            표 = dict(zip(이름, got))
    print(f"[번역] {file.filename} · {enc_in} · {len(lines)}줄 중 {len(todo)}줄 "
          f"· 이름 {len(표)}개 · {model or llm.label(api)}")

    # ② 나머지를 묶음으로. 이름 표를 매번 같이 보낸다.
    for a in range(0, len(todo), jp.CHUNK):
        묶음 = todo[a : a + jp.CHUNK]
        원문 = [lines[i].body for i in 묶음]
        try:
            reply, _stop = llm.extract(
                api, _ask(api, jp.line_parts(원문, 표), max_tokens=8000, model=model)
            )
        except HTTPException as e:
            print(f"[번역] {a}~ 묶음 실패 — {e.detail}")
            실패 += len(묶음)
            continue
        got = jp.take(reply, len(묶음))
        if got is None:
            # 개수가 안 맞으면 줄이 밀린다. 밀린 것보다 원문이 낫다.
            print(f"[번역] {a}~ 묶음 개수 불일치 — 원문 유지")
            실패 += len(묶음)
            continue
        done.update(dict(zip(묶음, got)))

    out = jp.build(lines, done)
    name = Path(file.filename or "script.txt").stem
    # **바이트는 여기서 굽는다.** 브라우저의 `Blob` 은 무슨 charset 을 적어 줘도
    # UTF-8 로만 쓴다 — `cp949` 를 고르면 조용히 UTF-8 이 나갔을 것이다.
    데이터, 못쓴글자 = jp.encode(out, enc)
    print(f"[번역] {name} · 옮김 {len(done)}줄 · 원문 유지 {실패}줄"
          + (f" · {enc} 로 못 적은 글자 {못쓴글자}자" if 못쓴글자 else ""))
    return {
        "name": f"{name}_ko.txt",
        "b64": base64.b64encode(데이터).decode(),
        "lost": 못쓴글자,
        "enc": enc,
        "enc_in": enc_in,
        "lines": len(lines),
        "targets": len(todo),
        "done": len(done),
        "failed": 실패,
        "names": 표,
        "model": model,
    }


def main() -> None:
    import uvicorn

    WORK.mkdir(parents=True, exist_ok=True)
    host = os.environ.get("CONVERTER_HOST", "127.0.0.1")
    port = int(os.environ.get("CONVERTER_PORT", "8000"))
    print(f"\n  상세페이지 변환기 → http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
