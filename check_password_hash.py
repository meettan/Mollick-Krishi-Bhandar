"""
Password hash diagnostic for BENFED FastAPI.

Run from the project root:
    python check_password_hash.py

Enter the exact original password used when creating the account, then paste
the stored hash. The password is not printed or saved.
"""
import getpass

from app.database import verify_password

print("Mollick Krishi Bhandar password hash diagnostic")
print("This checks a password against one stored hash.")
entered_password = getpass.getpass("Enter the original password: ")
stored_hash = input("Paste the complete database hash: ").strip()

if verify_password(entered_password, stored_hash):
    print("RESULT: MATCH - this password belongs to this hash.")
else:
    print("RESULT: NO MATCH - password and hash do not belong together.")
