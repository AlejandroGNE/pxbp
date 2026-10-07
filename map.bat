@echo off
setlocal
cd /d "%~dp0"
set "PXBP_NATIVE=%~dp0.venv-native\Scripts\python.exe"
if not exist "%PXBP_NATIVE%" (
    echo Native environment missing. Run setup.bat native first.
    exit /b 1
)
"%PXBP_NATIVE%" "%~dp0mappings.py"
exit /b %errorlevel%
