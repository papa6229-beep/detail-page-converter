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


def 지금코드() -> str:
    """지금 돌고 있는 코드가 무엇인지 한 줄로. git 이 아니면 빈 문자열.

    ⚠️ **이게 없어서 옛 코드가 도는 줄 모르고 한참을 헤맸다.** 규칙을 바꿔
    올렸는데 결과물이 옛 규칙 그대로였고, 화면 어디에도 무슨 코드가 도는지
    안 나와서 사장님이 확인할 방법이 없었다. 켤 때마다 찍는다.
    """
    import subprocess

    try:
        r = subprocess.run(["git", "log", "--oneline", "-1"], cwd=str(ROOT),
                           capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    # 한국어 윈도우에서 text=True 로 받으면 cp949 로 풀다 터진다. 바이트로 받는다.
    return r.stdout.decode("utf-8", "replace").strip() if r.returncode == 0 else ""


def auto_update() -> None:
    """켤 때 알아서 최신으로 당긴다.

    zip 을 매번 다시 받는 것이 가장 불편한 지점이었다. git 으로 받아 두면
    바뀐 것만 조용히 따라온다. 직접 고친 내용이 있으면 건드리지 않는다.
    CONVERTER_NO_UPDATE=1 이면 건너뛴다.

    ⚠️ **안 됐으면 왜 안 됐는지 반드시 말한다.** 예전에는 `except Exception:
    pass` 로 통째로 삼켰다. 그래서 갱신이 조용히 안 되고 있어도 아무도 몰랐다.
    실행을 막지는 않되, 입은 다물지 않는다.
    """
    if os.environ.get("CONVERTER_NO_UPDATE"):
        print("  CONVERTER_NO_UPDATE 가 켜져 있어 갱신을 건너뜁니다.")
        return
    try:
        import update
    except Exception as e:
        print(f"  [!] 갱신 코드를 못 읽었습니다 — {type(e).__name__}: {e}")
        return
    if not update.is_clone():
        print("  이 폴더는 zip 을 푼 것이라 자동 갱신이 안 됩니다.")
        print("  git 으로 받아 두면 켤 때마다 알아서 최신이 됩니다 (README 의 '코드 받기').")
        return
    if not update.has_git():
        print("  git 이 없어 자동 갱신을 못 합니다.")
        print("  https://git-scm.com/download/win 에서 설치하면 됩니다.")
        return
    try:
        if update.pull(quiet=True):
            print()
    except Exception as e:
        print(f"  [!] 갱신 중 문제가 있었습니다 — {type(e).__name__}: {e}")


def main() -> int:
    _setup_console()
    print()
    print("  상세페이지 변환기")
    print("  " + "-" * 36)
    print()
    auto_update()

    코드 = 지금코드()
    if 코드:
        print(f"  지금 도는 코드 : {코드}")
        print()

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
