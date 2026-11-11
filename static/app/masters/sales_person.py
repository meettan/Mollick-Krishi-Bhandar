from pathlib import Path
from decimal import Decimal
from datetime import date
import traceback

import mysql.connector
from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates


# ============================================================
# PATH / TEMPLATE
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = PROJECT_ROOT / "templates"

from ..sidebar_context import sidebar_context


templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR),
    context_processors=[sidebar_context],
)


# ============================================================
# ROUTER
# ============================================================

router = APIRouter(
    prefix="/sales-person",
    tags=["Sales Person Master"]
)


# ============================================================
# DATABASE CONFIG
# ============================================================

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "python_login",
}


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():
    return mysql.connector.connect(
        host=DB_CONFIG["host"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database=DB_CONFIG["database"]
    )


# ============================================================
# SALES PERSON MASTER PAGE
# ============================================================

@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    search: str = Query(default=""),
    status: str = Query(default="")
):

    conn = None
    cursor = None

    try:

        conn = get_connection()

        # Dictionary cursor
        cursor = conn.cursor(dictionary=True)

        # ====================================================
        # SALES PERSON LIST
        # ====================================================

        sql = """
            SELECT
                id,
                employee_code,
                name,
                mobile,
                email,
                address,
                joining_date,
                daily_target,
                monthly_target,
                status,
                user_id
            FROM sales_persons
            WHERE 1=1
        """

        params = []

        # Search
        if search:

            sql += """
                AND (
                    employee_code LIKE %s
                    OR name LIKE %s
                    OR mobile LIKE %s
                    OR email LIKE %s
                )
            """

            search_value = "%" + search + "%"

            params.extend([
                search_value,
                search_value,
                search_value,
                search_value
            ])

        # Status
        if status in ("0", "1"):

            sql += """
                AND status = %s
            """

            params.append(int(status))

        sql += """
            ORDER BY id DESC
        """

        cursor.execute(
            sql,
            tuple(params)
        )

        sales_persons = cursor.fetchall()

        # ====================================================
        # USERS DROPDOWN
        # ====================================================

        users = []

        try:

            cursor.execute("""
                SELECT
                    id,
                    username
                FROM users
                ORDER BY username
            """)

            users = cursor.fetchall()

        except Exception as user_error:

            print(
                "USERS DROPDOWN ERROR:",
                repr(user_error)
            )

            users = []

        # ====================================================
        # TEMPLATE
        # ====================================================

        return templates.TemplateResponse(
            request=request,
            name="sales_person.html",
            context={
                "request": request,
                "sales_persons": sales_persons,
                "users": users,
                "search": search,
                "status": status
            }
        )

    except Exception as e:

        print("")
        print("==============================================")
        print("SALES PERSON LIST ERROR")
        print("==============================================")
        print("ERROR:", repr(e))
        traceback.print_exc()
        print("==============================================")
        print("")

        return HTMLResponse(
            content=f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Sales Person Error</title>
                    <style>
                        body {{
                            font-family: Arial, sans-serif;
                            padding: 30px;
                            background: #f4f6f9;
                        }}

                        .error {{
                            background: white;
                            padding: 25px;
                            border-radius: 8px;
                            box-shadow: 0 2px 10px rgba(0,0,0,.1);
                        }}

                        pre {{
                            background: #f8f8f8;
                            border: 1px solid #ddd;
                            padding: 15px;
                            white-space: pre-wrap;
                            color: #b00020;
                        }}
                    </style>
                </head>

                <body>

                    <div class="error">

                        <h2>Sales Person Error</h2>

                        <pre>{repr(e)}</pre>

                        <p>
                            Please check the terminal for the complete traceback.
                        </p>

                    </div>

                </body>
                </html>
            """,
            status_code=500
        )

    finally:

        try:
            if cursor:
                cursor.close()
        except:
            pass

        try:
            if conn:
                conn.close()
        except:
            pass


# ============================================================
# GET SINGLE SALES PERSON
# ============================================================

@router.get("/get/{sales_person_id}")
async def get_sales_person(
    sales_person_id: int
):

    conn = None
    cursor = None

    try:

        conn = get_connection()

        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                employee_code,
                name,
                mobile,
                email,
                address,
                joining_date,
                daily_target,
                monthly_target,
                status,
                user_id
            FROM sales_persons
            WHERE id = %s
        """, (sales_person_id,))

        row = cursor.fetchone()

        if not row:

            return JSONResponse(
                {
                    "success": False,
                    "message": "Sales person not found"
                },
                status_code=404
            )

        # Date conversion
        if row.get("joining_date"):

            if isinstance(
                row["joining_date"],
                (date,)
            ):

                row["joining_date"] = row[
                    "joining_date"
                ].strftime("%Y-%m-%d")

        else:

            row["joining_date"] = ""

        # Decimal conversion
        if isinstance(
            row.get("daily_target"),
            Decimal
        ):

            row["daily_target"] = float(
                row["daily_target"]
            )

        if isinstance(
            row.get("monthly_target"),
            Decimal
        ):

            row["monthly_target"] = float(
                row["monthly_target"]
            )

        return JSONResponse(
            {
                "success": True,
                "data": row
            }
        )

    except Exception as e:

        print(
            "GET SALES PERSON ERROR:",
            repr(e)
        )

        traceback.print_exc()

        return JSONResponse(
            {
                "success": False,
                "message": str(e)
            },
            status_code=500
        )

    finally:

        try:
            if cursor:
                cursor.close()
        except:
            pass

        try:
            if conn:
                conn.close()
        except:
            pass


# ============================================================
# SAVE NEW SALES PERSON
# ============================================================

@router.post("/save")
async def save_sales_person(

    employee_code: str = Form(...),
    name: str = Form(...),
    mobile: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    joining_date: str = Form(""),
    daily_target: str = Form("0"),
    monthly_target: str = Form("0"),
    status: str = Form("1"),
    user_id: str = Form("")

):

    conn = None
    cursor = None

    try:

        conn = get_connection()

        cursor = conn.cursor()

        # ----------------------------------------------------
        # USER ID
        # ----------------------------------------------------

        user_id_value = None

        if user_id and user_id.strip():

            user_id_value = int(
                user_id
            )

        # ----------------------------------------------------
        # DATE
        # ----------------------------------------------------

        joining_date_value = None

        if joining_date and joining_date.strip():

            joining_date_value = joining_date.strip()

        # ----------------------------------------------------
        # TARGET
        # ----------------------------------------------------

        daily_target_value = float(
            daily_target or 0
        )

        monthly_target_value = float(
            monthly_target or 0
        )

        status_value = int(
            status or 1
        )

        # ----------------------------------------------------
        # INSERT
        # ----------------------------------------------------

        sql = """
            INSERT INTO sales_persons
            (
                employee_code,
                name,
                mobile,
                email,
                address,
                joining_date,
                daily_target,
                monthly_target,
                status,
                user_id
            )
            VALUES
            (
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

        values = (
            employee_code.strip(),
            name.strip(),
            mobile.strip(),
            email.strip(),
            address.strip(),
            joining_date_value,
            daily_target_value,
            monthly_target_value,
            status_value,
            user_id_value
        )

        cursor.execute(
            sql,
            values
        )

        conn.commit()

        return JSONResponse({
            "success": True,
            "message": "Sales person added successfully",
            "id": cursor.lastrowid
        })

    except mysql.connector.Error as e:

        if conn:
            conn.rollback()

        print(
            "SAVE SALES PERSON DB ERROR:",
            repr(e)
        )

        return JSONResponse({
            "success": False,
            "message": str(e)
        })

    except Exception as e:

        if conn:
            conn.rollback()

        print(
            "SAVE SALES PERSON ERROR:",
            repr(e)
        )

        traceback.print_exc()

        return JSONResponse({
            "success": False,
            "message": str(e)
        })

    finally:

        try:
            if cursor:
                cursor.close()
        except:
            pass

        try:
            if conn:
                conn.close()
        except:
            pass


# ============================================================
# UPDATE SALES PERSON
# ============================================================

@router.post("/update/{sales_person_id}")
async def update_sales_person(

    sales_person_id: int,

    employee_code: str = Form(...),
    name: str = Form(...),
    mobile: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    joining_date: str = Form(""),
    daily_target: str = Form("0"),
    monthly_target: str = Form("0"),
    status: str = Form("1"),
    user_id: str = Form("")

):

    conn = None
    cursor = None

    try:

        conn = get_connection()

        cursor = conn.cursor()

        # ----------------------------------------------------
        # USER ID
        # ----------------------------------------------------

        user_id_value = None

        if user_id and user_id.strip():

            user_id_value = int(
                user_id
            )

        # ----------------------------------------------------
        # DATE
        # ----------------------------------------------------

        joining_date_value = None

        if joining_date and joining_date.strip():

            joining_date_value = joining_date.strip()

        # ----------------------------------------------------
        # TARGET
        # ----------------------------------------------------

        daily_target_value = float(
            daily_target or 0
        )

        monthly_target_value = float(
            monthly_target or 0
        )

        status_value = int(
            status or 1
        )

        # ----------------------------------------------------
        # UPDATE
        # ----------------------------------------------------

        sql = """
            UPDATE sales_persons
            SET
                employee_code = %s,
                name = %s,
                mobile = %s,
                email = %s,
                address = %s,
                joining_date = %s,
                daily_target = %s,
                monthly_target = %s,
                status = %s,
                user_id = %s
            WHERE id = %s
        """

        values = (
            employee_code.strip(),
            name.strip(),
            mobile.strip(),
            email.strip(),
            address.strip(),
            joining_date_value,
            daily_target_value,
            monthly_target_value,
            status_value,
            user_id_value,
            sales_person_id
        )

        cursor.execute(
            sql,
            values
        )

        conn.commit()

        return JSONResponse({
            "success": True,
            "message": "Sales person updated successfully"
        })

    except mysql.connector.Error as e:

        if conn:
            conn.rollback()

        print(
            "UPDATE SALES PERSON DB ERROR:",
            repr(e)
        )

        return JSONResponse({
            "success": False,
            "message": str(e)
        })

    except Exception as e:

        if conn:
            conn.rollback()

        print(
            "UPDATE SALES PERSON ERROR:",
            repr(e)
        )

        traceback.print_exc()

        return JSONResponse({
            "success": False,
            "message": str(e)
        })

    finally:

        try:
            if cursor:
                cursor.close()
        except:
            pass

        try:
            if conn:
                conn.close()
        except:
            pass


# ============================================================
# DELETE SALES PERSON
# ============================================================

@router.delete("/delete/{sales_person_id}")
async def delete_sales_person(
    sales_person_id: int
):

    conn = None
    cursor = None

    try:

        conn = get_connection()

        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM sales_persons
            WHERE id = %s
        """, (sales_person_id,))

        if cursor.rowcount == 0:

            return JSONResponse({
                "success": False,
                "message": "Sales person not found"
            })

        conn.commit()

        return JSONResponse({
            "success": True,
            "message": "Sales person deleted successfully"
        })

    except mysql.connector.Error as e:

        if conn:
            conn.rollback()

        print(
            "DELETE SALES PERSON DB ERROR:",
            repr(e)
        )

        return JSONResponse({
            "success": False,
            "message": str(e)
        })

    except Exception as e:

        if conn:
            conn.rollback()

        print(
            "DELETE SALES PERSON ERROR:",
            repr(e)
        )

        traceback.print_exc()

        return JSONResponse({
            "success": False,
            "message": str(e)
        })

    finally:

        try:
            if cursor:
                cursor.close()
        except:
            pass

        try:
            if conn:
                conn.close()
        except:
            pass