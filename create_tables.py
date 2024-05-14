import sqlite3

# Connect with db
con = sqlite3.connect("database.db")
cur = con.cursor()

# Create "users" table
cur.execute(
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL,
        faculty TEXT NOT NULL,
        username TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL UNIQUE,
        phone_number TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL
        )"""
)

# Create "appointments" table
cur.execute(
    """CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student INTEGER NOT NULL,
        lecturer INTEGER NOT NULL,
        appointment_date TEXT NOT NULL,
        appointment_time TEXT NOT NULL,
        purpose TEXT NOT NULL,
        status TEXT NOT NULL,
        FOREIGN KEY (student) REFERENCES users (username),
        FOREIGN KEY (lecturer) REFERENCES users (username)
    )"""
)

# Create "facultyhub" table
cur.execute(
    """CREATE TABLE IF NOT EXISTS facultyhub (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        faculty_name TEXT NOT NULL,
        faculty_image TEXT NOT NULL
        )"""
)

con.commit()
con.close()
