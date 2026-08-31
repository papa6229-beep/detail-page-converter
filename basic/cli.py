"""시제품 실행 — 이미지 몇 장을 밴드로 잘라 **순서대로 그대로** 한 페이지로 만든다.

    python -m basic.cli 본문1.jpg [본문2.jpg …] --out out/상품코드

본문에는 판단이 없다. 무엇이 제목이고 무엇이 사진인지 가르지 않고, 구간을 열지 않고,
글자를 떼지 않는다. 그래서 AI 를 안 부른다 — 키도 필요 없다.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

from . import bands as B
from . import render

Image.MAX_IMAGE_PIXELS = None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    out = Path(a.out)
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    cuts: list[Path] = []
    for img in a.images:
        arr = np.asarray(Image.open(img).convert("RGB"))
        for b in B.read(arr):
            f = assets / f"band_{len(cuts):03d}.jpg"
            Image.fromarray(arr[b.y : b.y + b.height]).save(f, quality=90)
            cuts.append(f)

    (out / "index.html").write_text(
        '<!doctype html><meta charset="utf-8">' + render.render(cuts),
        encoding="utf-8", newline="\n")
    print(f"밴드 {len(cuts)}개 → {out / 'index.html'}")


if __name__ == "__main__":
    main()
