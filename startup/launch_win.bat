@echo off
setlocal
cd /d "%~dp0.."
set "FITS_BOOTSTRAP_PYTHON="
for /f "delims=" %%P in ('uv python find --system --managed-python 3.12') do set "FITS_BOOTSTRAP_PYTHON=%%P"
if not defined FITS_BOOTSTRAP_PYTHON (
    echo Could not find uv's managed Python. Run install_win.bat again.
    pause
    exit /b 1
)
"%FITS_BOOTSTRAP_PYTHON%" startup\launcher.py %*
if errorlevel 1 pause
