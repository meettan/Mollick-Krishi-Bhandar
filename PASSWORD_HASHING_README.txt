Mollick Krishi Bhandar FASTAPI PASSWORD LOGIN FIX
=================================

This project archive is based on the ZIP uploaded in this conversation.
Existing routers, templates, and application features have been retained.

PASSWORD BEHAVIOUR
------------------
- New user passwords are stored as salted PBKDF2-HMAC-SHA256 hashes.
- Login verifies the entered original password against the stored hash.
- A password hash is not decrypted.
- Every new hash has a random salt. Therefore, two hashes made from the same
  original password are expected to look different.
- The login form must submit the exact password entered at account creation.
  Do not strip, lowercase, uppercase, or otherwise change the password.
- Legacy plaintext records are upgraded after a successful login.
- The users.password column is altered to VARCHAR(255) during startup.

DEPLOYMENT
----------
1. Back up your project folder and MySQL database.
2. Extract this archive.
3. Copy the updated app/database.py into your current project, or deploy the
   full project while preserving any local changes made after the uploaded ZIP.
4. Confirm app/config.py has the correct database connection settings.
5. Start from the project folder, for example:
       uvicorn app.main:app --reload --host 127.0.0.1 --port 8081
6. On startup, ensure_login_database() will widen users.password to VARCHAR(255).

TEST A STORED HASH
------------------
From the project root:
       python check_password_hash.py
Enter the original password (not the hash), then paste the full stored hash.
The script prints MATCH or NO MATCH and does not print the password.

IMPORTANT FOR THE TWO HASHES REPORTED
-------------------------------------
The two hashes have different salts, which is normal. They can both verify
successfully only if they were generated from the same original password.
If the first verifies and the second does not, then either:
- the second hash was generated from a different password,
- the password typed at login differs (including capitalization or symbols),
- or the stored value was altered/truncated before verification.

If a user no longer knows the original password, reset it through an
administrator-authorized reset flow. Do not try to decrypt the hash.

SECURITY
--------
The uploaded project contains a development SECRET_KEY value in config.py.
Set a long, random, private SECRET_KEY before production deployment.
Change the default admin password if the default account is in use.
