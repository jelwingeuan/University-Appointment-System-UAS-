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

# Create "facultyhub" table
cur.execute(
    """CREATE TABLE IF NOT EXISTS facultyhub (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        faculty_name TEXT NOT NULL,
        faculty_image TEXT NOT NULL
        )"""
)


# I WANT THESE TO BE DELETED#++++++++++++++++++++++++++++++++++++++
# # Create "faculty_hubs" table
# cur.execute(
#     """CREATE TABLE IF NOT EXISTS faculty_hubs (
#         id INTEGER PRIMARY KEY AUTOINCREMENT,
#         name TEXT NOT NULL,
#         image_path TEXT
#         )"""
# )


# # Create "faculty_hubs" table
# cur.execute(
#     """CREATE TABLE IF NOT EXISTS faculty_hubs (
#         id INTEGER PRIMARY KEY AUTOINCREMENT,
#         name TEXT NOT NULL,
#         location TEXT NOT NULL
#         )"""
# )
# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

con.commit()
con.close()
