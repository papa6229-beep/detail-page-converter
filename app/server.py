"""변환기 웹앱.

    python -m app.server        → http://127.0.0.1:8000

엑셀을 올리거나, 통이미지 URL 하나만 넣어도 돌아간다.
캡션은 잘라낸 원본 조각을 옆에 띄워 놓고 사람이 입력한다.
`ANTHROPIC_API_KEY` 나 `OPENAI_API_KEY` 가 있으면 그 칸을 자동으로 채운다.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import convert, excel, llm, render
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
        apply_tags(p.units, p.meta.options)
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


_SPEC_FIELD = re.compile(r'"spec"\s*:\s*"([^"]*)"')


def _parse_spec(text: str) -> str:
    """답에서 `spec` 한 칸만 꺼낸다. 캡션 해석과 엮지 않는다.

    스펙은 있으면 좋고 없어도 그만인 값이다. 이것 때문에 캡션 전체가 날아가면 안 된다.
    """
    m = _SPEC_FIELD.search(text or "")
    return m.group(1).strip() if m else ""


#: 고쳐 쓰는 일이 아니라 교정하는 일이다.
#:
#: 원본 문구는 글 잘 쓰는 사람이 쓴 것이 아니지만, 그렇다고 우리가 더 잘 쓰라는
#: 주문을 받은 것도 아니다. 더 좋게 들리게 손대는 순간 없던 말이 섞이고
#: (`묵직한`) 수치가 흔들린다. 그래서 **틀린 것만** 고치게 한다. 고칠 것이
#: 없으면 원본이 그대로 나오는 것이 정답이다.
PROMPT = """쇼핑몰 상세페이지의 상품 설명이다. #번호 순서대로 주어진다.
그림으로 온 것은 그 안에 적힌 한국어를 읽고, 글자로 온 것은 그대로 받는다.

**고쳐 쓰는 일이 아니라 교정하는 일이다.** 원본을 그대로 두는 것이 기본이고,
아래 다섯 가지만 손댄다.

1. 오타·맞춤법·띄어쓰기를 바로잡는다
2. 어색하게 끊긴 문장을 맺어 준다 (예: "…부드러운 질벽" → "…부드러운 질벽입니다")
3. 원본에 없는 말은 한 단어도 보태지 마라. 더 좋게 들리게 바꾸지 마라.
   요약하지도 늘리지도 마라. 수치와 단위는 한 글자도 건드리지 마라.
   고칠 것이 없으면 **원본을 그대로** 돌려줘라
4. 그 항목에서 가장 중요한 말 **한 군데**를 `**이렇게**` 별표 두 개로 감싸라.
   감싸는 말은 원본에 있는 그대로여야 한다. 마땅한 말이 없으면 감싸지 않는다.
   조사는 감싸는 말 **밖에** 둔다 — `**돌기도**` 가 아니라 `**포르치오 돌기**도`
5. `[웨이비 2]` 같은 대괄호 말머리는 위치와 표기를 그대로 남긴다

JSON 하나만 출력하라. 설명도 코드펜스도 붙이지 마라.
{"captions": ["양방향으로 당기면 **쭈욱 늘어났다가** 다시 제자리로 돌아옵니다.", "..."]}"""

#: 치수가 그림 픽셀로만 있는 원본이 흔하다. 캡션 글자에서 아무것도 못 찾았을 때만 묻는다.
SPEC_ASK = """
마지막 그림은 이 상품의 사진들을 한 장에 모아 붙인 것이다. #번호와는 무관하다.
거기에 **상품의 치수가 숫자로 찍혀 있으면** `spec` 에 옮겨 적어라.

- 사람의 신체 치수(스리사이즈·B/W/H·컵·신장·체중)는 상품 치수가 아니다. 무시하라
- 무엇의 치수인지 그림에 함께 적혀 있으면 그 말도 쓴다 — `전장 12.5cm`
- 안 적혀 있으면 숫자와 단위만 쓴다 — `12.5cm`
- 여럿이면 ` · ` 로 잇는다. 찍힌 것이 없으면 빈 문자열로 둬라. 지어내지 마라

{"captions": [...], "spec": "233g · 12.5cm"}"""


def _ask(key: str, parts: list[tuple[str, str]], max_tokens: int = 8000) -> dict:
    """모델에 한 번 물어본다. 회사 차이는 llm 이 다 흡수한다.

    길이 상한의 이름만 예외다. OpenAI 쪽에서 `max_completion_tokens` 로 바뀌었는데
    옛 모델은 그 이름을 모르고 새 모델은 옛 이름을 거부한다. 어느 모델을 쓰실지
    모르니 거부당하면 다른 이름으로 한 번 더 보낸다.
    """
    import urllib.error
    import urllib.request

    for legacy in (False, True):
        url, headers, body = llm.build(key, parts, max_tokens, legacy_cap=legacy)
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


#: 치수 단위. `종` 개수 같은 것은 치수가 아니다.
MEASURES = {"mm", "cm", "m", "kg", "g", "ml", "l"}


def _has_measure(product) -> bool:
    return any(u in MEASURES for _, _, u in render.guess_specs(product))


def _spec_sheet(job: Job) -> bytes:
    paths = [job.dir / u.image for u in job.work.product.units if u.image]
    paths = [p for p in paths if p.exists()]
    return convert.contact_sheet(paths) if paths else b""


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

    # 캡션 글자에 치수가 이미 적혀 있으면 사진을 올려보낼 이유가 없다.
    # 없을 때만 붙임장 한 장을 얹는다 — 대개 그림 픽셀에만 남아 있는 경우다.
    sheet = _spec_sheet(job) if not _has_measure(job.work.product) else b""
    if sheet:
        parts[0] = ("text", PROMPT + SPEC_ASK)
        parts.append(("image", base64.b64encode(sheet).decode()))

    n_img = sum(1 for kind, _ in parts if kind == "image")
    print(f"[autofill] {llm.label(key)} · {len(idx)}칸 고치는 중"
          f" (그림에서 읽을 것 {n_img}칸{' · 치수 붙임장 포함' if sheet else ''})…")
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
    # 읽어 온 치수도 화면 칸에 그대로 띄운다. 사람이 보고 고칠 수 있어야
    # 자동으로 읽는 것이 위험하지 않다. 파싱을 통과한 것만 돌려준다.
    spec = " · ".join(f"{k} {v}{u}".strip() for k, v, u in render.parse_specs(_parse_spec(text))) if sheet else ""

    # 0 도 찍는다. 아무 줄도 안 뜨는 것과 "0칸 되돌림" 은 보는 사람에게 다른 말이다.
    print(f"[autofill] 끝 · 원본에서 벗어나 되돌린 칸 {kept}개" + (f" · 치수 {spec}" if spec else ""))
    return {"captions": captions, "kept": kept, "spec": spec}


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
