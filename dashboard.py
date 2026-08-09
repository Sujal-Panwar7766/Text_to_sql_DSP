import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px

# Connect DB
conn = sqlite3.connect("students.db")

# Fetch student names (ADD HERE)
def get_student_names():
    query = "SELECT DISTINCT name FROM students"
    df_names = pd.read_sql_query(query, conn)
    return df_names["name"].tolist()

st.set_page_config(page_title="AI Student Analytics", layout="wide")

st.title("🎓 AI Student Analytics Dashboard")

# ---------- THEME + ANIMATION (ADDED) ----------
st.markdown("""
<style>

/* ===== BACKGROUND ===== */
.stApp {
    background: radial-gradient(circle at top, #1a1a1a, #000000);
    color: white;
    animation: fadeIn 1.5s ease-in;
}

/* ===== SIDEBAR ===== */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #111111, #000000);
    border-right: 2px solid #FFD700;
    animation: slideIn 0.8s ease-in-out;
}

/* ===== TITLE ===== */
h1 {
    color: #FFD700;
    text-shadow: 0px 0px 20px rgba(255,215,0,0.6);
    animation: glow 2s infinite alternate;
}

/* ===== HEADINGS ===== */
h2, h3 {
    color: #FFD700;
}

/* ===== INPUT BOX ===== */
.stTextInput input {
    background-color: #1a1a1a;
    color: white;
    border: 1px solid #FFD700;
    border-radius: 10px;
}

/* ===== SELECT BOX ===== */
.stSelectbox div {
    background-color: #1a1a1a;
    color: white;
}

/* ===== METRICS ===== */
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #1a1a1a, #000000);
    border-left: 5px solid #FFD700;
    border-radius: 10px;
    padding: 10px;
    animation: popIn 0.6s ease;
}

/* ===== DATA TABLE ===== */
[data-testid="stDataFrame"] {
    background-color: #111111;
    border-radius: 10px;
}

/* ===== BUTTON ===== */
.stButton>button {
    background-color: #FFD700;
    color: black;
    font-weight: bold;
    border-radius: 8px;
    transition: 0.3s;
}
.stButton>button:hover {
    transform: scale(1.1);
    box-shadow: 0px 0px 10px #FFD700;
}

/* ===== ANIMATIONS ===== */
@keyframes fadeIn {
    from {opacity: 0;}
    to {opacity: 1;}
}

@keyframes slideIn {
    from {transform: translateX(-100%);}
    to {transform: translateX(0);}
}

@keyframes popIn {
    from {transform: scale(0.9); opacity: 0;}
    to {transform: scale(1); opacity: 1;}
}

@keyframes glow {
    from {text-shadow: 0px 0px 10px #FFD700;}
    to {text-shadow: 0px 0px 25px #FFD700;}
}

</style>
""", unsafe_allow_html=True)

# ---------- FILTERS ----------
st.sidebar.header("🔍 Filters")

semester = st.sidebar.selectbox(
    "Select Semester",
    ["All", "Semester 1", "Semester 2", "Semester 3", "Semester 4", "Semester 5", "Semester 6"]
)

subject = st.sidebar.selectbox(
    "Select Subject",
    ["All", "Mathematics", "Physics", "Data Structures", "Operating Systems", "Database Systems"]
)

st.sidebar.header("🔍 Student Search")

student_list = get_student_names()

student_name = st.sidebar.selectbox(
    "Select Student",
    ["None"] + student_list
)

# ---------- INPUT ----------
question = st.text_input("Ask a question (e.g. attendance below 75, top students, average marks)")

# ---------- GPA FUNCTION (ADDED) ----------
def calculate_gpa(mark):
    if mark >= 90:
        return 10, "A+"
    elif mark >= 80:
        return 9, "A"
    elif mark >= 70:
        return 8, "B"
    elif mark >= 60:
        return 7, "C"
    elif mark >= 50:
        return 6, "D"
    else:
        return 0, "F"

# ---------- STUDENT REPORT (ADDED) ----------
def get_student_report(name):
    query = f"""
    SELECT s.name, sub.subject_name, a.semester_id, 
           a.marks, a.attendance
    FROM students s
    JOIN academic_records a ON s.student_id = a.student_id
    JOIN subjects sub ON a.subject_id = sub.subject_id
    WHERE s.name LIKE '%{name}%'
    """
    return pd.read_sql_query(query, conn)

# ---------- SQL CLEANER ----------
def clean_sql(sql):
    sql = sql.replace("remove LIMIT", "")
    sql = sql.replace(";", "")
    return sql.strip()

# ---------- APPLY FILTERS ----------
def apply_filters(base_sql):

    conditions = []

    if semester != "All":
        sem_num = semester.split()[-1]
        conditions.append(f"a.semester_id = {sem_num}")

    if subject != "All":
        conditions.append(f"sub.subject_name = '{subject}'")

    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)

        if "GROUP BY" in base_sql:
            parts = base_sql.split("GROUP BY")
            base_sql = parts[0] + where_clause + " GROUP BY " + parts[1]
        else:
            base_sql += where_clause

    return base_sql

# ---------- SQL GENERATOR ----------
def generate_sql(question):

    q = question.lower()

    if "attendance" in q:
        return """
        SELECT s.name, AVG(a.attendance) as avg_attendance
        FROM students s
        JOIN academic_records a ON s.student_id = a.student_id
        JOIN subjects sub ON a.subject_id = sub.subject_id
        GROUP BY s.student_id
        ORDER BY avg_attendance ASC
        LIMIT 50
        """

    elif "top students" in q:
        return """
        SELECT s.name, AVG(a.marks) as avg_marks
        FROM students s
        JOIN academic_records a ON s.student_id = a.student_id
        JOIN subjects sub ON a.subject_id = sub.subject_id
        GROUP BY s.student_id
        ORDER BY avg_marks DESC
        LIMIT 100
        """

    elif "average marks" in q:
        return """
        SELECT AVG(a.marks) as avg_marks
        FROM academic_records a
        JOIN subjects sub ON a.subject_id = sub.subject_id
        """

    return None

def generate_insight(df, question):

    if df.empty:
        return "No data available."

    if "attendance" in question.lower():
        avg = df["avg_attendance"].mean()
        lowest = df.iloc[0]
        return f"""
📉 Average attendance is **{avg:.2f}%**  
⚠️ Lowest: **{lowest['name']} ({lowest['avg_attendance']:.2f}%)**
"""

    elif "top students" in question.lower():
        top = df.iloc[0]
        avg = df["avg_marks"].mean()
        return f"""
🏆 Top performer: **{top['name']}**  
📊 Avg marks of top students: **{avg:.2f}**
"""

    elif "average marks" in question.lower():
        avg = df["avg_marks"][0]
        return f"📊 Overall average marks = **{avg:.2f}**"

    return "Data analyzed successfully."

# ---------- STUDENT SEARCH DISPLAY (ADDED MAIN FEATURE) ----------
if student_name != "None":

    df_student = get_student_report(student_name)

    if df_student.empty:
        st.warning("No student found")
    else:
        st.subheader(f"📄 Report for {student_name}")

        # ADD GPA + GRADE
        df_student["GPA"] = df_student["marks"].apply(lambda x: calculate_gpa(x)[0])
        df_student["Grade"] = df_student["marks"].apply(lambda x: calculate_gpa(x)[1])

        overall_gpa = df_student["GPA"].mean()

        col1, col2 = st.columns(2)

        with col1:
            st.dataframe(df_student, use_container_width=True)

        with col2:
            with col2:
                fig1 = px.bar(df_student, x="subject_name", y="marks",
                            color="semester_id", title="Marks")

                fig1.update_layout(
                    plot_bgcolor="#0e0e0e",
                    paper_bgcolor="#0e0e0e",
                    font_color="white",
                    title_font=dict(color="#FFD700"),
                    transition_duration=500
                )

                fig1.update_traces(marker_color="#FFD700")  # ⭐ add this

                st.plotly_chart(fig1, use_container_width=True)


                # -------- FIXED fig2 --------
                fig2 = px.bar(df_student, x="subject_name", y="attendance",
                            color="semester_id", title="Attendance")

                fig2.update_layout(
                    plot_bgcolor="#0e0e0e",
                    paper_bgcolor="#0e0e0e",
                    font_color="white",
                    title_font=dict(color="#FFD700"),
                    transition_duration=500
                )

                fig2.update_traces(marker_color="#FFD700")  # ⭐ add this

                st.plotly_chart(fig2, use_container_width=True)

        st.subheader("🎓 Performance")

        c1, c2 = st.columns(2)
        c1.metric("📊 Avg Marks", f"{df_student['marks'].mean():.2f}")
        c2.metric("🎓 GPA", f"{overall_gpa:.2f}")

        st.subheader("🤖 AI Student Insight")

        st.success(f"""
📊 Average Marks: **{df_student['marks'].mean():.2f}**  
🎓 GPA: **{overall_gpa:.2f}**  
📉 Attendance: **{df_student['attendance'].mean():.2f}%**

🧠 Analysis:
- {"Excellent performance 🏆" if overall_gpa >= 8 else "Needs improvement ⚠️"}
- {"Good attendance 👍" if df_student['attendance'].mean() > 75 else "Low attendance 🚨"}
""")

# ---------- NORMAL QUERY SYSTEM ----------
if question:

    sql = generate_sql(question)    

    if not sql:
        st.error("❌ Question not supported yet")
    else:
        sql = clean_sql(sql)
        sql = apply_filters(sql)

        st.write("SQL Query:", sql)

        df = pd.read_sql_query(sql, conn)

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("📊 Data Table")
            st.dataframe(df, use_container_width=True)

        with col2:
            st.subheader("📈 Visualization")

            if "avg_attendance" in df.columns:
                df_chart = df.head(10)
                fig = px.bar(df_chart, x="name", y="avg_attendance",
                             title="Lowest Attendance Students")
                st.plotly_chart(fig, use_container_width=True)

            elif "name" in df.columns and "avg_marks" in df.columns:
                df_chart = df.head(10)
                fig = px.bar(df_chart, x="name", y="avg_marks",
                             title="Top Students")
                st.plotly_chart(fig, use_container_width=True)

            elif "avg_marks" in df.columns:
                st.metric("📊 Average Marks", f"{df['avg_marks'][0]:.2f}")

        st.subheader("🤖 AI Insight")
        st.success(generate_insight(df, question))

        #streamlit run dashboard.py