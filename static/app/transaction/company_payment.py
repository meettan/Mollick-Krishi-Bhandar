from pathlib import Path
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import mysql.connector
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME
from ..sidebar_context import sidebar_context

BASE_DIR = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"), context_processors=[sidebar_context])
router = APIRouter(prefix="/company-payments", tags=["Company Payments"])
DB = {"host": DB_HOST, "user": DB_USER, "password": DB_PASSWORD, "database": DB_NAME}


def db():
    return mysql.connector.connect(**DB)


def dec(value):
    try:
        return Decimal(str(value or "0").strip())
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def ensure_company_payments_table():
    conn = cur = None
    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS company_payments (
                id BIGINT NOT NULL AUTO_INCREMENT,
                payment_no VARCHAR(40) NOT NULL,
                purchase_id INT NOT NULL,
                company_id INT NOT NULL,
                payment_date DATE NOT NULL,
                paid_amount DECIMAL(18,2) NOT NULL DEFAULT 0.00,
                payment_mode VARCHAR(40) NOT NULL,
                reference_no VARCHAR(150) DEFAULT NULL,
                remarks VARCHAR(500) DEFAULT NULL,
                created_by INT DEFAULT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                UNIQUE KEY uk_company_payments_no (payment_no),
                KEY idx_company_payments_purchase (purchase_id),
                KEY idx_company_payments_company (company_id),
                KEY idx_company_payments_date (payment_date),
                CONSTRAINT fk_company_payments_purchase
                    FOREIGN KEY (purchase_id) REFERENCES purchase_master(id)
                    ON DELETE RESTRICT ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        # Repair the table shape supplied by older/manual SQL definitions:
        # id must be indexed and AUTO_INCREMENT because inserts omit id.
        cur.execute("""
            SELECT COLUMN_TYPE, EXTRA, IS_NULLABLE
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'company_payments'
              AND COLUMN_NAME = 'id'
        """)
        id_info = cur.fetchone()
        cur.execute("""
            SELECT COUNT(*) AS primary_count
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'company_payments'
              AND INDEX_NAME = 'PRIMARY'
        """)
        primary_info = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS total_rows, COUNT(id) AS nonnull_ids, COUNT(DISTINCT id) AS distinct_ids FROM company_payments")
        id_counts = cur.fetchone()
        if id_info and id_counts and id_counts['total_rows'] == id_counts['nonnull_ids'] == id_counts['distinct_ids']:
            if not primary_info or primary_info['primary_count'] == 0:
                cur.execute("ALTER TABLE company_payments ADD PRIMARY KEY (id)")
            if 'auto_increment' not in str(id_info['EXTRA']).lower():
                cur.execute("ALTER TABLE company_payments MODIFY id BIGINT(20) NOT NULL AUTO_INCREMENT")
        conn.commit()
    finally:
        if cur: cur.close()
        if conn: conn.close()


@router.get("/", response_class=HTMLResponse)
async def company_payment_page(request: Request, saved: str = "", error: str = ""):
    ensure_company_payments_table()
    conn = cur = None
    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT COMP_ID AS id, COMP_NAME AS name
            FROM mm_company_dtls
            ORDER BY COMP_NAME
        """)
        companies = cur.fetchall()

        cur.execute("""
            SELECT pm.id AS purchase_id, pm.company_id,
                   COALESCE(c.COMP_NAME, '') AS company_name,
                   pm.purchase_no, COALESCE(pm.invoice_no, '') AS invoice_no,
                   pm.purchase_date, pm.invoice_date,
                   pm.net_amount, pm.paid_amount,
                   GREATEST(COALESCE(pm.net_amount,0)-COALESCE(pm.paid_amount,0),0) AS outstanding
            FROM purchase_master pm
            LEFT JOIN mm_company_dtls c ON c.COMP_ID = pm.company_id
            ORDER BY c.COMP_NAME, pm.purchase_date DESC, pm.id DESC
        """)
        open_purchases = cur.fetchall()

        cur.execute("""
            SELECT cp.id, cp.payment_no, cp.payment_date, cp.paid_amount,
                   cp.payment_mode, cp.reference_no, cp.remarks,
                   pm.purchase_no, COALESCE(pm.invoice_no,'') AS invoice_no,
                   COALESCE(c.COMP_NAME,'') AS company_name
            FROM company_payments cp
            INNER JOIN purchase_master pm ON pm.id = cp.purchase_id
            LEFT JOIN mm_company_dtls c ON c.COMP_ID = cp.company_id
            ORDER BY cp.payment_date DESC, cp.id DESC
            LIMIT 500
        """)
        history = cur.fetchall()
        return templates.TemplateResponse(
            request=request,
            name="company_payments.html",
            context={"request": request, "companies": companies,
                     "open_purchases": open_purchases, "history": history,
                     "today": date.today().isoformat(), "saved": saved, "error": error},
        )
    except Exception as exc:
        return HTMLResponse(f"Company Payment screen error: {str(exc)}", status_code=500)
    finally:
        if cur: cur.close()
        if conn: conn.close()


@router.post("/save")
async def save_company_payment(
    request: Request,
    purchase_id: int = Form(...),
    payment_date: str = Form(...),
    paid_amount: str = Form(...),
    payment_mode: str = Form(...),
    reference_no: str = Form(""),
    remarks: str = Form(""),
):
    amount = dec(paid_amount).quantize(Decimal("0.01"))
    try:
        pay_date = datetime.strptime(payment_date, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse("/company-payments/?error=Invalid%20payment%20date", status_code=303)
    if amount <= 0:
        return RedirectResponse("/company-payments/?error=Payment%20amount%20must%20be%20greater%20than%20zero", status_code=303)

    conn = cur = None
    try:
        ensure_company_payments_table()
        conn = db()
        cur = conn.cursor(dictionary=True)
        conn.start_transaction()
        cur.execute("""
            SELECT id, company_id, purchase_no, net_amount, paid_amount
            FROM purchase_master WHERE id=%s FOR UPDATE
        """, (purchase_id,))
        purchase = cur.fetchone()
        if not purchase:
            conn.rollback()
            return RedirectResponse("/company-payments/?error=Purchase%20invoice%20not%20found", status_code=303)

        net = dec(purchase["net_amount"])
        already_paid = dec(purchase["paid_amount"])
        outstanding = max(net - already_paid, Decimal("0.00"))
        if amount > outstanding:
            conn.rollback()
            return RedirectResponse("/company-payments/?error=Payment%20cannot%20exceed%20invoice%20outstanding", status_code=303)

        new_paid = already_paid + amount
        new_outstanding = max(net - new_paid, Decimal("0.00"))
        cur.execute("""
            INSERT INTO company_payments
                (payment_no, purchase_id, company_id, payment_date, paid_amount,
                 payment_mode, reference_no, remarks, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            f"TMP-{uuid4().hex}", purchase_id, purchase["company_id"], pay_date, amount,
            payment_mode.strip().upper(), reference_no.strip() or None,
            remarks.strip() or None, request.session.get("user_id"),
        ))
        payment_id = cur.lastrowid
        payment_no = f"CPAY-{pay_date:%Y%m%d}-{payment_id:06d}"
        cur.execute("UPDATE company_payments SET payment_no=%s WHERE id=%s", (payment_no, payment_id))
        cur.execute("""
            UPDATE purchase_master
            SET paid_amount=%s, outstanding_amount=%s
            WHERE id=%s
        """, (new_paid, new_outstanding, purchase_id))
        conn.commit()
        return RedirectResponse(f"/company-payments/?saved={payment_no}", status_code=303)
    except Exception as exc:
        if conn: conn.rollback()
        return RedirectResponse("/company-payments/?error=Unable%20to%20save%20payment", status_code=303)
    finally:
        if cur: cur.close()
        if conn: conn.close()
