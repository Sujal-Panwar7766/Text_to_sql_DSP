import os
import re

import streamlit as st
from transformers import pipeline
from env_loader import load_project_env

from db import get_schema

load_project_env()

# Load the model once and cache it
@st.cache_resource
def load_model():
    """Load the text generation model (cached for performance)"""
    try:
        return pipeline("text2text-generation", model="google/flan-t5-base", device=-1)
    except Exception as e:
        st.error(f"Failed to load model: {e}")
        return None


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
    """Run AI task using local transformers model"""
    try:
        model = load_model()
        if model is None:
            return None, "Model failed to load"
        
        # Combine system message and user prompt
        full_prompt = f"{system_message}\n\n{user_prompt}"
        
        # Generate text
        result = model(
            full_prompt,
            max_length=max_tokens,
            num_beams=1,
            early_stopping=True,
        )
        
        if result and len(result) > 0:
            generated_text = result[0].get("generated_text", "").strip()
            return generated_text, None
        
        return None, "No response from model"
        
    except Exception as e:
        error = str(e)
        if "cuda" in error.lower() or "gpu" in error.lower():
            return None, "Model error. Try again later."
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

    prompt = f"""Generate a SQL SELECT query.

Available tables:
{table_list}

{schema_context}

RULES:
1. Return ONLY a valid SQL SELECT query. No explanation.
2. Use ONLY the tables and columns shown above.
3. Always end with semicolon.

Question: {user_question}

SQL:"""

    raw_text, error = run_ai_task(
        "You are a SQL expert. Return only a SQL SELECT query with no explanation.",
        prompt,
        max_tokens=300,
        temperature=0,
    )
    if error:
        return None, error

    sql = extract_sql(raw_text)
    if not sql:
        return None, f"Could not extract SQL from response:\n{raw_text}"

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

    prompt = f"""Generate 5 example questions about this data. Return only the questions, one per line.

Tables:
{scope}

{schema_context}

Questions:"""

    raw_text, error = run_ai_task(
        "Generate short example questions for data exploration.",
        prompt,
        max_tokens=220,
        temperature=0.3,
    )
    if error:
        return None, error

    questions = extract_lines(raw_text, max_items=5)
    if not questions:
        return None, f"Could not extract example questions:\n{raw_text}"

    return questions, None


def generate_table_insights(table_name):
    """Generate insights about uploaded table"""
    schema = get_schema(table_name)
    prompt = f"""Analyze this table and provide 3 short insights about the data. One per line.

{schema}

Insights:"""

    raw_text, error = run_ai_task(
        "Analyze data and provide brief insights.",
        prompt,
        max_tokens=200,
        temperature=0.5,
    )
    if error:
        return None, error

    insights = extract_lines(raw_text, max_items=3)
    return insights if insights else None, error


def generate_follow_up_questions(result_df, original_question, table_names):
    """Generate follow-up questions based on query results"""
    result_context = format_result_context(result_df, max_rows=5)
    schema_context = build_schema_context(table_names)

    prompt = f"""Based on these query results, suggest 3 follow-up questions. One per line.

Original question: {original_question}

Results:
{result_context}

Follow-up questions:"""

    raw_text, error = run_ai_task(
        "Suggest follow-up questions for data exploration.",
        prompt,
        max_tokens=250,
        temperature=0.5,
    )
    if error:
        return None, error

    questions = extract_lines(raw_text, max_items=3)
    return questions if questions else None, error


def generate_result_summary(result_df, user_question, table_names):
    """Generate AI summary of query results"""
    result_context = format_result_context(result_df, max_rows=10)
    schema_context = build_schema_context(table_names)

    prompt = f"""Summarize these query results in 2-3 sentences.

Question: {user_question}

Results:
{result_context}

Summary:"""

    raw_text, error = run_ai_task(
        "Provide clear summaries of SQL query results.",
        prompt,
        max_tokens=200,
        temperature=0.5,
    )
    if error:
        return None, error

    return raw_text.strip() if raw_text else None, error
