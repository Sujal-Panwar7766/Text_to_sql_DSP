import os
import re

from env_loader import load_project_env

from db import get_schema

load_project_env()


def normalize_table_names(table_names):
    if isinstance(table_names, str):
        return [table_names]
    return [table_name for table_name in (table_names or []) if table_name]


def build_schema_context(table_names):
    normalized_tables = normalize_table_names(table_names)
    if not normalized_tables:
        return ""
    return "\n\n".join(get_schema(table_name) for table_name in normalized_tables)


def extract_lines(text, max_items=7):
    """Extract lines from text response"""
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
    """Format query results for context"""
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
    """Generate SQL query from natural language using rule-based approach"""
    normalized_tables = normalize_table_names(table_names)
    if not normalized_tables:
        return None, "No tables selected"
    
    table_name = normalized_tables[0]
    schema = get_schema(table_name)
    question = user_question.lower()
    
    # Extract column names from schema - improved parsing
    col_names = []
    in_columns_section = False
    for line in schema.split('\n'):
        # Look for "Columns:" section
        if "Columns:" in line:
            in_columns_section = True
            continue
        
        # Stop at next section
        if in_columns_section and ("Sample" in line or "Unique" in line or "Table" in line):
            in_columns_section = False
        
        # Extract column name if in columns section
        if in_columns_section and (" - " in line or line.strip().startswith("-")):
            # Clean up the line and extract column name
            cleaned = line.strip()
            if cleaned.startswith("- "):
                cleaned = cleaned[2:]  # Remove "- "
            
            # Split by " (" to get column name
            if " (" in cleaned:
                col_name = cleaned.split(" (")[0].strip()
                if col_name:
                    col_names.append(col_name)
    
    # If still no columns found, try a simpler approach
    if not col_names:
        # Just use a generic approach - most queries work without specific column knowledge
        pass
    
    # Rule-based SQL generation
    try:
        # COUNT queries
        if "how many" in question or "count" in question or "total" in question:
            return f"SELECT COUNT(*) as count FROM {table_name};", None
        
        # SHOW ALL / FIRST N ROWS
        if "show all" in question or "display all" in question or "select all" in question:
            return f"SELECT * FROM {table_name};", None
        
        if "first" in question and "rows" in question:
            match = re.search(r'first\s+(\d+)', question)
            if match:
                n = match.group(1)
                return f"SELECT * FROM {table_name} LIMIT {n};", None
            return f"SELECT * FROM {table_name} LIMIT 10;", None
        
        # DISTINCT values
        if "distinct" in question or "unique" in question or "different" in question:
            if col_names:
                for col in col_names:
                    if col.lower() in question or question.find(col.lower()) != -1:
                        return f"SELECT DISTINCT {col} FROM {table_name};", None
                # Default to first column
                return f"SELECT DISTINCT {col_names[0]} FROM {table_name};", None
            return f"SELECT * FROM {table_name} LIMIT 20;", None
        
        # AVERAGE
        if "average" in question or "avg" in question or "mean" in question:
            if col_names:
                for col in col_names:
                    if col.lower() in question:
                        return f"SELECT AVG({col}) as average FROM {table_name};", None
                return f"SELECT AVG({col_names[0]}) as average FROM {table_name};", None
            return f"SELECT * FROM {table_name} LIMIT 20;", None
        
        # MIN/MAX
        if "minimum" in question or "lowest" in question or "min" in question:
            if col_names:
                for col in col_names:
                    if col.lower() in question:
                        return f"SELECT * FROM {table_name} ORDER BY {col} ASC LIMIT 10;", None
            return f"SELECT * FROM {table_name} LIMIT 20;", None
        
        if "maximum" in question or "highest" in question or "max" in question:
            if col_names:
                for col in col_names:
                    if col.lower() in question:
                        return f"SELECT * FROM {table_name} ORDER BY {col} DESC LIMIT 10;", None
            return f"SELECT * FROM {table_name} LIMIT 20;", None
        
        # GROUP BY / COUNT
        if "group" in question or "by" in question:
            if col_names:
                for col in col_names:
                    if col.lower() in question:
                        return f"SELECT {col}, COUNT(*) as count FROM {table_name} GROUP BY {col};", None
            return f"SELECT * FROM {table_name} LIMIT 20;", None
        
        # Default: SELECT all
        return f"SELECT * FROM {table_name} LIMIT 20;", None
        
    except Exception as e:
        return None, f"Error generating SQL: {str(e)}"


def generate_example_questions(table_names):
    """Generate example questions"""
    return [
        "How many rows are there?",
        "Show the first 10 rows.",
        "What are the distinct values?",
        "Which rows have the highest values?",
        "What is the average value?",
    ], None


def generate_table_insights(table_name):
    """Generate insights about table"""
    return [
        "Table uploaded successfully.",
        "Ready to answer questions about your data.",
        "Use natural language to query your data.",
    ], None


def generate_follow_up_questions(result_df, original_question, table_names):
    """Generate follow-up questions"""
    return [
        "Show me more details.",
        "What is the average value?",
        "Count rows by category.",
        "Find the highest values.",
    ], None


def generate_result_summary(result_df, user_question, table_names):
    """Generate summary of results"""
    if result_df is None or result_df.empty:
        return "No results found.", None
    
    num_rows = len(result_df)
    num_cols = len(result_df.columns)
    
    return f"Query returned {num_rows} rows with {num_cols} columns.", None
