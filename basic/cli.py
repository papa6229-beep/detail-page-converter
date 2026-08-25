"""시제품 실행.

    python -m basic.cli 본문1.jpg [본문2.jpg …] --out out/상품코드 [--key sk-…] [--texts read.json]

--key 를 주면 글자 조각을 읽어 채운다. 안 주면 환경변수(ANTHROPIC_API_KEY · OPENAI_API_KEY)
에서 찾는다. 그것도 없으면 글자 자리에 조각 이미지를 그대로 보여준다 — 왜 안 읽었는지 말한다.
--texts 는 미리 읽어 둔 결과(JSON)를 넣는 자리 — 같은 상품을 다시 돌릴 때 AI 를 또 부르지 않는다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import body, read_text, render


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--key", default="")
    ap.add_argument("--texts", default="")
    a = ap.parse_args()

    out = Path(a.out)
    assets = out / "assets"
    pieces = []
    for n, img in enumerate(a.images):
        pieces += body.read_image(Path(img), assets, prefix=f"i{n}_")

    crops = [p for p in pieces if p.crop and p.kind != body.BADGE]
    key = a.key.strip() or read_text.key_from_env()
    texts: dict[str, str] = {}
    if a.texts:
        texts = json.loads(Path(a.texts).read_text(encoding="utf-8"))
    elif key:
        texts = read_text.read(key, [assets / p.crop for p in crops])
        (out / "texts.json").write_text(json.dumps(texts, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        print("키가 없다 — 글자를 안 읽고 조각 이미지를 그대로 둔다."
              " --key 를 주거나 ANTHROPIC_API_KEY · OPENAI_API_KEY 를 넣어라.")
    for i, p in enumerate(crops):
        p.text = texts.get(str(i), texts.get(p.crop, ""))

    secs = body.sections(pieces)
    (out / "index.html").write_text(
        '<!doctype html><meta charset="utf-8">'
        '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">'
        + render.render(secs, assets), encoding="utf-8")

    # 사람이 볼 장부
    log = [f"밴드 {len(pieces)}개 → 섹션 {len(secs)}개 · 읽을 조각 {len(crops)}개"]
    for p in pieces:
        log.append(f"  y={p.y:5d} h={p.h:4d} {p.kind:6} [{p.band_kind}] {p.why}")
    (out / "log.txt").write_text("\n".join(log), encoding="utf-8")
    print("\n".join(log))


if __name__ == "__main__":
    main()
