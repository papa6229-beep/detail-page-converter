@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo.
echo   상세페이지 변환기
echo   ------------------------------------
echo.

rem 파이썬 찾기. py 런처를 먼저 보고, 없으면 python 을 본다.
rem (블록 안에서 %errorlevel% 을 읽으면 파싱 시점 값이라 틀린다. 라벨로 흐름을 나눈다.)
where py > nul 2>&1
if not errorlevel 1 goto have_py
where python > nul 2>&1
if not errorlevel 1 goto have_python
goto no_python

:have_py
set "PY=py -3"
goto check_venv

:have_python
set "PY=python"
goto check_venv

:no_python
echo   [!] 파이썬이 없습니다.
echo.
echo       https://www.python.org/downloads/ 에서 받아 설치하세요.
echo       설치 첫 화면 맨 아래 "Add python.exe to PATH" 를 꼭 체크하세요.
echo.
pause
exit /b 1

:check_venv
if exist ".venv\Scripts\python.exe" goto run

echo   처음 실행이라 준비를 합니다. 2~3분 걸립니다...
echo.
%PY% -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo.
echo   준비 끝.
echo.

:run
echo   브라우저에서 http://127.0.0.1:8000 을 여세요.
echo   끄려면 이 창에서 Ctrl+C 를 누르거나 창을 닫으세요.
echo.
start "" http://127.0.0.1:8000
.venv\Scripts\python.exe -m app.server
pause
exit /b 0

:fail
echo.
echo   [!] 준비 중 문제가 생겼습니다. 위에 찍힌 메시지를 그대로 알려주세요.
echo.
pause
exit /b 1
