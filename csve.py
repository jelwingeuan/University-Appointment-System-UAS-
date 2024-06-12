import sqlite3
import csv


def export_to_csv():
    con = sqlite3.connect("database.db")
    cur = con.cursor()

    # Export 'users' table to CSV
    cur.execute("SELECT * FROM users")
    with open("users.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([i[0] for i in cur.description])  # Write headers
        writer.writerows(cur.fetchall())

    # Export 'calendar' table to CSV
    cur.execute("SELECT * FROM calendar")
    with open("calendar.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([i[0] for i in cur.description])  # Write headers
        writer.writerows(cur.fetchall())

    # Export 'appointments' table to CSV
    cur.execute("SELECT * FROM appointments")
    with open("appointments.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([i[0] for i in cur.description])  # Write headers
        writer.writerows(cur.fetchall())

    # Export 'facultyhub' table to CSV
    cur.execute("SELECT * FROM facultyhub")
    with open("facultyhub.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([i[0] for i in cur.description])  # Write headers
        writer.writerows(cur.fetchall())

    con.close()


export_to_csv()
