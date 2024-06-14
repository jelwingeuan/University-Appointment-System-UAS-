
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask import session, flash
import logging
from flask_login import LoginManager, UserMixin
from werkzeug.utils import secure_filename
from create_tables import get_db_connection
from user_authentication import(
    email_auth, username_auth, phonenumber_auth, create_user, login_student,
    update_user_info, id_password, new_hashed_password,delete_appointment
    )
from student_booking import(
    user_booking, make_booking, update_booking_status
)
from teacher_availability import(
    get_availability, availability_record, availability_repeat
    )
import bcrypt
import random
import os
import json
from datetime import datetime, timedelta



# Display debug messages
logging.basicConfig(level=logging.DEBUG)


# Initialise Flask-Login
app = Flask(__name__, static_folder="static")
login_manager = LoginManager()
login_manager.init_app(app)


# Load secret key from environment variable
app.secret_key = os.environ.get("SECRET_KEY", "default_secret_key")


# Set the upload file path, "faculty_pp" here
UPLOAD_FOLDER = os.path.join(app.static_folder, "faculty_pp")

# Create the folder if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Configure flask app
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# Manage the user's profile with UserMixin
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username


# Load user with Flask-Login
@login_manager.user_loader
def load_user(id):
    con = get_db_connection()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (id,))
    user = cur.fetchone()
    con.close()
    if user:
        return User(user['id'], user['username'])
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


# Hash password with bcrypt
def hash_password(password):
    # Encode the password to a byte string as bcrypt requires bytes input
    encoded_password = password.encode("utf-8")
    
    # Generate a salt and hash the password with the salt
    hashed_password = bcrypt.hashpw(encoded_password, bcrypt.gensalt())
    
    # Decode the hashed password back to a UTF-8 string and return it
    return hashed_password.decode("utf-8")


# Sign up for student and teacher
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
        
        # if else statements to check the credentials of teacher and student
        if role == "teacher":
            if not email.endswith("@mmu.edu.my"):
                flash("SIGN UP FAILED! Lecturers must use an @mmu.edu.my email.", "error")
                return redirect("/signup")

            stored_pin = load_pin()
            if pin != stored_pin:
                flash("PIN is incorrect", "error")
                return redirect("/signup")

        elif role == "student":
            if not email.endswith("@student.mmu.edu.my"):
                flash("SIGN UP FAILED! Students must use an @student.mmu.edu.my email.", "error")
                return redirect("/signup")
            
        # Check if password is given by user
        if not password:
            flash("Password is required", "error")
            return redirect("/signup")
        
        # Call the hash_password function
        hashed_password = hash_password(password)
        
        # Authenticate the user's email, username, and phone number
        user_email = email_auth(email)
        user_username = username_auth(username)
        user_phone = phonenumber_auth(phone_number)
        
        
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
            create_users = create_user(role, faculty, username, email, phone_number, hashed_password)
            return create_users
        
    else:
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("SELECT faculty_name FROM facultyhub")
        faculties = cur.fetchall()
        con.close()
        return render_template("signup.html", faculties=faculties)


# Log in for student and teacher
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
            user = login_student(email)
            
            # If else statement that check if the password provided by user matched with the password in db
            if user and bcrypt.checkpw(
                password.encode("utf-8"), user["password"].encode("utf-8")
            ):
                # Session that indicate user is logged in 
                session["logged_in"] = True
                
                # Store user's id for fetching user's specific data
                session["id"] = user["id"]
                return redirect("/")
            else:
                flash("Invalid email or password")
                return redirect("/login")
    else:
        return render_template("login.html")


# Update user's info for student and lecturer
@app.route("/update_user_info", methods=["POST"])
def update_user():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        phone_number = request.form.get("phone_number")
        update_user_info(session["id"], username, email, phone_number)

        return redirect("/profile")


# Change password for student and teacher
@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        if new_password != confirm_password:
            return render_template("profile.html", message="New password and confirm password do not match")
        else:
            user_data = id_password(id)

        if not user_data or not bcrypt.checkpw(
            current_password.encode("utf-8"), user_data["password"].encode("utf-8")
        ):
            return render_template("profile.html", message="Incorrect current password")


        hashed_new_password = hash_password(new_password)
        new_hashed_password(hashed_new_password, id)

        return redirect("/profile")
    else:
        return render_template("profile.html")


# student
@app.route("/create_booking", methods=["POST"])
def create_booking():
    
    # Fetch the current user's data from the database using their session ID
    user_data = user_booking()

    # Store the username in the session
    session["username"] = user_data["username"]

    if request.method == "POST":
        # Generate a random booking id
        booking_id = random.randint(100000, 999999)
        
        # Retrieve and store the form data for the booking
        student = session["username"]
        lecturer = request.form.get("lecturer")
        purpose = request.form.get("purpose")
        appointment_date = request.form.get("appointment_date")
        start_time = request.form.get("start_time")
        end_time = request.form.get("end_time")
        
        # Insert the booking data into the appointments table in the database
        make_booking(booking_id, student, lecturer, purpose, appointment_date, start_time, end_time, status="Pending")
        
        return redirect("/bookinghistory")


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


@app.route("/accept_booking", methods=["POST"])
def accept_booking():
    booking_id = request.form.get("id")
    update_booking_status(booking_id, "Accepted")
    return redirect("/bookinghistory")


@app.route("/reject_booking", methods=["POST"])
def reject_booking():
    booking_id = request.form.get("id")
    update_booking_status(booking_id, "Rejected")
    return redirect("/bookinghistory")


@app.route("/cancel_booking", methods=["POST"])
def cancel_booking():
    booking_id = request.form.get("id")
    update_booking_status(booking_id, "Cancelled")
    return redirect("/bookinghistory")


# teacher
@app.route("/record_availability", methods=["GET", "POST"])
def record_availability():
    if request.method == "POST":
        lecturer = request.form["lecturer"]
        appointment_date = request.form["appointment_date"]
        start_time = request.form["start_time"]
        end_time = request.form["end_time"]
        
        availability_record(lecturer, appointment_date, start_time, end_time)
        
        return redirect(url_for("display_availability"))
    
    return render_template("availability.html")


@app.route("/repeat_availability", methods=["GET", "POST"])
def repeat_availability():
    if request.method == "POST":
        appointment_date = request.form["appointment_date"]
        start_time = request.form["start_time"]
        end_time = request.form["end_time"]
        repeat_type = request.form["repeat_type"]
        repeat_interval = int(request.form["repeat_interval"])
        repeat_count = int(request.form["repeat_count"])
        
        if repeat_type not in ["No repeat", "Daily", "Weekly", "Monthly"]:
            return render_template("availability.html", message="Invalid repeat type. Must be No Repeat, Daily, Weekly, or Monthly.")
        
        if repeat_count < 1:
            return render_template("availability.html", message="Repeat count must be at least 1.")
        
        result = availability_repeat(appointment_date, start_time, end_time, repeat_type, repeat_interval, repeat_count)
        
        if result is None:
            return render_template("availability.html", message="Event not found or invalid date format.")
        
        return redirect(url_for("display_availability"))
    
    availability = get_availability()
    return render_template("availability.html", availability=availability)


@app.route("/display_availability")
def display_availability():
    availability = get_availability()
    return render_template("availability.html", availability=availability)


@app.route("/appointment")
def appointment():
    return render_template("appointment.html")


@app.route("/appointment2")
def appointment2():
    return render_template("appointment2.html")


# admin
@app.route("/appointmentcontrol", methods=["GET", "POST"])
def appointmentcontrol():
    conn = get_db_connection()
    cursor = conn.cursor()
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
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'teacher'")
    num_teachers = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'student'")
    num_students = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM appointments")
    num_appointments = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users")
    num_users = cursor.fetchone()[0]

    cursor.execute(
        "SELECT lecturer, student, appointment_date, purpose, status, appointment_time FROM appointments"
    )
    appointments = cursor.fetchall()

    cursor.close()
    conn.close()

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
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    user_data = cursor.fetchall()
    conn.close()

    return render_template("usercontrol.html", users=user_data)


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

    return render_template("adminpageeditor.html", **content, pin=load_pin())


@app.route("/getpin", methods=["GET"])
def get_pin():
    return jsonify({"pin": load_pin()})


@app.route("/update_home_content", methods=["POST"])
def update_home_content():
    content = load_content()
    home_content = request.form["home_content"]
    content["home_content"] = home_content
    save_content(content)
    return redirect("/adminpageeditor")


@app.route("/delete_user", methods=["POST"])
def delete_user_route():
    id = request.form["id"]
    delete_user(id)
    return redirect("/usercontrol")


@app.route("/changepassword")
def changepassword():
    return render_template("changepassword.html")


@app.route("/history")
def history():
    return render_template("schedule.html")


@app.route("/faculty")
def faculty():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT faculty_name, faculty_image FROM facultyhub")
    faculty_info = cursor.fetchall()

    faculty_data = []
    for faculty in faculty_info:
        cursor.execute(
            "SELECT username, email FROM users WHERE faculty = ? AND role = 'teacher'",
            (faculty["faculty_name"],),
        )
        lecturers = cursor.fetchall()

        cursor.execute(
            "SELECT username, email FROM users WHERE faculty = ? AND role = 'student'",
            (faculty["faculty_name"],),
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

    return render_template("faculty.html", faculty_info=faculty_data)


# admin
@app.route("/facultyhub/<int:hub_id>", methods=["GET"])
def faculty_hub_page(hub_id=None):
    try:
        if hub_id:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, image_path FROM facultyhub WHERE id = ?", (hub_id,)
            )
            faculty_hub = cursor.fetchone()
            conn.close()

            if faculty_hub:
                return render_template("facultyhub.html", faculty_hub=faculty_hub)
            else:
                return render_template("error.html", message="Faculty Hub Not Found")
        else:
            return render_template(
                "error.html", message="Please provide a valid Faculty Hub ID"
            )
    except Exception as e:
        print("Error in faculty_hub_page:", e)
        return render_template(
            "error.html", message="An error occurred while processing your request"
        )


@app.route("/createfacultyhub", methods=["GET", "POST"])
def create_faculty_hub():
    if request.method == "POST":
        faculty_name = request.form.get("faculty_name")
        faculty_image = request.files.get("faculty_image")

        if not faculty_name or not faculty_image:
            return render_template(
                "createfacultyhub.html", message="Missing required fields"
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
                "INSERT INTO facultyhub (faculty_name, faculty_image) VALUES (?, ?)",
                (faculty_name, relative_image_path),
            )
            conn.commit()
            conn.close()

            return redirect(url_for("create_faculty_hub"))
        except Exception as e:
            print("Error occurred:", e)
            return render_template(
                "createfacultyhub.html",
                message="An error occurred while creating faculty hub",
            )
    else:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM facultyhub")
        faculty_hubs = cursor.fetchall()
        conn.close()
        return render_template("createfacultyhub.html", faculty_hubs=faculty_hubs)


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