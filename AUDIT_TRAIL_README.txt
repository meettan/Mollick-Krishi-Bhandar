AUDIT TRAIL - FULL PROJECT UPDATE

This project version adds an administrator-only Audit Trail screen using the supplied td_audit_trail schema (id, login_dt, user_id, terminal_name, logout).

1. Back up your existing project folder first.
2. Extract this ZIP and copy the inner benfed_fastapi_login folder over your existing project folder, allowing files to be replaced.
3. Check app/config.py and confirm the database settings point to your existing application database. The table is created in the configured database; this package does not change DB_NAME.
4. Start the app using run_8080.bat (or your usual start command). Startup creates td_audit_trail if missing.
5. Sign in as an ADMIN user and choose Administration > Audit Trail, or open http://127.0.0.1:8080/audit-trail.
6. Successful logins create a row with login time, username in user_id, and client IP in terminal_name. Logout updates that same row before clearing the session, so user_id is not lost.
7. Use filters and Export CSV to review/download records.

The supplied SQL dump uses the column named user_id to store login names such as demo; this implementation follows that convention. Existing data is not deleted.
