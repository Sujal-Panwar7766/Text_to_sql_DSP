import sqlite3

conn = sqlite3.connect("students.db")
cursor = conn.cursor()

# Students table
cursor.execute("""
CREATE TABLE students (
    student_id INTEGER PRIMARY KEY,
    name TEXT,
    department TEXT,
    year INTEGER
)
""")

# Subjects table
cursor.execute("""
CREATE TABLE subjects (
    subject_id INTEGER PRIMARY KEY,
    subject_name TEXT
)
""")

# Semesters table
cursor.execute("""
CREATE TABLE semesters (
    semester_id INTEGER PRIMARY KEY,
    semester_name TEXT
)
""")

# Academic records table
cursor.execute("""
CREATE TABLE academic_records (
    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    semester_id INTEGER,
    subject_id INTEGER,
    marks REAL,
    attendance REAL,
    assignment_score REAL,
    midterm_score REAL,
    final_score REAL
)
""")

conn.commit()
conn.close()

print("Database created successfully")