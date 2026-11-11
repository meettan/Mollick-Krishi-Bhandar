from pathlib import Path
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import mysql.connector
from mysql.connector import Error

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates


# ============================================================
# PROJECT PATH
# ============================================================

# purchase.py:
# C:\python\benfed_fastapi_login_screen\benfed_fastapi_login\
# app\transaction\purchase.py
#
# parents[0] = transaction
# parents[1] = app
# parents[2] = benfed_fastapi_login
#
BASE_DIR = Path(__file__).resolve().parents[2]


# ============================================================
# TEMPLATE CONFIGURATION
# ============================================================

# FINAL TEMPLATE LOCATION:
#
# C:\python\benfed_fastapi_login_screen\benfed_fastapi_login\
# templates\purchase.html
#
TEMPLATE_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(
    directory=str(TEMPLATE_DIR)
)


# ============================================================
# ROUTER
# ============================================================

router = APIRouter(
    prefix="/purchase",
    tags=["Purchase"]
)


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

# Login / Company database
LOGIN_DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "python_login",
}


# Fertilizer / Product database
FERTILIZER_DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "benfed_fertilizer",
}


# ============================================================
# DATABASE CONNECTIONS
# ============================================================

def get_login_connection():
    return mysql.connector.connect(
        **LOGIN_DB_CONFIG
    )


def get_fertilizer_connection():
    return mysql.connector.connect(
        **FERTILIZER_DB_CONFIG
    )


# ============================================================
# SAFE HELPERS
# ============================================================

def safe_int(value, default=0):

    try:

        if value is None:
            return default

        value = str(value).strip()

        if value == "":
            return default

        return int(value)

    except (ValueError, TypeError):

        return default


def safe_decimal(
    value,
    default=Decimal("0.00")
):

    try:

        if value is None:
            return default

        if isinstance(value, Decimal):
            return value

        value = str(value).strip()

        if value == "":
            return default

        return Decimal(value)

    except (
        InvalidOperation,
        ValueError,
        TypeError
    ):

        return default


def safe_date(
    value,
    default=None
):

    if value is None:
        return default

    if isinstance(value, date):
        return value

    try:

        value = str(value).strip()

        if not value:
            return default

        return datetime.strptime(
            value,
            "%Y-%m-%d"
        ).date()

    except (
        ValueError,
        TypeError
    ):

        return default


def decimal_to_float(value):

    if value is None:
        return 0

    try:
        return float(value)

    except Exception:
        return 0


# ============================================================
# PURCHASE CALCULATION
# ============================================================

def calculate_purchase_values(
    qty,
    unit_price,
    discount,
    gst_rate,
    paid_amount
):

    qty = safe_decimal(qty)

    unit_price = safe_decimal(unit_price)

    discount = safe_decimal(discount)

    gst_rate = safe_decimal(gst_rate)

    paid_amount = safe_decimal(paid_amount)


    # Gross Amount
    gross_amount = (
        qty * unit_price
    )


    # Taxable Amount
    taxable_amount = (
        gross_amount - discount
    )


    if taxable_amount < 0:
        taxable_amount = Decimal("0.00")


    # GST Amount
    gst_amount = (
        taxable_amount
        * gst_rate
        / Decimal("100")
    )


    # Net Amount
    net_amount = (
        taxable_amount
        + gst_amount
    )


    # Outstanding
    outstanding_amount = (
        net_amount
        - paid_amount
    )


    if outstanding_amount < 0:
        outstanding_amount = Decimal("0.00")


    return {

        "gross_amount":
            gross_amount,

        "taxable_amount":
            taxable_amount,

        "gst_amount":
            gst_amount,

        "net_amount":
            net_amount,

        "outstanding_amount":
            outstanding_amount,

        "line_total":
            net_amount,
    }


# ============================================================
# CREATE PURCHASE TABLE
# ============================================================

def ensure_purchase_table():

    conn = None
    cursor = None

    try:

        conn = get_login_connection()

        cursor = conn.cursor()


        create_sql = """
        CREATE TABLE IF NOT EXISTS purchases (

            id INT NOT NULL AUTO_INCREMENT,

            purchase_no VARCHAR(50) NOT NULL,

            ro VARCHAR(50) NOT NULL DEFAULT '',

            vendor_id INT NOT NULL DEFAULT 0,

            company_id INT NOT NULL DEFAULT 0,

            product_id INT NOT NULL DEFAULT 0,

            batch_id INT NOT NULL DEFAULT 0,

            purchase_date DATE NOT NULL,

            invoice_no VARCHAR(50),

            invoice_date DATE,

            qty DECIMAL(12,3)
                NOT NULL DEFAULT 0.000,

            unit_price DECIMAL(12,2)
                NOT NULL DEFAULT 0.00,

            discount DECIMAL(12,2)
                NOT NULL DEFAULT 0.00,

            gst_rate DECIMAL(5,2)
                NOT NULL DEFAULT 0.00,

            gst_amount DECIMAL(12,2)
                NOT NULL DEFAULT 0.00,

            line_total DECIMAL(12,2)
                NOT NULL DEFAULT 0.00,

            gross_amount DECIMAL(12,2)
                NOT NULL DEFAULT 0.00,

            net_amount DECIMAL(12,2)
                NOT NULL DEFAULT 0.00,

            paid_amount DECIMAL(12,2)
                NOT NULL DEFAULT 0.00,

            outstanding_amount DECIMAL(12,2)
                NOT NULL DEFAULT 0.00,

            credit_period INT
                NOT NULL DEFAULT 0,

            due_date DATE,

            status VARCHAR(20)
                NOT NULL DEFAULT 'DRAFT',

            created_by INT DEFAULT NULL,

            created_at DATETIME
                DEFAULT CURRENT_TIMESTAMP,

            PRIMARY KEY (id),

            KEY idx_purchase_no (purchase_no),

            KEY idx_ro (ro),

            KEY idx_company (company_id),

            KEY idx_product (product_id),

            KEY idx_batch (batch_id),

            KEY idx_purchase_date (purchase_date)

        ) ENGINE=InnoDB
          DEFAULT CHARSET=utf8mb4
        """


        cursor.execute(create_sql)

        conn.commit()


        print(
            "Purchase table initialization: OK"
        )


    except Exception as e:

        print(
            "Purchase table initialization error:",
            e
        )


    finally:

        try:

            if cursor:
                cursor.close()

        except Exception:
            pass


        try:

            if conn:
                conn.close()

        except Exception:
            pass


# ============================================================
# COMPANY LIST
# ============================================================

def get_companies():

    conn = None
    cursor = None

    companies = []

    try:

        conn = get_login_connection()

        cursor = conn.cursor()


        sql = """
        SELECT
            COMP_ID,
            COMP_NAME
        FROM mm_company_dtls
        ORDER BY COMP_NAME
        """


        cursor.execute(sql)

        rows = cursor.fetchall()


        for row in rows:

            companies.append({

                "id": row[0],

                "name":
                    row[1] or ""
            })


    except Exception as e:

        print(
            "COMPANY LIST ERROR:",
            e
        )


    finally:

        try:

            if cursor:
                cursor.close()

        except Exception:
            pass


        try:

            if conn:
                conn.close()

        except Exception:
            pass


    return companies


# ============================================================
# PRODUCT LIST BY COMPANY
# ============================================================

def get_products_by_company(
    company_id
):

    products = []

    conn = None
    cursor = None

    company_id = safe_int(
        company_id
    )


    if company_id <= 0:

        return products


    try:

        conn = get_fertilizer_connection()

        cursor = conn.cursor()


        sql = """
        SELECT
            PROD_ID AS id,
            PROD_DESC AS name
        FROM mm_product
        WHERE COMPANY = %s
        ORDER BY PROD_DESC
        """


        cursor.execute(
            sql,
            (company_id,)
        )


        rows = cursor.fetchall()


        for row in rows:

            products.append({

                "id": row[0],

                "name":
                    row[1] or ""
            })


    except Exception as e:

        print(
            "PRODUCT LIST ERROR:",
            e
        )


    finally:

        try:

            if cursor:
                cursor.close()

        except Exception:
            pass


        try:

            if conn:
                conn.close()

        except Exception:
            pass


    return products


# ============================================================
# GET PURCHASE LIST
# ============================================================

def get_purchase_list():

    purchases = []

    conn = None
    cursor = None


    try:

        conn = get_login_connection()

        cursor = conn.cursor()


        sql = """
        SELECT

            p.id,

            p.purchase_no,

            p.ro,

            p.company_id,

            COALESCE(
                c.COMP_NAME,
                ''
            ) AS company_name,

            p.product_id,

            COALESCE(
                pr.PROD_DESC,
                ''
            ) AS product_name,

            p.batch_id,

            p.purchase_date,

            p.invoice_no,

            p.invoice_date,

            p.qty,

            p.unit_price,

            p.discount,

            p.gst_rate,

            p.gst_amount,

            p.gross_amount,

            p.net_amount,

            p.paid_amount,

            p.outstanding_amount,

            p.credit_period,

            p.due_date,

            p.status


        FROM python_login.purchases p


        LEFT JOIN
            python_login.mm_company_dtls c

            ON c.COMP_ID =
               p.company_id


        LEFT JOIN
            benfed_fertilizer.mm_product pr

            ON pr.PROD_ID =
               p.product_id


        ORDER BY

            p.purchase_date DESC,

            p.id DESC
        """


        cursor.execute(sql)

        rows = cursor.fetchall()


        for row in rows:

            purchases.append({

                "id":
                    row[0],

                "purchase_no":
                    row[1] or "",

                "ro":
                    row[2] or "",

                "company_id":
                    row[3] or 0,

                "company_name":
                    row[4] or "",

                "product_id":
                    row[5] or 0,

                "product_name":
                    row[6] or "",

                "batch_id":
                    row[7] or 0,

                "purchase_date":
                    row[8],

                "invoice_no":
                    row[9] or "",

                "invoice_date":
                    row[10],

                "qty":
                    decimal_to_float(row[11]),

                "unit_price":
                    decimal_to_float(row[12]),

                "discount":
                    decimal_to_float(row[13]),

                "gst_rate":
                    decimal_to_float(row[14]),

                "gst_amount":
                    decimal_to_float(row[15]),

                "gross_amount":
                    decimal_to_float(row[16]),

                "net_amount":
                    decimal_to_float(row[17]),

                "paid_amount":
                    decimal_to_float(row[18]),

                "outstanding_amount":
                    decimal_to_float(row[19]),

                "credit_period":
                    row[20] or 0,

                "due_date":
                    row[21],

                "status":
                    row[22] or "DRAFT",
            })


    except Exception as e:

        print(
            "PURCHASE LIST ERROR:",
            e
        )


    finally:

        try:

            if cursor:
                cursor.close()

        except Exception:
            pass


        try:

            if conn:
                conn.close()

        except Exception:
            pass


    return purchases


# ============================================================
# GET PURCHASE BY ID
# ============================================================

def get_purchase_by_id(
    purchase_id
):

    purchase = None

    conn = None
    cursor = None

    purchase_id = safe_int(
        purchase_id
    )


    if purchase_id <= 0:

        return None


    try:

        conn = get_login_connection()

        cursor = conn.cursor()


        sql = """
        SELECT

            id,

            purchase_no,

            ro,

            company_id,

            product_id,

            batch_id,

            purchase_date,

            invoice_no,

            invoice_date,

            qty,

            unit_price,

            discount,

            gst_rate,

            gst_amount,

            line_total,

            gross_amount,

            net_amount,

            paid_amount,

            outstanding_amount,

            credit_period,

            due_date,

            status

        FROM purchases

        WHERE id = %s

        LIMIT 1
        """


        cursor.execute(
            sql,
            (purchase_id,)
        )


        row = cursor.fetchone()


        if row:

            purchase = {

                "id":
                    row[0],

                "purchase_no":
                    row[1] or "",

                "ro":
                    row[2] or "",

                "company_id":
                    row[3] or 0,

                "product_id":
                    row[4] or 0,

                "batch_id":
                    row[5] or 0,

                "purchase_date":
                    row[6],

                "invoice_no":
                    row[7] or "",

                "invoice_date":
                    row[8],

                "qty":
                    decimal_to_float(row[9]),

                "unit_price":
                    decimal_to_float(row[10]),

                "discount":
                    decimal_to_float(row[11]),

                "gst_rate":
                    decimal_to_float(row[12]),

                "gst_amount":
                    decimal_to_float(row[13]),

                "line_total":
                    decimal_to_float(row[14]),

                "gross_amount":
                    decimal_to_float(row[15]),

                "net_amount":
                    decimal_to_float(row[16]),

                "paid_amount":
                    decimal_to_float(row[17]),

                "outstanding_amount":
                    decimal_to_float(row[18]),

                "credit_period":
                    row[19] or 0,

                "due_date":
                    row[20],

                "status":
                    row[21] or "DRAFT",
            }


    except Exception as e:

        print(
            "GET PURCHASE ERROR:",
            e
        )


    finally:

        try:

            if cursor:
                cursor.close()

        except Exception:
            pass


        try:

            if conn:
                conn.close()

        except Exception:
            pass


    return purchase


# ============================================================
# PURCHASE LIST
# ============================================================

@router.get("")
async def purchase_list(
    request: Request
):

    try:

        ensure_purchase_table()


        companies = get_companies()


        purchases = get_purchase_list()


        return templates.TemplateResponse(

            request=request,

            name="purchase.html",

            context={

                "request":
                    request,

                "companies":
                    companies,

                "purchases":
                    purchases,

                "edit_mode":
                    False,

                "purchase":
                    None,

                "products":
                    [],
            }
        )


    except Exception as e:

        print(
            "PURCHASE PAGE ERROR:",
            e
        )


        return JSONResponse(

            status_code=500,

            content={

                "success":
                    False,

                "message":
                    "Purchase page could not be loaded.",

                "error":
                    str(e)
            }
        )


# ============================================================
# PURCHASE LIST /
# ============================================================

@router.get("/")
async def purchase_list_slash(
    request: Request
):

    return await purchase_list(
        request
    )


# ============================================================
# ADD PURCHASE
# ============================================================

@router.get("/add")
async def purchase_add(
    request: Request
):

    try:

        ensure_purchase_table()


        companies = get_companies()


        purchases = get_purchase_list()


        return templates.TemplateResponse(

            request=request,

            name="purchase.html",

            context={

                "request":
                    request,

                "companies":
                    companies,

                "purchases":
                    purchases,

                "edit_mode":
                    False,

                "purchase":
                    None,

                "products":
                    [],
            }
        )


    except Exception as e:

        print(
            "PURCHASE ADD PAGE ERROR:",
            e
        )


        return JSONResponse(

            status_code=500,

            content={

                "success":
                    False,

                "message":
                    "Purchase add page could not be loaded.",

                "error":
                    str(e)
            }
        )


# ============================================================
# EDIT PURCHASE
# ============================================================

@router.get("/edit/{purchase_id}")
async def purchase_edit(

    request: Request,

    purchase_id: int

):

    try:

        ensure_purchase_table()


        purchase = get_purchase_by_id(
            purchase_id
        )


        if not purchase:

            return RedirectResponse(

                url="/purchase/",

                status_code=303
            )


        companies = get_companies()


        products = get_products_by_company(

            purchase["company_id"]

        )


        purchases = get_purchase_list()


        return templates.TemplateResponse(

            request=request,

            name="purchase.html",

            context={

                "request":
                    request,

                "companies":
                    companies,

                "purchases":
                    purchases,

                "edit_mode":
                    True,

                "purchase":
                    purchase,

                "products":
                    products,
            }
        )


    except Exception as e:

        print(
            "PURCHASE EDIT ERROR:",
            e
        )


        return JSONResponse(

            status_code=500,

            content={

                "success":
                    False,

                "message":
                    "Purchase edit page could not be loaded.",

                "error":
                    str(e)
            }
        )


# ============================================================
# PRODUCT API
# ============================================================

@router.get("/api/products")
async def purchase_products_api(

    company_id: int = 0

):

    try:

        company_id = safe_int(
            company_id
        )


        products = get_products_by_company(

            company_id
        )


        return {

            "success":
                True,

            "products":
                products
        }


    except Exception as e:

        print(
            "PURCHASE PRODUCT API ERROR:",
            e
        )


        return JSONResponse(

            status_code=500,

            content={

                "success":
                    False,

                "products":
                    [],

                "message":
                    str(e)
            }
        )


# ============================================================
# SAVE PURCHASE
# ============================================================

@router.post("/save")
async def purchase_save(

    request: Request,

    purchase_id: int = Form(0),

    purchase_no: str = Form(""),

    company_id: int = Form(0),

    purchase_date: str = Form(""),

    product_id: int = Form(0),

    batch_id: int = Form(0),

    invoice_no: str = Form(""),

    invoice_date: str = Form(""),

    qty: str = Form("0"),

    unit_price: str = Form("0"),

    discount: str = Form("0"),

    gst_rate: str = Form("0"),

    paid_amount: str = Form("0"),

    credit_period: int = Form(0),

    due_date: str = Form(""),

    status: str = Form("DRAFT"),

):

    conn = None

    cursor = None


    try:

        ensure_purchase_table()


        # ----------------------------------------------------
        # BASIC VALUES
        # ----------------------------------------------------

        purchase_id = safe_int(
            purchase_id
        )


        purchase_no = (
            purchase_no or ""
        ).strip()


        company_id = safe_int(
            company_id
        )


        product_id = safe_int(
            product_id
        )


        batch_id = safe_int(
            batch_id
        )


        purchase_date_obj = safe_date(

            purchase_date,

            date.today()
        )


        invoice_date_obj = safe_date(

            invoice_date,

            None
        )


        due_date_obj = safe_date(

            due_date,

            None
        )


        credit_period = safe_int(

            credit_period,

            0
        )


        status = (

            status or "DRAFT"

        ).strip().upper()


        allowed_status = {

            "DRAFT",

            "POSTED",

            "PAID",

            "PARTIAL",

            "CANCELLED"
        }


        if status not in allowed_status:

            status = "DRAFT"


        # ----------------------------------------------------
        # VALIDATION
        # ----------------------------------------------------

        if not purchase_no:

            return JSONResponse(

                status_code=400,

                content={

                    "success":
                        False,

                    "message":
                        "Purchase No / RO No is required."
                }
            )


        if company_id <= 0:

            return JSONResponse(

                status_code=400,

                content={

                    "success":
                        False,

                    "message":
                        "Company / Vendor is required."
                }
            )


        if product_id <= 0:

            return JSONResponse(

                status_code=400,

                content={

                    "success":
                        False,

                    "message":
                        "Product is required."
                }
            )


        # ----------------------------------------------------
        # CALCULATE
        # ----------------------------------------------------

        values = calculate_purchase_values(

            qty,

            unit_price,

            discount,

            gst_rate,

            paid_amount
        )


        qty_decimal = safe_decimal(
            qty
        )


        unit_price_decimal = safe_decimal(
            unit_price
        )


        discount_decimal = safe_decimal(
            discount
        )


        gst_rate_decimal = safe_decimal(
            gst_rate
        )


        paid_decimal = safe_decimal(
            paid_amount
        )


        gross_amount = values[
            "gross_amount"
        ]


        gst_amount = values[
            "gst_amount"
        ]


        net_amount = values[
            "net_amount"
        ]


        outstanding_amount = values[
            "outstanding_amount"
        ]


        line_total = values[
            "line_total"
        ]


        # ----------------------------------------------------
        # DUE DATE
        # ----------------------------------------------------

        if due_date_obj is None:

            due_date_obj = (

                purchase_date_obj

                + timedelta(
                    days=credit_period
                )
            )


        # ----------------------------------------------------
        # DATABASE
        # ----------------------------------------------------

        conn = get_login_connection()

        cursor = conn.cursor()


        # ====================================================
        # UPDATE
        # ====================================================

        if purchase_id > 0:

            update_sql = """

            UPDATE purchases

            SET

                purchase_no = %s,

                ro = %s,

                vendor_id = %s,

                company_id = %s,

                product_id = %s,

                batch_id = %s,

                purchase_date = %s,

                invoice_no = %s,

                invoice_date = %s,

                qty = %s,

                unit_price = %s,

                discount = %s,

                gst_rate = %s,

                gst_amount = %s,

                line_total = %s,

                gross_amount = %s,

                net_amount = %s,

                paid_amount = %s,

                outstanding_amount = %s,

                credit_period = %s,

                due_date = %s,

                status = %s

            WHERE id = %s

            """


            cursor.execute(

                update_sql,

                (

                    purchase_no,

                    # Purchase No = RO No
                    purchase_no,

                    # Legacy vendor_id
                    0,

                    company_id,

                    product_id,

                    batch_id,

                    purchase_date_obj,

                    invoice_no,

                    invoice_date_obj,

                    qty_decimal,

                    unit_price_decimal,

                    discount_decimal,

                    gst_rate_decimal,

                    gst_amount,

                    line_total,

                    gross_amount,

                    net_amount,

                    paid_decimal,

                    outstanding_amount,

                    credit_period,

                    due_date_obj,

                    status,

                    purchase_id
                )
            )


            conn.commit()


            print(
                "PURCHASE UPDATED:",
                purchase_id
            )


        # ====================================================
        # INSERT
        # ====================================================

        else:

            insert_sql = """

            INSERT INTO purchases (

                purchase_no,

                ro,

                vendor_id,

                company_id,

                product_id,

                batch_id,

                purchase_date,

                invoice_no,

                invoice_date,

                qty,

                unit_price,

                discount,

                gst_rate,

                gst_amount,

                line_total,

                gross_amount,

                net_amount,

                paid_amount,

                outstanding_amount,

                credit_period,

                due_date,

                status

            )

            VALUES (

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s,

                %s

            )

            """


            cursor.execute(

                insert_sql,

                (

                    purchase_no,

                    # Purchase No = RO No
                    purchase_no,

                    # Legacy vendor_id
                    0,

                    company_id,

                    product_id,

                    batch_id,

                    purchase_date_obj,

                    invoice_no,

                    invoice_date_obj,

                    qty_decimal,

                    unit_price_decimal,

                    discount_decimal,

                    gst_rate_decimal,

                    gst_amount,

                    line_total,

                    gross_amount,

                    net_amount,

                    paid_decimal,

                    outstanding_amount,

                    credit_period,

                    due_date_obj,

                    status
                )
            )


            conn.commit()


            new_id = cursor.lastrowid


            print(
                "PURCHASE INSERTED:",
                new_id
            )


        # ----------------------------------------------------
        # REDIRECT
        # ----------------------------------------------------

        return RedirectResponse(

            url="/purchase/",

            status_code=303
        )


    except Exception as e:

        if conn:

            try:

                conn.rollback()

            except Exception:
                pass


        print(
            "PURCHASE SAVE ERROR:",
            e
        )


        return JSONResponse(

            status_code=500,

            content={

                "success":
                    False,

                "message":
                    "Purchase could not be saved.",

                "error":
                    str(e)
            }
        )


    finally:

        try:

            if cursor:
                cursor.close()

        except Exception:
            pass


        try:

            if conn:
                conn.close()

        except Exception:
            pass


# ============================================================
# DELETE PURCHASE
# ============================================================

@router.get("/delete/{purchase_id}")
async def purchase_delete(

    request: Request,

    purchase_id: int

):

    conn = None

    cursor = None


    try:

        purchase_id = safe_int(
            purchase_id
        )


        if purchase_id <= 0:

            return RedirectResponse(

                url="/purchase/",

                status_code=303
            )


        conn = get_login_connection()

        cursor = conn.cursor()


        delete_sql = """

        DELETE FROM purchases

        WHERE id = %s

        """


        cursor.execute(

            delete_sql,

            (purchase_id,)
        )


        conn.commit()


        print(
            "PURCHASE DELETED:",
            purchase_id
        )


        return RedirectResponse(

            url="/purchase/",

            status_code=303
        )


    except Exception as e:

        if conn:

            try:

                conn.rollback()

            except Exception:
                pass


        print(
            "PURCHASE DELETE ERROR:",
            e
        )


        return JSONResponse(

            status_code=500,

            content={

                "success":
                    False,

                "message":
                    "Purchase could not be deleted.",

                "error":
                    str(e)
            }
        )


    finally:

        try:

            if cursor:
                cursor.close()

        except Exception:
            pass


        try:

            if conn:
                conn.close()

        except Exception:
            pass