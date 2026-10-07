@echo off
setlocal
call "%~dp0..\setup.bat" viewer %*
exit /b %errorlevel%
