@echo off
cd /d %~dp0
C:\Users\Admin\AppData\Local\Programs\Python\Python310\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
pause
