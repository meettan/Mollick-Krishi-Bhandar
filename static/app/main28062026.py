from pathlib import Path

import mysql.connector

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware


# ============================================================
# LOCAL APP IMPORTS
# ============================================================

from .config import SECRET_KEY, APP_HOST, APP_PORT

from .database import (
    ensure_login_database,
    authenticate_user,
    get_connection,
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


# ============================================================
# PURCHASE TRANSACTION
# ============================================================

from .transaction.purchase import (
    router as purchase_router,
    ensure_purchase_table,
)


# ============================================================
# BASE PATH
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="BENFED Management Portal",
    description="BENFED Fertilizer Management System",
    version="1.0.0",
)


# ============================================================
# SESSION
# ============================================================

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

templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR)
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

app.include_router(
    purchase_router
)


# ============================================================
# APPLICATION STARTUP
# ============================================================

@app.on_event("startup")
def startup():

    # --------------------------------------------------------
    # Login database
    # --------------------------------------------------------

    try:

        ensure_login_database()

        print(
            "Login database initialization: OK"
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


# ============================================================
# DASHBOARD STATISTICS
# ============================================================

def get_dashboard_stats():

    stats = {
        "companies": None,
        "products": None,
        "districts": None,
        "users": None,
    }


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
    # BENFED FERTILIZER DATABASE
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


        # ----------------------------------------------------
        # District count
        # ----------------------------------------------------

        try:

            cur.execute(
                """
                SELECT COUNT(*)
                FROM md_district
                """
            )

            row = cur.fetchone()

            if row:
                stats["districts"] = row[0]

        except Exception as e:

            print(
                "District count error:",
                e
            )


        cur.close()
        db.close()

    except Exception as e:

        print(
            "BENFED fertilizer database error:",
            e
        )


    return stats


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

            "stats": stats,
        },
    )


# ============================================================
# LOGOUT
# ============================================================

@app.get("/logout")
def logout(
    request: Request
):

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
        "application": "BENFED",
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