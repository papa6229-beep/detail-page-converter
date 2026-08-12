"""번호 찍힌 컨택트시트 — DESIGN.md 4.2.

비전에게 좌표를 묻지 않는다. 조각에 번호를 붙여 한 판에 놓고 보여준 뒤
**번호로** 답하게 한다. 그러면 좌표 오차가 원천적으로 사라진다.

광고컷 판정은 문서 내 위치가 필요하므로(상단에 붙는 것이 정의의 일부)
조각을 하나씩 따로 묻지 말고 전체를 한 번에 보여줘야 한다. 그래서 한 판이다.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

#: 유닛 테두리 / 이미지 조각 / 캡션 조각
UNIT_COLOR = (255, 0, 0)
IMAGE_COLOR = (0, 140, 255)
CAPTION_COLOR = (0, 180, 60)


def _font(size: int):
    from PIL import ImageFont

    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(img: Image.Image, result, scale: float = 1.0) -> Image.Image:
    """원본 위에 유닛 번호와 조각 경계를 그린다."""
    if scale != 1.0:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
    sheet = img.convert("RGB").copy()
    draw = ImageDraw.Draw(sheet)
    font = _font(max(11, int(18 * scale)))

    def box(rect, color, width):
        draw.rectangle(
            [rect.x0 * scale, rect.y0 * scale, rect.x1 * scale, rect.y1 * scale],
            outline=color,
            width=width,
        )

    for i, unit in enumerate(result.units):
        for part in unit.parts:
            box(part, CAPTION_COLOR if part in unit.captions else IMAGE_COLOR, 1)
        box(unit.rect, UNIT_COLOR, 2)

        label = str(i)
        x, y = unit.rect.x0 * scale + 2, unit.rect.y0 * scale + 2
        tw = draw.textlength(label, font=font)
        draw.rectangle([x, y, x + tw + 6, y + font.size + 6], fill=UNIT_COLOR)
        draw.text((x + 3, y + 2), label, fill=(255, 255, 255), font=font)

    return sheet


def export_units(img: Image.Image, result, outdir) -> list[str]:
    """유닛별 이미지 조각을 파일로 떨군다."""
    from pathlib import Path

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, unit in enumerate(result.units):
        r = unit.image
        path = outdir / f"unit_{i:03d}.png"
        img.crop((r.x0, r.y0, r.x1 + 1, r.y1 + 1)).save(path)
        paths.append(str(path))
    return paths
