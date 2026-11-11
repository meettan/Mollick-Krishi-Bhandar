from pathlib import Path
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import List

import mysql.connector
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from ..sidebar_context import sidebar_context

# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR), context_processors=[sidebar_context])

# ============================================================
# ROUTER
# ============================================================

router = APIRouter(
    prefix="/purchase",
    tags=["Purchase"],
)

# ============================================================
# DATABASES
# ============================================================

LOGIN_DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "python_login",
}

FERTILIZER_DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "benfed_fertilizer",
}


def get_login_connection():
    return mysql.connector.connect(**LOGIN_DB_CONFIG)


def get_fertilizer_connection():
    return mysql.connector.connect(**FERTILIZER_DB_CONFIG)


# ============================================================
# HELPERS
# ============================================================

def safe_int(value, default=0):
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_decimal(value, default=Decimal("0.00")):
    try:
        if value is None or str(value).strip() == "":
            return default
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return default


def safe_date(value, default=None):
    if value is None or str(value).strip() == "":
        return default

    if isinstance(value, date):
        return value

    try:
        return datetime.strptime(
            str(value).strip(),
            "%Y-%m-%d",
        ).date()
    except (ValueError, TypeError):
        return default


def decimal_to_float(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def calculate_line(qty, unit_price, discount, gst_rate):
    qty = max(safe_decimal(qty), Decimal("0"))
    unit_price = max(safe_decimal(unit_price), Decimal("0"))
    discount = max(safe_decimal(discount), Decimal("0"))
    gst_rate = max(safe_decimal(gst_rate), Decimal("0"))

    gross = qty * unit_price
    taxable = max(gross - discount, Decimal("0"))
    gst = taxable * gst_rate / Decimal("100")
    line_total = taxable + gst

    return {
        "gross": gross.quantize(Decimal("0.01")),
        "discount": discount.quantize(Decimal("0.01")),
        "taxable": taxable.quantize(Decimal("0.01")),
        "gst": gst.quantize(Decimal("0.01")),
        "line_total": line_total.quantize(Decimal("0.01")),
    }


# ============================================================
# MASTER / DETAIL TABLE INITIALIZATION
#
# IMPORTANT:
# This function DOES NOT create/use the old `purchases` table.
# New purchase data is stored ONLY in:
#   purchase_master
#   purchase_details
# ============================================================

def ensure_purchase_table():
    conn = None
    cursor = None

    try:
        conn = get_login_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS purchase_master (
                id INT AUTO_INCREMENT PRIMARY KEY,
                purchase_no VARCHAR(100) NOT NULL,
                ro_no VARCHAR(100) DEFAULT NULL,
                company_id INT NOT NULL,
                purchase_date DATE NOT NULL,
                invoice_no VARCHAR(100) DEFAULT NULL,
                invoice_date DATE DEFAULT NULL,
                credit_period INT DEFAULT 0,
                due_date DATE DEFAULT NULL,
                gross_amount DECIMAL(18,2) DEFAULT 0.00,
                discount_amount DECIMAL(18,2) DEFAULT 0.00,
                taxable_amount DECIMAL(18,2) DEFAULT 0.00,
                gst_amount DECIMAL(18,2) DEFAULT 0.00,
                net_amount DECIMAL(18,2) DEFAULT 0.00,
                paid_amount DECIMAL(18,2) DEFAULT 0.00,
                outstanding_amount DECIMAL(18,2) DEFAULT 0.00,
                status VARCHAR(20) DEFAULT 'DRAFT',
                remarks VARCHAR(500) DEFAULT NULL,
                created_by INT DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                modified_by INT DEFAULT NULL,
                modified_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_pm_purchase_no (purchase_no),
                KEY idx_pm_ro_no (ro_no),
                KEY idx_pm_company (company_id),
                KEY idx_pm_date (purchase_date),
                KEY idx_pm_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS purchase_details (
                id INT AUTO_INCREMENT PRIMARY KEY,
                purchase_id INT NOT NULL,
                product_id INT NOT NULL,
                batch_id INT DEFAULT NULL,
                qty DECIMAL(18,3) DEFAULT 0.000,
                unit_price DECIMAL(18,2) DEFAULT 0.00,
                gross_amount DECIMAL(18,2) DEFAULT 0.00,
                discount DECIMAL(18,2) DEFAULT 0.00,
                taxable_amount DECIMAL(18,2) DEFAULT 0.00,
                gst_rate DECIMAL(8,2) DEFAULT 0.00,
                gst_amount DECIMAL(18,2) DEFAULT 0.00,
                line_total DECIMAL(18,2) DEFAULT 0.00,
                remarks VARCHAR(500) DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                modified_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_pd_purchase (purchase_id),
                KEY idx_pd_product (product_id),
                KEY idx_pd_batch (batch_id),
                CONSTRAINT fk_pd_purchase
                    FOREIGN KEY (purchase_id)
                    REFERENCES purchase_master(id)
                    ON DELETE CASCADE
                    ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        conn.commit()
        print("PURCHASE MASTER/DETAIL TABLES READY")

    except Exception:
        if conn:
            conn.rollback()
        raise

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ============================================================
# COMPANY / PRODUCT LOOKUPS
# ============================================================

def get_companies():
    rows = []
    conn = cursor = None

    try:
        conn = get_login_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COMP_ID, COMP_NAME
            FROM mm_company_dtls
            ORDER BY COMP_NAME
        """)

        for company_id, company_name in cursor.fetchall():
            rows.append({
                "id": company_id,
                "name": company_name or "",
            })

    except Exception as e:
        print("COMPANY LIST ERROR:", e)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return rows


def get_products_by_company(company_id):
    rows = []
    company_id = safe_int(company_id)

    if company_id <= 0:
        return rows

    conn = cursor = None

    try:
        conn = get_fertilizer_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT PROD_ID AS id, PROD_DESC AS name
            FROM mm_product
            WHERE COMPANY = %s
            ORDER BY PROD_DESC
        """, (company_id,))

        for product_id, product_name in cursor.fetchall():
            rows.append({
                "id": product_id,
                "name": product_name or "",
            })

    except Exception as e:
        print("PRODUCT LIST ERROR:", e)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return rows


# ============================================================
# PURCHASE LIST
# ============================================================

def get_purchase_list():
    rows = []
    conn = cursor = None

    try:
        conn = get_login_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                pm.id,
                pm.purchase_no,
                pm.ro_no,
                pm.company_id,
                COALESCE(c.COMP_NAME, ''),
                pm.purchase_date,
                pm.invoice_no,
                pm.invoice_date,
                pm.gross_amount,
                pm.discount_amount,
                pm.taxable_amount,
                pm.gst_amount,
                pm.net_amount,
                pm.paid_amount,
                pm.outstanding_amount,
                pm.credit_period,
                pm.due_date,
                pm.status,
                COUNT(pd.id) AS product_count,
                COALESCE(
                    GROUP_CONCAT(
                        DISTINCT COALESCE(pr.PROD_DESC, '')
                        ORDER BY pd.id SEPARATOR ', '
                    ),
                    ''
                ) AS product_names
            FROM purchase_master pm
            LEFT JOIN mm_company_dtls c
                ON c.COMP_ID = pm.company_id
            LEFT JOIN purchase_details pd
                ON pd.purchase_id = pm.id
            LEFT JOIN benfed_fertilizer.mm_product pr
                ON pr.PROD_ID = pd.product_id
            GROUP BY
                pm.id,
                pm.purchase_no,
                pm.ro_no,
                pm.company_id,
                c.COMP_NAME,
                pm.purchase_date,
                pm.invoice_no,
                pm.invoice_date,
                pm.gross_amount,
                pm.discount_amount,
                pm.taxable_amount,
                pm.gst_amount,
                pm.net_amount,
                pm.paid_amount,
                pm.outstanding_amount,
                pm.credit_period,
                pm.due_date,
                pm.status
            ORDER BY pm.purchase_date DESC, pm.id DESC
        """)

        for row in cursor.fetchall():
            rows.append({
                "id": row[0],
                "purchase_no": row[1] or "",
                "ro_no": row[2] or "",
                "company_id": row[3] or 0,
                "company_name": row[4] or "",
                "purchase_date": row[5],
                "invoice_no": row[6] or "",
                "invoice_date": row[7],
                "gross_amount": decimal_to_float(row[8]),
                "discount_amount": decimal_to_float(row[9]),
                "taxable_amount": decimal_to_float(row[10]),
                "gst_amount": decimal_to_float(row[11]),
                "net_amount": decimal_to_float(row[12]),
                "paid_amount": decimal_to_float(row[13]),
                "outstanding_amount": decimal_to_float(row[14]),
                "credit_period": row[15] or 0,
                "due_date": row[16],
                "status": row[17] or "DRAFT",
                "product_count": row[18] or 0,
                "product_names": row[19] or "",
            })

    except Exception as e:
        print("PURCHASE LIST ERROR:", e)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return rows


# ============================================================
# PURCHASE BY ID
# ============================================================

def get_purchase_by_id(purchase_id):
    purchase_id = safe_int(purchase_id)

    if purchase_id <= 0:
        return None

    conn = cursor = None

    try:
        conn = get_login_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                purchase_no,
                ro_no,
                company_id,
                purchase_date,
                invoice_no,
                invoice_date,
                credit_period,
                due_date,
                gross_amount,
                discount_amount,
                taxable_amount,
                gst_amount,
                net_amount,
                paid_amount,
                outstanding_amount,
                status,
                remarks
            FROM purchase_master
            WHERE id = %s
            LIMIT 1
        """, (purchase_id,))

        purchase = cursor.fetchone()

        if not purchase:
            return None

        cursor.execute("""
            SELECT
                id,
                purchase_id,
                product_id,
                batch_id,
                qty,
                unit_price,
                gross_amount,
                discount,
                taxable_amount,
                gst_rate,
                gst_amount,
                line_total,
                remarks
            FROM purchase_details
            WHERE purchase_id = %s
            ORDER BY id
        """, (purchase_id,))

        purchase["details"] = cursor.fetchall()

        for key in (
            "gross_amount",
            "discount_amount",
            "taxable_amount",
            "gst_amount",
            "net_amount",
            "paid_amount",
            "outstanding_amount",
        ):
            purchase[key] = decimal_to_float(purchase.get(key))

        for detail in purchase["details"]:
            for key in (
                "qty",
                "unit_price",
                "gross_amount",
                "discount",
                "taxable_amount",
                "gst_rate",
                "gst_amount",
                "line_total",
            ):
                detail[key] = decimal_to_float(detail.get(key))

        return purchase

    except Exception as e:
        print("GET PURCHASE ERROR:", e)
        return None

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ============================================================
# COMMON PAGE CONTEXT
# ============================================================

def purchase_page_context(purchase=None, edit_mode=False):
    return {
        "companies": get_companies(),
        "purchases": get_purchase_list(),
        "edit_mode": edit_mode,
        "purchase": purchase,
    }


# ============================================================
# LIST
# ============================================================

@router.get("")
@router.get("/")
async def purchase_list(request: Request):
    try:
        ensure_purchase_table()

        context = purchase_page_context()
        context["request"] = request

        return templates.TemplateResponse(
            request=request,
            name="purchase.html",
            context=context,
        )

    except Exception as e:
        print("PURCHASE LIST PAGE ERROR:", e)

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Purchase page could not be loaded.",
                "error": str(e),
            },
        )


# ============================================================
# ADD
# ============================================================

@router.get("/add")
async def purchase_add(request: Request):
    try:
        ensure_purchase_table()

        context = purchase_page_context()
        context["request"] = request

        return templates.TemplateResponse(
            request=request,
            name="purchase.html",
            context=context,
        )

    except Exception as e:
        print("PURCHASE ADD PAGE ERROR:", e)

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Purchase add page could not be loaded.",
                "error": str(e),
            },
        )


# ============================================================
# EDIT
# ============================================================

@router.get("/edit/{purchase_id}")
async def purchase_edit(request: Request, purchase_id: int):
    try:
        ensure_purchase_table()

        purchase = get_purchase_by_id(purchase_id)

        if not purchase:
            return RedirectResponse(
                "/purchase/",
                status_code=303,
            )

        context = purchase_page_context(
            purchase=purchase,
            edit_mode=True,
        )
        context["request"] = request

        return templates.TemplateResponse(
            request=request,
            name="purchase.html",
            context=context,
        )

    except Exception as e:
        print("PURCHASE EDIT ERROR:", e)

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Purchase edit page could not be loaded.",
                "error": str(e),
            },
        )


# ============================================================
# PRODUCT API
# ============================================================

@router.get("/api/products")
async def purchase_products_api(company_id: int = 0):
    try:
        return {
            "success": True,
            "products": get_products_by_company(company_id),
        }

    except Exception as e:
        print("PURCHASE PRODUCT API ERROR:", e)

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "products": [],
                "message": str(e),
            },
        )


# ============================================================
# SAVE
#
# ONE purchase_master row
# MANY purchase_details rows
#
# NO INSERT INTO purchases
# ============================================================

@router.post("/save")
async def purchase_save(
    request: Request,
    purchase_id: int = Form(0),
    purchase_no: str = Form(""),
    company_id: int = Form(0),
    purchase_date: str = Form(""),
    invoice_no: str = Form(""),
    invoice_date: str = Form(""),
    credit_period: int = Form(0),
    due_date: str = Form(""),
    paid_amount: str = Form("0"),
    status: str = Form("DRAFT"),
    remarks: str = Form(""),
    product_id: List[int] = Form([]),
    batch_id: List[str] = Form([]),
    qty: List[str] = Form([]),
    unit_price: List[str] = Form([]),
    discount: List[str] = Form([]),
    gst_rate: List[str] = Form([]),
):
    conn = cursor = None

    try:
        ensure_purchase_table()

        purchase_id = safe_int(purchase_id)
        purchase_no = (purchase_no or "").strip()
        company_id = safe_int(company_id)

        purchase_date_obj = safe_date(
            purchase_date,
            date.today(),
        )

        invoice_date_obj = safe_date(invoice_date)
        due_date_obj = safe_date(due_date)

        credit_period = max(
            safe_int(credit_period),
            0,
        )

        paid = max(
            safe_decimal(paid_amount),
            Decimal("0"),
        )

        status = (
            status or "DRAFT"
        ).strip().upper()

        allowed_status = {
            "DRAFT",
            "POSTED",
            "PAID",
            "PARTIAL",
            "CANCELLED",
        }

        if status not in allowed_status:
            status = "DRAFT"

        if not purchase_no:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Purchase No / RO No is required.",
                },
            )

        if company_id <= 0:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Company / Vendor is required.",
                },
            )

        if not product_id:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "At least one product is required.",
                },
            )

        if due_date_obj is None:
            due_date_obj = (
                purchase_date_obj
                + timedelta(days=credit_period)
            )

        # ----------------------------------------------------
        # BUILD DETAIL LINES
        # ----------------------------------------------------

        lines = []

        gross_total = Decimal("0")
        discount_total = Decimal("0")
        taxable_total = Decimal("0")
        gst_total = Decimal("0")
        net_total = Decimal("0")

        for i, pid_value in enumerate(product_id):
            pid = safe_int(pid_value)

            if pid <= 0:
                continue

            batch_value = (
                batch_id[i]
                if i < len(batch_id)
                else ""
            )

            qty_value = (
                qty[i]
                if i < len(qty)
                else "0"
            )

            price_value = (
                unit_price[i]
                if i < len(unit_price)
                else "0"
            )

            discount_value = (
                discount[i]
                if i < len(discount)
                else "0"
            )

            gst_rate_value = (
                gst_rate[i]
                if i < len(gst_rate)
                else "0"
            )

            batch = safe_int(
                batch_value,
                0,
            )

            q = max(
                safe_decimal(qty_value),
                Decimal("0"),
            )

            up = max(
                safe_decimal(price_value),
                Decimal("0"),
            )

            disc = max(
                safe_decimal(discount_value),
                Decimal("0"),
            )

            gst_rate_decimal = max(
                safe_decimal(gst_rate_value),
                Decimal("0"),
            )

            if q <= 0:
                continue

            calc = calculate_line(
                q,
                up,
                disc,
                gst_rate_decimal,
            )

            lines.append({
                "product_id": pid,
                "batch_id": batch if batch > 0 else None,
                "qty": q,
                "unit_price": up,
                "gross": calc["gross"],
                "discount": calc["discount"],
                "taxable": calc["taxable"],
                "gst_rate": gst_rate_decimal,
                "gst": calc["gst"],
                "line_total": calc["line_total"],
            })

            gross_total += calc["gross"]
            discount_total += calc["discount"]
            taxable_total += calc["taxable"]
            gst_total += calc["gst"]
            net_total += calc["line_total"]

        if not lines:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "At least one valid product with quantity greater than zero is required.",
                },
            )

        outstanding = max(
            net_total - paid,
            Decimal("0"),
        )

        # ----------------------------------------------------
        # DATABASE TRANSACTION
        # ----------------------------------------------------

        conn = get_login_connection()
        cursor = conn.cursor()

        if purchase_id > 0:
            # Confirm master exists.
            cursor.execute(
                "SELECT id FROM purchase_master WHERE id = %s",
                (purchase_id,),
            )

            if not cursor.fetchone():
                purchase_id = 0

        if purchase_id > 0:
            cursor.execute("""
                UPDATE purchase_master
                SET
                    purchase_no = %s,
                    ro_no = %s,
                    company_id = %s,
                    purchase_date = %s,
                    invoice_no = %s,
                    invoice_date = %s,
                    credit_period = %s,
                    due_date = %s,
                    gross_amount = %s,
                    discount_amount = %s,
                    taxable_amount = %s,
                    gst_amount = %s,
                    net_amount = %s,
                    paid_amount = %s,
                    outstanding_amount = %s,
                    status = %s,
                    remarks = %s
                WHERE id = %s
            """, (
                purchase_no,
                purchase_no,
                company_id,
                purchase_date_obj,
                invoice_no.strip() or None,
                invoice_date_obj,
                credit_period,
                due_date_obj,
                gross_total,
                discount_total,
                taxable_total,
                gst_total,
                net_total,
                paid,
                outstanding,
                status,
                remarks.strip() or None,
                purchase_id,
            ))

            # Delete old detail rows; FK cascade is not needed here.
            cursor.execute(
                "DELETE FROM purchase_details WHERE purchase_id = %s",
                (purchase_id,),
            )

            master_id = purchase_id

        else:
            cursor.execute("""
                INSERT INTO purchase_master (
                    purchase_no,
                    ro_no,
                    company_id,
                    purchase_date,
                    invoice_no,
                    invoice_date,
                    credit_period,
                    due_date,
                    gross_amount,
                    discount_amount,
                    taxable_amount,
                    gst_amount,
                    net_amount,
                    paid_amount,
                    outstanding_amount,
                    status,
                    remarks
                )
                VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s
                )
            """, (
                purchase_no,
                purchase_no,
                company_id,
                purchase_date_obj,
                invoice_no.strip() or None,
                invoice_date_obj,
                credit_period,
                due_date_obj,
                gross_total,
                discount_total,
                taxable_total,
                gst_total,
                net_total,
                paid,
                outstanding,
                status,
                remarks.strip() or None,
            ))

            master_id = cursor.lastrowid

        # ----------------------------------------------------
        # INSERT MULTIPLE DETAIL ROWS
        # ----------------------------------------------------

        for line in lines:
            cursor.execute("""
                INSERT INTO purchase_details (
                    purchase_id,
                    product_id,
                    batch_id,
                    qty,
                    unit_price,
                    gross_amount,
                    discount,
                    taxable_amount,
                    gst_rate,
                    gst_amount,
                    line_total
                )
                VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
            """, (
                master_id,
                line["product_id"],
                line["batch_id"],
                line["qty"],
                line["unit_price"],
                line["gross"],
                line["discount"],
                line["taxable"],
                line["gst_rate"],
                line["gst"],
                line["line_total"],
            ))

        conn.commit()

        print(
            "PURCHASE MASTER SAVED:",
            master_id,
            "DETAIL COUNT:",
            len(lines),
        )

        return RedirectResponse(
            "/purchase/",
            status_code=303,
        )

    except Exception as e:
        if conn:
            conn.rollback()

        print("PURCHASE SAVE ERROR:", e)

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Purchase could not be saved.",
                "error": str(e),
            },
        )

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


# ============================================================
# DELETE
# ============================================================

@router.get("/delete/{purchase_id}")
async def purchase_delete(
    request: Request,
    purchase_id: int,
):
    conn = cursor = None

    try:
        purchase_id = safe_int(purchase_id)

        if purchase_id <= 0:
            return RedirectResponse(
                "/purchase/",
                status_code=303,
            )

        conn = get_login_connection()
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM purchase_master WHERE id = %s",
            (purchase_id,),
        )

        conn.commit()

        return RedirectResponse(
            "/purchase/",
            status_code=303,
        )

    except Exception as e:
        if conn:
            conn.rollback()

        print("PURCHASE DELETE ERROR:", e)

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Purchase could not be deleted.",
                "error": str(e),
            },
        )

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()
