@echo off
setlocal
cd /d "%~dp0"
where git >nul 2>&1
if errorlevel 1 (
    echo Git is required. Install Git, then run this installer again.
    goto failed
)
echo uv is required by FIScH and will be installed if missing.
echo uv is maintained independently; FIScH does not manage its updates or removal.
where uv >nul 2>&1
if errorlevel 1 set "PATH=%PATH%;%USERPROFILE%\.local\bin"
where uv >nul 2>&1
if errorlevel 1 (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0startup\install_uv.ps1"
    if errorlevel 1 goto failed
)
where uv >nul 2>&1
if errorlevel 1 goto failed
set "FISCH_BOOTSTRAP_PYTHON="
for /f "delims=" %%P in ('uv python find --system --managed-python 3.12 2^>nul') do set "FISCH_BOOTSTRAP_PYTHON=%%P"
if not defined FISCH_BOOTSTRAP_PYTHON (
    uv python install 3.12
    if errorlevel 1 goto failed
    for /f "delims=" %%P in ('uv python find --system --managed-python 3.12') do set "FISCH_BOOTSTRAP_PYTHON=%%P"
)
if not defined FISCH_BOOTSTRAP_PYTHON goto failed
"%FISCH_BOOTSTRAP_PYTHON%" startup\setup.py --pause %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo FIScH installation failed. See startup\logs\install.log if it was created.
pause
exit /b 1
