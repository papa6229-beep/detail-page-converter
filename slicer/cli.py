"""분할기 CLI.

    python -m slicer.cli <이미지> --out out/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from . import contactsheet
from .background import DEFAULT_TOL
from .layout import CutConfig
from .slicer import slice_image


def build_report(result) -> dict:
    return {
        "sections": [
            {"y0": s.y0, "y1": s.y1, "h": s.h, "bg": list(s.bg), "dark": s.is_dark}
            for s in result.sections
        ],
        "column_counts": result.column_counts,
        "ink_coverage": round(result.ink_coverage, 6),
        "n_units": result.n_units,
        "n_panels": len(result.panels),
        "units": [
            {
                "index": i,
                "section": u.section,
                "column": u.column,
                "rect": list(u.rect.as_tuple()),
                "image": list(u.image.as_tuple()),
                "captions": [list(c.as_tuple()) for c in u.captions],
                "has_caption": u.has_caption,
            }
            for i, u in enumerate(result.units)
        ],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="통이미지를 유닛 배열로 분할한다")
    ap.add_argument("image")
    ap.add_argument("--out", default="out", help="결과를 쓸 디렉터리")
    ap.add_argument("--tol", type=int, default=DEFAULT_TOL, help="배경색 허용 오차")
    ap.add_argument("--max-rule", type=int, default=6, help="괘선으로 볼 최대 두께(px)")
    ap.add_argument("--min-panel", type=int, default=8, help="조각 최소 크기(px)")
    ap.add_argument("--gap-ratio", type=float, default=2.0, help="간격 두 무리를 가를 최소 비")
    ap.add_argument("--sheet-scale", type=float, default=1.0, help="컨택트시트 배율")
    ap.add_argument("--export-units", action="store_true", help="유닛 이미지 조각도 파일로 떨군다")
    args = ap.parse_args(argv)

    with Image.open(args.image) as im:
        img = im.convert("RGB")
    arr = np.asarray(img)

    cfg = CutConfig(tol=args.tol, max_rule=args.max_rule, min_panel=args.min_panel)
    result = slice_image(arr, tol=args.tol, cfg=cfg, min_gap_ratio=args.gap_ratio)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    report = build_report(result)
    (outdir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    contactsheet.render(img, result, scale=args.sheet_scale).save(outdir / "contactsheet.png")
    if args.export_units:
        contactsheet.export_units(img, result, outdir / "units")

    print(f"구간 {len(result.sections)}개 · 유닛 {result.n_units}개 · 조각 {len(result.panels)}개")
    for s in result.sections:
        print(f"  구간 y {s.y0}-{s.y1} bg={s.bg} {'어두움' if s.is_dark else '밝음'}")
    print(f"  열 구성: {result.column_counts}")
    print(f"  불변식 ① 잉크 보존율: {result.ink_coverage:.4f}")
    print(f"  → {outdir}/contactsheet.png, {outdir}/report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
