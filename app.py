from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask import session, flash
from flask_login import LoginManager, UserMixin
from werkzeug.utils import secure_filename
from db_functions import update_user_info, delete_appointment
from lecturer_calendar import calendar_record, calendar_repeat
import sqlite3
import bcrypt
import random
import os
import json
from supabase import create_client, Client
import calendar
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import logging

logging.basicConfig(level=logging.DEBUG)


app = Flask(__name__, static_folder="static")
login_manager = LoginManager()
login_manager.init_app(app)
app.secret_key = "jelwin"
UPLOAD_FOLDER = os.path.join(
    app.static_folder, "faculty_pp"
) 
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# Define a User class that inherits from UserMixin provided by Flask-Login
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

    @staticmethod
    def from_dict(user_dict):
        return User(user_dict['id'], user_dict['username'])

# Function to load a user from the database, used by Flask-Login
@login_manager.user_loader
def load_user(id):
    response = supabase.table('users').select('*').eq('id', id).execute()
    user_data = response.data
    
    if user_data:
        user = user_data[0]  # Get the first user record
        return User.from_dict(user)  # Create and return a User object
    return None


def load_pin():
    with open("pin.json", "r") as file:
        return json.load(file)["pin"]


def save_pin(new_pin):
    with open("pin.json", "w") as file:
        json.dump({"pin": new_pin}, file)

def load_content():
    with open("content.json") as f:
        return json.load(f)


def save_content(content):
    with open("content.json", "w") as f:
        json.dump(content, f)

def get_current_admin_credentials():
    with open("admin.json", "r") as admin_file:
        admin_data = json.load(admin_file)
        return admin_data.get("email"), admin_data.get("password")


content_data = load_content()
home_content = content_data["home_content"]


@app.route("/")
def home():
    with open("content.json", "r") as file:
        content = json.load(file)

    return render_template(
        "home.html",
        home_content=content["home_content"],
        school_name=content["school_name"],
        school_tel=content["school_tel"],
        school_email=content["school_email"],
        school_logo=content["school_logo"],  
    )


@app.route("/about")
def about():
    return render_template("about.html")


def hash_password(password):
    # Encode the password to a byte string as bcrypt requires bytes input
    encoded_password = password.encode("utf-8")
    
    # Generate a salt and hash the password with the salt
    hashed_password = bcrypt.hashpw(encoded_password, bcrypt.gensalt())
    
    # Decode the hashed password back to a UTF-8 string and return it
    return hashed_password.decode("utf-8")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        role = request.form.get("role")
        faculty = request.form.get("faculty")
        username = request.form.get("username")
        email = request.form.get("email")
        phone_number = request.form.get("phone_number")
        password = request.form.get("password")
        pin = request.form.get("pin")

        if role == "teacher":
            if not email.endswith("@mmu.edu.my"):
                flash("SIGN UP FAILED. Lecturers must use an @mmu.edu.my email.", "error")
                return redirect("/signup")

            stored_pin = load_pin()
            if pin != stored_pin:
                flash("PIN is incorrect", "error")
                return redirect("/signup")

        elif role == "student":
            if not email.endswith("@student.mmu.edu.my"):
                flash("SIGN UP FAILED. Students must use an @student.mmu.edu.my email.", "error")
                return redirect("/signup")

        if not password:
            flash("Password is required", "error")
            return redirect("/signup")

        hashed_password = hash_password(password)

        # Check if the user already exists
        user_email = supabase.table('users').select('*').eq('email', email).execute().data
        user_username = supabase.table('users').select('*').eq('username', username).execute().data
        user_phone = supabase.table('users').select('*').eq('phone_number', phone_number).execute().data

        if user_email:
            flash("User with this email already exists", "error")
            return redirect("/signup")
        elif user_username:
            flash("User with this username already exists", "error")
            return redirect("/signup")
        elif user_phone:
            flash("User with this phone number already exists", "error")
            return redirect("/signup")
        else:
            # Insert the new user into the database
            supabase.table('users').insert({
                'role': role,
                'faculty': faculty,
                'username': username,
                'email': email,
                'phone_number': phone_number,
                'password': hashed_password
            }).execute()
            return redirect("/login")
    else:
        # Fetch faculties from the hub table
        response = supabase.table('hub').select('faculty_name').execute()
        faculties = response.data
        return render_template("signup.html", faculties=faculties)



@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        # Load admin credentials from admin.json
        with open("admin.json", "r") as admin_file:
            admin_data = json.load(admin_file)

        if email == admin_data["email"] and password == admin_data["password"]:
            session["logged_in"] = True
            return redirect("/admin")
        else:
            # Query the Supabase users table for a user with the matching email
            response = supabase.table('users').select('*').eq('email', email).execute()
            user_data = response.data

            if user_data:
                user = user_data[0]  # Get the first user record
                if bcrypt.checkpw(password.encode("utf-8"), user["password"].encode("utf-8")):
                    session["logged_in"] = True
                    session["id"] = user["id"]  # Assuming the ID is in the "id" field
                    return redirect("/")
                else:
                    flash("Invalid email or password")
                    return redirect("/login")
            else:
                flash("Invalid email or password")
                return redirect("/login")
    else:
        return render_template("login.html")


# student and lecturer
@app.route("/update_user_info", methods=["POST"])
def update_user():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        phone_number = request.form.get("phone_number")
        response = supabase.table('users').update({
            'username': username,
            'email': email,
            'phone_number': phone_number
        }).eq('id', session['id']).execute()
        return redirect("/profile")

@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        if new_password != confirm_password:
            return render_template(
                "profile.html", message="New password and confirm password do not match"
            )

        # Query the current user's password from Supabase
        response = supabase.table('users').select('password').eq('id', session['id']).execute()
        user_data = response.data

        if not user_data or not bcrypt.checkpw(
            current_password.encode("utf-8"), user_data[0]['password'].encode("utf-8")
        ):
            return render_template("profile.html", message="Incorrect current password")

        hashed_new_password = hash_password(new_password)
        supabase.table('users').update({
            'password': hashed_new_password
        }).eq('id', session['id']).execute()

        return redirect("/profile")
    else:
        return render_template("profile.html")



# student
@app.route("/create_booking", methods=["POST"])
def create_booking():
    # Fetch the current user's data from Supabase using their session ID
    user_data = supabase.from_('users').select('*').eq('id', session["id"]).execute().get('data')[0]

    # Store the username in the session
    session["username"] = user_data["username"]

    if request.method == "POST":
        # Generate a random booking ID
        booking_id = random.randint(100000, 999999)
        
        # Retrieve and store the form data for the booking
        student = session["username"]
        lecturer = request.form.get("lecturer")
        purpose = request.form.get("purpose")
        appointment_date = request.form.get("appointment_date")
        appointment_time = request.form.get("selected_time_slot")

        try:
            # Insert the booking data into the appointments table in Supabase
            response = supabase.from_('appointments').insert([{
                'booking_id': booking_id,
                'student': student,
                'lecturer': lecturer,
                'purpose': purpose,
                'appointment_date': appointment_date,
                'appointment_time': appointment_time,
                'status': 'Pending'
            }]).execute()
            appointment_id = response.get('data')[0]['id']
        except Exception as e:
            # Handle any database errors and flash a message if an error occurs
            flash(f"An error occurred: {str(e)}", "danger")
            return redirect("/appointment")

        # Store the appointment ID in the session
        session["appointment_id"] = appointment_id

        # Calculate the start and end times for the appointment
        start_time = datetime.strptime(appointment_time.split(" - ")[0], "%I:%M %p")
        end_time = (start_time + timedelta(hours=1)).strftime("%H:%M")
        start_time = start_time.strftime("%H:%M")

        # Update the calendar status for the booking
        update_calendar_status(booking_id, status="Pending")

        # Insert the event into the events table in Supabase
        event_title = f"Appointment with {user_data['username']} (Booking ID: {booking_id})"
        insert_event_into_supabase(
            event_title=event_title,
            event_date=appointment_date,
            start_time=start_time,
            event_type="appointment",
            end_time=end_time,
            repeat_type="", 
            lecturer=lecturer,
            status="Pending"
        )

        # Flash a success message and redirect to the invoice page
        flash("Booking created successfully!", "success")
        return redirect("/invoice")



# student
@app.route("/invoice")
def render_template_invoice():
    user_id = session.get("id")

    # Fetch user data from Supabase
    response = supabase.table('users').select('*').eq('id', user_id).execute()
    user_data = response.data[0]

    appointment_id = session.get("appointment_id")

    # Fetch appointment data from Supabase
    response = supabase.table('appointments').select('*').eq('id', appointment_id).execute()
    appointment = response.data[0]

    return render_template(
        "invoice.html",
        username=session.get("username"),
        email=user_data["email"],
        faculty=user_data["faculty"],
        phone_number=user_data["phone_number"],
        role=user_data["role"],
        appointment=appointment,
        booking_id=appointment["booking_id"]
    )

@app.route("/bookinghistory")
def user_booking_history():
    username = session.get("username")
    role = session.get("role")

    try:
        if role == "student":
            response = supabase.table('appointments').select('*').eq('student', username).execute()
            display_role = "lecturer"
            role = 'student'
        else:
            response = supabase.table('appointments').select('*').eq('lecturer', username).execute()
            display_role = "student"
            role = 'teacher'

        appointments = response.data
    except Exception as e:
        flash(f"An error occurred: {str(e)}", "danger")
        return redirect("/")

    return render_template("booking_history.html", appointments=appointments, display_role=display_role, role=role)


# lecturer

@app.route("/cancel_booking", methods=["POST"])
def cancel_booking():
    appointment_id = request.form.get("id")

    try:
        # Get the booking_id from the appointments table
        response = supabase.table('appointments').select('booking_id').eq('id', appointment_id).execute()
        booking_id = response.data[0]["booking_id"]
        
        # Update the status in the appointments table
        supabase.table('appointments').update({'status': 'Cancelled'}).eq('id', appointment_id).execute()
        
        # Debug: print a message indicating appointment status update
        print(f"Appointment ID {appointment_id} status updated to 'Cancelled'")
        
        update_calendar_status(booking_id, "Cancelled")
    except Exception as e:
        flash(f"An error occurred: {str(e)}", "danger")
    return redirect("/bookinghistory")

@app.route("/reject_booking", methods=["POST"])
def reject_booking():
    appointment_id = request.form.get("id")

    try:
        # Get the booking_id from the appointments table
        response = supabase.table('appointments').select('booking_id').eq('id', appointment_id).execute()
        booking_id = response.data[0]["booking_id"]
        
        # Update the status in the appointments table
        supabase.table('appointments').update({'status': 'Rejected'}).eq('id', appointment_id).execute()
        
        # Debug: print a message indicating appointment status update
        print(f"Appointment ID {appointment_id} status updated to 'Rejected'")
        
        update_calendar_status(booking_id, "Rejected")
    except Exception as e:
        flash(f"An error occurred: {str(e)}", "danger")
    return redirect("/bookinghistory")

@app.route("/accept_booking", methods=["POST"])
def accept_booking():
    appointment_id = request.form.get("id")

    try:
        # Get the booking_id from the appointments table
        response = supabase.table('appointments').select('booking_id').eq('id', appointment_id).execute()
        booking_id = response.data[0]["booking_id"]
        
        # Update the status in the appointments table
        supabase.table('appointments').update({'status': 'Accepted'}).eq('id', appointment_id).execute()
        
        # Debug: print a message indicating appointment status update
        print(f"Appointment ID {appointment_id} status updated to 'Accepted'")
        
        update_calendar_status(booking_id, "Accepted")
    except Exception as e:
        flash(f"An error occurred: {str(e)}", "danger")
    return redirect("/bookinghistory")




# lecturer\

@app.route("/calendar_record", methods=["GET", "POST"])
def create_calendar():
    if request.method == "POST":
        event_title = request.form["event_title"]
        event_date = request.form["event_date"]
        start_time = request.form["start_time"]
        end_time = request.form["end_time"]
        repeat_type = request.form.get("repeat_type", "")
        
        # Fetch lecturer name from the session
        lecturer = session["username"]  # Assuming the lecturer name is stored in the session

        print(f"Creating event: {event_title} on {event_date} with repeat {repeat_type}")

        if repeat_type == "weekly":
            repeat_weekly(event_title, event_date, start_time, end_time, lecturer)
        elif repeat_type == "monthly":
            repeat_monthly(event_title, event_date, start_time, end_time, lecturer)
        else:
            insert_event_into_supabase(event_title, event_date, start_time, end_time, lecturer, "Pending", repeat_type, event_type='Work')

        return redirect("/calendar")


def repeat_weekly(event_title, event_date, start_time, end_time, lecturer):
    """
    Schedule an event to repeat weekly within the same month.

    Parameters:
    - event_title: The title of the event.
    - event_date: The start date of the event in 'YYYY-MM-DD' format.
    - start_time: The start time of the event.
    - end_time: The end time of the event.
    - lecturer: The lecturer associated with the event.
    """
    # Parse the initial event date from string to datetime object
    event_date = datetime.strptime(event_date, '%Y-%m-%d')
    initial_month = event_date.month
    
    # Loop to insert events weekly within the same month
    while event_date.month == initial_month:
        # Insert the event into Supabase
        insert_event_into_supabase(
            event_title, 
            event_date.strftime('%Y-%m-%d'), 
            start_time, 
            end_time, 
            lecturer, 
            "Pending", 
            "weekly", 
            event_type='Work'
        )
        # Increment the event date by one week
        event_date += timedelta(weeks=1)


def repeat_monthly(event_title, event_date, start_time, end_time, lecturer):
    """
    Schedule an event to repeat monthly within the same year.

    Parameters:
    - event_title: The title of the event.
    - event_date: The start date of the event in 'YYYY-MM-DD' format.
    - start_time: The start time of the event.
    - end_time: The end time of the event.
    - lecturer: The lecturer associated with the event.
    """
    # Parse the initial event date from string to datetime object
    event_date = datetime.strptime(event_date, '%Y-%m-%d')
    
    # Loop to insert events monthly within the same year
    while event_date.year == datetime.now().year:
        # Insert the event into Supabase
        insert_event_into_supabase(
            event_title, 
            event_date.strftime('%Y-%m-%d'), 
            start_time, 
            end_time, 
            lecturer, 
            "Pending", 
            "monthly", 
            event_type='Work'
        )
        
        # Calculate the next month and year
        year = event_date.year
        month = event_date.month + 1
        if month > 12:
            month = 1
            year += 1
        
        # Ensure the day exists in the next month
        day = min(event_date.day, calendar.monthrange(year, month)[1])
        event_date = event_date.replace(year=year, month=month, day=day)



@app.route("/calendar", methods=["GET", "POST"])
def event():
    return render_template("calendar.html")

@app.route("/events", methods=["GET"])
def get_events():
    """
    Retrieve events for the currently logged-in lecturer from the events table.
    
    Returns:
    - JSON list of events with titles, start/end times, all-day flags, and statuses.
    - HTTP 401 if the user is not logged in.
    - HTTP 500 if an error occurs during data fetching.
    """
    # Get the username of the logged-in lecturer from the session
    lecturer = session.get("username")

    if lecturer:
        try:
            # Fetch events from the events table filtered by lecturer's username
            response = supabase.table('events').select('event_title', 'event_date', 'start_time', 'end_time', 'status', 'event_type').eq('lecturer', lecturer).execute()
            events_list = []

            for event in response.data:
                start_time = event["start_time"]
                end_time = event["end_time"]
                
                # Check if the event type is "appointment" and the status is "Accepted"
                if event["event_type"] == "appointment":
                    if event["status"] == "Accepted":
                        events_list.append({
                            "title": event["event_title"],
                            "start": f"{event['event_date']}T{start_time}",
                            "end": f"{event['event_date']}T{end_time}" if end_time else None,
                            "allDay": False if start_time and end_time else True,
                            "status": event["status"]
                        })
                else:
                    # For other event types, directly append to the events list
                    events_list.append({
                        "title": event["event_title"],
                        "start": f"{event['event_date']}T{start_time}",
                        "end": f"{event['event_date']}T{end_time}" if end_time else None,
                        "allDay": False if start_time and end_time else True,
                        "status": event["status"]
                    })

            # Return the list of events as a JSON response
            return jsonify(events_list)
        except Exception as e:
            # Handle any exceptions that might occur during data fetching
            return jsonify({"error": str(e)}), 500
    else:
        # Return an error response if the user is not logged in
        return jsonify({"error": "User not logged in"}), 401


def parse_time(time_str):
    """
    Parse a time string in 12-hour format with AM/PM to 24-hour format.

    Parameters:
    - time_str: Time string in 12-hour format (e.g., "02:30PM")

    Returns:
    - Parsed time string in 24-hour format (e.g., "14:30")
    """
    # Parse the input time string from 12-hour format to a datetime object, then format it to 24-hour format
    return datetime.strptime(time_str, "%I:%M%p").strftime("%H:%M")



def insert_event_into_supabase(event_title, event_date, start_time, end_time, lecturer, status, repeat_type, event_type):
    response = supabase.table('events').insert([
        {
            "event_title": event_title,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
            "lecturer": lecturer,
            "status": status,
            "repeat_type": repeat_type,
            "event_type": event_type
        }
    ]).execute()

    if response.error:
        print(f"An error occurred: {response.error}")
    else:
        print("Event inserted successfully")


def update_calendar_status(booking_id, status):
    response = supabase.table('events').update({
        "status": status
    }, f"event_title LIKE '%Booking ID: {booking_id}%'").execute()

    if response.error:
        print(f"Error updating calendar status: {response.error}")
    else:
        print(f"Calendar status updated to '{status}' for booking ID: {booking_id}")
        print(f"Number of rows updated: {len(response.data)}")



@app.route('/delete_event', methods=['POST'])
def delete_event():
    event_title = request.form.get('event_title')
    if event_title:
        if delete_event_from_supabase(event_title):
            return jsonify({'status': 'success'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Event not found or deletion failed'}), 500
    else:
        return jsonify({'status': 'error', 'message': 'Invalid event title'}), 400


def delete_event_from_supabase(event_title):
    response = supabase.table('events').delete().eq('event_title', event_title).execute()

    if response.error:
        print(f"Error deleting event: {response.error}")
        return False
    else:
        print(f"Event '{event_title}' deleted successfully")
        return True



@app.route("/appointment")
def appointment():
    if 'id' not in session:
        return redirect('/login')  # Redirect to the login route if session ID is not found
    else:
        return render_template("appointment.html")


def get_lecturers():
    response = supabase.table('users').select('username').eq('role', 'teacher').execute()

    if response.error:
        print(f"Error fetching lecturers: {response.error}")
        return []
    else:
        lecturers = response.data
        return [lecturer['username'] for lecturer in lecturers]


@app.route("/appointment2")
def appointment2():
    lecturers = get_lecturers()
    return render_template("appointment2.html", lecturers=lecturers)



@app.route("/check_availability", methods=["POST"])
def check_availability():
    # Extract data from the request's JSON payload
    data = request.get_json()
    lecturer = data["lecturer"]
    appointment_date = data["appointment_date"]
    start_time_str = data["start_time"]
    end_time_str = data["end_time"]

    # Log a debug message with the provided data for availability check
    logging.debug(f"Checking availability for {lecturer} on {appointment_date} from {start_time_str} to {end_time_str}")

    try:
        # Parse start and end times from string to hour format
        start_time = datetime.strptime(start_time_str, "%I:%M %p").hour
        end_time = datetime.strptime(end_time_str, "%I:%M %p").hour
    except ValueError as e:
        # Handle any parsing errors and return a 400 Bad Request response
        logging.error(f"Time parsing error: {str(e)}")
        return jsonify({"error": "Invalid time format"}), 400

    # Initialize a list to store unavailable hours
    unavailable_hours = []

    try:
        # Fetch events from the calendar table filtered by lecturer's username, appointment date, and overlapping time range
        response = supabase.table('calendar').select('start_time', 'end_time').eq('lecturer', lecturer).eq('event_date', appointment_date).execute()

        if response.error:
            # Handle any errors that might occur during data fetching and return a 500 Internal Server Error response
            logging.error(f"Supabase error: {response.error}")
            return jsonify({"error": str(response.error)}), 500

        # Extract events data from the response
        events = response.data

        # Iterate over each hour in the specified time range
        for hour in range(start_time, end_time + 1):
            # Check for any calendar events overlapping with the specified hour
            overlapping_events = [event for event in events if event['start_time'] <= hour < event['end_time']]
            # If there are overlapping events, add the hour to unavailable_hours
            if overlapping_events:
                unavailable_hours.append(hour)

    except Exception as e:
        # Handle any other exceptions and return a 500 Internal Server Error response
        logging.error(f"Error occurred: {str(e)}")
        return jsonify({"error": str(e)}), 500

    # If there are unavailable hours, return them along with the availability status
    if unavailable_hours:
        logging.debug(f"Unavailable hours: {unavailable_hours}")
        return jsonify({"availability": "unavailable", "hours": unavailable_hours})
    else:
        # If all hours are available, return the availability status
        logging.debug("All hours available")
        return jsonify({"availability": "available"})




# admin
@app.route("/appointmentcontrol", methods=["GET", "POST"])
def appointmentcontrol():
    search_query = request.args.get('search', '')

    # Fetch appointments based on search query
    if search_query:
        query = f"""
            SELECT id, lecturer, student, appointment_date, purpose, status, appointment_time 
            FROM appointments 
            WHERE lecturer ILIKE '%{search_query}%' 
            OR student ILIKE '%{search_query}%' 
            OR appointment_date ILIKE '%{search_query}%' 
            OR purpose ILIKE '%{search_query}%' 
            OR status ILIKE '%{search_query}%'
        """
    else:
        query = """
            SELECT id, lecturer, student, appointment_date, purpose, status, appointment_time 
            FROM appointments
        """

    # Execute the query
    response = supabase.query(query)

    if response['error']:
        # Handle any errors
        return render_template("error.html", error=response['error'])

    # Fetch the results
    appointments = response['data']

    return render_template("appointment_control.html", appointments=appointments)


# admin
def delete_appointment(id):
    # Connect to Supabase
    supabase = supabase.Client(SUPABASE_URL, SUPABASE_KEY)

    # Construct the deletion query
    query = f"DELETE FROM appointments WHERE id = {id}"

    # Execute the query
    response = supabase.query(query)

    if response['error']:
        # Handle any errors
        print(f"Error deleting appointment: {response['error']}")
    else:
        print("Appointment deleted successfully")


# admin
@app.route("/delete_booking", methods=["POST"])
def delete_booking():
    id = request.form["id"]
    delete_appointment(id)
    return redirect("/appointmentcontrol")

# admin
@app.route("/admin")
def admin_dashboard():
    search_query = request.args.get('search')
    
    # Connect to Supabase
    supabase = supabase.Client(SUPABASE_URL, SUPABASE_KEY)
    
    # Initialize counts and appointments variables
    num_teachers = 0
    num_students = 0
    num_appointments = 0
    num_users = 0
    appointments = []

    # Fetch the counts and appointments based on the search query if provided
    if search_query:
        # Fetch counts of teachers, students, appointments, and users
        response = supabase.from_('users').select('COUNT(*)').eq('role', 'teacher').execute()
        num_teachers = response['count']

        response = supabase.from_('users').select('COUNT(*)').eq('role', 'student').execute()
        num_students = response['count']

        response = supabase.from_('appointments').select('COUNT(*)').execute()
        num_appointments = response['count']

        response = supabase.from_('users').select('COUNT(*)').execute()
        num_users = response['count']

        # Fetch appointments based on the search query
        query = f"""
            SELECT lecturer, student, appointment_date, purpose, status, appointment_time, booking_id
            FROM appointments
            WHERE lecturer ILIKE '%{search_query}%' OR student ILIKE '%{search_query}%'
            OR appointment_date ILIKE '%{search_query}%' OR purpose ILIKE '%{search_query}%'
            OR status ILIKE '%{search_query}%'
        """
        response = supabase.sql(query).execute()
        appointments = response['data']
    else:
        # Fetch counts of teachers, students, appointments, and users
        response = supabase.from_('users').select('COUNT(*)').eq('role', 'teacher').execute()
        num_teachers = response['count']

        response = supabase.from_('users').select('COUNT(*)').eq('role', 'student').execute()
        num_students = response['count']

        response = supabase.from_('appointments').select('COUNT(*)').execute()
        num_appointments = response['count']

        response = supabase.from_('users').select('COUNT(*)').execute()
        num_users = response['count']

        # Fetch all appointments
        query = """
            SELECT lecturer, student, appointment_date, purpose, status, appointment_time, booking_id
            FROM appointments
        """
        response = supabase.sql(query).execute()
        appointments = response['data']

    return render_template(
        "admin.html",
        appointments=appointments,
        num_teachers=num_teachers,
        num_students=num_students,
        num_appointments=num_appointments,
        num_users=num_users,
    )



# admin
@app.route("/usercontrol")
def usercontrol():
    search_query = request.args.get('search', '')

    # Connect to Supabase
    supabase = supabase.Client(SUPABASE_URL, SUPABASE_KEY)
    
    # Initialize users variable
    users = []

    # Fetch users based on the search query if provided
    if search_query:
        # Fetch users based on the search query
        query = f"""
            SELECT id, role, faculty, username, phone_number 
            FROM users 
            WHERE username ILIKE '%{search_query}%' OR role ILIKE '%{search_query}%'
            OR faculty ILIKE '%{search_query}%' OR phone_number ILIKE '%{search_query}%'
        """
        response = supabase.sql(query).execute()
        users = response['data']
    else:
        # Fetch all users
        response = supabase.from_('users').select('id, role, faculty, username, phone_number').execute()
        users = response['data']

    return render_template("usercontrol.html", users=users)



# admin
def delete_user(id):
    # Connect to Supabase
    supabase = supabase.Client(SUPABASE_URL, SUPABASE_KEY)
    
    # Delete the user with the specified id
    response = supabase.from_('users').delete().eq('id', id).execute()

    if response['error']:
        print(f"Error deleting user: {response['error']}")
        return False
    else:
        print(f"User with id {id} deleted successfully.")
        return True



@app.route("/adminpageeditor", methods=["GET", "POST"])
def admin_page_editor():
    content = load_content()
    current_admin_email, current_admin_password = get_current_admin_credentials()

    if request.method == "POST":
        home_content = request.form.get("home_content")
        school_name = request.form.get("school_name")
        school_tel = request.form.get("school_tel")
        school_email = request.form.get("school_email")
        new_pin = request.form.get("new_pin")
        retype_new_pin = request.form.get("retype_new_pin")

        filename = ""
        if "school_logo" in request.files:
            file = request.files["school_logo"]
            if file.filename != "":
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        content.update(
            {
                "home_content": home_content,
                "school_name": school_name,
                "school_tel": school_tel,
                "school_email": school_email,
                "school_logo": filename,
            }
        )

        save_content(content)

        if new_pin and retype_new_pin:
            if new_pin == retype_new_pin:
                save_pin(new_pin)
            else:
                return render_template(
                    "adminpageeditor.html",
                    **content,
                    pin=load_pin(),
                    message="PINs do not match",
                )

        return redirect(url_for("admin_page_editor"))

    return render_template(
        "adminpageeditor.html",
        **content,
        pin=load_pin(),
        current_admin_email=current_admin_email,
        current_admin_password=current_admin_password,
    )

@app.route("/getpin", methods=["GET"])
def get_pin():
    return jsonify({"pin": load_pin()})

@app.route("/changepin", methods=["POST"])
def change_teacher_pin():
    new_pin = request.form.get("new_pin")
    retype_new_pin = request.form.get("retype_new_pin")

    if new_pin != retype_new_pin:
        return "New PIN and Retyped PIN do not match", 400

    save_pin(new_pin)

    return redirect("/adminpageeditor")

@app.route("/change_admin_credentials", methods=["POST"])
def change_admin_credentials():
    admin_email = request.form.get("admin_email")
    admin_password = request.form.get("admin_password")

    admin_data = {"email": admin_email, "password": admin_password}
    with open("admin.json", "w") as admin_file:
        json.dump(admin_data, admin_file)

    return redirect("/adminpageeditor")


@app.route("/delete_user", methods=["POST"])
def delete_user_route():
    id = request.form["id"]
    delete_user(id)
    return redirect("/usercontrol")


@app.route("/changepassword")
def changepassword():
    return render_template("changepassword.html")


@app.route("/faculty")
def faculty():
    # Connect to Supabase
    supabase = supabase.Client(SUPABASE_URL, SUPABASE_KEY)

    # Fetch faculty information from the 'hub' table
    faculty_info = supabase.from_('hub').select('faculty_name, faculty_image').execute().get('data')

    faculty_data = []
    if faculty_info:
        for faculty in faculty_info:
            # Fetch lecturers for the current faculty
            lecturers = supabase.from_('users').select('username, email').eq('faculty', faculty['faculty_name']).eq('role', 'teacher').execute().get('data')

            # Fetch students for the current faculty
            students = supabase.from_('users').select('username, email').eq('faculty', faculty['faculty_name']).eq('role', 'student').execute().get('data')

            faculty_data.append({
                "faculty_name": faculty["faculty_name"],
                "faculty_image": faculty["faculty_image"],
                "lecturers": lecturers if lecturers else [],
                "students": students if students else [],
            })

    return render_template("Faculty.html", faculty_info=faculty_data)



# admin

@app.route("/createhub", methods=["GET", "POST"])
def create_faculty_hub():
    if request.method == "POST":
        faculty_name = request.form.get("faculty_name")
        faculty_image = request.files.get("faculty_image")

        if not faculty_name or not faculty_image:
            return render_template("createhub.html", message="Missing required fields")

        try:
            filename = secure_filename(faculty_image.filename)
            image_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            faculty_image.save(image_path)
            print(f"Saved file to {image_path}")

            # Upload image to Supabase Storage
            image_upload_response = supabase.storage.from_path(filename, image_path).upload()

            if image_upload_response['data']:
                # Get the URL of the uploaded image
                relative_image_path = image_upload_response['data']['RelativeUrl']

                # Insert faculty hub information into the 'hub' table
                insert_result = supabase.from_('hub').insert([{'faculty_name': faculty_name, 'faculty_image': relative_image_path}]).execute()

                if insert_result['data']:
                    return redirect('/faculty')
                else:
                    return render_template("createhub.html", message="Failed to insert faculty hub information")
            else:
                return render_template("createhub.html", message="Failed to upload image")
        except Exception as e:
            print("Error occurred:", e)
            return render_template("createhub.html", message="An error occurred while creating faculty hub")
    else:
        # Fetch existing faculty hubs from Supabase
        faculty_hubs = supabase.from_('hub').select('*').execute().get('data')
        return render_template("createhub.html", faculty_hubs=faculty_hubs)


# admin
@app.route("/profile")
def profile():
    # Fetch user data from Supabase
    user_data_response = supabase.from_('users').select('*').eq('id', session["id"]).execute()

    if user_data_response['data']:
        user_data = user_data_response['data'][0]

        # Update session with user data
        session["username"] = user_data["username"]
        session["role"] = user_data["role"]
        session["faculty"] = user_data["faculty"]
        session["email"] = user_data["email"]
        session["phone_number"] = user_data["phone_number"]

        return render_template(
            "profile.html",
            username=user_data["username"],
            email=user_data["email"],
            faculty=user_data["faculty"],
            phone_number=user_data["phone_number"],
            role=user_data["role"],
        )
    else:
        return "User not found"  # Handle case where user data is not found


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


if __name__ == "__main__":
    app.run(debug=True, port=6969)
