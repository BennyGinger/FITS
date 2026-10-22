@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>&1
if errorlevel 1 (
    echo uv is required. Install it from https://docs.astral.sh/uv/getting-started/startup/
    goto failed
)
where git >nul 2>&1
if errorlevel 1 (
    echo Git is required. Install Git, then run this installer again.
    goto failed
)
set "FITS_BOOTSTRAP_PYTHON="
for /f "delims=" %%P in ('uv python find --system --managed-python 3.12 2^>nul') do set "FITS_BOOTSTRAP_PYTHON=%%P"
if not defined FITS_BOOTSTRAP_PYTHON (
    uv python install 3.12
    if errorlevel 1 goto failed
    for /f "delims=" %%P in ('uv python find --system --managed-python 3.12') do set "FITS_BOOTSTRAP_PYTHON=%%P"
)
if not defined FITS_BOOTSTRAP_PYTHON goto failed
"%FITS_BOOTSTRAP_PYTHON%" startup\setup.py %*
if errorlevel 1 goto failed
pause
exit /b 0
:failed
echo FITS installation failed. See startup\logs\install.log if it was created.
pause
exit /b 1
