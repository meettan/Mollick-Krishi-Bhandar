BENFED Role-Based Menu Permissions
=================================

Changes included:
- Adds AGENT and OPERATOR user types (along with USER and ADMIN).
- Adds a user_menu_permissions table automatically at application startup.
- Adds a Permissions action for each user in User Management.
- Admin can select which menu links each user can see.
- Server-side middleware blocks access to a menu URL when the logged-in user lacks permission.
- Dashboard and My Profile remain available to signed-in users.
- New users with no saved custom permissions use their role defaults.

Role defaults:
- ADMIN: all menus (admin always has full access)
- AGENT: Customer Master, Sales, Sales Invoices, Money Received, Sale Report, Stock Report
- OPERATOR: Product Master, Customer Master, Purchase, Sales, Sales Invoices, Money Received
- USER: Product Master, Customer Master, Sales, Sales Invoices

Install:
1. Stop the currently running app.
2. Back up your current project folder and database.
3. Extract this ZIP and replace the project files with the included files, preserving your own config.py database settings if they differ.
4. Make sure MySQL database `python_login` exists and DB settings in app/config.py are correct.
5. Start the app using your normal command, for example:
   uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
6. Log in as admin, open User Management, and click Permissions next to a user.
7. Select menus and click Save Permissions.

Important:
- Existing users without custom permissions receive the default menus for their role.
- Admin's access is not restricted by menu permissions.
- This patch keeps the existing password/authentication behavior unchanged. For a production deployment, passwords should be stored using a secure password hash and SECRET_KEY should be changed.
