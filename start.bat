@echo off
cd /d "%~dp0"

where py >nul 2>&1
if not errorlevel 1 goto usepy
where python >nul 2>&1
if not errorlevel 1 goto usepython
goto nopython

:usepy
py -3 start.py
goto done

:usepython
python start.py
goto done

:nopython
echo.
echo   [!] Python not found.
echo.
echo       Install from https://www.python.org/downloads/
echo       IMPORTANT: check "Add python.exe to PATH" in the installer.
echo.
pause
exit /b 1

:done
pause
