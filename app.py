
from flask import Flask, render_template, request, redirect, url_for
from flask import session, flash
from flask_login import LoginManager, UserMixin, login_required
from db_functions import (
    update_user_info,
    create_appointment,
    get_appointments,
    update_appointment,
    delete_appointment,
)
import sqlite3
import bcrypt
import random
import os

app = Flask(__name__)
login_manager = LoginManager()
login_manager.init_app(app)
app.secret_key = "jelwin"
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


class User(UserMixin):
    def __init__(self, user_id):
        self.id = user_id


# Function to get database connection
def get_db_connection():
    con = sqlite3.connect("database.db")
    con.row_factory = sqlite3.Row
    return con


@login_manager.user_loader
def load_user(user_id):
    # Load and return a user from the database based on user_id
    con = get_db_connection()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cur.fetchone()
    con.close()
    if user:
        return User(user["id"])
    else:
        return None


# Prevent auto log in
first_request = True

@app.before_request
def clear_session():
    global first_request
    if first_request:
        session.clear()
        first_request = False


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/about")
def about():
    return render_template("about.html")


# Function for hashed password
def hash_password(password):
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed_password.decode("utf-8")


# Route for "sign up"
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        role = request.form.get("role")
        if role == "teacher":
            # If the selected role is "teacher", redirect to the teacher sign-up page
            return redirect("/signupteacher")
        else:
            # Handle other roles (e.g., student) here
            faculty = request.form.get("faculty")
            username = request.form.get("username")
            email = request.form.get("email")
            phone_number = request.form.get("phone_number")
            password = request.form.get("password")

            if not password:  # Check if password is provided
                return render_template("signup.html", message="Password is required")

            hashed_password = hash_password(password)

            con = get_db_connection()
            cur = con.cursor()

            # Check if email already exists
            cur.execute("SELECT * FROM users WHERE email = ?", (email,))
            user = cur.fetchone()

            if user:
                con.close()
                return render_template(
                    "signup.html", message="User with this email already exists"
                )
            else:
                cur.execute(
                    "INSERT INTO users (role, faculty, username, email, phone_number, password) VALUES (?, ?, ?, ?, ?, ?)",
                    (role, faculty, username, email, phone_number, hashed_password),
                )
                con.commit()
                con.close()
                return redirect("/signupflash")
    else:
        return render_template("signup.html")


# Route for signupteacher
@app.route("/signupteacher", methods=["GET", "POST"])
def signupteacher():
    if request.method == "POST":
        pin_number = request.form.get("pin_number")

        # Check if the entered PIN number is correct
        if pin_number != "006942000":
            return render_template("signupteacher.html", message="Incorrect PIN number")

        # PIN is correct, proceed with saving teacher details
        faculty = request.form.get("faculty")
        username = request.form.get("username")
        email = request.form.get("email")
        phone_number = request.form.get("phone_number")
        password = request.form.get("password")

        if not password:  # Check if password is provided
            return render_template("signupteacher.html", message="Password is required")

        hashed_password = hash_password(password)

        con = get_db_connection()
        cur = con.cursor()

        try:
            # Check if email already exists
            cur.execute("SELECT * FROM users WHERE email = ?", (email,))
            user = cur.fetchone()

            if user:
                con.close()
                return render_template(
                    "signup.html", message="User with this email already exists"
                )
            else:
                cur.execute(
                    "INSERT INTO users (role, faculty, username, email, phone_number, password) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "teacher",
                        faculty,
                        username,
                        email,
                        phone_number,
                        hashed_password,
                    ),
                )
                con.commit()
                con.close()
                return redirect(
                    "/signupflash"
                )  # Redirect to signup flash page upon successful signup

        except Exception as e:
            # Handle exceptions here, if necessary
            print(e)
            return render_template("error.html", message="An error occurred.")

    else:
        return render_template("signupteacher.html")


# Route for "log in"
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        if email == "admin@example.com" and password == "123":
            session["logged_in"] = True
            return redirect("/admin")
        else:
            # If not admin, proceed with regular user login logic
            con = get_db_connection()
            cur = con.cursor()
            cur.execute("SELECT * FROM users WHERE email = ?", (email,))
            user = cur.fetchone()

            if user and bcrypt.checkpw(
                password.encode("utf-8"), user["password"].encode("utf-8")
            ):
                # Redirect to the home page upon successful login for regular users
                session["logged_in"] = True
                session["id"] = user["id"]
                return redirect("/flash")
            else:
                return render_template(
                    "login.html", message="Invalid email or password"
                )
    else:
        return render_template("login.html")


# Route for rendering profile page
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
    session["phone_number"] = user_data[5]

    return render_template(
        "profile.html",
        username=user_data["username"],
        email=user_data["email"],
        faculty=user_data["faculty"],
        phone_number=user_data["phone_number"],
        role=user_data["role"],
    )



# Route for updating user information
@app.route("/update_user_info", methods=["POST"])
@login_required
def update_user():
    if request.method == "POST":
        faculty = request.form.get("faculty")
        username = request.form.get("username")
        email = request.form.get("email")
        phone_number = request.form.get("phone_number")
        update_user_info(session["id"], faculty, username, email, phone_number)

        return redirect(url_for("profile"))


# Route for changing password
@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        # Verify if new password and confirm password match
        if new_password != confirm_password:
            return render_template(
                "profile.html", message="New password and confirm password do not match"
            )

        # Verify if the current password is correct
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("SELECT password FROM users WHERE id = ?", (session["id"],))
        user_data = cur.fetchone()

        if not user_data or not bcrypt.checkpw(
            current_password.encode("utf-8"), user_data["password"].encode("utf-8")
        ):
            return render_template("profile.html", message="Incorrect current password")

        # Update the password in the database
        hashed_new_password = hash_password(new_password)
        con = get_db_connection()
        cur = con.cursor()
        cur.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (hashed_new_password, session["id"]),
        )
        con.commit()
        con.close()

        return render_template("profile.html", message="Password updated successfully")

    else:
        return render_template("profile.html")


# Function to create a new appointment
@app.route("/make_appointment", methods=["POST"])
def make_appointment():
    if request.method == "POST":
        student = request.form.get("student")
        lecturer = request.form.get("lecturer")
        appointment_date = request.form.get("appointment_date")
        appointment_time = request.form.get("appointment_time")
        purpose = request.form.get("purpose")

        if student and lecturer and appointment_date and appointment_time and purpose:
            create_appointment(
                student,
                lecturer,
                appointment_date,
                appointment_time,
                purpose,
                status="Pending",
            )

            return render_template(
                "appointment.html", message="Appointment created successfully"
            )
        else:
            return render_template(
                "appointment.html", message="Missing required field(s)"
            )
    else:
        return render_template("appointment.html")


# Functionn to list a student's appointment(s)
@app.route("/appointments", methods=["GET"])
def list_appointments():
    student = request.args.get("student")
    if student:
        appointments = get_appointments(student)
        return render_template("appointments.html", appointments=appointments)
    else:
        return render_template("appointment.html", message="No student specified")


@app.route("/update_appointment", methods=["POST"])
def update_appointments(appointment_id):
    if request.method == "POST":
        new_date = request.form.get("new_date")
        new_time = request.form.get("new_time")
        new_purpose = request.form.get("new_purpose")

        update_appointment(appointment_id, new_date, new_time, new_purpose)

        return redirect(url_for("list_appointments"))


@app.route("/delete_appointment", methods=["POST"])
def delete_appointment(appointment_id):
    if request.method == "POST":

        delete_appointment(appointment_id)

        return redirect(url_for("list_appointments"))


@app.route("/flash")
def flash():

    return render_template("messageflashing.html")


@app.route("/appointment")
def appointment():
    return render_template("appointment.html")


@app.route("/appointment2")
def appointment2():
    return render_template("appointment2.html")


@app.route("/invoice")
def render_template_invoice():
    return render_template("invoice.html")


@app.route("/admin")
def admin():
    return render_template("admin.html")


@app.route("/usercontrol")
def usercontrol():
    return render_template("usercontrol.html")


@app.route("/appointmentcontrol")
def appointmentcontrol():
    return render_template("appointment_control.html")


@app.route("/changepassword")
def changepassword():
    return render_template("changepassword.html")


@app.route("/history")
def history():
    return render_template("history.html")


@app.route("/faculty")
def faculty():
    # Retrieve faculty information from the database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT faculty_name, faculty_image FROM facultyhub")
    faculty_info = cursor.fetchall()
    conn.close()

    # Render the faculty.html template with the faculty_info variable
    return render_template("faculty.html", faculty_info=faculty_info)


@app.route("/facultyhub/<int:hub_id>", methods=["GET"])
def faculty_hub_page(hub_id=None):
    try:
        if hub_id:
            # Retrieve faculty hub information from the database based on hub_id
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, image_path FROM facultyhub WHERE id = ?", (hub_id,)
            )
            faculty_hub = cursor.fetchone()
            conn.close()

            if faculty_hub:
                # Render the faculty hub page with the relevant information
                return render_template("facultyhub.html", faculty_hub=faculty_hub)
            else:
                # If faculty hub not found, render an error page or redirect to another page
                return render_template("error.html", message="Faculty Hub Not Found")
        else:
            # Handle the case when hub_id is not provided
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
            # Save image to server
            if not os.path.exists(app.config["UPLOAD_FOLDER"]):
                os.makedirs(app.config["UPLOAD_FOLDER"])

            image_path = os.path.join(
                app.config["UPLOAD_FOLDER"], faculty_image.filename
            )
            print("Image Path:", image_path)  # Debugging print statement

            faculty_image.save(image_path)

            # Insert faculty hub info into database
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO facultyhub (faculty_name, faculty_image) VALUES (?, ?)",
                (faculty_name, image_path),
            )
            conn.commit()

            conn.close()
            print("Faculty hub created successfully!")  # Debugging print statement
            return redirect(url_for("create_faculty_hub"))
        except Exception as e:
            print("Error occurred:", e)  # Debugging print statement
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


@app.route("/signoutflash")
def signoutflash():
    return render_template("signoutflash.html")


@app.route("/signoutflash2")
def signoutflash2():
    return render_template("signoutflash2.html")


@app.route("/signupflash")
def sigupflash():
    return render_template("signupflash.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/signoutflash")


@app.route("/create_booking", methods=["POST"])
def create_booking():
    if request.method == "POST":
        email = request.form.get("email")
        booking_id = random.randint(10000, 99999)

        # Insert the booking into the database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            " ",
            (email, booking_id),
        )
        conn.commit()
        conn.close()

        # Redirect to the invoice page with the booking ID
        return redirect(url_for("invoice", booking_id=booking_id))


@app.route("/invoice/<int:booking_id>")
def invoice(booking_id):
    # Retrieve the booking details from the database using the booking ID
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(" ", (booking_id,))
    booking = cursor.fetchone()
    conn.close()

    if booking:
        # Render the invoice template with the booking details
        return render_template("invoice.html", booking=booking)
    else:
        # If booking not found, render an error page or redirect to another page
        return render_template("error.html", message="Booking Not Found")


if __name__ == "__main__":
    # Run the application
    app.run(debug=True, port=6969)
