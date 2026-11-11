from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME
from ..database import get_connection

router = APIRouter(prefix="/commission-slabs", tags=["Commission Slabs Master"])
BASE_DIR = Path(__file__).resolve().parents[2]
from ..sidebar_context import sidebar_context


templates = Jinja2Templates(directory=str(BASE_DIR / "templates"), context_processors=[sidebar_context])


def ensure_commission_slabs_table():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS commission_slabs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                effective_dt DATE NOT NULL,
                from_days INT NOT NULL,
                to_days INT NOT NULL,
                commission_percentage DECIMAL(5,2) NOT NULL,
                status CHAR(1) NOT NULL DEFAULT 'A',
                CONSTRAINT chk_commission_days CHECK (from_days >= 0 AND to_days >= from_days),
                CONSTRAINT chk_commission_percentage CHECK (commission_percentage >= 0 AND commission_percentage <= 100)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci
        """)
        conn.commit()
    finally:
        cur.close()
        conn.close()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, search: str = Query(default=""), status: str = Query(default=""), edit_id: int = Query(default=0), message: str = Query(default="")):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        sql = "SELECT id, effective_dt, from_days, to_days, commission_percentage, status FROM commission_slabs WHERE 1=1"
        params = []
        if search.strip():
            sql += " AND CAST(id AS CHAR) LIKE %s"
            params.append(f"%{search.strip()}%")
        if status in ("A", "I"):
            sql += " AND status=%s"
            params.append(status)
        sql += " ORDER BY effective_dt DESC, from_days ASC, id DESC"
        cur.execute(sql, params)
        slabs = cur.fetchall()
        edit_row = None
        if edit_id:
            cur.execute("SELECT id, effective_dt, from_days, to_days, commission_percentage, status FROM commission_slabs WHERE id=%s", (edit_id,))
            edit_row = cur.fetchone()
        return templates.TemplateResponse(request=request, name="masters/commission_slabs.html", context={
            "request": request, "slabs": slabs, "edit_row": edit_row, "search": search,
            "status_filter": status, "message": message, "user_type": request.session.get("user_type", "USER"),
            "today": date.today().isoformat()
        })
    finally:
        cur.close()
        conn.close()


@router.post("/save")
async def save(request: Request, id: int = Form(default=0), effective_dt: str = Form(...), from_days: int = Form(...), to_days: int = Form(...), commission_percentage: Decimal = Form(...), status: str = Form(default="A")):
    if from_days < 0 or to_days < from_days or commission_percentage < 0 or commission_percentage > 100 or status not in ("A", "I"):
        return RedirectResponse(url="/commission-slabs/?message=Please+check+the+entered+values" + (f"&edit_id={id}" if id else ""), status_code=303)
    conn = get_connection()
    cur = conn.cursor()
    try:
        values = (effective_dt, from_days, to_days, commission_percentage, status)
        if id:
            cur.execute("UPDATE commission_slabs SET effective_dt=%s, from_days=%s, to_days=%s, commission_percentage=%s, status=%s WHERE id=%s", values + (id,))
            msg = "Commission slab updated"
        else:
            cur.execute("INSERT INTO commission_slabs (effective_dt, from_days, to_days, commission_percentage, status) VALUES (%s,%s,%s,%s,%s)", values)
            msg = "Commission slab added"
        conn.commit()
        return RedirectResponse(url="/commission-slabs/?message=" + msg.replace(" ", "+"), status_code=303)
    finally:
        cur.close()
        conn.close()


@router.post("/toggle/{slab_id}")
async def toggle_status(slab_id: int):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE commission_slabs SET status=IF(status='A','I','A') WHERE id=%s", (slab_id,))
        conn.commit()
        return RedirectResponse(url="/commission-slabs/?message=Status+updated", status_code=303)
    finally:
        cur.close()
        conn.close()
