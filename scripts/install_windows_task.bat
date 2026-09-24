@echo off
REM Installs a logon task that keeps the gpu-maid agent running.
REM Usage: install_windows_task.bat C:\path\to\residents.json [taskname]
setlocal
set CONFIG=%1
if "%CONFIG%"=="" (
  echo usage: %~nx0 C:\path\to\residents.json [taskname]
  exit /b 1
)
set TASK=%2
if "%TASK%"=="" set TASK=gpumaid
set AGENT_DIR=%~dp0..

schtasks /Create /F /TN %TASK% /SC ONLOGON ^
  /TR "cmd /c cd /d %AGENT_DIR% && python -m gpumaid --config %CONFIG%"
if %errorlevel%==0 (
  echo Task "%TASK%" installed. Start it now with:  schtasks /Run /TN %TASK%
) else (
  echo schtasks failed - are you running from an elevated prompt?
  exit /b 1
)
