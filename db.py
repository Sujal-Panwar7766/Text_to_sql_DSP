import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from pathlib import Path

from env_loader import load_project_env

load_project_env()

# SQLite database file (stored in current directory)
DB_PATH = "app_data.db"

PASSWORD_ITERATIONS = 100_000


def get_connection():
    """Get SQLite connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Return rows as dictionaries
    return conn


def ensure_users_table():
    """Create users and workspaces tables if they don't exist"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_workspaces (
            user_id INTEGER PRIMARY KEY,
            workspace_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
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
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE email = ?", (normalized_email,))
    existing_user = cursor.fetchone()
    if existing_user:
        conn.close()
        return None, "An account with this email already exists."

    password_hash = hash_password(password)
    cursor.execute(
        """
        INSERT INTO users (full_name, email, password_hash)
        VALUES (?, ?, ?)
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
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, full_name, email, password_hash
        FROM users
        WHERE email = ?
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
        INSERT OR REPLACE INTO user_workspaces (user_id, workspace_json)
        VALUES (?, ?)
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
        WHERE user_id = ?
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return json.loads(row[0])


def run_query(query):
    """Execute a SELECT query and return results"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(query)
        result = cursor.fetchall()
        conn.close()
        # Convert sqlite3.Row to dict for consistency
        return [dict(row) for row in result]
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
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()

    col_names = []
    for col in columns:
        col_name = col[1]
        col_type = col[2]
        schema += f"  - {col_name} ({col_type})\n"
        col_names.append(col_name)

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
        col_name = col[1]
        col_type = col[2].lower()
        if "text" in col_type or "char" in col_type:
            try:
                cursor.execute(f"SELECT DISTINCT {col_name} FROM {table_name} LIMIT 10")
                unique_vals = [str(r[0]) for r in cursor.fetchall() if r[0] is not None]
                if unique_vals:
                    schema += f"  - {col_name}: {', '.join(unique_vals)}\n"
            except:
                pass

    conn.close()
    return schema


def insert_data(df, source_name=None):
    """Insert CSV data into a new SQLite table"""
    conn = get_connection()
    cursor = conn.cursor()

    # Clean column names
    df.columns = [col.strip().replace(" ", "_").lower() for col in df.columns]

    # Unique table name using source name + timestamp
    if source_name:
        base_name = re.sub(r"[^a-zA-Z0-9_]+", "_", source_name.rsplit(".", 1)[0].lower()).strip("_")
    else:
        base_name = "dataset"

    if not base_name:
        base_name = "dataset"

    table_name = f"{base_name}_{time.time_ns()}"

    # Build column definitions for SQLite
    column_defs = []
    for col in df.columns:
        # SQLite is flexible with types, but we'll hint them
        if df[col].dtype == "int64":
            column_defs.append(f"{col} INTEGER")
        elif df[col].dtype == "float64":
            column_defs.append(f"{col} REAL")
        else:
            column_defs.append(f"{col} TEXT")

    columns_sql = ", ".join(column_defs)
    cursor.execute(f"CREATE TABLE {table_name} ({columns_sql})")

    # Insert rows safely with parameterized queries
    for _, row in df.iterrows():
        placeholders = ", ".join(["?"] * len(row))
        cols = ", ".join(df.columns)
        query = f"INSERT INTO {table_name} ({cols}) VALUES ({placeholders})"
        cursor.execute(query, tuple(None if str(v) == 'nan' else v for v in row))

    conn.commit()
    conn.close()
    return table_name
