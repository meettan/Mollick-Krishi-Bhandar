from pathlib import Path
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

import mysql.connector
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from .config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME
from .sidebar_context import sidebar_context

BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates"),
    context_processors=[sidebar_context],
)

router = APIRouter(prefix="/reports/company-payment", tags=["Company Payment Report"])
DB = {"host": DB_HOST, "user": DB_USER, "password": DB_PASSWORD, "database": DB_NAME}


def financial_year_bounds(financial_year: str):
    """Convert an Indian financial year such as 2026-27 to 1-Apr through 31-Mar."""
    try:
        start_year_text, end_year_text = financial_year.split("-", 1)
        start_year = int(start_year_text)
        end_year = int(end_year_text)
    except (ValueError, AttributeError):
        raise ValueError("Please select a valid financial year.")
    if end_year != (start_year + 1) % 100:
        raise ValueError("Invalid financial year.")
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def financial_year_options():
    current = date.today()
    current_start = current.year if current.month >= 4 else current.year - 1
    return [
        {
            "value": f"{year}-{(year + 1) % 100:02d}",
            "label": f"FY {year}-{(year + 1) % 100:02d}",
            "start": f"{year}-04-01",
            "end": f"{year + 1}-03-31",
        }
        for year in range(current_start - 5, current_start + 2)
    ]


def db():
    return mysql.connector.connect(**DB)


def parse_report_dates(from_date: str, to_date: str):
    try:
        start = datetime.strptime(from_date, "%Y-%m-%d").date()
        end = datetime.strptime(to_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValueError("Please enter valid From Date and To Date.")
    if start > end:
        raise ValueError("From Date cannot be later than To Date.")
    return start, end


def fetch_companies():
    conn = cur = None
    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT COMP_ID AS id, COMP_NAME AS name
            FROM mm_company_dtls
            ORDER BY COMP_NAME
        """)
        return cur.fetchall()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def fetch_report_rows(start, end, company_id=None):
    conn = cur = None
    try:
        conn = db()
        cur = conn.cursor(dictionary=True)
        sql = """
            SELECT
                cp.id,
                cp.payment_no,
                cp.payment_date,
                cp.paid_amount,
                cp.payment_mode,
                cp.reference_no,
                cp.remarks,
                cp.company_id,
                COALESCE(c.COMP_NAME, '') AS company_name,
                pm.purchase_no,
                COALESCE(pm.invoice_no, '') AS invoice_no
            FROM company_payments cp
            INNER JOIN purchase_master pm ON pm.id = cp.purchase_id
            LEFT JOIN mm_company_dtls c ON c.COMP_ID = cp.company_id
            WHERE cp.payment_date >= %s
              AND cp.payment_date <= %s
        """
        params = [start, end]
        if company_id:
            sql += " AND cp.company_id = %s"
            params.append(company_id)
        sql += " ORDER BY c.COMP_NAME, cp.payment_date, cp.id"
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        for row in rows:
            row["paid_amount"] = Decimal(str(row["paid_amount"] or "0.00"))
        return rows
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def report_context(request, start, end, company_id, companies, rows, error=""):
    company_totals = {}
    grand_total = Decimal("0.00")
    for row in rows:
        name = row["company_name"] or "(Company not found)"
        company_totals[name] = company_totals.get(name, Decimal("0.00")) + row["paid_amount"]
        grand_total += row["paid_amount"]
    return {
        "request": request,
        "from_date": start.isoformat(),
        "to_date": end.isoformat(),
        "selected_company_id": str(company_id or ""),
        "companies": companies,
        "rows": rows,
        "company_totals": sorted(company_totals.items()),
        "grand_total": grand_total,
        "error": error,
    }


@router.get("/", response_class=HTMLResponse)
async def company_payment_report(
    request: Request,
    financial_year: str = Query(default=""),
    from_date: str = Query(default=""),
    to_date: str = Query(default=""),
    company_id: int = Query(default=0),
):
    today = date.today()
    fy_options = financial_year_options()
    current_fy = next((item["value"] for item in fy_options
                       if item["start"] <= today.isoformat() <= item["end"]),
                      fy_options[-2]["value"])
    selected_fy = financial_year or current_fy
    try:
        fy_start, fy_end = financial_year_bounds(selected_fy)
        # When no custom dates are supplied, show the selected FY to date.
        start_text = from_date or fy_start.isoformat()
        end_text = to_date or min(fy_end, today).isoformat()
        start, end = parse_report_dates(start_text, end_text)
        if start < fy_start or end > fy_end:
            raise ValueError("From Date and To Date must be within the selected financial year.")
        companies = fetch_companies()
        rows = fetch_report_rows(start, end, company_id or None)
        context = report_context(request, start, end, company_id, companies, rows)
        context["financial_year"] = selected_fy
        context["financial_year_options"] = fy_options
    except ValueError as exc:
        companies = fetch_companies()
        fallback_start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
        context = report_context(
            request, fallback_start, today, company_id, companies, [],
            error=str(exc)
        )
        context["from_date"] = from_date
        context["to_date"] = to_date
        context["financial_year"] = selected_fy
        context["financial_year_options"] = fy_options
    return templates.TemplateResponse(
        request=request,
        name="company_payment_report.html",
        context=context,
    )


@router.get("/export/excel")
async def export_company_payment_excel(
    from_date: str = Query(...),
    to_date: str = Query(...),
    company_id: int = Query(default=0),
):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    start, end = parse_report_dates(from_date, to_date)
    rows = fetch_report_rows(start, end, company_id or None)

    wb = Workbook()
    ws = wb.active
    ws.title = "Company Payments"
    ws.append(["Company Payment Report"])
    ws.append([f"From: {start:%d-%m-%Y}", f"To: {end:%d-%m-%Y}"])
    ws.append([])
    headers = [
        "Sl. No.", "Payment Date", "Company", "Payment No.",
        "Purchase Invoice No.", "Purchase No.", "Payment Mode",
        "Reference No.", "Amount", "Remarks"
    ]
    ws.append(headers)
    for cell in ws[4]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(horizontal="center")
    total = Decimal("0.00")
    for index, row in enumerate(rows, 1):
        total += row["paid_amount"]
        ws.append([
            index,
            row["payment_date"].strftime("%d-%m-%Y") if row["payment_date"] else "",
            row["company_name"],
            row["payment_no"],
            row["invoice_no"],
            row["purchase_no"],
            row["payment_mode"],
            row["reference_no"] or "",
            float(row["paid_amount"]),
            row["remarks"] or "",
        ])
    ws.append([])
    ws.append(["", "", "", "", "", "", "", "Grand Total", float(total)])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    widths = [10, 15, 28, 24, 22, 20, 18, 22, 16, 35]
    for i, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    for row in ws.iter_rows(min_row=5, min_col=9, max_col=9):
        row[0].number_format = '#,##0.00'
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    filename = f"company_payment_report_{start:%Y%m%d}_{end:%Y%m%d}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/pdf")
async def export_company_payment_pdf(
    from_date: str = Query(...),
    to_date: str = Query(...),
    company_id: int = Query(default=0),
):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    start, end = parse_report_dates(from_date, to_date)
    rows = fetch_report_rows(start, end, company_id or None)
    output = BytesIO()
    doc = SimpleDocTemplate(
        output, pagesize=landscape(A4),
        rightMargin=10 * mm, leftMargin=10 * mm,
        topMargin=10 * mm, bottomMargin=10 * mm,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Company Payment Report", styles["Title"]),
        Paragraph(f"From {start:%d-%m-%Y} To {end:%d-%m-%Y}", styles["Normal"]),
        Spacer(1, 5 * mm),
    ]
    data = [[
        "Sl.", "Payment Date", "Company", "Payment No.",
        "Invoice No.", "Purchase No.", "Mode", "Reference", "Amount"
    ]]
    total = Decimal("0.00")
    for index, row in enumerate(rows, 1):
        total += row["paid_amount"]
        data.append([
            str(index),
            row["payment_date"].strftime("%d-%m-%Y") if row["payment_date"] else "",
            str(row["company_name"] or "")[:28],
            str(row["payment_no"] or ""),
            str(row["invoice_no"] or ""),
            str(row["purchase_no"] or ""),
            str(row["payment_mode"] or ""),
            str(row["reference_no"] or "")[:20],
            f'{row["paid_amount"]:,.2f}',
        ])
    data.append(["", "", "", "", "", "", "", "Grand Total", f"{total:,.2f}"])
    table = Table(data, repeatRows=1, colWidths=[
        9*mm, 22*mm, 42*mm, 31*mm, 25*mm, 25*mm, 20*mm, 30*mm, 25*mm
    ])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E8EEF5")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    doc.build(story)
    output.seek(0)
    filename = f"company_payment_report_{start:%Y%m%d}_{end:%Y%m%d}.pdf"
    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
