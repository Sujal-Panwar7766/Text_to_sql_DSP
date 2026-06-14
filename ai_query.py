import os
import re

from groq import Groq

from db import get_schema
from env_loader import load_project_env

load_project_env()

client = Groq(
    api_key=os.getenv(
        "GROQ_API_KEY",
        "",
    )
)


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
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content.strip(), None
    except Exception as e:
        error = str(e)
        if "401" in error or "auth" in error.lower():
            return None, "Invalid Groq API key. Check your .env file."
        if "429" in error or "rate" in error.lower():
            return None, "Rate limit hit. Wait a few seconds and try again."
        return None, f"AI Error: {error}"


def extract_sql(text):
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
    normalized_tables = normalize_table_names(table_names)
    schema_context = build_schema_context(normalized_tables)
    table_list = ", ".join(normalized_tables)

    prompt = f"""You are an expert MySQL query generator.

Available tables:
{table_list}

{schema_context}

RULES:
1. Return ONLY a valid MySQL SELECT query. No explanation, no markdown, no extra text.
2. Use ONLY the tables and columns shown above.
3. Use WHERE clause for filtering questions.
4. Use COUNT(*) for counting questions.
5. Return all matching rows unless the user explicitly asks for only one row, the top N rows, a count, or an aggregate.
6. For highest/top/maximum questions, prefer returning all rows tied for the maximum value instead of forcing LIMIT 1 unless the user clearly asks for a single row.
7. For lowest/minimum questions, prefer returning all rows tied for the minimum value instead of forcing LIMIT 1 unless the user clearly asks for a single row.
8. Use ORDER BY with LIMIT only when the user explicitly asks for top N, bottom N, first row, last row, or a single best/worst record.
9. Use AVG() for average questions.
10. Use GROUP BY for per-category aggregations.
11. Match string values exactly as they appear in the sample data.
12. If multiple tables are needed, only join tables when a shared column clearly exists in the schemas.
13. Never invent table names, column names, or values.
14. Always end the query with a semicolon.

User question: {user_question}

SQL:"""

    raw_text, error = run_ai_task(
        "You are a MySQL expert. Always return only a valid SQL SELECT query with no explanation.",
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
    normalized_tables = normalize_table_names(table_names)
    schema_context = build_schema_context(normalized_tables)
    scope = ", ".join(normalized_tables)

    prompt = f"""You are helping a user explore uploaded MySQL data.

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
6. Every question must be answerable with a single MySQL SELECT query.
7. If multiple tables are available, include at least one question that could use more than one table.
"""

    raw_text, error = run_ai_task(
        "You generate short, schema-aware example questions for SQL exploration. Return only plain questions.",
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


def generate_result_summary(question, sql, result_df, table_names):
    normalized_tables = normalize_table_names(table_names)
    result_context = format_result_context(result_df)

    prompt = f"""Create a concise plain-English summary of this SQL result.

Question:
{question}

SQL:
{sql}

Tables:
{', '.join(normalized_tables)}

Result:
{result_context}

RULES:
1. Return 2 short sentences maximum.
2. Focus on the actual result, not the SQL mechanics.
3. If no rows were returned, say that clearly.
"""

    return run_ai_task(
        "You summarize SQL query results for end users in clear, direct English.",
        prompt,
        max_tokens=120,
        temperature=0.2,
    )


def generate_follow_up_questions(question, sql, result_df, table_names):
    normalized_tables = normalize_table_names(table_names)
    result_context = format_result_context(result_df)

    prompt = f"""Suggest 4 useful follow-up questions based on this SQL query and its result.

Question:
{question}

SQL:
{sql}

Tables:
{', '.join(normalized_tables)}

Result:
{result_context}

RULES:
1. Return ONLY questions, one per line.
2. Keep them short, natural, and specific.
3. Make them realistic next steps a user would ask.
"""

    raw_text, error = run_ai_task(
        "You suggest short, useful follow-up questions for SQL data exploration. Return only questions.",
        prompt,
        max_tokens=160,
        temperature=0.4,
    )
    if error:
        return None, error

    questions = extract_lines(raw_text, max_items=4)
    if not questions:
        return None, f"Could not extract follow-up questions from AI response:\n{raw_text}"

    return questions, None


def generate_table_insights(table_name, profile_text):
    prompt = f"""You are helping a user understand an uploaded CSV that is now stored in MySQL.

Table:
{table_name}

Profile:
{profile_text}

TASK:
Generate 4 short insights.

RULES:
1. Return ONLY bullet-style insight lines, one per line.
2. Keep each insight specific and concrete.
3. Mention data quality or distribution observations when possible.
4. Do not invent information beyond the profile provided.
"""

    raw_text, error = run_ai_task(
        "You generate concise, practical data insights from dataset profiles. Return only the insight lines.",
        prompt,
        max_tokens=180,
        temperature=0.3,
    )
    if error:
        return None, error

    insights = extract_lines(raw_text, max_items=4)
    if not insights:
        return None, f"Could not extract dataset insights from AI response:\n{raw_text}"

    return insights, None
