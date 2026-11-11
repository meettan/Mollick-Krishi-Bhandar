from datetime import datetime
from pathlib import Path

import mysql.connector
from mysql.connector import Error

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates


# ============================================================
# COMPANY MASTER
# Database : python_login
# Table    : mm_company_dtls
# MySQL    : localhost
# User     : root
# Password : blank
# ============================================================


# ------------------------------------------------------------
# PATH
# ------------------------------------------------------------

# company_master.py
#     app/
#         masters/
#
# parents[0] = masters
# parents[1] = app
# parents[2] = project root

BASE_DIR = Path(__file__).resolve().parents[2]

TEMPLATES_DIR = BASE_DIR / "templates"


# ------------------------------------------------------------
# JINJA2
# ------------------------------------------------------------

from ..sidebar_context import sidebar_context


templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR),
    context_processors=[sidebar_context],
)


# ------------------------------------------------------------
# ROUTER
# ------------------------------------------------------------

router = APIRouter(
    prefix="/company",
    tags=["Company Master"]
)


# ------------------------------------------------------------
# DATABASE CONFIG
# ------------------------------------------------------------

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "python_login",
}


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_company_db():

    try:

        db = mysql.connector.connect(
            host=DB_CONFIG["host"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
        )

        return db

    except Error as e:

        print("Company database connection error:", e)

        raise


# ============================================================
# CREATE COMPANY TABLE IF NOT EXISTS
# ============================================================

def ensure_company_table():

    db = get_company_db()

    cur = db.cursor()

    try:

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS mm_company_dtls
            (
                comp_id INT NOT NULL PRIMARY KEY,

                comp_name VARCHAR(200) NOT NULL,

                short_name VARCHAR(100) DEFAULT NULL,

                comp_pn_no VARCHAR(50) DEFAULT NULL,

                comp_email_id VARCHAR(150) DEFAULT NULL,

                created_by VARCHAR(100) DEFAULT NULL,

                created_dt DATETIME DEFAULT NULL,

                modified_by VARCHAR(100) DEFAULT NULL,

                modified_dt DATETIME DEFAULT NULL,

                comp_add VARCHAR(500) DEFAULT NULL,

                pan_no VARCHAR(30) DEFAULT NULL,

                gst_no VARCHAR(30) DEFAULT NULL,

                cin VARCHAR(50) DEFAULT NULL,

                mfms VARCHAR(50) DEFAULT NULL,

                acc_cd VARCHAR(50) DEFAULT NULL,

                adv_acc VARCHAR(50) DEFAULT NULL,

                tds_acc VARCHAR(50) DEFAULT NULL,

                bank_name VARCHAR(150) DEFAULT NULL,

                bnk_branch_name VARCHAR(150) DEFAULT NULL,

                ac_no VARCHAR(100) DEFAULT NULL,

                ifsc VARCHAR(30) DEFAULT NULL
            )
            """
        )

        db.commit()

    except Exception as e:

        db.rollback()

        print("Company table creation error:", e)

        raise

    finally:

        cur.close()
        db.close()


# ============================================================
# GET NEXT COMPANY ID
# ============================================================

def get_next_company_id():

    db = get_company_db()

    cur = db.cursor()

    try:

        cur.execute(
            """
            SELECT COALESCE(MAX(comp_id), 0) + 1
            FROM mm_company_dtls
            """
        )

        row = cur.fetchone()

        if row and row[0] is not None:
            return int(row[0])

        return 1

    finally:

        cur.close()
        db.close()


# ============================================================
# GET COMPANY BY ID
# ============================================================

def get_company_by_id(comp_id: int):

    db = get_company_db()

    cur = db.cursor(dictionary=True)

    try:

        cur.execute(
            """
            SELECT
                comp_id,
                comp_name,
                short_name,
                comp_pn_no,
                comp_email_id,
                created_by,
                created_dt,
                modified_by,
                modified_dt,
                comp_add,
                pan_no,
                gst_no,
                cin,
                mfms,
                acc_cd,
                adv_acc,
                tds_acc,
                bank_name,
                bnk_branch_name,
                ac_no,
                ifsc
            FROM mm_company_dtls
            WHERE comp_id = %s
            """,
            (comp_id,),
        )

        return cur.fetchone()

    finally:

        cur.close()
        db.close()


# ============================================================
# FLASH MESSAGE HELPER
# ============================================================

def set_flash(request: Request, message: str):

    request.session["company_flash"] = message


def get_flash(request: Request):

    message = request.session.pop(
        "company_flash",
        None
    )

    return message


# ============================================================
# COMPANY LIST
# ============================================================

@router.get(
    "",
    response_class=HTMLResponse
)
@router.get(
    "/",
    response_class=HTMLResponse
)
def company_list(
    request: Request,
    q: str = Query(
        default="",
        max_length=150
    )
):

    db = get_company_db()

    cur = db.cursor(dictionary=True)

    try:

        if q.strip():

            search_text = q.strip()

            like_value = f"%{search_text}%"

            cur.execute(
                """
                SELECT
                    comp_id,
                    comp_name,
                    gst_no,
                    short_name
                FROM mm_company_dtls
                WHERE
                    comp_name LIKE %s
                    OR short_name LIKE %s
                    OR gst_no LIKE %s
                    OR pan_no LIKE %s
                    OR CAST(comp_id AS CHAR) LIKE %s
                ORDER BY comp_id
                """,
                (
                    like_value,
                    like_value,
                    like_value,
                    like_value,
                    like_value,
                )
            )

        else:

            cur.execute(
                """
                SELECT
                    comp_id,
                    comp_name,
                    gst_no,
                    short_name
                FROM mm_company_dtls
                ORDER BY comp_id
                """
            )

        companies = cur.fetchall()

    finally:

        cur.close()
        db.close()


    flash_message = get_flash(request)


    return templates.TemplateResponse(
        request=request,
        name="masters/company_list.html",
        context={
            "request": request,
            "companies": companies,
            "q": q,
            "flash_message": flash_message,
        }
    )


# ============================================================
# ADD COMPANY - PAGE
# ============================================================

@router.get(
    "/add",
    response_class=HTMLResponse
)
def company_add_page(request: Request):

    next_id = get_next_company_id()

    return templates.TemplateResponse(
        request=request,
        name="masters/company_form.html",
        context={
            "request": request,
            "mode": "add",
            "company": {},
            "next_id": next_id,
        }
    )


# ============================================================
# ADD COMPANY - SAVE
# ============================================================

@router.post("/add")
def company_add(
    request: Request,

    comp_name: str = Form(...),

    short_name: str = Form(""),

    comp_pn_no: str = Form(""),

    comp_email_id: str = Form(""),

    comp_add: str = Form(""),

    pan_no: str = Form(""),

    gst_no: str = Form(""),

    cin: str = Form(""),

    mfms: str = Form(""),

    acc_cd: str = Form(""),

    adv_acc: str = Form(""),

    tds_acc: str = Form(""),

    bank_name: str = Form(""),

    bnk_branch_name: str = Form(""),

    ac_no: str = Form(""),

    ifsc: str = Form(""),
):

    # --------------------------------------------------------
    # Required field validation
    # --------------------------------------------------------

    comp_name = comp_name.strip()

    if not comp_name:

        set_flash(
            request,
            "Company Name is required."
        )

        return RedirectResponse(
            url="/company/add",
            status_code=303
        )


    # --------------------------------------------------------
    # Logged in user
    # --------------------------------------------------------

    created_by = request.session.get(
        "username",
        "admin"
    )


    # --------------------------------------------------------
    # Database
    # --------------------------------------------------------

    db = get_company_db()

    cur = db.cursor()

    try:

        # Generate next company code

        cur.execute(
            """
            SELECT COALESCE(MAX(comp_id), 0) + 1
            FROM mm_company_dtls
            """
        )

        row = cur.fetchone()

        comp_id = int(
            row[0] if row and row[0] else 1
        )


        # ----------------------------------------------------
        # INSERT
        # ----------------------------------------------------

        sql = """
            INSERT INTO mm_company_dtls
            (
                comp_id,
                comp_name,
                short_name,
                comp_pn_no,
                comp_email_id,
                comp_add,
                pan_no,
                gst_no,
                cin,
                mfms,
                acc_cd,
                adv_acc,
                tds_acc,
                bank_name,
                bnk_branch_name,
                ac_no,
                ifsc,
                created_by,
                created_dt
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
            comp_id,

            comp_name,

            short_name.strip(),

            comp_pn_no.strip(),

            comp_email_id.strip(),

            comp_add.strip(),

            pan_no.strip(),

            gst_no.strip(),

            cin.strip(),

            mfms.strip(),

            acc_cd.strip(),

            adv_acc.strip(),

            tds_acc.strip(),

            bank_name.strip(),

            bnk_branch_name.strip(),

            ac_no.strip(),

            ifsc.strip(),

            created_by,

            datetime.now(),
        )


        cur.execute(
            sql,
            values
        )

        db.commit()


    except Exception as e:

        db.rollback()

        print(
            "Company add error:",
            e
        )

        set_flash(
            request,
            f"Unable to add company: {e}"
        )

        return RedirectResponse(
            url="/company/add",
            status_code=303
        )


    finally:

        cur.close()
        db.close()


    set_flash(
        request,
        "Successfully Added"
    )


    return RedirectResponse(
        url="/company",
        status_code=303
    )


# ============================================================
# EDIT COMPANY - PAGE
# ============================================================

@router.get(
    "/edit/{comp_id}",
    response_class=HTMLResponse
)
def company_edit_page(
    request: Request,
    comp_id: int
):

    company = get_company_by_id(
        comp_id
    )


    if not company:

        set_flash(
            request,
            "Company not found."
        )

        return RedirectResponse(
            url="/company",
            status_code=303
        )


    return templates.TemplateResponse(
        request=request,
        name="masters/company_form.html",
        context={
            "request": request,
            "mode": "edit",
            "company": company,
            "next_id": comp_id,
        }
    )


# ============================================================
# EDIT COMPANY - UPDATE
# ============================================================

@router.post(
    "/edit/{comp_id}"
)
def company_edit(
    request: Request,

    comp_id: int,

    comp_name: str = Form(...),

    short_name: str = Form(""),

    comp_pn_no: str = Form(""),

    comp_email_id: str = Form(""),

    comp_add: str = Form(""),

    pan_no: str = Form(""),

    gst_no: str = Form(""),

    cin: str = Form(""),

    mfms: str = Form(""),

    acc_cd: str = Form(""),

    adv_acc: str = Form(""),

    tds_acc: str = Form(""),

    bank_name: str = Form(""),

    bnk_branch_name: str = Form(""),

    ac_no: str = Form(""),

    ifsc: str = Form(""),
):

    # --------------------------------------------------------
    # Validation
    # --------------------------------------------------------

    comp_name = comp_name.strip()

    if not comp_name:

        set_flash(
            request,
            "Company Name is required."
        )

        return RedirectResponse(
            url=f"/company/edit/{comp_id}",
            status_code=303
        )


    # --------------------------------------------------------
    # Logged user
    # --------------------------------------------------------

    modified_by = request.session.get(
        "username",
        "admin"
    )


    # --------------------------------------------------------
    # Database
    # --------------------------------------------------------

    db = get_company_db()

    cur = db.cursor()

    try:

        # ----------------------------------------------------
        # UPDATE
        # ----------------------------------------------------

        sql = """
            UPDATE mm_company_dtls
            SET

                comp_name = %s,

                short_name = %s,

                comp_pn_no = %s,

                comp_email_id = %s,

                comp_add = %s,

                pan_no = %s,

                gst_no = %s,

                cin = %s,

                mfms = %s,

                acc_cd = %s,

                adv_acc = %s,

                tds_acc = %s,

                bank_name = %s,

                bnk_branch_name = %s,

                ac_no = %s,

                ifsc = %s,

                modified_by = %s,

                modified_dt = %s

            WHERE comp_id = %s
        """


        values = (

            comp_name,

            short_name.strip(),

            comp_pn_no.strip(),

            comp_email_id.strip(),

            comp_add.strip(),

            pan_no.strip(),

            gst_no.strip(),

            cin.strip(),

            mfms.strip(),

            acc_cd.strip(),

            adv_acc.strip(),

            tds_acc.strip(),

            bank_name.strip(),

            bnk_branch_name.strip(),

            ac_no.strip(),

            ifsc.strip(),

            modified_by,

            datetime.now(),

            comp_id,
        )


        cur.execute(
            sql,
            values
        )

        db.commit()


        # ----------------------------------------------------
        # Check if company exists
        # ----------------------------------------------------

        if cur.rowcount == 0:

            set_flash(
                request,
                "No changes made or Company not found."
            )

        else:

            set_flash(
                request,
                "Successfully Updated"
            )


    except Exception as e:

        db.rollback()

        print(
            "Company update error:",
            e
        )

        set_flash(
            request,
            f"Unable to update company: {e}"
        )


    finally:

        cur.close()
        db.close()


    return RedirectResponse(
        url="/company",
        status_code=303
    )


# ============================================================
# OPTIONAL: COMPANY DETAILS API
# Useful later for Sale/Purchase reports
# ============================================================

@router.get(
    "/api/{comp_id}"
)
def company_api(
    comp_id: int
):

    company = get_company_by_id(
        comp_id
    )

    if not company:

        return {
            "success": False,
            "message": "Company not found",
        }


    return {
        "success": True,
        "data": company,
    }


# ============================================================
# OPTIONAL: COMPANY LIST JSON API
# Useful later for dropdowns/reports
# ============================================================

@router.get(
    "/api/list/all"
)
def company_api_list():

    db = get_company_db()

    cur = db.cursor(
        dictionary=True
    )

    try:

        cur.execute(
            """
            SELECT
                comp_id,
                comp_name,
                short_name,
                gst_no
            FROM mm_company_dtls
            ORDER BY comp_id
            """
        )

        rows = cur.fetchall()

        return {
            "success": True,
            "data": rows,
        }

    finally:

        cur.close()
        db.close()


# ============================================================
# MODULE SETUP
# ============================================================

def setup_company_master():

    ensure_company_table()