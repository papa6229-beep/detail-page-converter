"""통이미지 분할기.

    from slicer import slice_path
    result = slice_path("detail.jpg")
"""

from .background import Section, find_sections
from .gaps import GapSplit, group_by_gaps, split_gaps
from .geometry import Rect
from .layout import CutConfig, Node, build_columns, gutter_extents, trim
from .slicer import SliceResult, Unit, ink_coverage, slice_image

__all__ = [
    "CutConfig",
    "GapSplit",
    "Node",
    "Rect",
    "Section",
    "SliceResult",
    "Unit",
    "find_sections",
    "group_by_gaps",
    "ink_coverage",
    "slice_image",
    "slice_path",
    "build_columns",
    "gutter_extents",
    "trim",
    "split_gaps",
]


def slice_path(path, **kwargs) -> SliceResult:
    """이미지 파일 하나를 분할한다."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as im:
        arr = np.asarray(im.convert("RGB"))
    return slice_image(arr, **kwargs)
