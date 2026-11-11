COMPANY PAYMENT REPORT
======================

Menu: Reports > Company Payment Report
URL: /reports/company-payment/

Features
--------
1. Select an Indian financial year (1 April to 31 March).
2. The report initially shows payments from 1 April of the selected/current FY
   through today's date (for the current FY).
3. Change From Date and To Date to view any custom period within that FY.
4. Optionally select one company, or keep All Companies.
5. The report displays payment-wise details, grand total, and company-wise totals.
6. Export the filtered result to Excel or PDF.

Data source
-----------
company_payments joined to purchase_master and mm_company_dtls.
The report uses payment_date and paid_amount, so partial payments are reported
as individual payment transactions and totals reflect actual payment dates.

URL examples
------------
/reports/company-payment/
/reports/company-payment/?financial_year=2025-26&from_date=2025-04-01&to_date=2025-09-30

Installation
------------
Replace the project files with the contents of this updated package after taking
a backup. Preserve your existing app/config.py database credentials.
The report router and Reports menu item are registered in app/main.py and
templates/sidebar.html. No database table changes are required.
