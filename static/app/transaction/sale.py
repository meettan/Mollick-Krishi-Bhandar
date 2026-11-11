from pathlib import Path
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import List

import mysql.connector
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from ..sidebar_context import sidebar_context

BASE_DIR = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"), context_processors=[sidebar_context])

router = APIRouter(prefix="/sale", tags=["Sale"])

LOGIN_DB = {"host": "localhost", "user": "root", "password": "", "database": "python_login"}
FERTILIZER_DB = {"host": "localhost", "user": "root", "password": "", "database": "benfed_fertilizer"}


def login_db():
    return mysql.connector.connect(**LOGIN_DB)


def fertilizer_db():
    return mysql.connector.connect(**FERTILIZER_DB)


def dec(v, default=Decimal("0.00")):
    try:
        if v is None or str(v).strip() == "":
            return default
        return Decimal(str(v).strip())
    except (InvalidOperation, ValueError, TypeError):
        return default


def as_float(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def ensure_sales_table():
    conn = cur = None
    try:
        conn = login_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                sale_invoice_no VARCHAR(50) NOT NULL,
                sale_date DATE NOT NULL,
                ro VARCHAR(100) NOT NULL,
                customer_id INT NOT NULL,
                sales_person_id INT NOT NULL,
                product_id INT NOT NULL,
                batch_id INT NOT NULL,
                qty DECIMAL(12,3) NOT NULL DEFAULT 0.000,
                selling_price DECIMAL(12,2) NOT NULL DEFAULT 0.00,
                discount DECIMAL(12,2) NOT NULL DEFAULT 0.00,
                gst_rate DECIMAL(5,2) NOT NULL DEFAULT 0.00,
                gst_amount DECIMAL(12,2) NOT NULL DEFAULT 0.00,
                line_total DECIMAL(12,2) NOT NULL DEFAULT 0.00,
                gross_amount DECIMAL(12,2) NOT NULL DEFAULT 0.00,
                net_amount DECIMAL(12,2) NOT NULL DEFAULT 0.00,
                received_amount DECIMAL(12,2) NOT NULL DEFAULT 0.00,
                outstanding_amount DECIMAL(12,2) NOT NULL DEFAULT 0.00,
                credit_days INT NOT NULL DEFAULT 0,
                due_date DATE DEFAULT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
                created_by INT DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (sale_invoice_no, ro, product_id, batch_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        # Existing installations may have the old primary key without RO.
        try:
            cur.execute("ALTER TABLE sales DROP PRIMARY KEY, ADD PRIMARY KEY (sale_invoice_no, ro, product_id, batch_id)")
        except Exception:
            conn.rollback()
        conn.commit()
    finally:
        if cur: cur.close()
        if conn: conn.close()


def get_ros():
    conn = cur = None
    try:
        conn = login_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT TRIM(ro_no) AS ro_no
            FROM purchase_master
            WHERE ro_no IS NOT NULL AND TRIM(ro_no) <> ''
            ORDER BY TRIM(ro_no)
        """)
        return [str(r[0]).strip() for r in cur.fetchall() if r[0] is not None and str(r[0]).strip()]
    finally:
        if cur: cur.close()
        if conn: conn.close()


def get_customers():
    conn = cur = None
    try:
        conn = login_db(); cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, customer_code, customer_name FROM customers WHERE status=1 ORDER BY customer_name")
        return cur.fetchall()
    finally:
        if cur: cur.close()
        if conn: conn.close()


def get_sales_persons():
    conn = cur = None
    try:
        conn = login_db(); cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, employee_code, name FROM sales_persons WHERE status=1 ORDER BY name")
        return cur.fetchall()
    finally:
        if cur: cur.close()
        if conn: conn.close()


def get_products_for_ro(ro: str):
    """Get products ONLY through RO -> purchase_master -> purchase_details.

    Data relationship:
      purchase_master.ro_no = selected RO
      purchase_master.id = purchase_details.purchase_id
      purchase_details.product_id = mm_product.PROD_ID

    mm_product is used only to get the product description/master data.
    It is NEVER used as the source of the Sale product list by itself.
    """
    ro = (ro or "").strip()
    if not ro:
        return []

    conn = cur = None
    try:
        conn = login_db()
        cur = conn.cursor(dictionary=True)

        # IMPORTANT: Start from purchase_master and purchase_details.
        # Therefore a product can be returned only when that product_id
        # was actually present in a purchase belonging to this RO.
        cur.execute("""
            SELECT
                TRIM(pm.ro_no) AS ro_no,
                pd.product_id AS id,
                COALESCE(pr.PROD_DESC, CONCAT('Product ', pd.product_id)) AS name,
                COALESCE(pr.GST_RT, MAX(pd.gst_rate), 0) AS gst_rate,
                COALESCE(pr.HSN_CODE, '') AS hsn_code,
                COALESCE(pr.unit, '') AS unit,
                COALESCE(pd.batch_id, 0) AS batch_id,
                COALESCE(SUM(pd.qty), 0) AS purchased_qty,
                MAX(COALESCE(pd.unit_price, 0)) AS purchase_price
            FROM purchase_master pm
            INNER JOIN purchase_details pd
                ON pm.id = pd.purchase_id
            INNER JOIN benfed_fertilizer.mm_product pr
                ON pr.PROD_ID = pd.product_id
            WHERE TRIM(pm.ro_no) = TRIM(%s)
            GROUP BY
                TRIM(pm.ro_no),
                pd.product_id,
                pr.PROD_DESC,
                pr.GST_RT,
                pr.HSN_CODE,
                pr.unit,
                pd.batch_id
            ORDER BY pr.PROD_DESC, pd.product_id, pd.batch_id
        """, (ro,))

        rows = cur.fetchall()
        result = []
        for r in rows:
            result.append({
                "ro_no": str(r.get("ro_no") or "").strip(),
                "id": int(r.get("id") or 0),
                "name": str(r.get("name") or "").strip(),
                "gst_rate": as_float(r.get("gst_rate")),
                "hsn_code": str(r.get("hsn_code") or ""),
                "unit": str(r.get("unit") or ""),
                "batch_id": int(r.get("batch_id") or 0),
                "purchased_qty": as_float(r.get("purchased_qty")),
                "purchase_price": as_float(r.get("purchase_price")),
            })
        return result
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def context(request):
    return {
        'request': request,
        'ros': get_ros(),
        'customers': get_customers(),
        'sales_persons': get_sales_persons(),
        'sale_date': date.today().isoformat(),
    }


@router.on_event("startup")
def startup_sale_table():
    ensure_sales_table()


@router.get("/", response_class=HTMLResponse)
async def sale_page(request: Request):
    try:
        ensure_sales_table()
        return templates.TemplateResponse(request=request, name="sale.html", context=context(request))
    except Exception as e:
        print("SALE PAGE ERROR:", repr(e))
        return JSONResponse(status_code=500, content={'success': False, 'message': str(e)})


@router.get("/invoices", response_class=HTMLResponse)
async def sale_invoice_list(request: Request, saved: str = ""):
    """List saved sales invoices, one row per invoice."""
    conn = cur = None
    try:
        ensure_sales_table()
        conn = login_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT
                s.sale_invoice_no,
                MIN(s.sale_date) AS sale_date,
                MIN(s.customer_id) AS customer_id,
                COALESCE(MAX(c.customer_code), '') AS customer_code,
                COALESCE(MAX(c.customer_name), '') AS customer_name,
                MIN(s.sales_person_id) AS sales_person_id,
                COALESCE(MAX(sp.employee_code), '') AS sales_person_code,
                COALESCE(MAX(sp.name), '') AS sales_person_name,
                MAX(s.gross_amount) AS gross_amount,
                MAX(s.received_amount) AS received_amount,
                MAX(s.outstanding_amount) AS outstanding_amount,
                MAX(s.net_amount) AS net_amount,
                MAX(s.status) AS status,
                COUNT(*) AS line_count
            FROM sales s
            LEFT JOIN customers c ON c.id = s.customer_id
            LEFT JOIN sales_persons sp ON sp.id = s.sales_person_id
            GROUP BY s.sale_invoice_no
            ORDER BY MIN(s.sale_date) DESC, s.sale_invoice_no DESC
        """)
        invoices = cur.fetchall()
        return templates.TemplateResponse(
            request=request,
            name="sale_invoices.html",
            context={"request": request, "invoices": invoices, "saved": saved}
        )
    except Exception as e:
        print("SALE INVOICE LIST ERROR:", repr(e))
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})
    finally:
        if cur: cur.close()
        if conn: conn.close()


@router.get("/invoices/{invoice_no}", response_class=HTMLResponse)
async def sale_invoice_detail(request: Request, invoice_no: str):
    """Show all lines belonging to one saved sales invoice."""
    conn = cur = None
    try:
        conn = login_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT
                s.*,
                COALESCE(c.customer_code, '') AS customer_code,
                COALESCE(c.customer_name, '') AS customer_name,
                COALESCE(sp.employee_code, '') AS sales_person_code,
                COALESCE(sp.name, '') AS sales_person_name,
                COALESCE(pr.PROD_DESC, CONCAT('Product ', s.product_id)) AS product_name
            FROM sales s
            LEFT JOIN customers c ON c.id = s.customer_id
            LEFT JOIN sales_persons sp ON sp.id = s.sales_person_id
            LEFT JOIN benfed_fertilizer.mm_product pr ON pr.PROD_ID = s.product_id
            WHERE s.sale_invoice_no = %s
            ORDER BY s.ro, s.product_id, s.batch_id
        """, (invoice_no,))
        lines = cur.fetchall()
        if not lines:
            return RedirectResponse('/sale/invoices', status_code=303)
        return templates.TemplateResponse(
            request=request,
            name="sale_invoice_detail.html",
            context={"request": request, "invoice_no": invoice_no, "lines": lines}
        )
    except Exception as e:
        print("SALE INVOICE DETAIL ERROR:", repr(e))
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})
    finally:
        if cur: cur.close()
        if conn: conn.close()


def _number_to_words_indian(number):
    """Convert a non-negative integer to English words using Indian grouping."""
    number = int(number)
    if number == 0:
        return "Zero"

    ones = [
        "Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven",
        "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen",
        "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"
    ]
    tens = [
        "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy",
        "Eighty", "Ninety"
    ]

    def under_thousand(value):
        parts = []
        if value >= 100:
            parts.append(ones[value // 100] + " Hundred")
            value %= 100
        if value >= 20:
            parts.append(tens[value // 10])
            if value % 10:
                parts.append(ones[value % 10])
        elif value > 0:
            parts.append(ones[value])
        return " ".join(parts)

    groups = [
        (10000000, "Crore"),
        (100000, "Lakh"),
        (1000, "Thousand"),
        (1, "")
    ]
    parts = []
    remaining = number
    for divisor, label in groups:
        group_value = remaining // divisor
        remaining %= divisor
        if group_value:
            words = under_thousand(group_value)
            parts.append((words + (" " + label if label else "")).strip())
    return " ".join(parts)


def amount_in_words(amount):
    """Format a currency amount as Indian Rupees and Paise in English."""
    value = Decimal(str(amount or 0)).quantize(Decimal("0.01"))
    if value < 0:
        return "Minus " + amount_in_words(abs(value))

    rupees = int(value)
    paise = int((value - Decimal(rupees)) * 100)

    result = "Rupees " + _number_to_words_indian(rupees)
    if paise:
        result += " and " + _number_to_words_indian(paise) + " Paise"
    return result + " Only"


@router.get("/invoices/{invoice_no}/print", response_class=HTMLResponse, name="sale_invoice_print")
async def sale_invoice_print(request: Request, invoice_no: str):
    """Commercial/A4 print view for a saved sales invoice."""
    conn = cur = None
    try:
        conn = login_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT
                s.*,
                COALESCE(c.customer_code, '') AS customer_code,
                COALESCE(c.customer_name, '') AS customer_name,
                COALESCE(sp.employee_code, '') AS sales_person_code,
                COALESCE(sp.name, '') AS sales_person_name,
                COALESCE(pr.PROD_DESC, CONCAT('Product ', s.product_id)) AS product_name,
                COALESCE(pr.HSN_CODE, '') AS hsn_code,
                COALESCE(pr.unit, '') AS product_unit
            FROM sales s
            LEFT JOIN customers c ON c.id = s.customer_id
            LEFT JOIN sales_persons sp ON sp.id = s.sales_person_id
            LEFT JOIN benfed_fertilizer.mm_product pr ON pr.PROD_ID = s.product_id
            WHERE s.sale_invoice_no = %s
            ORDER BY s.ro, s.product_id, s.batch_id
        """, (invoice_no,))
        lines = cur.fetchall()
        if not lines:
            return RedirectResponse('/sale/invoices', status_code=303)

        cur.execute("""
            SELECT comp_id, comp_name, short_name, comp_add, comp_pn_no,
                   comp_email_id, pan_no, gst_no, cin, bank_name,
                   bnk_branch_name, ac_no, ifsc
            FROM mm_company_dtls
            ORDER BY comp_id
            LIMIT 1
        """)
        company = cur.fetchone() or {
            'comp_name': 'BENFED', 'short_name': '', 'comp_add': '',
            'comp_pn_no': '', 'comp_email_id': '', 'pan_no': '',
            'gst_no': '', 'cin': '', 'bank_name': '',
            'bnk_branch_name': '', 'ac_no': '', 'ifsc': ''
        }

        gross = sum((Decimal(str(x.get('gross_amount') or 0)) for x in lines), Decimal('0'))
        discount = sum((Decimal(str(x.get('discount') or 0)) for x in lines), Decimal('0'))
        gst = sum((Decimal(str(x.get('gst_amount') or 0)) for x in lines), Decimal('0'))
        net = sum((Decimal(str(x.get('line_total') or 0)) for x in lines), Decimal('0'))
        return templates.TemplateResponse(
            request=request,
            name='sale_invoice_print.html',
            context={
                'request': request,
                'invoice_no': invoice_no,
                'lines': lines,
                'company': company,
                'gross': gross,
                'discount': discount,
                'gst': gst,
                'net': net,
                'total_amount_words': amount_in_words(net),
                'received': Decimal(str(lines[0].get('received_amount') or 0)),
                'outstanding': Decimal(str(lines[0].get('outstanding_amount') or 0)),
            }
        )
    except Exception as e:
        print('SALE INVOICE PRINT ERROR:', repr(e))
        return JSONResponse(status_code=500, content={'success': False, 'message': str(e)})
    finally:
        if cur: cur.close()
        if conn: conn.close()


# Compatibility print URL. This also supports installations/bookmarks that use
# /sale/print/<invoice_no> instead of /sale/invoices/<invoice_no>/print.
@router.get("/print/{invoice_no}", response_class=HTMLResponse, name="sale_invoice_print_compat")
async def sale_invoice_print_compat(request: Request, invoice_no: str):
    return await sale_invoice_print(request, invoice_no)


@router.get("/api/products", response_class=JSONResponse)
async def sale_products(ro: str = Query("")):
    try:
        ro = ro.strip()
        if not ro:
            return {'success': True, 'products': []}
        rows = get_products_for_ro(ro)
        return JSONResponse(content={'success': True, 'products': rows}, headers={'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0'})
    except Exception as e:
        print('SALE PRODUCTS ERROR:', repr(e))
        return JSONResponse(status_code=500, content={'success': False, 'message': str(e)})


@router.post("/save")
async def sale_save(
    request: Request,
    sale_date: str = Form(""),
    customer_id: int = Form(0),
    sales_person_id: int = Form(0),
    credit_days: int = Form(0),
    status: str = Form("POSTED"),
    ro: List[str] = Form([]),
    product_id: List[int] = Form([]),
    batch_id: List[int] = Form([]),
    qty: List[str] = Form([]),
    selling_price: List[str] = Form([]),
    discount: List[str] = Form([]),
    gst_rate: List[str] = Form([]),
):
    conn = cur = None
    try:
        ensure_sales_table()
        if customer_id <= 0:
            return JSONResponse(status_code=400, content={'success':False,'message':'Customer is required.'})
        if sales_person_id <= 0:
            return JSONResponse(status_code=400, content={'success':False,'message':'Sales Person is required.'})
        if not product_id:
            return JSONResponse(status_code=400, content={'success':False,'message':'Add at least one product.'})
        if not (len(ro) == len(product_id) == len(batch_id)):
            return JSONResponse(status_code=400, content={'success':False,'message':'Sale product rows are incomplete.'})

        sale_date_obj = datetime.strptime(sale_date, '%Y-%m-%d').date() if sale_date else date.today()
        received = Decimal('0')
        credit_days = max(int(credit_days or 0), 0)
        due_date = sale_date_obj + timedelta(days=credit_days)

        lines = []
        gross = discount_total = gst_total = net = Decimal('0')
        seen = set()

        # Validate EVERY row against purchase_master + purchase_details for that row's RO.
        for i, pid_raw in enumerate(product_id):
            row_ro = str(ro[i] if i < len(ro) else '').strip()
            pid = int(pid_raw)
            batch = int(batch_id[i] or 0)
            if not row_ro:
                return JSONResponse(status_code=400, content={'success':False,'message':f'RO is required for product row {i+1}.'})
            if pid <= 0:
                return JSONResponse(status_code=400, content={'success':False,'message':f'Product is required for row {i+1}.'})

            conn_check = login_db(); cur_check = conn_check.cursor()
            try:
                cur_check.execute("""
                    SELECT COALESCE(SUM(pd.qty),0), MAX(COALESCE(pd.gst_rate,0)), MAX(COALESCE(pd.unit_price,0))
                    FROM purchase_master pm
                    INNER JOIN purchase_details pd ON pd.purchase_id = pm.id
                    WHERE TRIM(pm.ro_no)=TRIM(%s)
                      AND pd.product_id=%s
                      AND COALESCE(pd.batch_id,0)=%s
                """, (row_ro, pid, batch))
                purchased = cur_check.fetchone()
            finally:
                cur_check.close(); conn_check.close()

            if not purchased or purchased[0] is None or Decimal(str(purchased[0] or 0)) <= 0:
                return JSONResponse(status_code=400, content={'success':False,'message':f'Product {pid} / Batch {batch} was not purchased under RO {row_ro}.'})

            key = (row_ro, pid, batch)
            if key in seen:
                return JSONResponse(status_code=400, content={'success':False,'message':'The same RO + Product + Batch cannot be added twice.'})
            seen.add(key)

            q = dec(qty[i] if i < len(qty) else 0)
            price = dec(selling_price[i] if i < len(selling_price) else 0)
            disc = dec(discount[i] if i < len(discount) else 0)
            gst = dec(gst_rate[i] if i < len(gst_rate) and str(gst_rate[i]).strip() else (purchased[1] or 0))
            if q <= 0:
                return JSONResponse(status_code=400, content={'success':False,'message':f'Quantity must be greater than zero for product {pid}.'})
            if price < 0 or disc < 0:
                return JSONResponse(status_code=400, content={'success':False,'message':'Price and discount cannot be negative.'})

            line_gross = q * price
            taxable = max(line_gross - disc, Decimal('0'))
            line_gst = taxable * gst / Decimal('100')
            line_total = taxable + line_gst
            gross += line_gross; discount_total += disc; gst_total += line_gst; net += line_total
            lines.append((row_ro, pid, batch, q, price, disc, gst, line_gst, line_total))

        outstanding = net
        conn = login_db(); cur = conn.cursor()
        cur.execute("SELECT sale_invoice_no FROM sales WHERE sale_invoice_no LIKE %s ORDER BY sale_invoice_no DESC LIMIT 1", ('SAL-' + sale_date_obj.strftime('%Y%m%d') + '-%',))
        last = cur.fetchone()
        seq = 1
        if last and last[0].rsplit('-',1)[-1].isdigit():
            seq = int(last[0].rsplit('-',1)[-1]) + 1
        invoice = f"SAL-{sale_date_obj.strftime('%Y%m%d')}-{seq:03d}"
        status = (status or 'POSTED').upper()

        sql = """INSERT INTO sales
            (sale_invoice_no,sale_date,ro,customer_id,sales_person_id,product_id,batch_id,qty,selling_price,discount,gst_rate,gst_amount,line_total,gross_amount,net_amount,received_amount,outstanding_amount,credit_days,due_date,status,created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        user_id = request.session.get('user_id')
        for row_ro,pid,batch,q,price,disc,gst,line_gst,line_total in lines:
            cur.execute(sql, (invoice,sale_date_obj,row_ro,customer_id,sales_person_id,pid,batch,q,price,disc,gst,line_gst,line_total,gross,net,received,outstanding,credit_days,due_date,status,user_id))
        conn.commit()
        return RedirectResponse('/sale/invoices?saved=' + invoice, status_code=303)
    except Exception as e:
        if conn: conn.rollback()
        print('SALE SAVE ERROR:', repr(e))
        return JSONResponse(status_code=500, content={'success':False,'message':str(e)})
    finally:
        if cur: cur.close()
        if conn: conn.close()
