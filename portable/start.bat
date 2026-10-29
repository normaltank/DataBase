@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0runtime\python.exe" goto missing
"%~dp0runtime\python.exe" -I -B "%~dp0portable\launch.py" start %*
if errorlevel 1 pause
exit /b
:missing
echo Runtime missing. Extract the complete ZIP to a writable local folder first.
pause
exit /b 1
