Mollick Krishi Bhandar FastAPI Login + Dashboard (Unified)

This package combines the working professional login screen with the V6 dashboard in ONE project.
Static files are mounted correctly so dashboard.css will load.

Database:
- Login users: python_login
- Company/Product/District counts: benfed_fertilizer
- MySQL: localhost / root / blank password

Install:
C:\Users\Admin\AppData\Local\Programs\Python\Python310\python.exe -m pip install -r requirements.txt

Run:
C:\Users\Admin\AppData\Local\Programs\Python\Python310\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080

Open:
http://localhost:8080

Default login:
admin / 1234

Important:
Stop any older Uvicorn process using port 8080 before starting this project.
If 8080 is already occupied, use `netstat -ano | findstr :8080` to identify the PID.
