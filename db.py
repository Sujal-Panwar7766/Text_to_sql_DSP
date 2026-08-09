"""
Enhanced database schema and operations for SaaS platform
Manages conversations, messages, and query history per user
"""
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from env_loader import load_project_env

load_project_env()

DB_PATH = "app_data.db"
PASSWORD_ITERATIONS = 100_000


def get_connection():
    """Get SQLite connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database():
    """Create all necessary tables for SaaS platform"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
    """)
    
    # Conversations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_archived BOOLEAN DEFAULT 0,
            message_count INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    # Messages table (chat history)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,  -- 'user' or 'assistant'
            content TEXT NOT NULL,
            query_sql TEXT,  -- SQL query if applicable
            result_json TEXT,  -- JSON results if applicable
            result_row_count INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    # Query history table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS query_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            conversation_id INTEGER,
            table_names TEXT,  -- JSON array of table names
            question TEXT,
            query_sql TEXT,
            result_row_count INTEGER,
            execution_time_ms REAL,
            success BOOLEAN DEFAULT 1,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
        )
    """)
    
    # Tables metadata table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            table_name TEXT NOT NULL,
            source_filename TEXT,
            row_count INTEGER,
            column_count INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    # User workspace (settings, theme, etc)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_workspaces (
            user_id INTEGER PRIMARY KEY,
            workspace_json TEXT NOT NULL,
            theme TEXT DEFAULT 'Dark',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    conn.close()


# ==================== USER MANAGEMENT ====================

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
    if cursor.fetchone():
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
    
    # Create default workspace
    cursor.execute(
        """
        INSERT INTO user_workspaces (user_id, workspace_json, theme)
        VALUES (?, ?, ?)
        """,
        (user_id, json.dumps({}), "Dark"),
    )
    conn.commit()
    conn.close()
    
    return {
        "id": user_id,
        "full_name": full_name.strip(),
        "email": normalized_email,
    }, None


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

    if not user or not verify_password(password, user["password_hash"]):
        conn.close()
        return None

    # Update last login
    cursor.execute(
        "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?",
        (user["id"],),
    )
    conn.commit()
    conn.close()

    return {
        "id": user["id"],
        "full_name": user["full_name"],
        "email": user["email"],
    }


# ==================== CONVERSATION MANAGEMENT ====================

def create_conversation(user_id, title="New Conversation", description=""):
    """Create a new conversation for the user"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        INSERT INTO conversations (user_id, title, description)
        VALUES (?, ?, ?)
        """,
        (user_id, title, description),
    )
    conn.commit()
    conversation_id = cursor.lastrowid
    conn.close()
    
    return conversation_id


def get_user_conversations(user_id, limit=50, offset=0, archived=False):
    """Get all conversations for a user"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        SELECT id, title, description, created_at, updated_at, message_count
        FROM conversations
        WHERE user_id = ? AND is_archived = ?
        ORDER BY updated_at DESC
        LIMIT ? OFFSET ?
        """,
        (user_id, 1 if archived else 0, limit, offset),
    )
    conversations = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return conversations


def get_conversation(conversation_id, user_id):
    """Get a specific conversation"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        SELECT id, user_id, title, description, created_at, updated_at, message_count
        FROM conversations
        WHERE id = ? AND user_id = ?
        """,
        (conversation_id, user_id),
    )
    conversation = cursor.fetchone()
    conn.close()
    
    return dict(conversation) if conversation else None


def update_conversation(conversation_id, user_id, title=None, description=None):
    """Update conversation title/description"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if title:
        cursor.execute(
            """
            UPDATE conversations
            SET title = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
            """,
            (title, conversation_id, user_id),
        )
    
    if description is not None:
        cursor.execute(
            """
            UPDATE conversations
            SET description = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
            """,
            (description, conversation_id, user_id),
        )
    
    conn.commit()
    conn.close()


def delete_conversation(conversation_id, user_id):
    """Delete a conversation (soft delete via archive)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        UPDATE conversations
        SET is_archived = 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (conversation_id, user_id),
    )
    conn.commit()
    conn.close()


def search_conversations(user_id, query, limit=20):
    """Search conversations by title"""
    conn = get_connection()
    cursor = conn.cursor()
    
    search_query = f"%{query.lower()}%"
    cursor.execute(
        """
        SELECT id, title, description, created_at, updated_at, message_count
        FROM conversations
        WHERE user_id = ? AND is_archived = 0 AND LOWER(title) LIKE ?
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (user_id, search_query, limit),
    )
    conversations = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return conversations


# ==================== MESSAGE MANAGEMENT ====================

def add_message(conversation_id, user_id, role, content, query_sql=None, result_json=None, row_count=None):
    """Add a message to a conversation"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        INSERT INTO messages (conversation_id, user_id, role, content, query_sql, result_json, result_row_count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (conversation_id, user_id, role, content, query_sql, result_json, row_count),
    )
    conn.commit()
    message_id = cursor.lastrowid
    
    # Update conversation message count and timestamp
    cursor.execute(
        """
        UPDATE conversations
        SET message_count = message_count + 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (conversation_id,),
    )
    conn.commit()
    conn.close()
    
    return message_id


def get_conversation_history(conversation_id, user_id, limit=50):
    """Get all messages in a conversation"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        SELECT id, role, content, query_sql, result_json, result_row_count, created_at
        FROM messages
        WHERE conversation_id = ? AND user_id = ?
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (conversation_id, user_id, limit),
    )
    messages = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return messages


# ==================== QUERY HISTORY ====================

def log_query(user_id, conversation_id, table_names, question, query_sql, row_count, exec_time_ms, success=True, error_msg=None):
    """Log a query execution"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        INSERT INTO query_history (user_id, conversation_id, table_names, question, query_sql, result_row_count, execution_time_ms, success, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            conversation_id,
            json.dumps(table_names),
            question,
            query_sql,
            row_count,
            exec_time_ms,
            1 if success else 0,
            error_msg,
        ),
    )
    conn.commit()
    conn.close()


def get_query_history(user_id, limit=100, offset=0):
    """Get query history for a user"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        SELECT id, question, query_sql, result_row_count, execution_time_ms, success, created_at
        FROM query_history
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (user_id, limit, offset),
    )
    history = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return history


# ==================== WORKSPACE ====================

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


# ==================== DATA OPERATIONS ====================

def run_query(query):
    """Execute a SELECT query and return results"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(query)
        result = cursor.fetchall()
        conn.close()
        return [dict(row) for row in result]
    except Exception as e:
        return str(e)


def get_schema(table_name):
    """Returns schema with column names, types, and sample values"""
    conn = get_connection()
    cursor = conn.cursor()

    schema = f"Table name: {table_name}\nColumns:\n"

    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()

    col_names = []
    for col in columns:
        col_name = col[1]
        col_type = col[2]
        schema += f"  - {col_name} ({col_type})\n"
        col_names.append(col_name)

    cursor.execute(f"SELECT * FROM {table_name} LIMIT 5")
    sample_rows = cursor.fetchall()

    if sample_rows:
        schema += "\nSample data (first 5 rows):\n"
        schema += " | ".join(col_names) + "\n"
        schema += "-" * 60 + "\n"
        for row in sample_rows:
            schema += " | ".join(str(v) for v in row) + "\n"

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


def insert_data(df, user_id, source_name=None):
    """Insert CSV data into a new SQLite table"""
    conn = get_connection()
    cursor = conn.cursor()

    # Clean column names
    df.columns = [re.sub(r'[^a-zA-Z0-9_]', '_', col.strip().lower()) for col in df.columns]
    df.columns = [f"col_{col}" if col[0].isdigit() else col for col in df.columns]

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
            column_defs.append(f'"{col}" INTEGER')
        elif df[col].dtype == "float64":
            column_defs.append(f'"{col}" REAL')
        else:
            column_defs.append(f'"{col}" TEXT')

    columns_sql = ", ".join(column_defs)
    cursor.execute(f"CREATE TABLE {table_name} ({columns_sql})")

    # Insert rows
    for _, row in df.iterrows():
        placeholders = ", ".join(["?"] * len(row))
        cols = ", ".join([f'"{col}"' for col in df.columns])
        query = f"INSERT INTO {table_name} ({cols}) VALUES ({placeholders})"
        cursor.execute(query, tuple(None if str(v) == 'nan' else v for v in row))

    conn.commit()
    
    # Log table metadata
    cursor.execute(
        """
        INSERT INTO user_tables (user_id, table_name, source_filename, row_count, column_count)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, table_name, source_name, len(df), len(df.columns)),
    )
    conn.commit()
    conn.close()
    
    return table_name


def get_user_tables(user_id):
    """Get all tables uploaded by a user"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        SELECT table_name, source_filename, row_count, column_count, created_at
        FROM user_tables
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,),
    )
    tables = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return tables
