"""본문 — **원본 밴드를 순서대로 그대로.** 폭 860 한 줄.

여기에는 **판단이 없다.** 무엇이 제목이고 무엇이 사진인지 가르지 않고, 구간을 열지
않고, 번호를 붙이지 않고, 글자를 떼거나 덮거나 다시 쓰지 않는다. 받은 밴드를 받은
차례대로 싣는다.

**왜 다 지웠는가.** 여기 있던 것들은 하나같이 "원본을 반쯤 뜯어 다시 세우는" 일이었다.
종류 다섯으로 가르고(제목·설명·사진·글자박힌사진·장식), 제목이 구간을 열게 하고,
연달아 나온 제목 중 하나를 고르고, 3분의 2가 넘으면 통째로 싣고, 글자 덩어리를
배경색으로 덮고 그 자리에 우리 폰트로 다시 쓰고 — 그때마다 뜯긴 자국이 남았다.
사진이 뚫리고, 지시선이 끊기고, 같은 글이 두 번 나오고, 글자가 원본의 두 배로
앉았다. 고칠 때마다 다른 자리가 터졌다.

원본은 사진과 글을 한 덩어리로 짜 놓은 디자인이다. 그대로 실으면 손님은 그 디자인을
그대로 본다. 잃는 것은 "그 글이 우리 글이 아니라는 것" 하나뿐이다.
"""
from __future__ import annotations

import base64
from pathlib import Path

CSS = """
.bpage{max-width:860px;margin:0 auto}
.bpage img{display:block;max-width:100%;margin:0 auto}
"""


def _uri(path: Path) -> str:
    ext = path.suffix.lstrip(".").lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def render(files: list[Path], embed: bool = True) -> str:
    """밴드들을 순서대로 싣는다. 그것이 전부다."""
    out = [f"<style>{CSS}</style>", '<div class="bpage">']
    out += [f'<img src="{_uri(f) if embed else f.name}" alt="">' for f in files]
    out.append("</div>")
    return "\n".join(out)
