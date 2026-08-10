import os
import re

import requests

from env_loader import load_project_env
from db import get_schema

load_project_env()

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

DEFAULT_EXAMPLE_QUESTIONS = [
    "How many rows are there?",
    "Show the first 10 rows.",
    "What are the distinct values?",
    "Which rows have the highest values?",
    "What is the average value?",
]

DEFAULT_TABLE_INSIGHTS = [
    "Table uploaded successfully.",
    "Ready to answer questions about your data.",
    "Use natural language to query your data.",
]

DEFAULT_FOLLOW_UP_QUESTIONS = [
    "Show me more details.",
    "What is the average value?",
    "Count rows by category.",
    "Find the highest values.",
]


def normalize_table_names(table_names):
    if isinstance(table_names, str):
        return [table_names]
    return [table_name for table_name in (table_names or []) if table_name]


def get_groq_api_key():
    return os.getenv("GROQ_API_KEY", "").strip()


def get_groq_model():
    return os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip() or "llama-3.3-70b-versatile"


def build_schema_context(table_names):
    normalized_tables = normalize_table_names(table_names)
    if not normalized_tables:
        return ""
    return "\n\n".join(get_schema(table_name) for table_name in normalized_tables)


def run_ai_task(system_message, user_prompt, max_tokens=256, temperature=0.2):
    """Call Groq chat completions using the official OpenAI-compatible endpoint."""
    groq_api_key = get_groq_api_key()
    if not groq_api_key:
        return None, "GROQ_API_KEY is not configured."

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": get_groq_model(),
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_prompt},
                ],
                "max_completion_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=45,
        )

        if response.status_code == 401:
            return None, "Invalid Groq API key. Check GROQ_API_KEY."
        if response.status_code == 429:
            return None, "Groq rate limit hit. Please try again in a moment."
        if response.status_code >= 500:
            return None, "Groq API is temporarily unavailable."

        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"].strip()
        if not content:
            return None, "Groq returned an empty response."
        return content, None
    except requests.exceptions.Timeout:
        return None, "Groq request timed out."
    except requests.exceptions.RequestException as exc:
        return None, f"Groq request failed: {exc}"
    except (KeyError, IndexError, TypeError, ValueError):
        return None, "Unexpected response format from Groq."


def extract_sql(text):
    """Extract a SELECT query from model output."""
    match = re.search(r"```(?:sql)?\s*(SELECT.*?)```", text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip().rstrip(";") + ";"

    match = re.search(r"(SELECT\s+.*?;)", text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()

    match = re.search(r"(SELECT\s+.+?)(?:\n|$)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip().rstrip(";") + ";"

    return None


def extract_lines(text, max_items=7):
    """Extract simple bullet or line-based answers."""
    items = []
    seen = set()

    for line in text.splitlines():
        cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
        cleaned = cleaned.strip("`\"' ")

        if not cleaned:
            continue

        lowered = cleaned.lower()
        if lowered.startswith(("here are", "example questions", "questions:", "follow-up questions", "insights:")):
            continue

        if cleaned not in seen:
            seen.add(cleaned)
            items.append(cleaned)

        if len(items) >= max_items:
            break

    return items


def format_result_context(result_df, max_rows=10):
    """Format query results for summary and follow-up prompts."""
    if result_df is None or result_df.empty:
        return "No rows returned."

    preview_df = result_df.head(max_rows)
    lines = [
        f"Columns: {', '.join(preview_df.columns.astype(str))}",
        f"Rows returned: {len(result_df)}",
        "Sample rows:",
        preview_df.to_csv(index=False),
    ]
    return "\n".join(lines)


def generate_rule_based_sql(user_question, table_names):
    """Fallback SQL generation when Groq is unavailable."""
    normalized_tables = normalize_table_names(table_names)
    if not normalized_tables:
        return None, "No tables selected"

    table_name = normalized_tables[0]
    schema = get_schema(table_name)
    question = user_question.lower()

    col_names = []
    in_columns_section = False
    for line in schema.split("\n"):
        if "Columns:" in line:
            in_columns_section = True
            continue

        if in_columns_section and ("Sample" in line or "Unique" in line or "Table" in line):
            in_columns_section = False

        if in_columns_section and (" - " in line or line.strip().startswith("-")):
            cleaned = line.strip()
            if cleaned.startswith("- "):
                cleaned = cleaned[2:]

            if " (" in cleaned:
                col_name = cleaned.split(" (", 1)[0].strip()
                if col_name:
                    col_names.append(col_name)

    try:
        if "how many" in question or "count" in question or "total" in question:
            return f"SELECT COUNT(*) AS count FROM {table_name};", None

        if "show all" in question or "display all" in question or "select all" in question:
            return f"SELECT * FROM {table_name};", None

        if "first" in question and "rows" in question:
            match = re.search(r"first\s+(\d+)", question)
            if match:
                return f"SELECT * FROM {table_name} LIMIT {match.group(1)};", None
            return f"SELECT * FROM {table_name} LIMIT 10;", None

        if "distinct" in question or "unique" in question or "different" in question:
            if col_names:
                for col in col_names:
                    if col.lower() in question:
                        return f'SELECT DISTINCT "{col}" FROM {table_name};', None
                return f'SELECT DISTINCT "{col_names[0]}" FROM {table_name};', None
            return f"SELECT * FROM {table_name} LIMIT 20;", None

        if "average" in question or "avg" in question or "mean" in question:
            if col_names:
                for col in col_names:
                    if col.lower() in question:
                        return f'SELECT AVG("{col}") AS average FROM {table_name};', None
                return f'SELECT AVG("{col_names[0]}") AS average FROM {table_name};', None
            return f"SELECT * FROM {table_name} LIMIT 20;", None

        if "minimum" in question or "lowest" in question or "min" in question:
            if col_names:
                for col in col_names:
                    if col.lower() in question:
                        return f'SELECT * FROM {table_name} ORDER BY "{col}" ASC LIMIT 10;', None
            return f"SELECT * FROM {table_name} LIMIT 20;", None

        if "maximum" in question or "highest" in question or "max" in question:
            if col_names:
                for col in col_names:
                    if col.lower() in question:
                        return f'SELECT * FROM {table_name} ORDER BY "{col}" DESC LIMIT 10;', None
            return f"SELECT * FROM {table_name} LIMIT 20;", None

        if "group" in question or "by" in question:
            if col_names:
                for col in col_names:
                    if col.lower() in question:
                        return f'SELECT "{col}", COUNT(*) AS count FROM {table_name} GROUP BY "{col}";', None
            return f"SELECT * FROM {table_name} LIMIT 20;", None

        return f"SELECT * FROM {table_name} LIMIT 20;", None
    except Exception as exc:
        return None, f"Error generating SQL: {exc}"


def generate_sql(user_question, table_names):
    """Generate SQL from natural language using Groq, with a local fallback."""
    normalized_tables = normalize_table_names(table_names)
    if not normalized_tables:
        return None, "No tables selected"

    schema_context = build_schema_context(normalized_tables)
    table_list = ", ".join(normalized_tables)

    prompt = f"""You are an expert SQLite query generator.

Available tables:
{table_list}

{schema_context}

RULES:
1. Return ONLY one valid SQLite SELECT query.
2. Use ONLY the tables and columns shown above.
3. Never invent table names, column names, joins, or filter values.
4. Use double quotes around column names when helpful.
5. Use COUNT(*) for counting questions.
6. Use AVG() for average questions.
7. Use GROUP BY for per-category aggregations.
8. Use ORDER BY with LIMIT only when the user explicitly asks for top N, bottom N, first N, or a single best or worst record.
9. If multiple tables are needed, only join them when a shared column clearly exists in the schemas.
10. Always end the query with a semicolon.

User question: {user_question}

SQL:"""

    raw_text, error = run_ai_task(
        "You write precise SQLite SELECT queries and return only SQL.",
        prompt,
        max_tokens=300,
        temperature=0.1,
    )
    if error:
        return generate_rule_based_sql(user_question, normalized_tables)

    sql = extract_sql(raw_text)
    if not sql:
        return generate_rule_based_sql(user_question, normalized_tables)

    if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        return generate_rule_based_sql(user_question, normalized_tables)

    return sql, None


def generate_example_questions(table_names):
    """Generate schema-aware example questions."""
    normalized_tables = normalize_table_names(table_names)
    if not normalized_tables:
        return DEFAULT_EXAMPLE_QUESTIONS, None

    schema_context = build_schema_context(normalized_tables)
    scope = ", ".join(normalized_tables)

    prompt = f"""You are helping a user explore uploaded SQLite data.

Available tables:
{scope}

{schema_context}

TASK:
Generate 5 short example questions the user can ask.

RULES:
1. Return ONLY the questions, one per line.
2. Do not return SQL.
3. Make every question specific to the schema or sample values.
4. Include a mix of counts, filters, rankings, and groupings.
5. Keep each question natural and short.
"""

    raw_text, error = run_ai_task(
        "You generate short, schema-aware questions for SQL exploration.",
        prompt,
        max_tokens=180,
        temperature=0.3,
    )
    if error:
        return DEFAULT_EXAMPLE_QUESTIONS, None

    questions = extract_lines(raw_text, max_items=5)
    return (questions or DEFAULT_EXAMPLE_QUESTIONS), None


def generate_table_insights(table_name):
    """Generate short dataset insights."""
    schema_context = get_schema(table_name)
    prompt = f"""Review this SQLite table schema and sample data, then provide 3 short insights.

{schema_context}

RULES:
1. Return ONLY the insights, one per line.
2. Keep each insight concrete and short.
3. Focus on patterns, useful questions, or data quality hints.
"""

    raw_text, error = run_ai_task(
        "You generate concise dataset insights.",
        prompt,
        max_tokens=160,
        temperature=0.3,
    )
    if error:
        return DEFAULT_TABLE_INSIGHTS, None

    insights = extract_lines(raw_text, max_items=3)
    return (insights or DEFAULT_TABLE_INSIGHTS), None


def generate_follow_up_questions(result_df, original_question, table_names):
    """Generate follow-up questions after a query result."""
    result_context = format_result_context(result_df, max_rows=5)
    schema_context = build_schema_context(table_names)

    prompt = f"""Based on the query result below, suggest 4 follow-up questions.

Original question:
{original_question}

Result:
{result_context}

Schema:
{schema_context}

RULES:
1. Return ONLY questions, one per line.
2. Keep them short and useful.
3. Make them realistic next questions for the same data.
"""

    raw_text, error = run_ai_task(
        "You suggest useful follow-up questions for data analysis.",
        prompt,
        max_tokens=160,
        temperature=0.4,
    )
    if error:
        return DEFAULT_FOLLOW_UP_QUESTIONS, None

    questions = extract_lines(raw_text, max_items=4)
    return (questions or DEFAULT_FOLLOW_UP_QUESTIONS), None


def generate_result_summary(result_df, user_question, table_names):
    """Generate a concise result summary."""
    if result_df is None or result_df.empty:
        return "No results found.", None

    result_context = format_result_context(result_df)
    table_scope = ", ".join(normalize_table_names(table_names))

    prompt = f"""Summarize this SQLite query result in at most 2 short sentences.

User question:
{user_question}

Tables:
{table_scope}

Result:
{result_context}

RULES:
1. Focus on what the result shows.
2. Do not explain SQL mechanics.
3. Be short and direct.
"""

    raw_text, error = run_ai_task(
        "You summarize SQL query results for end users in plain English.",
        prompt,
        max_tokens=120,
        temperature=0.2,
    )
    if error or not raw_text:
        num_rows = len(result_df)
        num_cols = len(result_df.columns)
        return f"Query returned {num_rows} rows with {num_cols} columns.", None

    return raw_text.strip(), None
