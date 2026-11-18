@echo off
cd /d "%~dp0.."
solara run src\main.py
if errorlevel 1 pause
