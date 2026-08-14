"""두 회사 모델로 같은 상품을 돌려 문구를 나란히 놓고 본다.

    python compare.py 2481433

어느 쪽이 나은지는 제가 기억으로 답할 일이 아닙니다. **실제 파일로 재야** 합니다.
한글이 작게 박힌 그림을 읽는 일이라, 남의 벤치마크 점수는 이 원본에 대해
아무것도 말해주지 않습니다.

키는 환경변수나 아래 물음에서 받습니다. 값은 화면에만 나오고 저장하지 않습니다.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app import convert, excel, llm, server, source  # noqa: E402

WORK = Path(os.environ.get("CONVERTER_WORK", ROOT / "work"))
CACHE = WORK / "_cache"


def ask(name: str, env: str) -> str:
    key = os.environ.get(env, "").strip()
    if key:
        return key
    try:
        import getpass

        return getpass.getpass(f"  {name} 키 (엔터 치면 건너뜀): ").strip()
    except Exception:
        return ""


def run(key: str, work, job_dir: Path) -> tuple[list[str], float, str]:
    """한 회사로 한 번 물어본다. (문구들, 걸린 시간, 오류)"""
    import base64

    parts: list[tuple[str, str]] = [("text", server.PROMPT)]
    n = 0
    for u in work.product.units:
        crop = job_dir / u.caption_crop if u.caption_crop else None
        if crop and crop.exists():
            n += 1
            parts.append(("text", f"#{n}"))
            parts.append(("image", base64.b64encode(crop.read_bytes()).decode()))
        elif u.caption.strip():
            n += 1
            parts.append(("text", f"#{n}"))
            parts.append(("text", u.caption.strip()))
    if not n:
        return [], 0.0, "다듬을 문구가 없습니다"

    t = time.time()
    try:
        out = server._ask(key, parts)
    except Exception as e:
        return [], time.time() - t, str(e)[:200]
    text, _stop = llm.extract(key, out)
    got = server._parse_captions(text) or []
    return got, time.time() - t, "" if got else f"해석 실패: {text[:120]!r}"


def main() -> int:
    code = sys.argv[1] if len(sys.argv) > 1 else ""
    sheets = sorted(Path(os.environ.get("CONVERTER_XLSX", ROOT)).glob("*.xlsx"))
    row = None
    for f in sheets:
        for r in excel.load(f.read_bytes()).rows:
            if not code or r.code == code:
                row = r
                break
        if row:
            break
    if row is None:
        print("엑셀에서 그 상품을 못 찾았습니다. 엑셀을 이 폴더에 두고 상품번호를 주세요.")
        print("  예:  python compare.py 2481433")
        return 1

    print()
    print(f"  {row.code}  {row.name[:50]}")
    print("  " + "-" * 60)
    job = WORK / "compare"
    work = convert.convert(row, job, CACHE)
    p = work.product
    print(f"  {p.adapter} · 유닛 {len(p.units)}개 · 읽을 문구 {sum(1 for u in p.units if u.caption_crop or u.caption)}칸")
    print()

    results = {}
    for label, env in (("Anthropic", "ANTHROPIC_API_KEY"), ("OpenAI", "OPENAI_API_KEY")):
        key = ask(label, env)
        if not key:
            continue
        model = llm.model_for(llm.provider_of(key))
        print(f"  {label} ({model}) 물어보는 중…")
        got, secs, err = run(key, work, job)
        results[label] = (got, secs, err, model)
        print(f"    {secs:.1f}초 · {len(got)}칸" + (f" · {err}" if err else ""))
    print()

    if len(results) < 2:
        print("  둘 다 넣어야 비교가 됩니다.")
        return 0

    a, b = results.get("Anthropic"), results.get("OpenAI")
    print("  " + "=" * 60)
    for i in range(max(len(a[0]), len(b[0]))):
        print(f"  #{i + 1}")
        print(f"    A  {a[0][i] if i < len(a[0]) else '—'}")
        print(f"    O  {b[0][i] if i < len(b[0]) else '—'}")
    print("  " + "=" * 60)
    print(f"  Anthropic {a[3]}  {a[1]:.1f}초 · {len(a[0])}칸")
    print(f"  OpenAI    {b[3]}  {b[1]:.1f}초 · {len(b[0])}칸")
    print()
    print("  볼 것: 한글을 제대로 읽었나 · 수치가 원본과 같나 · 문구가 어색하지 않나")
    (job / "compare.json").write_text(
        json.dumps({k: {"model": v[3], "seconds": v[1], "captions": v[0]} for k, v in results.items()},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  전문은 {job / 'compare.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
