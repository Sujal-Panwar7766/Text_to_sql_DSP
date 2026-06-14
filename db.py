import hashlib
import hmac
import json
import os
import re
import tempfile
import time
from functools import lru_cache
from pathlib import Path

import mysql.connector
from env_loader import load_project_env

load_project_env()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "mydb"),
}

DB_CONNECTION_TIMEOUT = int(os.getenv("DB_CONNECTION_TIMEOUT", "5"))

PASSWORD_ITERATIONS = 100_000


def _env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _looks_like_pem(value):
    return "-----BEGIN" in value


@lru_cache(maxsize=None)
def _materialize_secret_file(prefix, value):
    if not value:
        return None

    if not _looks_like_pem(value):
        return value

    secret_dir = Path(tempfile.gettempdir()) / "ai_text_to_sql_secrets"
    secret_dir.mkdir(parents=True, exist_ok=True)

    secret_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    secret_path = secret_dir / f"{prefix}_{secret_hash}.pem"
    secret_path.write_text(value, encoding="utf-8")
    return str(secret_path)


def _build_ssl_config():
    if _env_flag("DB_SSL_DISABLED", default=False):
        return {}

    ssl_ca = _materialize_secret_file("db_ssl_ca", os.getenv("DB_SSL_CA", "").strip())
    ssl_cert = _materialize_secret_file("db_ssl_cert", os.getenv("DB_SSL_CERT", "").strip())
    ssl_key = _materialize_secret_file("db_ssl_key", os.getenv("DB_SSL_KEY", "").strip())

    ssl_config = {}
    if ssl_ca:
        ssl_config["ssl_ca"] = ssl_ca
    if ssl_cert:
        ssl_config["ssl_cert"] = ssl_cert
    if ssl_key:
        ssl_config["ssl_key"] = ssl_key

    if ssl_config:
        ssl_config["ssl_verify_cert"] = _env_flag("DB_SSL_VERIFY_CERT", default=True)

    return ssl_config


DB_SSL_CONFIG = _build_ssl_config()


def get_connection():
    return mysql.connector.connect(
        **DB_CONFIG,
        **DB_SSL_CONFIG,
        connection_timeout=DB_CONNECTION_TIMEOUT,
    )


def get_server_connection():
    server_config = DB_CONFIG.copy()
    server_config.pop("database", None)
    return mysql.connector.connect(
        **server_config,
        **DB_SSL_CONFIG,
        connection_timeout=DB_CONNECTION_TIMEOUT,
    )


def ensure_database_exists():
    conn = get_server_connection()
    cursor = conn.cursor()
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_CONFIG['database']}`")
    conn.commit()
    conn.close()


def ensure_users_table():
    ensure_database_exists()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            full_name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_workspaces (
            user_id INT PRIMARY KEY,
            workspace_json LONGTEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.commit()
    conn.close()


def normalize_email(email):
    return email.strip().lower()


def hash_password(password):
    salt = os.urandom(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return f"{PASSWORD_ITERATIONS}${salt.hex()}${derived_key.hex()}"


def verify_password(password, stored_password_hash):
    try:
        iterations_str, salt_hex, stored_hash_hex = stored_password_hash.split("$", 2)
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(stored_hash_hex)
    except (ValueError, TypeError):
        return False

    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(derived_key, expected_hash)


def create_user(full_name, email, password):
    normalized_email = normalize_email(email)
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id FROM users WHERE email = %s", (normalized_email,))
    existing_user = cursor.fetchone()
    if existing_user:
        conn.close()
        return None, "An account with this email already exists."

    password_hash = hash_password(password)
    cursor.execute(
        """
        INSERT INTO users (full_name, email, password_hash)
        VALUES (%s, %s, %s)
        """,
        (full_name.strip(), normalized_email, password_hash),
    )
    conn.commit()

    user_id = cursor.lastrowid
    conn.close()
    return (
        {
            "id": user_id,
            "full_name": full_name.strip(),
            "email": normalized_email,
        },
        None,
    )


def authenticate_user(email, password):
    normalized_email = normalize_email(email)
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT id, full_name, email, password_hash
        FROM users
        WHERE email = %s
        """,
        (normalized_email,),
    )
    user = cursor.fetchone()
    conn.close()

    if not user or not verify_password(password, user["password_hash"]):
        return None

    return {
        "id": user["id"],
        "full_name": user["full_name"],
        "email": user["email"],
    }


def save_user_workspace(user_id, workspace_state):
    conn = get_connection()
    cursor = conn.cursor()
    workspace_json = json.dumps(workspace_state)
    cursor.execute(
        """
        INSERT INTO user_workspaces (user_id, workspace_json)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE
            workspace_json = VALUES(workspace_json)
        """,
        (user_id, workspace_json),
    )
    conn.commit()
    conn.close()


def load_user_workspace(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT workspace_json
        FROM user_workspaces
        WHERE user_id = %s
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return json.loads(row[0])


def run_query(query):
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query)
        result = cursor.fetchall()
        conn.close()
        return result
    except Exception as e:
        return str(e)


def get_schema(table_name):
    """
    Returns a rich schema with column names, types, AND sample values.
    This is critical so the AI knows what data looks like.
    """
    conn = get_connection()
    cursor = conn.cursor()

    schema = f"Table name: {table_name}\nColumns:\n"

    # Get column names and types
    cursor.execute(f"DESCRIBE {table_name}")
    columns = cursor.fetchall()

    col_names = []
    for col in columns:
        schema += f"  - {col[0]} ({col[1]})\n"
        col_names.append(col[0])

    # Get sample rows so AI understands the actual values
    cursor.execute(f"SELECT * FROM {table_name} LIMIT 5")
    sample_rows = cursor.fetchall()

    if sample_rows:
        schema += "\nSample data (first 5 rows):\n"
        schema += " | ".join(col_names) + "\n"
        schema += "-" * 60 + "\n"
        for row in sample_rows:
            schema += " | ".join(str(v) for v in row) + "\n"

    # Get unique values for text columns (helps AI know exact filter values)
    schema += "\nUnique values in text columns:\n"
    for col in columns:
        col_name = col[0]
        col_type = col[1].lower()
        if "text" in col_type or "varchar" in col_type or "char" in col_type:
            try:
                cursor.execute(f"SELECT DISTINCT `{col_name}` FROM {table_name} LIMIT 10")
                unique_vals = [str(r[0]) for r in cursor.fetchall() if r[0] is not None]
                if unique_vals:
                    schema += f"  - {col_name}: {', '.join(unique_vals)}\n"
            except:
                pass

    conn.close()
    return schema


def insert_data(df, source_name=None):
    conn = get_connection()
    cursor = conn.cursor()

    # Clean column names
    df.columns = [col.strip().replace(" ", "_").lower() for col in df.columns]

    # Unique table name using source name + high resolution timestamp
    if source_name:
        base_name = re.sub(r"[^a-zA-Z0-9_]+", "_", source_name.rsplit(".", 1)[0].lower()).strip("_")
    else:
        base_name = "dataset"

    if not base_name:
        base_name = "dataset"

    table_name = f"{base_name}_{time.time_ns()}"

    # Build column definitions
    column_defs = []
    for col in df.columns:
        if df[col].dtype == "int64":
            column_defs.append(f"`{col}` INT")
        elif df[col].dtype == "float64":
            column_defs.append(f"`{col}` FLOAT")
        else:
            column_defs.append(f"`{col}` TEXT")

    columns_sql = ", ".join(column_defs)
    cursor.execute(f"CREATE TABLE `{table_name}` ({columns_sql})")

    # Insert rows safely with parameterized queries
    for _, row in df.iterrows():
        placeholders = ", ".join(["%s"] * len(row))
        cols = ", ".join([f"`{c}`" for c in df.columns])
        query = f"INSERT INTO `{table_name}` ({cols}) VALUES ({placeholders})"
        cursor.execute(query, tuple(None if str(v) == 'nan' else v for v in row))

    conn.commit()
    conn.close()
    return table_name
