import sqlite3
import random

conn = sqlite3.connect("students.db")
cursor = conn.cursor()

# Insert subjects
subjects = [
    (1, "Mathematics"),
    (2, "Physics"),
    (3, "Data Structures"),
    (4, "Operating Systems"),
    (5, "Database Systems")
]

cursor.executemany("INSERT OR IGNORE INTO subjects VALUES (?,?)", subjects)

# Insert semesters
semesters = [
    (1,"Semester 1"),
    (2,"Semester 2"),
    (3,"Semester 3"),
    (4,"Semester 4"),
    (5,"Semester 5"),
    (6,"Semester 6")
]

cursor.executemany("INSERT OR IGNORE INTO semesters VALUES (?,?)", semesters)

# Generate students
student_names = [
    "Rahul","Aman","Anjali","Priya","Rohit","Karan","Sneha","Neha",
    "Arjun","Riya","Aditya","Kavya","Sahil","Isha","Dev","Simran"
]

student_id = 1

for i in range(500):

    name = random.choice(student_names) + str(i)
    department = "CSE"
    year = random.randint(1,4)

    cursor.execute(
        "INSERT INTO students VALUES (?,?,?,?)",
        (student_id,name,department,year)
    )

    # academic records
    for semester in range(1,7):

        for subject in range(1,6):

            marks = random.randint(40,100)
            attendance = random.randint(60,100)
            assignment = random.randint(10,30)
            midterm = random.randint(10,30)
            final = random.randint(20,40)

            cursor.execute(
                """INSERT INTO academic_records
                (student_id,semester_id,subject_id,marks,attendance,assignment_score,midterm_score,final_score)
                VALUES (?,?,?,?,?,?,?,?)""",
                (student_id,semester,subject,marks,attendance,assignment,midterm,final)
            )

    student_id += 1


conn.commit()
conn.close()

print("Dataset generated successfully")