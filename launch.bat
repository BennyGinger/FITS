@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m fits.gui.main %*
if errorlevel 1 pause
