"""Shared sidebar context for templates rendered by individual routers."""
from .database import get_connection

MENU_ITEMS = {
    "company", "product", "customer", "sales_person", "commission_slabs",
    "purchase", "sale", "sale_invoices", "receipts", "purchase_report", "company_payment_report",
    "sale_report", "stock_report", "commission_report", "collection_report", "customer_ledger", "create_user", "user_management",
}
ROLE_DEFAULTS = {
    "ADMIN": set(MENU_ITEMS),
    "AGENT": {"customer", "sale", "sale_invoices", "receipts", "sale_report", "stock_report", "commission_report", "collection_report", "customer_ledger"},
    "OPERATOR": {"product", "customer", "purchase", "company_payment_report", "sale", "sale_invoices", "receipts"},
    "USER": {"product", "customer", "sale", "sale_invoices"},
}

def sidebar_context(request):
    """Provide user_type and allowed_menus wherever sidebar.html is included."""
    role = str(request.session.get("user_type", "USER")).upper()
    user_id = request.session.get("user_id")
    if role == "ADMIN":
        menus = set(MENU_ITEMS)
    elif not user_id:
        menus = set()
    else:
        conn = None
        cur = None
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT menu_key FROM user_menu_permissions WHERE user_id=%s", (user_id,))
            saved = {row[0] for row in cur.fetchall()}
            if not saved:
                menus = set(ROLE_DEFAULTS.get(role, ROLE_DEFAULTS["USER"]))
            elif "__custom__" in saved and len(saved) == 1:
                menus = set()
            else:
                menus = saved - {"__custom__"}
        except Exception as exc:
            # Keep the page available if the permissions table is unavailable;
            # role defaults are safer than hiding every menu.
            print("Sidebar context lookup error:", exc)
            menus = set(ROLE_DEFAULTS.get(role, ROLE_DEFAULTS["USER"]))
        finally:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()
    return {"user_type": role, "allowed_menus": menus}
