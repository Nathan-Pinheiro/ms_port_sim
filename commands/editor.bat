@echo off
cd /d "%~dp0.."
python src\port_editor_tk.py
if errorlevel 1 pause
