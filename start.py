"""변환기 시작 — 준비와 실행을 한 번에.

    python start.py

가상환경이 없으면 만들고, 필요한 것을 설치하고, 서버를 띄운다.
윈도우 배치 파일은 이 파일을 부르기만 한다. 배치 파일에 한글이나 로직을 넣으면
cmd 가 CP949 로 읽어 깨지고, 깨진 글자를 명령으로 실행하려 든다. 실제로 그랬다.
"""

from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PORT = os.environ.get("CONVERTER_PORT", "8000")


def _setup_console() -> None:
    """윈도우 콘솔에서도 한글이 깨지지 않게."""
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


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_venv() -> Path:
    py = venv_python()
    if py.exists():
        return py

    print("  처음 실행이라 준비를 합니다. 2~3분 걸립니다...")
    print()
    if VENV.exists():  # 지난번에 만들다 만 것이 남아 있으면 지우고 다시
        import shutil

        shutil.rmtree(VENV, ignore_errors=True)

    venv.EnvBuilder(with_pip=True, clear=True).create(VENV)
    py = venv_python()
    if not py.exists():
        raise SystemExit("  [!] 가상환경을 만들지 못했습니다.")

    subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip", "--quiet"], check=False)
    r = subprocess.run([str(py), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    if r.returncode != 0:
        raise SystemExit("  [!] 라이브러리 설치에 실패했습니다. 위 메시지를 그대로 알려주세요.")

    print()
    print("  준비 끝.")
    print()
    return py


def open_browser_later(url: str) -> None:
    import threading
    import webbrowser

    threading.Timer(2.5, lambda: webbrowser.open(url)).start()


def auto_update() -> None:
    """켤 때 알아서 최신으로 당긴다.

    zip 을 매번 다시 받는 것이 가장 불편한 지점이었다. git 으로 받아 두면
    바뀐 것만 조용히 따라온다. 직접 고친 내용이 있으면 건드리지 않는다.
    CONVERTER_NO_UPDATE=1 이면 건너뛴다.
    """
    if os.environ.get("CONVERTER_NO_UPDATE"):
        return
    try:
        import update

        if update.is_clone() and update.has_git() and update.pull(quiet=True):
            print()
    except Exception:
        pass  # 갱신 실패가 실행을 막지는 않는다


def main() -> int:
    _setup_console()
    print()
    print("  상세페이지 변환기")
    print("  " + "-" * 36)
    print()
    auto_update()

    if sys.version_info < (3, 10):
        print(f"  [!] 파이썬 3.10 이상이 필요합니다. 지금은 {sys.version.split()[0]} 입니다.")
        print("      https://www.python.org/downloads/ 에서 최신 버전을 받으세요.")
        return 1

    try:
        py = ensure_venv()
    except SystemExit as e:
        print(e)
        return 1

    url = f"http://127.0.0.1:{PORT}"
    print(f"  브라우저에서 {url} 을 여세요.")
    print("  끄려면 이 창에서 Ctrl+C 를 누르거나 창을 닫으세요.")
    print()

    open_browser_later(url)
    try:
        return subprocess.call([str(py), "-m", "app.server"], cwd=str(ROOT))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
