from pathlib import Path
import re

def validate_new_user_password(password: str) -> bool:
    """Return True only for 8+ chars with a letter, digit, special char, and no whitespace."""
    return bool(
        len(password) >= 8
        and re.search(r"[A-Za-z]", password)
        and re.search(r"[0-9]", password)
        and re.search(r"[^A-Za-z0-9\s]", password)
        and not re.search(r"\s", password)
    )
from datetime import date
from uuid import uuid4
import csv
import io

import mysql.connector

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware


# ============================================================
# LOCAL APP IMPORTS
# ============================================================

from .config import SECRET_KEY, APP_HOST, APP_PORT

from .database import (
    ensure_login_database,
    authenticate_user,
    get_connection,
    hash_password,
)


# ============================================================
# COMPANY MASTER
# ============================================================

from .masters.company_master import (
    router as company_router,
    setup_company_master,
)


# ============================================================
# PRODUCT MASTER
# ============================================================

from .masters.product_master import (
    router as product_router,
    setup_product_master,
)


# ============================================================
# SALES PERSON MASTER
# ============================================================

from .masters.sales_person import (
    router as sales_person_router,
)

# COMMISSION SLABS MASTER
from .masters.commission_slabs import (
    router as commission_slabs_router,
    ensure_commission_slabs_table,
)


# ============================================================
# CUSTOMER MASTER
# ============================================================

from .masters.customer import (
    router as customer_router,
    ensure_customer_table,
)


# ============================================================
# PURCHASE TRANSACTION
# ============================================================

from .transaction.purchase import (
    router as purchase_router,
    ensure_purchase_table,
)

from .transaction.company_payment import (
    router as company_payment_router,
    ensure_company_payments_table,
)

# ============================================================
# SALE TRANSACTION
# ============================================================

from .transaction.sale import (
    router as sale_router,
    ensure_sales_table,
    sale_invoice_print,
    sale_invoice_print_compat,
)
from .reports import router as reports_router
from .company_payment_report import router as company_payment_report_router

from .transaction.receipt import (
    router as receipt_router,
    ensure_receipts_table,
    receipt_page,
    collect_money,
    print_money_received,
)



# ============================================================
# BASE PATH
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


# ============================================================
# ROLE-BASED MENU PERMISSIONS
# ============================================================

MENU_ITEMS = {
    "company": "Company Master",
    "product": "Product Master",
    "customer": "Customer Master",
    "sales_person": "Sales Persons",
    "commission_slabs": "Commission Slabs",
    "purchase": "Purchase",
    "company_payments": "Company Payments",
    "company_payment_report": "Company Payment Report",
    "sale": "Sales",
    "sale_invoices": "Sales Invoices",
    "receipts": "Money Received",
    "purchase_report": "Purchase Report",
    "sale_report": "Sale Report",
    "sales_person_report": "Sales Persons Details Report",
    "stock_report": "Stock Report",
    "commission_report": "Agent-wise Commission Report",
    "collection_report": "Agent-wise Collection Report",
    "customer_ledger": "Customer Ledger",
    "create_user": "Create User",
    "user_management": "User Management",
}
MENU_PATHS = [
    ("/company", "company"), ("/product", "product"),
    ("/customer", "customer"), ("/sales-person", "sales_person"),
    ("/commission-slabs", "commission_slabs"), ("/purchase", "purchase"),
    ("/company-payments", "company_payments"),
    ("/reports/company-payment", "company_payment_report"),
    ("/sale/invoices", "sale_invoices"), ("/sale", "sale"),
    ("/receipts", "receipts"), ("/purchase-report", "purchase_report"),
    ("/sale-report", "sale_report"), ("/sales-person-report", "sales_person_report"), ("/stock-report", "stock_report"),
    ("/commission-report", "commission_report"),
    ("/collection-report", "collection_report"),
    ("/customer-ledger", "customer_ledger"),
    ("/create-user", "create_user"), ("/user-management", "user_management"),
]
ROLE_DEFAULTS = {
    "ADMIN": set(MENU_ITEMS),
    "AGENT": {"customer", "sale", "sale_invoices", "receipts", "sale_report", "stock_report", "commission_report", "collection_report", "customer_ledger"},
    "OPERATOR": {"product", "customer", "purchase", "company_payments", "company_payment_report", "sale", "sale_invoices", "receipts"},
    "USER": {"product", "customer", "sale", "sale_invoices"},
}

def ensure_menu_permissions_table():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_menu_permissions (
            user_id INT NOT NULL,
            menu_key VARCHAR(50) NOT NULL,
            PRIMARY KEY (user_id, menu_key),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def get_user_menus(user_id, user_type):
    if str(user_type).upper() == "ADMIN":
        return set(MENU_ITEMS)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT menu_key FROM user_menu_permissions WHERE user_id=%s", (user_id,))
    saved = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    # No saved rows means use role defaults. Saving an empty selection is represented
    # by a separate marker row, so an admin can intentionally remove every menu.
    if not saved:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT menu_key FROM user_menu_permissions WHERE user_id=%s AND menu_key='__custom__'", (user_id,))
        custom = cur.fetchone()
        cur.close()
        conn.close()
        if custom:
            return set()
        return set(ROLE_DEFAULTS.get(str(user_type).upper(), ROLE_DEFAULTS["USER"]))
    return set(saved) - {"__custom__"}

class MenuPermissionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        uid = request.session.get("user_id")
        role = str(request.session.get("user_type", "USER")).upper()
        if uid and role != "ADMIN":
            required = next((key for prefix, key in MENU_PATHS if path == prefix or path.startswith(prefix + "/")), None)
            if required:
                try:
                    allowed = get_user_menus(uid, role)
                except Exception as exc:
                    print("Menu permission check error:", exc)
                    return HTMLResponse("Permission check failed. Please contact administrator.", status_code=500)
                if required not in allowed:
                    return HTMLResponse("<h2>Access denied</h2><p>Your account does not have permission to open this menu. Contact your administrator.</p><p><a href='/dashboard'>Back to dashboard</a></p>", status_code=403)
        return await call_next(request)


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="Mollick Krishi Bhandar Management Portal",
    description="Mollick Krishi Bhandar Management System",
    version="1.0.0",
)


# ============================================================
# SESSION
# ============================================================

# Add permission middleware first; SessionMiddleware is added afterward so the
# session is available to the permission checker.
app.add_middleware(MenuPermissionMiddleware)

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
)


# ============================================================
# STATIC FILES
# ============================================================

app.mount(
    "/static",
    StaticFiles(
        directory=str(STATIC_DIR)
    ),
    name="static",
)


# ============================================================
# JINJA2 TEMPLATES
# ============================================================

def sidebar_context(request: Request):
    uid = request.session.get("user_id")
    role = request.session.get("user_type", "USER")
    try:
        menus = get_user_menus(uid, role) if uid else set()
    except Exception as exc:
        print("Sidebar menu lookup error:", exc)
        menus = set()
    return {"allowed_menus": menus}


templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR),
    context_processors=[sidebar_context],
)


# ============================================================
# ROUTERS
# ============================================================

app.include_router(
    company_router
)

app.include_router(
    product_router
)

app.include_router(
    sales_person_router
)

app.include_router(commission_slabs_router)

app.include_router(
    customer_router
)

app.include_router(
    purchase_router
)

app.include_router(company_payment_router)

# Company Payment Report
app.include_router(company_payment_report_router)

app.include_router(
    sale_router
)

app.include_router(
    reports_router
)

# Stock Report is provided by reports_router: GET /stock-report and GET /stock-report/export.


# Explicit Money Received routes. Keep these at application level so the
# receipt page and print URL are always present in the final FastAPI app.
app.add_api_route(
    "/receipts",
    receipt_page,
    methods=["GET"],
    response_class=HTMLResponse,
    name="money_received",
)
app.add_api_route(
    "/receipts/",
    receipt_page,
    methods=["GET"],
    response_class=HTMLResponse,
    name="money_received_slash",
)
app.add_api_route(
    "/receipts/collect",
    collect_money,
    methods=["POST"],
    name="money_received_collect",
)
app.add_api_route(
    "/receipts/print/{recovery_no}",
    print_money_received,
    methods=["GET"],
    response_class=HTMLResponse,
    name="money_received_print",
)

# Receipt routes are registered explicitly above. Do not include the receipt
# router a second time, because the same paths are already registered.

# Explicit application-level print routes. These mirror the Sale router
# routes so the commercial invoice print URL is always registered in the
# final FastAPI application.
app.add_api_route(
    "/sale/invoices/{invoice_no}/print",
    sale_invoice_print,
    methods=["GET"],
    response_class=HTMLResponse,
    name="sale_invoice_print_direct",
)
app.add_api_route(
    "/sale/print/{invoice_no}",
    sale_invoice_print_compat,
    methods=["GET"],
    response_class=HTMLResponse,
    name="sale_invoice_print_compat_direct",
)


# ============================================================
# APPLICATION STARTUP
# ============================================================

@app.on_event("startup")
def startup():

    try:
        ensure_receipts_table()
        print("Receipts initialization: OK")
    except Exception as e:
        print("Receipts initialization error:", e)

    # --------------------------------------------------------
    # Login database
    # --------------------------------------------------------

    try:

        ensure_login_database()
        ensure_menu_permissions_table()
        ensure_activity_table()
        ensure_td_audit_trail_table()

        print(
            "Login database and menu permissions initialization: OK"
        )

    except Exception as e:

        print(
            "Login database initialization error:",
            e
        )


    # --------------------------------------------------------
    # Company Master
    # --------------------------------------------------------

    try:

        setup_company_master()

        print(
            "Company Master initialization: OK"
        )

    except Exception as e:

        print(
            "Company Master initialization error:",
            e
        )


    # --------------------------------------------------------
    # Product Master
    # --------------------------------------------------------

    try:

        setup_product_master()

        print(
            "Product Master initialization: OK"
        )

    except Exception as e:

        print(
            "Product Master initialization error:",
            e
        )


    # --------------------------------------------------------
    # Commission Slabs Master
    # --------------------------------------------------------
    try:
        ensure_commission_slabs_table()
        print("Commission Slabs Master initialization: OK")
    except Exception as e:
        print("Commission Slabs Master initialization error:", e)

    # --------------------------------------------------------
    # Customer Master
    # --------------------------------------------------------

    try:

        ensure_customer_table()

        print(
            "Customer Master initialization: OK"
        )

    except Exception as e:

        print(
            "Customer Master initialization error:",
            e
        )


    # --------------------------------------------------------
    # Sales Table
    # --------------------------------------------------------

    try:

        ensure_sales_table()

        print(
            "Sales table initialization: OK"
        )

    except Exception as e:

        print(
            "Sales table initialization error:",
            e
        )


    # --------------------------------------------------------
    # Purchase Table
    # --------------------------------------------------------

    try:

        ensure_purchase_table()

        print(
            "Purchase table initialization: OK"
        )

    except Exception as e:

        print(
            "Purchase table initialization error:",
            e
        )

    try:
        ensure_company_payments_table()
        print("Company Payments table initialization: OK")
    except Exception as e:
        print("Company Payments table initialization error:", e)


# ============================================================
# DASHBOARD STATISTICS
# ============================================================

def get_dashboard_stats():

    stats = {
        "companies": None,
        "products": None,
        "purchase_invoices": None,
        "sale_invoices": None,
        "total_purchase": None,
        "total_sale": None,
        "financial_year": "",
        "users": None,
    }


    # Financial year in India runs from 1 April through 31 March.
    today = date.today()
    fy_start_year = today.year if today.month >= 4 else today.year - 1
    fy_start = date(fy_start_year, 4, 1)
    fy_end = date(fy_start_year + 1, 4, 1)
    stats["financial_year"] = f"{fy_start_year}-{str(fy_start_year + 1)[-2:]}"

    # ========================================================
    # USER COUNT
    # ========================================================

    try:

        db = get_connection()

        cur = db.cursor()

        cur.execute(
            """
            SELECT COUNT(*)
            FROM users
            """
        )

        row = cur.fetchone()

        if row:
            stats["users"] = row[0]

        cur.close()
        db.close()

    except Exception as e:

        print(
            "User count error:",
            e
        )


    # ========================================================
    # COMPANY COUNT
    # ========================================================

    try:

        db = get_connection()

        cur = db.cursor()

        cur.execute(
            """
            SELECT COUNT(*)
            FROM mm_company_dtls
            """
        )

        row = cur.fetchone()

        if row:
            stats["companies"] = row[0]

        cur.close()
        db.close()

    except Exception as e:

        print(
            "Company count error:",
            e
        )


    # ========================================================
    # Mollick Krishi Bhandar DATABASE
    # ========================================================

    try:

        db = mysql.connector.connect(

            host="localhost",
            user="root",
            password="",
            database="benfed_fertilizer",
        )

        cur = db.cursor()


        # ----------------------------------------------------
        # Product count
        # ----------------------------------------------------

        try:

            cur.execute(
                """
                SELECT COUNT(*)
                FROM mm_product
                """
            )

            row = cur.fetchone()

            if row:
                stats["products"] = row[0]

        except Exception as e:

            print(
                "Product count error:",
                e
            )




        cur.close()
        db.close()

    except Exception as e:

        print(
            "database error:",
            e
        )


    # ========================================================
    # PURCHASE AND SALES METRICS (stored in python_login DB)
    # ========================================================
    metrics_db = metrics_cur = None
    try:
        metrics_db = mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="python_login",
        )
        metrics_cur = metrics_db.cursor()

        # One row in purchase_master represents one purchase invoice.
        metrics_cur.execute(
            """
            SELECT COUNT(*)
            FROM purchase_master
            WHERE purchase_date >= %s AND purchase_date < %s
            """,
            (fy_start, fy_end),
        )
        row = metrics_cur.fetchone()
        stats["purchase_invoices"] = int((row[0] if row else 0) or 0)

        metrics_cur.execute(
            """
            SELECT COUNT(DISTINCT sale_invoice_no)
            FROM sales
            WHERE sale_date >= %s AND sale_date < %s
              AND sale_invoice_no IS NOT NULL
              AND TRIM(sale_invoice_no) <> ''
            """,
            (fy_start, fy_end),
        )
        row = metrics_cur.fetchone()
        stats["sale_invoices"] = int((row[0] if row else 0) or 0)

        metrics_cur.execute(
            """
            SELECT COALESCE(SUM(COALESCE(net_amount, 0)), 0)
            FROM purchase_master
            WHERE purchase_date >= %s AND purchase_date < %s
            """,
            (fy_start, fy_end),
        )
        row = metrics_cur.fetchone()
        stats["total_purchase"] = float((row[0] if row else 0) or 0)
        print(f"Dashboard FY purchase total ({fy_start} to {fy_end}): {stats['total_purchase']:.2f}")

        # net_amount repeats on every sales line; count each invoice total once.
        metrics_cur.execute(
            """
            SELECT COALESCE(SUM(invoice_total), 0)
            FROM (
                SELECT sale_invoice_no, MAX(COALESCE(net_amount, 0)) AS invoice_total
                FROM sales
                WHERE sale_date >= %s AND sale_date < %s
                  AND sale_invoice_no IS NOT NULL
                  AND TRIM(sale_invoice_no) <> ''
                GROUP BY sale_invoice_no
            ) AS invoice_totals
            """,
            (fy_start, fy_end),
        )
        row = metrics_cur.fetchone()
        stats["total_sale"] = float((row[0] if row else 0) or 0)
        print(f"Dashboard FY sale total ({fy_start} to {fy_end}): {stats['total_sale']:.2f}")

    except Exception as e:
        print("Dashboard purchase/sale metrics SQL ERROR:", repr(e))
        # Keep invoice cards visibly diagnostic instead of falsely showing zero.
        stats["purchase_invoices"] = None
        stats["sale_invoices"] = None
        stats["total_purchase"] = None
        stats["total_sale"] = None
    finally:
        if metrics_cur is not None:
            metrics_cur.close()
        if metrics_db is not None:
            metrics_db.close()

    return stats


# ============================================================
# DASHBOARD: OTHER ACTIVE LOGIN SESSIONS
# ============================================================

def ensure_activity_table():
    """Track signed-in browser sessions; a heartbeat marks them active."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS active_login_sessions (
            session_key VARCHAR(64) NOT NULL PRIMARY KEY,
            user_id INT NOT NULL,
            username VARCHAR(100) NOT NULL,
            user_type VARCHAR(30) NOT NULL DEFAULT 'USER',
            signed_in_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_active_last_seen (last_seen),
            INDEX idx_active_user (user_id)
        )
    """)
    conn.commit()
    cur.close()
    conn.close()



def ensure_td_audit_trail_table():
    """Create the login/logout audit table using the supplied td_audit_trail schema."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS td_audit_trail (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                login_dt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                user_id VARCHAR(55) NOT NULL,
                terminal_name VARCHAR(55) NOT NULL,
                logout DATETIME DEFAULT NULL,
                INDEX idx_td_audit_login_dt (login_dt),
                INDEX idx_td_audit_user_id (user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        conn.commit()
    finally:
        cur.close()
        conn.close()


def record_td_audit_login(request, user):
    """Insert a login row and keep its primary key in the signed session for logout."""
    terminal = request.client.host if request.client else "unknown"
    terminal = str(terminal or "unknown")[:55]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO td_audit_trail (login_dt, user_id, terminal_name, logout) VALUES (NOW(), %s, %s, NULL)",
            (str(user.get("username") or user.get("id") or "unknown")[:55], terminal),
        )
        conn.commit()
        request.session["td_audit_trail_id"] = cur.lastrowid
    finally:
        cur.close()
        conn.close()


def close_td_audit_login(request):
    """Stamp logout before the session is cleared; fallback for older sessions without a row id."""
    audit_id = request.session.get("td_audit_trail_id")
    username = request.session.get("username")
    terminal = request.client.host if request.client else "unknown"
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        if audit_id:
            cur.execute(
                "UPDATE td_audit_trail SET logout=NOW() WHERE id=%s AND logout IS NULL",
                (audit_id,),
            )
        elif username:
            # Compatibility for sessions created before audit tracking was enabled.
            cur.execute(
                "UPDATE td_audit_trail SET logout=NOW() WHERE user_id=%s AND terminal_name=%s AND logout IS NULL ORDER BY login_dt DESC LIMIT 1",
                (str(username)[:55], str(terminal or "unknown")[:55]),
            )
        conn.commit()
    except Exception as exc:
        print("Audit trail logout update error:", exc)
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()


def _audit_trail_rows(user_filter="", date_from="", date_to=""):
    """Read audit rows with optional username and date filters."""
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        sql = """
            SELECT id, login_dt, user_id, terminal_name, logout,
                   TIMESTAMPDIFF(MINUTE, login_dt, COALESCE(logout, NOW())) AS duration_minutes
            FROM td_audit_trail WHERE 1=1
        """
        params = []
        if user_filter:
            sql += " AND user_id LIKE %s"
            params.append("%" + user_filter.strip()[:55] + "%")
        if date_from:
            sql += " AND DATE(login_dt) >= %s"
            params.append(date_from)
        if date_to:
            sql += " AND DATE(login_dt) <= %s"
            params.append(date_to)
        sql += " ORDER BY id DESC LIMIT 1000"
        cur.execute(sql, tuple(params))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def record_login_session(request, user):
    session_key = uuid4().hex
    request.session["activity_session_key"] = session_key
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO active_login_sessions
            (session_key, user_id, username, user_type, signed_in_at, last_seen)
        VALUES (%s, %s, %s, %s, NOW(), NOW())
        ON DUPLICATE KEY UPDATE
            user_id=VALUES(user_id), username=VALUES(username),
            user_type=VALUES(user_type), last_seen=NOW()
    """, (session_key, user["id"], user["username"], user["user_type"]))
    conn.commit()
    cur.close()
    conn.close()


def get_other_active_sessions(current_user_id):
    """Only sessions seen in the last 2 minutes are considered online."""
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT username, user_type, last_seen, signed_in_at
        FROM active_login_sessions
        WHERE user_id <> %s
          AND last_seen >= DATE_SUB(NOW(), INTERVAL 2 MINUTE)
        ORDER BY last_seen DESC
    """, (current_user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def safe_get_other_active_sessions(current_user_id):
    try:
        return get_other_active_sessions(current_user_id)
    except Exception as exc:
        print("Dashboard active-user lookup error:", exc)
        return []


@app.post("/activity/heartbeat")
def activity_heartbeat(request: Request):
    """
    Keep this browser session marked as online.
    Also register sessions that were already logged in before live tracking
    was installed, so users do not have to log out and sign in again.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"ok": False, "error": "Not signed in"}, status_code=401)

    session_key = request.session.get("activity_session_key")
    if not session_key:
        session_key = uuid4().hex
        request.session["activity_session_key"] = session_key

    username = request.session.get("username", "User")
    user_type = request.session.get("user_type", "USER")

    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        # Upsert makes heartbeat self-healing if login-time tracking failed.
        cur.execute("""
            INSERT INTO active_login_sessions
                (session_key, user_id, username, user_type, signed_in_at, last_seen)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
                user_id=VALUES(user_id),
                username=VALUES(username),
                user_type=VALUES(user_type),
                last_seen=NOW()
        """, (session_key, user_id, username, user_type))
        conn.commit()
        return {"ok": True}
    except Exception as exc:
        print("Activity heartbeat error:", exc)
        return JSONResponse({"ok": False, "error": "Activity tracking unavailable"}, status_code=500)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.get("/activity/other-users")
def activity_other_users(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"error": "Not signed in"}, status_code=401)
    try:
        users = get_other_active_sessions(user_id)
        return {"users": [
            {
                "username": row["username"],
                "user_type": row["user_type"],
                "last_seen": row["last_seen"].strftime("%H:%M:%S") if row["last_seen"] else "",
                "signed_in_at": row["signed_in_at"].strftime("%d-%m-%Y %H:%M") if row["signed_in_at"] else "",
            }
            for row in users
        ]}
    except Exception as exc:
        print("Dashboard active-user lookup error:", exc)
        return JSONResponse({"users": [], "error": "Could not load active users"}, status_code=500)



# ============================================================
# ADMIN MONITORING: ACTIVE LOGIN SESSIONS
# ============================================================

def get_admin_active_sessions(current_user_id):
    """Return other users' browser sessions active within the last 2 minutes."""
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT user_id, username, user_type, signed_in_at, last_seen
            FROM active_login_sessions
            WHERE user_id <> %s
              AND last_seen >= DATE_SUB(NOW(), INTERVAL 2 MINUTE)
            ORDER BY last_seen DESC, signed_in_at DESC
        """, (current_user_id,))
        return cur.fetchall()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.get("/admin-monitoring", response_class=HTMLResponse)
def admin_monitoring_page(request: Request):
    redirect = _require_login(request)
    if redirect:
        return redirect
    if not _is_admin(request):
        return HTMLResponse(
            "<h3>Access denied</h3><p>Administrator access is required.</p>",
            status_code=403,
        )

    return templates.TemplateResponse(
        request=request,
        name="admin_monitoring.html",
        context={
            "request": request,
            "username": request.session.get("username", "User"),
            "user_type": request.session.get("user_type", "USER"),
            "allowed_menus": get_user_menus(
                request.session.get("user_id"),
                request.session.get("user_type", "USER"),
            ),
        },
    )


@app.get("/admin-monitoring/active-sessions")
def admin_monitoring_active_sessions(request: Request):
    if not request.session.get("user_id"):
        return JSONResponse({"error": "Not signed in"}, status_code=401)
    if not _is_admin(request):
        return JSONResponse({"error": "Administrator access is required"}, status_code=403)

    try:
        rows = get_admin_active_sessions(request.session.get("user_id"))
        return {
            "users": [
                {
                    "user_id": row["user_id"],
                    "username": row["username"] or "User",
                    "user_type": row["user_type"] or "USER",
                    "signed_in_at": row["signed_in_at"].strftime("%d-%m-%Y %H:%M:%S")
                        if row["signed_in_at"] else "",
                    "last_seen": row["last_seen"].strftime("%d-%m-%Y %H:%M:%S")
                        if row["last_seen"] else "",
                    "status": "Online",
                }
                for row in rows
            ],
            "updated_at": date.today().strftime("%d-%m-%Y"),
        }
    except Exception as exc:
        print("Admin monitoring lookup error:", exc)
        return JSONResponse(
            {"error": "Could not load active sessions"},
            status_code=500,
        )


# ============================================================
# AUDIT TRAIL (ADMIN ONLY)
# ============================================================

@app.get("/audit-trail", response_class=HTMLResponse)
def audit_trail_page(
    request: Request,
    user: str = "",
    date_from: str = "",
    date_to: str = "",
):
    redirect = _require_login(request)
    if redirect:
        return redirect
    if not _is_admin(request):
        return HTMLResponse("<h2>Access denied</h2><p>Administrator access is required.</p><p><a href='/dashboard'>Back to dashboard</a></p>", status_code=403)
    try:
        rows = _audit_trail_rows(user, date_from, date_to)
        error = None
    except Exception as exc:
        print("Audit trail page error:", exc)
        rows, error = [], "Could not load audit trail. Check the database connection and td_audit_trail table."
    return templates.TemplateResponse(
        request=request,
        name="audit_trail.html",
        context={
            "request": request,
            "username": request.session.get("username", "Admin"),
            "user_type": request.session.get("user_type", "USER"),
            "allowed_menus": get_user_menus(request.session.get("user_id"), request.session.get("user_type", "USER")),
            "rows": rows,
            "user_filter": user,
            "date_from": date_from,
            "date_to": date_to,
            "error": error,
        },
    )


@app.get("/audit-trail/export")
def audit_trail_export(
    request: Request,
    user: str = "",
    date_from: str = "",
    date_to: str = "",
):
    if not request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    if not _is_admin(request):
        return HTMLResponse("Administrator access is required.", status_code=403)
    try:
        rows = _audit_trail_rows(user, date_from, date_to)
    except Exception as exc:
        print("Audit trail export error:", exc)
        return HTMLResponse("Could not export audit trail. Check the database connection.", status_code=500)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Login Date/Time", "User ID", "Terminal Name / IP", "Logout Date/Time", "Duration Minutes"])
    for row in rows:
        writer.writerow([
            row.get("id"), row.get("login_dt"), row.get("user_id"), row.get("terminal_name"),
            row.get("logout") or "Still open / not recorded", row.get("duration_minutes"),
        ])
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=td_audit_trail.csv"},
    )


# ============================================================
# LOGIN PAGE
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse
)
def login_page(
    request: Request
):

    if request.session.get("user_id"):

        return RedirectResponse(
            url="/dashboard",
            status_code=303
        )


    return templates.TemplateResponse(

        request=request,

        name="login.html",

        context={
            "request": request,
            "error": None,
            "username": "",
        },
    )


# ============================================================
# LOGIN SUBMIT
# ============================================================

@app.post(
    "/login",
    response_class=HTMLResponse
)
def login(

    request: Request,

    username: str = Form(""),

    password: str = Form(""),
):

    username = username.strip()

    error = None


    if not username:

        error = "Please enter User ID."


    elif not password:

        error = "Please enter Password."


    else:

        try:

            user = authenticate_user(
                username,
                password
            )

        except Exception as e:

            print(
                "Authentication error:",
                e
            )

            user = None

            error = (
                "Unable to connect to the database."
            )


        if user:

            request.session["user_id"] = (
                user["id"]
            )

            request.session["username"] = (
                user["username"]
            )

            request.session["user_type"] = (
                user["user_type"]
            )

            try:
                record_login_session(request, user)
            except Exception as e:
                print("Active session tracking error:", e)

            try:
                record_td_audit_login(request, user)
            except Exception as e:
                print("Audit trail login insert error:", e)

            return RedirectResponse(
                url="/dashboard",
                status_code=303
            )


        if error is None:

            error = (
                "Invalid User ID or Password."
            )


    return templates.TemplateResponse(

        request=request,

        name="login.html",

        context={
            "request": request,
            "error": error,
            "username": username,
        },

        status_code=401,
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.get(
    "/dashboard",
    response_class=HTMLResponse
)
def dashboard(
    request: Request
):

    if not request.session.get("user_id"):

        return RedirectResponse(
            url="/",
            status_code=303
        )


    username = request.session.get(
        "username",
        "User"
    )

    user_type = request.session.get(
        "user_type",
        "USER"
    )


    stats = get_dashboard_stats()


    return templates.TemplateResponse(

        request=request,

        name="dashboard.html",

        context={

            "request": request,

            "username": username,

            "user_type": user_type,
            "allowed_menus": get_user_menus(request.session.get("user_id"), user_type),

            "stats": stats,
            "other_active_users": safe_get_other_active_sessions(request.session.get("user_id")) if request.session.get("activity_session_key") else [],
        },
    )


# ============================================================
# USER MANAGEMENT / PROFILE
# ============================================================

def _require_login(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    return None


def _is_admin(request: Request):
    return str(request.session.get("user_type", "USER")).upper() == "ADMIN"


@app.get("/create-user", response_class=HTMLResponse)
def create_user_page(request: Request):
    redirect = _require_login(request)
    if redirect:
        return redirect
    if not _is_admin(request):
        return HTMLResponse("<h3>Access denied</h3><p>Administrator access is required.</p>", status_code=403)
    return templates.TemplateResponse(
        request=request,
        name="create_user.html",
        context={"request": request, "username": request.session.get("username", "User"),
                 "user_type": request.session.get("user_type", "USER"), "error": None, "success": None},
    )


@app.post("/create-user", response_class=HTMLResponse)
def create_user(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    user_type: str = Form("USER"),
):
    redirect = _require_login(request)
    if redirect:
        return redirect
    if not _is_admin(request):
        return HTMLResponse("<h3>Access denied</h3><p>Administrator access is required.</p>", status_code=403)
    username = username.strip()
    user_type = user_type.strip().upper() or "USER"
    error = None
    success = None
    if not username or not password:
        error = "Username and password are required."
    elif not validate_new_user_password(password):
        error = "Invalid password. Use at least 8 characters with at least one letter, one number, and one special character (@, #, $, !, etc.). Do not include spaces."
    elif user_type not in ("ADMIN", "AGENT", "OPERATOR", "USER"):
        error = "Invalid user type."
    else:
        conn = cur = None
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO users (username,password,user_type) VALUES (%s,%s,%s)",
                        (username, hash_password(password), user_type))
            conn.commit()
            success = f"User '{username}' created successfully."
        except mysql.connector.Error as e:
            if conn:
                conn.rollback()
            error = "Username already exists." if getattr(e, "errno", None) == 1062 else str(e)
        finally:
            if cur: cur.close()
            if conn: conn.close()
    return templates.TemplateResponse(
        request=request, name="create_user.html",
        context={"request": request, "username": request.session.get("username", "User"),
                 "user_type": request.session.get("user_type", "USER"), "error": error, "success": success},
        status_code=400 if error else 200,
    )


@app.get("/user-management", response_class=HTMLResponse)
def user_management(request: Request):
    redirect = _require_login(request)
    if redirect:
        return redirect
    if not _is_admin(request):
        return HTMLResponse("<h3>Access denied</h3><p>Administrator access is required.</p>", status_code=403)
    users = []
    conn = cur = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, username, user_type FROM users ORDER BY id")
        users = cur.fetchall()
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return templates.TemplateResponse(
        request=request, name="user_management.html",
        context={"request": request, "username": request.session.get("username", "User"),
                 "user_type": request.session.get("user_type", "USER"), "users": users},
    )


@app.get("/user-management/permissions/{user_id}", response_class=HTMLResponse)
def edit_user_permissions(request: Request, user_id: int):
    redirect = _require_login(request)
    if redirect:
        return redirect
    if not _is_admin(request):
        return HTMLResponse("Access denied", status_code=403)
    conn = cur = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, username, user_type FROM users WHERE id=%s", (user_id,))
        target = cur.fetchone()
        if not target:
            return HTMLResponse("User not found", status_code=404)
        cur.execute("SELECT menu_key FROM user_menu_permissions WHERE user_id=%s", (user_id,))
        saved = {r["menu_key"] for r in cur.fetchall()}
        if "__custom__" in saved:
            selected = saved - {"__custom__"}
        elif saved:
            selected = saved
        else:
            selected = set(ROLE_DEFAULTS.get(str(target["user_type"]).upper(), ROLE_DEFAULTS["USER"]))
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return templates.TemplateResponse(
        request=request, name="user_permissions.html",
        context={"request": request, "username": request.session.get("username", "User"),
                 "user_type": request.session.get("user_type", "ADMIN"), "target_user": target,
                 "menu_items": MENU_ITEMS, "selected": selected,
                 "success": "Permissions saved successfully." if request.query_params.get("saved") else None, "error": None},
    )


@app.post("/user-management/permissions/{user_id}", response_class=HTMLResponse)
async def save_user_permissions(request: Request, user_id: int):
    redirect = _require_login(request)
    if redirect:
        return redirect
    if not _is_admin(request):
        return HTMLResponse("Access denied", status_code=403)
    form = await request.form()
    selected = {key for key in MENU_ITEMS if form.get(key) == "on"}
    conn = cur = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, username, user_type FROM users WHERE id=%s", (user_id,))
        target = cur.fetchone()
        if not target:
            return HTMLResponse("User not found", status_code=404)
        cur.execute("DELETE FROM user_menu_permissions WHERE user_id=%s", (user_id,))
        keys = list(selected) or ["__custom__"]
        cur.executemany("INSERT INTO user_menu_permissions (user_id, menu_key) VALUES (%s,%s)",
                        [(user_id, key) for key in keys])
        conn.commit()
    except Exception:
        if conn: conn.rollback()
        raise
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return RedirectResponse(url=f"/user-management/permissions/{user_id}?saved=1", status_code=303)


@app.post("/user-management/delete/{user_id}")
def delete_user(request: Request, user_id: int):
    redirect = _require_login(request)
    if redirect:
        return redirect
    if not _is_admin(request):
        return HTMLResponse("Access denied", status_code=403)
    if int(user_id) == int(request.session.get("user_id")):
        return RedirectResponse(url="/user-management?error=You%20cannot%20delete%20your%20own%20account", status_code=303)
    conn = cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
        conn.commit()
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return RedirectResponse(url="/user-management", status_code=303)


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    redirect = _require_login(request)
    if redirect:
        return redirect
    conn = cur = None
    user = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, username, user_type FROM users WHERE id=%s LIMIT 1", (request.session.get("user_id"),))
        user = cur.fetchone()
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return templates.TemplateResponse(
        request=request, name="profile.html",
        context={"request": request, "username": request.session.get("username", "User"),
                 "user_type": request.session.get("user_type", "USER"), "user": user,
                 "error": None, "success": None},
    )


@app.post("/profile", response_class=HTMLResponse)
def profile_update(request: Request, password: str = Form("")):
    redirect = _require_login(request)
    if redirect:
        return redirect
    error = None
    success = None
    if not password:
        error = "Please enter a new password."
    else:
        conn = cur = None
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("UPDATE users SET password=%s WHERE id=%s", (hash_password(password), request.session.get("user_id")))
            conn.commit()
            success = "Password updated successfully."
        finally:
            if cur: cur.close()
            if conn: conn.close()
    conn = cur = None
    user = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, username, user_type FROM users WHERE id=%s LIMIT 1", (request.session.get("user_id"),))
        user = cur.fetchone()
    finally:
        if cur: cur.close()
        if conn: conn.close()
    return templates.TemplateResponse(
        request=request, name="profile.html",
        context={"request": request, "username": request.session.get("username", "User"),
                 "user_type": request.session.get("user_type", "USER"), "user": user,
                 "error": error, "success": success},
    )


# ============================================================
# LOGOUT
# ============================================================

@app.get("/logout")
def logout(
    request: Request
):

    # Update the audit row while the signed-in user and audit row ID are still in session.
    close_td_audit_login(request)

    session_key = request.session.get("activity_session_key")
    if session_key:
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM active_login_sessions WHERE session_key=%s", (session_key,))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print("Active session cleanup error:", e)

    request.session.clear()

    return RedirectResponse(
        url="/",
        status_code=303
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "ok",
        "application": "Mollick Krishi Bhandar",
    }


# ============================================================
# HOME
# ============================================================

@app.get(
    "/home",
    include_in_schema=False
)
def home(
    request: Request
):

    if request.session.get("user_id"):

        return RedirectResponse(
            url="/dashboard",
            status_code=303
        )

    return RedirectResponse(
        url="/",
        status_code=303
    )


# ============================================================
# LOCAL RUN
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(

        "app.main:app",

        host=APP_HOST,

        port=APP_PORT,

        reload=False,
    )