import copy
import io
import importlib.util
import re
import time

import altair as alt
import pandas as pd
import streamlit as st

from ai_query import (
    generate_example_questions,
    generate_follow_up_questions,
    generate_result_summary,
    generate_sql,
    generate_table_insights,
)
from db import (
    authenticate_user,
    create_user,
    ensure_users_table,
    get_schema,
    insert_data,
    load_user_workspace,
    run_query,
    save_user_workspace,
)


FALLBACK_EXAMPLE_QUESTIONS = [
    "How many rows are there?",
    "Show the first 10 rows.",
    "What are the distinct values in the main text columns?",
    "Which rows have the highest values in a numeric column?",
    "Which rows have the lowest values in a numeric column?",
    "What is the average of a numeric column?",
    "Count rows grouped by a useful category column.",
]

OPENPYXL_AVAILABLE = importlib.util.find_spec("openpyxl") is not None

THEME_CONFIGS = {
    "Dark": {
        "description": "High-contrast workspace with electric accents.",
        "app_bg": "#08111f",
        "app_bg_secondary": "#0f172a",
        "sidebar_bg": "#0b1324",
        "surface": "#111c30",
        "surface_soft": "#16233a",
        "surface_strong": "#1b2a44",
        "border": "rgba(148, 163, 184, 0.18)",
        "text": "#e5eefb",
        "muted": "#9fb2cc",
        "primary": "#38bdf8",
        "primary_strong": "#0ea5e9",
        "accent": "#22c55e",
        "glow_one": "rgba(56, 189, 248, 0.22)",
        "glow_two": "rgba(34, 197, 94, 0.16)",
        "shadow": "rgba(8, 15, 30, 0.6)",
        "input_bg": "rgba(15, 23, 42, 0.82)",
        "code_bg": "#0b1220",
        "chart_bg": "#111c30",
        "chart_text": "#dce7f8",
        "chart_grid": "rgba(159, 178, 204, 0.18)",
        "chart_palette": ["#38bdf8", "#22c55e", "#f59e0b", "#fb7185", "#a78bfa"],
    },
    "Light": {
        "description": "Clean and bright with crisp blue highlights.",
        "app_bg": "#f5f7fb",
        "app_bg_secondary": "#e9eef8",
        "sidebar_bg": "#eef4ff",
        "surface": "#ffffff",
        "surface_soft": "#f8fbff",
        "surface_strong": "#eef4ff",
        "border": "rgba(15, 23, 42, 0.10)",
        "text": "#102038",
        "muted": "#5b6c84",
        "primary": "#2563eb",
        "primary_strong": "#1d4ed8",
        "accent": "#14b8a6",
        "glow_one": "rgba(37, 99, 235, 0.12)",
        "glow_two": "rgba(20, 184, 166, 0.10)",
        "shadow": "rgba(37, 99, 235, 0.12)",
        "input_bg": "#ffffff",
        "code_bg": "#f3f7fd",
        "chart_bg": "#ffffff",
        "chart_text": "#102038",
        "chart_grid": "rgba(16, 32, 56, 0.12)",
        "chart_palette": ["#2563eb", "#14b8a6", "#f97316", "#ec4899", "#8b5cf6"],
    },
    "Colorful": {
        "description": "More playful gradients, richer contrast, and bolder energy.",
        "app_bg": "#120f2f",
        "app_bg_secondary": "#22124d",
        "sidebar_bg": "#1d1242",
        "surface": "#261954",
        "surface_soft": "#31206a",
        "surface_strong": "#3b2380",
        "border": "rgba(255, 255, 255, 0.12)",
        "text": "#fff3ff",
        "muted": "#d7c9f3",
        "primary": "#ff6b6b",
        "primary_strong": "#ff8e53",
        "accent": "#2dd4bf",
        "glow_one": "rgba(255, 107, 107, 0.22)",
        "glow_two": "rgba(45, 212, 191, 0.18)",
        "shadow": "rgba(17, 12, 36, 0.55)",
        "input_bg": "rgba(37, 24, 82, 0.88)",
        "code_bg": "#1b113e",
        "chart_bg": "#261954",
        "chart_text": "#fff3ff",
        "chart_grid": "rgba(255, 255, 255, 0.14)",
        "chart_palette": ["#ff6b6b", "#ffd166", "#06d6a0", "#4cc9f0", "#c77dff"],
    },
}


def get_session_defaults():
    return {
        "user": None,
        "theme_mode": "Dark",
        "theme_transition": None,
        "workspace_loaded_for": None,
        "workspace_persistence_error": None,
        "uploaded_tables": {},
        "current_table": None,
        "selected_tables": [],
        "question_input": "",
        "generated_sql": "",
        "editable_sql": "",
        "last_run": None,
        "query_history": [],
        "dashboard_cards": [],
        "pending_question_input": None,
        "pending_selected_tables": None,
        "pending_generated_sql": None,
        "pending_editable_sql": None,
    }


def init_session_state():
    for key, value in get_session_defaults().items():
        if key not in st.session_state:
            st.session_state[key] = copy.deepcopy(value)


def reset_session_state(preserve_user=False):
    current_user = st.session_state.get("user") if preserve_user else None
    current_theme = st.session_state.get("theme_mode", "Dark")
    for key, value in get_session_defaults().items():
        if key == "user" and preserve_user:
            st.session_state[key] = current_user
        elif key == "theme_mode":
            st.session_state[key] = current_theme
        else:
            st.session_state[key] = copy.deepcopy(value)


def make_json_safe(value):
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass

    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, TypeError):
            pass

    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return str(value)

    if hasattr(value, "isoformat") and not isinstance(value, (str, bytes)):
        return value.isoformat()

    return value


def dataframe_to_payload(df):
    safe_df = df.astype(object).apply(lambda column: column.map(make_json_safe))
    return {
        "columns": list(safe_df.columns),
        "records": safe_df.to_dict(orient="records"),
    }


def dataframe_from_payload(payload):
    if not payload:
        return pd.DataFrame()

    columns = payload.get("columns", [])
    records = payload.get("records", [])
    return pd.DataFrame(records, columns=columns)


def serialize_table_metadata(metadata):
    return {
        "file_name": metadata["file_name"],
        "table_name": metadata["table_name"],
        "row_count": metadata["row_count"],
        "column_count": metadata["column_count"],
        "columns": metadata["columns"],
        "preview": dataframe_to_payload(metadata["preview"]),
        "profile_text": metadata["profile_text"],
        "local_insights": metadata["local_insights"],
    }


def deserialize_table_metadata(payload):
    return {
        "file_name": payload["file_name"],
        "table_name": payload["table_name"],
        "row_count": payload["row_count"],
        "column_count": payload["column_count"],
        "columns": payload["columns"],
        "preview": dataframe_from_payload(payload.get("preview")),
        "profile_text": payload["profile_text"],
        "local_insights": payload["local_insights"],
    }


def serialize_result_entry(entry):
    return {
        "id": entry["id"],
        "question": entry["question"],
        "sql": entry["sql"],
        "table_names": entry["table_names"],
        "result_df": dataframe_to_payload(entry["result_df"]),
        "summary": entry["summary"],
        "follow_ups": entry["follow_ups"],
        "chart_default": entry["chart_default"],
    }


def deserialize_result_entry(payload):
    return {
        "id": payload["id"],
        "question": payload["question"],
        "sql": payload["sql"],
        "table_names": payload["table_names"],
        "result_df": dataframe_from_payload(payload.get("result_df")),
        "summary": payload["summary"],
        "follow_ups": payload["follow_ups"],
        "chart_default": payload["chart_default"],
    }


def serialize_dashboard_card(card):
    return {
        "id": card["id"],
        "question": card["question"],
        "summary": card["summary"],
        "result_df": dataframe_to_payload(card["result_df"]),
        "chart_default": card["chart_default"],
        "table_names": card["table_names"],
    }


def deserialize_dashboard_card(payload):
    return {
        "id": payload["id"],
        "question": payload["question"],
        "summary": payload["summary"],
        "result_df": dataframe_from_payload(payload.get("result_df")),
        "chart_default": payload["chart_default"],
        "table_names": payload["table_names"],
    }


def build_workspace_payload():
    return {
        "theme_mode": st.session_state.get("theme_mode", "Dark"),
        "uploaded_tables": {
            table_name: serialize_table_metadata(metadata)
            for table_name, metadata in st.session_state["uploaded_tables"].items()
        },
        "current_table": st.session_state.get("current_table"),
        "selected_tables": st.session_state.get("selected_tables", []),
        "question_input": st.session_state.get("question_input", ""),
        "generated_sql": st.session_state.get("generated_sql", ""),
        "editable_sql": st.session_state.get("editable_sql", ""),
        "last_run": (
            serialize_result_entry(st.session_state["last_run"])
            if st.session_state.get("last_run")
            else None
        ),
        "query_history": [
            serialize_result_entry(entry)
            for entry in st.session_state.get("query_history", [])
        ],
        "dashboard_cards": [
            serialize_dashboard_card(card)
            for card in st.session_state.get("dashboard_cards", [])
        ],
        "pending_question_input": st.session_state.get("pending_question_input"),
        "pending_selected_tables": st.session_state.get("pending_selected_tables"),
        "pending_generated_sql": st.session_state.get("pending_generated_sql"),
        "pending_editable_sql": st.session_state.get("pending_editable_sql"),
    }


def load_workspace_into_session(workspace):
    uploaded_tables = {
        table_name: deserialize_table_metadata(metadata)
        for table_name, metadata in workspace.get("uploaded_tables", {}).items()
    }
    available_tables = set(uploaded_tables.keys())

    current_table = workspace.get("current_table")
    if current_table not in available_tables:
        current_table = next(reversed(uploaded_tables), None) if uploaded_tables else None

    selected_tables = [
        table_name
        for table_name in workspace.get("selected_tables", [])
        if table_name in available_tables
    ]
    if not selected_tables and current_table:
        selected_tables = [current_table]

    pending_selected_tables = [
        table_name
        for table_name in (workspace.get("pending_selected_tables") or [])
        if table_name in available_tables
    ]

    st.session_state["theme_mode"] = workspace.get(
        "theme_mode",
        st.session_state.get("theme_mode", "Dark"),
    )
    if st.session_state["theme_mode"] not in THEME_CONFIGS:
        st.session_state["theme_mode"] = "Dark"

    st.session_state["uploaded_tables"] = uploaded_tables
    st.session_state["current_table"] = current_table
    st.session_state["selected_tables"] = selected_tables
    st.session_state["question_input"] = workspace.get("question_input", "")
    st.session_state["generated_sql"] = workspace.get("generated_sql", "")
    st.session_state["editable_sql"] = workspace.get("editable_sql", "")
    st.session_state["last_run"] = (
        deserialize_result_entry(workspace["last_run"])
        if workspace.get("last_run")
        else None
    )
    st.session_state["query_history"] = [
        deserialize_result_entry(entry)
        for entry in workspace.get("query_history", [])
    ]
    st.session_state["dashboard_cards"] = [
        deserialize_dashboard_card(card)
        for card in workspace.get("dashboard_cards", [])
    ]
    st.session_state["pending_question_input"] = workspace.get("pending_question_input")
    st.session_state["pending_selected_tables"] = pending_selected_tables or None
    st.session_state["pending_generated_sql"] = workspace.get("pending_generated_sql")
    st.session_state["pending_editable_sql"] = workspace.get("pending_editable_sql")


def load_current_user_workspace():
    user = st.session_state.get("user")
    if not user:
        return

    if st.session_state.get("workspace_loaded_for") == user["id"]:
        return

    try:
        workspace = load_user_workspace(user["id"])
        if workspace:
            load_workspace_into_session(workspace)
        st.session_state["workspace_persistence_error"] = None
        st.session_state["workspace_loaded_for"] = user["id"]
    except Exception as exc:
        st.session_state["workspace_persistence_error"] = (
            f"Could not load saved workspace: {exc}"
        )


def save_current_workspace():
    user = st.session_state.get("user")
    if not user:
        return

    if st.session_state.get("workspace_loaded_for") != user["id"]:
        return

    try:
        save_user_workspace(user["id"], build_workspace_payload())
        st.session_state["workspace_persistence_error"] = None
    except Exception as exc:
        st.session_state["workspace_persistence_error"] = (
            f"Could not save workspace: {exc}"
        )


def get_active_theme():
    return THEME_CONFIGS.get(
        st.session_state.get("theme_mode", "Dark"),
        THEME_CONFIGS["Dark"],
    )


def apply_theme_css():
    theme = get_active_theme()
    st.markdown(
        f"""
        <style>
        :root {{
            --app-bg: {theme["app_bg"]};
            --app-bg-secondary: {theme["app_bg_secondary"]};
            --sidebar-bg: {theme["sidebar_bg"]};
            --surface: {theme["surface"]};
            --surface-soft: {theme["surface_soft"]};
            --surface-strong: {theme["surface_strong"]};
            --border-color: {theme["border"]};
            --text-primary: {theme["text"]};
            --text-muted: {theme["muted"]};
            --primary: {theme["primary"]};
            --primary-strong: {theme["primary_strong"]};
            --accent: {theme["accent"]};
            --input-bg: {theme["input_bg"]};
            --code-bg: {theme["code_bg"]};
            --shadow-color: {theme["shadow"]};
        }}

        .stApp {{
            color: var(--text-primary);
            background:
                radial-gradient(circle at top left, {theme["glow_one"]} 0%, transparent 32%),
                radial-gradient(circle at top right, {theme["glow_two"]} 0%, transparent 30%),
                linear-gradient(180deg, var(--app-bg) 0%, var(--app-bg-secondary) 100%);
        }}

        .stApp,
        [data-testid="stSidebar"],
        [data-testid="stMetric"],
        [data-testid="stFileUploader"],
        [data-testid="stExpander"],
        [data-testid="stDataFrame"],
        [data-testid="stCodeBlock"],
        [data-testid="stForm"],
        .stTabs [data-baseweb="tab-panel"],
        [data-testid="stFileUploaderDropzone"],
        div[data-baseweb="input"] > div,
        div[data-baseweb="base-input"] > div,
        div[data-baseweb="select"] > div,
        textarea,
        input,
        .stButton > button,
        .stDownloadButton > button,
        .stFormSubmitButton > button,
        button[data-baseweb="tab"] {{
            transition:
                background 0.35s ease,
                background-color 0.35s ease,
                color 0.25s ease,
                border-color 0.25s ease,
                box-shadow 0.25s ease,
                transform 0.18s ease,
                filter 0.18s ease;
        }}

        [data-testid="stHeader"] {{
            background: transparent;
        }}

        [data-testid="stAppViewContainer"] > .main {{
            background: transparent;
        }}

        .block-container {{
            padding-top: 2rem;
            padding-bottom: 3rem;
        }}

        [data-testid="stSidebar"] {{
            background: linear-gradient(180deg, var(--sidebar-bg) 0%, var(--surface) 100%);
            border-right: 1px solid var(--border-color);
        }}

        [data-testid="stSidebar"] * {{
            color: var(--text-primary);
        }}

        h1, h2, h3, h4, h5, h6, p, li {{
            color: inherit;
        }}

        [data-testid="stAppViewContainer"],
        [data-testid="stAppViewContainer"] * {{
            color: var(--text-primary);
        }}

        [data-testid="stSidebar"] a,
        [data-testid="stAppViewContainer"] a {{
            color: var(--primary) !important;
        }}

        [data-testid="stWidgetLabel"],
        [data-testid="stWidgetLabel"] *,
        [data-baseweb="radio"],
        [data-baseweb="radio"] *,
        [role="radiogroup"] label,
        [role="radiogroup"] label * {{
            color: var(--text-primary) !important;
        }}

        [data-testid="stWidgetLabel"] {{
            font-weight: 600;
        }}

        [data-testid="stMetric"],
        [data-testid="stFileUploader"],
        [data-testid="stExpander"],
        [data-testid="stDataFrame"],
        [data-testid="stCodeBlock"],
        [data-testid="stForm"],
        .stTabs [data-baseweb="tab-panel"] {{
            background: var(--surface-soft);
            border: 1px solid var(--border-color);
            border-radius: 18px;
            box-shadow: 0 22px 40px -30px var(--shadow-color);
        }}

        [data-testid="stMetric"] {{
            padding: 0.9rem 1rem;
        }}

        [data-testid="stFileUploaderDropzone"] {{
            background: var(--surface-soft);
            border: 1px dashed var(--border-color);
            border-radius: 18px;
        }}

        [data-testid="stFileUploaderDropzone"] button {{
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-strong) 100%) !important;
            color: #ffffff !important;
            border: 0 !important;
            border-radius: 14px !important;
            font-weight: 600 !important;
        }}

        div[data-baseweb="input"] > div,
        div[data-baseweb="base-input"] > div,
        div[data-baseweb="select"] > div,
        textarea,
        input {{
            background: var(--input-bg) !important;
            border: 1px solid var(--border-color) !important;
            border-radius: 14px !important;
            color: var(--text-primary) !important;
        }}

        textarea::placeholder,
        input::placeholder {{
            color: var(--text-muted) !important;
        }}

        .stButton > button,
        .stDownloadButton > button,
        .stFormSubmitButton > button {{
            border: 1px solid transparent;
            border-radius: 999px;
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-strong) 100%);
            color: #ffffff;
            font-weight: 600;
            box-shadow: 0 18px 30px -22px var(--shadow-color);
            transition: transform 0.18s ease, box-shadow 0.18s ease, filter 0.18s ease;
        }}

        .stButton > button:hover,
        .stDownloadButton > button:hover,
        .stFormSubmitButton > button:hover {{
            transform: translateY(-1px);
            filter: brightness(1.03);
            box-shadow: 0 22px 34px -22px var(--shadow-color);
        }}

        .stButton > button[kind="secondary"] {{
            background: var(--surface-strong);
            color: var(--text-primary);
            border-color: var(--border-color);
        }}

        button[data-baseweb="tab"] {{
            border-radius: 999px;
            background: transparent;
            color: var(--text-muted);
        }}

        button[data-baseweb="tab"][aria-selected="true"] {{
            background: var(--surface-strong);
            color: var(--text-primary);
        }}

        [data-testid="stNotificationContentInfo"],
        [data-testid="stNotificationContentSuccess"],
        [data-testid="stNotificationContentWarning"],
        [data-testid="stNotificationContentError"] {{
            background: var(--surface-soft);
            border-radius: 16px;
        }}

        pre, code {{
            background: var(--code-bg) !important;
            color: var(--text-primary) !important;
        }}

        .stCaption {{
            color: var(--text-muted);
        }}

        [role="radiogroup"] {{
            gap: 0.35rem;
        }}

        [role="radiogroup"] > label {{
            border-radius: 999px;
            padding: 0.2rem 0.55rem 0.2rem 0.15rem;
            transition: background-color 0.22s ease, transform 0.22s ease;
        }}

        [role="radiogroup"] > label:hover {{
            background: var(--surface-soft);
            transform: translateY(-1px);
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_theme_transition():
    transition = st.session_state.get("theme_transition")
    if not transition:
        return

    theme_name = transition.get("theme")
    theme = THEME_CONFIGS.get(theme_name)
    if not theme:
        st.session_state["theme_transition"] = None
        return

    transition_key = transition.get("key", f"{theme_name}-{time.time_ns()}")
    st.markdown(
        f"""
        <style>
        .theme-transition-circle[data-transition-key="{transition_key}"] {{
            position: fixed;
            inset: 0;
            pointer-events: none;
            z-index: 9999;
            overflow: hidden;
        }}

        .theme-transition-circle[data-transition-key="{transition_key}"]::before {{
            content: "";
            position: absolute;
            width: 8rem;
            height: 8rem;
            top: 5.75rem;
            right: clamp(1.5rem, 9vw, 10rem);
            border-radius: 50%;
            background:
                radial-gradient(circle at 32% 32%, rgba(255, 255, 255, 0.32) 0%, transparent 38%),
                linear-gradient(135deg, {theme["primary"]} 0%, {theme["accent"]} 100%);
            box-shadow:
                0 0 0 1px {theme["border"]},
                0 0 90px {theme["glow_one"]};
            transform: translate(50%, -50%) scale(0.16);
            opacity: 0.92;
            animation: theme-circle-burst-{transition_key} 820ms cubic-bezier(0.22, 1, 0.36, 1) forwards;
        }}

        .theme-transition-circle[data-transition-key="{transition_key}"]::after {{
            content: "";
            position: absolute;
            inset: -18vmax;
            background:
                radial-gradient(circle at 86% 11%, {theme["glow_one"]} 0%, transparent 16%),
                radial-gradient(circle at 82% 15%, {theme["glow_two"]} 0%, transparent 18%);
            opacity: 0.28;
            animation: theme-overlay-fade-{transition_key} 820ms ease-out forwards;
        }}

        @keyframes theme-circle-burst-{transition_key} {{
            0% {{
                transform: translate(50%, -50%) scale(0.16);
                opacity: 0.92;
            }}
            45% {{
                opacity: 0.78;
            }}
            100% {{
                transform: translate(50%, -50%) scale(28);
                opacity: 0;
            }}
        }}

        @keyframes theme-overlay-fade-{transition_key} {{
            0% {{
                opacity: 0.28;
            }}
            100% {{
                opacity: 0;
            }}
        }}
        </style>
        <div class="theme-transition-circle" data-transition-key="{transition_key}"></div>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["theme_transition"] = None


def render_theme_picker():
    theme_names = list(THEME_CONFIGS.keys())
    current_theme = st.session_state.get("theme_mode", "Dark")
    selected_theme = st.radio(
        "Theme mode",
        theme_names,
        index=theme_names.index(current_theme),
        horizontal=True,
        label_visibility="collapsed",
        help="Switch between light, dark, and a more colorful look.",
    )

    if selected_theme != current_theme:
        st.session_state["theme_mode"] = selected_theme
        st.session_state["theme_transition"] = {
            "theme": selected_theme,
            "key": f"{selected_theme.lower()}-{time.time_ns()}",
        }
        save_current_workspace()
        st.rerun()


def sanitize_dataframe(df):
    sanitized_df = df.copy()
    sanitized_df.columns = [
        col.strip().replace(" ", "_").lower() for col in sanitized_df.columns
    ]
    return sanitized_df


def build_profile_text(df):
    lines = [
        f"Rows: {len(df)}",
        f"Columns: {len(df.columns)}",
        f"Column names: {', '.join(df.columns)}",
    ]

    missing = df.isna().sum()
    missing = missing[missing > 0].sort_values(ascending=False)
    if not missing.empty:
        lines.append(
            "Missing values: "
            + ", ".join(f"{col}={int(count)}" for col, count in missing.head(5).items())
        )
    else:
        lines.append("Missing values: none")

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if numeric_cols:
        lines.append("Numeric columns: " + ", ".join(numeric_cols))
        numeric_summary = (
            df[numeric_cols]
            .agg(["mean", "min", "max"])
            .transpose()
            .round(2)
            .head(5)
        )
        for col, row in numeric_summary.iterrows():
            lines.append(
                f"{col} stats: mean={row['mean']}, min={row['min']}, max={row['max']}"
            )
    else:
        lines.append("Numeric columns: none")

    text_cols = [col for col in df.columns if col not in numeric_cols]
    if text_cols:
        lines.append("Text columns: " + ", ".join(text_cols[:8]))
        for col in text_cols[:4]:
            top_values = (
                df[col].dropna().astype(str).value_counts().head(3).index.tolist()
            )
            if top_values:
                lines.append(f"Top values in {col}: {', '.join(top_values)}")

    return "\n".join(lines)


def build_local_insights(df):
    insights = [f"Dataset has {len(df)} rows and {len(df.columns)} columns."]

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    text_cols = [col for col in df.columns if col not in numeric_cols]

    if numeric_cols:
        insights.append(f"Numeric columns available: {', '.join(numeric_cols[:5])}.")
        non_null_counts = df[numeric_cols].count().sort_values(ascending=False)
        if not non_null_counts.empty:
            insights.append(
                f"`{non_null_counts.index[0]}` has the most populated numeric values."
            )

    if text_cols:
        richest_text_col = (
            df[text_cols].nunique(dropna=True).sort_values(ascending=False).index[0]
        )
        insights.append(
            f"`{richest_text_col}` has the widest variety of text values to filter on."
        )

    missing = df.isna().sum().sort_values(ascending=False)
    if not missing.empty and int(missing.iloc[0]) > 0:
        insights.append(
            f"`{missing.index[0]}` has the most missing values ({int(missing.iloc[0])})."
        )
    else:
        insights.append("No missing values were detected in the uploaded data.")

    return insights[:4]


def build_table_metadata(file_name, table_name, df):
    return {
        "file_name": file_name,
        "table_name": table_name,
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": list(df.columns),
        "preview": df.head(10),
        "profile_text": build_profile_text(df),
        "local_insights": build_local_insights(df),
    }


def format_table_label(table_name):
    metadata = st.session_state["uploaded_tables"].get(table_name, {})
    file_name = metadata.get("file_name", table_name)
    return f"{file_name} -> {table_name}"


def suggestions_cache_key(table_names):
    return "example_questions_" + "__".join(sorted(table_names))


def follow_up_button_key(prefix, question):
    safe_text = re.sub(r"[^a-zA-Z0-9]+", "_", question.lower()).strip("_")
    return f"{prefix}_{safe_text}_{abs(hash(question))}"


def build_excel_bytes(df):
    if not OPENPYXL_AVAILABLE:
        return None

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="results")
    buffer.seek(0)
    return buffer.getvalue()


def validate_select_sql(sql):
    if not sql.strip():
        return "SQL cannot be empty."
    if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        return "Only SELECT queries are allowed."
    return None


def validate_email(email):
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))


def render_auth_screen():
    st.title("AI SQL Assistant")
    st.caption("Create an account or log in to use the app.")

    login_tab, signup_tab = st.tabs(["Login", "Sign Up"])

    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button(
                "Login",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            if not email.strip() or not password:
                st.error("Please enter both email and password.")
            else:
                try:
                    user = authenticate_user(email, password)
                except Exception as exc:
                    st.error(f"Login failed because the database is unavailable: {exc}")
                else:
                    if user:
                        st.session_state["user"] = user
                        reset_session_state(preserve_user=True)
                        st.success("Login successful.")
                        st.rerun()
                    else:
                        st.error("Invalid email or password.")

    with signup_tab:
        with st.form("signup_form"):
            full_name = st.text_input("Full Name")
            email = st.text_input("Email", key="signup_email")
            password = st.text_input("Password", type="password", key="signup_password")
            confirm_password = st.text_input(
                "Confirm Password",
                type="password",
                key="signup_confirm_password",
            )
            submitted = st.form_submit_button(
                "Create Account",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            if not full_name.strip():
                st.error("Full name is required.")
            elif not validate_email(email):
                st.error("Enter a valid email address.")
            elif len(password) < 8:
                st.error("Password must be at least 8 characters.")
            elif password != confirm_password:
                st.error("Passwords do not match.")
            else:
                try:
                    user, error = create_user(full_name, email, password)
                except Exception as exc:
                    st.error(f"Sign up failed because the database is unavailable: {exc}")
                else:
                    if error:
                        st.error(error)
                    else:
                        st.session_state["user"] = user
                        reset_session_state(preserve_user=True)
                        st.success("Account created successfully.")
                        st.rerun()


def get_chart_spec(df):
    if df.empty:
        return {"options": ["Table"], "default": "Table"}

    numeric_cols = [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])]
    categorical_cols = [
        col for col in df.columns if not pd.api.types.is_numeric_dtype(df[col])
    ]

    if categorical_cols and numeric_cols:
        return {
            "options": ["Table", "Bar", "Line", "Pie"],
            "default": "Bar",
            "x": categorical_cols[0],
            "y": numeric_cols[0],
            "mode": "categorical_numeric",
        }

    if len(numeric_cols) >= 2:
        return {
            "options": ["Table", "Scatter", "Line"],
            "default": "Scatter",
            "x": numeric_cols[0],
            "y": numeric_cols[1],
            "mode": "numeric_numeric",
        }

    return {"options": ["Table"], "default": "Table"}


def render_chart(df, chart_type, key_prefix):
    chart_spec = get_chart_spec(df)
    if chart_type == "Table" or len(chart_spec["options"]) == 1:
        st.dataframe(df, use_container_width=True)
        return

    theme = get_active_theme()
    chart_df = df.head(25).copy()
    x_col = chart_spec["x"]
    y_col = chart_spec["y"]

    if chart_type == "Bar":
        chart = alt.Chart(chart_df).mark_bar(
            color=theme["primary"],
            cornerRadiusTopLeft=8,
            cornerRadiusTopRight=8,
        ).encode(
            x=alt.X(f"{x_col}:N", sort="-y"),
            y=alt.Y(f"{y_col}:Q"),
            tooltip=list(chart_df.columns),
        )
    elif chart_type == "Line":
        x_type = "Q" if chart_spec["mode"] == "numeric_numeric" else "N"
        chart = alt.Chart(chart_df).mark_line(
            point={"filled": True, "size": 85},
            color=theme["accent"],
            strokeWidth=3,
        ).encode(
            x=alt.X(f"{x_col}:{x_type}"),
            y=alt.Y(f"{y_col}:Q"),
            tooltip=list(chart_df.columns),
        )
    elif chart_type == "Pie":
        chart = alt.Chart(chart_df).mark_arc(outerRadius=125).encode(
            theta=alt.Theta(f"{y_col}:Q"),
            color=alt.Color(
                f"{x_col}:N",
                scale=alt.Scale(range=theme["chart_palette"]),
                legend=alt.Legend(orient="bottom"),
            ),
            tooltip=list(chart_df.columns),
        )
    elif chart_type == "Scatter":
        chart = alt.Chart(chart_df).mark_circle(
            size=140,
            color=theme["primary"],
            opacity=0.85,
        ).encode(
            x=alt.X(f"{x_col}:Q"),
            y=alt.Y(f"{y_col}:Q"),
            tooltip=list(chart_df.columns),
        )
    else:
        st.dataframe(df, use_container_width=True)
        return

    chart = (
        chart.properties(height=320, background=theme["chart_bg"])
        .configure_view(strokeWidth=0)
        .configure_axis(
            labelColor=theme["chart_text"],
            titleColor=theme["chart_text"],
            domainColor=theme["chart_grid"],
            tickColor=theme["chart_grid"],
            gridColor=theme["chart_grid"],
        )
        .configure_legend(
            labelColor=theme["chart_text"],
            titleColor=theme["chart_text"],
        )
    )

    st.altair_chart(chart, use_container_width=True)
    if len(df) > len(chart_df):
        st.caption("Chart preview is limited to the first 25 rows.")


def set_question(question, selected_tables=None, sql=""):
    st.session_state["pending_question_input"] = question
    st.session_state["pending_selected_tables"] = selected_tables
    st.session_state["pending_generated_sql"] = sql
    st.session_state["pending_editable_sql"] = sql
    save_current_workspace()


def apply_pending_question_state():
    if st.session_state.get("pending_question_input") is not None:
        st.session_state["question_input"] = st.session_state["pending_question_input"]
        st.session_state["pending_question_input"] = None

    pending_tables = st.session_state.get("pending_selected_tables")
    if pending_tables:
        st.session_state["selected_tables"] = pending_tables
    st.session_state["pending_selected_tables"] = None

    if st.session_state.get("pending_generated_sql") is not None:
        st.session_state["generated_sql"] = st.session_state["pending_generated_sql"]
        st.session_state["pending_generated_sql"] = None

    if st.session_state.get("pending_editable_sql") is not None:
        st.session_state["editable_sql"] = st.session_state["pending_editable_sql"]
        st.session_state["pending_editable_sql"] = None


def add_to_history(entry):
    history = st.session_state["query_history"]
    history.insert(0, entry)
    st.session_state["query_history"] = history[:15]


def execute_sql_workflow(question, sql, table_names):
    validation_error = validate_select_sql(sql)
    if validation_error:
        st.error(f"⚠️ {validation_error}")
        return

    with st.spinner("Running SQL and generating AI insights..."):
        result = run_query(sql)
        if isinstance(result, str):
            st.error(f"❌ MySQL Error: {result}")
            return

        result_df = pd.DataFrame(result)

        if result_df.empty:
            fallback_summary = "The query ran successfully but returned no rows."
        else:
            fallback_summary = (
                f"The query returned {len(result_df)} rows and {len(result_df.columns)} columns."
            )

        summary, summary_error = generate_result_summary(question, sql, result_df, table_names)
        if summary_error or not summary:
            summary = fallback_summary

        follow_ups, follow_up_error = generate_follow_up_questions(
            question, sql, result_df, table_names
        )
        if follow_up_error or not follow_ups:
            follow_ups = []

    chart_spec = get_chart_spec(result_df)
    entry = {
        "id": time.time_ns(),
        "question": question,
        "sql": sql,
        "table_names": list(table_names),
        "result_df": result_df,
        "summary": summary,
        "follow_ups": follow_ups,
        "chart_default": chart_spec["default"],
    }

    st.session_state["last_run"] = entry
    add_to_history(entry)
    save_current_workspace()


def render_result_block(result_entry, block_key, allow_dashboard=True):
    result_df = result_entry["result_df"]
    if result_df.empty:
        st.warning("⚠️ Query ran successfully but returned no results.")
    else:
        st.success(f"✅ {len(result_df)} row(s) returned")

    st.markdown("**AI Summary**")
    st.write(result_entry["summary"])

    st.markdown("**Result**")
    chart_spec = get_chart_spec(result_df)
    chart_type = st.selectbox(
        "Choose a view",
        chart_spec["options"],
        index=chart_spec["options"].index(result_entry["chart_default"]),
        key=f"chart_type_{block_key}",
    )
    render_chart(result_df, chart_type, block_key)

    csv_bytes = result_df.to_csv(index=False).encode("utf-8")
    excel_bytes = build_excel_bytes(result_df)
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "Download CSV",
            data=csv_bytes,
            file_name=f"query_result_{result_entry['id']}.csv",
            mime="text/csv",
            key=f"csv_download_{block_key}",
        )
    with col2:
        if excel_bytes is not None:
            st.download_button(
                "Download Excel",
                data=excel_bytes,
                file_name=f"query_result_{result_entry['id']}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"excel_download_{block_key}",
            )
        else:
            st.caption("Install `openpyxl` to enable Excel downloads.")

    if allow_dashboard:
        if st.button("Add this result to dashboard", key=f"dashboard_{block_key}"):
            st.session_state["dashboard_cards"].insert(
                0,
                {
                    "id": result_entry["id"],
                    "question": result_entry["question"],
                    "summary": result_entry["summary"],
                    "result_df": result_df.copy(),
                    "chart_default": chart_type,
                    "table_names": result_entry["table_names"],
                },
            )
            save_current_workspace()
            st.success("Saved to dashboard.")

    if result_entry["follow_ups"]:
        st.markdown("**Suggested follow-up questions**")
        for follow_up in result_entry["follow_ups"]:
            if st.button(
                follow_up,
                key=follow_up_button_key(f"follow_up_{block_key}", follow_up),
                use_container_width=True,
            ):
                set_question(follow_up, selected_tables=result_entry["table_names"])
                st.rerun()


st.set_page_config(page_title="AI SQL Assistant", layout="wide", page_icon="🧠")

init_session_state()
apply_theme_css()

try:
    ensure_users_table()
except Exception as exc:
    st.error(
        "Database connection failed while preparing login. "
        "Make sure your MySQL server is running and your DB settings are correct."
    )
    st.caption(str(exc))
    st.stop()

if not st.session_state["user"]:
    render_auth_screen()
    st.stop()

load_current_user_workspace()
apply_theme_css()
render_theme_transition()

title_col, theme_col = st.columns([0.72, 0.28])
with title_col:
    st.title("🧠 AI SQL Assistant")
with theme_col:
    st.markdown("#### Theme")
    render_theme_picker()

st.caption("Upload CSV files, explore them with AI, edit SQL safely, and build a mini dashboard.")

if st.session_state.get("workspace_persistence_error"):
    st.warning(st.session_state["workspace_persistence_error"])

with st.sidebar:
    user = st.session_state["user"]
    st.markdown(f"**Logged in as:** {user['full_name']}")
    st.caption(user["email"])
    if st.button("Logout", use_container_width=True):
        save_current_workspace()
        reset_session_state()
        st.rerun()

    st.divider()
    st.header("Workspace")
    uploaded_tables = st.session_state["uploaded_tables"]

    if uploaded_tables:
        table_names = list(uploaded_tables.keys())
        current_table = st.session_state["current_table"] or table_names[-1]
        if current_table not in table_names:
            current_table = table_names[-1]

        selected_active_table = st.selectbox(
            "Active table",
            table_names,
            index=table_names.index(current_table),
            format_func=format_table_label,
        )
        st.session_state["current_table"] = selected_active_table

        selected_tables = st.multiselect(
            "Tables for the next question",
            table_names,
            default=[
                table_name
                for table_name in st.session_state["selected_tables"]
                if table_name in table_names
            ]
            or [selected_active_table],
            format_func=format_table_label,
        )

        if not selected_tables:
            selected_tables = [selected_active_table]

        st.session_state["selected_tables"] = selected_tables
        st.caption(
            f"{len(uploaded_tables)} uploaded table(s), {len(st.session_state['query_history'])} saved query runs."
        )
    else:
        st.info("Upload one or more CSV files to start.")


st.subheader("📂 Step 1: Upload Your CSV Files")

uploaded_files = st.file_uploader(
    "Choose one or more CSV files",
    type=["csv"],
    accept_multiple_files=True,
)

pending_uploads = []
if uploaded_files:
    for uploaded_file in uploaded_files:
        uploaded_file.seek(0)
        preview_df = sanitize_dataframe(pd.read_csv(uploaded_file))
        pending_uploads.append((uploaded_file.name, preview_df))

    preview_tabs = st.tabs([name for name, _ in pending_uploads])
    for tab, (file_name, preview_df) in zip(preview_tabs, pending_uploads):
        with tab:
            st.write(
                f"**Preview** — {len(preview_df)} rows × {len(preview_df.columns)} columns"
            )
            st.dataframe(preview_df.head(10), use_container_width=True)

    if st.button("⬆️ Upload selected files to database", type="primary"):
        uploaded_count = 0
        for file_name, prepared_df in pending_uploads:
            try:
                table_name = insert_data(prepared_df.copy(), source_name=file_name)
                st.session_state["uploaded_tables"][table_name] = build_table_metadata(
                    file_name, table_name, prepared_df
                )
                st.session_state["current_table"] = table_name
                uploaded_count += 1
            except Exception as e:
                st.error(f"❌ Failed to upload `{file_name}`: {e}")

        if uploaded_count:
            st.session_state["selected_tables"] = [st.session_state["current_table"]]
            save_current_workspace()
            st.success(f"✅ Uploaded {uploaded_count} file(s) successfully.")
            st.rerun()


if st.session_state["current_table"]:
    current_table = st.session_state["current_table"]
    current_meta = st.session_state["uploaded_tables"][current_table]
    selected_tables = st.session_state["selected_tables"] or [current_table]
    scope_label = ", ".join(format_table_label(table) for table in selected_tables)

    st.info(
        f"🗄️ Active table: `{current_table}`\n\nQuery scope: {scope_label}"
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("Rows", f"{current_meta['row_count']}")
    col2.metric("Columns", f"{current_meta['column_count']}")
    col3.metric("Tables in scope", f"{len(selected_tables)}")

    with st.expander("📈 Quick insights about the active table", expanded=True):
        for insight in current_meta["local_insights"]:
            st.markdown(f"- {insight}")

        insights_key = f"ai_insights_{current_table}"
        error_key = f"{insights_key}_error"
        if insights_key not in st.session_state:
            with st.spinner("Generating AI insights for this upload..."):
                ai_insights, ai_error = generate_table_insights(
                    current_table, current_meta["profile_text"]
                )
                st.session_state[insights_key] = ai_insights or []
                st.session_state[error_key] = ai_error

        ai_insights = st.session_state.get(insights_key, [])
        ai_error = st.session_state.get(error_key)
        if ai_insights:
            st.markdown("**AI insights**")
            for insight in ai_insights:
                st.markdown(f"- {insight}")
        elif ai_error:
            st.caption("AI insights are unavailable right now.")


st.divider()

st.subheader("💬 Step 2: Ask a Question")

selected_tables = st.session_state["selected_tables"]
if selected_tables:
    with st.expander("💡 Example questions you can ask", expanded=True):
        cache_key = suggestions_cache_key(selected_tables)
        error_key = f"{cache_key}_error"

        if cache_key not in st.session_state:
            with st.spinner("Analyzing selected tables with AI to generate example questions..."):
                ai_questions, ai_error = generate_example_questions(selected_tables)
                st.session_state[cache_key] = ai_questions or FALLBACK_EXAMPLE_QUESTIONS
                st.session_state[error_key] = ai_error

        example_questions = st.session_state.get(cache_key, FALLBACK_EXAMPLE_QUESTIONS)
        ai_error = st.session_state.get(error_key)
        if ai_error:
            st.caption("AI suggestions are unavailable right now, so fallback questions are shown.")

        suggestion_columns = st.columns(2)
        for index, example_question in enumerate(example_questions):
            with suggestion_columns[index % 2]:
                if st.button(
                    example_question,
                    key=follow_up_button_key("example", example_question),
                    use_container_width=True,
                ):
                    set_question(example_question, selected_tables=selected_tables, sql="")
                    st.rerun()


apply_pending_question_state()

st.text_input(
    "Ask anything about your data:",
    key="question_input",
    placeholder="e.g. Compare average sales by city, or show the top 5 products",
)

query_action_col1, query_action_col2 = st.columns([1, 1])
with query_action_col1:
    if st.button("🧠 Generate SQL", type="primary", use_container_width=True):
        if not selected_tables:
            st.error("⚠️ Upload a CSV and select at least one table first.")
        elif not st.session_state["question_input"].strip():
            st.warning("⚠️ Please enter a question.")
        else:
            with st.spinner("Generating SQL from your question..."):
                sql, error = generate_sql(
                    st.session_state["question_input"],
                    selected_tables,
                )

            if error:
                st.error(f"❌ {error}")
                st.info("💡 Try rephrasing your question with clearer column names or values.")
            else:
                st.session_state["generated_sql"] = sql
                st.session_state["editable_sql"] = sql

with query_action_col2:
    if st.button("Clear question + SQL", use_container_width=True):
        set_question("", selected_tables=selected_tables, sql="")
        st.session_state["last_run"] = None
        save_current_workspace()
        st.rerun()


if st.session_state["generated_sql"]:
    st.markdown("**Generated SQL**")
    st.text_area(
        "Review or edit SQL before running it",
        key="editable_sql",
        height=160,
    )

    run_action_col1, run_action_col2 = st.columns([1, 1])
    with run_action_col1:
        if st.button("🔍 Run SQL", type="primary", use_container_width=True):
            execute_sql_workflow(
                st.session_state["question_input"].strip()
                or "Manual SQL run",
                st.session_state["editable_sql"],
                st.session_state["selected_tables"],
            )
    with run_action_col2:
        if st.button("Reset to generated SQL", use_container_width=True):
            st.session_state["editable_sql"] = st.session_state["generated_sql"]
            save_current_workspace()
            st.rerun()


if st.session_state["last_run"]:
    st.markdown("### Latest result")
    render_result_block(st.session_state["last_run"], "latest_result", allow_dashboard=True)


st.divider()

if st.session_state["query_history"]:
    st.subheader("🕘 Query history")
    for history_entry in st.session_state["query_history"]:
        label = f"{history_entry['question']} ({', '.join(history_entry['table_names'])})"
        with st.expander(label):
            st.markdown("**SQL**")
            st.code(history_entry["sql"], language="sql")
            st.write(history_entry["summary"])
            action_col1, action_col2 = st.columns(2)
            with action_col1:
                if st.button(
                    "Reuse this question",
                    key=f"reuse_question_{history_entry['id']}",
                    use_container_width=True,
                ):
                    set_question(
                        history_entry["question"],
                        selected_tables=history_entry["table_names"],
                        sql=history_entry["sql"],
                    )
                    st.rerun()
            with action_col2:
                if st.button(
                    "Show result again",
                    key=f"reuse_result_{history_entry['id']}",
                    use_container_width=True,
                ):
                    st.session_state["last_run"] = history_entry
                    save_current_workspace()
                    st.rerun()


if st.session_state["dashboard_cards"]:
    st.divider()
    st.subheader("📊 Dashboard mode")
    for card in st.session_state["dashboard_cards"]:
        with st.container(border=True):
            st.markdown(f"**{card['question']}**")
            st.caption("Tables: " + ", ".join(card["table_names"]))
            st.write(card["summary"])
            render_chart(card["result_df"], card["chart_default"], f"dashboard_{card['id']}")


if st.session_state["current_table"]:
    st.divider()
    st.subheader("🔎 Schema and sample data")

    for table_name in st.session_state["selected_tables"] or [st.session_state["current_table"]]:
        with st.expander(format_table_label(table_name)):
            st.text(get_schema(table_name))


save_current_workspace()
