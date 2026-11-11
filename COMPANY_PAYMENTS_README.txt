COMPANY PAYMENT MODULE - FULL PROJECT PACKAGE
=============================================

URL: /company-payments/
Menu: Transactions > Company Payments

WHAT THIS VERSION DOES
- The New Company Payment form is ALWAYS visible on the page.
- There is no New Payment button, hidden card, <details> toggle, or click-to-open JavaScript.
  This deliberately removes the interaction that was failing in the previous versions.
- Select a company, then select one outstanding purchase invoice for that company.
- Enter one partial or full payment. More than one payment can be entered against the same invoice.
- Each payment is saved as a separate row in company_payments.
- purchase_master.paid_amount and purchase_master.outstanding_amount are updated in the same transaction.
- Payment history is shown below the form.
- Payment amount must be greater than zero and cannot exceed the invoice outstanding amount.
- On startup/page load, the module checks the company_payments.id field. If an existing table
  matches the supplied old schema and its IDs are unique/non-null, it adds the missing primary
  key and AUTO_INCREMENT so the application can insert payment rows without supplying id.

DATABASE
- Existing database: python_login (connection values are in app/config.py).
- Purchase table expected: purchase_master with id, company_id, purchase_no, invoice_no,
  purchase_date, net_amount, paid_amount, outstanding_amount.
- Company table expected: mm_company_dtls with COMP_ID and COMP_NAME.
- SQL create script: COMPANY_PAYMENTS_TABLE.sql.

INSTALL
1. Stop the BENFED application.
2. Make a backup of your current project folder and MySQL database.
3. Extract this ZIP.
4. Copy/replace the project files into your BENFED project folder. Preserve your own
   app/config.py database credentials if they differ from this package.
5. Start the app using run_8080.bat.
6. Open http://127.0.0.1:8080/company-payments/ and press Ctrl+F5.
7. The payment form should be visible immediately; no New Payment click is required.

NOTE
This ZIP is based on the previously uploaded BENFED project available in this conversation.
If your current local project has newer changes, back it up and compare before replacing it.
