"""변환기 웹앱.

    python -m app.server        → http://127.0.0.1:8000

엑셀을 올리거나, 통이미지 URL 하나만 넣어도 돌아간다.
캡션은 잘라낸 원본 조각을 옆에 띄워 놓고 사람이 입력한다.
`ANTHROPIC_API_KEY` 가 있으면 그 칸을 자동으로 채운다.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import convert, excel, render
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
        apply_tags(p.units, p.meta.options)
    if req.name is not None:
        p.meta.name = req.name
    if req.brand is not None:
        p.meta.brand = req.brand
    if req.lead is not None:
        p.lead = req.lead
    p.meta.specs = render.guess_specs(p)

    html = render.render(p, job.dir)
    (job.dir / "detail.html").write_text(html, encoding="utf-8")
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
    return {"available": bool(os.environ.get("ANTHROPIC_API_KEY"))}


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

    # 배열이 아니면 "1. 캡션" 같은 줄 목록이라도 건진다.
    lines = [
        _re.sub(r"^\s*(?:#?\d+[.)]|[-*])\s*", "", ln).strip().strip('"')
        for ln in text.splitlines()
        if ln.strip()
    ]
    lines = [ln for ln in lines if len(ln) > 4]
    return lines or None


class AutofillReq(BaseModel):
    job: str
    #: 화면에서 넣은 키. 없으면 환경변수를 본다.
    key: str | None = None


@app.post("/api/autofill")
def api_autofill(req: AutofillReq):
    """캡션 조각을 한 번에 보내 읽고 다듬어 온다.

    호출을 유닛마다 쪼개지 않는다. 한 상품에 한 번이면 5~10초 예산에 들어간다.
    """
    key = (req.key or "").strip() or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise HTTPException(400, "API 키가 없습니다. 화면 위쪽 키 칸에 넣으세요.")
    job = JOBS.get(req.job)
    if job is None or job.work is None:
        raise HTTPException(404, "그 작업을 찾을 수 없다")

    import base64
    import urllib.error
    import urllib.request

    content: list[dict] = [{
        "type": "text",
        "text": (
            "쇼핑몰 상세페이지 이미지에서 잘라낸 캡션 줄들이다. 순서대로 번호가 붙어 있다.\n"
            "각 이미지에 적힌 한국어를 그대로 읽되, 명백한 오타와 띄어쓰기만 바로잡아라.\n"
            "내용을 새로 지어내지 마라. 없는 사실을 추가하지 마라.\n"
            "`[웨이비 2]` 같은 대괄호 말머리가 있으면 그대로 남겨라.\n"
            'JSON 배열 하나만 출력하라. 예: ["첫 캡션", "둘째 캡션"]'
        ),
    }]
    idx = []
    for i, u in enumerate(job.work.product.units):
        crop = job.dir / u.caption_crop if u.caption_crop else None
        if not crop or not crop.exists():
            continue
        idx.append(i)
        content.append({"type": "text", "text": f"#{len(idx)}"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png",
                       "data": base64.b64encode(crop.read_bytes()).decode()},
        })
    if not idx:
        return {"captions": [], "note": "읽을 그림 글자가 없습니다 (조각형 원본은 이미 텍스트가 들어 있습니다)."}

    body = json.dumps({
        "model": os.environ.get("CONVERTER_MODEL", "claude-sonnet-5"),
        # 한국어는 토큰을 많이 먹는다. 넉넉히 주지 않으면 배열이 중간에 잘리고,
        # 잘린 배열은 파싱에 실패해 "읽지 못했습니다"로만 보인다.
        "max_tokens": 8000,
        "messages": [{"role": "user", "content": content}],
    }).encode()
    print(f"[autofill] 그림 글자 {len(idx)}칸을 읽는 중…")
    r = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(r, timeout=180) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise HTTPException(502, f"API 호출 실패 ({e.code}): {detail}") from e
    except Exception as e:
        raise HTTPException(502, f"API 에 닿지 못했습니다: {e}") from e

    text = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text").strip()
    got = _parse_captions(text)
    if got is None:
        # 무엇이 왔는지 보여준다. 감추면 고칠 수가 없다.
        print("[autofill] 해석 실패. 받은 값:", repr(text[:600]))
        stop = out.get("stop_reason")
        hint = " (길이 제한에 걸려 잘렸습니다)" if stop == "max_tokens" else ""
        raise HTTPException(502, f"읽은 내용을 해석하지 못했습니다{hint}. 받은 값: {text[:160]!r}")

    captions = [""] * len(job.work.product.units)
    for slot, value in zip(idx, got):
        captions[slot] = str(value)
    return {"captions": captions}


@app.post("/api/reset")
def reset():
    for job in list(JOBS.values()):
        shutil.rmtree(job.dir, ignore_errors=True)
    JOBS.clear()
    SHEETS.clear()
    return JSONResponse({"ok": True})


def main() -> None:
    import uvicorn

    WORK.mkdir(parents=True, exist_ok=True)
    host = os.environ.get("CONVERTER_HOST", "127.0.0.1")
    port = int(os.environ.get("CONVERTER_PORT", "8000"))
    print(f"\n  상세페이지 변환기 → http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
