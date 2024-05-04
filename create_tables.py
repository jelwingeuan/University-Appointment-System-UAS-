import sqlite3

# Connect with db
con = sqlite3.connect("database.db")
cur = con.cursor()

# Create "users" table
cur.execute(
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL UNIQUE,
        phone_number INT NOT NULL UNIQUE,
        password TEXT NOT NULL
        )"""
)

# Create "faculty_hubs" table
cur.execute(
    """CREATE TABLE IF NOT EXISTS faculty_hubs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        location TEXT NOT NULL
        )"""
)


con.commit()
con.close()
