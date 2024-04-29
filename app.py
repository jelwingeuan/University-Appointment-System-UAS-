from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import bcrypt
import random



app = Flask(__name__)


# function to get database connection
def get_db_connection():
    con = sqlite3.connect("database.db")
    con.row_factory = sqlite3.Row
    return con


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

# function for "sign up"
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
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
                "INSERT INTO users (username, email, phone_number, password) VALUES (?, ?, ?, ?)",
                (username, email, phone_number, hashed_password),
            )
            con.commit()
            con.close()
            return redirect(url_for("login"))
    else:
        return render_template("signup.html")


# function for "log in"
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        if email == "admin@example.com" and password == "123":
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
                return redirect('/flash')
            else:
                return render_template("login.html", message="Invalid email or password")
    else:
        return render_template("login.html")


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
        return render_template("error.html", message="Booking Not Found u bitch")


if __name__ == "__main__":
    # Run the application
    app.run(debug=True, port=8000)
