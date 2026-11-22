"""
Campus Analytics - College Management & Analytics Portal (single file)

Run:    streamlit run app_upgraded_1.py
Needs:  pip install streamlit pandas plotly scikit-learn openpyxl
"""

import hashlib
import hmac
import html
import io
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Campus Analytics", page_icon="🎓", layout="wide")

# =============================================================================
# 1. SETTINGS  (change a rule here once and every page follows it)
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FOLDER = os.path.join(BASE_DIR, "database")
DB_PATH = os.path.join(DB_FOLDER, "students.db")

DEPARTMENTS = ["AI&DS", "CSE", "ECE", "IT", "EEE", "MECH", "CIVIL"]
YEARS = [1, 2, 3, 4]

PASS_MARK = 50
MIN_ATTENDANCE = 75
EXCELLENT_ATTENDANCE = 90
GRADE_BANDS = [(90, "A+"), (80, "A"), (70, "B"), (60, "C"), (50, "D")]
GRADE_ORDER = ["A+", "A", "B", "C", "D", "Fail"]
PERFORMANCE_BANDS = [(80, "Excellent"), (60, "Good"), (0, "Needs Attention")]

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 300
MIN_PASSWORD_LENGTH = 8
DEFAULT_ADMIN_USER = "admin"
LEGACY_DEFAULT_PASSWORD = "Campus@123"
# First-run password. Set the CAMPUS_ADMIN_PASSWORD environment variable to override.
DEFAULT_ADMIN_PASSWORD = os.environ.get("CAMPUS_ADMIN_PASSWORD", LEGACY_DEFAULT_PASSWORD)

DESIGNATIONS = ["Professor", "Associate Professor", "Assistant Professor", "Lab Instructor"]
FACULTY_STATUS = ["Active", "On Leave"]
FEE_TYPES = ["Tuition", "Hostel", "Transport", "Exam", "Lab", "Library"]
PAYMENT_MODES = ["UPI", "Cash", "Card", "Net Banking", "Cheque"]
LABS = ["Computer Lab", "AI & Data Lab", "Electronics Lab", "Networking Lab", "Electrical Lab",
        "Mechanical Workshop", "Civil & Survey Lab", "Physics Lab", "Chemistry Lab"]
EQUIPMENT_CATEGORIES = ["Computer", "Electronics", "Networking", "Electrical", "Mechanical",
                        "Physics/Chemistry", "Furniture", "Other"]
CONDITIONS = ["Good", "Needs Repair", "Out of Service"]
LOW_STOCK_RATIO = 0.2          # an item is "Low stock" when 20% or less is available
STUDENTS_PER_FACULTY_REFERENCE = 20

LOAN_DAYS = 14                 # students: days a book can be kept
FACULTY_LOAN_DAYS = 30
MAX_RENEWALS = 2
FINE_PER_DAY = 2               # rupees per day late
MAX_STUDENT_BOOKS = 3
DUE_SOON_DAYS = 3
BOOK_CATEGORIES = ["Computer Science", "Electronics", "Electrical", "Mechanical", "Civil", "Mathematics",
                   "Physics/Chemistry", "Management", "General"]
ROOM_TYPES = ["Non-AC", "AC"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
PERIODS = {1: "9:00-9:50", 2: "9:50-10:40", 3: "10:50-11:40", 4: "11:40-12:30",
           5: "1:30-2:20", 6: "2:20-3:10", 7: "3:10-4:00"}

PALETTE = ["#2563EB", "#0EA5E9", "#14B8A6", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899"]
DEPT_COLORS = dict(zip(DEPARTMENTS, PALETTE))
BAND_COLORS = {"Excellent": "#14B8A6", "Good": "#2563EB", "Needs Attention": "#F59E0B"}
STATUS_COLORS = {"Excellent": "#14B8A6", "Eligible": "#2563EB", "Low Attendance": "#EF4444"}

# =============================================================================
# 2. DATABASE
# =============================================================================

STUDENT_COLUMNS = ["student_id", "name", "department", "year", "email", "phone", "marks", "attendance"]
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@contextmanager
def get_connection():
    """Commit on success, roll back on error, and ALWAYS close the connection."""
    os.makedirs(DB_FOLDER, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS students (
                student_id TEXT PRIMARY KEY, name TEXT NOT NULL, department TEXT NOT NULL,
                year INTEGER NOT NULL, email TEXT, phone TEXT,
                marks REAL DEFAULT 0, attendance REAL DEFAULT 0)
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                username TEXT PRIMARY KEY, salt TEXT NOT NULL, password_hash TEXT NOT NULL)
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS faculty (
                faculty_id TEXT PRIMARY KEY, name TEXT NOT NULL, department TEXT NOT NULL,
                designation TEXT NOT NULL, qualification TEXT, email TEXT, phone TEXT,
                experience REAL DEFAULT 0, subjects TEXT, status TEXT DEFAULT 'Active')
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS fees (
                fee_id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL, fee_type TEXT NOT NULL,
                amount REAL NOT NULL, due_date TEXT NOT NULL, UNIQUE (student_id, fee_type, due_date))
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS fee_payments (
                payment_id INTEGER PRIMARY KEY AUTOINCREMENT, fee_id INTEGER NOT NULL,
                amount REAL NOT NULL, paid_on TEXT NOT NULL, mode TEXT)
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS lab_equipment (
                item_id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, lab TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1, unit_cost REAL DEFAULT 0,
                condition TEXT DEFAULT 'Good', purchase_date TEXT)
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS lab_issues (
                issue_id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL, issued_to TEXT NOT NULL,
                quantity INTEGER NOT NULL, issued_on TEXT NOT NULL, returned_on TEXT)
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS library_books (
                book_id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT, category TEXT,
                copies INTEGER NOT NULL DEFAULT 1)
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS library_loans (
                loan_id INTEGER PRIMARY KEY AUTOINCREMENT, book_id TEXT NOT NULL, borrower_id TEXT NOT NULL,
                borrower_type TEXT NOT NULL, borrower_name TEXT NOT NULL, issued_on TEXT NOT NULL,
                due_on TEXT NOT NULL, returned_on TEXT, renewals INTEGER DEFAULT 0, fine REAL DEFAULT 0)
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS hostel_rooms (
                room_no TEXT PRIMARY KEY, block TEXT NOT NULL, floor INTEGER DEFAULT 0,
                capacity INTEGER NOT NULL, room_type TEXT DEFAULT 'Non-AC', rent REAL DEFAULT 0)
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS hostel_allocations (
                alloc_id INTEGER PRIMARY KEY AUTOINCREMENT, room_no TEXT NOT NULL, student_id TEXT NOT NULL,
                allotted_on TEXT NOT NULL, vacated_on TEXT)
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS timetable (
                slot_id INTEGER PRIMARY KEY AUTOINCREMENT, department TEXT NOT NULL, year INTEGER NOT NULL,
                day TEXT NOT NULL, period INTEGER NOT NULL, subject TEXT NOT NULL, faculty TEXT DEFAULT '',
                room TEXT DEFAULT '', UNIQUE (department, year, day, period))
        """)
        # Upgrade older databases in place (your existing data is kept).
        existing = {row["name"] for row in connection.execute("PRAGMA table_info(admins)")}
        for column, definition in [("failed_attempts", "INTEGER DEFAULT 0"),
                                   ("locked_until", "REAL DEFAULT 0"),
                                   ("must_change", "INTEGER DEFAULT 0")]:
            if column not in existing:
                connection.execute(f"ALTER TABLE admins ADD COLUMN {column} {definition}")


def validate_student(student_id, name, email, phone):
    problems = []
    if not str(student_id).strip():
        problems.append("Student ID is required.")
    if not str(name).strip():
        problems.append("Student Name is required.")
    email = str(email or "").strip()
    if email and not EMAIL_PATTERN.match(email):
        problems.append("Email address is not valid.")
    phone = str(phone or "").strip()
    if phone and not re.fullmatch(r"\+?\d{10,13}", phone.replace(" ", "")):
        problems.append("Phone number must contain 10 to 13 digits.")
    return problems


def load_students(columns=None):
    cols = ", ".join(columns or STUDENT_COLUMNS)
    with get_connection() as connection:
        return pd.read_sql_query(
            f"SELECT {cols} FROM students ORDER BY department, student_id", connection)


def add_student(student_id, name, department, year, email, phone, marks, attendance):
    problems = validate_student(student_id, name, email, phone)
    if problems:
        return False, " ".join(problems)
    try:
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO students (student_id, name, department, year, email, phone, marks, attendance)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(student_id).strip(), str(name).strip(), department, int(year),
                 str(email or "").strip(), str(phone or "").strip(), float(marks), float(attendance)))
        return True, "Student saved successfully."
    except sqlite3.IntegrityError:
        return False, "This Student ID already exists."


def update_student(student_id, name, department, year, email, phone, marks, attendance):
    problems = validate_student(student_id, name, email, phone)
    if problems:
        return False, " ".join(problems)
    with get_connection() as connection:
        connection.execute(
            """UPDATE students SET name=?, department=?, year=?, email=?, phone=?, marks=?, attendance=?
               WHERE student_id=?""",
            (str(name).strip(), department, int(year), str(email or "").strip(),
             str(phone or "").strip(), float(marks), float(attendance), student_id))
    return True, "Student updated successfully."


def delete_student(student_id):
    with get_connection() as connection:
        connection.execute("DELETE FROM fee_payments WHERE fee_id IN (SELECT fee_id FROM fees WHERE student_id = ?)", (student_id,))
        connection.execute("DELETE FROM fees WHERE student_id = ?", (student_id,))
        connection.execute("DELETE FROM library_loans WHERE borrower_id = ? AND borrower_type = 'Student'", (student_id,))
        connection.execute("DELETE FROM hostel_allocations WHERE student_id = ?", (student_id,))
        connection.execute("DELETE FROM students WHERE student_id = ?", (student_id,))


def import_students(frame):
    """Bulk import. Returns (number_added, list_of_skipped_messages)."""
    missing = {"student_id", "name", "department", "year", "marks", "attendance"} - set(frame.columns)
    if missing:
        return 0, [f"Missing columns: {', '.join(sorted(missing))}"]
    added, skipped = 0, []
    for position, row in frame.reset_index(drop=True).iterrows():
        label = f"Row {position + 2}"
        try:
            year, marks, attendance = int(row["year"]), float(row["marks"]), float(row["attendance"])
        except (TypeError, ValueError):
            skipped.append(f"{label}: year, marks or attendance is not a number.")
            continue
        if not (0 <= marks <= 100 and 0 <= attendance <= 100):
            skipped.append(f"{label}: marks and attendance must be between 0 and 100.")
            continue
        ok, message = add_student(row["student_id"], row["name"], str(row["department"]).strip(), year,
                                  row.get("email", ""), row.get("phone", ""), marks, attendance)
        if ok:
            added += 1
        else:
            skipped.append(f"{label}: {message}")
    return added, skipped


# ----- faculty -----
FACULTY_COLUMNS = ["faculty_id", "name", "department", "designation", "qualification",
                   "email", "phone", "experience", "subjects", "status"]


def load_faculty():
    with get_connection() as connection:
        return pd.read_sql_query(f"SELECT {', '.join(FACULTY_COLUMNS)} FROM faculty ORDER BY department, name", connection)


def _faculty_problems(faculty_id, name, email, phone, experience):
    problems = validate_student(faculty_id, name, email, phone)
    problems = [p.replace("Student", "Faculty") for p in problems]
    if not (0 <= float(experience) <= 50):
        problems.append("Experience must be between 0 and 50 years.")
    return problems


def add_faculty(faculty_id, name, department, designation, qualification, email, phone, experience, subjects, status):
    problems = _faculty_problems(faculty_id, name, email, phone, experience)
    if problems:
        return False, " ".join(problems)
    try:
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO faculty (faculty_id, name, department, designation, qualification, email, phone,
                   experience, subjects, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(faculty_id).strip(), str(name).strip(), department, designation, str(qualification or "").strip(),
                 str(email or "").strip(), str(phone or "").strip(), float(experience),
                 str(subjects or "").strip(), status))
        return True, "Faculty member saved successfully."
    except sqlite3.IntegrityError:
        return False, "This Faculty ID already exists."


def update_faculty(faculty_id, name, department, designation, qualification, email, phone, experience, subjects, status):
    problems = _faculty_problems(faculty_id, name, email, phone, experience)
    if problems:
        return False, " ".join(problems)
    with get_connection() as connection:
        connection.execute(
            """UPDATE faculty SET name=?, department=?, designation=?, qualification=?, email=?, phone=?,
               experience=?, subjects=?, status=? WHERE faculty_id=?""",
            (str(name).strip(), department, designation, str(qualification or "").strip(), str(email or "").strip(),
             str(phone or "").strip(), float(experience), str(subjects or "").strip(), status, faculty_id))
    return True, "Faculty member updated successfully."


def delete_faculty(faculty_id):
    with get_connection() as connection:
        connection.execute("DELETE FROM faculty WHERE faculty_id = ?", (faculty_id,))


# ----- fees -----
def money(value):
    """Rupees with Indian digit grouping, e.g. 1234567 -> ₹12,34,567."""
    number = int(round(float(value)))
    digits = str(abs(number))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        digits = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head) + "," + tail
    return ("-" if number < 0 else "") + "₹" + digits


def fee_status(amount, paid, due_date):
    if paid >= amount - 0.005:
        return "Paid"
    if str(due_date) < datetime.now().strftime("%Y-%m-%d"):
        return "Overdue"
    return "Partial" if paid > 0 else "Pending"


def load_fees():
    """One row per fee with paid amount, balance and status worked out."""
    with get_connection() as connection:
        frame = pd.read_sql_query(
            """SELECT f.fee_id, f.student_id, COALESCE(s.name, '(deleted)') AS student_name,
                      COALESCE(s.department, '-') AS department, COALESCE(s.year, 0) AS year,
                      f.fee_type, f.amount, f.due_date, COALESCE(SUM(p.amount), 0) AS paid
               FROM fees f LEFT JOIN students s ON s.student_id = f.student_id
               LEFT JOIN fee_payments p ON p.fee_id = f.fee_id
               GROUP BY f.fee_id ORDER BY f.due_date, f.fee_id""", connection)
    if frame.empty:
        frame["balance"], frame["status"] = [], []
        return frame
    frame["balance"] = (frame["amount"] - frame["paid"]).clip(lower=0)
    frame["status"] = [fee_status(a, p, d) for a, p, d in zip(frame["amount"], frame["paid"], frame["due_date"])]
    return frame


def load_payments():
    with get_connection() as connection:
        return pd.read_sql_query(
            """SELECT p.payment_id, p.fee_id, f.student_id, f.fee_type, p.amount, p.paid_on, p.mode
               FROM fee_payments p JOIN fees f ON f.fee_id = p.fee_id ORDER BY p.paid_on DESC, p.payment_id DESC""",
            connection)


def assign_fee(student_ids, fee_type, amount, due_date):
    """Create the same fee for many students. Returns (created, skipped_duplicates)."""
    if float(amount) <= 0:
        return 0, 0
    created = 0
    with get_connection() as connection:
        for student_id in student_ids:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO fees (student_id, fee_type, amount, due_date) VALUES (?, ?, ?, ?)",
                (str(student_id), fee_type, float(amount), str(due_date)))
            created += cursor.rowcount
    return created, len(list(student_ids)) - created


def record_payment(fee_id, amount, mode, paid_on):
    """Returns (ok, message). The amount cannot exceed the balance."""
    amount = float(amount)
    if amount <= 0:
        return False, "Payment amount must be greater than zero."
    with get_connection() as connection:
        row = connection.execute(
            """SELECT f.amount, COALESCE(SUM(p.amount), 0) AS paid FROM fees f
               LEFT JOIN fee_payments p ON p.fee_id = f.fee_id WHERE f.fee_id = ? GROUP BY f.fee_id""",
            (int(fee_id),)).fetchone()
        if row is None:
            return False, "Fee record not found."
        balance = row["amount"] - row["paid"]
        if amount > balance + 0.005:
            return False, f"Payment is more than the balance of {money(balance)}."
        connection.execute("INSERT INTO fee_payments (fee_id, amount, paid_on, mode) VALUES (?, ?, ?, ?)",
                           (int(fee_id), amount, str(paid_on), mode))
    return True, f"Payment of {money(amount)} recorded."


def delete_fee(fee_id):
    with get_connection() as connection:
        connection.execute("DELETE FROM fee_payments WHERE fee_id = ?", (int(fee_id),))
        connection.execute("DELETE FROM fees WHERE fee_id = ?", (int(fee_id),))


# ----- lab equipment -----
def load_equipment():
    """Inventory with units currently issued out and units still available."""
    with get_connection() as connection:
        frame = pd.read_sql_query(
            """SELECT e.item_id, e.name, e.category, e.lab, e.quantity, e.unit_cost, e.condition, e.purchase_date,
                      COALESCE(SUM(CASE WHEN i.returned_on IS NULL THEN i.quantity END), 0) AS issued
               FROM lab_equipment e LEFT JOIN lab_issues i ON i.item_id = e.item_id
               GROUP BY e.item_id ORDER BY e.lab, e.name""", connection)
    if frame.empty:
        frame["available"], frame["stock"], frame["value"] = [], [], []
        return frame
    frame["available"] = frame["quantity"] - frame["issued"]
    frame["value"] = frame["quantity"] * frame["unit_cost"]
    frame["stock"] = np.select(
        [frame["available"] <= 0, frame["available"] <= frame["quantity"] * LOW_STOCK_RATIO],
        ["Out of stock", "Low stock"], default="In stock")
    return frame


def load_open_issues():
    with get_connection() as connection:
        return pd.read_sql_query(
            """SELECT i.issue_id, i.item_id, e.name AS item_name, i.issued_to, i.quantity, i.issued_on
               FROM lab_issues i JOIN lab_equipment e ON e.item_id = i.item_id
               WHERE i.returned_on IS NULL ORDER BY i.issued_on DESC, i.issue_id DESC""", connection)


def add_equipment(item_id, name, category, lab, quantity, unit_cost, condition, purchase_date):
    if not str(item_id).strip() or not str(name).strip():
        return False, "Item ID and Item Name are required."
    if int(quantity) < 1:
        return False, "Quantity must be at least 1."
    try:
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO lab_equipment (item_id, name, category, lab, quantity, unit_cost, condition, purchase_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(item_id).strip(), str(name).strip(), category, lab, int(quantity), float(unit_cost),
                 condition, str(purchase_date)))
        return True, "Equipment item saved successfully."
    except sqlite3.IntegrityError:
        return False, "This Item ID already exists."


def update_equipment(item_id, name, category, lab, quantity, unit_cost, condition, purchase_date):
    if not str(name).strip():
        return False, "Item Name is required."
    with get_connection() as connection:
        issued = connection.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM lab_issues WHERE item_id = ? AND returned_on IS NULL",
            (item_id,)).fetchone()[0]
        if int(quantity) < issued:
            return False, f"{issued} unit(s) are currently issued, so quantity cannot be below {issued}."
        connection.execute(
            """UPDATE lab_equipment SET name=?, category=?, lab=?, quantity=?, unit_cost=?, condition=?,
               purchase_date=? WHERE item_id=?""",
            (str(name).strip(), category, lab, int(quantity), float(unit_cost), condition, str(purchase_date), item_id))
    return True, "Equipment item updated successfully."


def delete_equipment(item_id):
    with get_connection() as connection:
        connection.execute("DELETE FROM lab_issues WHERE item_id = ?", (item_id,))
        connection.execute("DELETE FROM lab_equipment WHERE item_id = ?", (item_id,))


def issue_equipment(item_id, issued_to, quantity, issued_on):
    if not str(issued_to).strip():
        return False, "Please enter who the item is issued to."
    with get_connection() as connection:
        row = connection.execute(
            """SELECT e.quantity, e.condition, COALESCE(SUM(CASE WHEN i.returned_on IS NULL THEN i.quantity END), 0) AS issued
               FROM lab_equipment e LEFT JOIN lab_issues i ON i.item_id = e.item_id
               WHERE e.item_id = ? GROUP BY e.item_id""", (item_id,)).fetchone()
        if row is None:
            return False, "Item not found."
        if row["condition"] == "Out of Service":
            return False, "This item is out of service and cannot be issued."
        available = row["quantity"] - row["issued"]
        if int(quantity) < 1 or int(quantity) > available:
            return False, f"Only {available} unit(s) are available."
        connection.execute("INSERT INTO lab_issues (item_id, issued_to, quantity, issued_on) VALUES (?, ?, ?, ?)",
                           (item_id, str(issued_to).strip(), int(quantity), str(issued_on)))
    return True, f"Issued {int(quantity)} unit(s) to {str(issued_to).strip()}."


def return_equipment(issue_id, returned_on):
    with get_connection() as connection:
        connection.execute("UPDATE lab_issues SET returned_on = ? WHERE issue_id = ? AND returned_on IS NULL",
                           (str(returned_on), int(issue_id)))
    return True, "Item marked as returned."


# ----- library -----
def loan_status(due_on, returned_on, today=None):
    if not pd.isna(returned_on) and str(returned_on).strip():
        return "Returned"
    today = today or date.today().isoformat()
    if str(due_on) < today:
        return "Overdue"
    days_left = (date.fromisoformat(str(due_on)) - date.fromisoformat(today)).days
    return "Due Soon" if days_left <= DUE_SOON_DAYS else "Issued"


def fine_for(due_on, end_date):
    late = (date.fromisoformat(str(end_date)) - date.fromisoformat(str(due_on))).days
    return float(max(late, 0) * FINE_PER_DAY)


def load_books():
    with get_connection() as connection:
        frame = pd.read_sql_query(
            """SELECT b.book_id, b.title, b.author, b.category, b.copies,
                      COUNT(CASE WHEN l.returned_on IS NULL THEN l.loan_id END) AS on_loan
               FROM library_books b LEFT JOIN library_loans l ON l.book_id = b.book_id
               GROUP BY b.book_id ORDER BY b.title""", connection)
    if frame.empty:
        frame["available"], frame["stock"] = [], []
        return frame
    frame["available"] = frame["copies"] - frame["on_loan"]
    frame["stock"] = np.select([frame["available"] <= 0, frame["available"] <= frame["copies"] * LOW_STOCK_RATIO],
                               ["Out of stock", "Low stock"], default="In stock")
    return frame


def load_loans():
    """All loans with status and fine (accruing for open overdue loans)."""
    with get_connection() as connection:
        frame = pd.read_sql_query(
            """SELECT l.loan_id, l.book_id, COALESCE(b.title, '(deleted)') AS title, l.borrower_id, l.borrower_type,
                      l.borrower_name, l.issued_on, l.due_on, l.returned_on, l.renewals, l.fine
               FROM library_loans l LEFT JOIN library_books b ON b.book_id = l.book_id
               ORDER BY l.issued_on DESC, l.loan_id DESC""", connection)
    if frame.empty:
        frame["status"], frame["days_late"] = [], []
        return frame
    today = date.today().isoformat()
    frame["status"] = [loan_status(d, r, today) for d, r in zip(frame["due_on"], frame["returned_on"])]
    open_overdue = frame["status"] == "Overdue"
    frame.loc[open_overdue, "fine"] = [fine_for(d, today) for d in frame.loc[open_overdue, "due_on"]]
    frame["days_late"] = np.where(open_overdue, [max((date.today() - date.fromisoformat(d)).days, 0)
                                                 for d in frame["due_on"]], 0)
    return frame


def _loan_days(borrower_type):
    return FACULTY_LOAN_DAYS if borrower_type == "Faculty" else LOAN_DAYS


def add_book(book_id, title, author, category, copies):
    if not str(book_id).strip() or not str(title).strip():
        return False, "Book ID and Title are required."
    if int(copies) < 1:
        return False, "Copies must be at least 1."
    try:
        with get_connection() as connection:
            connection.execute("INSERT INTO library_books (book_id, title, author, category, copies) VALUES (?, ?, ?, ?, ?)",
                               (str(book_id).strip(), str(title).strip(), str(author or "").strip(), category, int(copies)))
        return True, "Book saved successfully."
    except sqlite3.IntegrityError:
        return False, "This Book ID already exists."


def update_book(book_id, title, author, category, copies):
    if not str(title).strip():
        return False, "Title is required."
    with get_connection() as connection:
        on_loan = connection.execute("SELECT COUNT(*) FROM library_loans WHERE book_id = ? AND returned_on IS NULL",
                                     (book_id,)).fetchone()[0]
        if int(copies) < on_loan:
            return False, f"{on_loan} copies are on loan, so copies cannot be below {on_loan}."
        connection.execute("UPDATE library_books SET title=?, author=?, category=?, copies=? WHERE book_id=?",
                           (str(title).strip(), str(author or "").strip(), category, int(copies), book_id))
    return True, "Book updated successfully."


def delete_book(book_id):
    with get_connection() as connection:
        connection.execute("DELETE FROM library_loans WHERE book_id = ?", (book_id,))
        connection.execute("DELETE FROM library_books WHERE book_id = ?", (book_id,))


def issue_book(book_id, borrower_id, borrower_type, issued_on):
    """Returns (ok, message). Enforces availability, the student book limit and overdue blocking."""
    borrower_id = str(borrower_id).strip()
    table_name, key = ("students", "student_id") if borrower_type == "Student" else ("faculty", "faculty_id")
    with get_connection() as connection:
        person = connection.execute(f"SELECT name FROM {table_name} WHERE {key} = ?", (borrower_id,)).fetchone()
        if person is None:
            return False, f"No {borrower_type.lower()} found with ID {borrower_id or '(blank)'}."
        book = connection.execute(
            """SELECT b.copies, b.title, COUNT(CASE WHEN l.returned_on IS NULL THEN l.loan_id END) AS on_loan
               FROM library_books b LEFT JOIN library_loans l ON l.book_id = b.book_id
               WHERE b.book_id = ? GROUP BY b.book_id""", (book_id,)).fetchone()
        if book is None:
            return False, "Book not found."
        if book["copies"] - book["on_loan"] <= 0:
            return False, "No copies of this book are available right now."
        open_loans = connection.execute(
            "SELECT book_id, due_on FROM library_loans WHERE borrower_id = ? AND borrower_type = ? AND returned_on IS NULL",
            (borrower_id, borrower_type)).fetchall()
        if any(row["book_id"] == book_id for row in open_loans):
            return False, "This person already has this book."
        if any(row["due_on"] < date.today().isoformat() for row in open_loans):
            return False, "This person has an overdue book. Please return it (and pay any fine) first."
        if borrower_type == "Student" and len(open_loans) >= MAX_STUDENT_BOOKS:
            return False, f"Students can borrow at most {MAX_STUDENT_BOOKS} books at a time."
        due = date.fromisoformat(str(issued_on)) + timedelta(days=_loan_days(borrower_type))
        connection.execute(
            """INSERT INTO library_loans (book_id, borrower_id, borrower_type, borrower_name, issued_on, due_on)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (book_id, borrower_id, borrower_type, person["name"], str(issued_on), due.isoformat()))
    return True, f"Issued '{book['title']}' to {person['name']}. Due on {due:%d %b %Y}."


def return_book(loan_id, returned_on):
    """Returns (ok, message, fine)."""
    with get_connection() as connection:
        loan = connection.execute("SELECT due_on, returned_on FROM library_loans WHERE loan_id = ?", (int(loan_id),)).fetchone()
        if loan is None or loan["returned_on"]:
            return False, "This loan is not open.", 0.0
        fine = fine_for(loan["due_on"], returned_on)
        connection.execute("UPDATE library_loans SET returned_on = ?, fine = ? WHERE loan_id = ?",
                           (str(returned_on), fine, int(loan_id)))
    message = "Book returned." if fine == 0 else f"Book returned late. Fine to collect: {money(fine)}."
    return True, message, fine


def renew_book(loan_id, today=None):
    """Extend the due date. Not allowed when overdue, returned, or after MAX_RENEWALS renewals."""
    today = str(today or date.today().isoformat())
    with get_connection() as connection:
        loan = connection.execute("SELECT * FROM library_loans WHERE loan_id = ?", (int(loan_id),)).fetchone()
        if loan is None or loan["returned_on"]:
            return False, "This loan is not open."
        if loan["due_on"] < today:
            return False, "Overdue books cannot be renewed. Return the book and pay the fine."
        if loan["renewals"] >= MAX_RENEWALS:
            return False, f"This book has already been renewed {MAX_RENEWALS} times (the maximum)."
        new_due = date.fromisoformat(loan["due_on"]) + timedelta(days=_loan_days(loan["borrower_type"]))
        connection.execute("UPDATE library_loans SET due_on = ?, renewals = renewals + 1 WHERE loan_id = ?",
                           (new_due.isoformat(), int(loan_id)))
    return True, f"Renewed. New due date: {new_due:%d %b %Y}."


# ----- hostel -----
def load_rooms():
    with get_connection() as connection:
        frame = pd.read_sql_query(
            """SELECT r.room_no, r.block, r.floor, r.capacity, r.room_type, r.rent,
                      COUNT(CASE WHEN a.vacated_on IS NULL THEN a.alloc_id END) AS occupied
               FROM hostel_rooms r LEFT JOIN hostel_allocations a ON a.room_no = r.room_no
               GROUP BY r.room_no ORDER BY r.block, r.room_no""", connection)
    if frame.empty:
        frame["vacant"], frame["status"] = [], []
        return frame
    frame["vacant"] = frame["capacity"] - frame["occupied"]
    frame["status"] = np.select([frame["occupied"] >= frame["capacity"], frame["occupied"] == 0],
                                ["Full", "Empty"], default="Available")
    return frame


def load_residents():
    with get_connection() as connection:
        return pd.read_sql_query(
            """SELECT a.alloc_id, a.room_no, r.block, a.student_id, COALESCE(s.name, '(deleted)') AS name,
                      COALESCE(s.department, '-') AS department, COALESCE(s.year, 0) AS year, a.allotted_on
               FROM hostel_allocations a LEFT JOIN students s ON s.student_id = a.student_id
               LEFT JOIN hostel_rooms r ON r.room_no = a.room_no
               WHERE a.vacated_on IS NULL ORDER BY a.room_no, name""", connection)


def add_room(room_no, block, floor, capacity, room_type, rent):
    if not str(room_no).strip() or not str(block).strip():
        return False, "Room number and block are required."
    if int(capacity) < 1:
        return False, "Capacity must be at least 1."
    try:
        with get_connection() as connection:
            connection.execute("INSERT INTO hostel_rooms (room_no, block, floor, capacity, room_type, rent) VALUES (?, ?, ?, ?, ?, ?)",
                               (str(room_no).strip(), str(block).strip(), int(floor), int(capacity), room_type, float(rent)))
        return True, "Room saved successfully."
    except sqlite3.IntegrityError:
        return False, "This room number already exists."


def update_room(room_no, block, floor, capacity, room_type, rent):
    with get_connection() as connection:
        occupied = connection.execute("SELECT COUNT(*) FROM hostel_allocations WHERE room_no = ? AND vacated_on IS NULL",
                                      (room_no,)).fetchone()[0]
        if int(capacity) < occupied:
            return False, f"{occupied} resident(s) live here, so capacity cannot be below {occupied}."
        connection.execute("UPDATE hostel_rooms SET block=?, floor=?, capacity=?, room_type=?, rent=? WHERE room_no=?",
                           (str(block).strip(), int(floor), int(capacity), room_type, float(rent), room_no))
    return True, "Room updated successfully."


def delete_room(room_no):
    with get_connection() as connection:
        occupied = connection.execute("SELECT COUNT(*) FROM hostel_allocations WHERE room_no = ? AND vacated_on IS NULL",
                                      (room_no,)).fetchone()[0]
        if occupied:
            return False, f"{occupied} resident(s) still live here. Vacate them first."
        connection.execute("DELETE FROM hostel_allocations WHERE room_no = ?", (room_no,))
        connection.execute("DELETE FROM hostel_rooms WHERE room_no = ?", (room_no,))
    return True, "Room deleted."


def allot_room(room_no, student_id, allotted_on):
    student_id = str(student_id).strip()
    with get_connection() as connection:
        student = connection.execute("SELECT name FROM students WHERE student_id = ?", (student_id,)).fetchone()
        if student is None:
            return False, "Student not found."
        current = connection.execute("SELECT room_no FROM hostel_allocations WHERE student_id = ? AND vacated_on IS NULL",
                                     (student_id,)).fetchone()
        if current:
            return False, f"{student['name']} already lives in room {current['room_no']}. Vacate that first."
        room = connection.execute(
            """SELECT r.capacity, COUNT(CASE WHEN a.vacated_on IS NULL THEN a.alloc_id END) AS occupied
               FROM hostel_rooms r LEFT JOIN hostel_allocations a ON a.room_no = r.room_no
               WHERE r.room_no = ? GROUP BY r.room_no""", (room_no,)).fetchone()
        if room is None:
            return False, "Room not found."
        if room["occupied"] >= room["capacity"]:
            return False, "This room is full."
        connection.execute("INSERT INTO hostel_allocations (room_no, student_id, allotted_on) VALUES (?, ?, ?)",
                           (room_no, student_id, str(allotted_on)))
    return True, f"{student['name']} allotted to room {room_no}."


def vacate_room(alloc_id, vacated_on):
    with get_connection() as connection:
        connection.execute("UPDATE hostel_allocations SET vacated_on = ? WHERE alloc_id = ? AND vacated_on IS NULL",
                           (str(vacated_on), int(alloc_id)))
    return True, "Room vacated."


# ----- timetable -----
def load_timetable(department=None, year=None):
    query, params = "SELECT department, year, day, period, subject, faculty, room FROM timetable", []
    if department is not None:
        query += " WHERE department = ? AND year = ?"
        params = [department, int(year)]
    with get_connection() as connection:
        return pd.read_sql_query(query + " ORDER BY department, year, day, period", connection, params=params)


def save_slot(department, year, day, period, subject, faculty, room):
    """Insert or replace one period. Blocks a faculty member or room being in two places at once."""
    subject, faculty, room = str(subject).strip(), str(faculty or "").strip(), str(room or "").strip()
    if not subject:
        return False, "Subject is required."
    with get_connection() as connection:
        clash = connection.execute(
            """SELECT department, year, faculty, room FROM timetable
               WHERE day = ? AND period = ? AND NOT (department = ? AND year = ?)
                 AND ((? != '' AND faculty = ?) OR (? != '' AND room = ?))""",
            (day, int(period), department, int(year), faculty, faculty, room, room)).fetchone()
        if clash:
            what = f"{faculty} is" if faculty and clash["faculty"] == faculty else f"Room {room} is"
            return False, f"Clash: {what} already booked on {day} period {period} for {clash['department']} year {clash['year']}."
        connection.execute(
            """INSERT INTO timetable (department, year, day, period, subject, faculty, room) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (department, year, day, period)
               DO UPDATE SET subject = excluded.subject, faculty = excluded.faculty, room = excluded.room""",
            (department, int(year), day, int(period), subject, faculty, room))
    return True, "Period saved."


def clear_slot(department, year, day, period):
    with get_connection() as connection:
        connection.execute("DELETE FROM timetable WHERE department = ? AND year = ? AND day = ? AND period = ?",
                           (department, int(year), day, int(period)))


# ----- fee receipts -----
def payment_receipt(payment_id):
    with get_connection() as connection:
        row = connection.execute(
            """SELECT p.payment_id, p.amount, p.paid_on, p.mode, f.fee_id, f.student_id, f.fee_type,
                      f.amount AS fee_amount, f.due_date, COALESCE(s.name, '(deleted)') AS name,
                      COALESCE(s.department, '-') AS department, COALESCE(s.year, 0) AS year
               FROM fee_payments p JOIN fees f ON f.fee_id = p.fee_id
               LEFT JOIN students s ON s.student_id = f.student_id WHERE p.payment_id = ?""", (int(payment_id),)).fetchone()
        if row is None:
            return None
        data = dict(row)
        paid_to_date = connection.execute("SELECT COALESCE(SUM(amount), 0) FROM fee_payments WHERE fee_id = ? AND payment_id <= ?",
                                          (row["fee_id"], int(payment_id))).fetchone()[0]
    data["balance_after"] = max(data["fee_amount"] - paid_to_date, 0.0)
    data["receipt_no"] = f"RCP-{int(payment_id):05d}"
    return data


def receipt_html(data):
    """A standalone, print-friendly receipt page (open it and press Ctrl+P to print or save as PDF)."""
    rows = [("Student", f"{data['name']} ({data['student_id']})"), ("Department / Year", f"{data['department']} / Year {data['year']}"),
            ("Fee type", data["fee_type"]), ("Total fee", money(data["fee_amount"])), ("Payment date", data["paid_on"]),
            ("Payment mode", data["mode"] or "-"), ("Balance after this payment", money(data["balance_after"]))]
    body = "".join(f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>" for k, v in rows)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Receipt {html.escape(data['receipt_no'])}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f1f5f9;padding:32px}}
.card{{max-width:560px;margin:auto;background:#fff;border-radius:16px;padding:32px;box-shadow:0 8px 30px rgba(15,23,42,.12)}}
h1{{margin:0;color:#2563eb;font-size:22px}} .sub{{color:#64748b;margin-bottom:18px}}
.no{{float:right;font-weight:700;color:#0f172a}} table{{width:100%;border-collapse:collapse;margin-top:10px}}
td{{padding:10px 4px;border-bottom:1px solid #e2e8f0}} td:first-child{{color:#64748b}} td:last-child{{text-align:right;font-weight:600}}
.paid{{margin-top:20px;background:#dcfce7;color:#166534;border-radius:12px;padding:16px;text-align:center;font-size:22px;font-weight:800}}
.foot{{margin-top:22px;color:#94a3b8;font-size:12px;text-align:center}}
@media print{{body{{background:#fff;padding:0}} .card{{box-shadow:none}}}}</style></head><body><div class="card">
<span class="no">{html.escape(data['receipt_no'])}</span><h1>🎓 Campus Analytics</h1><div class="sub">Fee Payment Receipt</div>
<table>{body}</table><div class="paid">Amount received: {money(data['amount'])}</div>
<div class="foot">This is a computer-generated receipt and does not need a signature.</div></div></body></html>"""


DEMO_FIRST = ["Aarav", "Ananya", "Karthik", "Divya", "Rohan", "Meera", "Vikram", "Priya", "Arjun", "Sneha",
              "Harini", "Naveen", "Lakshmi", "Surya", "Kavya", "Ravi", "Nithya", "Gokul", "Swathi", "Dinesh"]
DEMO_LAST = ["Kumar", "Raj", "Iyer", "Nair", "Sharma", "Reddy", "Menon", "Pillai", "Das", "Krishnan"]


def generate_demo_data(count=60):
    """Insert realistic sample students (IDs start with DEMO) for trying out the app."""
    rng = np.random.default_rng(42)
    rows = []
    for i in range(1, count + 1):
        attendance = float(np.clip(rng.normal(80, 12), 35, 100))
        marks = float(np.clip(28 + 0.5 * attendance + rng.normal(0, 9), 15, 100))
        first, last = rng.choice(DEMO_FIRST), rng.choice(DEMO_LAST)
        rows.append((f"DEMO{i:03d}", f"{first} {last}", str(rng.choice(DEPARTMENTS)),
                     int(rng.integers(1, 5)), f"{first.lower()}.{last.lower()}{i}@college.edu",
                     "9" + "".join(str(d) for d in rng.integers(0, 10, 9)),
                     round(marks, 1), round(attendance, 1)))
    with get_connection() as connection:
        connection.executemany(
            """INSERT OR IGNORE INTO students (student_id, name, department, year, email, phone, marks, attendance)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", rows)
    return len(rows)


def generate_all_demo_data():
    """Students + faculty + fees + equipment in one go. Returns the number of students."""
    count = generate_demo_data()
    generate_demo_campus()
    generate_demo_extras()
    return count


def generate_demo_campus():
    """Demo faculty, fees and lab equipment (IDs start with DEMO) tied to the demo students."""
    rng = np.random.default_rng(7)
    today = date.today()
    first = ["Dr. Suresh", "Dr. Meena", "Prof. Anand", "Dr. Revathi", "Prof. Karthikeyan", "Dr. Uma",
             "Prof. Balaji", "Dr. Sangeetha", "Prof. Mohan", "Dr. Padma", "Prof. Ilango", "Dr. Vasanth"]
    last = ["Subramanian", "Narayanan", "Rajan", "Venkatesh", "Chandran", "Natarajan", "Gopal", "Ramesh"]
    quals = ["Ph.D", "M.E", "M.Tech", "Ph.D (Pursuing)"]
    faculty_rows = []
    for index in range(1, 15):
        department = DEPARTMENTS[(index - 1) % len(DEPARTMENTS)]
        designation = str(rng.choice(DESIGNATIONS, p=[0.2, 0.3, 0.4, 0.1]))
        name = f"{first[(index - 1) % len(first)]} {last[(index * 3) % len(last)]}"
        faculty_rows.append((f"DEMOF{index:03d}", name, department, designation, str(rng.choice(quals)),
                             f"faculty{index}@college.edu", "98" + "".join(str(d) for d in rng.integers(0, 10, 8)),
                             float(rng.integers(1, 26)), f"{department} core subjects",
                             "On Leave" if rng.random() < 0.1 else "Active"))
    equipment = [("Desktop Computer", "Computer", "Computer Lab", 40, 45000), ("Laptop", "Computer", "AI & Data Lab", 15, 62000),
                 ("GPU Workstation", "Computer", "AI & Data Lab", 4, 185000), ("Oscilloscope", "Electronics", "Electronics Lab", 12, 38000),
                 ("Function Generator", "Electronics", "Electronics Lab", 12, 15000), ("Network Switch", "Networking", "Networking Lab", 10, 22000),
                 ("Router", "Networking", "Networking Lab", 8, 18000), ("Digital Multimeter", "Electrical", "Electrical Lab", 30, 2500),
                 ("Lathe Machine", "Mechanical", "Mechanical Workshop", 3, 320000), ("Total Station", "Other", "Civil & Survey Lab", 2, 450000),
                 ("Vernier Caliper", "Physics/Chemistry", "Physics Lab", 40, 600), ("Digital Balance", "Physics/Chemistry", "Chemistry Lab", 6, 9000),
                 ("Projector", "Electronics", "Computer Lab", 5, 42000), ("Soldering Station", "Electronics", "Electronics Lab", 20, 3200),
                 ("Arduino Kit", "Electronics", "AI & Data Lab", 25, 1800), ("Lab Stool", "Furniture", "Physics Lab", 60, 1200)]
    equipment_rows = []
    for index, (name, category, lab, quantity, cost) in enumerate(equipment, start=1):
        condition = "Good" if rng.random() > 0.2 else str(rng.choice(["Needs Repair", "Out of Service"]))
        purchased = (today - timedelta(days=int(rng.integers(60, 1800)))).isoformat()
        equipment_rows.append((f"DEMOE{index:03d}", name, category, lab, quantity, float(cost), condition, purchased))

    with get_connection() as connection:
        connection.executemany(
            """INSERT OR IGNORE INTO faculty (faculty_id, name, department, designation, qualification, email, phone,
               experience, subjects, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", faculty_rows)
        connection.executemany(
            """INSERT OR IGNORE INTO lab_equipment (item_id, name, category, lab, quantity, unit_cost, condition, purchase_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", equipment_rows)
        for item_id, _, _, _, quantity, *_ in equipment_rows:
            if rng.random() < 0.6 and quantity >= 4:
                connection.execute(
                    "INSERT INTO lab_issues (item_id, issued_to, quantity, issued_on) SELECT ?, ?, ?, ? "
                    "WHERE NOT EXISTS (SELECT 1 FROM lab_issues WHERE item_id = ?)",
                    (item_id, f"Faculty {rng.choice(last)}", int(rng.integers(1, max(2, quantity // 2))),
                     (today - timedelta(days=int(rng.integers(1, 30)))).isoformat(), item_id))
        students = [r["student_id"] for r in connection.execute("SELECT student_id FROM students WHERE student_id LIKE 'DEMO%'")]
        for student_id in students:
            # one generator per student, so loading the demo twice never creates duplicate fees
            student_rng = np.random.default_rng(int(re.sub(r"\D", "", student_id) or 0) + 1000)
            for fee_type, low, high, offset in [("Tuition", 45000, 65000, int(student_rng.integers(-70, 50))),
                                                ("Exam", 1500, 3000, int(student_rng.integers(-20, 60)))]:
                amount = float(round(student_rng.integers(low, high) / 500) * 500)
                due = (today + timedelta(days=offset)).isoformat()
                roll = student_rng.random()
                part_fraction, paid_days_ago = float(student_rng.uniform(0.3, 0.7)), int(student_rng.integers(0, 60))
                mode = str(student_rng.choice(PAYMENT_MODES))
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO fees (student_id, fee_type, amount, due_date) VALUES (?, ?, ?, ?)",
                    (student_id, fee_type, amount, due))
                if cursor.rowcount != 1:
                    continue
                fee_id = cursor.lastrowid
                if roll < 0.55:
                    parts = [amount]
                elif roll < 0.8:
                    parts = [round(amount * part_fraction / 100) * 100]
                else:
                    parts = []
                for part in parts:
                    connection.execute("INSERT INTO fee_payments (fee_id, amount, paid_on, mode) VALUES (?, ?, ?, ?)",
                                       (fee_id, float(part), (today - timedelta(days=paid_days_ago)).isoformat(), mode))
    return len(faculty_rows), len(equipment_rows)


def generate_demo_extras():
    """Demo library, hostel and timetable data (requires the demo students and faculty)."""
    rng = np.random.default_rng(11)
    today = date.today()
    books = [("Introduction to Algorithms", "Cormen", "Computer Science", 4), ("Python Crash Course", "Matthes", "Computer Science", 5),
             ("Database System Concepts", "Silberschatz", "Computer Science", 3), ("Computer Networks", "Tanenbaum", "Computer Science", 3),
             ("Artificial Intelligence: A Modern Approach", "Russell", "Computer Science", 3), ("Operating System Concepts", "Galvin", "Computer Science", 4),
             ("Digital Design", "Mano", "Electronics", 4), ("Electronic Devices and Circuits", "Boylestad", "Electronics", 3),
             ("Signals and Systems", "Oppenheim", "Electronics", 3), ("Electrical Machines", "Nagrath", "Electrical", 3),
             ("Power Systems", "Kothari", "Electrical", 2), ("Engineering Thermodynamics", "Nag", "Mechanical", 3),
             ("Fluid Mechanics", "Bansal", "Mechanical", 3), ("Strength of Materials", "Rajput", "Civil", 3),
             ("Surveying", "Punmia", "Civil", 2), ("Advanced Engineering Mathematics", "Kreyszig", "Mathematics", 6),
             ("Higher Engineering Mathematics", "Grewal", "Mathematics", 6), ("Probability and Statistics", "Walpole", "Mathematics", 4),
             ("Engineering Physics", "Gaur", "Physics/Chemistry", 4), ("Engineering Chemistry", "Jain", "Physics/Chemistry", 4),
             ("Principles of Management", "Koontz", "Management", 3), ("Wings of Fire", "Kalam", "General", 5),
             ("Think and Grow Rich", "Hill", "General", 2), ("Data Science from Scratch", "Grus", "Computer Science", 3)]
    with get_connection() as connection:
        connection.executemany("INSERT OR IGNORE INTO library_books (book_id, title, author, category, copies) VALUES (?, ?, ?, ?, ?)",
                               [(f"DEMOB{i:03d}", t, a, c, n) for i, (t, a, c, n) in enumerate(books, start=1)])
        students = connection.execute("SELECT student_id, name FROM students WHERE student_id LIKE 'DEMO%' ORDER BY student_id").fetchall()

        # library loans: some returned, some open, a few overdue or renewed
        if students and not connection.execute("SELECT 1 FROM library_loans WHERE borrower_id LIKE 'DEMO%'").fetchone():
            open_count = {}
            for student in students[:34]:
                book_index = int(rng.integers(0, len(books)))
                book_id, copies = f"DEMOB{book_index + 1:03d}", books[book_index][3]
                issued = today - timedelta(days=int(rng.integers(1, 40)))
                renewals = int(rng.choice([0, 0, 1]))
                due = issued + timedelta(days=LOAN_DAYS * (1 + renewals))
                returned, fine = None, 0.0
                if rng.random() < 0.4:
                    returned = min(today, due + timedelta(days=int(rng.integers(-5, 6))))
                    returned = max(returned, issued)
                    fine = fine_for(due, returned)
                elif open_count.get(book_id, 0) >= copies:
                    continue
                else:
                    open_count[book_id] = open_count.get(book_id, 0) + 1
                connection.execute(
                    """INSERT INTO library_loans (book_id, borrower_id, borrower_type, borrower_name, issued_on, due_on,
                       returned_on, renewals, fine) VALUES (?, ?, 'Student', ?, ?, ?, ?, ?, ?)""",
                    (book_id, student["student_id"], student["name"], issued.isoformat(), due.isoformat(),
                     returned.isoformat() if returned else None, renewals, fine))

        # hostel rooms and residents
        rooms = []
        for block in ("A", "B"):
            for number in range(1, 7):
                rooms.append((f"DEMO-{block}{100 + number}", block, 1 + number // 4, 2 + number % 2,
                              "AC" if number % 3 == 0 else "Non-AC", 6500.0 if number % 3 == 0 else 3800.0))
        connection.executemany("INSERT OR IGNORE INTO hostel_rooms (room_no, block, floor, capacity, room_type, rent) VALUES (?, ?, ?, ?, ?, ?)", rooms)
        if students and not connection.execute("SELECT 1 FROM hostel_allocations WHERE room_no LIKE 'DEMO-%'").fetchone():
            pool = [s_["student_id"] for s_ in students[:22]]
            for room_no, _, _, capacity, _, _ in rooms:
                for _ in range(capacity):
                    if pool and rng.random() < 0.85:
                        connection.execute("INSERT INTO hostel_allocations (room_no, student_id, allotted_on) VALUES (?, ?, ?)",
                                           (room_no, pool.pop(0), (today - timedelta(days=int(rng.integers(10, 200)))).isoformat()))

        # timetable for three departments (year 2): rooms start with DEMO- so they can be removed
        if not connection.execute("SELECT 1 FROM timetable WHERE room LIKE 'DEMO-%'").fetchone():
            subjects = ["Mathematics", "Core Theory", "Programming Lab", "Data Structures", "Electives", "Soft Skills", "Project Work"]
            for dept_index, department in enumerate(DEPARTMENTS[:3]):
                staff = [r["name"] for r in connection.execute(
                    "SELECT name FROM faculty WHERE faculty_id LIKE 'DEMO%' AND department = ?", (department,))] or ["TBA"]
                for day_index, day in enumerate(DAYS[:5]):
                    for period in range(1, 7):
                        slot = (day_index * 2 + period + dept_index) % len(subjects)
                        connection.execute(
                            """INSERT OR IGNORE INTO timetable (department, year, day, period, subject, faculty, room)
                               VALUES (?, 2, ?, ?, ?, ?, ?)""",
                            (department, day, period, subjects[slot], staff[(day_index + period) % len(staff)], f"DEMO-CR{dept_index + 1}"))


def remove_demo_data():
    """Remove every demo record (students, their fees, demo faculty and demo equipment)."""
    with get_connection() as connection:
        connection.execute("DELETE FROM fee_payments WHERE fee_id IN (SELECT fee_id FROM fees WHERE student_id LIKE 'DEMO%')")
        connection.execute("DELETE FROM fees WHERE student_id LIKE 'DEMO%'")
        connection.execute("DELETE FROM library_loans WHERE book_id LIKE 'DEMO%' OR borrower_id LIKE 'DEMO%'")
        connection.execute("DELETE FROM library_books WHERE book_id LIKE 'DEMO%'")
        connection.execute("DELETE FROM hostel_allocations WHERE room_no LIKE 'DEMO-%' OR student_id LIKE 'DEMO%'")
        connection.execute("DELETE FROM hostel_rooms WHERE room_no LIKE 'DEMO-%'")
        connection.execute("DELETE FROM timetable WHERE room LIKE 'DEMO-%'")
        connection.execute("DELETE FROM lab_issues WHERE item_id LIKE 'DEMO%'")
        connection.execute("DELETE FROM lab_equipment WHERE item_id LIKE 'DEMO%'")
        connection.execute("DELETE FROM faculty WHERE faculty_id LIKE 'DEMO%'")
        cursor = connection.execute("DELETE FROM students WHERE student_id LIKE 'DEMO%'")
        return cursor.rowcount


# =============================================================================
# 3. AUTHENTICATION
# =============================================================================

def hash_password(password, salt=None):
    salt = os.urandom(16) if salt is None else salt
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return salt.hex(), digest.hex()


def verify_password(password, salt_hex, hash_hex):
    _, entered = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(entered, hash_hex)  # constant-time comparison


def ensure_default_admin():
    """First run: create admin and force a password change. Old DBs on the default get flagged."""
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM admins WHERE username = ?", (DEFAULT_ADMIN_USER,)).fetchone()
        if row is None:
            salt, digest = hash_password(DEFAULT_ADMIN_PASSWORD)
            connection.execute(
                "INSERT INTO admins (username, salt, password_hash, must_change) VALUES (?, ?, ?, 1)",
                (DEFAULT_ADMIN_USER, salt, digest))
        elif verify_password(LEGACY_DEFAULT_PASSWORD, row["salt"], row["password_hash"]):
            connection.execute("UPDATE admins SET must_change = 1 WHERE username = ?", (DEFAULT_ADMIN_USER,))


def attempt_login(username, password):
    """Returns (ok, message, must_change). Locks the account after repeated failures."""
    username, now = username.strip(), time.time()
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM admins WHERE username = ?", (username,)).fetchone()
        if row is not None and (row["locked_until"] or 0) > now:
            minutes = int((row["locked_until"] - now) // 60) + 1
            return False, f"Too many failed attempts. Try again in about {minutes} minute(s).", False
        if row is not None and verify_password(password, row["salt"], row["password_hash"]):
            connection.execute("UPDATE admins SET failed_attempts = 0, locked_until = 0 WHERE username = ?", (username,))
            return True, "", bool(row["must_change"])
        if row is not None:
            attempts = (row["failed_attempts"] or 0) + 1
            locked_until = now + LOCKOUT_SECONDS if attempts >= MAX_FAILED_ATTEMPTS else 0
            connection.execute("UPDATE admins SET failed_attempts = ?, locked_until = ? WHERE username = ?",
                               (0 if locked_until else attempts, locked_until, username))
        return False, "Invalid username or password.", False


def change_password(username, current, new, confirm):
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM admins WHERE username = ?", (username,)).fetchone()
        if row is None or not verify_password(current, row["salt"], row["password_hash"]):
            return False, "Current password is incorrect."
        if len(new) < MIN_PASSWORD_LENGTH:
            return False, f"New password must contain at least {MIN_PASSWORD_LENGTH} characters."
        if new != confirm:
            return False, "New password and confirmation do not match."
        if new == current or new == LEGACY_DEFAULT_PASSWORD:
            return False, "Choose a password different from the current or default one."
        salt, digest = hash_password(new)
        connection.execute("UPDATE admins SET salt = ?, password_hash = ?, must_change = 0 WHERE username = ?",
                           (salt, digest, username))
    return True, "Password updated successfully."


# =============================================================================
# 4. ANALYTICS HELPERS + MACHINE LEARNING
# =============================================================================

def grade_for(marks):
    for minimum, grade in GRADE_BANDS:
        if marks >= minimum:
            return grade
    return "Fail"


def performance_band(marks):
    for minimum, label in PERFORMANCE_BANDS:
        if marks >= minimum:
            return label
    return PERFORMANCE_BANDS[-1][1]


def attendance_status(value):
    if value >= EXCELLENT_ATTENDANCE:
        return "Excellent"
    return "Eligible" if value >= MIN_ATTENDANCE else "Low Attendance"


def add_risk_columns(frame):
    frame = frame.copy()
    low_marks, low_att = frame["marks"] < PASS_MARK, frame["attendance"] < MIN_ATTENDANCE
    frame["Risk Reason"] = np.select(
        [low_marks & low_att, low_marks, low_att],
        ["Low Marks & Low Attendance", "Low Marks", "Low Attendance"],
        default="No Current Risk Flag")
    return frame


def department_summary(frame):
    return (frame.groupby("department")
            .agg(Total_Students=("student_id", "count"), Average_Marks=("marks", "mean"),
                 Average_Attendance=("attendance", "mean"))
            .round(2).reset_index())


TARGET_LABELS = ["Needs Attention", "Good", "Excellent"]


def build_feature_frame(frame):
    # NOTE: marks is deliberately NOT a feature - the label is derived from it (that was a leak).
    return pd.get_dummies(frame[["attendance", "year", "department"]], columns=["department"], dtype=float)


def train_and_evaluate(frame):
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict

    target = frame["marks"].apply(performance_band)
    counts = target.value_counts()
    if len(counts) < 2 or counts.min() < 2:
        return {"error": "Each performance category in use needs at least 2 students, and at least 2 "
                         "categories must exist, to evaluate the model honestly."}
    features = build_feature_frame(frame)
    folds = int(min(5, counts.min()))
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
    model = RandomForestClassifier(n_estimators=200, random_state=42, min_samples_leaf=3)
    cv_pred = cross_val_predict(model, features, target, cv=cv)
    base_pred = cross_val_predict(DummyClassifier(strategy="most_frequent"), features, target, cv=cv)
    model.fit(features, target)
    importance = pd.Series(model.feature_importances_, index=features.columns).sort_values(ascending=False).reset_index()
    importance.columns = ["Feature", "Importance"]
    return {"model": model, "columns": list(features.columns), "folds": folds, "n_students": len(frame),
            "cv_accuracy": accuracy_score(target, cv_pred), "baseline_accuracy": accuracy_score(target, base_pred),
            "importance": importance, "class_counts": counts}


def predict_one(result, department, year, attendance):
    row = pd.DataFrame([{"attendance": attendance, "year": year, "department": department}])
    encoded = build_feature_frame(row).reindex(columns=result["columns"], fill_value=0.0)
    model = result["model"]
    return model.predict(encoded)[0], dict(zip(model.classes_, model.predict_proba(encoded)[0]))


# =============================================================================
# 5. THEME (CSS + chart style)
# =============================================================================

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, .stApp, .stMarkdown, p, h1, h2, h3, h4, label, input, textarea, button,
[data-testid="stMetricValue"], [data-testid="stCaptionContainer"] {
    font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
}
.stApp { background: __APP_BG__; color: #0F172A; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 1.8rem; padding-bottom: 3rem; max-width: 1280px; }
h1, h2, h3 { color: #0F172A; letter-spacing: -0.02em; }

/* ---------- page header ---------- */
.page-header { display: flex; align-items: center; gap: 16px; margin: 0 0 1.4rem 0; }
.page-icon { width: 54px; height: 54px; border-radius: 15px; display: flex; align-items: center;
    justify-content: center; font-size: 26px; flex: none;
    background: linear-gradient(135deg, #2563EB, #0EA5E9); box-shadow: 0 8px 20px rgba(37,99,235,.30); }
.page-title { font-size: 1.7rem; font-weight: 800; color: #0F172A; line-height: 1.15; }
.page-sub { color: #64748B; font-size: .95rem; margin-top: 3px; }

/* ---------- KPI cards ---------- */
.kpi { display: flex; align-items: center; gap: 14px; background: #fff; border: 1px solid #E2E8F0;
    border-radius: 16px; padding: 16px 18px; min-height: 92px;
    box-shadow: 0 1px 2px rgba(15,23,42,.04), 0 6px 16px rgba(15,23,42,.04); transition: transform .15s, box-shadow .15s; }
.kpi:hover { transform: translateY(-2px); box-shadow: 0 10px 24px rgba(15,23,42,.10); }
.kpi-icon { width: 46px; height: 46px; border-radius: 12px; display: flex; align-items: center;
    justify-content: center; font-size: 22px; flex: none; }
.kpi-blue .kpi-icon { background: #DBEAFE; } .kpi-teal .kpi-icon { background: #CCFBF1; }
.kpi-amber .kpi-icon { background: #FEF3C7; } .kpi-red .kpi-icon { background: #FEE2E2; }
.kpi-violet .kpi-icon { background: #EDE9FE; }
.kpi-label { font-size: .72rem; color: #64748B; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; }
.kpi-value { font-size: 1.65rem; font-weight: 800; color: #0F172A; line-height: 1.2; }
.kpi-hint { font-size: .76rem; color: #94A3B8; }

/* ---------- insights / sections / empty state ---------- */
.insight { border-radius: 12px; padding: 12px 16px; font-size: .9rem; color: #1E293B; height: 100%;
    background: #EFF6FF; border: 1px solid #DBEAFE; border-left: 4px solid #2563EB; }
.insight-good { background: #F0FDFA; border-color: #CCFBF1; border-left-color: #14B8A6; }
.insight-warn { background: #FFFBEB; border-color: #FEF3C7; border-left-color: #F59E0B; }
.section-title { font-size: 1.05rem; font-weight: 700; color: #0F172A; margin: .6rem 0 .1rem 0; }
.section-caption { color: #64748B; font-size: .85rem; margin-bottom: .6rem; }
.empty { text-align: center; padding: 3rem 1rem; background: #fff; border: 2px dashed #CBD5E1;
    border-radius: 18px; margin: 1rem 0; }
.empty-icon { font-size: 3rem; } .empty-title { font-size: 1.2rem; font-weight: 700; margin-top: .4rem; }
.empty-text { color: #64748B; margin-top: .3rem; }

/* ---------- tabs, buttons, inputs, metrics ---------- */
.stTabs [data-baseweb="tab-list"] { gap: 6px; border-bottom: 1px solid #E2E8F0; }
.stTabs [data-baseweb="tab"] { border-radius: 10px 10px 0 0; padding: 9px 16px; font-weight: 600; color: #64748B; }
.stTabs [aria-selected="true"] { color: #2563EB; }
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
    border-radius: 10px; font-weight: 600; border: 1px solid #CBD5E1; transition: all .15s; }
.stButton > button:hover, .stDownloadButton > button:hover { border-color: #2563EB; color: #2563EB; }
.stButton > button[kind="primary"], button[data-testid="stBaseButton-primary"],
[data-testid="stFormSubmitButton"] > button {
    background: linear-gradient(135deg, #2563EB, #0EA5E9); color: #fff; border: none;
    box-shadow: 0 4px 12px rgba(37,99,235,.28); }
.stButton > button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] > button:hover {
    color: #fff; filter: brightness(1.07); }
[data-testid="stMetric"] { background: #fff; border: 1px solid #E2E8F0; border-radius: 14px; padding: 14px 16px; }
.stAlert { border-radius: 12px; }
[data-testid="stDataFrame"] { border: 1px solid #E2E8F0; border-radius: 12px; overflow: hidden; }

/* ---------- sidebar ---------- */
[data-testid="stSidebar"] { background: linear-gradient(180deg, #0B1B30, #14243A); display: __SIDEBAR_DISPLAY__; }
[data-testid="stSidebar"] * { color: #E2E8F0; }
.brand { display: flex; align-items: center; gap: 12px; padding: .3rem .2rem 1rem; }
.brand-logo { width: 42px; height: 42px; border-radius: 12px; display: flex; align-items: center;
    justify-content: center; font-size: 22px; background: linear-gradient(135deg, #38BDF8, #2563EB); }
.brand-name { font-weight: 800; font-size: 1.05rem; letter-spacing: .02em; color: #fff; }
.brand-sub { font-size: .72rem; color: #94A3B8; }
[data-testid="stSidebar"] .stButton > button { background: transparent; border: none; box-shadow: none;
    justify-content: flex-start; text-align: left; padding: .55rem .85rem; border-radius: 10px; color: #CBD5E1; }
[data-testid="stSidebar"] .stButton > button p { text-align: left; width: 100%; font-weight: 500; }
[data-testid="stSidebar"] .stButton > button:hover { background: rgba(255,255,255,.08); color: #fff; }
[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
    background: linear-gradient(135deg, #2563EB, #0EA5E9); color: #fff; }
[data-testid="stSidebar"] .stButton > button[kind="primary"] p { font-weight: 700; color: #fff; }
[data-testid="stSidebar"] .stButton > button:disabled { opacity: .35; }
[data-testid="stSidebar"] .nav-group { font-size: .66rem; font-weight: 700; letter-spacing: .14em; color: #64748B;
    margin: .85rem 0 .25rem .5rem; }
.user-chip { display: flex; align-items: center; gap: 10px; padding: .6rem .7rem; border-radius: 12px;
    background: rgba(255,255,255,.07); margin-bottom: .6rem; }
.avatar { width: 34px; height: 34px; border-radius: 50%; background: linear-gradient(135deg, #14B8A6, #2563EB);
    display: flex; align-items: center; justify-content: center; font-weight: 800; color: #fff; }
.user-name { font-weight: 600; font-size: .9rem; color: #fff; } .user-role { font-size: .72rem; color: #94A3B8; }

/* ---------- login ---------- */
.login-brand { text-align: center; color: #fff; margin-bottom: 1.2rem; }
.login-logo { font-size: 3.2rem; } .login-title { font-size: 2rem; font-weight: 800; letter-spacing: .03em; }
.login-sub { opacity: .9; margin-top: 2px; }
.login-note { text-align: center; color: rgba(255,255,255,.85); font-size: .8rem; margin-top: 1rem; }
[data-testid="stForm"] { background: #fff; border-radius: 18px; padding: 1.6rem; border: none;
    box-shadow: 0 20px 50px rgba(2,32,71,.30); }

/* ---------- colour chips + student profile ---------- */
.legend { margin: .2rem 0 .7rem; font-size: .82rem; color: #475569; }
.chip { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .74rem; font-weight: 700; margin: 0 4px 4px 0; }
.chip-green { background: #DCFCE7; color: #166534; } .chip-blue { background: #DBEAFE; color: #1E40AF; }
.chip-amber { background: #FEF3C7; color: #92400E; } .chip-red { background: #FEE2E2; color: #991B1B; }
.receipt { background: #fff; border: 2px dashed #CBD5E1; border-radius: 16px; padding: 22px 26px; }
.receipt-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
.receipt-title { font-weight: 800; font-size: 1.15rem; color: #2563EB; } .receipt-no { font-weight: 700; color: #0F172A; }
.receipt-row { display: flex; justify-content: space-between; padding: 7px 0; border-bottom: 1px solid #E2E8F0; font-size: .92rem; }
.receipt-row span:first-child { color: #64748B; } .receipt-row span:last-child { font-weight: 600; color: #0F172A; }
.receipt-total { margin-top: 14px; background: #DCFCE7; color: #166534; border-radius: 12px; padding: 12px; text-align: center;
    font-size: 1.3rem; font-weight: 800; }
.profile-card { display: flex; align-items: center; gap: 20px; background: #fff; border: 1px solid #E2E8F0;
    border-radius: 18px; padding: 22px 24px; box-shadow: 0 1px 2px rgba(15,23,42,.04), 0 8px 22px rgba(15,23,42,.05); }
.profile-avatar { width: 76px; height: 76px; border-radius: 50%; flex: none; display: flex; align-items: center;
    justify-content: center; font-size: 1.9rem; font-weight: 800; color: #fff;
    background: linear-gradient(135deg, #2563EB, #14B8A6); box-shadow: 0 8px 20px rgba(37,99,235,.28); }
.profile-name { font-size: 1.4rem; font-weight: 800; color: #0F172A; line-height: 1.2; }
.profile-meta { color: #64748B; font-size: .9rem; margin: 4px 0 8px; }
</style>
"""


def build_css(logged_in):
    if logged_in:
        background, sidebar = "#F1F5F9", "block"
    else:
        background, sidebar = "linear-gradient(135deg, #03B5F5, #0878F9)", "none"
    return CSS.replace("__APP_BG__", background).replace("__SIDEBAR_DISPLAY__", sidebar)


def style_fig(fig, height=360, legend=False):
    """One consistent look for every chart."""
    fig.update_layout(
        template="plotly_white", height=height, margin=dict(l=8, r=8, t=52, b=8),
        font=dict(family="Inter, Segoe UI, sans-serif", size=13, color="#334155"),
        title=dict(font=dict(size=16, color="#0F172A"), x=0.0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=legend,
        colorway=PALETTE, hoverlabel=dict(bgcolor="#0F172A", font_color="#fff"),
        legend=dict(orientation="h", y=-0.15))
    fig.update_xaxes(showgrid=False, title_font=dict(size=12))
    fig.update_yaxes(gridcolor="#E2E8F0", title_font=dict(size=12))
    return fig


def show(fig, height=360, legend=False):
    st.plotly_chart(style_fig(fig, height, legend), use_container_width=True, config={"displayModeBar": False})


# =============================================================================
# 6. REUSABLE UI PIECES
# =============================================================================

def esc(value):
    return html.escape(str(value))


def page_header(icon, title, subtitle):
    st.markdown(
        f'<div class="page-header"><div class="page-icon">{icon}</div><div>'
        f'<div class="page-title">{esc(title)}</div><div class="page-sub">{esc(subtitle)}</div></div></div>',
        unsafe_allow_html=True)


def section(title, caption=""):
    st.markdown(f'<div class="section-title">{esc(title)}</div>'
                + (f'<div class="section-caption">{esc(caption)}</div>' if caption else ""), unsafe_allow_html=True)


def kpi_cards(items):
    """items: (icon, label, value, hint, tone)"""
    for column, (icon, label, value, hint, tone) in zip(st.columns(len(items)), items):
        column.markdown(
            f'<div class="kpi kpi-{tone}"><div class="kpi-icon">{icon}</div><div>'
            f'<div class="kpi-label">{esc(label)}</div><div class="kpi-value">{esc(value)}</div>'
            f'<div class="kpi-hint">{esc(hint)}</div></div></div>', unsafe_allow_html=True)


def insight_cards(items):
    """items: (tone, html_text) where tone is info/good/warn. Text may contain <b>."""
    for column, (tone, text) in zip(st.columns(len(items)), items):
        column.markdown(f'<div class="insight insight-{tone}">{text}</div>', unsafe_allow_html=True)


def no_data(page_key, title="No student records yet", text="Add students to see analytics here.", demo=True):
    st.markdown(f'<div class="empty"><div class="empty-icon">🗂️</div><div class="empty-title">{esc(title)}</div>'
                f'<div class="empty-text">{esc(text)}</div></div>', unsafe_allow_html=True)
    if demo:
        middle = st.columns([1, 1, 1])[1]
        if middle.button("✨ Load demo data to explore", type="primary", use_container_width=True,
                         key=f"demo_{page_key}"):
            added = generate_all_demo_data()
            flash(f"Loaded {added} demo students plus faculty, fees, lab equipment, library, hostel and timetable. Remove them any time in Admin Settings.", "success")
            st.rerun()


SCORE_COLORS = [  # (minimum, background, text, label)
    (80, "#DCFCE7", "#166534", "80+ Excellent"),
    (60, "#DBEAFE", "#1E40AF", "60-79 Good"),
    (PASS_MARK, "#FEF3C7", "#92400E", f"{PASS_MARK}-59 Pass"),
    (0, "#FEE2E2", "#991B1B", f"Below {PASS_MARK} At risk"),
]
ATTENDANCE_COLORS = [
    (EXCELLENT_ATTENDANCE, "#DCFCE7", "#166534", f"{EXCELLENT_ATTENDANCE}+ Excellent"),
    (MIN_ATTENDANCE, "#DBEAFE", "#1E40AF", f"{MIN_ATTENDANCE}-{EXCELLENT_ATTENDANCE - 1} Eligible"),
    (0, "#FEE2E2", "#991B1B", f"Below {MIN_ATTENDANCE} Low"),
]


def _cell_style(value, scale):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    for minimum, background, color, _ in scale:
        if number >= minimum:
            return f"background-color: {background}; color: {color}; font-weight: 700;"
    return ""


_GREEN, _BLUE, _AMBER, _RED = ("#DCFCE7", "#166534"), ("#DBEAFE", "#1E40AF"), ("#FEF3C7", "#92400E"), ("#FEE2E2", "#991B1B")
TEXT_STYLES = {  # words used in Status / Condition / Stock columns
    "Paid": _GREEN, "Active": _GREEN, "Good": _GREEN, "In stock": _GREEN, "Returned": _GREEN, "Available": _GREEN,
    "Partial": _BLUE, "Issued": _BLUE, "Empty": _BLUE,
    "Pending": _AMBER, "On Leave": _AMBER, "Low stock": _AMBER, "Needs Repair": _AMBER, "Due Soon": _AMBER, "Full": _AMBER,
    "Overdue": _RED, "Out of stock": _RED, "Out of Service": _RED,
}


def _text_style(value):
    colors = TEXT_STYLES.get(str(value))
    return f"background-color: {colors[0]}; color: {colors[1]}; font-weight: 700;" if colors else ""


def color_legend():
    """Small key explaining the cell colours used in the tables."""
    tone = {"#DCFCE7": "green", "#DBEAFE": "blue", "#FEF3C7": "amber", "#FEE2E2": "red"}

    def chips(scale):
        return "".join(f'<span class="chip chip-{tone[bg]}">{esc(label)}</span>' for _, bg, _, label in scale)
    st.markdown(f'<div class="legend"><b>Score:</b> {chips(SCORE_COLORS)} &nbsp; '
                f'<b>Attendance:</b> {chips(ATTENDANCE_COLORS)}</div>', unsafe_allow_html=True)


def table(frame, columns=None, height=None, legend=True):
    """Dataframe with colour-coded Score and Attendance cells and tidy labels."""
    frame = (frame[columns] if columns else frame).reset_index(drop=True)  # Styler needs a unique index
    config = {}
    for key, label in [("marks", "Score (%)"), ("attendance", "Attendance (%)")]:
        if key in frame:
            config[key] = st.column_config.NumberColumn(label, format="%.1f")
    for key, label in [("student_id", "ID"), ("name", "Name"), ("department", "Dept"), ("year", "Year"),
                       ("email", "Email"), ("phone", "Phone")]:
        if key in frame:
            config[key] = (st.column_config.NumberColumn(label, format="%d") if key == "year"
                           else st.column_config.TextColumn(label))
    data = frame
    colored = [c for c in ("marks", "attendance") if c in frame]
    status_cols = [c for c in ("Status", "Condition", "Stock") if c in frame]
    money_cols = [c for c in frame.columns if str(c).endswith("(₹)")]
    if colored and legend:
        color_legend()
    if colored or status_cols or money_cols:
        try:
            data = frame.style
            def paint(styler, function, columns):
                return (styler.map if hasattr(styler, "map") else styler.applymap)(function, subset=columns)
            if "marks" in frame:
                data = paint(data, lambda v: _cell_style(v, SCORE_COLORS), ["marks"])
            if "attendance" in frame:
                data = paint(data, lambda v: _cell_style(v, ATTENDANCE_COLORS), ["attendance"])
            if status_cols:
                data = paint(data, _text_style, status_cols)
            formats = {c: "{:.1f}" for c in colored}
            formats.update({c: money for c in money_cols})
            if formats:
                data = data.format(formats)
        except ImportError:  # Styler needs jinja2; fall back to a plain table
            data = frame
    options = {"height": height} if height else {}  # newer Streamlit rejects height=None
    st.dataframe(data, use_container_width=True, hide_index=True, column_config=config, **options)


def flash(message, kind="success"):
    st.session_state["_flash"] = (kind, message)


def show_flash():
    item = st.session_state.pop("_flash", None)
    if item:
        kind, message = item
        st.toast(message, icon={"success": "✅", "error": "❌", "info": "ℹ️", "warning": "⚠️"}.get(kind, "ℹ️"))


def csv_bytes(frame):
    return frame.to_csv(index=False).encode("utf-8")


# =============================================================================
# 7. PAGES
# =============================================================================

def build_insights(df):
    summary = department_summary(df)
    best = summary.loc[summary["Average_Marks"].idxmax()]
    items = [("good", f"🏆 <b>{esc(best['department'])}</b> leads with an average score of "
                      f"<b>{best['Average_Marks']:.1f}%</b>.")]
    low_att = (df["attendance"] < MIN_ATTENDANCE).mean() * 100
    items.append(("warn" if low_att >= 20 else "good",
                  f"📅 <b>{low_att:.0f}%</b> of students are below the {MIN_ATTENDANCE}% attendance requirement."))
    if len(df) >= 3 and df["attendance"].nunique() > 1 and df["marks"].nunique() > 1:
        r = df["attendance"].corr(df["marks"])
        strength = "strong" if abs(r) >= 0.6 else "moderate" if abs(r) >= 0.3 else "weak"
        direction = "positive" if r >= 0 else "negative"
        items.append(("info", f"🔗 Attendance and score show a <b>{strength} {direction}</b> link (r = {r:.2f}). "
                              "Correlation is not proof of cause."))
    else:
        failing = int((df["marks"] < PASS_MARK).sum())
        items.append(("info", f"📝 <b>{failing}</b> student(s) are below the {PASS_MARK}% pass mark."))
    return items


def campus_snapshot(student_count):
    """Faculty / fees / lab equipment summary shown on the dashboard (only for data that exists)."""
    faculty, fees, equipment = load_faculty(), load_fees(), load_equipment()
    if faculty.empty and fees.empty and equipment.empty and load_books().empty and load_rooms().empty:
        return
    section("🏫 Campus operations", "Faculty, fees and lab resources at a glance")
    cards = []
    if not faculty.empty:
        cards.append(("👩‍🏫", "Faculty", len(faculty), f"{student_count / len(faculty):.1f} students per faculty", "violet"))
    if not fees.empty:
        billed, collected = fees["amount"].sum(), fees["paid"].sum()
        rate = collected / billed * 100 if billed else 0
        overdue = fees[fees["status"] == "Overdue"]
        cards.append(("💰", "Fee Collection", f"{rate:.0f}%", f"{money(fees['balance'].sum())} pending", "teal" if rate >= 75 else "amber"))
        cards.append(("🚨", "Overdue Fees", money(overdue["balance"].sum()), f"{len(overdue)} fee record(s)", "red" if len(overdue) else "teal"))
    if not equipment.empty:
        needs = int((equipment["condition"] != "Good").sum())
        cards.append(("🧪", "Lab Units", int(equipment["quantity"].sum()), f"{needs} item(s) need attention", "red" if needs else "blue"))
    loans, rooms = load_loans(), load_rooms()
    if not loans.empty:
        late = int((loans["status"] == "Overdue").sum())
        cards.append(("📚", "Books on Loan", int(loans["returned_on"].isna().sum()), f"{late} overdue", "red" if late else "blue"))
    if not rooms.empty:
        beds = int(rooms["capacity"].sum())
        cards.append(("🏠", "Hostel Occupancy", f"{rooms['occupied'].sum() / beds * 100:.0f}%" if beds else "0%",
                      f"{int(rooms['vacant'].sum())} beds vacant", "violet"))
    for start in range(0, len(cards), 3):
        kpi_cards(cards[start:start + 3])
    st.write("")


def page_dashboard():
    today = datetime.now().strftime("%A, %d %B %Y")
    page_header("🏠", "Dashboard", f"{today}  ·  Welcome back, {st.session_state.current_admin}")
    df = load_students()
    if df.empty:
        return no_data("dashboard", text="Open Student Records to add students, or load demo data to explore.")

    flagged = add_risk_columns(df)
    at_risk = int((flagged["Risk Reason"] != "No Current Risk Flag").sum())
    kpi_cards([
        ("🎓", "Students", len(df), f"{df['year'].nunique()} year group(s)", "blue"),
        ("🏢", "Departments", df["department"].nunique(), "with enrolled students", "violet"),
        ("📊", "Average Score", f"{df['marks'].mean():.1f}%", f"Pass rate {(df['marks'] >= PASS_MARK).mean() * 100:.0f}%", "teal"),
        ("📅", "Avg Attendance", f"{df['attendance'].mean():.1f}%", f"Minimum {MIN_ATTENDANCE}%", "amber"),
        ("⚠️", "At Risk", at_risk, f"{at_risk / len(df) * 100:.0f}% of students", "red"),
    ])
    st.write("")
    insight_cards(build_insights(df))
    st.write("")
    campus_snapshot(len(df))

    left, right = st.columns(2)
    with left, st.container(border=True):
        by_dept = df.groupby("department")["marks"].mean().reset_index()
        fig = px.bar(by_dept, x="department", y="marks", color="department", color_discrete_map=DEPT_COLORS,
                     text_auto=".1f", title="Average score by department",
                     labels={"department": "", "marks": "Average score (%)"})
        fig.update_yaxes(range=[0, 100])
        show(fig)
    with right, st.container(border=True):
        bands = df["marks"].apply(performance_band).value_counts().reset_index()
        bands.columns = ["Performance", "Students"]
        fig = px.pie(bands, names="Performance", values="Students", hole=0.55, color="Performance",
                     color_discrete_map=BAND_COLORS, title="Performance categories")
        show(fig, legend=True)

    with st.container(border=True):
        fig = px.scatter(df, x="attendance", y="marks", color="department", color_discrete_map=DEPT_COLORS,
                         hover_data=["student_id", "name", "year"], opacity=0.85,
                         title="Attendance vs score (each dot is a student)",
                         labels={"attendance": "Attendance (%)", "marks": "Score (%)"})
        fig.add_hline(y=PASS_MARK, line_dash="dot", line_color="#EF4444", annotation_text="Pass mark")
        fig.add_vline(x=MIN_ATTENDANCE, line_dash="dot", line_color="#F59E0B", annotation_text="Min attendance")
        if len(df) >= 3 and df["attendance"].nunique() > 1:
            slope, intercept = np.polyfit(df["attendance"], df["marks"], 1)
            x0, x1 = float(df["attendance"].min()), float(df["attendance"].max())
            fig.add_shape(type="line", x0=x0, y0=slope * x0 + intercept, x1=x1, y1=slope * x1 + intercept,
                          line=dict(color="#0F172A", width=2, dash="dash"))
        show(fig, height=400, legend=True)

    color_legend()
    top_col, low_col = st.columns(2)
    with top_col:
        section("🏅 Top 5 students", "Highest scores right now")
        table(df.sort_values("marks", ascending=False).head(5), ["student_id", "name", "department", "marks", "attendance"], legend=False)
    with low_col:
        section("🆘 5 students to support first", "Lowest scores right now")
        table(df.sort_values("marks").head(5), ["student_id", "name", "department", "marks", "attendance"], legend=False)


def student_fields(prefix, defaults=None):
    d = defaults or {}
    left, right = st.columns(2)
    name = left.text_input("Student Name *", value=d.get("name", ""), key=f"{prefix}_name")
    dept_index = DEPARTMENTS.index(d["department"]) if d.get("department") in DEPARTMENTS else 0
    department = right.selectbox("Department", DEPARTMENTS, index=dept_index, key=f"{prefix}_dept")
    left, right = st.columns(2)
    year_index = YEARS.index(int(d["year"])) if d.get("year") in YEARS else 0
    year = left.selectbox("Year", YEARS, index=year_index, key=f"{prefix}_year")
    email = right.text_input("Email", value=d.get("email", ""), key=f"{prefix}_email", placeholder="name@college.edu")
    left, right = st.columns(3)[0:2]
    phone = left.text_input("Phone Number", value=d.get("phone", ""), key=f"{prefix}_phone", placeholder="10 digits")
    marks_col, att_col = st.columns(2)
    marks = marks_col.number_input("Academic Score (%)", 0.0, 100.0, float(d.get("marks", 0.0)), step=0.5, key=f"{prefix}_marks")
    attendance = att_col.number_input("Attendance (%)", 0.0, 100.0, float(d.get("attendance", 0.0)), step=0.5, key=f"{prefix}_att")
    return name, department, year, email, phone, marks, attendance


def page_students():
    page_header("👨‍🎓", "Student Records", "Add, search, edit and manage student information")
    tab_view, tab_add, tab_edit, tab_delete, tab_import = st.tabs(
        ["📋 View & Search", "➕ Add Student", "✏️ Edit", "🗑️ Delete", "📤 Import CSV"])

    with tab_view:
        records = load_students()
        if records.empty:
            no_data("students", text="No students yet. Use the Add Student tab or import a CSV file.")
        else:
            with st.container(border=True):
                f1, f2, f3 = st.columns([2, 1.2, 1])
                search = f1.text_input("🔍 Search", placeholder="Student ID or name")
                dept_filter = f2.multiselect("Department", sorted(records["department"].unique()))
                year_filter = f3.multiselect("Year", sorted(records["year"].unique()))
                score_range = st.slider("Score range (%)", 0, 100, (0, 100))
            view = records
            if search:
                # regex=False so characters like ( or + can be searched safely
                view = view[view["student_id"].str.contains(search, case=False, na=False, regex=False)
                            | view["name"].str.contains(search, case=False, na=False, regex=False)]
            if dept_filter:
                view = view[view["department"].isin(dept_filter)]
            if year_filter:
                view = view[view["year"].isin(year_filter)]
            view = view[view["marks"].between(*score_range)]
            head, button = st.columns([3, 1])
            head.caption(f"Showing **{len(view)}** of **{len(records)}** students")
            button.download_button("⬇️ Download CSV", csv_bytes(view), "students.csv", "text/csv", use_container_width=True)
            table(view)

    with tab_add:
        with st.form("add_student_form", clear_on_submit=True):
            student_id = st.text_input("Student ID *", placeholder="e.g. 24AD101")
            fields = student_fields("add")
            submitted = st.form_submit_button("💾 Save Student", use_container_width=True)
        if submitted:
            ok, message = add_student(student_id, *fields)
            (st.success if ok else st.error)(message)
            if ok:
                st.toast("Student added", icon="✅")

    with tab_edit:
        records = load_students()
        if records.empty:
            st.info("No student records available to edit.")
        else:
            names = dict(zip(records["student_id"].astype(str), records["name"]))
            selected = st.selectbox("Choose a student", list(names), format_func=lambda s: f"{s}  —  {names[s]}", key="edit_select")
            current = records[records["student_id"].astype(str) == selected].iloc[0].to_dict()
            current["email"], current["phone"] = current.get("email") or "", current.get("phone") or ""
            with st.form(f"edit_form_{selected}"):
                fields = student_fields(f"edit_{selected}", current)
                submitted = st.form_submit_button("💾 Update Student", use_container_width=True)
            if submitted:
                ok, message = update_student(selected, *fields)
                if ok:
                    flash(message)
                    st.rerun()
                else:
                    st.error(message)

    with tab_delete:
        records = load_students(["student_id", "name", "department", "year", "marks", "attendance"])
        if records.empty:
            st.info("No student records available to delete.")
        else:
            names = dict(zip(records["student_id"].astype(str), records["name"]))
            selected = st.selectbox("Choose a student to delete", list(names),
                                    format_func=lambda s: f"{s}  —  {names[s]}", key="delete_select")
            row = records[records["student_id"].astype(str) == selected]
            table(row)
            st.warning("Deleting a student cannot be undone. Their fee records are deleted too.")
            confirm = st.checkbox("I understand and want to delete this record", key=f"confirm_{selected}")
            if st.button("🗑️ Delete Student", type="primary", disabled=not confirm):
                delete_student(selected)
                flash("Student record deleted.")
                st.rerun()

    with tab_import:
        st.caption("Required columns: student_id, name, department, year, marks, attendance. "
                   "Optional: email, phone. Existing IDs are skipped, never overwritten.")
        template = pd.DataFrame([{"student_id": "S001", "name": "Example Name", "department": "CSE", "year": 2,
                                  "email": "example@college.edu", "phone": "9876543210", "marks": 72.5, "attendance": 88}])
        st.download_button("⬇️ Download CSV template", csv_bytes(template), "student_import_template.csv", "text/csv")
        upload = st.file_uploader("Drop a CSV file here", type="csv")
        if upload is not None:
            try:
                data = pd.read_csv(upload, dtype={"student_id": str, "phone": str}).fillna("")
            except Exception as error:
                st.error(f"Could not read the file: {error}")
            else:
                st.caption(f"{len(data)} rows found. Preview of the first 10:")
                st.dataframe(data.head(10), use_container_width=True, hide_index=True)
                if st.button("✅ Import these students", type="primary"):
                    added, skipped = import_students(data)
                    st.success(f"Imported {added} student(s).")
                    if skipped:
                        st.warning(f"Skipped {len(skipped)} row(s):")
                        st.markdown("\n".join(f"- {s}" for s in skipped[:20]))


def next_milestone(marks, attendance):
    """Plain-language 'what to do next' tips for one student."""
    tips = []
    if marks < PASS_MARK:
        tips.append(f"📝 Needs <b>{PASS_MARK - marks:.1f}</b> more marks to reach the {PASS_MARK}% pass mark.")
    else:
        higher = [(m, g) for m, g in GRADE_BANDS if m > marks]
        if higher:
            target_marks, target_grade = higher[-1]
            tips.append(f"🎯 Needs <b>{target_marks - marks:.1f}</b> more marks to reach grade <b>{target_grade}</b>.")
        else:
            tips.append("🏆 Already at the top grade band. Keep it up!")
    if attendance < MIN_ATTENDANCE:
        tips.append(f"📅 Needs <b>{MIN_ATTENDANCE - attendance:.1f}</b> more attendance points to meet the {MIN_ATTENDANCE}% requirement.")
    else:
        tips.append(f"✅ Meets the {MIN_ATTENDANCE}% attendance requirement.")
    return tips


def page_profile():
    page_header("🪪", "Student Profile", "A complete 360° view of one student")
    df = load_students()
    if df.empty:
        return no_data("profile")
    names = dict(zip(df["student_id"].astype(str), df["name"]))
    selected = st.selectbox("🔍 Search or choose a student", list(names),
                            format_func=lambda sid: f"{sid}  —  {names[sid]}", key="profile_select")
    student = df[df["student_id"].astype(str) == selected].iloc[0]
    marks, attendance = float(student["marks"]), float(student["attendance"])
    same_dept = df[df["department"] == student["department"]]
    college_rank = int((df["marks"] > marks).sum()) + 1
    dept_rank = int((same_dept["marks"] > marks).sum()) + 1
    percentile = (df["marks"] < marks).mean() * 100
    risk = add_risk_columns(pd.DataFrame([{"marks": marks, "attendance": attendance}])).iloc[0]["Risk Reason"]

    band = performance_band(marks)
    band_chip = {"Excellent": "green", "Good": "blue", "Needs Attention": "amber"}[band]
    risk_chip = "green" if risk == "No Current Risk Flag" else "red"
    initials = "".join(part[0] for part in str(student["name"]).split()[:2]).upper() or "?"
    contact = " · ".join(esc(v) for v in (student["email"], student["phone"]) if v)
    st.markdown(
        f'<div class="profile-card"><div class="profile-avatar">{esc(initials)}</div><div>'
        f'<div class="profile-name">{esc(student["name"])}</div>'
        f'<div class="profile-meta">ID {esc(student["student_id"])} · {esc(student["department"])} · '
        f'Year {int(student["year"])}' + (f' · {contact}' if contact else '') + '</div>'
        f'<span class="chip chip-{band_chip}">{esc(band)}</span>'
        f'<span class="chip chip-{risk_chip}">{"No risk flags" if risk_chip == "green" else esc(risk)}</span>'
        f'<span class="chip chip-blue">Grade {esc(grade_for(marks))}</span></div></div>', unsafe_allow_html=True)
    st.write("")

    all_fees = load_fees()
    my_fees = all_fees[all_fees["student_id"].astype(str) == str(selected)] if not all_fees.empty else all_fees
    fee_balance = float(my_fees["balance"].sum()) if not my_fees.empty else 0.0
    fee_overdue = bool((my_fees["status"] == "Overdue").any()) if not my_fees.empty else False
    if my_fees.empty:
        fee_hint, fee_tone = "no fees assigned", "blue"
    elif fee_overdue:
        fee_hint, fee_tone = "overdue", "red"
    else:
        fee_hint, fee_tone = ("all paid" if fee_balance == 0 else "pending"), ("teal" if fee_balance == 0 else "amber")
    kpi_cards([
        ("📊", "Score", f"{marks:.1f}%", f"Grade {grade_for(marks)}", "teal" if marks >= PASS_MARK else "red"),
        ("📅", "Attendance", f"{attendance:.1f}%", attendance_status(attendance), "blue" if attendance >= MIN_ATTENDANCE else "red"),
        ("🏆", "College rank", f"#{college_rank}", f"of {len(df)} · top {100 - percentile:.0f}%", "violet"),
        ("🏢", "Department rank", f"#{dept_rank}", f"of {len(same_dept)} in {student['department']}", "amber"),
        ("💰", "Fee balance", money(fee_balance), fee_hint, fee_tone),
    ])
    st.write("")

    left, right = st.columns([3, 2])
    with left, st.container(border=True):
        comparison = pd.DataFrame({
            "Measure": ["Score (%)", "Score (%)", "Score (%)", "Attendance (%)", "Attendance (%)", "Attendance (%)"],
            "Group": ["This student", f"{student['department']} average", "College average"] * 2,
            "Value": [marks, same_dept["marks"].mean(), df["marks"].mean(),
                      attendance, same_dept["attendance"].mean(), df["attendance"].mean()]})
        fig = px.bar(comparison, x="Measure", y="Value", color="Group", barmode="group", text_auto=".1f",
                     color_discrete_map={"This student": "#2563EB", f"{student['department']} average": "#14B8A6",
                                         "College average": "#CBD5E1"},
                     title="How this student compares", labels={"Value": "", "Measure": ""})
        fig.update_yaxes(range=[0, 105])
        show(fig, height=340, legend=True)
    with right, st.container(border=True):
        section("🧭 What to do next")
        tips = next_milestone(marks, attendance)
        all_loans = load_loans()
        mine = all_loans[(all_loans["borrower_id"].astype(str) == str(selected)) & (all_loans["borrower_type"] == "Student")
                         & all_loans["returned_on"].isna()] if not all_loans.empty else all_loans
        if not mine.empty:
            late_books = int((mine["status"] == "Overdue").sum())
            tips.append(f"📚 <b>{len(mine)}</b> book(s) on loan" + (f", <b>{late_books}</b> overdue." if late_books else "."))
        residents = load_residents()
        room_row = residents[residents["student_id"].astype(str) == str(selected)] if not residents.empty else residents
        if not room_row.empty:
            tips.append(f"🏠 Lives in hostel room <b>{esc(room_row.iloc[0]['room_no'])}</b> (Block {esc(room_row.iloc[0]['block'])}).")
        if fee_overdue:
            tips.append(f"💰 <b>{money(my_fees.loc[my_fees['status'] == 'Overdue', 'balance'].sum())}</b> of fees are overdue.")
        for tip in tips:
            st.markdown(f'<div class="insight" style="margin-bottom:8px">{tip}</div>', unsafe_allow_html=True)
        if risk != "No Current Risk Flag":
            st.warning(f"Risk flag: **{risk}**. A mentor follow-up is recommended.")
        else:
            st.success("No current risk flags for this student.")
    st.download_button("⬇️ Download this profile (CSV)", csv_bytes(student.to_frame().T),
                       f"profile_{selected}.csv", "text/csv")


def page_academic():
    page_header("📊", "Academic Performance", "Marks, grades and pass rates across the college")
    df = load_students()
    if df.empty:
        return no_data("academic")
    kpi_cards([
        ("🎓", "Students", len(df), "in the database", "blue"),
        ("📊", "Average Marks", f"{df['marks'].mean():.1f}%", "college-wide", "teal"),
        ("🥇", "Highest Marks", f"{df['marks'].max():.1f}%", "best individual score", "violet"),
        ("✅", "Pass Rate", f"{(df['marks'] >= PASS_MARK).mean() * 100:.1f}%", f"pass mark {PASS_MARK}%", "amber"),
    ])
    st.write("")
    tab_over, tab_grades, tab_low = st.tabs(["📈 Overview", "🎯 Grades", "⚠️ Needs Improvement"])
    with tab_over:
        left, right = st.columns(2)
        with left, st.container(border=True):
            by_dept = df.groupby("department")["marks"].mean().reset_index()
            fig = px.bar(by_dept, x="department", y="marks", color="department", color_discrete_map=DEPT_COLORS,
                         text_auto=".1f", title="Average marks by department", labels={"department": "", "marks": "Marks (%)"})
            show(fig)
        with right, st.container(border=True):
            fig = px.histogram(df, x="marks", nbins=10, title="Marks distribution", labels={"marks": "Marks (%)"})
            fig.update_traces(marker_color="#2563EB", marker_line_width=0)
            fig.update_layout(bargap=0.06, yaxis_title="Students")
            show(fig)
    with tab_grades:
        graded = df.copy()
        graded["Grade"] = graded["marks"].apply(grade_for)
        counts = graded["Grade"].value_counts().reindex(GRADE_ORDER, fill_value=0).reset_index()
        counts.columns = ["Grade", "Students"]
        with st.container(border=True):
            fig = px.bar(counts, x="Grade", y="Students", text_auto=True, title="Students per grade")
            fig.update_traces(marker_color="#0EA5E9", marker_line_width=0)
            show(fig, height=300)
        chosen = st.multiselect("Filter by grade", GRADE_ORDER)
        shown = graded[graded["Grade"].isin(chosen)] if chosen else graded
        table(shown, ["student_id", "name", "department", "year", "marks", "Grade"])
    with tab_low:
        low = df[df["marks"] < PASS_MARK]
        if low.empty:
            st.success(f"No students below {PASS_MARK}% marks. 🎉")
        else:
            st.warning(f"{len(low)} student(s) are below the {PASS_MARK}% pass mark.")
            table(low.sort_values("marks"), ["student_id", "name", "department", "year", "marks", "attendance"])


def page_attendance():
    page_header("📅", "Attendance", f"Monitor attendance against the {MIN_ATTENDANCE}% requirement")
    df = load_students()
    if df.empty:
        return no_data("attendance")
    eligible = int((df["attendance"] >= MIN_ATTENDANCE).sum())
    kpi_cards([
        ("🎓", "Students", len(df), "tracked", "blue"),
        ("📅", "Average Attendance", f"{df['attendance'].mean():.1f}%", "college-wide", "teal"),
        ("✅", "Eligible", eligible, f"≥ {MIN_ATTENDANCE}% attendance", "violet"),
        ("🚫", "Low Attendance", len(df) - eligible, f"< {MIN_ATTENDANCE}% attendance", "red"),
    ])
    st.write("")
    tab_over, tab_low, tab_all = st.tabs(["📈 Overview", "⚠️ Below requirement", "📋 All students"])
    with tab_over:
        left, right = st.columns(2)
        with left, st.container(border=True):
            by_dept = df.groupby("department")["attendance"].mean().reset_index()
            fig = px.bar(by_dept, x="department", y="attendance", color="department", color_discrete_map=DEPT_COLORS,
                         text_auto=".1f", title="Average attendance by department",
                         labels={"department": "", "attendance": "Attendance (%)"})
            fig.add_hline(y=MIN_ATTENDANCE, line_dash="dash", line_color="#EF4444", annotation_text=f"{MIN_ATTENDANCE}% minimum")
            show(fig)
        with right, st.container(border=True):
            status = df["attendance"].apply(attendance_status).value_counts().reset_index()
            status.columns = ["Status", "Students"]
            fig = px.pie(status, names="Status", values="Students", hole=0.55, color="Status",
                         color_discrete_map=STATUS_COLORS, title="Attendance status")
            show(fig, legend=True)
    with tab_low:
        low = df[df["attendance"] < MIN_ATTENDANCE]
        if low.empty:
            st.success(f"Everyone has at least {MIN_ATTENDANCE}% attendance. 🎉")
        else:
            st.warning(f"{len(low)} student(s) are below {MIN_ATTENDANCE}% attendance.")
            table(low.sort_values("attendance"), ["student_id", "name", "department", "year", "attendance"])
    with tab_all:
        table(df, ["student_id", "name", "department", "year", "attendance"])


def page_departments():
    page_header("🏢", "Department Analysis", "Compare performance across departments")
    df = load_students()
    if df.empty:
        return no_data("departments")
    summary = department_summary(df)
    best = summary.loc[summary["Average_Marks"].idxmax()]
    kpi_cards([
        ("🏢", "Departments", len(summary), "with students", "violet"),
        ("🎓", "Students", len(df), "in total", "blue"),
        ("📊", "Avg Dept Marks", f"{summary['Average_Marks'].mean():.1f}%", "mean of departments", "teal"),
        ("🏆", "Top Department", best["department"], f"{best['Average_Marks']:.1f}% average", "amber"),
    ])
    st.write("")
    section("📋 Summary table")
    st.dataframe(summary.rename(columns={"department": "Department", "Total_Students": "Students",
                                         "Average_Marks": "Avg Marks (%)", "Average_Attendance": "Avg Attendance (%)"}),
                 use_container_width=True, hide_index=True)
    c1, c2, c3 = st.columns(3)
    for column, field, title in [(c1, "Total_Students", "Students per department"),
                                 (c2, "Average_Marks", "Average marks"),
                                 (c3, "Average_Attendance", "Average attendance")]:
        with column, st.container(border=True):
            fig = px.bar(summary, x="department", y=field, color="department", color_discrete_map=DEPT_COLORS,
                         title=title, labels={"department": "", field: ""})
            show(fig, height=320)
    with st.container(border=True):
        pivot = df.pivot_table(index="department", columns="year", values="marks", aggfunc="mean").round(1)
        fig = px.imshow(pivot, text_auto=True, aspect="auto", color_continuous_scale=["#E0F2FE", "#2563EB"],
                        title="Average marks: department × year",
                        labels={"x": "Year", "y": "Department", "color": "Marks"})
        show(fig, height=380)


def page_prediction():
    page_header("🤖", "Performance Prediction", "A machine-learning demo, evaluated honestly")
    df = load_students()
    minimum = 15
    if df.empty or len(df) < minimum:
        return no_data("prediction", "Not enough data to train a model",
                       f"At least {minimum} students are needed (you have {len(df)}).")
    st.info("The model predicts a performance category **without being shown the marks** (that would be cheating). "
            "Accuracy is measured with cross-validation on unseen students and compared with a naive baseline "
            "that always guesses the most common category.")
    if st.button("🚀 Train & Evaluate Model", type="primary"):
        with st.spinner("Training model..."):
            result = train_and_evaluate(df)
        if "error" in result:
            st.warning(result["error"])
        else:
            st.session_state["prediction_result"] = result
            st.toast("Model trained", icon="✅")
    result = st.session_state.get("prediction_result")
    if not result:
        return
    st.write("")
    gain = (result["cv_accuracy"] - result["baseline_accuracy"]) * 100
    kpi_cards([
        ("🎯", f"Accuracy ({result['folds']}-fold CV)", f"{result['cv_accuracy'] * 100:.1f}%", "on unseen students", "teal"),
        ("📏", "Naive baseline", f"{result['baseline_accuracy'] * 100:.1f}%", "always guess most common", "amber"),
        ("📈", "Improvement", f"{gain:+.1f} pts", "model minus baseline", "blue" if gain > 0 else "red"),
    ])
    if gain <= 0:
        st.warning("The model does not beat the baseline, so attendance, year and department are not predictive "
                   "enough for this dataset. That is a genuine finding, not an error.")
    st.caption(f"Trained on {result['n_students']} students. Small datasets give unstable estimates.")
    left, right = st.columns(2)
    with left, st.container(border=True):
        fig = px.bar(result["importance"].head(8), x="Importance", y="Feature", orientation="h",
                     title="What the model relied on")
        fig.update_traces(marker_color="#2563EB", marker_line_width=0)
        fig.update_yaxes(categoryorder="total ascending")
        show(fig, height=330)
    with right, st.container(border=True):
        section("🎯 Try a prediction")
        with st.form("predict_form"):
            department = st.selectbox("Department", DEPARTMENTS)
            year = st.selectbox("Year", YEARS)
            attendance = st.slider("Attendance (%)", 0, 100, 80)
            go = st.form_submit_button("Predict", use_container_width=True)
        if go:
            label, probabilities = predict_one(result, department, year, float(attendance))
            st.success(f"Predicted category: **{label}**")
            st.dataframe(pd.DataFrame({"Category": list(probabilities),
                                       "Probability": [f"{p * 100:.0f}%" for p in probabilities.values()]}),
                         hide_index=True, use_container_width=True)
    st.caption("Experimental output for planning discussions only. Never use it to make decisions about an individual student.")


def page_at_risk():
    page_header("⚠️", "At-Risk Students", "Early warning flags to help students before it is too late")
    df = load_students()
    if df.empty:
        return no_data("at_risk")
    flagged = add_risk_columns(df)
    at_risk = flagged[flagged["Risk Reason"] != "No Current Risk Flag"].copy()
    both = at_risk[at_risk["Risk Reason"] == "Low Marks & Low Attendance"]
    kpi_cards([
        ("🎓", "Students", len(df), "checked", "blue"),
        ("⚠️", "At Risk", len(at_risk), f"{len(at_risk) / len(df) * 100:.0f}% of students", "amber"),
        ("📝", "Low Marks", int((df["marks"] < PASS_MARK).sum()), f"< {PASS_MARK}%", "violet"),
        ("📅", "Low Attendance", int((df["attendance"] < MIN_ATTENDANCE).sum()), f"< {MIN_ATTENDANCE}%", "red"),
    ])
    st.write("")
    if at_risk.empty:
        st.success("No students currently meet the risk criteria. 🎉")
        return
    badges = {"Low Marks & Low Attendance": "🔴 Low Marks & Low Attendance", "Low Marks": "🟠 Low Marks",
              "Low Attendance": "🟡 Low Attendance"}
    at_risk["Risk"] = at_risk["Risk Reason"].map(badges)
    tab_list, tab_both, tab_dept = st.tabs(["📋 Students requiring attention", "🚨 Both risk factors", "🏢 By department"])
    with tab_list:
        reason = st.multiselect("Filter by reason", list(badges.values()))
        shown = at_risk[at_risk["Risk"].isin(reason)] if reason else at_risk
        head, button = st.columns([3, 1])
        head.caption(f"{len(shown)} student(s)")
        button.download_button("⬇️ Download CSV", csv_bytes(shown.drop(columns="Risk")), "at_risk_students.csv",
                               "text/csv", use_container_width=True)
        table(shown, ["student_id", "name", "department", "year", "marks", "attendance", "Risk"])
    with tab_both:
        if both.empty:
            st.success("No student has both low marks and low attendance.")
        else:
            st.error(f"{len(both)} student(s) need individual follow-up first.")
            table(both, ["student_id", "name", "department", "year", "marks", "attendance"])
    with tab_dept:
        by_dept = at_risk.groupby("department")["student_id"].count().reset_index(name="At-risk students")
        with st.container(border=True):
            fig = px.bar(by_dept, x="department", y="At-risk students", color="department",
                         color_discrete_map=DEPT_COLORS, text_auto=True, title="At-risk students by department",
                         labels={"department": ""})
            show(fig, height=320)
    section("💡 Suggested support")
    insight_cards([("info", "📝 <b>Low marks:</b> academic mentoring or extra tutorials."),
                   ("warn", "📅 <b>Low attendance:</b> counselling and a follow-up with the family."),
                   ("warn", "🚨 <b>Both:</b> a personal action plan with a mentor.")])
    st.caption("These are screening flags from entered marks and attendance, not a formal assessment of any student.")


def page_reports():
    page_header("📑", "Reports & Export", "Download clean reports for every part of the college")
    students, faculty, fees, equipment = load_students(), load_faculty(), load_fees(), load_equipment()
    payments = load_payments()
    books, loans, rooms, residents, schedule = load_books(), load_loans(), load_rooms(), load_residents(), load_timetable()
    kpi_cards([
        ("🎓", "Students", len(students), "records", "blue"),
        ("👩‍🏫", "Faculty", len(faculty), "records", "violet"),
        ("💰", "Fee records", len(fees), f"{money(fees['paid'].sum()) if not fees.empty else '₹0'} collected", "teal"),
        ("🧪", "Equipment items", len(equipment), "in inventory", "amber"),
    ])
    st.write("")
    tab_students, tab_faculty, tab_fees, tab_equipment, tab_library, tab_hostel, tab_all = st.tabs(
        ["🎓 Students", "👩‍🏫 Faculty", "💰 Fees", "🧪 Lab Equipment", "📚 Library", "🏠 Hostel", "📦 Complete workbook"])

    with tab_students:
        if students.empty:
            no_data("reports", demo=False, text="Add students first, then come back to export reports.")
        else:
            st.download_button("⬇️ Download all students (CSV)", csv_bytes(students), "college_student_report.csv", "text/csv")
            department = st.selectbox("Department", ["All departments"] + sorted(students["department"].dropna().unique()))
            subset = students if department == "All departments" else students[students["department"] == department]
            st.caption(f"{len(subset)} student(s) · average marks {subset['marks'].mean():.1f}% · "
                       f"average attendance {subset['attendance'].mean():.1f}%")
            if department != "All departments":
                st.download_button("⬇️ Download this department", csv_bytes(subset), f"{department}_report.csv", "text/csv")
            table(subset)
    with tab_faculty:
        if faculty.empty:
            st.info("No faculty records yet.")
        else:
            st.download_button("⬇️ Download faculty (CSV)", csv_bytes(faculty_display(faculty)), "faculty_report.csv", "text/csv")
            table(faculty_display(faculty))
    with tab_fees:
        if fees.empty:
            st.info("No fee records yet.")
        else:
            st.download_button("⬇️ Download fees (CSV)", csv_bytes(fee_display(fees)), "fees_report.csv", "text/csv")
            table(fee_display(fees))
    with tab_equipment:
        if equipment.empty:
            st.info("No equipment records yet.")
        else:
            st.download_button("⬇️ Download equipment (CSV)", csv_bytes(equipment_display(equipment)), "lab_equipment_report.csv", "text/csv")
            table(equipment_display(equipment))
    with tab_library:
        if books.empty:
            st.info("No library records yet.")
        else:
            st.download_button("⬇️ Download loans (CSV)", csv_bytes(loans_display(loans)), "library_loans.csv", "text/csv")
            table(loans_display(loans) if not loans.empty else books_display(books))
    with tab_hostel:
        if rooms.empty:
            st.info("No hostel records yet.")
        else:
            st.download_button("⬇️ Download rooms (CSV)", csv_bytes(rooms_display(rooms)), "hostel_rooms.csv", "text/csv")
            table(rooms_display(rooms))
    with tab_all:
        sheets = {}
        if not students.empty:
            sheets["Students"] = students
            sheets["Department Summary"] = department_summary(students)
        if not faculty.empty:
            sheets["Faculty"] = faculty_display(faculty)
        if not fees.empty:
            sheets["Fees"] = fee_display(fees)
        if not payments.empty:
            sheets["Fee Payments"] = payments
        if not equipment.empty:
            sheets["Lab Equipment"] = equipment_display(equipment)
        if not books.empty:
            sheets["Library Books"] = books_display(books)
        if not loans.empty:
            sheets["Library Loans"] = loans_display(loans)
        if not rooms.empty:
            sheets["Hostel Rooms"] = rooms_display(rooms)
        if not residents.empty:
            sheets["Hostel Residents"] = residents_display(residents)
        if not schedule.empty:
            sheets["Timetable"] = schedule
        if not sheets:
            st.info("There is nothing to export yet.")
        else:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                for sheet_name, frame in sheets.items():
                    frame.to_excel(writer, sheet_name=sheet_name, index=False)
            st.caption("One Excel file with a sheet for each: " + ", ".join(sheets))
            st.download_button("⬇️ Download complete Excel workbook", buffer.getvalue(),
                               f"campus_report_{datetime.now():%Y%m%d}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               type="primary", use_container_width=True)


def page_settings():
    page_header("⚙️", "Admin Settings", "Security, data tools and system information")
    if st.session_state.get("must_change"):
        st.warning("You are using a temporary password. Please set a new one to unlock the other modules.")
    tab_security, tab_data, tab_about = st.tabs(["🔐 Security", "🗄️ Data", "ℹ️ About"])

    with tab_security:
        with st.form("change_admin_password_form", clear_on_submit=True):
            current = st.text_input("Current password", type="password")
            new = st.text_input("New password", type="password", help=f"At least {MIN_PASSWORD_LENGTH} characters")
            confirm = st.text_input("Confirm new password", type="password")
            submitted = st.form_submit_button("Update Password", use_container_width=True)
        if submitted:
            ok, message = change_password(st.session_state.current_admin, current, new, confirm)
            if ok:
                st.session_state.must_change = False
                flash(message)
                st.rerun()
            else:
                st.error(message)

    with tab_data:
        df = load_students()
        demo_count = int(df["student_id"].astype(str).str.startswith("DEMO").sum()) if not df.empty else 0
        size_kb = os.path.getsize(DB_PATH) / 1024 if os.path.exists(DB_PATH) else 0
        kpi_cards([("🎓", "Students", len(df), "records stored", "blue"),
                   ("🧪", "Demo records", demo_count, "IDs starting with DEMO", "violet"),
                   ("💾", "Database size", f"{size_kb:.0f} KB", "students.db", "teal")])
        st.write("")
        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            section("🧪 Demo data", "Sample students, faculty, fees, equipment, library, hostel and timetable.")
            if st.button("✨ Load demo data", use_container_width=True):
                flash(f"Loaded {generate_all_demo_data()} demo students plus faculty, fees, equipment, library, hostel and timetable.")
                st.rerun()
            if st.button("🧹 Remove demo data", use_container_width=True, disabled=demo_count == 0):
                flash(f"Removed {remove_demo_data()} demo students.")
                st.rerun()
        with c2, st.container(border=True):
            section("💾 Backup", "Download a copy of the whole database file.")
            if os.path.exists(DB_PATH):
                with open(DB_PATH, "rb") as handle:
                    st.download_button("⬇️ Download database backup", handle.read(),
                                       f"students_backup_{datetime.now():%Y%m%d}.db", use_container_width=True)

    with tab_about:
        st.write("**Application:** Campus Analytics")
        st.write("**Storage:** local SQLite database")
        st.write("**Signed in as:**", st.session_state.current_admin)
        st.write(f"**Rules:** pass mark {PASS_MARK}% · minimum attendance {MIN_ATTENDANCE}%")
        st.caption("This is a local student project. A real college deployment needs individual accounts, "
                   "role-based permissions, HTTPS, audit logs, backups and a security review.")


# =============================================================================
# 8. LOGIN + APP SHELL
# =============================================================================

# -----------------------------------------------------------------------------
# Campus management modules: Faculty, Fees, Lab Equipment
# -----------------------------------------------------------------------------

def option_index(options, value, default=0):
    return options.index(value) if value in options else default


def to_date(value):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return date.today()


def faculty_fields(prefix, d=None):
    d = d or {}
    a, b = st.columns(2)
    name = a.text_input("Full Name *", value=d.get("name", ""), key=f"{prefix}_name")
    department = b.selectbox("Department", DEPARTMENTS, index=option_index(DEPARTMENTS, d.get("department")), key=f"{prefix}_dept")
    a, b = st.columns(2)
    designation = a.selectbox("Designation", DESIGNATIONS, index=option_index(DESIGNATIONS, d.get("designation")), key=f"{prefix}_desig")
    qualification = b.text_input("Qualification", value=d.get("qualification") or "", key=f"{prefix}_qual", placeholder="e.g. Ph.D, M.E")
    a, b = st.columns(2)
    email = a.text_input("Email", value=d.get("email") or "", key=f"{prefix}_email", placeholder="name@college.edu")
    phone = b.text_input("Phone Number", value=d.get("phone") or "", key=f"{prefix}_phone", placeholder="10 digits")
    a, b, c = st.columns(3)
    experience = a.number_input("Experience (years)", 0.0, 50.0, float(d.get("experience") or 0.0), step=0.5, key=f"{prefix}_exp")
    status = b.selectbox("Status", FACULTY_STATUS, index=option_index(FACULTY_STATUS, d.get("status")), key=f"{prefix}_status")
    subjects = c.text_input("Subjects handled", value=d.get("subjects") or "", key=f"{prefix}_subjects")
    return name, department, designation, qualification, email, phone, experience, subjects, status


def faculty_display(frame):
    return frame.rename(columns={
        "faculty_id": "ID", "name": "Name", "department": "Dept", "designation": "Designation",
        "qualification": "Qualification", "email": "Email", "phone": "Phone",
        "experience": "Experience (yrs)", "subjects": "Subjects", "status": "Status"})


def page_faculty():
    page_header("👩‍🏫", "Faculty", "Teaching staff directory, status and student-faculty ratio")
    faculty = load_faculty()
    tab_over, tab_dir, tab_add, tab_edit, tab_delete = st.tabs(
        ["📊 Overview", "📋 Directory", "➕ Add Faculty", "✏️ Edit", "🗑️ Delete"])

    with tab_over:
        if faculty.empty:
            no_data("faculty", "No faculty records yet", "Add faculty members in the Add Faculty tab, or load demo data.")
        else:
            students = load_students(["student_id", "department"])
            active = int((faculty["status"] == "Active").sum())
            kpi_cards([
                ("👩‍🏫", "Faculty", len(faculty), f"{active} active", "violet"),
                ("🏢", "Departments", faculty["department"].nunique(), "with faculty", "blue"),
                ("🎓", "Avg Experience", f"{faculty['experience'].mean():.1f} yrs", "across all faculty", "teal"),
                ("🌴", "On Leave", int((faculty["status"] == "On Leave").sum()), "currently away", "amber"),
            ])
            st.write("")
            left, right = st.columns(2)
            with left, st.container(border=True):
                per_dept = faculty.groupby("department")["faculty_id"].count().reset_index(name="Faculty")
                fig = px.bar(per_dept, x="department", y="Faculty", color="department", color_discrete_map=DEPT_COLORS,
                             text_auto=True, title="Faculty per department", labels={"department": ""})
                show(fig)
            with right, st.container(border=True):
                designations = faculty["designation"].value_counts().reset_index()
                designations.columns = ["Designation", "Faculty"]
                fig = px.pie(designations, names="Designation", values="Faculty", hole=0.55, title="Designations")
                show(fig, legend=True)
            if not students.empty:
                with st.container(border=True):
                    ratio = (students.groupby("department")["student_id"].count().rename("Students").to_frame()
                             .join(faculty.groupby("department")["faculty_id"].count().rename("Faculty"), how="left")
                             .fillna(0).reset_index())
                    covered = ratio[ratio["Faculty"] > 0].copy()
                    covered["Students per faculty"] = (covered["Students"] / covered["Faculty"]).round(1)
                    fig = px.bar(covered, x="department", y="Students per faculty", color="department",
                                 color_discrete_map=DEPT_COLORS, text_auto=True, title="Students per faculty member",
                                 labels={"department": ""})
                    fig.add_hline(y=STUDENTS_PER_FACULTY_REFERENCE, line_dash="dot", line_color="#EF4444",
                                  annotation_text=f"Reference: {STUDENTS_PER_FACULTY_REFERENCE} students per faculty")
                    show(fig)
                    missing = ratio[(ratio["Faculty"] == 0) & (ratio["Students"] > 0)]["department"].tolist()
                    if missing:
                        st.warning("Departments with students but no faculty: " + ", ".join(missing))

    with tab_dir:
        if faculty.empty:
            st.info("No faculty records yet.")
        else:
            with st.container(border=True):
                a, b, c, d = st.columns([2, 1.2, 1.2, 1])
                search = a.text_input("🔍 Search", placeholder="Name, ID or subject", key="fac_search")
                dept_filter = b.multiselect("Department", sorted(faculty["department"].unique()), key="fac_dept")
                desig_filter = c.multiselect("Designation", DESIGNATIONS, key="fac_desig")
                status_filter = d.multiselect("Status", FACULTY_STATUS, key="fac_status")
            view = faculty
            if search:
                view = view[view["name"].str.contains(search, case=False, na=False, regex=False)
                            | view["faculty_id"].str.contains(search, case=False, na=False, regex=False)
                            | view["subjects"].fillna("").str.contains(search, case=False, regex=False)]
            if dept_filter:
                view = view[view["department"].isin(dept_filter)]
            if desig_filter:
                view = view[view["designation"].isin(desig_filter)]
            if status_filter:
                view = view[view["status"].isin(status_filter)]
            head, button = st.columns([3, 1])
            head.caption(f"Showing **{len(view)}** of **{len(faculty)}** faculty members")
            button.download_button("⬇️ Download CSV", csv_bytes(view), "faculty.csv", "text/csv", use_container_width=True)
            table(faculty_display(view))

    with tab_add:
        with st.form("add_faculty_form", clear_on_submit=True):
            faculty_id = st.text_input("Faculty ID *", placeholder="e.g. FAC101")
            fields = faculty_fields("addfac")
            submitted = st.form_submit_button("💾 Save Faculty", use_container_width=True)
        if submitted:
            ok, message = add_faculty(faculty_id, *fields)
            (st.success if ok else st.error)(message)
            if ok:
                st.toast("Faculty added", icon="✅")

    with tab_edit:
        if faculty.empty:
            st.info("No faculty records available to edit.")
        else:
            names = dict(zip(faculty["faculty_id"], faculty["name"]))
            selected = st.selectbox("Choose a faculty member", list(names), format_func=lambda f: f"{f}  —  {names[f]}", key="fac_edit_select")
            current = faculty[faculty["faculty_id"] == selected].iloc[0].to_dict()
            with st.form(f"edit_faculty_{selected}"):
                fields = faculty_fields(f"editfac_{selected}", current)
                submitted = st.form_submit_button("💾 Update Faculty", use_container_width=True)
            if submitted:
                ok, message = update_faculty(selected, *fields)
                if ok:
                    flash(message)
                    st.rerun()
                else:
                    st.error(message)

    with tab_delete:
        if faculty.empty:
            st.info("No faculty records available to delete.")
        else:
            names = dict(zip(faculty["faculty_id"], faculty["name"]))
            selected = st.selectbox("Choose a faculty member to delete", list(names),
                                    format_func=lambda f: f"{f}  —  {names[f]}", key="fac_delete_select")
            table(faculty_display(faculty[faculty["faculty_id"] == selected]))
            st.warning("Deleting a faculty record cannot be undone.")
            confirm = st.checkbox("I understand and want to delete this record", key=f"fac_confirm_{selected}")
            if st.button("🗑️ Delete Faculty", type="primary", disabled=not confirm, key="fac_delete_btn"):
                delete_faculty(selected)
                flash("Faculty record deleted.")
                st.rerun()


FEE_STATUS_COLORS = {"Paid": "#14B8A6", "Partial": "#2563EB", "Pending": "#F59E0B", "Overdue": "#EF4444"}


def fee_display(frame):
    renamed = frame.rename(columns={
        "fee_id": "Fee ID", "student_id": "ID", "student_name": "Name", "department": "Dept", "fee_type": "Fee Type",
        "amount": "Amount (₹)", "paid": "Paid (₹)", "balance": "Balance (₹)", "due_date": "Due Date", "status": "Status"})
    return renamed[["Fee ID", "ID", "Name", "Dept", "Fee Type", "Amount (₹)", "Paid (₹)", "Balance (₹)", "Due Date", "Status"]]


def page_fees():
    page_header("💰", "Fees", "Fee structure, payments, balances and defaulters")
    fees = load_fees()
    tab_over, tab_records, tab_assign, tab_pay, tab_def, tab_receipts = st.tabs(
        ["📊 Overview", "🧾 Fee Records", "➕ Assign Fee", "💳 Record Payment", "🚨 Defaulters", "🖨️ Receipts"])

    with tab_over:
        if fees.empty:
            no_data("fees", "No fee records yet", "Assign fees in the Assign Fee tab (needs students), or load demo data.")
        else:
            billed, collected = fees["amount"].sum(), fees["paid"].sum()
            pending = fees["balance"].sum()
            overdue_amount = fees.loc[fees["status"] == "Overdue", "balance"].sum()
            rate = collected / billed * 100 if billed else 0
            kpi_cards([
                ("🧾", "Total Billed", money(billed), f"{len(fees)} fee records", "blue"),
                ("✅", "Collected", money(collected), f"{rate:.0f}% collection rate", "teal"),
                ("⏳", "Pending", money(pending), "still to be collected", "amber"),
                ("🚨", "Overdue", money(overdue_amount), "past the due date", "red"),
            ])
            st.write("")
            left, right = st.columns(2)
            with left, st.container(border=True):
                by_type = fees.groupby("fee_type")[["paid", "balance"]].sum().reset_index()
                long = by_type.melt(id_vars="fee_type", var_name="Type", value_name="Amount")
                long["Type"] = long["Type"].map({"paid": "Collected", "balance": "Pending"})
                fig = px.bar(long, x="fee_type", y="Amount", color="Type", barmode="stack",
                             color_discrete_map={"Collected": "#14B8A6", "Pending": "#F59E0B"},
                             title="Collected vs pending by fee type", labels={"fee_type": "", "Amount": "Amount (₹)"})
                show(fig, legend=True)
            with right, st.container(border=True):
                statuses = fees["status"].value_counts().reset_index()
                statuses.columns = ["Status", "Fee records"]
                fig = px.pie(statuses, names="Status", values="Fee records", hole=0.55, color="Status",
                             color_discrete_map=FEE_STATUS_COLORS, title="Fee status")
                show(fig, legend=True)
            left, right = st.columns(2)
            with left, st.container(border=True):
                by_dept = fees[fees["balance"] > 0].groupby("department")["balance"].sum().reset_index()
                fig = px.bar(by_dept, x="department", y="balance", color="department", color_discrete_map=DEPT_COLORS,
                             title="Pending amount by department", labels={"department": "", "balance": "Pending (₹)"})
                show(fig)
            with right, st.container(border=True):
                payments = load_payments()
                if payments.empty:
                    st.info("No payments recorded yet.")
                else:
                    payments["Month"] = payments["paid_on"].str[:7]
                    monthly = payments.groupby("Month")["amount"].sum().reset_index()
                    fig = px.bar(monthly, x="Month", y="amount", title="Collections by month", labels={"amount": "Collected (₹)"})
                    fig.update_traces(marker_color="#2563EB", marker_line_width=0)
                    show(fig)

    with tab_records:
        if fees.empty:
            st.info("No fee records yet.")
        else:
            with st.container(border=True):
                a, b, c = st.columns(3)
                status_filter = a.multiselect("Status", ["Paid", "Partial", "Pending", "Overdue"], key="fee_status_filter")
                type_filter = b.multiselect("Fee type", FEE_TYPES, key="fee_type_filter")
                search = c.text_input("🔍 Student ID or name", key="fee_search")
            view = fees
            if status_filter:
                view = view[view["status"].isin(status_filter)]
            if type_filter:
                view = view[view["fee_type"].isin(type_filter)]
            if search:
                view = view[view["student_id"].str.contains(search, case=False, na=False, regex=False)
                            | view["student_name"].str.contains(search, case=False, na=False, regex=False)]
            head, button = st.columns([3, 1])
            head.caption(f"Showing **{len(view)}** of **{len(fees)}** fee records")
            button.download_button("⬇️ Download CSV", csv_bytes(fee_display(view)), "fee_records.csv", "text/csv", use_container_width=True)
            table(fee_display(view))
            with st.expander("🗑️ Delete a fee record"):
                options = list(fees["fee_id"])
                chosen = st.selectbox("Fee ID", options, key="fee_delete_select")
                confirm = st.checkbox("Delete this fee and all its payments", key=f"fee_confirm_{chosen}")
                if st.button("Delete fee record", disabled=not confirm, key="fee_delete_btn"):
                    delete_fee(chosen)
                    flash("Fee record deleted.")
                    st.rerun()

    with tab_assign:
        students = load_students(["student_id", "name", "department", "year"])
        if students.empty:
            st.info("Add students first, then assign fees to them.")
        else:
            mode = st.radio("Who is this fee for?", ["One student", "A group of students"], horizontal=True, key="fee_assign_mode")
            a, b, c = st.columns(3)
            fee_type = a.selectbox("Fee type", FEE_TYPES, key="fee_assign_type")
            amount = b.number_input("Amount (₹)", min_value=0.0, value=0.0, step=500.0, key="fee_assign_amount")
            due = c.date_input("Due date", value=date.today() + timedelta(days=30), key="fee_assign_due")
            if mode == "One student":
                names = dict(zip(students["student_id"].astype(str), students["name"]))
                chosen = st.selectbox("Student", list(names), format_func=lambda sid: f"{sid}  —  {names[sid]}", key="fee_assign_student")
                targets = [chosen]
            else:
                a, b = st.columns(2)
                dept_choice = a.selectbox("Department", ["All departments"] + DEPARTMENTS, key="fee_assign_dept")
                year_choice = b.selectbox("Year", ["All years"] + YEARS, key="fee_assign_year")
                group = students
                if dept_choice != "All departments":
                    group = group[group["department"] == dept_choice]
                if year_choice != "All years":
                    group = group[group["year"] == year_choice]
                targets = group["student_id"].astype(str).tolist()
                st.info(f"This will create a {fee_type} fee for **{len(targets)}** student(s).")
            if st.button("💾 Create fee", type="primary", disabled=amount <= 0 or not targets, key="fee_assign_btn"):
                created, skipped = assign_fee(targets, fee_type, amount, due.isoformat())
                message = f"Created {created} fee record(s)."
                if skipped:
                    message += f" Skipped {skipped} that already exist for the same fee type and due date."
                flash(message, "success" if created else "warning")
                st.rerun()

    with tab_pay:
        last_id = st.session_state.get("last_payment_id")
        last = payment_receipt(last_id) if last_id else None
        if last:
            box, button = st.columns([3, 1])
            box.success(f"Last payment saved: **{last['receipt_no']}** · {money(last['amount'])} from {last['name']}")
            button.download_button("🧾 Download receipt", receipt_html(last), f"{last['receipt_no']}.html", "text/html",
                                   use_container_width=True, key="last_receipt_download")
        open_fees = fees[fees["balance"] > 0] if not fees.empty else fees
        if open_fees.empty:
            st.success("Every fee is fully paid. 🎉" if not fees.empty else "No fee records yet.")
        else:
            labels = {int(r.fee_id): f"#{int(r.fee_id)} · {r.student_id} {r.student_name} · {r.fee_type} · balance {money(r.balance)}"
                      for r in open_fees.itertuples()}
            chosen = st.selectbox("Choose the fee being paid", list(labels), format_func=lambda i: labels[i], key="pay_select")
            row = open_fees[open_fees["fee_id"] == chosen].iloc[0]
            kpi_cards([("🧾", "Fee amount", money(row["amount"]), row["fee_type"], "blue"),
                       ("✅", "Paid so far", money(row["paid"]), f"due {row['due_date']}", "teal"),
                       ("⏳", "Balance", money(row["balance"]), row["status"], "red" if row["status"] == "Overdue" else "amber")])
            st.write("")
            with st.form(f"payment_form_{chosen}"):
                a, b, c = st.columns(3)
                amount = a.number_input("Amount received (₹)", min_value=0.01, max_value=float(row["balance"]),
                                        value=float(row["balance"]), step=100.0)
                mode = b.selectbox("Payment mode", PAYMENT_MODES)
                paid_on = c.date_input("Payment date", value=date.today())
                submitted = st.form_submit_button("💳 Record payment", use_container_width=True)
            if submitted:
                ok, message = record_payment(chosen, amount, mode, paid_on.isoformat())
                if ok:
                    st.session_state["last_payment_id"] = int(load_payments()["payment_id"].max())
                    flash(message)
                    st.rerun()
                else:
                    st.error(message)
            history = load_payments()
            history = history[history["fee_id"] == chosen]
            if not history.empty:
                section("Payment history for this fee")
                st.dataframe(history.rename(columns={"payment_id": "Payment", "amount": "Amount (₹)", "paid_on": "Date",
                                                     "mode": "Mode"})[["Payment", "Amount (₹)", "Date", "Mode"]],
                             use_container_width=True, hide_index=True)

    with tab_def:
        overdue = fees[fees["status"] == "Overdue"] if not fees.empty else fees
        if overdue.empty:
            st.success("No overdue fees right now. 🎉" if not fees.empty else "No fee records yet.")
        else:
            today = pd.Timestamp(date.today())
            grouped = overdue.groupby(["student_id", "student_name", "department"]).agg(
                items=("fee_id", "count"), balance=("balance", "sum"), oldest=("due_date", "min")).reset_index()
            grouped["days"] = (today - pd.to_datetime(grouped["oldest"])).dt.days
            grouped = grouped.sort_values("balance", ascending=False)
            st.error(f"{len(grouped)} student(s) have overdue fees totalling {money(grouped['balance'].sum())}.")
            shown = grouped.rename(columns={"student_id": "ID", "student_name": "Name", "department": "Dept",
                                            "items": "Overdue Items", "balance": "Overdue Amount (₹)",
                                            "oldest": "Oldest Due Date", "days": "Days Overdue"})
            st.download_button("⬇️ Download defaulter list (CSV)", csv_bytes(shown), "fee_defaulters.csv", "text/csv")
            table(shown)

    with tab_receipts:
        render_receipts(fees)


def render_receipts(fees):
    payments = load_payments()
    if payments.empty:
        st.info("No payments yet. A receipt is created automatically for every payment you record.")
        return
    names = dict(zip(fees["student_id"], fees["student_name"])) if not fees.empty else {}
    search = st.text_input("🔍 Find a receipt", placeholder="Student ID, name or receipt number", key="receipt_search")
    payments = payments.assign(name=payments["student_id"].map(names).fillna("(deleted)"))
    payments["label"] = [f"RCP-{int(r.payment_id):05d} · {r.student_id} {r.name} · {r.fee_type} · {money(r.amount)} · {r.paid_on}"
                         for r in payments.itertuples()]
    if search:
        payments = payments[payments["label"].str.contains(search, case=False, regex=False)]
    if payments.empty:
        st.info("No receipts match your search.")
        return
    labels = dict(zip(payments["payment_id"].astype(int), payments["label"]))
    chosen = st.selectbox("Receipt", list(labels), format_func=lambda i: labels[i], key="receipt_select")
    data = payment_receipt(chosen)
    left, right = st.columns([3, 2])
    with left:
        rows = [("Student", f"{data['name']} ({data['student_id']})"), ("Department", f"{data['department']} · Year {data['year']}"),
                ("Fee type", data["fee_type"]), ("Total fee", money(data["fee_amount"])), ("Date", data["paid_on"]),
                ("Mode", data["mode"] or "-"), ("Balance after", money(data["balance_after"]))]
        st.markdown('<div class="receipt"><div class="receipt-head"><span class="receipt-title">🎓 Campus Analytics</span>'
                    f'<span class="receipt-no">{esc(data["receipt_no"])}</span></div>'
                    + "".join(f'<div class="receipt-row"><span>{esc(k)}</span><span>{esc(v)}</span></div>' for k, v in rows)
                    + f'<div class="receipt-total">Amount received: {esc(money(data["amount"]))}</div></div>', unsafe_allow_html=True)
    with right, st.container(border=True):
        section("🖨️ Print or save")
        st.caption("Download the receipt, open it in your browser, then press Ctrl+P to print or save as PDF.")
        st.download_button("⬇️ Download receipt (HTML)", receipt_html(data), f"{data['receipt_no']}.html", "text/html",
                           use_container_width=True, type="primary", key="receipt_download")


def equipment_fields(prefix, d=None):
    d = d or {}
    a, b = st.columns(2)
    name = a.text_input("Item Name *", value=d.get("name", ""), key=f"{prefix}_name")
    category = b.selectbox("Category", EQUIPMENT_CATEGORIES, index=option_index(EQUIPMENT_CATEGORIES, d.get("category")), key=f"{prefix}_cat")
    a, b = st.columns(2)
    lab = a.selectbox("Lab / Location", LABS, index=option_index(LABS, d.get("lab")), key=f"{prefix}_lab")
    condition = b.selectbox("Condition", CONDITIONS, index=option_index(CONDITIONS, d.get("condition")), key=f"{prefix}_cond")
    a, b, c = st.columns(3)
    quantity = a.number_input("Quantity (units)", 1, 10000, int(d.get("quantity") or 1), key=f"{prefix}_qty")
    unit_cost = b.number_input("Cost per unit (₹)", 0.0, 100000000.0, float(d.get("unit_cost") or 0.0), step=500.0, key=f"{prefix}_cost")
    purchase_date = c.date_input("Purchase date", value=to_date(d.get("purchase_date")), key=f"{prefix}_date")
    return name, category, lab, quantity, unit_cost, condition, purchase_date.isoformat()


def equipment_display(frame):
    renamed = frame.rename(columns={
        "item_id": "ID", "name": "Item", "category": "Category", "lab": "Lab", "quantity": "Units", "issued": "Issued",
        "available": "Available", "stock": "Stock", "condition": "Condition", "unit_cost": "Unit Cost (₹)",
        "value": "Value (₹)", "purchase_date": "Purchased"})
    return renamed[["ID", "Item", "Category", "Lab", "Units", "Issued", "Available", "Stock", "Condition",
                    "Unit Cost (₹)", "Value (₹)", "Purchased"]]


def page_equipment():
    page_header("🧪", "Lab Equipment", "Inventory, condition, issue and return tracking")
    equipment = load_equipment()
    tab_over, tab_inv, tab_add, tab_edit, tab_issue = st.tabs(
        ["📊 Overview", "📦 Inventory", "➕ Add Item", "✏️ Edit / Delete", "🔄 Issue & Return"])

    with tab_over:
        if equipment.empty:
            no_data("equipment", "No lab equipment yet", "Add items in the Add Item tab, or load demo data.")
        else:
            attention = equipment[equipment["condition"] != "Good"]
            kpi_cards([
                ("📦", "Item Types", len(equipment), f"{equipment['lab'].nunique()} lab(s)", "blue"),
                ("🔢", "Total Units", int(equipment["quantity"].sum()), f"{int(equipment['issued'].sum())} issued out", "violet"),
                ("✅", "Available Now", int(equipment["available"].sum()), "ready to issue", "teal"),
                ("🛠️", "Need Attention", len(attention), "repair or out of service", "red" if len(attention) else "teal"),
                ("💎", "Asset Value", money(equipment["value"].sum()), "at purchase cost", "amber"),
            ])
            st.write("")
            left, right = st.columns(2)
            with left, st.container(border=True):
                by_lab = equipment.groupby("lab")[["available", "issued"]].sum().reset_index()
                long = by_lab.melt(id_vars="lab", var_name="Status", value_name="Units")
                long["Status"] = long["Status"].map({"available": "Available", "issued": "Issued"})
                fig = px.bar(long, x="lab", y="Units", color="Status", barmode="stack",
                             color_discrete_map={"Available": "#14B8A6", "Issued": "#2563EB"},
                             title="Units by lab", labels={"lab": ""})
                show(fig, legend=True)
            with right, st.container(border=True):
                conditions = equipment.groupby("condition")["quantity"].sum().reset_index()
                fig = px.pie(conditions, names="condition", values="quantity", hole=0.55, color="condition",
                             color_discrete_map={"Good": "#14B8A6", "Needs Repair": "#F59E0B", "Out of Service": "#EF4444"},
                             title="Units by condition")
                show(fig, legend=True)
            with st.container(border=True):
                by_cat = equipment.groupby("category")["value"].sum().reset_index()
                fig = px.bar(by_cat, x="category", y="value", title="Asset value by category",
                             labels={"category": "", "value": "Value (₹)"})
                fig.update_traces(marker_color="#2563EB", marker_line_width=0)
                show(fig, height=320)
            alerts = equipment[equipment["stock"] != "In stock"]
            if not alerts.empty:
                section("⚠️ Stock alerts", "Items that are low or fully issued")
                table(equipment_display(alerts)[["ID", "Item", "Lab", "Units", "Available", "Stock", "Condition"]])
            if not attention.empty:
                section("🛠️ Items needing attention")
                table(equipment_display(attention)[["ID", "Item", "Lab", "Units", "Condition"]])

    with tab_inv:
        if equipment.empty:
            st.info("No equipment records yet.")
        else:
            with st.container(border=True):
                a, b, c, d = st.columns([2, 1.2, 1.2, 1.2])
                search = a.text_input("🔍 Search", placeholder="Item name or ID", key="eq_search")
                lab_filter = b.multiselect("Lab", sorted(equipment["lab"].unique()), key="eq_lab")
                cat_filter = c.multiselect("Category", sorted(equipment["category"].unique()), key="eq_cat")
                cond_filter = d.multiselect("Condition", CONDITIONS, key="eq_cond")
            view = equipment
            if search:
                view = view[view["name"].str.contains(search, case=False, na=False, regex=False)
                            | view["item_id"].str.contains(search, case=False, na=False, regex=False)]
            if lab_filter:
                view = view[view["lab"].isin(lab_filter)]
            if cat_filter:
                view = view[view["category"].isin(cat_filter)]
            if cond_filter:
                view = view[view["condition"].isin(cond_filter)]
            head, button = st.columns([3, 1])
            head.caption(f"Showing **{len(view)}** of **{len(equipment)}** items")
            button.download_button("⬇️ Download CSV", csv_bytes(equipment_display(view)), "lab_equipment.csv", "text/csv", use_container_width=True)
            table(equipment_display(view))

    with tab_add:
        with st.form("add_equipment_form", clear_on_submit=True):
            item_id = st.text_input("Item ID *", placeholder="e.g. LAB-OSC-001")
            fields = equipment_fields("addeq")
            submitted = st.form_submit_button("💾 Save Item", use_container_width=True)
        if submitted:
            ok, message = add_equipment(item_id, *fields)
            (st.success if ok else st.error)(message)
            if ok:
                st.toast("Equipment added", icon="✅")

    with tab_edit:
        if equipment.empty:
            st.info("No equipment records available.")
        else:
            names = dict(zip(equipment["item_id"], equipment["name"]))
            selected = st.selectbox("Choose an item", list(names), format_func=lambda i: f"{i}  —  {names[i]}", key="eq_edit_select")
            current = equipment[equipment["item_id"] == selected].iloc[0].to_dict()
            with st.form(f"edit_equipment_{selected}"):
                fields = equipment_fields(f"editeq_{selected}", current)
                submitted = st.form_submit_button("💾 Update Item", use_container_width=True)
            if submitted:
                ok, message = update_equipment(selected, *fields)
                if ok:
                    flash(message)
                    st.rerun()
                else:
                    st.error(message)
            with st.expander("🗑️ Delete this item"):
                st.warning("This also deletes the item's issue history and cannot be undone.")
                confirm = st.checkbox("I understand and want to delete this item", key=f"eq_confirm_{selected}")
                if st.button("Delete item", type="primary", disabled=not confirm, key="eq_delete_btn"):
                    delete_equipment(selected)
                    flash("Equipment item deleted.")
                    st.rerun()

    with tab_issue:
        left, right = st.columns(2)
        with left, st.container(border=True):
            section("📤 Issue an item")
            ready = equipment[(equipment["available"] > 0) & (equipment["condition"] != "Out of Service")] if not equipment.empty else equipment
            if ready.empty:
                st.info("No items are available to issue.")
            else:
                labels = {r.item_id: f"{r.item_id} · {r.name} ({int(r.available)} available)" for r in ready.itertuples()}
                chosen = st.selectbox("Item", list(labels), format_func=lambda i: labels[i], key="issue_item")
                max_units = int(ready[ready["item_id"] == chosen].iloc[0]["available"])
                with st.form(f"issue_form_{chosen}"):
                    issued_to = st.text_input("Issued to", placeholder="Student or faculty name")
                    quantity = st.number_input("Units", 1, max_units, 1)
                    issued_on = st.date_input("Issue date", value=date.today())
                    submitted = st.form_submit_button("Issue item", use_container_width=True)
                if submitted:
                    ok, message = issue_equipment(chosen, issued_to, quantity, issued_on.isoformat())
                    if ok:
                        flash(message)
                        st.rerun()
                    else:
                        st.error(message)
        with right, st.container(border=True):
            section("📥 Return an item")
            open_issues = load_open_issues()
            if open_issues.empty:
                st.success("Nothing is currently issued out.")
            else:
                labels = {int(r.issue_id): f"#{int(r.issue_id)} · {r.item_name} × {int(r.quantity)} → {r.issued_to}"
                          for r in open_issues.itertuples()}
                chosen_issue = st.selectbox("Issued item", list(labels), format_func=lambda i: labels[i], key="return_select")
                returned_on = st.date_input("Return date", value=date.today(), key="return_date")
                if st.button("Mark as returned", type="primary", use_container_width=True, key="return_btn"):
                    ok, message = return_equipment(chosen_issue, returned_on.isoformat())
                    flash(message)
                    st.rerun()
        open_issues = load_open_issues()
        if not open_issues.empty:
            section("Currently issued", f"{len(open_issues)} open issue(s)")
            st.dataframe(open_issues.rename(columns={"issue_id": "Issue", "item_id": "Item ID", "item_name": "Item",
                                                     "issued_to": "Issued to", "quantity": "Units", "issued_on": "Issued on"}),
                         use_container_width=True, hide_index=True)


# -----------------------------------------------------------------------------
# Library, Hostel and Timetable
# -----------------------------------------------------------------------------

def loans_display(frame):
    shown = frame.assign(returned_on=frame["returned_on"].fillna("-")).rename(columns={
        "loan_id": "Loan", "book_id": "Book ID", "title": "Title", "borrower_id": "Borrower ID", "borrower_name": "Borrower",
        "borrower_type": "Type", "issued_on": "Issued", "due_on": "Due", "returned_on": "Returned", "renewals": "Renewals",
        "fine": "Fine (₹)", "status": "Status", "days_late": "Days Late"})
    return shown[["Loan", "Book ID", "Title", "Borrower ID", "Borrower", "Type", "Issued", "Due", "Returned",
                  "Renewals", "Days Late", "Fine (₹)", "Status"]]


def books_display(frame):
    renamed = frame.rename(columns={"book_id": "ID", "title": "Title", "author": "Author", "category": "Category",
                                    "copies": "Copies", "on_loan": "On Loan", "available": "Available", "stock": "Stock"})
    return renamed[["ID", "Title", "Author", "Category", "Copies", "On Loan", "Available", "Stock"]]


def page_library():
    page_header("📚", "Library", f"Issue, return and renew books · fine ₹{FINE_PER_DAY}/day · {MAX_RENEWALS} renewals allowed")
    books, loans = load_books(), load_loans()
    open_loans = loans[loans["returned_on"].isna()] if not loans.empty else loans
    tab_over, tab_ret, tab_issue, tab_cat, tab_manage, tab_hist = st.tabs(
        ["📊 Overview", "🔁 Return & Renew", "📤 Issue Book", "📖 Catalogue", "➕ Add / Edit Books", "🕘 Loan History"])

    with tab_over:
        if books.empty:
            no_data("library", "No books yet", "Add books in the Add / Edit Books tab, or load demo data.")
        else:
            overdue = open_loans[open_loans["status"] == "Overdue"] if not open_loans.empty else open_loans
            collected = float(loans.loc[loans["returned_on"].notna(), "fine"].sum()) if not loans.empty else 0.0
            kpi_cards([
                ("📚", "Titles", len(books), f"{int(books['copies'].sum())} copies in total", "blue"),
                ("✅", "Available", int(books["available"].sum()), "copies on the shelf", "teal"),
                ("📤", "On Loan", len(open_loans), f"{int((open_loans['status'] == 'Due Soon').sum()) if not open_loans.empty else 0} due soon", "violet"),
                ("⏰", "Overdue", len(overdue), "books past the due date", "red" if len(overdue) else "teal"),
                ("💸", "Fines Accruing", money(overdue["fine"].sum() if not overdue.empty else 0), f"{money(collected)} already charged", "amber"),
            ])
            st.write("")
            left, right = st.columns(2)
            with left, st.container(border=True):
                by_cat = books.groupby("category")["copies"].sum().reset_index()
                fig = px.bar(by_cat, x="category", y="copies", title="Copies by category", labels={"category": "", "copies": "Copies"})
                fig.update_traces(marker_color="#2563EB", marker_line_width=0)
                show(fig)
            with right, st.container(border=True):
                if loans.empty:
                    st.info("No loans recorded yet.")
                else:
                    status = loans["status"].value_counts().reset_index()
                    status.columns = ["Status", "Loans"]
                    fig = px.pie(status, names="Status", values="Loans", hole=0.55, color="Status", title="Loan status",
                                 color_discrete_map={"Returned": "#14B8A6", "Issued": "#2563EB", "Due Soon": "#F59E0B", "Overdue": "#EF4444"})
                    show(fig, legend=True)
            if not loans.empty:
                with st.container(border=True):
                    popular = loans.groupby("title")["loan_id"].count().sort_values(ascending=False).head(8).reset_index(name="Times borrowed")
                    fig = px.bar(popular, x="Times borrowed", y="title", orientation="h", title="Most borrowed books", labels={"title": ""})
                    fig.update_traces(marker_color="#14B8A6", marker_line_width=0)
                    fig.update_yaxes(categoryorder="total ascending")
                    show(fig, height=340)
            if not overdue.empty:
                section("⏰ Overdue books", "Return these and collect the fine")
                table(loans_display(overdue)[["Loan", "Title", "Borrower", "Type", "Due", "Days Late", "Fine (₹)", "Status"]])
            soon = open_loans[open_loans["status"] == "Due Soon"] if not open_loans.empty else open_loans
            if not soon.empty:
                section("🔔 Due within 3 days")
                table(loans_display(soon)[["Loan", "Title", "Borrower", "Type", "Due", "Renewals", "Status"]])

    with tab_ret:
        if open_loans.empty:
            st.success("No books are currently on loan." if not books.empty else "Add books first.")
        else:
            search = st.text_input("🔍 Find a loan", placeholder="Borrower name, ID or book title", key="lib_find")
            pool = open_loans
            if search:
                pool = pool[pool["title"].str.contains(search, case=False, na=False, regex=False)
                            | pool["borrower_name"].str.contains(search, case=False, na=False, regex=False)
                            | pool["borrower_id"].str.contains(search, case=False, na=False, regex=False)]
            if pool.empty:
                st.info("No open loans match your search.")
            else:
                labels = {int(r.loan_id): f"#{int(r.loan_id)} · {r.title} → {r.borrower_name} ({r.borrower_type}) · due {r.due_on} · {r.status}"
                          for r in pool.itertuples()}
                chosen = st.selectbox("Open loan", list(labels), format_func=lambda i: labels[i], key="lib_loan_select")
                row = pool[pool["loan_id"] == chosen].iloc[0]
                overdue_now = row["status"] == "Overdue"
                kpi_cards([
                    ("📅", "Due date", row["due_on"], row["status"], "red" if overdue_now else "blue"),
                    ("🔁", "Renewals used", f"{int(row['renewals'])} / {MAX_RENEWALS}", "extends by "
                     f"{FACULTY_LOAN_DAYS if row['borrower_type'] == 'Faculty' else LOAN_DAYS} days", "violet"),
                    ("💸", "Fine if returned today", money(row["fine"]), f"{int(row['days_late'])} day(s) late", "red" if row["fine"] else "teal"),
                ])
                st.write("")
                left, right = st.columns(2)
                can_renew = (not overdue_now) and int(row["renewals"]) < MAX_RENEWALS
                with left, st.container(border=True):
                    section("🔁 Renew")
                    if overdue_now:
                        st.warning("Overdue books cannot be renewed. Return the book and collect the fine.")
                    elif int(row["renewals"]) >= MAX_RENEWALS:
                        st.warning(f"Already renewed {MAX_RENEWALS} times, which is the maximum.")
                    else:
                        st.caption("Extends the due date from its current date.")
                    if st.button("🔁 Renew this book", use_container_width=True, disabled=not can_renew, key=f"renew_{chosen}"):
                        ok, message = renew_book(chosen)
                        flash(message, "success" if ok else "error")
                        st.rerun()
                with right, st.container(border=True):
                    section("✅ Return")
                    returned_on = st.date_input("Return date", value=date.today(), key=f"ret_date_{chosen}")
                    fine = fine_for(row["due_on"], returned_on)
                    if fine:
                        st.warning(f"Late return. Fine to collect: **{money(fine)}**.")
                    if st.button("✅ Mark as returned", type="primary", use_container_width=True, key=f"return_{chosen}"):
                        ok, message, _ = return_book(chosen, returned_on.isoformat())
                        flash(message, "warning" if fine else "success")
                        st.rerun()

    with tab_issue:
        ready = books[books["available"] > 0] if not books.empty else books
        if ready.empty:
            st.info("No books are available to issue. Add books or wait for returns.")
        else:
            borrower_type = st.radio("Issue to", ["Student", "Faculty"], horizontal=True, key="lib_borrower_type")
            people = load_students(["student_id", "name"]) if borrower_type == "Student" else load_faculty()[["faculty_id", "name"]]
            if people.empty:
                st.info(f"No {borrower_type.lower()} records yet. Add some first.")
            else:
                ids = people.iloc[:, 0].astype(str).tolist()
                names = dict(zip(ids, people["name"]))
                book_labels = {r.book_id: f"{r.title} · {r.author or 'unknown'} ({int(r.available)} available)" for r in ready.itertuples()}
                a, b = st.columns(2)
                book_id = a.selectbox("Book", list(book_labels), format_func=lambda i: book_labels[i], key="lib_issue_book")
                person = b.selectbox(borrower_type, ids, format_func=lambda i: f"{i}  —  {names[i]}", key="lib_issue_person")
                days = FACULTY_LOAN_DAYS if borrower_type == "Faculty" else LOAN_DAYS
                issued_on = st.date_input("Issue date", value=date.today(), key="lib_issue_date")
                st.caption(f"Due date will be {(issued_on + timedelta(days=days)):%d %b %Y} ({days} days). "
                           + (f"Students can hold up to {MAX_STUDENT_BOOKS} books." if borrower_type == "Student" else ""))
                if st.button("📤 Issue book", type="primary", use_container_width=True, key="lib_issue_btn"):
                    ok, message = issue_book(book_id, person, borrower_type, issued_on.isoformat())
                    if ok:
                        flash(message)
                        st.rerun()
                    else:
                        st.error(message)

    with tab_cat:
        if books.empty:
            st.info("No books yet.")
        else:
            with st.container(border=True):
                a, b, c = st.columns([2, 1.2, 1.2])
                search = a.text_input("🔍 Search", placeholder="Title, author or ID", key="cat_search")
                cats = b.multiselect("Category", sorted(books["category"].dropna().unique()), key="cat_cat")
                only_available = c.checkbox("Only available", key="cat_avail")
            view = books
            if search:
                view = view[view["title"].str.contains(search, case=False, na=False, regex=False)
                            | view["author"].fillna("").str.contains(search, case=False, regex=False)
                            | view["book_id"].str.contains(search, case=False, na=False, regex=False)]
            if cats:
                view = view[view["category"].isin(cats)]
            if only_available:
                view = view[view["available"] > 0]
            head, button = st.columns([3, 1])
            head.caption(f"Showing **{len(view)}** of **{len(books)}** titles")
            button.download_button("⬇️ Download CSV", csv_bytes(books_display(view)), "library_catalogue.csv", "text/csv", use_container_width=True)
            table(books_display(view))

    with tab_manage:
        with st.form("add_book_form", clear_on_submit=True):
            st.markdown("**Add a new book**")
            book_id = st.text_input("Book ID *", placeholder="e.g. BK-1001")
            a, b = st.columns(2)
            title = a.text_input("Title *")
            author = b.text_input("Author")
            a, b = st.columns(2)
            category = a.selectbox("Category", BOOK_CATEGORIES)
            copies = b.number_input("Copies", 1, 1000, 1)
            submitted = st.form_submit_button("💾 Save Book", use_container_width=True)
        if submitted:
            ok, message = add_book(book_id, title, author, category, copies)
            (st.success if ok else st.error)(message)
        if not books.empty:
            with st.expander("✏️ Edit or delete a book"):
                names = dict(zip(books["book_id"], books["title"]))
                selected = st.selectbox("Choose a book", list(names), format_func=lambda i: f"{i}  —  {names[i]}", key="book_edit_select")
                current = books[books["book_id"] == selected].iloc[0]
                with st.form(f"edit_book_{selected}"):
                    a, b = st.columns(2)
                    title = a.text_input("Title *", value=current["title"], key=f"bt_{selected}")
                    author = b.text_input("Author", value=current["author"] or "", key=f"ba_{selected}")
                    a, b = st.columns(2)
                    category = a.selectbox("Category", BOOK_CATEGORIES, index=option_index(BOOK_CATEGORIES, current["category"]), key=f"bc_{selected}")
                    copies = b.number_input("Copies", 1, 1000, int(current["copies"]), key=f"bn_{selected}")
                    submitted = st.form_submit_button("💾 Update Book", use_container_width=True)
                if submitted:
                    ok, message = update_book(selected, title, author, category, copies)
                    if ok:
                        flash(message)
                        st.rerun()
                    else:
                        st.error(message)
                st.warning("Deleting a book also deletes its loan history.")
                confirm = st.checkbox("I understand and want to delete this book", key=f"book_confirm_{selected}")
                if st.button("🗑️ Delete book", disabled=not confirm, key="book_delete_btn"):
                    delete_book(selected)
                    flash("Book deleted.")
                    st.rerun()

    with tab_hist:
        if loans.empty:
            st.info("No loans recorded yet.")
        else:
            with st.container(border=True):
                a, b = st.columns([2, 1.5])
                search = a.text_input("🔍 Search", placeholder="Borrower, ID or title", key="hist_search")
                statuses = b.multiselect("Status", ["Issued", "Due Soon", "Overdue", "Returned"], key="hist_status")
            view = loans
            if search:
                view = view[view["title"].str.contains(search, case=False, na=False, regex=False)
                            | view["borrower_name"].str.contains(search, case=False, na=False, regex=False)
                            | view["borrower_id"].str.contains(search, case=False, na=False, regex=False)]
            if statuses:
                view = view[view["status"].isin(statuses)]
            head, button = st.columns([3, 1])
            head.caption(f"{len(view)} loan(s)")
            button.download_button("⬇️ Download CSV", csv_bytes(loans_display(view)), "loan_history.csv", "text/csv", use_container_width=True)
            table(loans_display(view))


def rooms_display(frame):
    renamed = frame.rename(columns={"room_no": "Room", "block": "Block", "floor": "Floor", "room_type": "Type",
                                    "capacity": "Beds", "occupied": "Occupied", "vacant": "Vacant", "rent": "Rent (₹)", "status": "Status"})
    return renamed[["Room", "Block", "Floor", "Type", "Beds", "Occupied", "Vacant", "Rent (₹)", "Status"]]


def residents_display(frame):
    renamed = frame.rename(columns={"alloc_id": "Allotment", "room_no": "Room", "block": "Block", "student_id": "ID",
                                    "name": "Name", "department": "Dept", "year": "Year", "allotted_on": "Since"})
    return renamed[["Allotment", "Room", "Block", "ID", "Name", "Dept", "Year", "Since"]]


def page_hostel():
    page_header("🏠", "Hostel", "Rooms, occupancy and resident allotment")
    rooms, residents = load_rooms(), load_residents()
    tab_over, tab_rooms, tab_allot, tab_res, tab_manage = st.tabs(
        ["📊 Overview", "🛏️ Rooms", "🔑 Allot & Vacate", "👥 Residents", "⚙️ Manage Rooms"])

    with tab_over:
        if rooms.empty:
            no_data("hostel", "No hostel rooms yet", "Add rooms in the Manage Rooms tab, or load demo data.")
        else:
            beds, occupied = int(rooms["capacity"].sum()), int(rooms["occupied"].sum())
            kpi_cards([
                ("🚪", "Rooms", len(rooms), f"{rooms['block'].nunique()} block(s)", "blue"),
                ("🛏️", "Beds", beds, "total capacity", "violet"),
                ("👥", "Occupied", occupied, "residents living in", "teal"),
                ("🟢", "Vacant Beds", beds - occupied, "free to allot", "amber"),
                ("📈", "Occupancy", f"{occupied / beds * 100:.0f}%" if beds else "0%", "of all beds", "teal" if beds and occupied / beds < 0.95 else "red"),
            ])
            st.write("")
            left, right = st.columns(2)
            with left, st.container(border=True):
                by_block = rooms.groupby("block")[["occupied", "vacant"]].sum().reset_index()
                long = by_block.melt(id_vars="block", var_name="Beds", value_name="Count")
                long["Beds"] = long["Beds"].map({"occupied": "Occupied", "vacant": "Vacant"})
                fig = px.bar(long, x="block", y="Count", color="Beds", barmode="stack", title="Beds by block",
                             color_discrete_map={"Occupied": "#2563EB", "Vacant": "#CBD5E1"}, labels={"block": "Block"})
                show(fig, legend=True)
            with right, st.container(border=True):
                status = rooms["status"].value_counts().reset_index()
                status.columns = ["Status", "Rooms"]
                fig = px.pie(status, names="Status", values="Rooms", hole=0.55, color="Status", title="Room status",
                             color_discrete_map={"Full": "#F59E0B", "Available": "#14B8A6", "Empty": "#2563EB"})
                show(fig, legend=True)
            if not residents.empty:
                with st.container(border=True):
                    by_dept = residents.groupby("department")["student_id"].count().reset_index(name="Residents")
                    fig = px.bar(by_dept, x="department", y="Residents", color="department", color_discrete_map=DEPT_COLORS,
                                 text_auto=True, title="Residents by department", labels={"department": ""})
                    show(fig, height=300)

    with tab_rooms:
        if rooms.empty:
            st.info("No rooms yet.")
        else:
            with st.container(border=True):
                a, b, c = st.columns(3)
                blocks = a.multiselect("Block", sorted(rooms["block"].unique()), key="room_block")
                types = b.multiselect("Type", ROOM_TYPES, key="room_type_filter")
                statuses = c.multiselect("Status", ["Available", "Empty", "Full"], key="room_status")
            view = rooms
            if blocks:
                view = view[view["block"].isin(blocks)]
            if types:
                view = view[view["room_type"].isin(types)]
            if statuses:
                view = view[view["status"].isin(statuses)]
            st.caption(f"Showing **{len(view)}** of **{len(rooms)}** rooms")
            table(rooms_display(view))

    with tab_allot:
        left, right = st.columns(2)
        with left, st.container(border=True):
            section("🔑 Allot a room")
            free_rooms = rooms[rooms["vacant"] > 0] if not rooms.empty else rooms
            students = load_students(["student_id", "name"])
            housed = set(residents["student_id"].astype(str)) if not residents.empty else set()
            students = students[~students["student_id"].astype(str).isin(housed)] if not students.empty else students
            if free_rooms.empty:
                st.info("No rooms have a vacant bed.")
            elif students.empty:
                st.info("Every student already has a room (or there are no students).")
            else:
                room_labels = {r.room_no: f"{r.room_no} · Block {r.block} · {r.room_type} · {int(r.vacant)} vacant" for r in free_rooms.itertuples()}
                names = dict(zip(students["student_id"].astype(str), students["name"]))
                room_no = st.selectbox("Room", list(room_labels), format_func=lambda r: room_labels[r], key="allot_room")
                student_id = st.selectbox("Student", list(names), format_func=lambda i: f"{i}  —  {names[i]}", key="allot_student")
                allotted_on = st.date_input("Allotment date", value=date.today(), key="allot_date")
                if st.button("🔑 Allot room", type="primary", use_container_width=True, key="allot_btn"):
                    ok, message = allot_room(room_no, student_id, allotted_on.isoformat())
                    if ok:
                        flash(message)
                        st.rerun()
                    else:
                        st.error(message)
        with right, st.container(border=True):
            section("🚪 Vacate a room")
            if residents.empty:
                st.info("No residents to vacate.")
            else:
                labels = {int(r.alloc_id): f"{r.room_no} · {r.name} ({r.student_id})" for r in residents.itertuples()}
                alloc = st.selectbox("Resident", list(labels), format_func=lambda i: labels[i], key="vacate_select")
                vacated_on = st.date_input("Vacating date", value=date.today(), key="vacate_date")
                if st.button("🚪 Vacate room", use_container_width=True, key="vacate_btn"):
                    ok, message = vacate_room(alloc, vacated_on.isoformat())
                    flash(message)
                    st.rerun()

    with tab_res:
        if residents.empty:
            st.info("No residents yet.")
        else:
            search = st.text_input("🔍 Search", placeholder="Name, ID or room", key="res_search")
            view = residents
            if search:
                view = view[view["name"].str.contains(search, case=False, na=False, regex=False)
                            | view["student_id"].str.contains(search, case=False, na=False, regex=False)
                            | view["room_no"].str.contains(search, case=False, na=False, regex=False)]
            head, button = st.columns([3, 1])
            head.caption(f"{len(view)} resident(s)")
            button.download_button("⬇️ Download CSV", csv_bytes(residents_display(view)), "hostel_residents.csv", "text/csv", use_container_width=True)
            table(residents_display(view))

    with tab_manage:
        with st.form("add_room_form", clear_on_submit=True):
            st.markdown("**Add a room**")
            a, b, c = st.columns(3)
            room_no = a.text_input("Room number *", placeholder="e.g. A101")
            block = b.text_input("Block *", placeholder="e.g. A")
            floor = c.number_input("Floor", 0, 30, 1)
            a, b, c = st.columns(3)
            capacity = a.number_input("Beds", 1, 20, 2)
            room_type = b.selectbox("Type", ROOM_TYPES)
            rent = c.number_input("Rent per bed / month (₹)", 0.0, 100000.0, 0.0, step=100.0)
            submitted = st.form_submit_button("💾 Save Room", use_container_width=True)
        if submitted:
            ok, message = add_room(room_no, block, floor, capacity, room_type, rent)
            (st.success if ok else st.error)(message)
        if not rooms.empty:
            with st.expander("✏️ Edit or delete a room"):
                selected = st.selectbox("Choose a room", list(rooms["room_no"]), key="room_edit_select")
                current = rooms[rooms["room_no"] == selected].iloc[0]
                with st.form(f"edit_room_{selected}"):
                    a, b, c = st.columns(3)
                    block = a.text_input("Block", value=current["block"], key=f"rb_{selected}")
                    floor = b.number_input("Floor", 0, 30, int(current["floor"]), key=f"rf_{selected}")
                    capacity = c.number_input("Beds", 1, 20, int(current["capacity"]), key=f"rc_{selected}")
                    a, b = st.columns(2)
                    room_type = a.selectbox("Type", ROOM_TYPES, index=option_index(ROOM_TYPES, current["room_type"]), key=f"rt_{selected}")
                    rent = b.number_input("Rent per bed / month (₹)", 0.0, 100000.0, float(current["rent"]), step=100.0, key=f"rr_{selected}")
                    submitted = st.form_submit_button("💾 Update Room", use_container_width=True)
                if submitted:
                    ok, message = update_room(selected, block, floor, capacity, room_type, rent)
                    if ok:
                        flash(message)
                        st.rerun()
                    else:
                        st.error(message)
                confirm = st.checkbox("I understand and want to delete this room", key=f"room_confirm_{selected}")
                if st.button("🗑️ Delete room", disabled=not confirm, key="room_delete_btn"):
                    ok, message = delete_room(selected)
                    if ok:
                        flash(message)
                        st.rerun()
                    else:
                        st.error(message)


def page_timetable():
    page_header("🗓️", "Timetable", "Weekly class schedule with clash checking for faculty and rooms")
    a, b = st.columns(2)
    department = a.selectbox("Department", DEPARTMENTS, key="tt_dept")
    year = b.selectbox("Year", YEARS, index=1, key="tt_year")
    slots = load_timetable(department, year)
    tab_week, tab_edit, tab_faculty = st.tabs(["📅 Weekly view", "✏️ Edit period", "👩‍🏫 Faculty schedule"])

    with tab_week:
        total = len(DAYS) * len(PERIODS)
        if slots.empty:
            no_data("timetable", f"No timetable for {department} year {year}", "Add periods in the Edit period tab, or load demo data.")
        else:
            kpi_cards([
                ("📅", "Periods / week", len(slots), f"of {total} possible", "blue"),
                ("📘", "Subjects", slots["subject"].nunique(), "different subjects", "violet"),
                ("👩‍🏫", "Faculty involved", slots.loc[slots["faculty"] != "", "faculty"].nunique(), "teaching this class", "teal"),
                ("🕓", "Free periods", total - len(slots), "unscheduled", "amber"),
            ])
            st.write("")
            today_name = DAYS[date.today().weekday()] if date.today().weekday() < len(DAYS) else None
            grid = pd.DataFrame("", index=[f"P{p} · {t}" for p, t in PERIODS.items()], columns=DAYS)
            for row in slots.itertuples():
                cell = row.subject + (f" — {row.faculty}" if row.faculty else "") + (f" ({row.room})" if row.room else "")
                grid.loc[f"P{row.period} · {PERIODS[row.period]}", row.day] = cell
            grid = grid.replace("", "-")
            if today_name:
                grid = grid.rename(columns={today_name: f"{today_name} (today)"})
            try:
                styled = grid.style.map(lambda v: "background-color: #EFF6FF; color: #1E40AF; font-weight: 600;" if v != "-"
                                        else "color: #94A3B8;")
            except (ImportError, AttributeError):
                styled = grid
            st.dataframe(styled, use_container_width=True)
            st.download_button("⬇️ Download timetable (CSV)", grid.reset_index().rename(columns={"index": "Period"}).to_csv(index=False).encode("utf-8"),
                               f"timetable_{department}_year{year}.csv", "text/csv")

    with tab_edit:
        faculty = load_faculty()
        staff = faculty[faculty["department"] == department]["name"].tolist() or faculty["name"].tolist()
        a, b = st.columns(2)
        day = a.selectbox("Day", DAYS, key="tt_day")
        period = b.selectbox("Period", list(PERIODS), format_func=lambda p: f"Period {p} ({PERIODS[p]})", key="tt_period")
        existing = slots[(slots["day"] == day) & (slots["period"] == period)]
        current = existing.iloc[0] if not existing.empty else None
        if current is not None:
            st.info(f"Currently: **{current['subject']}**" + (f" with {current['faculty']}" if current["faculty"] else "")
                    + (f" in {current['room']}" if current["room"] else ""))
        key = f"{department}_{year}_{day}_{period}"
        with st.form(f"slot_form_{key}"):
            subject = st.text_input("Subject *", value=current["subject"] if current is not None else "", key=f"tt_sub_{key}")
            a, b = st.columns(2)
            choices = ["(none)"] + staff
            default = option_index(choices, current["faculty"]) if current is not None else 0
            picked = a.selectbox("Faculty", choices, index=default, key=f"tt_fac_{key}")
            typed = b.text_input("...or type a name", key=f"tt_typed_{key}")
            room = st.text_input("Room", value=current["room"] if current is not None else "", key=f"tt_room_{key}", placeholder="e.g. CR-101")
            c1, c2 = st.columns(2)
            save = c1.form_submit_button("💾 Save period", use_container_width=True)
            clear = c2.form_submit_button("🧹 Clear period", use_container_width=True)
        if save:
            faculty_name = typed.strip() or ("" if picked == "(none)" else picked)
            ok, message = save_slot(department, year, day, period, subject, faculty_name, room)
            if ok:
                flash(message)
                st.rerun()
            else:
                st.error(message)
        if clear:
            clear_slot(department, year, day, period)
            flash("Period cleared.")
            st.rerun()

    with tab_faculty:
        everything = load_timetable()
        if everything.empty:
            st.info("No timetable entries yet.")
        else:
            names = sorted(set(everything.loc[everything["faculty"] != "", "faculty"]))
            if not names:
                st.info("No faculty are assigned to periods yet.")
            else:
                who = st.selectbox("Faculty member", names, key="tt_faculty_pick")
                mine = everything[everything["faculty"] == who].copy()
                mine["Time"] = mine["period"].map(PERIODS)
                mine["Class"] = mine["department"] + " · Year " + mine["year"].astype(str)
                mine["day_order"] = mine["day"].map({d: i for i, d in enumerate(DAYS)})
                mine = mine.sort_values(["day_order", "period"])
                kpi_cards([("📅", "Periods / week", len(mine), who, "blue"),
                           ("🏫", "Classes taught", mine["Class"].nunique(), "different classes", "violet"),
                           ("🕓", "Free periods", len(DAYS) * len(PERIODS) - len(mine), "in the week", "amber")])
                st.write("")
                table(mine.rename(columns={"day": "Day", "period": "Period", "subject": "Subject", "room": "Room"})[
                    ["Day", "Period", "Time", "Class", "Subject", "Room"]])


PAGES = [  # (name, icon, function, sidebar group)
    ("Dashboard", "🏠", page_dashboard, "OVERVIEW"),
    ("Student Records", "👨‍🎓", page_students, "STUDENTS"),
    ("Student Profile", "🪪", page_profile, "STUDENTS"),
    ("Faculty", "👩‍🏫", page_faculty, "CAMPUS"),
    ("Fees", "💰", page_fees, "CAMPUS"),
    ("Lab Equipment", "🧪", page_equipment, "CAMPUS"),
    ("Library", "📚", page_library, "CAMPUS"),
    ("Hostel", "🏠", page_hostel, "CAMPUS"),
    ("Timetable", "🗓️", page_timetable, "CAMPUS"),
    ("Academic Performance", "📊", page_academic, "ANALYTICS"),
    ("Attendance", "📅", page_attendance, "ANALYTICS"),
    ("Department Analysis", "🏢", page_departments, "ANALYTICS"),
    ("Performance Prediction", "🤖", page_prediction, "ANALYTICS"),
    ("At-Risk Students", "⚠️", page_at_risk, "ANALYTICS"),
    ("Reports", "📑", page_reports, "ADMIN"),
    ("Admin Settings", "⚙️", page_settings, "ADMIN"),
]


def login_page():
    _, center, _ = st.columns([1, 1.25, 1])
    with center:
        st.write("")
        st.markdown('<div class="login-brand"><div class="login-logo">🎓</div>'
                    '<div class="login-title">CAMPUS ANALYTICS</div>'
                    '<div class="login-sub">College Management Portal</div></div>', unsafe_allow_html=True)
        with st.form("login_form"):  # a form lets the Enter key submit
            st.markdown("### Admin Login")
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            submitted = st.form_submit_button("Sign in  →", use_container_width=True)
        if submitted:
            ok, message, must_change = attempt_login(username, password)
            if ok:
                st.session_state.logged_in = True
                st.session_state.current_admin = username.strip()
                st.session_state.must_change = must_change
                st.session_state.page = "Admin Settings" if must_change else "Dashboard"
                st.rerun()
            else:
                st.error(message)
        st.markdown('<div class="login-note">🔒 Authorized college management access only</div>', unsafe_allow_html=True)


def app_shell():
    must_change = st.session_state.must_change
    if must_change:
        st.session_state.page = "Admin Settings"
    current = st.session_state.setdefault("page", "Dashboard")

    with st.sidebar:
        st.markdown('<div class="brand"><div class="brand-logo">🎓</div><div><div class="brand-name">CAMPUS ANALYTICS</div>'
                    '<div class="brand-sub">College Management Portal</div></div></div>', unsafe_allow_html=True)
        group = None
        for name, icon, _, page_group in PAGES:
            if page_group != group:
                group = page_group
                st.markdown(f'<div class="nav-group">{group}</div>', unsafe_allow_html=True)
            if st.button(f"{icon}  {name}", key=f"nav_{name}", use_container_width=True,
                         type="primary" if name == current else "secondary",
                         disabled=must_change and name != "Admin Settings"):
                st.session_state.page = name
                st.rerun()
        st.divider()
        admin = st.session_state.current_admin or "Admin"
        st.markdown(f'<div class="user-chip"><div class="avatar">{esc(admin[:1].upper())}</div><div>'
                    f'<div class="user-name">{esc(admin)}</div><div class="user-role">Administrator</div></div></div>',
                    unsafe_allow_html=True)
        if st.button("🚪  Logout", use_container_width=True, key="logout"):
            for key in ("logged_in", "current_admin", "must_change", "prediction_result", "page"):
                st.session_state.pop(key, None)
            st.rerun()

    show_flash()
    for name, _, function, _ in PAGES:
        if name == current:
            function()
            break


def main():
    initialize_database()
    ensure_default_admin()
    st.session_state.setdefault("logged_in", False)
    st.session_state.setdefault("current_admin", None)
    st.session_state.setdefault("must_change", False)
    st.markdown(build_css(st.session_state.logged_in), unsafe_allow_html=True)
    if st.session_state.logged_in:
        app_shell()
    else:
        login_page()


main()
