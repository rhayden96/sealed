@echo off
cd /d "%~dp0"
py -3 start.py %*
exit /b %ERRORLEVEL%
