from flask import Flask, render_template, request, redirect, url_for
from flask import session, flash
from flask_login import LoginManager, UserMixin, login_required, current_user
from create_tables import get_db_connection
import sqlite3
import bcrypt
import random
import os


app = Flask(__name__)

# Function to CREATE user's account for sign up
def create_user(role, faculty, username, email, phone_number, hashed_password):
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("INSERT INTO users (role, faculty, username, email, phone_number, password) VALUES (?, ?, ?, ?, ?, ?)", (role, faculty, username, email, phone_number, hashed_password))
        con.commit()
        con.close()
        flash("User created successfully", "success")
        return redirect("/login")


# Function to READ user's email for login
def login_student(email):
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cur.fetchone()
        con.close()
        return user


# Function to READ user's email for sign up
def email_auth(email):
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        user_email = cur.fetchone()
        return user_email


# Function to READ user's username for sign up
def username_auth(username):
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("SELECT * FROM users WHERE username = ?", (username,))
        user_username = cur.fetchone()
        return user_username


# Function to READ user's phone_number for sign up
def phonenumber_auth(phone_number):
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("""
                SELECT * FROM users 
                WHERE phone_number = ?
                """, (phone_number,)
                )
        user_phone = cur.fetchone()
        return user_phone


# Function to UPDATE user's info
def update_user_info(id, username, email, phone_number):
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("""
                UPDATE users SET username=?, email=?, phone_number=?
                WHERE id=?
                """,(username, email, phone_number, id)
                )
        con.commit()
        con.close()
        flash("User information updated successfully", "success")


# Function to READ user's password for password changing
def id_password(id):
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("""
                SELECT password FROM users
                WHERE id = ?
                """, (session["id"],)
                )
        user_data = cur.fetchone()
        return user_data


# Function to UPDATE new password
def new_hashed_password(hashed_new_password, id):
        con = get_db_connection()
        cur = con.cursor()
        cur.execute(
                """
                UPDATE users SET password = ?
                WHERE id = ?
                """, (hashed_new_password, id),
                )
        con.commit()
        con.close()


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
