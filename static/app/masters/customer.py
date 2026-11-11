
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import mysql.connector
from pathlib import Path

from ..config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME


router = APIRouter(
    prefix="/customer",
    tags=["Customer Master"]
)


# ---------------------------------------------------------
# TEMPLATE PATH
# ---------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parents[2]
from ..sidebar_context import sidebar_context


templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates"),
    context_processors=[sidebar_context],
)


# ---------------------------------------------------------
# DATABASE CONFIG
# ---------------------------------------------------------
DB_CONFIG = {
    "host": DB_HOST,
    "user": DB_USER,
    "password": DB_PASSWORD,
    "database": DB_NAME,
}


# ---------------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------------
def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


# ---------------------------------------------------------
# CREATE CUSTOMER TABLE
# ---------------------------------------------------------
def ensure_customer_table():

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INT AUTO_INCREMENT PRIMARY KEY,

                customer_code VARCHAR(50) NOT NULL UNIQUE,
                customer_name VARCHAR(150) NOT NULL,

                mobile VARCHAR(20) DEFAULT NULL,
                email VARCHAR(100) DEFAULT NULL,

                address TEXT DEFAULT NULL,

                gst_no VARCHAR(20) DEFAULT NULL,
                pan_no VARCHAR(20) DEFAULT NULL,

                credit_days INT DEFAULT 0,

                opening_balance DECIMAL(15,2) DEFAULT 0.00,

                status TINYINT(1) DEFAULT 1,

                created_by INT DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

                modified_by INT DEFAULT NULL,
                modified_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            )
        """)

        conn.commit()

        print("CUSTOMER TABLE READY")

    except Exception as e:
        print("CUSTOMER TABLE ERROR:", e)

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()


# ---------------------------------------------------------
# NEXT CUSTOMER CODE
# ---------------------------------------------------------
def get_next_customer_code():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(
                MAX(CAST(SUBSTRING(customer_code, 6) AS UNSIGNED)),
                0
            )
            FROM customers
            WHERE customer_code REGEXP '^CUST-[0-9]+$'
        """)
        row = cursor.fetchone()
        next_number = int(row[0] or 0) + 1
        return f"CUST-{next_number:04d}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ---------------------------------------------------------
# CUSTOMER LIST
# ---------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
async def customer_master(
    request: Request,
    search: str = "",
    status: str = ""
):

    customers = []
    error = ""

    conn = None
    cursor = None

    try:

        # Make sure table exists
        ensure_customer_table()

        conn = get_db_connection()

        cursor = conn.cursor(dictionary=True)

        sql = """
            SELECT
                id,
                customer_code,
                customer_name,
                mobile,
                email,
                address,
                gst_no,
                pan_no,
                credit_days,
                opening_balance,
                status
            FROM customers
            WHERE 1=1
        """

        params = []

        # Search
        if search.strip():

            sql += """
                AND (
                    customer_code LIKE %s
                    OR customer_name LIKE %s
                    OR mobile LIKE %s
                    OR email LIKE %s
                    OR gst_no LIKE %s
                    OR pan_no LIKE %s
                )
            """

            search_value = "%" + search.strip() + "%"

            params.extend([
                search_value,
                search_value,
                search_value,
                search_value,
                search_value,
                search_value
            ])

        # Status filter
        if status != "":

            sql += " AND status = %s"

            params.append(int(status))

        sql += """
            ORDER BY customer_name ASC
        """

        cursor.execute(sql, params)

        customers = cursor.fetchall()

        # MySQL DECIMAL values are returned as Decimal objects.
        # Convert values used by the Jinja tojson filter to native
        # JSON-compatible Python types before rendering.
        for customer in customers:
            if customer.get("opening_balance") is not None:
                customer["opening_balance"] = float(customer["opening_balance"])
            if customer.get("credit_days") is not None:
                customer["credit_days"] = int(customer["credit_days"])
            if customer.get("status") is not None:
                customer["status"] = int(customer["status"])

    except Exception as e:

        error = str(e)

        print("CUSTOMER LIST ERROR:", e)

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()

    next_customer_code = "CUST-0001"
    try:
        next_customer_code = get_next_customer_code()
    except Exception as e:
        print("CUSTOMER NEXT CODE ERROR:", e)

    return templates.TemplateResponse(
        request=request,
        name="customer.html",
        context={
            "request": request,
            "customers": customers,
            "search": search,
            "status": status,
            "next_customer_code": next_customer_code,
            "error": error
        }
    )


# ---------------------------------------------------------
# ADD CUSTOMER
# ---------------------------------------------------------
@router.post("/add")
async def add_customer(

    customer_name: str = Form(...),

    mobile: str = Form(""),
    email: str = Form(""),

    address: str = Form(""),

    gst_no: str = Form(""),
    pan_no: str = Form(""),

    credit_days: int = Form(0),

    opening_balance: float = Form(0),

    status: int = Form(1)

):

    conn = None
    cursor = None

    try:

        conn = get_db_connection()

        cursor = conn.cursor()

        # Customer Code is system generated; never trust the browser value.
        cursor.execute("""
            SELECT COALESCE(
                MAX(CAST(SUBSTRING(customer_code, 6) AS UNSIGNED)),
                0
            )
            FROM customers
            WHERE customer_code REGEXP '^CUST-[0-9]+$'
        """)
        row = cursor.fetchone()
        generated_customer_code = f"CUST-{int(row[0] or 0) + 1:04d}"

        sql = """
            INSERT INTO customers
            (
                customer_code,
                customer_name,
                mobile,
                email,
                address,
                gst_no,
                pan_no,
                credit_days,
                opening_balance,
                status
            )
            VALUES
            (
                %s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s
            )
        """

        values = (
            generated_customer_code,
            customer_name.strip(),
            mobile.strip(),
            email.strip(),
            address.strip(),
            gst_no.strip().upper(),
            pan_no.strip().upper(),
            credit_days,
            opening_balance,
            status
        )

        cursor.execute(sql, values)

        conn.commit()

        print("CUSTOMER ADDED")

    except mysql.connector.IntegrityError as e:

        print("CUSTOMER ADD DUPLICATE ERROR:", e)

    except Exception as e:

        print("CUSTOMER ADD ERROR:", e)

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()

    return RedirectResponse(
        url="/customer/",
        status_code=303
    )


# ---------------------------------------------------------
# UPDATE CUSTOMER
# ---------------------------------------------------------
@router.post("/update")
async def update_customer(

    id: int = Form(...),

    customer_name: str = Form(...),

    mobile: str = Form(""),
    email: str = Form(""),

    address: str = Form(""),

    gst_no: str = Form(""),
    pan_no: str = Form(""),

    credit_days: int = Form(0),

    opening_balance: float = Form(0),

    status: int = Form(1)

):

    conn = None
    cursor = None

    try:

        conn = get_db_connection()

        cursor = conn.cursor()

        sql = """
            UPDATE customers
            SET
                customer_name = %s,
                mobile = %s,
                email = %s,
                address = %s,
                gst_no = %s,
                pan_no = %s,
                credit_days = %s,
                opening_balance = %s,
                status = %s
            WHERE id = %s
        """

        values = (
            customer_name.strip(),
            mobile.strip(),
            email.strip(),
            address.strip(),
            gst_no.strip().upper(),
            pan_no.strip().upper(),
            credit_days,
            opening_balance,
            status,
            id
        )

        cursor.execute(sql, values)

        conn.commit()

        print("CUSTOMER UPDATED")

    except mysql.connector.IntegrityError as e:

        print("CUSTOMER UPDATE DUPLICATE ERROR:", e)

    except Exception as e:

        print("CUSTOMER UPDATE ERROR:", e)

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()

    return RedirectResponse(
        url="/customer/",
        status_code=303
    )


# ---------------------------------------------------------
# DELETE CUSTOMER
# ---------------------------------------------------------
@router.post("/delete")
async def delete_customer(
    id: int = Form(...)
):

    conn = None
    cursor = None

    try:

        conn = get_db_connection()

        cursor = conn.cursor(dictionary=True)

        # -------------------------------------------------
        # Check whether sales_master exists
        # -------------------------------------------------
        cursor.execute("""
            SELECT COUNT(*) AS cnt
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_name = 'sales_master'
        """, (
            DB_CONFIG["database"],
        ))

        table_result = cursor.fetchone()

        sales_table_exists = (
            table_result
            and table_result["cnt"] > 0
        )

        # -------------------------------------------------
        # Do not delete customer already used in sales
        # -------------------------------------------------
        if sales_table_exists:

            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM sales_master
                WHERE customer_id = %s
            """, (
                id,
            ))

            usage_result = cursor.fetchone()

            if usage_result and usage_result["cnt"] > 0:

                print(
                    "CUSTOMER DELETE BLOCKED: "
                    "Customer already used in sales."
                )

                return RedirectResponse(
                    url="/customer/",
                    status_code=303
                )

        # -------------------------------------------------
        # Delete
        # -------------------------------------------------
        cursor.execute(
            "DELETE FROM customers WHERE id = %s",
            (id,)
        )

        conn.commit()

        print("CUSTOMER DELETED")

    except Exception as e:

        print("CUSTOMER DELETE ERROR:", e)

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()

    return RedirectResponse(
        url="/customer/",
        status_code=303
    )

