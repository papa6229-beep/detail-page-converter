#!/usr/bin/env bash
# 상세페이지 변환기 — 맥 · 리눅스용
cd "$(dirname "$0")"
if command -v python3 > /dev/null 2>&1; then
  exec python3 start.py
elif command -v python > /dev/null 2>&1; then
  exec python start.py
else
  echo
  echo "  [!] 파이썬이 없습니다."
  echo
  echo "      맥이라면 터미널에:  brew install python"
  echo "      또는 https://www.python.org/downloads/ 에서 받으세요."
  echo
  exit 1
fi
