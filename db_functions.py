from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_login import LoginManager, UserMixin, login_required, current_user
from dotenv import load_dotenv
from supabase import create_client
import os

load_dotenv()

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

supabase = create_client(url, key)

app = Flask(__name__)


# Function for updating student info
def update_user_info(id, username, email, phone_number):
    response = (
        supabase.table("users")
        .update({"username": username, "email": email, "phone_number": phone_number})
        .eq("id", id)
        .execute()
    )

    if response.error:
        flash("Error updating user information: " + response.error["message"], "error")
    else:
        flash("User information updated successfully", "success")


# Function to create a new appointment
def create_appointment(
    student, lecturer, appointment_date, appointment_time, purpose, status="Pending"
):
    response = (
        supabase.table("appointments")
        .insert(
            {
                "student_id": student,
                "lecturer_id": lecturer,
                "appointment_date": appointment_date,
                "appointment_time": appointment_time,
                "purpose": purpose,
                "status": status,
            }
        )
        .execute()
    )

    if response.error:
        flash("Error creating appointment: " + response.error["message"], "error")
    else:
        flash("Appointment created successfully", "success")


# Function to retrieve appointments for a student
def get_appointments(student):
    response = (
        supabase.table("appointments").select("*").eq("student_id", student).execute()
    )

    if response.error:
        flash("Error retrieving appointments: " + response.error["message"], "error")
        return []
    else:
        return response.data


# Function to update an existing appointment
def update_appointment(appointment_id, new_date, new_time, new_purpose):
    response = (
        supabase.table("appointments")
        .update(
            {
                "appointment_date": new_date,
                "appointment_time": new_time,
                "purpose": new_purpose,
            }
        )
        .eq("id", appointment_id)
        .execute()
    )

    if response.error:
        flash("Error updating appointment: " + response.error["message"], "error")
    else:
        flash("Appointment updated successfully", "success")


# Function to delete an appointment
def delete_appointment(id):
    response = supabase.table("appointments").delete().eq("id", id).execute()

    if response.error:
        flash("Error deleting appointment: " + response.error["message"], "error")
    else:
        flash("Appointment deleted successfully", "success")
