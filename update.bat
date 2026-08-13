@echo off
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 goto usepy
where python >nul 2>&1
if not errorlevel 1 goto usepython
goto nopython

:usepy
py -3 update.py
goto done

:usepython
python update.py
goto done

:nopython
echo.
echo   [!] Python not found.
echo.
pause
exit /b 1

:done
pause
