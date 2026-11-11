@echo off
cd /d %~dp0
if exist app\__pycache__ rmdir /s /q app\__pycache__
if exist app\transaction\__pycache__ rmdir /s /q app\transaction\__pycache__
if exist app\masters\__pycache__ rmdir /s /q app\masters\__pycache__
C:\Users\Admin\AppData\Local\Programs\Python\Python310\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8081 --app-dir "%~dp0"
pause
