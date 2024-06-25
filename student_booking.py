
from flask import session, flash
from create_tables import get_db_connection


# Function to READ user's data with id
def user_booking():
    con = get_db_connection()
    cur = con.cursor()
    cur.execute("""SELECT *
                FROM users
                WHERE id = ?""", (session["id"],)
                )
    user_data = cur.fetchone()
    con.close()
    return user_data


# Function to CREATE booking
def make_booking(booking_id, student, lecturer, purpose, appointment_date, start_time, end_time, status="Pending"):
    con = get_db_connection()
    cur = con.cursor()
    cur.execute("""
                INSERT INTO appointments (booking_id, student, lecturer, purpose, appointment_date, start_time, end_time, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (booking_id, student, lecturer, purpose, appointment_date, start_time, end_time, status))
    appointment_id = cur.lastrowid
    con.commit()
    con.close()
    return appointment_id



# Function to update the status of a booking (both student and teacher)
def update_booking_status(booking_id, status):
    con = get_db_connection()
    cur = con.cursor()
    cur.execute("""
        UPDATE appointments SET status = ? WHERE booking_id = ?
    """, (status, booking_id))
    con.commit()
    con.close()