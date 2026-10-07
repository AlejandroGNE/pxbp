@echo off
setlocal
cd /d "%~dp0"
set "PXBP_VIEWER=%~dp0.venv\Scripts\python.exe"
if not exist "%PXBP_VIEWER%" (
    echo Viewer environment missing. Run this folder's setup.bat first.
    exit /b 1
)
"%PXBP_VIEWER%" "%~dp0serve_viewer.py" %*
exit /b %errorlevel%
