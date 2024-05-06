from flask import Flask, render_template, request, redirect, url_for
from flask import session, flash
from flask_login import LoginManager, UserMixin, login_required, current_user
from db_functions import update_user_info
import sqlite3
import bcrypt
import random
import os 

app = Flask(__name__)
login_manager = LoginManager()
login_manager.init_app(app)
app.secret_key = 'jelwin'
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


class User(UserMixin):
    def __init__(self, user_id):
        self.id = user_id


# function to get database connection
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
        return User(user['id'])
    else:
        return None


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/about")
def about():
    return render_template("about.html")


# function for hashed password
def hash_password(password):
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed_password.decode("utf-8")


# route for "sign up"
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        role = request.form.get("role")
        faculty = request.form.get("faculty")
        username = request.form.get("username")
        email = request.form.get("email")
        phone_number = request.form.get("phone_number")
        password = request.form.get("password")

        hashed_password = hash_password(password)

        con = get_db_connection()
        cur = con.cursor()

        # check if email already exists
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
            return redirect('/signinflash')
    else:
        return render_template("signup.html")


# route for "log in"
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        if email == "admin@example.com" and password == "123":
            session['logged_in'] = True
            return redirect('/admin')
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
                session['logged_in'] = True
                return redirect('/flash')
            else:
                return render_template("login.html", message="Invalid email or password")
    else:
        return render_template("login.html")


# route for updating user information
@app.route("/update_user_info", methods=["POST"])
@login_required
def update_user():
    if request.method == "POST":
        faculty = request.form.get("faculty")
        username = request.form.get("username")
        email = request.form.get("email")
        phone_number = request.form.get("phone_number")

        update_user_info(current_user.id, faculty, username, email, phone_number)

        return redirect(url_for("profile"))


# route for changing password
@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        # Verify if new password and confirm password match
        if new_password != confirm_password:
            return render_template("profile.html", message= "New password and confirm password do not match")

        # Verify if the current password is correct
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("SELECT password FROM users WHERE id = ?", (current_user.id,))
        user_data = cur.fetchone()

        if not user_data or not bcrypt.checkpw(current_password.encode("utf-8"), user_data["password"].encode("utf-8")):
            return render_template("profile.html", message= "Incorrect current password")

        # Update the password in the database
        hashed_new_password = hash_password(new_password)
        con = get_db_connection()
        cur = con.cursor()
        cur.execute("UPDATE users SET password = ? WHERE id = ?", (hashed_new_password, current_user.id))
        con.commit()
        con.close()

        return render_template("profile.html", message= "Password updated successfully")

    else:
        return render_template("profile.html")


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

@app.route("/faculty")
def faculty():
    return render_template("faculty.html")

@app.route("/usercontrol")
def usercontrol():
    return render_template("usercontrol.html")

@app.route("/appointmentcontrol")
def appointmentcontrol():
    return render_template("appointment_control.html")

@app.route("/changepassword")
def changepassword():
    return render_template("changepassword.html")

@app.route("/facultyhub/<int:hub_id>", methods=["GET"])
def faculty_hub_page(hub_id=None):
    try:
        if hub_id:
            # Retrieve faculty hub information from the database based on hub_id
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT name, image_path FROM facultyhub WHERE id = ?", (hub_id,))
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
            return render_template("error.html", message="Please provide a valid Faculty Hub ID")
    except Exception as e:
        print("Error in faculty_hub_page:", e)
        return render_template("error.html", message="An error occurred while processing your request")




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

@app.route("/signinflash")
def signinflash():
    return render_template("signinflash.html")

@app.route('/profile')
def profile():
    return render_template("profile.html")

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/signoutflash')


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
