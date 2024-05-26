from flask import Flask, render_template, request, redirect, url_for
from flask import session, flash
from flask_login import LoginManager, UserMixin, login_required, current_user
import sqlite3
import bcrypt
import random
import os


app = Flask(__name__)

# Function to get database connection
def get_db_connection():
        con = sqlite3.connect("database.db")
        con.row_factory = sqlite3.Row
        return con


# Function for updating student info
def update_user_info(id, username, email, phone_number):
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("""UPDATE users SET username=?, email=?, phone_number=? WHERE id=?""",
                (username, email, phone_number, id))
        con.commit()
        con.close()
        flash("User information updated successfully", "success")


# Function to create a new appointment 
def create_appointment(student, lecturer, appointment_date, appointment_time, purpose, status="Pending"):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
        "INSERT INTO appointments (student_id, lecturer_id, appointment_date, appointment_time, purpose, status) VALUES (?, ?, ?, ?, ?, ?)",
        (student, lecturer, appointment_date, appointment_time, purpose, status)
        )
        conn.commit()
        conn.close()


# Function to retrieve appointments for a student
def get_appointments(student):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
        "SELECT * FROM appointments WHERE student= ?",
        (student,)
        )
        appointments = cursor.fetchall()
        conn.close()
        return appointments


# Function to update an existing appointment
def update_appointment(appointment_id, new_date, new_time, new_purpose):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
        "UPDATE appointments SET appointment_date = ?, appointment_time = ?, purpose = ? WHERE id = ?",
        (new_date, new_time, new_purpose, appointment_id)
        )
        conn.commit()
        conn.close()


# Function to delete an appointment
def delete_appointment(id):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
        "DELETE FROM appointments WHERE id = ?",
        (id,)
        )
        conn.commit()
        conn.close()
