@echo off
cd /d %~dp0\..\..
call .venv\Scripts\activate
python scripts\options_oi\fetch_options_oi.py --index NIFTY,BANKNIFTY --days 40 %*
pause
