import hashlib
import hmac
import secrets

import mysql.connector

from .config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME


# Keep this value consistent for all newly created passwords.
PASSWORD_HASH_ITERATIONS = 600_000
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_PREFIX = PASSWORD_HASH_ALGORITHM + "$"


def hash_password(password: str) -> str:
    """
    Create a salted PBKDF2-HMAC-SHA256 hash.

    Each call generates a NEW random salt, so the same password will normally
    produce a different stored hash each time. This is expected.
    """
    if not isinstance(password, str) or password == "":
        raise ValueError("Password must be a non-empty string.")

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )

    return (
        f"{PASSWORD_HASH_ALGORITHM}${PASSWORD_HASH_ITERATIONS}"
        f"${salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, stored_value: str) -> bool:
    """
    Verify a password against its stored PBKDF2 hash.

    Do NOT hash the supplied password and compare the resulting strings:
    each hash has a different random salt. Recalculate using the salt stored
    in the database and compare the digest with constant-time comparison.
    """
    if not isinstance(password, str) or stored_value is None:
        return False

    stored_value = str(stored_value)

    if stored_value.startswith(PASSWORD_HASH_PREFIX):
        try:
            parts = stored_value.split("$")
            if len(parts) != 4:
                return False

            algorithm, rounds_text, salt_hex, digest_hex = parts

            if algorithm != PASSWORD_HASH_ALGORITHM:
                return False

            rounds = int(rounds_text)
            if not 100_000 <= rounds <= 2_000_000:
                return False

            salt = bytes.fromhex(salt_hex)
            expected_digest = bytes.fromhex(digest_hex)

            if len(salt) != 16 or len(expected_digest) != 32:
                return False

            actual_digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt,
                rounds,
            )

            return hmac.compare_digest(actual_digest, expected_digest)

        except (ValueError, TypeError):
            return False

    # Backward compatibility for old plaintext records only.
    # A successful login upgrades the record to PBKDF2 immediately.
    try:
        return hmac.compare_digest(
            stored_value.encode("utf-8"),
            password.encode("utf-8"),
        )
    except (AttributeError, TypeError):
        return False


def get_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )


def ensure_login_database():
    """
    Create the users table and ensure password has enough room for the
    complete PBKDF2 hash. CREATE TABLE IF NOT EXISTS alone does not update
    an already-existing table, so ALTER TABLE is also required.
    """
    db = get_connection()
    cur = db.cursor()

    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL UNIQUE,
                password VARCHAR(255) NOT NULL,
                user_type VARCHAR(20) NOT NULL DEFAULT 'USER'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

        cur.execute(
            "ALTER TABLE users MODIFY COLUMN password VARCHAR(255) NOT NULL"
        )

        cur.execute(
            "SELECT id FROM users WHERE username=%s LIMIT 1",
            ("admin",),
        )

        if cur.fetchone() is None:
            cur.execute(
                """
                INSERT INTO users (username, password, user_type)
                VALUES (%s, %s, %s)
                """,
                ("admin", hash_password("1234"), "ADMIN"),
            )

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        cur.close()
        db.close()


def create_user_record(username: str, password: str, user_type: str):
    """Insert a new user with a fresh salted password hash."""
    username = (username or "").strip()
    user_type = (user_type or "USER").strip().upper()

    if not username:
        raise ValueError("Username is required.")

    if not isinstance(password, str) or password == "":
        raise ValueError("Password is required.")

    password_hash = hash_password(password)

    db = get_connection()
    cur = db.cursor()

    try:
        cur.execute(
            """
            INSERT INTO users (username, password, user_type)
            VALUES (%s, %s, %s)
            """,
            (username, password_hash, user_type),
        )
        db.commit()
        return cur.lastrowid

    except Exception:
        db.rollback()
        raise

    finally:
        cur.close()
        db.close()


def authenticate_user(username: str, password: str):
    """
    Authenticate using the original password entered in the login form.
    Passwords are never decrypted.
    """
    username = (username or "").strip()

    # Do not strip or otherwise modify password. Verify the exact input.
    if not username or not isinstance(password, str) or password == "":
        return None

    db = get_connection()
    cur = db.cursor(dictionary=True)

    try:
        cur.execute(
            """
            SELECT id, username, password, user_type
            FROM users
            WHERE username=%s
            LIMIT 1
            """,
            (username,),
        )
        row = cur.fetchone()

        if not row:
            return None

        stored_value = row.get("password")

        if not verify_password(password, stored_value):
            return None

        # Upgrade legacy plaintext values after a successful login.
        if not str(stored_value).startswith(PASSWORD_HASH_PREFIX):
            cur_update = db.cursor()
            try:
                cur_update.execute(
                    "UPDATE users SET password=%s WHERE id=%s",
                    (hash_password(password), row["id"]),
                )
                db.commit()
            finally:
                cur_update.close()

        # Never return the password hash to the caller/session.
        row.pop("password", None)
        return row

    finally:
        cur.close()
        db.close()


def reset_user_password(username: str, new_password: str) -> bool:
    """
    Reset a user's password. Call this only from an authenticated,
    administrator-authorized password-reset route.
    """
    username = (username or "").strip()
    new_hash = hash_password(new_password)

    db = get_connection()
    cur = db.cursor()

    try:
        cur.execute(
            "UPDATE users SET password=%s WHERE username=%s",
            (new_hash, username),
        )
        db.commit()
        return cur.rowcount > 0

    except Exception:
        db.rollback()
        raise

    finally:
        cur.close()
        db.close()
