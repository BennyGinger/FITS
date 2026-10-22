@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>&1
if errorlevel 1 (
    echo uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/
    goto failed
)
where git >nul 2>&1
if errorlevel 1 (
    echo Git is required. Install Git, then run this installer again.
    goto failed
)
uv run --no-project --python 3.12 python installation/setup.py %*
if errorlevel 1 goto failed
pause
exit /b 0
:failed
echo FITS installation failed. See installation\logs\install.log if it was created.
pause
exit /b 1
