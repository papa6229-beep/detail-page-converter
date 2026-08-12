#!/usr/bin/env bash
# 상세페이지 변환기 — 맥 · 리눅스용
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "  상세페이지 변환기"
echo "  ------------------------------------"
echo

if command -v python3 > /dev/null 2>&1; then
  PY=python3
elif command -v python > /dev/null 2>&1; then
  PY=python
else
  echo "  [!] 파이썬이 없습니다."
  echo
  echo "      맥이라면 터미널에 이렇게 치세요:  brew install python"
  echo "      또는 https://www.python.org/downloads/ 에서 받아 설치하세요."
  echo
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "  처음 실행이라 준비를 합니다. 2~3분 걸립니다..."
  echo
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip --quiet
  .venv/bin/python -m pip install -r requirements.txt
  echo
  echo "  준비 끝."
  echo
fi

PORT="${CONVERTER_PORT:-8000}"
echo "  브라우저에서 http://127.0.0.1:$PORT 을 여세요."
echo "  끄려면 이 창에서 Ctrl+C 를 누르세요."
echo

open_browser() {
  sleep 2
  if command -v open > /dev/null 2>&1; then
    open "http://127.0.0.1:$PORT"
  elif command -v xdg-open > /dev/null 2>&1; then
    xdg-open "http://127.0.0.1:$PORT"
  fi
}
open_browser > /dev/null 2>&1 &

exec .venv/bin/python -m app.server
