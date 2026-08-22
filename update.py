"""최신 코드로 갱신한다.

    python update.py

zip 을 다시 받지 않는다. git 이 바뀐 것만 가져온다.
requirements.txt 가 바뀌었을 때만 라이브러리를 다시 깐다.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQ = ROOT / "requirements.txt"
REPO = "https://github.com/papa6229-beep/detail-page-converter.git"


def setup_console() -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def has_git() -> bool:
    return shutil.which("git") is not None


def is_clone() -> bool:
    return (ROOT / ".git").exists()


def _git(*args):
    return subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def _req_hash() -> str:
    return hashlib.sha1(REQ.read_bytes()).hexdigest() if REQ.exists() else ""


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def explain_no_git() -> None:
    print("  이 폴더는 zip 을 푼 것이라 자동 갱신이 안 됩니다.")
    print()
    print("  한 번만 아래대로 옮겨두면, 다음부터는 zip 을 받을 일이 없습니다.")
    print()
    step = 1
    if not has_git():
        print(f"   {step}. https://git-scm.com/download/win 에서 Git 을 설치합니다")
        print("      (설치 화면은 전부 다음/Next 로 넘기면 됩니다)")
        step += 1
    print(f"   {step}. 새 폴더를 하나 만들고 그 안에서 오른쪽 클릭 →")
    print("      '터미널에서 열기' 또는 'Git Bash Here' 를 누른 뒤 아래를 붙여넣습니다")
    print()
    print(f"      git clone {REPO}")
    print()
    print("   처음 한 번만 GitHub 로그인 창이 뜹니다. 그다음부터는 안 물어봅니다.")
    print("   받아진 폴더의 실행.bat 을 쓰시면 됩니다. 켤 때마다 알아서 최신이 됩니다.")


def pull(quiet: bool = False) -> bool:
    """최신으로 당긴다. 실제로 뭔가 바뀌면 True."""
    if not is_clone() or not has_git():
        if not quiet:
            explain_no_git()
        return False

    # 추적 중인 파일만 본다. 실행하면서 생기는 .venv · work 같은 폴더까지 세면
    # 첫 실행 이후로 영영 "고친 것이 있다"가 되어 갱신이 멈춘다. 실제로 그랬다.
    if _git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        # quiet 여부와 무관하게 이유는 말한다. 조용히 건너뛰면 원인을 못 찾는다.
        print("  이 폴더의 코드를 직접 고치셨네요. 덮어쓰지 않으려고 갱신을 건너뜁니다.")
        print("  고친 것을 되돌리고 최신으로 받으려면:  git checkout . 후 다시 실행")
        return False

    before = _git("rev-parse", "HEAD").stdout.strip()
    req_before = _req_hash()

    result = _git("pull", "--ff-only")
    if result.returncode != 0:
        # 원격 쪽 역사가 다시 쓰였을 때(force push) 는 이어붙이기가 안 된다.
        # 이 폴더는 코드를 받아 쓰기만 하고 고친 것이 없으므로(위에서 확인함)
        # 원격 상태로 맞추면 그만이다.
        _git("fetch", "--all", "--prune")
        upstream = _git("rev-parse", "--abbrev-ref", "@{u}").stdout.strip()
        if not upstream or _git("reset", "--hard", upstream).returncode != 0:
            # **quiet 여부와 무관하게 말한다.** 조용히 실패하면 옛 코드가 도는 줄
            # 모른 채 결과물만 보고 원인을 엉뚱한 데서 찾게 된다. 실제로 그랬다.
            print("  갱신하지 못했습니다:")
            print("  " + (result.stderr or result.stdout).strip()[:400])
            return False

    after = _git("rev-parse", "HEAD").stdout.strip()
    if before == after:
        if not quiet:
            print("  이미 최신입니다.")
        return False

    print("  새로 받은 내용:")
    for line in _git("log", "--oneline", f"{before}..{after}").stdout.strip().splitlines():
        print("    " + line)

    if _req_hash() != req_before:
        py = venv_python()
        if py.exists():
            print()
            print("  필요한 라이브러리가 바뀌어 다시 깝니다...")
            subprocess.run([str(py), "-m", "pip", "install", "-r", str(REQ), "--quiet"], check=False)
    return True


def main() -> int:
    setup_console()
    print()
    print("  상세페이지 변환기 — 갱신")
    print("  " + "-" * 36)
    print()
    changed = pull()
    print()
    if changed:
        print("  갱신 끝. 실행.bat 을 다시 실행하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
