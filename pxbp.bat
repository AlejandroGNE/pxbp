@echo off
setlocal
cd /d "%~dp0"
set "PXBP_MODERN=%~dp0.venv\Scripts\python.exe"
if not exist "%PXBP_MODERN%" (
    echo Modern environment missing. Run setup.bat modern first.
    exit /b 1
)
"%PXBP_MODERN%" -m pxbp.cli %*
exit /b %errorlevel%
