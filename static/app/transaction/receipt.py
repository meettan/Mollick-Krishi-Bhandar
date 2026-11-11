from pathlib import Path
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import mysql.connector
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from ..sidebar_context import sidebar_context

BASE_DIR = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(BASE_DIR / 'templates'), context_processors=[sidebar_context])
router = APIRouter(prefix='/receipts', tags=['Money Received'])
DB = {'host': 'localhost', 'user': 'root', 'password': '', 'database': 'python_login'}


def db():
    return mysql.connector.connect(**DB)


def dec(v):
    try:
        return Decimal(str(v or '0').strip())
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0')


def ensure_receipts_table():
    conn = cur = None
    try:
        conn = db()
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS customer_recoveries (
                id INT(11) NOT NULL AUTO_INCREMENT,
                recovery_no VARCHAR(100) NOT NULL,
                customer_id INT(11) NOT NULL,
                sale_invoiceno VARCHAR(100) NOT NULL,
                sales_person_id INT(11) DEFAULT NULL,
                recovery_date DATE NOT NULL,
                recovered_amount DECIMAL(18,2) NOT NULL DEFAULT 0.00,
                payment_mode VARCHAR(50) DEFAULT NULL,
                reference_no VARCHAR(150) DEFAULT NULL,
                remarks VARCHAR(500) DEFAULT NULL,
                created_by INT(11) DEFAULT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                UNIQUE KEY uk_customer_recoveries_recovery_no (recovery_no),
                KEY idx_customer_recoveries_customer (customer_id),
                KEY idx_customer_recoveries_invoice (sale_invoiceno),
                KEY idx_customer_recoveries_sales_person (sales_person_id),
                KEY idx_customer_recoveries_date (recovery_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        ''')
        conn.commit()
    finally:
        if cur: cur.close()
        if conn: conn.close()


@router.on_event('startup')
def startup_receipts():
    ensure_receipts_table()


@router.get('/', response_class=HTMLResponse)
async def receipt_page(request: Request, saved: str = '', error: str = ''):
    try:
        ensure_receipts_table()
        conn = cur = None
        try:
            conn = db()
            cur = conn.cursor(dictionary=True)

            # One row per Sales Invoice. Sales Person is taken from the invoice
            # itself, not selected independently by the user.
            cur.execute('''
                SELECT
                    s.sale_invoice_no,
                    MIN(s.sale_date) AS sale_date,
                    MIN(s.customer_id) AS customer_id,
                    COALESCE(MAX(c.customer_code), '') AS customer_code,
                    COALESCE(MAX(c.customer_name), '') AS customer_name,
                    MIN(s.sales_person_id) AS sales_person_id,
                    COALESCE(MAX(sp.employee_code), '') AS sales_person_code,
                    COALESCE(MAX(sp.name), '') AS sales_person_name,
                    MAX(s.net_amount) AS net_amount,
                    COALESCE((
                        SELECT SUM(cr.recovered_amount)
                        FROM customer_recoveries cr
                        WHERE cr.sale_invoiceno = s.sale_invoice_no
                    ), 0) AS collected
                FROM sales s
                LEFT JOIN customers c ON c.id = s.customer_id
                LEFT JOIN sales_persons sp ON sp.id = s.sales_person_id
                GROUP BY s.sale_invoice_no
                ORDER BY MIN(s.sale_date) DESC, s.sale_invoice_no DESC
            ''')
            invoices = cur.fetchall()
            for x in invoices:
                x['outstanding'] = max(
                    dec(x['net_amount']) - dec(x['collected']), Decimal('0')
                )

            # Only invoices with money still due are offered for new recovery.
            open_invoices = [x for x in invoices if x['outstanding'] > 0]

            cur.execute('''
                SELECT
                    cr.id,
                    cr.recovery_no,
                    cr.recovery_date,
                    cr.sale_invoiceno,
                    cr.customer_id,
                    COALESCE(c.customer_code, '') AS customer_code,
                    COALESCE(c.customer_name, '') AS customer_name,
                    cr.sales_person_id,
                    COALESCE(sp.employee_code, '') AS sales_person_code,
                    COALESCE(sp.name, '') AS sales_person_name,
                    cr.recovered_amount,
                    cr.payment_mode,
                    cr.reference_no,
                    cr.remarks
                FROM customer_recoveries cr
                LEFT JOIN customers c ON c.id = cr.customer_id
                LEFT JOIN sales_persons sp ON sp.id = cr.sales_person_id
                ORDER BY cr.recovery_date DESC, cr.id DESC
                LIMIT 200
            ''')
            recoveries = cur.fetchall()
        finally:
            if cur: cur.close()
            if conn: conn.close()

        return templates.TemplateResponse(
            request=request,
            name='receipts.html',
            context={
                'request': request,
                'invoices': open_invoices,
                'recoveries': recoveries,
                'saved': saved,
                'error': error,
                'today': date.today().isoformat(),
            },
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={'success': False, 'message': str(e)})


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

@router.get('/print/{recovery_no}', response_class=HTMLResponse)
async def print_money_received(request: Request, recovery_no: str):
    ensure_receipts_table()
    conn = cur = None
    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        cur.execute('''
            SELECT
                cr.id, cr.recovery_no, cr.recovery_date, cr.sale_invoiceno,
                cr.customer_id, cr.sales_person_id, cr.recovered_amount,
                cr.payment_mode, cr.reference_no, cr.remarks, cr.created_at,
                COALESCE(c.customer_code, '') AS customer_code,
                COALESCE(c.customer_name, '') AS customer_name,
                COALESCE(sp.employee_code, '') AS sales_person_code,
                COALESCE(sp.name, '') AS sales_person_name,
                COALESCE(s.net_amount, 0) AS invoice_amount
            FROM customer_recoveries cr
            LEFT JOIN customers c ON c.id = cr.customer_id
            LEFT JOIN sales_persons sp ON sp.id = cr.sales_person_id
            LEFT JOIN (
                SELECT sale_invoice_no, MAX(net_amount) AS net_amount
                FROM sales
                GROUP BY sale_invoice_no
            ) s ON s.sale_invoice_no = cr.sale_invoiceno
            WHERE cr.recovery_no = %s
            LIMIT 1
        ''', (recovery_no,))
        recovery = cur.fetchone()
        if not recovery:
            return HTMLResponse('<h3>Money Received record not found</h3>', status_code=404)
        recovery['amount_in_words'] = amount_in_words(recovery['recovered_amount'])

        cur.execute('''
            SELECT COALESCE(SUM(recovered_amount),0) AS total_received
            FROM customer_recoveries
            WHERE sale_invoiceno = %s AND id <= %s
        ''', (recovery['sale_invoiceno'], recovery['id']))
        recovery['total_received'] = cur.fetchone()['total_received']
        recovery['balance_after'] = max(dec(recovery['invoice_amount']) - dec(recovery['total_received']), Decimal('0'))

        return templates.TemplateResponse(
            request=request,
            name='money_received_print.html',
            context={'request': request, 'r': recovery},
        )
    except Exception as e:
        return HTMLResponse(f'<h3>Unable to print receipt</h3><p>{e}</p>', status_code=500)
    finally:
        if cur: cur.close()
        if conn: conn.close()


@router.post('/collect')
async def collect_money(
    request: Request,
    recovery_date: str = Form(''),
    sale_invoice_no: str = Form(''),
    recovered_amount: str = Form('0'),
    payment_mode: str = Form('CASH'),
    reference_no: str = Form(''),
    remarks: str = Form(''),
):
    conn = cur = None
    try:
        ensure_receipts_table()
        amount = dec(recovered_amount)
        if not sale_invoice_no:
            raise ValueError('Sales Invoice is required.')
        if amount <= 0:
            raise ValueError('Received amount must be greater than zero.')

        rdate = datetime.strptime(recovery_date, '%Y-%m-%d').date() if recovery_date else date.today()

        conn = db()
        cur = conn.cursor(dictionary=True)

        # Lock invoice rows while calculating the remaining balance.
        cur.execute('''
            SELECT
                MAX(customer_id) AS customer_id,
                MIN(sales_person_id) AS sales_person_id,
                MAX(net_amount) AS net_amount
            FROM sales
            WHERE sale_invoice_no = %s
            GROUP BY sale_invoice_no
            FOR UPDATE
        ''', (sale_invoice_no,))
        inv = cur.fetchone()
        if not inv:
            raise ValueError('Sales invoice not found.')

        cur.execute('''
            SELECT COALESCE(SUM(recovered_amount), 0) AS collected
            FROM customer_recoveries
            WHERE sale_invoiceno = %s
        ''', (sale_invoice_no,))
        collected = dec(cur.fetchone()['collected'])
        outstanding = max(dec(inv['net_amount']) - collected, Decimal('0'))

        if amount > outstanding:
            raise ValueError(
                f'Received amount cannot exceed outstanding amount {outstanding:.2f}.'
            )

        # Generate REC-YYYYMMDD-001 style recovery number.
        prefix = 'REC-' + rdate.strftime('%Y%m%d') + '-'
        cur.execute(
            'SELECT recovery_no FROM customer_recoveries WHERE recovery_no LIKE %s ORDER BY id DESC LIMIT 1 FOR UPDATE',
            (prefix + '%',),
        )
        last = cur.fetchone()
        seq = 1
        if last and str(last['recovery_no']).rsplit('-', 1)[-1].isdigit():
            seq = int(str(last['recovery_no']).rsplit('-', 1)[-1]) + 1
        recovery_no = f'{prefix}{seq:03d}'

        user_id = request.session.get('user_id')
        cur.execute('''
            INSERT INTO customer_recoveries
            (recovery_no, customer_id, sale_invoiceno, sales_person_id,
             recovery_date, recovered_amount, payment_mode, reference_no,
             remarks, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ''', (
            recovery_no,
            inv['customer_id'],
            sale_invoice_no,
            inv['sales_person_id'],
            rdate,
            amount,
            payment_mode or 'CASH',
            reference_no or None,
            remarks or None,
            user_id,
        ))

        new_collected = collected + amount
        new_outstanding = max(dec(inv['net_amount']) - new_collected, Decimal('0'))
        status = 'PAID' if new_outstanding == 0 else 'PARTIAL'
        cur.execute('''
            UPDATE sales
            SET received_amount=%s,
                outstanding_amount=%s,
                status=%s
            WHERE sale_invoice_no=%s
        ''', (new_collected, new_outstanding, status, sale_invoice_no))

        conn.commit()
        return RedirectResponse('/receipts?saved=' + recovery_no, status_code=303)
    except Exception as e:
        if conn:
            conn.rollback()
        return RedirectResponse('/receipts?error=' + str(e), status_code=303)
    finally:
        if cur: cur.close()
        if conn: conn.close()
