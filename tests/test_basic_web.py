"""기본형 화면(basic/web.py)의 PAGE 안 JS 가 **평가된 뒤에도** 문법이 맞는가.

왜 이 테스트가 있나. PAGE 는 파이썬 일반 문자열이라 그 안의 `\\n` 을 파이썬이
먼저 먹는다. JS 홑따옴표 문자열 안에서 그 일이 벌어지면 문자열이 줄을 넘어가
끊기고, `<script>` 전체가 SyntaxError 로 죽는다. 그러면 `onchange` 가 안 붙어
**엑셀을 올려도 아무 일도 안 일어난다** — 화면은 멀쩡해 보이고 오류도 안 뜬다.
실제로 그렇게 한 번 죽었다.

소스를 읽는 것으로는 못 잡는다. 파이썬이 평가한 **결과**를 봐야 한다.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from basic.web import PAGE  # noqa: E402

SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.S)


def scripts() -> list[str]:
    return SCRIPT_RE.findall(PAGE)


def test_page_has_script():
    assert scripts(), "PAGE 에 <script> 가 없다"


@pytest.mark.skipif(not shutil.which("node"), reason="node 가 없다")
def test_page_script_parses(tmp_path):
    """node --check — 평가된 JS 를 그대로 파서에 먹인다."""
    for n, js in enumerate(scripts()):
        f = tmp_path / f"page_{n}.js"
        f.write_text(js, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, f"script[{n}] 문법 실패:\n{r.stderr}"


@pytest.mark.skipif(not shutil.which("node"), reason="node 가 없다")
def test_check_would_catch_the_old_bug(tmp_path):
    """검사기 자체가 그 버그를 잡는지 본다. 안 잡는 검사기는 없는 것과 같다.

    고치기 전 상태를 재현한다 — 평가된 PAGE 안의 두 글자 `\\n` 을 진짜 줄바꿈으로.
    """
    broken = PAGE.replace(chr(92) + "n", chr(10))
    js = SCRIPT_RE.findall(broken)[0]
    f = tmp_path / "broken.js"
    f.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert r.returncode != 0, "끊어진 문자열을 검사기가 못 잡았다"


def test_upload_handler_is_wired():
    """엑셀 올리기가 붙는 자리가 살아 있는가 — 화면이 조용히 죽는 것을 막는다."""
    js = "\n".join(scripts())
    assert "$('#f').onchange" in js
    assert "/api/basic/excel" in js
    assert "/api/basic/convert" in js


def test_pre_keeps_real_newlines():
    """`쓴 것 / 뺀 것` 목록은 줄이 나뉘어야 읽힌다 — JS 에 `\\n` 으로 도착해야 한다."""
    js = "\n".join(scripts())
    assert chr(92) + "n" in js, "JS 에 줄바꿈 이스케이프가 하나도 없다"
