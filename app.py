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
import calendar as cal
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


# Define a User class that inherits from UserMixin provided by Flask-Login
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

# Function to establish a connection to the SQLite database
def get_db_connection():
    con = sqlite3.connect("database.db")  # Connect to the database
    con.row_factory = sqlite3.Row        # Set row factory to sqlite3.Row for dictionary-like row access
    return con                           # Return the database connection

# Function to load a user from the database, used by Flask-Login
@login_manager.user_loader
def load_user(id):
    con = get_db_connection()            # Get a connection to the database
    cur = con.cursor()                   # Create a cursor object
    cur.execute("SELECT * FROM users WHERE id = ?", (id,))  # Execute a query to find the user by id
    user = cur.fetchone()                # Fetch the user record
    con.close()                          # Close the database connection
    if user:                             # If user is found
        return User(user['id'], user['username'])  # Create and return a User object

    return None                          # Return None if user is not found

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

        con = get_db_connection()
        cur = con.cursor()

        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        user_email = cur.fetchone()

        cur.execute("SELECT * FROM users WHERE username = ?", (username,))
        user_username = cur.fetchone()

        cur.execute("SELECT * FROM users WHERE phone_number = ?", (phone_number,))
        user_phone = cur.fetchone()

        if user_email:
            con.close()
            flash("User with this email already exists", "error")
            return redirect("/signup")
        elif user_username:
            con.close()
            flash("User with this username already exists", "error")
            return redirect("/signup")
        elif user_phone:
            con.close()
            flash("User with this phone number already exists", "error")
            return redirect("/signup")
        else:
            cur.execute(
                "INSERT INTO users (role, faculty, username, email, phone_number, password) VALUES (?, ?, ?, ?, ?, ?)",
                (role, faculty, username, email, phone_number, hashed_password),
            )
            con.commit()
            con.close()
            return redirect("/login")
    else:
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("SELECT faculty_name FROM hub")
        faculties = cur.fetchall()
        con.close()
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
            con = get_db_connection()
            cur = con.cursor()
            cur.execute("SELECT * FROM users WHERE email = ?", (email,))
            user = cur.fetchone()
            con.close()

            if user and bcrypt.checkpw(
                password.encode("utf-8"), user["password"].encode("utf-8")
            ):
                session["logged_in"] = True
                session["id"] = user["id"]  # Assuming the ID is in the "id" field
                return redirect("/")
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
        update_user_info(session["id"], username, email, phone_number)

        return redirect("/profile")

# student and lecturer
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

        con = get_db_connection()
        cur = con.cursor()
        cur.execute("SELECT password FROM users WHERE id = ?", (session["id"],))
        user_data = cur.fetchone()

        if not user_data or not bcrypt.checkpw(
            current_password.encode("utf-8"), user_data["password"].encode("utf-8")
        ):
            return render_template("profile.html", message="Incorrect current password")


        hashed_new_password = hash_password(new_password)
        cur.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (hashed_new_password, session["id"]),
        )
        con.commit()
        con.close()

        return redirect("/profile")
    else:
        return render_template("profile.html")


# student
@app.route("/create_booking", methods=["POST"])
def create_booking():
    """
    Create a booking for an appointment.
    
    Steps:
    1. Fetch the current user's data from the database using their session ID.
    2. Store the username in the session.
    3. If the request method is POST, process the form data to create a booking.
    4. Generate a random booking ID.
    5. Retrieve and store the form data for the booking.
    6. Insert the booking data into the appointments table in the database.
    7. Handle any database integrity errors and flash a message if an error occurs.
    8. Store the appointment ID in the session.
    9. Calculate the start and end times for the appointment.
    10. Update the calendar status for the booking.
    11. Insert the event into the events table in the database.
    12. Flash a success message and redirect to the invoice page.
    """
    
    # Step 1: Fetch the current user's data from the database using their session ID
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (session["id"],))
    user_data = cursor.fetchone()
    conn.close()

    # Step 2: Store the username in the session
    session["username"] = user_data["username"]

    if request.method == "POST":
        # Step 4: Generate a random booking ID
        booking_id = random.randint(100000, 999999)
        
        # Step 5: Retrieve and store the form data for the booking
        student = session["username"]
        lecturer = request.form.get("lecturer")
        purpose = request.form.get("purpose")
        appointment_date = request.form.get("appointment_date")
        appointment_time = request.form.get("selected_time_slot")

        try:
            # Step 6: Insert the booking data into the appointments table in the database
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO appointments (booking_id, student, lecturer, purpose, appointment_date, appointment_time, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (booking_id, student, lecturer, purpose, appointment_date, appointment_time, "Pending"),
            )
            appointment_id = cursor.lastrowid
            conn.commit()
        except sqlite3.IntegrityError as e:
            # Step 7: Handle any database integrity errors and flash a message if an error occurs
            flash(f"An error occurred: {str(e)}", "danger")
            return redirect("/appointment")
        finally:
            conn.close()

        # Step 8: Store the appointment ID in the session
        session["appointment_id"] = appointment_id

        # Step 9: Calculate the start and end times for the appointment
        start_time = datetime.strptime(appointment_time.split(" - ")[0], "%I:%M %p")
        end_time = (start_time + timedelta(hours=1)).strftime("%H:%M")
        start_time = start_time.strftime("%H:%M")

        # Step 10: Update the calendar status for the booking
        update_calendar_status(booking_id, status="Pending")

        # Step 11: Insert the event into the events table in the database
        event_title = f"Appointment with {user_data['username']} (Booking ID: {booking_id})"
        insert_event_into_db(
            event_title=event_title,
            event_date=appointment_date,
            start_time=start_time,
            event_type="appointment",
            end_time=end_time,
            repeat_type="", 
            lecturer=lecturer,
            status="Pending"
        )

        # Step 12: Flash a success message and redirect to the invoice page
        flash("Booking created successfully!", "success")
        return redirect("/invoice")


# student
@app.route("/invoice")
def render_template_invoice():
    user_id = session.get("id")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user_data = cursor.fetchone()
    conn.close()

    appointment_id = session.get("appointment_id")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,))
    appointment = cursor.fetchone()
    conn.close()

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


# student and lecturer
@app.route("/bookinghistory")
def user_booking_history():
    username = session.get("username")
    role = session.get("role")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        if role == "student":
            cursor.execute("SELECT * FROM appointments WHERE student = ?", (username,))
            display_role = "lecturer"
            role = 'student'
        else:
            cursor.execute("SELECT * FROM appointments WHERE lecturer = ?", (username,))
            display_role = "student"
            role = 'teacher'

        appointments = cursor.fetchall()
    finally:
        conn.close()

    return render_template("booking_history.html", appointments=appointments, display_role=display_role, role=role)

# lecturer

@app.route("/cancel_booking", methods=["POST"])
def cancel_booking():
    appointment_id = request.form.get("id")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get the booking_id from the appointments table
        cursor.execute("SELECT booking_id FROM appointments WHERE id = ?", (appointment_id,))
        booking_id = cursor.fetchone()["booking_id"]
        
        # Update the status in the appointments table
        cursor.execute("UPDATE appointments SET status = ? WHERE id = ?", ("Cancelled", appointment_id))
        conn.commit()
        
        # Debug: print a message indicating appointment status update
        print(f"Appointment ID {appointment_id} status updated to 'Cancelled'")
        
        update_calendar_status(booking_id, "Cancelled")
    finally:
        conn.close()

    return redirect("/bookinghistory")

@app.route("/reject_booking", methods=["POST"])
def reject_booking():
    appointment_id = request.form.get("id")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get the booking_id from the appointments table
        cursor.execute("SELECT booking_id FROM appointments WHERE id = ?", (appointment_id,))
        booking_id = cursor.fetchone()["booking_id"]
        
        # Update the status in the appointments table
        cursor.execute("UPDATE appointments SET status = ? WHERE id = ?", ("Rejected", appointment_id))
        conn.commit()
        
        # Debug: print a message indicating appointment status update
        print(f"Appointment ID {appointment_id} status updated to 'Rejected'")
        
        update_calendar_status(booking_id, "Rejected")
    finally:
        conn.close()

    return redirect("/bookinghistory")

@app.route("/accept_booking", methods=["POST"])
def accept_booking():
    appointment_id = request.form.get("id")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get the booking_id from the appointments table
        cursor.execute("SELECT booking_id FROM appointments WHERE id = ?", (appointment_id,))
        booking_id = cursor.fetchone()["booking_id"]
        
        # Update the status in the appointments table
        cursor.execute("UPDATE appointments SET status = ? WHERE id = ?", ("Accepted", appointment_id))
        conn.commit()
        
        # Debug: print a message indicating appointment status update
        print(f"Appointment ID {appointment_id} status updated to 'Accepted'")
        
        update_calendar_status(booking_id, "Accepted")
    finally:
        conn.close()

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
            insert_event_into_db(event_title, event_date, start_time, end_time, lecturer, "Pending", repeat_type, event_type='Work')

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
        # Insert the event into the database
        insert_event_into_db(
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
        # Insert the event into the database
        insert_event_into_db(
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
        day = min(event_date.day, cal.monthrange(year, month)[1])
        event_date = event_date.replace(year=year, month=month, day=day)


@app.route("/calendar", methods=["GET", "POST"])
def event():
    return render_template("calendar.html")

@app.route("/events", methods=["GET"])
def get_events():
    """
    Retrieve events for the currently logged-in lecturer from the calendar table.
    
    Returns:
    - JSON list of events with titles, start/end times, all-day flags, and statuses.
    - HTTP 401 if the user is not logged in.
    - HTTP 500 if an error occurs during data fetching.
    """
    # Get the username of the logged-in lecturer from the session
    lecturer = session.get("username")

    if lecturer:
        # Establish a connection to the database
        con = get_db_connection()
        cur = con.cursor()

        try:
            # Fetch events from the calendar table filtered by lecturer's username
            cur.execute("SELECT event_title, event_date, start_time, end_time, status, event_type FROM calendar WHERE lecturer = ?", (lecturer,))
            calendar_events = cur.fetchall()

            # Initialize an empty list to hold the event details
            events_list = []
            for event in calendar_events:
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
        finally:
            # Ensure the database connection is closed
            con.close()
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



def insert_event_into_db(event_title, event_date, start_time, end_time, lecturer, status, repeat_type, event_type):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO calendar (event_title, event_date, start_time, end_time, lecturer, status, repeat_type, event_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event_title, event_date, start_time, end_time, lecturer, status, repeat_type, event_type)
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        print(f"An error occurred: {str(e)}")
    finally:
        conn.close()


def update_calendar_status(booking_id, status):
    con = get_db_connection()
    cur = con.cursor()
    
    try:
        # Debug: print the status and booking ID being updated
        print(f"Updating calendar status to '{status}' for booking ID: {booking_id}")
        
        # Update the status in the calendar table
        cur.execute("UPDATE calendar SET status = ? WHERE event_title LIKE ?", (status, f'%Booking ID: {booking_id}%'))
        
        # Debug: print the number of rows updated
        print(f"Number of rows updated: {cur.rowcount}")
        
        con.commit()
    except sqlite3.Error as e:
        print("Error updating calendar status:", e)
    finally:
        con.close()


@app.route('/delete_event', methods=['POST'])
def delete_event():
    event_title = request.form.get('event_title')
    if event_title:
        if delete_event_from_db(event_title):
            return jsonify({'status': 'success'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Event not found or deletion failed'}), 500
    else:
        return jsonify({'status': 'error', 'message': 'Invalid event title'}), 400

def delete_event_from_db(event_title):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM calendar WHERE event_title=?", (event_title,))
        conn.commit()
        if cursor.rowcount > 0:
            return True  # Return True if deletion is successful
        else:
            return False  # Return False if event not found
    except sqlite3.Error as e:
        print("SQLite error while deleting event:", e)
        return False  # Return False if deletion fails
    finally:
        conn.close()


@app.route("/appointment")
def appointment():
    if 'id' not in session:
        return redirect('/login')  # Redirect to the login route if session ID is not found
    else:
        return render_template("appointment.html")


def get_lecturers():
    conn = sqlite3.connect('database.db')  # Connect to your database
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE role = 'teacher'")  # Adjust the query as needed
    lecturers = cursor.fetchall()
    conn.close()
    return [lecturer[0] for lecturer in lecturers]

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
        # Connect to the database and create a cursor
        with sqlite3.connect('database.db') as conn:
            cursor = conn.cursor()
            # Iterate over each hour in the specified time range
            for hour in range(start_time, end_time + 1):
                # Execute a query to check for any calendar events overlapping with the specified hour
                cursor.execute(
                    """
                    SELECT 1 FROM calendar 
                    WHERE lecturer = ? 
                    AND event_date = ? 
                    AND (
                        (start_time <= ? AND end_time > ?) OR
                        (start_time < ? AND end_time >= ?)
                    )
                    """, 
                    (lecturer, appointment_date, hour, hour, hour, hour)
                )
                # Fetch the result of the query
                conflict = cursor.fetchone()
                # Log the query result for debugging purposes
                logging.debug(f"Query result for hour {hour}: {conflict}")
                # If there's a conflict (i.e., event overlapping with the hour), add the hour to unavailable_hours
                if conflict:
                    unavailable_hours.append(hour)
    except sqlite3.Error as e:
        # Handle any database errors and return a 500 Internal Server Error response
        logging.error(f"Database error: {str(e)}")
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

    conn = get_db_connection()
    cursor = conn.cursor()

    if search_query:
        cursor.execute(
            """
            SELECT id, lecturer, student, appointment_date, purpose, status, appointment_time 
            FROM appointments 
            WHERE lecturer LIKE ? OR student LIKE ? OR appointment_date LIKE ? OR purpose LIKE ? OR status LIKE ?
            """, 
            (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%")
        )
    else:
        cursor.execute(
            "SELECT id, lecturer, student, appointment_date, purpose, status, appointment_time FROM appointments"
        )

    appointments = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template("appointment_control.html", appointments=appointments)


# admin
def delete_appointment(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM appointments WHERE id=?", (id,))
    conn.commit()
    conn.close()

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
    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch the counts and appointments based on the search query if provided
    if search_query:
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'teacher'"
        )
        num_teachers = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'student'"
        )
        num_students = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM appointments"
        )
        num_appointments = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM users"
        )
        num_users = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT lecturer, student, appointment_date, purpose, status, appointment_time, booking_id 
            FROM appointments 
            WHERE lecturer LIKE ? OR student LIKE ? OR appointment_date LIKE ? OR purpose LIKE ? OR status LIKE ?
            """,
            (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%")
        )
        appointments = cursor.fetchall()
    else:
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'teacher'"
        )
        num_teachers = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'student'"
        )
        num_students = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM appointments"
        )
        num_appointments = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM users"
        )
        num_users = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT lecturer, student, appointment_date, purpose, status, appointment_time, booking_id 
            FROM appointments
            """
        )
        appointments = cursor.fetchall()

    cursor.close()
    conn.close()



    return render_template(
    "admin.html",
    appointments=appointments,
    num_teachers=num_teachers,
    num_students=num_students,
    num_appointments=num_appointments,  # Remove one occurrence of num_appointments
    num_users=num_users,
    # num_appointments=json.dumps(num_appointments)  # Remove this line
)


# admin
@app.route("/usercontrol")
def usercontrol():
    search_query = request.args.get('search', '')

    conn = get_db_connection()
    cursor = conn.cursor()

    if search_query:
        cursor.execute(
            """
            SELECT id, role, faculty, username, phone_number 
            FROM users 
            WHERE username LIKE ? OR role LIKE ? OR faculty LIKE ? OR phone_number LIKE ?
            """, 
            (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%")
        )
    else:
        cursor.execute("SELECT id, role, faculty, username, phone_number FROM users")

    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("usercontrol.html", users=users)


# admin
def delete_user(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id=?", (id,))
    conn.commit()
    conn.close()


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
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT faculty_name, faculty_image FROM hub")
        faculty_info = cursor.fetchall()

        faculty_data = []
        if faculty_info:
            for faculty in faculty_info:
                cursor.execute(
                    "SELECT username, email FROM users WHERE faculty = ? AND role = 'teacher'",
                    (faculty["faculty_name"],)
                )
                lecturers = cursor.fetchall() 

                cursor.execute(
                    "SELECT username, email FROM users WHERE faculty = ? AND role = 'student'",
                    (faculty["faculty_name"],)
                )
                students = cursor.fetchall() 
                faculty_data.append(
                    {
                        "faculty_name": faculty["faculty_name"],
                        "faculty_image": faculty["faculty_image"],
                        "lecturers": [
                            {"username": lecturer[0], "email": lecturer[1]}
                            for lecturer in lecturers
                        ],
                        "students": [
                            {"username": student[0], "email": student[1]}
                            for student in students
                        ],
                    }
                )

        conn.close()
        return render_template("Faculty.html", faculty_info=faculty_data)


# admin

@app.route("/createhub", methods=["GET", "POST"])
def create_faculty_hub():
    if request.method == "POST":
        faculty_name = request.form.get("faculty_name")
        faculty_image = request.files.get("faculty_image")

        if not faculty_name or not faculty_image:
            return render_template(
                "createhub.html", message="Missing required fields"
            )

        try:
            filename = secure_filename(faculty_image.filename)
            image_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

 
            faculty_image.save(image_path)

            print(f"Saved file to {image_path}")

            relative_image_path = filename

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO hub (faculty_name, faculty_image) VALUES (?, ?)",
                (faculty_name, relative_image_path),
            )
            conn.commit()
            conn.close()

            return redirect('/faculty')
        except Exception as e:
            print("Error occurred:", e)
            return render_template(
                "createhub.html",
                message="An error occurred while creating faculty hub",
            )
    else:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM hub")
        faculty_hubs = cursor.fetchall()
        conn.close()
        return render_template("createhub.html", faculty_hubs=faculty_hubs)


# admin
@app.route("/profile")
def profile():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (session["id"],))
    user_data = cursor.fetchone()
    conn.close()

    session["username"] = user_data[3]
    session["role"] = user_data[1]
    session["faculty"] = user_data[2]
    session["email"] = user_data[4]
    session["phone_number"] = user_data[5]

    return render_template(
        "profile.html",
        username=user_data["username"],
        email=user_data["email"],
        faculty=user_data["faculty"],
        phone_number=user_data["phone_number"],
        role=user_data["role"],
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


if __name__ == "__main__":
    app.run(debug=True, port=6969)
