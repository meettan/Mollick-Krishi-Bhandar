from datetime import datetime
from pathlib import Path

import mysql.connector
from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = PROJECT_ROOT / "templates"
from ..sidebar_context import sidebar_context


templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR),
    context_processors=[sidebar_context],
)

router = APIRouter(prefix="/product", tags=["Product Master"])

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "python_login",
}

UNIT_OPTIONS = [
    {"value": 0, "label": "Pack"},
    {"value": 1, "label": "MTS"},
    {"value": 2, "label": "KGS"},
    {"value": 3, "label": "LTR"},
    {"value": 4, "label": "QTL"},
    {"value": 5, "label": "MLT"},
    {"value": 6, "label": "GMS"},
    {"value": 7, "label": "PCS"},
]

STORAGE_OPTIONS = [
    {"value": "B", "label": "B - Bag"},
    {"value": "T", "label": "T - Ton"},
    {"value": "P", "label": "P - Piece"},
]

STATE_OPTIONS = [
    {"value": 1, "label": "Active"},
    {"value": 0, "label": "Inactive"},
]


def get_db():
    return mysql.connector.connect(**DB_CONFIG)


def set_flash(request: Request, message: str, message_type: str = "success"):
    request.session["product_flash"] = {
        "message": message,
        "type": message_type,
    }


def pop_flash(request: Request):
    return request.session.pop("product_flash", None)


def to_int(value):
    value = "" if value is None else str(value).strip()
    return int(value) if value else None


def to_float(value):
    value = "" if value is None else str(value).strip()
    return float(value) if value else None


def get_next_product_id():
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("SELECT COALESCE(MAX(PROD_ID), 0) + 1 FROM mm_product")
        row = cur.fetchone()
        return int(row[0] if row and row[0] is not None else 1)
    finally:
        cur.close()
        db.close()


def get_companies():
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT COMP_ID AS comp_id,
                   COMP_NAME AS comp_name,
                   short_name
            FROM mm_company_dtls
            ORDER BY COMP_NAME
            """
        )
        return cur.fetchall()
    finally:
        cur.close()
        db.close()


def get_product(prod_id: int):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT PROD_ID, PROD_DESC, COMPANY, PROD_TYPE, mat_state,
                   CREATED_BY, CREATED_DT, MODIFIED_BY, MODIFIED_DT,
                   COMMODITY_ID, GST_RT, HSN_CODE, QTY_PER_BAG, unit, storage
            FROM mm_product
            WHERE PROD_ID = %s
            """,
            (prod_id,),
        )
        return cur.fetchone()
    finally:
        cur.close()
        db.close()


def setup_product_master():
    return True


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def product_list(request: Request, q: str = Query(default="", max_length=150)):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        q = q.strip()
        if q:
            like = f"%{q}%"
            cur.execute(
                """
                SELECT p.PROD_ID,
                       p.PROD_DESC,
                       p.COMPANY,
                       p.PROD_TYPE,
                       p.mat_state,
                       p.GST_RT,
                       p.HSN_CODE,
                       p.QTY_PER_BAG,
                       p.unit,
                       p.storage,
                       c.COMP_NAME AS comp_name
                FROM mm_product p
                LEFT JOIN mm_company_dtls c ON c.COMP_ID = p.COMPANY
                WHERE CAST(p.PROD_ID AS CHAR) LIKE %s
                   OR p.PROD_DESC LIKE %s
                   OR p.PROD_TYPE LIKE %s
                   OR CAST(p.HSN_CODE AS CHAR) LIKE %s
                   OR c.COMP_NAME LIKE %s
                ORDER BY p.PROD_ID DESC
                """,
                (like, like, like, like, like),
            )
        else:
            cur.execute(
                """
                SELECT p.PROD_ID,
                       p.PROD_DESC,
                       p.COMPANY,
                       p.PROD_TYPE,
                       p.mat_state,
                       p.GST_RT,
                       p.HSN_CODE,
                       p.QTY_PER_BAG,
                       p.unit,
                       p.storage,
                       c.COMP_NAME AS comp_name
                FROM mm_product p
                LEFT JOIN mm_company_dtls c ON c.COMP_ID = p.COMPANY
                ORDER BY p.PROD_ID DESC
                """
            )
        products = cur.fetchall()
    finally:
        cur.close()
        db.close()

    unit_map = {x["value"]: x["label"] for x in UNIT_OPTIONS}
    storage_map = {x["value"]: x["label"] for x in STORAGE_OPTIONS}

    for row in products:
        row["unit_label"] = unit_map.get(row.get("unit"), "—")
        row["storage_label"] = storage_map.get(row.get("storage"), "—")

    return templates.TemplateResponse(
        request=request,
        name="masters/product_list.html",
        context={
            "request": request,
            "products": products,
            "q": q,
            "flash": pop_flash(request),
        },
    )


@router.get("/add", response_class=HTMLResponse)
def add_product_page(request: Request):
    """Open the Add Product screen without throwing a raw 500 page."""
    product = {}
    companies = []
    next_id = ""
    page_error = None

    try:
        next_id = get_next_product_id()
    except Exception as exc:
        page_error = f"Product database error: {exc}"
        print("Product Add Page - ID error:", repr(exc))

    try:
        companies = get_companies()
    except Exception as exc:
        page_error = f"Company database error: {exc}"
        print("Product Add Page - Company error:", repr(exc))

    flash = pop_flash(request)
    if page_error and not flash:
        flash = {"message": page_error, "type": "error"}

    return templates.TemplateResponse(
        request=request,
        name="masters/product_form.html",
        context={
            "request": request,
            "mode": "add",
            "product": product,
            "next_id": next_id,
            "companies": companies,
            "unit_options": UNIT_OPTIONS,
            "storage_options": STORAGE_OPTIONS,
            "state_options": STATE_OPTIONS,
            "flash": flash,
        },
    )


@router.post("/add")
def add_product(
    request: Request,
    prod_desc: str = Form(...),
    company: str = Form(""),
    prod_type: str = Form(""),
    mat_state: str = Form("1"),
    commodity_id: str = Form(""),
    gst_rt: str = Form(""),
    hsn_code: str = Form(""),
    qty_per_bag: str = Form(""),
    unit: str = Form("0"),
    storage: str = Form("B"),
):
    prod_desc = (prod_desc or "").strip()

    if not prod_desc:
        set_flash(request, "Product Description is required.", "error")
        return RedirectResponse("/product/add", status_code=303)

    try:
        company_value = to_int(company)
        state_value = to_int(mat_state)
        commodity_value = to_int(commodity_id)
        gst_value = to_float(gst_rt)
        hsn_value = to_int(hsn_code)
        qty_value = to_int(qty_per_bag)
        unit_value = to_int(unit)
    except (TypeError, ValueError):
        set_flash(request, "Please enter valid numeric values.", "error")
        return RedirectResponse("/product/add", status_code=303)

    if company_value is None:
        set_flash(request, "Please select Company.", "error")
        return RedirectResponse("/product/add", status_code=303)

    if unit_value is None:
        set_flash(request, "Please select Unit.", "error")
        return RedirectResponse("/product/add", status_code=303)

    storage_value = (storage or "").strip()
    if storage_value not in {"B", "T", "P"}:
        set_flash(request, "Please select valid Storage.", "error")
        return RedirectResponse("/product/add", status_code=303)

    db = get_db()
    cur = db.cursor()
    created_by = request.session.get("username", "admin")

    try:
        cur.execute("SELECT COALESCE(MAX(PROD_ID), 0) + 1 FROM mm_product")
        row = cur.fetchone()
        prod_id = int(row[0] if row and row[0] is not None else 1)

        cur.execute(
            """
            INSERT INTO mm_product
            (
                PROD_ID, PROD_DESC, COMPANY, PROD_TYPE, mat_state,
                CREATED_BY, CREATED_DT, COMMODITY_ID, GST_RT,
                HSN_CODE, QTY_PER_BAG, unit, storage
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                prod_id,
                prod_desc,
                company_value,
                prod_type.strip() or None,
                state_value if state_value is not None else 1,
                created_by,
                datetime.now(),
                str(commodity_value) if commodity_value is not None else None,
                gst_value,
                hsn_value,
                qty_value,
                unit_value,
                storage_value,
            ),
        )
        db.commit()
        set_flash(request, "Successfully Added")
        return RedirectResponse("/product", status_code=303)
    except Exception as exc:
        db.rollback()
        print("Product Add Error:", repr(exc))
        set_flash(request, f"Unable to add product: {exc}", "error")
        return RedirectResponse("/product/add", status_code=303)
    finally:
        cur.close()
        db.close()


@router.get("/edit/{prod_id}", response_class=HTMLResponse)
def edit_product_page(request: Request, prod_id: int):
    product = get_product(prod_id)
    if not product:
        set_flash(request, "Product not found.", "error")
        return RedirectResponse("/product", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="masters/product_form.html",
        context={
            "request": request,
            "mode": "edit",
            "product": product,
            "next_id": prod_id,
            "companies": get_companies(),
            "unit_options": UNIT_OPTIONS,
            "storage_options": STORAGE_OPTIONS,
            "state_options": STATE_OPTIONS,
            "flash": pop_flash(request),
        },
    )


@router.post("/edit/{prod_id}")
def edit_product(
    request: Request,
    prod_id: int,
    prod_desc: str = Form(...),
    company: str = Form(""),
    prod_type: str = Form(""),
    mat_state: str = Form("1"),
    commodity_id: str = Form(""),
    gst_rt: str = Form(""),
    hsn_code: str = Form(""),
    qty_per_bag: str = Form(""),
    unit: str = Form("0"),
    storage: str = Form("B"),
):
    prod_desc = (prod_desc or "").strip()

    if not prod_desc:
        set_flash(request, "Product Description is required.", "error")
        return RedirectResponse(f"/product/edit/{prod_id}", status_code=303)

    try:
        company_value = to_int(company)
        state_value = to_int(mat_state)
        commodity_value = to_int(commodity_id)
        gst_value = to_float(gst_rt)
        hsn_value = to_int(hsn_code)
        qty_value = to_int(qty_per_bag)
        unit_value = to_int(unit)
    except (TypeError, ValueError):
        set_flash(request, "Please enter valid numeric values.", "error")
        return RedirectResponse(f"/product/edit/{prod_id}", status_code=303)

    if company_value is None or unit_value is None:
        set_flash(request, "Company and Unit are required.", "error")
        return RedirectResponse(f"/product/edit/{prod_id}", status_code=303)

    storage_value = (storage or "").strip()
    if storage_value not in {"B", "T", "P"}:
        set_flash(request, "Please select valid Storage.", "error")
        return RedirectResponse(f"/product/edit/{prod_id}", status_code=303)

    db = get_db()
    cur = db.cursor()
    modified_by = request.session.get("username", "admin")

    try:
        cur.execute(
            """
            UPDATE mm_product
            SET PROD_DESC=%s,
                COMPANY=%s,
                PROD_TYPE=%s,
                mat_state=%s,
                COMMODITY_ID=%s,
                GST_RT=%s,
                HSN_CODE=%s,
                QTY_PER_BAG=%s,
                unit=%s,
                storage=%s,
                MODIFIED_BY=%s,
                MODIFIED_DT=%s
            WHERE PROD_ID=%s
            """,
            (
                prod_desc,
                company_value,
                prod_type.strip() or None,
                state_value if state_value is not None else 1,
                str(commodity_value) if commodity_value is not None else None,
                gst_value,
                hsn_value,
                qty_value,
                unit_value,
                storage_value,
                modified_by,
                datetime.now(),
                prod_id,
            ),
        )
        db.commit()
        set_flash(request, "Successfully Updated")
        return RedirectResponse("/product", status_code=303)
    except Exception as exc:
        db.rollback()
        print("Product Update Error:", repr(exc))
        set_flash(request, f"Unable to update product: {exc}", "error")
        return RedirectResponse(f"/product/edit/{prod_id}", status_code=303)
    finally:
        cur.close()
        db.close()


@router.post("/delete/{prod_id}")
def delete_product(request: Request, prod_id: int):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("DELETE FROM mm_product WHERE PROD_ID=%s", (prod_id,))
        db.commit()
        if cur.rowcount:
            set_flash(request, "Successfully Deleted")
        else:
            set_flash(request, "Product not found.", "error")
    except Exception as exc:
        db.rollback()
        print("Product Delete Error:", repr(exc))
        set_flash(request, f"Unable to delete product: {exc}", "error")
    finally:
        cur.close()
        db.close()

    return RedirectResponse("/product", status_code=303)


@router.get("/api/list/all")
def product_list_api():
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT PROD_ID, PROD_DESC, COMPANY, PROD_TYPE,
                   mat_state, GST_RT, HSN_CODE, QTY_PER_BAG, unit, storage
            FROM mm_product
            ORDER BY PROD_ID
            """
        )
        rows = cur.fetchall()
        return {"success": True, "count": len(rows), "data": rows}
    finally:
        cur.close()
        db.close()


@router.get("/api/{prod_id}")
def product_api(prod_id: int):
    product = get_product(prod_id)
    return {"success": True, "data": product} if product else {
        "success": False,
        "message": "Product not found",
    }
