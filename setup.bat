@echo off
setlocal
cd /d "%~dp0"
if defined PXBP_PYTHON goto explicit_python
where py >nul 2>nul
if errorlevel 1 goto path_python
py -3.12 "%~dp0scripts\setup_environment.py" %*
exit /b %errorlevel%
:explicit_python
"%PXBP_PYTHON%" "%~dp0scripts\setup_environment.py" %*
exit /b %errorlevel%
:path_python
python "%~dp0scripts\setup_environment.py" %*
exit /b %errorlevel%
