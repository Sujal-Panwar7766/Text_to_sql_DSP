import os
import re

import requests
from env_loader import load_project_env

from db import get_schema

load_project_env()

HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "")
HF_MODEL = "google/flan-t5-base"  # Free, public model (no approval needed)
HF_API_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL}"


def normalize_table_names(table_names):
    if isinstance(table_names, str):
        return [table_names]
    return [table_name for table_name in (table_names or []) if table_name]


def build_schema_context(table_names):
    normalized_tables = normalize_table_names(table_names)
    if not normalized_tables:
        return ""
    return "\n\n".join(get_schema(table_name) for table_name in normalized_tables)


def run_ai_task(system_message, user_prompt, max_tokens=256, temperature=0):
    """Call HuggingFace inference API"""
    try:
        # Format prompt for Flan-T5 (simpler format, no special tokens needed)
        full_prompt = f"{system_message}\n\n{user_prompt}"
        
        headers = {
            "Authorization": f"Bearer {HF_API_KEY}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "inputs": full_prompt,
            "parameters": {
                "max_new_tokens": max_tokens,
                "temperature": temperature,
                "do_sample": temperature > 0,
            }
        }
        
        response = requests.post(HF_API_URL, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 401:
            return None, "Invalid HuggingFace API key. Check your .env file."
        if response.status_code == 429:
            return None, "Rate limit hit. Wait a few seconds and try again."
        if response.status_code >= 500:
            return None, "HuggingFace API temporarily unavailable. Try again later."
        
        response.raise_for_status()
        result = response.json()
        
        # Extract generated text
        if isinstance(result, list) and len(result) > 0:
            generated_text = result[0].get("generated_text", "").strip()
            return generated_text, None
        
        return None, "Unexpected API response format"
        
    except requests.exceptions.Timeout:
        return None, "Request timeout. Try again later."
    except requests.exceptions.RequestException as e:
        return None, f"API Error: {str(e)}"
    except Exception as e:
        error = str(e)
        if "401" in error or "auth" in error.lower():
            return None, "Invalid HuggingFace API key. Check your .env file."
        return None, f"AI Error: {error}"


def extract_sql(text):
    """Extract SQL query from AI response"""
    match = re.search(r"```(?:sql)?\s*(SELECT.*?)```", text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip().rstrip(";") + ";"

    match = re.search(r"(SELECT\s+.*?;)", text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()

    match = re.search(r"(SELECT\s+.+?)(?:\n|$)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip() + ";"

    return None


def extract_lines(text, max_items=7):
    """Extract lines from AI response"""
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
    """Format query results for AI"""
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


def generate_sql(user_question, table_names):
    """Generate SQL query from natural language question"""
    normalized_tables = normalize_table_names(table_names)
    schema_context = build_schema_context(normalized_tables)
    table_list = ", ".join(normalized_tables)

    prompt = f"""You are an expert SQL query generator.

Available tables:
{table_list}

{schema_context}

RULES:
1. Return ONLY a valid SQL SELECT query. No explanation, no markdown, no extra text.
2. Use ONLY the tables and columns shown above.
3. Use WHERE clause for filtering questions.
4. Use COUNT(*) for counting questions.
5. Return all matching rows unless the user explicitly asks for only one row, the top N rows, a count, or an aggregate.
6. Use ORDER BY with LIMIT only when the user explicitly asks for top N, bottom N, first row, last row, or a single best/worst record.
7. Use AVG() for average questions.
8. Use GROUP BY for per-category aggregations.
9. Match string values exactly as they appear in the sample data.
10. Never invent table names, column names, or values.
11. Always end the query with a semicolon.

User question: {user_question}

SQL:"""

    raw_text, error = run_ai_task(
        "You are a SQL expert. Always return only a valid SQL SELECT query with no explanation.",
        prompt,
        max_tokens=300,
        temperature=0,
    )
    if error:
        return None, error

    sql = extract_sql(raw_text)
    if not sql:
        return None, f"Could not extract SQL from AI response:\n{raw_text}"

    if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        return None, "AI returned a non-SELECT statement. Please try again."

    if re.match(r"SELECT\s+\*\s+FROM\s+\w+\s*;", sql, re.IGNORECASE):
        return None, "AI returned a generic query. Please be more specific in your question."

    return sql, None


def generate_example_questions(table_names):
    """Generate example questions for the user"""
    normalized_tables = normalize_table_names(table_names)
    schema_context = build_schema_context(normalized_tables)
    scope = ", ".join(normalized_tables)

    prompt = f"""You are helping a user explore uploaded data.

Available tables:
{scope}

{schema_context}

TASK:
Generate 7 short example questions the user can ask.

RULES:
1. Return ONLY the questions, one per line.
2. Do not return SQL.
3. Make every question specific to the available schema and sample values.
4. Include a mix of filters, aggregations, rankings, comparisons, and groupings.
5. Keep each question natural and short.
6. Every question must be answerable with a single SQL SELECT query.
"""

    raw_text, error = run_ai_task(
        "You generate short, schema-aware example questions for data exploration. Return only plain questions.",
        prompt,
        max_tokens=220,
        temperature=0.3,
    )
    if error:
        return None, error

    questions = extract_lines(raw_text, max_items=7)
    if not questions:
        return None, f"Could not extract example questions from AI response:\n{raw_text}"

    return questions, None


def generate_table_insights(table_name):
    """Generate insights about uploaded table"""
    schema = get_schema(table_name)
    prompt = f"""Analyze this table and provide 3-4 short insights about the data.

{schema}

RULES:
1. Return ONLY the insights, one per line.
2. Keep each insight short (under 15 words).
3. Focus on column types, data patterns, and what questions could be answered.
"""

    raw_text, error = run_ai_task(
        "You analyze data tables and provide brief insights.",
        prompt,
        max_tokens=200,
        temperature=0.5,
    )
    if error:
        return None, error

    insights = extract_lines(raw_text, max_items=4)
    return insights if insights else None, error


def generate_follow_up_questions(result_df, original_question, table_names):
    """Generate follow-up questions based on query results"""
    result_context = format_result_context(result_df, max_rows=5)
    schema_context = build_schema_context(table_names)

    prompt = f"""Based on the query results below, suggest 4 follow-up questions the user might ask.

Original question: {original_question}

Query results:
{result_context}

Schema:
{schema_context}

RULES:
1. Return ONLY the follow-up questions, one per line.
2. Each question should explore the results deeper or related patterns.
3. Keep questions short and natural.
4. Each must be answerable with available data.
"""

    raw_text, error = run_ai_task(
        "You suggest follow-up questions for data exploration.",
        prompt,
        max_tokens=250,
        temperature=0.5,
    )
    if error:
        return None, error

    questions = extract_lines(raw_text, max_items=4)
    return questions if questions else None, error


def generate_result_summary(result_df, user_question, table_names):
    """Generate AI summary of query results"""
    result_context = format_result_context(result_df, max_rows=10)
    schema_context = build_schema_context(table_names)

    prompt = f"""Summarize the query results below in 2-3 sentences. Be concise and insightful.

Question asked: {user_question}

Results:
{result_context}

Schema context:
{schema_context}
"""

    raw_text, error = run_ai_task(
        "You provide clear, concise summaries of SQL query results.",
        prompt,
        max_tokens=200,
        temperature=0.5,
    )
    if error:
        return None, error

    return raw_text.strip() if raw_text else None, error
