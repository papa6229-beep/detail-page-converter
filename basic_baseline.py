"""기본형 기준선 — 7개 상품의 대표컷·키피쳐·패키지·경계를 박아 두고 견준다.

    python basic_baseline.py save docs/basic_baseline.json   ← 기준선 박기
    python basic_baseline.py docs/basic_baseline.json        ← 견주기

단순형에 `compare_runs.py` 가 있는 것과 같은 자리다. **테스트가 못 지키는 것을
이것이 지킨다** — 임계값 하나를 건드리면 76개 테스트는 다 통과하는데 대표컷이
6칸 격자로 바뀐다. 그런 일이 실제로 있었다.

**AI 답은 돌릴 때마다 흔들린다.** 그래서 상품마다 모델 응답을 한 번만 받아
`out/basic_<코드>/ai_main.json` 에 저장하고, 그 뒤로는 그것을 다시 쓴다. 기준선이
재는 것은 **모델이 아니라 우리 거르기**다 — 같은 답을 넣었을 때 같은 밴드가
나오는가. 모델을 새로 부르려면 그 파일을 지우면 된다.

엑셀 경로는 이 컴퓨터 것이다. 다른 데서 돌리려면 `PRODUCTS` 를 고친다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
Image.MAX_IMAGE_PIXELS = None

from app import convert as _convert  # noqa: E402
from app import excel as _excel  # noqa: E402
from app import llm as _llm  # noqa: E402
from basic import boundary, main, web  # noqa: E402

#: 실물 7개. 픽셀 잣대를 고를 때 잰 것도 이 일곱이다.
PRODUCTS = [
    ("2479700", "핑거위글", r"D:\godo\test\설명용\새 폴더\복합형1_핑거위글.xlsx"),
    ("2421655", "브루스", r"C:\Users\BNN\Downloads\프리티 러브 브루스.xlsx"),
    ("2489604", "글랜스", r"C:\Users\BNN\Downloads\글렌스.xlsx"),
    ("2491798", "다일레이터", r"C:\Users\BNN\Downloads\테스트 (4).xlsx"),
    ("2498419", "벨벳키스", r"C:\Users\BNN\Downloads\테스트 (1).xlsx"),
    ("2416471", "유컵스", r"C:\Users\BNN\Downloads\테스트 (3).xlsx"),
    ("2486289", "죠우무", r"C:\Users\BNN\Downloads\테스트 (2).xlsx"),
]

CACHE = ROOT / "work" / "_cache"
OUT = ROOT / "out"


def row_of(code: str, xlsx: str):
    for r in _excel.load(xlsx).rows:
        if r.code == code:
            return r
    raise SystemExit(f"{code} 를 {xlsx} 에서 못 찾았다")


def reply_for(code: str, row, cuts, kinds) -> tuple[str, bool]:
    """모델 답. 저장해 둔 것이 있으면 그것을 쓴다. (답, 새로 불렀나)"""
    saved = OUT / f"basic_{code}" / "ai_main.json"
    if saved.exists():
        return saved.read_text(encoding="utf-8"), False
    key = _llm.key_from_env()
    if not key:
        raise SystemExit(f"{code}: 저장된 답도 없고 키도 없다. 키를 넣고 한 번 돌려야 한다.")
    parts = main.parts_for(row.name, row.brand or row.maker, web.typed_text(row), cuts, kinds)
    reply = web.ask_model(key, parts)
    saved.write_text(reply, encoding="utf-8")
    return reply, True


def run_one(code: str, label: str, xlsx: str) -> dict:
    row = row_of(code, xlsx)
    out = OUT / f"basic_{code}"
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    urls, _skipped = web.body_images(row)
    files = []
    for n, u in enumerate(urls):
        f = out / f"src_{n:02d}{Path(u.split('?')[0]).suffix.lower() or '.jpg'}"
        if not f.exists():
            f.write_bytes(_convert.fetch(u, CACHE))
        files.append(f)

    entries, cuts, kinds, hashes = web.cut_bands(files, assets)
    shots = web.shots_by_band(files, entries)
    blocked = boundary.summary_bands(entries)
    fallback, _why = boundary.find_body_start(entries)

    reply, fresh = reply_for(code, row, cuts, kinds)
    page, notes = main.take(reply, cuts, kinds, hashes, shots=shots, blocked=blocked)
    body_start = page.body_start if page.body_start >= 0 else fallback

    return {
        "label": label, "bands": len(cuts),
        "hero": page.main_band, "feature": page.feature_band,
        "package": page.package_band, "body_start": body_start,
        "notes": notes, "fresh": fresh,
    }


def run_all() -> dict[str, dict]:
    got = {}
    for code, label, xlsx in PRODUCTS:
        r = run_one(code, label, xlsx)
        mark = " (모델 새로 부름)" if r.pop("fresh") else ""
        print(f"  {label:6} {code}  대표컷 [{r['hero']:>3}] · 키피쳐 [{r['feature']:>3}] · "
              f"패키지 [{r['package']:>3}] · body_start {r['body_start']:>3}{mark}", flush=True)
        got[code] = r
    return got


#: 견줄 칸. `notes` 는 사람이 읽는 것이라 견주지 않는다 — 문구만 바뀌어도 시끄럽다.
FIELDS = ("hero", "feature", "package", "body_start", "bands")


def main_cli() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "save":
        where = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/basic_baseline.json")
        print("\n  기준선을 만든다\n")
        got = run_all()
        where.parent.mkdir(parents=True, exist_ok=True)
        where.write_text(json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n  {len(got)}개를 {where} 에 박았다\n")
        return 0

    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    old = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print("\n  지금 코드로 다시 돌린다\n")
    new = run_all()

    changed = []
    for code, want in old.items():
        got = new.get(code)
        if got is None:
            changed.append((code, want.get("label", ""), "이번엔 안 돌았다"))
            continue
        diff = [f"{k}: {want[k]} → {got[k]}" for k in FIELDS if want.get(k) != got.get(k)]
        if diff:
            changed.append((code, want.get("label", ""), " · ".join(diff)))

    print("\n  " + "─" * 64)
    print(f"  기준선 {len(old)}개 · 같음 {len(old) - len(changed)}개 · 달라짐 {len(changed)}개")
    for code, label, what in changed:
        print(f"  ● {label} {code}  {what}")
    if not changed:
        print("  달라진 것이 없습니다.")
    print("\n  볼 것: **고치려던 상품만** 달라졌는가. 아니면 그 커밋을 되돌린다.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
