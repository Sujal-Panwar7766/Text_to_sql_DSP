"""
AI Text-to-SQL SaaS Platform
Production-ready application with conversation management, query history, and modern UI
"""
import json
import time
import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime

from ai_query import (
    generate_example_questions,
    generate_follow_up_questions,
    generate_result_summary,
    generate_sql,
    generate_table_insights,
)
from db import (
    initialize_database,
    authenticate_user,
    create_user,
    create_conversation,
    get_user_conversations,
    get_conversation,
    update_conversation,
    delete_conversation,
    search_conversations,
    add_message,
    get_conversation_history,
    log_query,
    get_query_history,
    save_user_workspace,
    load_user_workspace,
    run_query,
    get_schema,
    insert_data,
    get_user_tables,
)

# ==================== PAGE CONFIG ====================

st.set_page_config(
    page_title="AI Text-to-SQL",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom UI styling for a modern workspace look
st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #0b1320 0%, #111827 100%);
        color: #e2e8f0;
    }
    section[data-testid="stSidebar"] {
        background: #0f172a;
        color: #e2e8f0;
    }
    .stButton>button {
        background: #2563eb;
        color: white;
        border-radius: 14px;
        border: none;
        box-shadow: 0 12px 30px rgba(37, 99, 235, 0.25);
    }
    .stButton>button:hover {
        background: #1d4ed8;
    }
    .stTextArea>div>textarea,
    .stTextInput>div>input {
        background: #0f172a;
        color: #f8fafc;
        border: 1px solid #334155;
        border-radius: 14px;
    }
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
        color: #f8fafc;
    }
    .stDataFrame table {
        border-radius: 14px;
        overflow: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Initialize database
initialize_database()

# ==================== SESSION STATE INITIALIZATION ====================

def init_session_state():
    """Initialize all session state variables"""
    if "user" not in st.session_state:
        st.session_state.user = None
    if "current_conversation" not in st.session_state:
        st.session_state.current_conversation = None
    if "current_tables" not in st.session_state:
        st.session_state.current_tables = []
    if "conversation_messages" not in st.session_state:
        st.session_state.conversation_messages = []
    if "search_results" not in st.session_state:
        st.session_state.search_results = None
    if "show_new_conversation" not in st.session_state:
        st.session_state.show_new_conversation = False
    if "theme" not in st.session_state:
        st.session_state.theme = "Dark"


init_session_state()


# ==================== AUTHENTICATION ====================

def show_auth_page():
    """Show login/signup page"""
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("---")
        st.markdown("# 📊 AI Text-to-SQL Platform")
        st.markdown("Convert natural language to SQL with AI-powered intelligence")
        st.markdown("---")
        
        auth_tab1, auth_tab2 = st.tabs(["Login", "Sign Up"])
        
        with auth_tab1:
            st.markdown("### Login to Your Account")
            login_email = st.text_input("Email", key="login_email")
            login_password = st.text_input("Password", type="password", key="login_password")
            
            if st.button("🔓 Login", use_container_width=True, type="primary"):
                if login_email and login_password:
                    user = authenticate_user(login_email, login_password)
                    if user:
                        st.session_state.user = user
                        st.success("✅ Logged in successfully!")
                        st.rerun()
                    else:
                        st.error("❌ Invalid email or password")
                else:
                    st.warning("⚠️ Please enter both email and password")
        
        with auth_tab2:
            st.markdown("### Create New Account")
            signup_name = st.text_input("Full Name", key="signup_name")
            signup_email = st.text_input("Email", key="signup_email")
            signup_password = st.text_input("Password", type="password", key="signup_password")
            signup_confirm = st.text_input("Confirm Password", type="password", key="signup_confirm")
            
            if st.button("✨ Create Account", use_container_width=True, type="primary"):
                if not all([signup_name, signup_email, signup_password, signup_confirm]):
                    st.warning("⚠️ Please fill in all fields")
                elif signup_password != signup_confirm:
                    st.error("❌ Passwords don't match")
                elif len(signup_password) < 6:
                    st.error("❌ Password must be at least 6 characters")
                else:
                    user, error = create_user(signup_name, signup_email, signup_password)
                    if user:
                        st.success("✅ Account created! Please login.")
                    else:
                        st.error(f"❌ {error}")
        
        st.markdown("---")
        st.markdown(
            "**Privacy & Security**: We use industry-standard encryption for all data. "
            "Your queries and data never leave our secure servers."
        )


# ==================== SIDEBAR - CONVERSATION HISTORY ====================

def show_sidebar():
    """Show conversation sidebar"""
    with st.sidebar:
        st.markdown("### 💬 Conversations")
        
        # New conversation button
        if st.button("➕ New Chat", use_container_width=True, key="new_chat_btn"):
            st.session_state.show_new_conversation = True
            st.session_state.current_conversation = None
            st.session_state.conversation_messages = []
            st.rerun()
        
        # Search box
        search_query = st.text_input("🔍 Search conversations", key="search_conv")
        
        if search_query:
            conversations = search_conversations(st.session_state.user["id"], search_query)
        else:
            conversations = get_user_conversations(st.session_state.user["id"])
        
        st.divider()
        
        # Active conversation
        if st.session_state.current_conversation:
            st.markdown(f"**Active:** {st.session_state.current_conversation['title'][:30]}")
            col1, col2 = st.columns([3, 1])
            with col1:
                if st.button("📝 Rename", key="rename_conv", use_container_width=True):
                    new_title = st.text_input("New title", value=st.session_state.current_conversation['title'])
                    if new_title:
                        update_conversation(
                            st.session_state.current_conversation['id'],
                            st.session_state.user["id"],
                            title=new_title
                        )
                        st.rerun()
            with col2:
                if st.button("🗑️", key="delete_conv"):
                    delete_conversation(
                        st.session_state.current_conversation['id'],
                        st.session_state.user["id"]
                    )
                    st.session_state.current_conversation = None
                    st.rerun()
            st.divider()
        
        # Conversation list
        if conversations:
            for conv in conversations:
                col1, col2 = st.columns([4, 1])
                with col1:
                    if st.button(
                        f"💭 {conv['title'][:25]}",
                        key=f"conv_{conv['id']}",
                        use_container_width=True
                    ):
                        st.session_state.current_conversation = conv
                        st.session_state.conversation_messages = get_conversation_history(
                            conv['id'], st.session_state.user["id"]
                        )
                        save_workspace_state()
                        st.rerun()
                with col2:
                    st.caption(f"({conv['message_count']})")
        else:
            st.info("📭 No conversations yet. Start a new chat!")
        
        st.divider()
        
        # User info & logout
        st.markdown(f"### 👤 {st.session_state.user['full_name']}")
        st.caption(st.session_state.user['email'])
        
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.user = None
            st.session_state.current_conversation = None
            st.rerun()


# ==================== WORKSPACE STATE HELPERS ====================

def save_workspace_state():
    if not st.session_state.user:
        return
    workspace_state = {
        "current_conversation_id": None,
    }
    if st.session_state.current_conversation:
        workspace_state["current_conversation_id"] = st.session_state.current_conversation["id"]
    save_user_workspace(st.session_state.user["id"], workspace_state)


def load_workspace_state():
    if not st.session_state.user or st.session_state.get("workspace_loaded", False):
        return
    workspace = load_user_workspace(st.session_state.user["id"])
    if workspace and workspace.get("current_conversation_id"):
        conv = get_conversation(workspace["current_conversation_id"], st.session_state.user["id"])
        if conv:
            st.session_state.current_conversation = conv
            st.session_state.conversation_messages = get_conversation_history(
                conv["id"], st.session_state.user["id"]
            )
    st.session_state.workspace_loaded = True


def create_or_get_active_conversation():
    if st.session_state.show_new_conversation and not st.session_state.current_conversation:
        conv_id = create_conversation(st.session_state.user["id"], "New Conversation")
        st.session_state.current_conversation = {
            "id": conv_id,
            "title": "New Conversation",
            "description": "",
            "message_count": 0,
        }
        st.session_state.conversation_messages = []
        st.session_state.show_new_conversation = False
        save_workspace_state()
        return st.session_state.current_conversation

    if not st.session_state.current_conversation:
        conversations = get_user_conversations(st.session_state.user["id"])
        if not conversations:
            conv_id = create_conversation(st.session_state.user["id"], "New Conversation")
            st.session_state.current_conversation = {
                "id": conv_id,
                "title": "New Conversation",
                "description": "",
                "message_count": 0,
            }
            st.session_state.conversation_messages = []
            save_workspace_state()
            return st.session_state.current_conversation
        else:
            return None
    return st.session_state.current_conversation


def submit_question(question):
    if not question:
        return "Please enter a question"
    if not st.session_state.current_tables:
        return "Please select at least one table"

    add_message(
        st.session_state.current_conversation["id"],
        st.session_state.user["id"],
        "user",
        question,
    )

    start_time = time.time()
    sql, error = generate_sql(question, st.session_state.current_tables)
    if error:
        add_message(
            st.session_state.current_conversation["id"],
            st.session_state.user["id"],
            "assistant",
            f"❌ Error: {error}",
        )
        return error

    result = run_query(sql)
    exec_time_ms = (time.time() - start_time) * 1000

    if isinstance(result, str):
        add_message(
            st.session_state.current_conversation["id"],
            st.session_state.user["id"],
            "assistant",
            f"❌ Execution Error: {result}",
        )
        log_query(
            st.session_state.user["id"],
            st.session_state.current_conversation["id"],
            st.session_state.current_tables,
            question,
            sql,
            0,
            exec_time_ms,
            success=False,
            error_msg=result,
        )
        st.session_state.conversation_messages = get_conversation_history(
            st.session_state.current_conversation["id"], st.session_state.user["id"]
        )
        return result

    result_df = pd.DataFrame(result)
    result_json = result_df.to_json()
    summary, _ = generate_result_summary(result_df, question, st.session_state.current_tables)

    response = f"""
**SQL Generated:**
```sql
{sql}
```

**Results:** {len(result_df)} rows returned

**Summary:** {summary}
"""

    add_message(
        st.session_state.current_conversation["id"],
        st.session_state.user["id"],
        "assistant",
        response,
        query_sql=sql,
        result_json=result_json,
        row_count=len(result_df),
    )

    log_query(
        st.session_state.user["id"],
        st.session_state.current_conversation["id"],
        st.session_state.current_tables,
        question,
        sql,
        len(result_df),
        exec_time_ms,
        success=True,
    )

    st.session_state.conversation_messages = get_conversation_history(
        st.session_state.current_conversation["id"], st.session_state.user["id"]
    )
    return None


def render_upload_section(user_tables):
    st.markdown("## 📤 Upload & Dataset Summary")
    st.markdown(
        "Upload CSV or Excel files first, then ask questions in the same AI chat workspace. "
        "Your dataset summary, row counts, and column counts appear here instantly."
    )

    uploaded_files = st.file_uploader(
        "Upload CSV or Excel files",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
        key="upload_files",
    )

    if uploaded_files:
        if st.button("📥 Upload Files", use_container_width=True, key="upload_submit"):
            upload_summary = []
            for file in uploaded_files:
                try:
                    if file.name.endswith(".csv"):
                        df = pd.read_csv(file)
                    else:
                        df = pd.read_excel(file)

                    table_name = insert_data(df, st.session_state.user["id"], file.name)
                    upload_summary.append(
                        {
                            "filename": file.name,
                            "table": table_name,
                            "rows": len(df),
                            "columns": len(df.columns),
                        }
                    )
                except Exception as e:
                    st.error(f"❌ Error uploading {file.name}: {str(e)}")

            if upload_summary:
                st.session_state.upload_summary = upload_summary
                st.success("✅ Upload completed successfully!")
                save_workspace_state()
                st.experimental_rerun()

    if st.session_state.get("upload_summary"):
        st.markdown("### Upload Status")
        st.table(pd.DataFrame(st.session_state.upload_summary))

    if user_tables:
        st.markdown("### Uploaded Datasets")
        summary_table = pd.DataFrame(user_tables)
        summary_table = summary_table.rename(
            columns={
                "source_filename": "Source File",
                "table_name": "Table Name",
                "row_count": "Rows",
                "column_count": "Columns",
                "created_at": "Uploaded At",
            }
        )
        st.dataframe(summary_table["Source File Table Name Rows Columns Uploaded At".split()], use_container_width=True)

        totals = {
            "tables": len(user_tables),
            "total_rows": sum(t["row_count"] for t in user_tables),
            "total_columns": sum(t["column_count"] for t in user_tables),
        }
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Tables", totals["tables"])
        col_b.metric("Total Rows", totals["total_rows"])
        col_c.metric("Total Columns", totals["total_columns"])

        st.markdown(
            f"**Dataset Overview:** {totals['tables']} tables, "
            f"{totals['total_rows']} rows total, {totals['total_columns']} columns total."
        )
    else:
        st.info("Upload your first file to start the AI workspace.")


def show_workspace():
    load_workspace_state()
    create_or_get_active_conversation()

    user_tables = get_user_tables(st.session_state.user["id"])
    if user_tables and not st.session_state.current_tables:
        st.session_state.current_tables = [user_tables[0]["table_name"]]

    render_upload_section(user_tables)

    st.markdown("---")
    st.markdown("## 💬 AI Chat Workspace")

    if not st.session_state.current_conversation:
        st.warning("Select a conversation from the sidebar or start a new chat.")
        return

    st.markdown(f"### {st.session_state.current_conversation['title']}")
    st.caption(
        f"{len(st.session_state.conversation_messages)} messages · "
        f"{len(st.session_state.current_tables)} selected table(s)"
    )

    if st.session_state.conversation_messages:
        for msg in st.session_state.conversation_messages:
            if msg["role"] == "user":
                with st.chat_message("user"):
                    st.write(msg["content"])
            else:
                with st.chat_message("assistant"):
                    st.write(msg["content"])
                    if msg.get("query_sql"):
                        with st.expander("🔍 View SQL"):
                            st.code(msg["query_sql"], language="sql")
                    if msg.get("result_json"):
                        with st.expander("📊 View Results"):
                            results = json.loads(msg["result_json"])
                            st.dataframe(results, use_container_width=True)
    else:
        st.info("Start the chat by asking a question or using one of the dataset suggestions below.")

    st.markdown("---")
    st.markdown("### 🤖 Suggested Questions")
    if user_tables:
        table_names = [table["table_name"] for table in user_tables]
        suggestions, _ = generate_example_questions(table_names)
        buttons = st.columns(len(suggestions) if suggestions else 1)
        for idx, suggestion in enumerate(suggestions):
            if buttons[idx].button(suggestion, key=f"suggestion_{idx}"):
                error = submit_question(suggestion)
                if error:
                    st.error(error)
                else:
                    st.experimental_rerun()
    else:
        st.info("Upload a dataset to see AI-generated suggestions.")

    st.markdown("---")
    st.markdown("### ✍️ Ask a Question")
    question = st.text_area("Enter your question here", height=120, key="chat_input")
    st.markdown("*Ask anything about the uploaded dataset. Your answer appears in the same chat flow.*")
    if st.button("🚀 Send", use_container_width=True, type="primary", key="send_chat"):
        error = submit_question(question)
        if error:
            st.error(error)
        else:
            st.experimental_rerun()


# ==================== MAIN APP ====================

def main():
    """Main application flow"""
    if not st.session_state.user:
        show_auth_page()
    else:
        show_sidebar()
        show_workspace()


if __name__ == "__main__":
    main()
