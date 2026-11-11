from pathlib import Path
from datetime import date
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from fastapi.templating import Jinja2Templates
from .sidebar_context import sidebar_context
import mysql.connector
import csv
import io

BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(BASE_DIR / 'templates'), context_processors=[sidebar_context])

router = APIRouter(tags=['Reports'])
DB = {'host': 'localhost', 'user': 'root', 'password': '', 'database': 'python_login'}


def db():
    return mysql.connector.connect(**DB)


def filters(from_date, to_date):
    return (from_date or '').strip(), (to_date or '').strip()


@router.get('/purchase-report', response_class=HTMLResponse)
async def purchase_report(
    request: Request,
    from_date: str = Query(''),
    to_date: str = Query(''),
    ro: str = Query(''),
    company_id: str = Query(''),
    status: str = Query(''),
):
    conn = cur = None
    rows = []
    companies = []
    ros = []
    summary = {'gross': 0, 'discount': 0, 'taxable': 0, 'gst': 0, 'net': 0, 'paid': 0, 'outstanding': 0}
    try:
        conn = db(); cur = conn.cursor(dictionary=True)
        cur.execute("SELECT COMP_ID AS id, COMP_NAME AS name FROM mm_company_dtls ORDER BY COMP_NAME")
        companies = cur.fetchall()
        cur.execute("SELECT DISTINCT TRIM(ro_no) AS ro_no FROM purchase_master WHERE ro_no IS NOT NULL AND TRIM(ro_no)<>'' ORDER BY TRIM(ro_no)")
        ros = [str(x['ro_no']).strip() for x in cur.fetchall()]

        sql = """
            SELECT pm.id, pm.purchase_no, TRIM(COALESCE(pm.ro_no,'')) AS ro_no,
                   pm.purchase_date, pm.invoice_no, pm.invoice_date,
                   COALESCE(c.COMP_NAME,'') AS company_name,
                   pm.status, pm.gross_amount, pm.discount_amount, pm.taxable_amount,
                   pm.gst_amount, pm.net_amount, pm.paid_amount, pm.outstanding_amount,
                   pd.product_id, COALESCE(pr.PROD_DESC, CONCAT('Product ',pd.product_id)) AS product_name,
                   pd.batch_id, pd.qty, pd.unit_price, pd.gross_amount AS line_gross,
                   pd.discount AS line_discount, pd.taxable_amount AS line_taxable,
                   pd.gst_rate, pd.gst_amount AS line_gst, pd.line_total
            FROM purchase_master pm
            INNER JOIN purchase_details pd ON pd.purchase_id = pm.id
            LEFT JOIN mm_company_dtls c ON c.COMP_ID = pm.company_id
            LEFT JOIN benfed_fertilizer.mm_product pr ON pr.PROD_ID = pd.product_id
            WHERE 1=1
        """
        args=[]
        if from_date:
            sql += ' AND pm.purchase_date >= %s'; args.append(from_date)
        if to_date:
            sql += ' AND pm.purchase_date <= %s'; args.append(to_date)
        if ro.strip():
            sql += ' AND TRIM(pm.ro_no) = %s'; args.append(ro.strip())
        if company_id.strip():
            sql += ' AND pm.company_id = %s'; args.append(company_id.strip())
        if status.strip():
            sql += ' AND pm.status = %s'; args.append(status.strip())
        sql += ' ORDER BY pm.purchase_date DESC, pm.id DESC, pd.id'
        cur.execute(sql, args)
        rows = cur.fetchall()
        for r in rows:
            summary['gross'] += float(r.get('line_gross') or 0)
            summary['discount'] += float(r.get('line_discount') or 0)
            summary['taxable'] += float(r.get('line_taxable') or 0)
            summary['gst'] += float(r.get('line_gst') or 0)
            summary['net'] += float(r.get('line_total') or 0)
        # Header-level totals avoid double counting multi-line invoices.
        seen=set()
        header_summary={'gross':0,'discount':0,'taxable':0,'gst':0,'net':0,'paid':0,'outstanding':0}
        for r in rows:
            if r['id'] not in seen:
                seen.add(r['id'])
                for k, src in [('gross','gross_amount'),('discount','discount_amount'),('taxable','taxable_amount'),('gst','gst_amount'),('net','net_amount'),('paid','paid_amount'),('outstanding','outstanding_amount')]:
                    header_summary[k] += float(r.get(src) or 0)
        summary.update(header_summary)
        return templates.TemplateResponse(request=request, name='purchase_report.html', context={
            'request':request,'rows':rows,'summary':summary,'companies':companies,'ros':ros,
            'from_date':from_date,'to_date':to_date,'ro':ro,'company_id':company_id,'status':status,
            'generated_on':date.today().isoformat(),'print_mode':False
        })
    except Exception as e:
        return HTMLResponse(f'<h3>Purchase Report Error</h3><pre>{e}</pre>', status_code=500)
    finally:
        if cur: cur.close()
        if conn: conn.close()


@router.get('/sale-report', response_class=HTMLResponse)
async def sale_report(
    request: Request,
    from_date: str = Query(''),
    to_date: str = Query(''),
    ro: str = Query(''),
    customer_id: str = Query(''),
    sales_person_id: str = Query(''),
    status: str = Query(''),
):
    conn = cur = None
    rows=[]; customers=[]; sales_persons=[]; ros=[]
    summary={'gross':0,'discount':0,'gst':0,'net':0,'received':0,'outstanding':0}
    try:
        conn=db(); cur=conn.cursor(dictionary=True)
        cur.execute("SELECT id, customer_code, customer_name FROM customers ORDER BY customer_name")
        customers=cur.fetchall()
        cur.execute("SELECT id, employee_code, name FROM sales_persons ORDER BY name")
        sales_persons=cur.fetchall()
        cur.execute("SELECT DISTINCT TRIM(ro) AS ro FROM sales WHERE ro IS NOT NULL AND TRIM(ro)<>'' ORDER BY TRIM(ro)")
        ros=[str(x['ro']).strip() for x in cur.fetchall()]
        sql="""
            SELECT s.sale_invoice_no, s.sale_date, TRIM(s.ro) AS ro,
                   s.customer_id, COALESCE(c.customer_code,'') AS customer_code,
                   COALESCE(c.customer_name,'') AS customer_name,
                   s.sales_person_id, COALESCE(sp.employee_code,'') AS sales_person_code,
                   COALESCE(sp.name,'') AS sales_person_name,
                   s.product_id, COALESCE(pr.PROD_DESC,CONCAT('Product ',s.product_id)) AS product_name,
                   s.batch_id, s.qty, s.selling_price, s.discount, s.gst_rate,
                   s.gst_amount, s.line_total, s.gross_amount, s.net_amount,
                   s.received_amount, s.outstanding_amount, s.status
            FROM sales s
            LEFT JOIN customers c ON c.id=s.customer_id
            LEFT JOIN sales_persons sp ON sp.id=s.sales_person_id
            LEFT JOIN benfed_fertilizer.mm_product pr ON pr.PROD_ID=s.product_id
            WHERE 1=1
        """
        args=[]
        if from_date: sql+=' AND s.sale_date >= %s'; args.append(from_date)
        if to_date: sql+=' AND s.sale_date <= %s'; args.append(to_date)
        if ro.strip(): sql+=' AND TRIM(s.ro) = %s'; args.append(ro.strip())
        if customer_id.strip(): sql+=' AND s.customer_id = %s'; args.append(customer_id.strip())
        if sales_person_id.strip(): sql+=' AND s.sales_person_id = %s'; args.append(sales_person_id.strip())
        if status.strip(): sql+=' AND s.status = %s'; args.append(status.strip())
        sql+=' ORDER BY s.sale_date DESC, s.sale_invoice_no DESC, s.ro, s.product_id'
        cur.execute(sql,args); rows=cur.fetchall()
        seen=set()
        for r in rows:
            key=r['sale_invoice_no']
            if key not in seen:
                seen.add(key)
                summary['gross'] += float(r.get('gross_amount') or 0)
                summary['discount'] += float(r.get('discount') or 0)
                summary['gst'] += float(r.get('gst_amount') or 0)
                summary['net'] += float(r.get('net_amount') or 0)
                summary['received'] += float(r.get('received_amount') or 0)
                summary['outstanding'] += float(r.get('outstanding_amount') or 0)
        return templates.TemplateResponse(request=request,name='sale_report.html',context={
            'request':request,'rows':rows,'summary':summary,'customers':customers,'sales_persons':sales_persons,'ros':ros,
            'from_date':from_date,'to_date':to_date,'ro':ro,'customer_id':customer_id,'sales_person_id':sales_person_id,'status':status,
            'generated_on':date.today().isoformat(),'print_mode':False
        })
    except Exception as e:
        return HTMLResponse(f'<h3>Sale Report Error</h3><pre>{e}</pre>',status_code=500)
    finally:
        if cur: cur.close()
        if conn: conn.close()


@router.get('/purchase-report/export')
async def purchase_report_export(from_date:str='',to_date:str='',ro:str='',company_id:str='',status:str=''):
    # Reuse the report query by requesting a compact CSV directly from the database.
    conn=cur=None
    try:
        conn=db(); cur=conn.cursor(dictionary=True)
        sql="""SELECT pm.purchase_no, pm.purchase_date, pm.invoice_no, TRIM(COALESCE(pm.ro_no,'')) ro_no,
        COALESCE(c.COMP_NAME,'') company_name, pd.product_id, COALESCE(pr.PROD_DESC,'') product_name,
        pd.batch_id,pd.qty,pd.unit_price,pd.gross_amount,pd.discount,pd.taxable_amount,pd.gst_rate,pd.gst_amount,pd.line_total,
        pm.paid_amount,pm.outstanding_amount,pm.status
        FROM purchase_master pm INNER JOIN purchase_details pd ON pd.purchase_id=pm.id
        LEFT JOIN mm_company_dtls c ON c.COMP_ID=pm.company_id LEFT JOIN benfed_fertilizer.mm_product pr ON pr.PROD_ID=pd.product_id WHERE 1=1"""
        args=[]
        if from_date: sql+=' AND pm.purchase_date >= %s';args.append(from_date)
        if to_date: sql+=' AND pm.purchase_date <= %s';args.append(to_date)
        if ro.strip(): sql+=' AND TRIM(pm.ro_no)=%s';args.append(ro.strip())
        if company_id.strip(): sql+=' AND pm.company_id=%s';args.append(company_id.strip())
        if status.strip(): sql+=' AND pm.status=%s';args.append(status.strip())
        sql+=' ORDER BY pm.purchase_date DESC,pm.id DESC,pd.id';cur.execute(sql,args);rows=cur.fetchall()
        out=io.StringIO();w=csv.writer(out);w.writerow(['Purchase No','Purchase Date','Invoice No','RO No','Company','Product ID','Product Name','Batch','Qty','Unit Price','Gross','Discount','Taxable','GST %','GST','Line Total','Paid','Outstanding','Status'])
        for r in rows:w.writerow([r[k] for k in ['purchase_no','purchase_date','invoice_no','ro_no','company_name','product_id','product_name','batch_id','qty','unit_price','gross_amount','discount','taxable_amount','gst_rate','gst_amount','line_total','paid_amount','outstanding_amount','status']])
        return StreamingResponse(iter([out.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=purchase_report.csv'})
    finally:
        if cur:cur.close()
        if conn:conn.close()


@router.get('/sale-report/export')
async def sale_report_export(from_date:str='',to_date:str='',ro:str='',customer_id:str='',sales_person_id:str='',status:str=''):
    conn=cur=None
    try:
        conn=db();cur=conn.cursor(dictionary=True)
        sql="""SELECT s.sale_invoice_no,s.sale_date,TRIM(s.ro) ro,c.customer_code,c.customer_name,sp.employee_code sales_person_code,sp.name sales_person_name,s.product_id,COALESCE(pr.PROD_DESC,'') product_name,s.batch_id,s.qty,s.selling_price,s.discount,s.gst_rate,s.gst_amount,s.line_total,s.net_amount,s.received_amount,s.outstanding_amount,s.status FROM sales s LEFT JOIN customers c ON c.id=s.customer_id LEFT JOIN sales_persons sp ON sp.id=s.sales_person_id LEFT JOIN benfed_fertilizer.mm_product pr ON pr.PROD_ID=s.product_id WHERE 1=1"""
        args=[]
        if from_date:sql+=' AND s.sale_date >= %s';args.append(from_date)
        if to_date:sql+=' AND s.sale_date <= %s';args.append(to_date)
        if ro.strip():sql+=' AND TRIM(s.ro)=%s';args.append(ro.strip())
        if customer_id.strip():sql+=' AND s.customer_id=%s';args.append(customer_id.strip())
        if sales_person_id.strip():sql+=' AND s.sales_person_id=%s';args.append(sales_person_id.strip())
        if status.strip():sql+=' AND s.status=%s';args.append(status.strip())
        sql+=' ORDER BY s.sale_date DESC,s.sale_invoice_no DESC,s.ro,s.product_id';cur.execute(sql,args);rows=cur.fetchall()
        out=io.StringIO();w=csv.writer(out);w.writerow(['Invoice No','Sale Date','RO No','Customer Code','Customer','Sales Person Code','Sales Person','Product ID','Product Name','Batch','Qty','Rate','Discount','GST %','GST','Line Total','Net Amount','Received','Outstanding','Status'])
        keys=['sale_invoice_no','sale_date','ro','customer_code','customer_name','sales_person_code','sales_person_name','product_id','product_name','batch_id','qty','selling_price','discount','gst_rate','gst_amount','line_total','net_amount','received_amount','outstanding_amount','status']
        for r in rows:w.writerow([r[k] for k in keys])
        return StreamingResponse(iter([out.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=sale_report.csv'})
    finally:
        if cur:cur.close()
        if conn:conn.close()


def current_financial_year(today=None):
    """Return current Indian financial-year start and end dates (inclusive)."""
    today = today or date.today()
    start_year = today.year if today.month >= 4 else today.year - 1
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


@router.get('/collection-report', response_class=HTMLResponse)
async def collection_report(
    request: Request,
    from_date: str = Query(''),
    to_date: str = Query(''),
    sales_person_id: str = Query(''),
):
    """Agent-wise customer collections, restricted to the current financial year."""
    conn = cur = None
    rows, sales_persons = [], []
    agent_totals = []
    summary = {'amount': 0.0, 'receipts': 0, 'invoices': 0}
    fy_start, fy_end = current_financial_year()
    errors = []

    def parse_date(value, label):
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError):
            errors.append(f'{label} is not a valid date.')
            return None

    from_dt = parse_date(from_date, 'From date')
    to_dt = parse_date(to_date, 'To date')
    if bool(from_date) != bool(to_date):
        errors.append('Please enter both From Date and To Date.')
    if from_dt and not (fy_start <= from_dt <= fy_end):
        errors.append(f'From date must be within the current financial year ({fy_start:%d-%m-%Y} to {fy_end:%d-%m-%Y}).')
    if to_dt and not (fy_start <= to_dt <= fy_end):
        errors.append(f'To date must be within the current financial year ({fy_start:%d-%m-%Y} to {fy_end:%d-%m-%Y}).')
    if from_dt and to_dt and from_dt > to_dt:
        errors.append('From date cannot be later than To date.')

    # Show current FY by default, through today; supplied dates are validated and preserved.
    if not from_date and not to_date:
        from_date = fy_start.isoformat()
        to_date = min(date.today(), fy_end).isoformat()
        from_dt, to_dt = date.fromisoformat(from_date), date.fromisoformat(to_date)

    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, employee_code, name FROM sales_persons ORDER BY name")
        sales_persons = cur.fetchall()

        if not errors:
            sql = """
                SELECT cr.id, cr.recovery_no, cr.recovery_date, cr.sale_invoiceno,
                       cr.recovered_amount, cr.payment_mode, cr.reference_no,
                       COALESCE(sp.id, 0) AS sales_person_id,
                       COALESCE(sp.employee_code, '') AS sales_person_code,
                       COALESCE(sp.name, 'Unassigned') AS sales_person_name,
                       COALESCE(c.customer_code, '') AS customer_code,
                       COALESCE(c.customer_name, '') AS customer_name
                FROM customer_recoveries cr
                LEFT JOIN (
                    SELECT sale_invoice_no, MIN(sales_person_id) AS sales_person_id
                    FROM sales GROUP BY sale_invoice_no
                ) s ON UPPER(TRIM(s.sale_invoice_no)) = UPPER(TRIM(cr.sale_invoiceno))
                LEFT JOIN sales_persons sp ON sp.id = COALESCE(cr.sales_person_id, s.sales_person_id)
                LEFT JOIN customers c ON c.id = cr.customer_id
                WHERE cr.recovery_date >= %s AND cr.recovery_date <= %s
            """
            args = [from_date, to_date]
            if sales_person_id.strip():
                sql += " AND COALESCE(cr.sales_person_id, s.sales_person_id) = %s"
                args.append(sales_person_id.strip())
            sql += " ORDER BY sp.name, cr.recovery_date, cr.recovery_no"
            cur.execute(sql, args)
            rows = cur.fetchall()

            totals = {}
            for row in rows:
                amount = float(row.get('recovered_amount') or 0)
                summary['amount'] += amount
                summary['receipts'] += 1
                row['recovered_amount'] = amount
                key = (row['sales_person_id'], row['sales_person_code'], row['sales_person_name'])
                if key not in totals:
                    totals[key] = {
                        'sales_person_id': key[0], 'sales_person_code': key[1],
                        'sales_person_name': key[2], 'amount': 0.0,
                        'receipts': 0, 'invoices': set()
                    }
                totals[key]['amount'] += amount
                totals[key]['receipts'] += 1
                totals[key]['invoices'].add(row.get('sale_invoiceno') or '')
            agent_totals = sorted(totals.values(), key=lambda x: x['sales_person_name'].lower())
            for agent in agent_totals:
                agent['amount'] = round(agent['amount'], 2)
                agent['invoices'] = len(agent['invoices'] - {''})
                summary['invoices'] = len({r.get('sale_invoiceno') for r in rows if r.get('sale_invoiceno')})
            summary['amount'] = round(summary['amount'], 2)

        return templates.TemplateResponse(request=request, name='collection_report.html', context={
            'request': request, 'rows': rows, 'sales_persons': sales_persons,
            'agent_totals': agent_totals, 'summary': summary,
            'from_date': from_date, 'to_date': to_date,
            'sales_person_id': sales_person_id, 'errors': errors,
            'fy_start': fy_start.isoformat(), 'fy_end': fy_end.isoformat(),
            'generated_on': date.today().isoformat(),
            'user_type': request.session.get('user_type', 'USER'),
        })
    except Exception as e:
        return HTMLResponse(f'<h3>Collection Report Error</h3><pre>{e}</pre>', status_code=500)
    finally:
        if cur: cur.close()
        if conn: conn.close()




def _collection_export_data(from_date: str, to_date: str, sales_person_id: str = ''):
    """Load validated collection rows and agent totals for PDF/Excel exports."""
    fy_start, fy_end = current_financial_year()
    if not from_date or not to_date:
        raise ValueError('Please provide both From Date and To Date.')
    try:
        from_dt = date.fromisoformat(from_date)
        to_dt = date.fromisoformat(to_date)
    except (TypeError, ValueError):
        raise ValueError('Please provide valid From Date and To Date values.')
    if not (fy_start <= from_dt <= fy_end):
        raise ValueError(f'From Date must be within the current financial year ({fy_start:%d-%m-%Y} to {fy_end:%d-%m-%Y}).')
    if not (fy_start <= to_dt <= fy_end):
        raise ValueError(f'To Date must be within the current financial year ({fy_start:%d-%m-%Y} to {fy_end:%d-%m-%Y}).')
    if from_dt > to_dt:
        raise ValueError('From Date cannot be later than To Date.')

    conn = cur = None
    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        sql = """
            SELECT cr.id, cr.recovery_no, cr.recovery_date, cr.sale_invoiceno,
                   cr.recovered_amount, cr.payment_mode, cr.reference_no,
                   COALESCE(sp.id, 0) AS sales_person_id,
                   COALESCE(sp.employee_code, '') AS sales_person_code,
                   COALESCE(sp.name, 'Unassigned') AS sales_person_name,
                   COALESCE(c.customer_code, '') AS customer_code,
                   COALESCE(c.customer_name, '') AS customer_name
            FROM customer_recoveries cr
            LEFT JOIN (
                SELECT sale_invoice_no, MIN(sales_person_id) AS sales_person_id
                FROM sales GROUP BY sale_invoice_no
            ) s ON UPPER(TRIM(s.sale_invoice_no)) = UPPER(TRIM(cr.sale_invoiceno))
            LEFT JOIN sales_persons sp ON sp.id = COALESCE(cr.sales_person_id, s.sales_person_id)
            LEFT JOIN customers c ON c.id = cr.customer_id
            WHERE cr.recovery_date >= %s AND cr.recovery_date <= %s
        """
        args = [from_dt.isoformat(), to_dt.isoformat()]
        if sales_person_id and sales_person_id.strip():
            sql += ' AND COALESCE(cr.sales_person_id, s.sales_person_id) = %s'
            args.append(sales_person_id.strip())
        sql += ' ORDER BY sp.name, cr.recovery_date, cr.recovery_no'
        cur.execute(sql, args)
        rows = cur.fetchall()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    totals = {}
    summary = {'amount': 0.0, 'receipts': len(rows), 'invoices': 0}
    invoices = set()
    for row in rows:
        row['recovered_amount'] = float(row.get('recovered_amount') or 0)
        summary['amount'] += row['recovered_amount']
        if row.get('sale_invoiceno'):
            invoices.add(row['sale_invoiceno'])
        key = (row['sales_person_id'], row['sales_person_code'], row['sales_person_name'])
        if key not in totals:
            totals[key] = {'sales_person_id': key[0], 'sales_person_code': key[1],
                           'sales_person_name': key[2], 'amount': 0.0,
                           'receipts': 0, 'invoice_set': set()}
        totals[key]['amount'] += row['recovered_amount']
        totals[key]['receipts'] += 1
        if row.get('sale_invoiceno'):
            totals[key]['invoice_set'].add(row['sale_invoiceno'])
    agent_totals = []
    for item in sorted(totals.values(), key=lambda x: x['sales_person_name'].lower()):
        item['amount'] = round(item['amount'], 2)
        item['invoices'] = len(item.pop('invoice_set'))
        agent_totals.append(item)
    summary['amount'] = round(summary['amount'], 2)
    summary['invoices'] = len(invoices)
    return rows, agent_totals, summary, from_dt, to_dt


@router.get('/collection-report/export/excel')
async def collection_report_export_excel(
    from_date: str = Query(''), to_date: str = Query(''), sales_person_id: str = Query('')
):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
        rows, agent_totals, summary, from_dt, to_dt = _collection_export_data(from_date, to_date, sales_person_id)
        wb = Workbook()
        ws = wb.active
        ws.title = 'Agent Summary'
        ws.append(['Agent-wise Collection Report'])
        ws.append(['From Date', from_dt.strftime('%d-%m-%Y'), 'To Date', to_dt.strftime('%d-%m-%Y')])
        ws.append(['Total Collection (₹)', summary['amount'], 'Receipts', summary['receipts'], 'Sale Invoices', summary['invoices']])
        ws.append([])
        ws.append(['Agent Code', 'Agent Name', 'Number of Receipts', 'Sale Invoices', 'Total Collection (₹)'])
        for a in agent_totals:
            ws.append([a['sales_person_code'], a['sales_person_name'], a['receipts'], a['invoices'], a['amount']])
        ws.append(['', 'GRAND TOTAL', summary['receipts'], summary['invoices'], summary['amount']])
        detail = wb.create_sheet('Collection Details')
        detail.append(['Received Date', 'Receipt No.', 'Sale Invoice', 'Agent Code', 'Agent Name',
                       'Customer Code', 'Customer Name', 'Payment Mode', 'Reference No.', 'Received Amount (₹)'])
        for r in rows:
            received = r.get('recovery_date')
            detail.append([received.strftime('%d-%m-%Y') if hasattr(received, 'strftime') else str(received or ''),
                           r.get('recovery_no') or '', r.get('sale_invoiceno') or '',
                           r.get('sales_person_code') or '', r.get('sales_person_name') or '',
                           r.get('customer_code') or '', r.get('customer_name') or '',
                           r.get('payment_mode') or '', r.get('reference_no') or '', r['recovered_amount']])
        for sheet in wb.worksheets:
            sheet.freeze_panes = 'A5' if sheet.title == 'Agent Summary' else 'A2'
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                cell.font = Font(bold=True, color='FFFFFF', size=14)
                cell.fill = PatternFill('solid', fgColor='244062')
            header_row = 5 if sheet.title == 'Agent Summary' else 1
            for cell in sheet[header_row]:
                cell.font = Font(bold=True, color='FFFFFF')
                cell.fill = PatternFill('solid', fgColor='4472C4')
                cell.alignment = Alignment(wrap_text=True)
            for col in sheet.columns:
                letter = get_column_letter(col[0].column)
                width = min(max(max(len(str(c.value or '')) for c in col) + 2, 12), 32)
                sheet.column_dimensions[letter].width = width
            for row in sheet.iter_rows():
                for cell in row:
                    if 'Amount' in str(sheet.cell(1, cell.column).value or '') or (sheet.title == 'Agent Summary' and cell.column == 5):
                        if isinstance(cell.value, (int, float)):
                            cell.number_format = '#,##0.00'
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        filename = f'agent_wise_collection_{from_dt:%Y%m%d}_{to_dt:%Y%m%d}.xlsx'
        return Response(content=output.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename="{filename}"'})
    except ValueError as e:
        return HTMLResponse(f'<h3>Collection Report Export</h3><p>{e}</p><p><a href="/collection-report">Back to report</a></p>', status_code=400)
    except Exception as e:
        return HTMLResponse(f'<h3>Excel Export Error</h3><pre>{e}</pre>', status_code=500)


@router.get('/collection-report/export/pdf')
async def collection_report_export_pdf(
    from_date: str = Query(''), to_date: str = Query(''), sales_person_id: str = Query('')
):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        rows, agent_totals, summary, from_dt, to_dt = _collection_export_data(from_date, to_date, sales_person_id)
        output = io.BytesIO()
        doc = SimpleDocTemplate(output, pagesize=landscape(A4), rightMargin=18, leftMargin=18, topMargin=22, bottomMargin=22)
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='SmallCell', parent=styles['Normal'], fontSize=6.5, leading=8))
        story = [Paragraph('Agent-wise Collection Report', styles['Title']),
                 Paragraph(f'Period: {from_dt:%d-%m-%Y} to {to_dt:%d-%m-%Y}', styles['Normal']),
                 Paragraph(f'Total Collection: Rs. {summary["amount"]:,.2f} &nbsp;&nbsp; Receipts: {summary["receipts"]} &nbsp;&nbsp; Sale Invoices: {summary["invoices"]}', styles['Normal']),
                 Spacer(1, 10), Paragraph('Agent-wise Summary', styles['Heading2'])]
        summary_data = [['Agent Code', 'Agent Name', 'Receipts', 'Sale Invoices', 'Total Collection (Rs.)']]
        for a in agent_totals:
            summary_data.append([str(a['sales_person_code']), str(a['sales_person_name']), str(a['receipts']), str(a['invoices']), f'{a["amount"]:,.2f}'])
        summary_data.append(['', 'GRAND TOTAL', str(summary['receipts']), str(summary['invoices']), f'{summary["amount"]:,.2f}'])
        st = Table(summary_data, repeatRows=1, hAlign='LEFT', colWidths=[85, 180, 65, 75, 115])
        st.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#4472C4')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),8),('GRID',(0,0),(-1,-1),0.3,colors.grey),('BACKGROUND',(0,-1),(-1,-1),colors.HexColor('#D9E2F3'))]))
        story += [st, Spacer(1, 12), Paragraph('Collection Details', styles['Heading2'])]
        headers = ['Received Date','Receipt No.','Sale Invoice','Agent Code','Agent Name','Customer Code','Customer Name','Payment Mode','Reference No.','Amount (Rs.)']
        detail_data = [[Paragraph(x, styles['SmallCell']) for x in headers]]
        for r in rows:
            d = r.get('recovery_date')
            date_text = d.strftime('%d-%m-%Y') if hasattr(d, 'strftime') else str(d or '')
            detail_data.append([Paragraph(str(x or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;'), styles['SmallCell']) for x in [date_text, r.get('recovery_no'), r.get('sale_invoiceno'), r.get('sales_person_code'), r.get('sales_person_name'), r.get('customer_code'), r.get('customer_name'), r.get('payment_mode'), r.get('reference_no'), f'{r["recovered_amount"]:,.2f}']])
        widths = [55, 65, 65, 50, 90, 55, 95, 60, 65, 65]
        dt = Table(detail_data, repeatRows=1, hAlign='LEFT', colWidths=widths)
        dt.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#244062')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('GRID',(0,0),(-1,-1),0.25,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP'),('ALIGN',(-1,1),(-1,-1),'RIGHT')]))
        story.append(dt)
        doc.build(story)
        output.seek(0)
        filename = f'agent_wise_collection_{from_dt:%Y%m%d}_{to_dt:%Y%m%d}.pdf'
        return Response(content=output.getvalue(), media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="{filename}"'})
    except ValueError as e:
        return HTMLResponse(f'<h3>Collection Report Export</h3><p>{e}</p><p><a href="/collection-report">Back to report</a></p>', status_code=400)
    except Exception as e:
        return HTMLResponse(f'<h3>PDF Export Error</h3><pre>{e}</pre>', status_code=500)


@router.get('/commission-report', response_class=HTMLResponse)
async def commission_report(
    request: Request,
    from_date: str = Query(''),
    to_date: str = Query(''),
    sales_person_id: str = Query(''),
):
    """Calculate commission for every recovery using the best matching active slab.

    Days are counted from sale date to recovery date, inclusive of the date
    difference. Eligible slabs must be active, effective on/before recovery,
    and contain the recovery-day count. The newest effective matching slab wins.
    """
    conn = cur = None
    rows, sales_persons, agent_totals = [], [], []
    summary = {'received': 0.0, 'commission': 0.0}
    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, employee_code, name FROM sales_persons ORDER BY name")
        sales_persons = cur.fetchall()
        # Load the configured commission table explicitly. This avoids a silent
        # zero caused by a brittle correlated lookup and keeps report/export aligned.
        cur.execute("""SELECT id, effective_dt, from_days, to_days, commission_percentage, status
                       FROM commission_slabs WHERE UPPER(TRIM(status))='A'
                       ORDER BY effective_dt DESC, from_days DESC, id DESC""")
        slabs = cur.fetchall()
        sql = """
            SELECT cr.id, cr.recovery_no, cr.recovery_date, cr.sale_invoiceno,
                   cr.recovered_amount, cr.payment_mode, cr.reference_no,
                   COALESCE(sp.id, 0) AS sales_person_id,
                   COALESCE(sp.employee_code, '') AS sales_person_code,
                   COALESCE(sp.name, 'Unassigned') AS sales_person_name,
                   COALESCE(c.customer_code, '') AS customer_code,
                   COALESCE(c.customer_name, '') AS customer_name,
                   s.sale_date AS sale_date,
                   DATEDIFF(cr.recovery_date, s.sale_date) AS days_to_recovery
            FROM customer_recoveries cr
            LEFT JOIN (SELECT sale_invoice_no, MIN(sale_date) AS sale_date,
                              MIN(sales_person_id) AS sales_person_id
                       FROM sales GROUP BY sale_invoice_no) s
              ON UPPER(TRIM(s.sale_invoice_no)) = UPPER(TRIM(cr.sale_invoiceno))
            LEFT JOIN sales_persons sp ON sp.id = COALESCE(cr.sales_person_id, s.sales_person_id)
            LEFT JOIN customers c ON c.id = cr.customer_id
            WHERE 1=1
        """
        args = []
        if from_date:
            sql += ' AND cr.recovery_date >= %s'; args.append(from_date)
        if to_date:
            sql += ' AND cr.recovery_date <= %s'; args.append(to_date)
        if sales_person_id.strip():
            sql += ' AND COALESCE(cr.sales_person_id, s.sales_person_id) = %s'; args.append(sales_person_id.strip())
        sql += ' ORDER BY sp.name, cr.recovery_date, cr.recovery_no'
        cur.execute(sql, args)
        rows = cur.fetchall()

        from datetime import datetime, date as date_type
        def as_date(value):
            if isinstance(value, datetime): return value.date()
            if isinstance(value, date_type): return value
            if value:
                try: return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
                except (TypeError, ValueError): return None
            return None

        totals = {}
        for r in rows:
            sale_dt, recovery_dt = as_date(r.get('sale_date')), as_date(r.get('recovery_date'))
            days = (recovery_dt - sale_dt).days if sale_dt and recovery_dt else None
            r['days_to_recovery'] = days
            # First find active slabs effective on/before the recovery date whose
            # day range matches this recovery. Then choose the newest effective
            # rule among those matches. This prevents a newer date containing
            # other day ranges from incorrectly forcing commission to zero.
            eligible_dates = [as_date(x.get('effective_dt')) for x in slabs
                              if recovery_dt and as_date(x.get('effective_dt'))
                              and as_date(x.get('effective_dt')) <= recovery_dt]
            matching_slabs = [
                x for x in slabs
                if recovery_dt and days is not None and days >= 0
                and as_date(x.get('effective_dt'))
                and as_date(x.get('effective_dt')) <= recovery_dt
                and int(x.get('from_days') or 0) <= days <= int(x.get('to_days') or 0)
            ]
            latest_effective_dt = max(
                (as_date(x.get('effective_dt')) for x in matching_slabs),
                default=None
            )
            applicable = [x for x in matching_slabs
                          if latest_effective_dt and as_date(x.get('effective_dt')) == latest_effective_dt]
            applicable.sort(key=lambda x: (int(x.get('from_days') or 0), int(x.get('id') or 0)), reverse=True)
            pct = float(applicable[0].get('commission_percentage') or 0) if applicable else 0.0
            r['commission_percentage'] = pct
            r['matched_slab_id'] = applicable[0].get('id') if applicable else None
            r['slab_effective_dt'] = latest_effective_dt
            if not sale_dt:
                r['commission_match_status'] = 'SALE INVOICE NOT MATCHED'
            elif days is not None and days < 0:
                r['commission_match_status'] = 'RECOVERY BEFORE SALE'
            elif not eligible_dates:
                r['commission_match_status'] = 'NO EFFECTIVE ACTIVE SLAB'
            elif not applicable:
                r['commission_match_status'] = 'NO DAY RANGE MATCH'
            else:
                r['commission_match_status'] = 'MATCHED'
            received = float(r.get('recovered_amount') or 0)
            commission = round(received * pct / 100, 2)
            r['commission_amount'] = commission
            summary['received'] += received
            summary['commission'] += commission
            key = (r['sales_person_id'], r['sales_person_code'], r['sales_person_name'])
            if key not in totals:
                totals[key] = {'sales_person_id': key[0], 'sales_person_code': key[1],
                               'sales_person_name': key[2], 'received': 0.0, 'commission': 0.0}
            totals[key]['received'] += received
            totals[key]['commission'] += commission
        agent_totals = sorted(totals.values(), key=lambda x: x['sales_person_name'].lower())
        for a in agent_totals:
            a['received'] = round(a['received'], 2); a['commission'] = round(a['commission'], 2)
        summary['received'] = round(summary['received'], 2)
        summary['commission'] = round(summary['commission'], 2)
        return templates.TemplateResponse(request=request, name='commission_report.html', context={
            'request': request, 'rows': rows, 'agent_totals': agent_totals,
            'summary': summary, 'sales_persons': sales_persons,
            'from_date': from_date, 'to_date': to_date,
            'sales_person_id': sales_person_id, 'generated_on': date.today().isoformat(),
            'user_type': request.session.get('user_type', 'USER'),
        })
    except Exception as e:
        return HTMLResponse(f'<h3>Commission Report Error</h3><pre>{e}</pre>', status_code=500)
    finally:
        if cur: cur.close()
        if conn: conn.close()


@router.get('/commission-report/export')
async def commission_report_export(from_date: str = '', to_date: str = '', sales_person_id: str = ''):
    conn = cur = None
    try:
        conn = db(); cur = conn.cursor(dictionary=True)
        cur.execute("""SELECT id, effective_dt, from_days, to_days, commission_percentage, status
                       FROM commission_slabs WHERE UPPER(TRIM(status))='A'
                       ORDER BY effective_dt DESC, from_days DESC, id DESC""")
        slabs = cur.fetchall()
        sql = """
            SELECT cr.recovery_no, cr.recovery_date, cr.sale_invoiceno,
                   s.sale_date AS sale_date,
                   COALESCE(sp.employee_code, '') AS agent_code,
                   COALESCE(sp.name, 'Unassigned') AS agent_name,
                   COALESCE(c.customer_name, '') AS customer_name,
                   cr.recovered_amount,
                   DATEDIFF(cr.recovery_date, s.sale_date) AS days_to_recovery
            FROM customer_recoveries cr
            LEFT JOIN (SELECT sale_invoice_no, MIN(sale_date) AS sale_date,
                              MIN(sales_person_id) AS sales_person_id
                       FROM sales GROUP BY sale_invoice_no) s
              ON UPPER(TRIM(s.sale_invoice_no))=UPPER(TRIM(cr.sale_invoiceno))
            LEFT JOIN sales_persons sp ON sp.id=COALESCE(cr.sales_person_id,s.sales_person_id)
            LEFT JOIN customers c ON c.id=cr.customer_id WHERE 1=1
        """
        args=[]
        if from_date: sql += ' AND cr.recovery_date >= %s'; args.append(from_date)
        if to_date: sql += ' AND cr.recovery_date <= %s'; args.append(to_date)
        if sales_person_id.strip(): sql += ' AND COALESCE(cr.sales_person_id,s.sales_person_id)=%s'; args.append(sales_person_id.strip())
        sql += ' ORDER BY sp.name,cr.recovery_date,cr.recovery_no'
        cur.execute(sql,args); rows=cur.fetchall()
        from datetime import datetime, date as date_type
        def as_date(value):
            if isinstance(value, datetime): return value.date()
            if isinstance(value, date_type): return value
            if value:
                try: return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
                except (TypeError, ValueError): return None
            return None
        out=io.StringIO(); w=csv.writer(out)
        w.writerow(['Recovery No','Money Received Date','Sale Invoice','Sale Date','Agent Code','Agent Name','Customer','Amount Received','Days From Sale','Commission %','Commission Amount','Matched Slab ID','Effective Date Used','Match Status'])
        for r in rows:
            sale_dt, recovery_dt = as_date(r.get('sale_date')), as_date(r.get('recovery_date'))
            days = (recovery_dt-sale_dt).days if sale_dt and recovery_dt else None
            eligible_dates=[as_date(x.get('effective_dt')) for x in slabs
                            if recovery_dt and as_date(x.get('effective_dt'))
                            and as_date(x.get('effective_dt')) <= recovery_dt]
            matching_slabs=[x for x in slabs
                            if recovery_dt and days is not None and days >= 0
                            and as_date(x.get('effective_dt'))
                            and as_date(x.get('effective_dt')) <= recovery_dt
                            and int(x.get('from_days') or 0) <= days <= int(x.get('to_days') or 0)]
            latest_effective_dt=max((as_date(x.get('effective_dt')) for x in matching_slabs), default=None)
            applicable=[x for x in matching_slabs
                        if latest_effective_dt and as_date(x.get('effective_dt')) == latest_effective_dt]
            applicable.sort(key=lambda x: (int(x.get('from_days') or 0), int(x.get('id') or 0)), reverse=True)
            pct=float(applicable[0].get('commission_percentage') or 0) if applicable else 0.0
            received=float(r.get('recovered_amount') or 0)
            if not sale_dt: match_status='SALE INVOICE NOT MATCHED'
            elif days is not None and days < 0: match_status='RECOVERY BEFORE SALE'
            elif not eligible_dates: match_status='NO EFFECTIVE ACTIVE SLAB'
            elif not applicable: match_status='NO DAY RANGE MATCH'
            else: match_status='MATCHED'
            w.writerow([r['recovery_no'],r['recovery_date'],r['sale_invoiceno'],r['sale_date'],r['agent_code'],r['agent_name'],r['customer_name'],f'{received:.2f}',days,f'{pct:.2f}',f'{received*pct/100:.2f}',applicable[0].get('id') if applicable else 'No matching slab',latest_effective_dt,match_status])
        return StreamingResponse(iter([out.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=commission_report.csv'})
    except Exception as e:
        return HTMLResponse(f'<h3>Commission Export Error</h3><pre>{e}</pre>', status_code=500)
    finally:
        if cur: cur.close()
        if conn: conn.close()


def _stock_report_query(cur, report_date, company_id='', product_id=''):
    """Company-wise and product-wise stock as at a date.

    Opening stock uses the latest tdf_opening_stock.balance_dt within the
    selected Indian financial year and not later than the report date.
    RO and batch are deliberately not part of the report grouping.
    """
    report_dt = date.fromisoformat(report_date)
    fy_start = date(report_dt.year if report_dt.month >= 4 else report_dt.year - 1, 4, 1)
    cur.execute(
        """SELECT MAX(balance_dt) AS snapshot_date
           FROM tdf_opening_stock
           WHERE balance_dt >= %s AND balance_dt <= %s""",
        (fy_start.isoformat(), report_date),
    )
    snapshot_row = cur.fetchone() or {}
    snapshot_date = snapshot_row.get('snapshot_date')
    if snapshot_date and hasattr(snapshot_date, 'isoformat'):
        snapshot_date = snapshot_date.isoformat()

    # Aggregate each source separately before UNION to avoid multiplying
    # quantities when joining company/product master records.
    parts = []
    args = []
    if snapshot_date:
        opening_sql = """
            SELECT os.comp_id AS company_id, os.prod_id AS product_id,
                   SUM(os.qty) AS opening_qty, 0 AS purchased_qty, 0 AS sold_qty,
                   NULL AS last_purchase_date, NULL AS last_sale_date
            FROM tdf_opening_stock os
            WHERE os.balance_dt = %s
        """
        opening_args = [snapshot_date]
        if company_id.strip():
            opening_sql += " AND os.comp_id = %s"; opening_args.append(company_id.strip())
        if product_id.strip():
            opening_sql += " AND os.prod_id = %s"; opening_args.append(product_id.strip())
        opening_sql += " GROUP BY os.comp_id, os.prod_id"
        parts.append(opening_sql); args.extend(opening_args)

    purchase_sql = """
        SELECT pm.company_id AS company_id, pd.product_id AS product_id,
               0 AS opening_qty, SUM(pd.qty) AS purchased_qty, 0 AS sold_qty,
               MAX(pm.purchase_date) AS last_purchase_date, NULL AS last_sale_date
        FROM purchase_master pm
        INNER JOIN purchase_details pd ON pd.purchase_id = pm.id
        WHERE pm.purchase_date <= %s
    """
    purchase_args = [report_date]
    if company_id.strip():
        purchase_sql += " AND pm.company_id = %s"; purchase_args.append(company_id.strip())
    if product_id.strip():
        purchase_sql += " AND pd.product_id = %s"; purchase_args.append(product_id.strip())
    purchase_sql += " GROUP BY pm.company_id, pd.product_id"
    parts.append(purchase_sql); args.extend(purchase_args)

    # Sale rows carry RO, while company is stored on purchase_master.
    # Resolve each RO to its company, then aggregate without displaying RO.
    sales_sql = """
        SELECT ro_company.company_id AS company_id, s.product_id AS product_id,
               0 AS opening_qty, 0 AS purchased_qty, SUM(s.qty) AS sold_qty,
               NULL AS last_purchase_date, MAX(s.sale_date) AS last_sale_date
        FROM sales s
        INNER JOIN (
            SELECT TRIM(ro_no) AS ro_no, MIN(company_id) AS company_id
            FROM purchase_master
            WHERE ro_no IS NOT NULL AND TRIM(ro_no) <> ''
            GROUP BY TRIM(ro_no)
        ) ro_company ON TRIM(s.ro) = ro_company.ro_no
        WHERE s.sale_date <= %s
    """
    sales_args = [report_date]
    if company_id.strip():
        sales_sql += " AND ro_company.company_id = %s"; sales_args.append(company_id.strip())
    if product_id.strip():
        sales_sql += " AND s.product_id = %s"; sales_args.append(product_id.strip())
    sales_sql += " GROUP BY ro_company.company_id, s.product_id"
    parts.append(sales_sql); args.extend(sales_args)

    sql = """
        SELECT x.company_id,
               COALESCE(c.COMP_NAME, CONCAT('Company ', x.company_id)) AS company_name,
               x.product_id,
               COALESCE(pr.PROD_DESC, CONCAT('Product ', x.product_id)) AS product_name,
               SUM(x.opening_qty) AS opening_qty,
               SUM(x.purchased_qty) AS purchased_qty,
               SUM(x.sold_qty) AS sold_qty,
               SUM(x.opening_qty) + SUM(x.purchased_qty) - SUM(x.sold_qty) AS balance_qty,
               MAX(x.last_purchase_date) AS last_purchase_date,
               MAX(x.last_sale_date) AS last_sale_date
        FROM (""" + " UNION ALL ".join(parts) + """) x
        LEFT JOIN mm_company_dtls c ON c.COMP_ID = x.company_id
        LEFT JOIN benfed_fertilizer.mm_product pr ON pr.PROD_ID = x.product_id
        GROUP BY x.company_id, c.COMP_NAME, x.product_id, pr.PROD_DESC
        HAVING SUM(x.opening_qty) <> 0 OR SUM(x.purchased_qty) <> 0 OR SUM(x.sold_qty) <> 0
        ORDER BY company_name, x.product_id
    """
    cur.execute(sql, args)
    rows = cur.fetchall()
    summary = {'opening': 0.0, 'purchased': 0.0, 'sold': 0.0, 'balance': 0.0}
    for r in rows:
        for key in ('opening_qty', 'purchased_qty', 'sold_qty', 'balance_qty'):
            r[key] = float(r.get(key) or 0)
        summary['opening'] += r['opening_qty']
        summary['purchased'] += r['purchased_qty']
        summary['sold'] += r['sold_qty']
        summary['balance'] += r['balance_qty']
    return rows, summary, snapshot_date


@router.get('/stock-report', response_class=HTMLResponse)
async def stock_report(
    request: Request,
    as_on_date: str = Query(''),
    company_id: str = Query(''),
    product_id: str = Query(''),
):
    conn = cur = None
    rows, products, companies = [], [], []
    summary = {'opening': 0.0, 'purchased': 0.0, 'sold': 0.0, 'balance': 0.0}
    report_date = as_on_date.strip() if as_on_date.strip() else date.today().isoformat()
    opening_snapshot_date = None
    try:
        date.fromisoformat(report_date)
        conn = db(); cur = conn.cursor(dictionary=True)
        cur.execute("""SELECT COMP_ID AS id, COMP_NAME AS name
                       FROM mm_company_dtls ORDER BY COMP_NAME""")
        companies = cur.fetchall()
        cur.execute("""SELECT DISTINCT pr.PROD_ID AS id,
                              COALESCE(pr.PROD_DESC, CONCAT('Product ', pr.PROD_ID)) AS name
                       FROM benfed_fertilizer.mm_product pr
                       ORDER BY pr.PROD_ID""")
        products = cur.fetchall()
        rows, summary, opening_snapshot_date = _stock_report_query(cur, report_date, company_id, product_id)
    except Exception as e:
        request.state.report_error = str(e)
    finally:
        if cur: cur.close()
        if conn: conn.close()

    report_dt = date.fromisoformat(report_date)
    fy_year = report_dt.year if report_dt.month >= 4 else report_dt.year - 1
    financial_year = f"{fy_year}-{str(fy_year + 1)[-2:]}"
    return templates.TemplateResponse(request=request, name='stock_report.html', context={
        'request': request, 'rows': rows, 'products': products, 'companies': companies,
        'as_on_date': report_date, 'company_id': company_id, 'product_id': product_id,
        'summary': summary, 'financial_year': financial_year,
        'opening_snapshot_date': opening_snapshot_date,
        'generated_on': date.today().isoformat(),
        'error': getattr(request.state, 'report_error', '')
    })


@router.get('/stock-report/export')
async def stock_report_export(
    as_on_date: str = Query(''),
    company_id: str = Query(''),
    product_id: str = Query(''),
):
    conn = cur = None
    try:
        report_date = as_on_date.strip() if as_on_date.strip() else date.today().isoformat()
        date.fromisoformat(report_date)
        conn = db(); cur = conn.cursor(dictionary=True)
        rows, summary, opening_snapshot_date = _stock_report_query(cur, report_date, company_id, product_id)
        report_dt = date.fromisoformat(report_date)
        fy_year = report_dt.year if report_dt.month >= 4 else report_dt.year - 1
        out = io.StringIO(); w = csv.writer(out)
        w.writerow(['Company-wise Product-wise Stock Report'])
        w.writerow(['Financial Year', f"{fy_year}-{str(fy_year + 1)[-2:]}"])
        w.writerow(['As On Date', report_date])
        w.writerow(['Opening Snapshot Date', opening_snapshot_date or 'No opening snapshot found in selected FY up to As On Date'])
        w.writerow([])
        w.writerow(['Company ID', 'Company', 'Product ID', 'Product', 'Opening Qty', 'Purchased Qty', 'Sold Qty', 'Closing Stock Qty', 'Last Purchase', 'Last Sale'])
        for r in rows:
            w.writerow([r['company_id'], r['company_name'], r['product_id'], r['product_name'],
                        r['opening_qty'], r['purchased_qty'], r['sold_qty'], r['balance_qty'],
                        r['last_purchase_date'] or '', r['last_sale_date'] or ''])
        w.writerow([])
        w.writerow(['GRAND TOTAL', '', '', '', summary['opening'], summary['purchased'], summary['sold'], summary['balance']])
        return StreamingResponse(iter([out.getvalue()]), media_type='text/csv', headers={
            'Content-Disposition': 'attachment; filename=company_product_stock_report.csv'
        })
    except Exception as e:
        return HTMLResponse(f'<h3>Stock Export Error</h3><pre>{e}</pre>', status_code=500)
    finally:
        if cur: cur.close()
        if conn: conn.close()


# ---------------------------------------------------------------------------
# Sales Persons Details Report
# ---------------------------------------------------------------------------
def _sales_person_report_rows(search: str = '', status: str = ''):
    conn = cur = None
    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        sql = """
            SELECT id, employee_code, name, mobile, email, address,
                   joining_date, daily_target, monthly_target, status, user_id
            FROM sales_persons
            WHERE 1=1
        """
        args = []
        if (search or '').strip():
            value = '%' + search.strip() + '%'
            sql += " AND (CAST(employee_code AS CHAR) LIKE %s OR name LIKE %s OR mobile LIKE %s OR email LIKE %s)"
            args.extend([value, value, value, value])
        if status in ('0', '1'):
            sql += ' AND status = %s'
            args.append(int(status))
        sql += ' ORDER BY name, id'
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@router.get('/sales-person-report', response_class=HTMLResponse)
async def sales_person_details_report(request: Request, search: str = Query(''), status: str = Query('')):
    try:
        rows = _sales_person_report_rows(search, status)
        return templates.TemplateResponse(request=request, name='sales_person_report.html', context={
            'request': request, 'rows': rows, 'search': search, 'status': status,
            'total_count': len(rows),
            'active_count': sum(1 for r in rows if str(r.get('status')) == '1'),
            'inactive_count': sum(1 for r in rows if str(r.get('status')) == '0'),
            'generated_on': date.today().isoformat(),
        })
    except Exception as e:
        return HTMLResponse(f'<h3>Sales Persons Report Error</h3><pre>{e}</pre>', status_code=500)


@router.get('/sales-person-report/export/excel')
async def sales_person_details_report_excel(search: str = '', status: str = ''):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
        rows = _sales_person_report_rows(search, status)
        wb = Workbook()
        ws = wb.active
        ws.title = 'Sales Persons'
        ws.append(['SALES PERSONS DETAILS REPORT'])
        ws.append(['Generated on', date.today().isoformat()])
        ws.append([])
        headers = ['ID', 'Employee Code', 'Name', 'Mobile', 'Email', 'Address', 'Joining Date', 'Daily Target', 'Monthly Target', 'Status', 'User ID']
        ws.append(headers)
        for cell in ws[4]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='174334')
            cell.alignment = Alignment(horizontal='center')
        for r in rows:
            status_text = 'Active' if str(r.get('status')) == '1' else ('Inactive' if str(r.get('status')) == '0' else str(r.get('status') or ''))
            ws.append([r.get('id'), r.get('employee_code'), r.get('name'), r.get('mobile'), r.get('email'), r.get('address'), str(r.get('joining_date') or ''), r.get('daily_target'), r.get('monthly_target'), status_text, r.get('user_id')])
        ws.freeze_panes = 'A5'
        ws.auto_filter.ref = f'A4:K{max(4, ws.max_row)}'
        for col in ws.columns:
            width = min(max(max(len(str(c.value or '')) for c in col) + 2, 12), 38)
            ws.column_dimensions[get_column_letter(col[0].column)].width = width
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return StreamingResponse(output, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename="sales_persons_details_report.xlsx"'})
    except Exception as e:
        return HTMLResponse(f'<h3>Sales Persons Excel Export Error</h3><pre>{e}</pre>', status_code=500)


# ---------------------------------------------------------------------
# CUSTOMER LEDGER
# Combines opening balance, sales invoices and customer recoveries.
# Sales can contain multiple product rows per invoice, so each invoice
# is grouped and its header net_amount is counted only once.
# ---------------------------------------------------------------------
@router.get('/customer-ledger', response_class=HTMLResponse)
async def customer_ledger(request: Request, customer_id: str = Query(''), financial_year: str = Query(''), from_date: str = Query(''), to_date: str = Query('')):
    """Customer ledger with opening balance from customer_op for selected FY."""
    conn = cur = None
    customers, rows, selected_customer = [], [], None
    summary = {'opening': 0.0, 'opening_debit': 0.0, 'opening_credit': 0.0, 'debit': 0.0, 'credit': 0.0, 'closing': 0.0, 'closing_debit': 0.0, 'closing_credit': 0.0}
    error = ''
    today = date.today()
    current_fy_start = today.year if today.month >= 4 else today.year - 1
    if not financial_year:
        financial_year = f'{current_fy_start}-{str(current_fy_start + 1)[-2:]}'
    try:
        fy_start_year = int(financial_year.split('-')[0])
        if financial_year != f'{fy_start_year}-{str(fy_start_year + 1)[-2:]}':
            raise ValueError
    except (ValueError, IndexError):
        fy_start_year = current_fy_start
        financial_year = f'{fy_start_year}-{str(fy_start_year + 1)[-2:]}'
    fy_start, fy_end = f'{fy_start_year}-04-01', f'{fy_start_year + 1}-03-31'
    from_date, to_date = (from_date or fy_start).strip(), (to_date or fy_end).strip()
    # Financial-year options are read dynamically from customer_op.
    # Any year for which an opening-balance row exists (1 April) appears here.
    financial_years = []
    try:
        conn = db(); cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT DISTINCT YEAR(balance_dt) AS fy_start_year
            FROM customer_op
            WHERE MONTH(balance_dt) = 4 AND DAY(balance_dt) = 1
            ORDER BY fy_start_year DESC
        """)
        available_fy_years = {int(row['fy_start_year']) for row in cur.fetchall() if row.get('fy_start_year')}
        # Keep the current FY selectable even before its customer_op rows are entered.
        available_fy_years.add(current_fy_start)
        # Preserve a valid FY passed in the URL, even if its opening row is not created yet.
        available_fy_years.add(fy_start_year)
        financial_years = [
            {'value': f'{y}-{str(y + 1)[-2:]}', 'label': f'{y}-{str(y + 1)[-2:]}'}
            for y in sorted(available_fy_years, reverse=True)
        ]
        cur.execute("SELECT id, customer_code, customer_name, opening_balance FROM customers ORDER BY customer_name")
        customers = cur.fetchall()
        if customer_id:
            cur.execute("SELECT id, customer_code, customer_name, opening_balance FROM customers WHERE id=%s", (customer_id,))
            selected_customer = cur.fetchone()
        if selected_customer:
            # Opening balance comes from the exact 1-April row in customer_op.
            cur.execute("SELECT COALESCE(amt,0) AS opening_amount FROM customer_op WHERE customer_code=%s AND balance_dt=%s LIMIT 1", (selected_customer['customer_code'], fy_start))
            op = cur.fetchone()
            opening = float((op or {}).get('opening_amount') or 0)
            cur.execute("""
                SELECT txn_date, txn_type, reference_no, description, debit, credit
                FROM (
                    SELECT MIN(s.sale_date) AS txn_date, 'SALE' AS txn_type,
                           s.sale_invoice_no AS reference_no,
                           CONCAT('Sales Invoice ', s.sale_invoice_no) AS description,
                           MAX(s.net_amount) AS debit, 0 AS credit, 1 AS sort_order
                    FROM sales s WHERE s.customer_id=%s AND s.sale_date >= %s AND s.sale_date <= %s
                    GROUP BY s.sale_invoice_no
                    UNION ALL
                    SELECT cr.recovery_date AS txn_date, 'RECOVERY' AS txn_type,
                           cr.recovery_no AS reference_no,
                           CONCAT('Money Received - ', cr.sale_invoiceno) AS description,
                           0 AS debit, cr.recovered_amount AS credit, 2 AS sort_order
                    FROM customer_recoveries cr WHERE cr.customer_id=%s AND cr.recovery_date >= %s AND cr.recovery_date <= %s
                ) ledger_txn ORDER BY txn_date, sort_order, reference_no
            """, (customer_id, from_date, to_date, customer_id, from_date, to_date))
            transactions = cur.fetchall()
            # Bring forward transactions between FY start and a later selected From Date.
            if from_date > fy_start:
                cur.execute("""
                    SELECT COALESCE(SUM(x.debit),0) AS debit, COALESCE(SUM(x.credit),0) AS credit
                    FROM (
                        SELECT s.sale_invoice_no, MAX(s.net_amount) AS debit, 0 AS credit
                        FROM sales s WHERE s.customer_id=%s AND s.sale_date >= %s AND s.sale_date < %s GROUP BY s.sale_invoice_no
                        UNION ALL
                        SELECT cr.recovery_no, 0 AS debit, cr.recovered_amount AS credit
                        FROM customer_recoveries cr WHERE cr.customer_id=%s AND cr.recovery_date >= %s AND cr.recovery_date < %s
                    ) x
                """, (customer_id, fy_start, from_date, customer_id, fy_start, from_date))
                prior = cur.fetchone()
                opening += float(prior.get('debit') or 0) - float(prior.get('credit') or 0)
            balance = opening; summary['opening'] = opening
            # Positive opening balance is Debit; negative opening balance is Credit.
            summary['opening_debit'] = opening if opening >= 0 else 0.0
            summary['opening_credit'] = abs(opening) if opening < 0 else 0.0
            for txn in transactions:
                debit, credit = float(txn.get('debit') or 0), float(txn.get('credit') or 0)
                balance += debit - credit
                item = dict(txn); item.update({'debit': debit, 'credit': credit, 'balance': balance,
                                               'balance_debit': balance if balance >= 0 else 0.0,
                                               'balance_credit': abs(balance) if balance < 0 else 0.0})
                rows.append(item); summary['debit'] += debit; summary['credit'] += credit
            summary['closing'] = balance
            summary['closing_debit'] = balance if balance >= 0 else 0.0
            summary['closing_credit'] = abs(balance) if balance < 0 else 0.0
        context = {'request': request, 'customers': customers, 'selected_customer': selected_customer,
                   'customer_id': customer_id, 'financial_year': financial_year, 'financial_years': financial_years,
                   'fy_start': fy_start, 'fy_end': fy_end, 'from_date': from_date, 'to_date': to_date,
                   'rows': rows, 'summary': summary, 'error': error}
        return templates.TemplateResponse(request=request, name='customer_ledger.html', context=context)
    except Exception as exc:
        error = str(exc)
        context = {'request': request, 'customers': customers, 'selected_customer': selected_customer,
                   'customer_id': customer_id, 'financial_year': financial_year, 'financial_years': financial_years,
                   'fy_start': fy_start, 'fy_end': fy_end, 'from_date': from_date, 'to_date': to_date,
                   'rows': rows, 'summary': summary, 'error': error}
        return templates.TemplateResponse(request=request, name='customer_ledger.html', context=context)
    finally:
        if cur: cur.close()
        if conn: conn.close()
