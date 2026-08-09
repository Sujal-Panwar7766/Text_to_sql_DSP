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
from db_saas import (
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


# ==================== MAIN CHAT INTERFACE ====================

def show_chat_interface():
    """Show the main chat and query interface"""
    
    # Initialize conversation if new
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
        st.rerun()
    
    if not st.session_state.current_conversation:
        st.info("👈 Select a conversation or start a new chat from the sidebar")
        return
    
    # Header
    st.markdown(f"## {st.session_state.current_conversation['title']}")
    
    # Conversation history display
    if st.session_state.conversation_messages:
        with st.container(border=True):
            for msg in st.session_state.conversation_messages:
                if msg['role'] == 'user':
                    with st.chat_message("user"):
                        st.write(msg['content'])
                else:
                    with st.chat_message("assistant"):
                        st.write(msg['content'])
                        if msg['query_sql']:
                            with st.expander("🔍 View SQL"):
                                st.code(msg['query_sql'], language="sql")
                        if msg['result_json']:
                            with st.expander("📊 View Results"):
                                results = json.loads(msg['result_json'])
                                st.dataframe(results, use_container_width=True)
    
    st.divider()
    
    # Input area
    col1, col2 = st.columns([1, 4])
    
    with col1:
        st.markdown("### 📋 Select Tables")
        user_tables = get_user_tables(st.session_state.user["id"])
        if user_tables:
            table_list = [t['table_name'] for t in user_tables]
            selected = st.multiselect(
                "Pick tables",
                table_list,
                default=st.session_state.current_tables,
                key="table_select"
            )
            st.session_state.current_tables = selected
        else:
            st.info("📂 Upload data first")
    
    with col2:
        st.markdown("### 💬 Ask a Question")
        question = st.text_area("What would you like to know about your data?", height=100)
        
        if st.button("🚀 Generate SQL & Execute", use_container_width=True, type="primary"):
            if not question:
                st.error("Please enter a question")
            elif not st.session_state.current_tables:
                st.error("Please select at least one table")
            else:
                # Add user message
                add_message(
                    st.session_state.current_conversation['id'],
                    st.session_state.user["id"],
                    "user",
                    question
                )
                
                # Generate SQL
                start_time = time.time()
                sql, error = generate_sql(question, st.session_state.current_tables)
                
                if error:
                    add_message(
                        st.session_state.current_conversation['id'],
                        st.session_state.user["id"],
                        "assistant",
                        f"❌ Error: {error}"
                    )
                    st.error(error)
                else:
                    # Execute query
                    result = run_query(sql)
                    exec_time_ms = (time.time() - start_time) * 1000
                    
                    if isinstance(result, str):  # Error
                        add_message(
                            st.session_state.current_conversation['id'],
                            st.session_state.user["id"],
                            "assistant",
                            f"❌ Execution Error: {result}"
                        )
                        log_query(
                            st.session_state.user["id"],
                            st.session_state.current_conversation['id'],
                            st.session_state.current_tables,
                            question,
                            sql,
                            0,
                            exec_time_ms,
                            success=False,
                            error_msg=result
                        )
                        st.error(f"Query Error: {result}")
                    else:
                        # Success
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
                            st.session_state.current_conversation['id'],
                            st.session_state.user["id"],
                            "assistant",
                            response,
                            query_sql=sql,
                            result_json=result_json,
                            row_count=len(result_df)
                        )
                        
                        log_query(
                            st.session_state.user["id"],
                            st.session_state.current_conversation['id'],
                            st.session_state.current_tables,
                            question,
                            sql,
                            len(result_df),
                            exec_time_ms,
                            success=True
                        )
                        
                        st.success("✅ Query executed successfully!")
                        st.dataframe(result_df, use_container_width=True)
                
                st.rerun()


# ==================== UPLOAD DATA PAGE ====================

def show_upload_page():
    """Show data upload interface"""
    st.markdown("## 📤 Upload Data")
    
    uploaded_files = st.file_uploader(
        "Upload CSV or Excel files",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
    )
    
    if uploaded_files:
        for file in uploaded_files:
            try:
                if file.name.endswith(".csv"):
                    df = pd.read_csv(file)
                else:
                    df = pd.read_excel(file)
                
                table_name = insert_data(df, st.session_state.user["id"], file.name)
                st.success(f"✅ {file.name} uploaded! Table: `{table_name}`")
                st.dataframe(df.head(10), use_container_width=True)
                
            except Exception as e:
                st.error(f"❌ Error uploading {file.name}: {str(e)}")


# ==================== QUERY HISTORY PAGE ====================

def show_history_page():
    """Show query history"""
    st.markdown("## 📜 Query History")
    
    history = get_query_history(st.session_state.user["id"], limit=50)
    
    if history:
        for i, record in enumerate(history):
            with st.expander(f"Query {i+1}: {record['question'][:50]}...", expanded=False):
                st.code(record['query_sql'], language="sql")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Rows", record['result_row_count'])
                with col2:
                    st.metric("Time (ms)", f"{record['execution_time_ms']:.1f}")
                with col3:
                    status = "✅ Success" if record['success'] else "❌ Failed"
                    st.metric("Status", status)
                st.caption(record['created_at'])
    else:
        st.info("📭 No query history yet")


# ==================== MAIN APP ====================

def main():
    """Main application flow"""
    
    if not st.session_state.user:
        show_auth_page()
    else:
        show_sidebar()
        
        # Navigation tabs
        nav_col1, nav_col2, nav_col3, nav_col4 = st.columns(4)
        
        with nav_col1:
            if st.button("💬 Chat", use_container_width=True):
                st.session_state.page = "chat"
        with nav_col2:
            if st.button("📤 Upload", use_container_width=True):
                st.session_state.page = "upload"
        with nav_col3:
            if st.button("📜 History", use_container_width=True):
                st.session_state.page = "history"
        with nav_col4:
            if st.button("⚙️ Settings", use_container_width=True):
                st.session_state.page = "settings"
        
        st.divider()
        
        # Page routing
        page = st.session_state.get("page", "chat")
        
        if page == "chat":
            show_chat_interface()
        elif page == "upload":
            show_upload_page()
        elif page == "history":
            show_history_page()
        elif page == "settings":
            st.markdown("## ⚙️ Settings")
            st.info("Settings coming soon!")


if __name__ == "__main__":
    main()
