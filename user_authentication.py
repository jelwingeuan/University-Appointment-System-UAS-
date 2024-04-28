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
        phone_number INT NOT NULL UNIQUE
        )"""
)

# Commit changes to db
con.commit()
con.close()
