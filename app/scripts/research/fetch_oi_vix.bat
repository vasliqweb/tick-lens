@echo off
cd /d %~dp0\..\..
call .venv\Scripts\activate
python scripts\research\fetch_oi_vix.py
pause
