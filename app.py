from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import random
import os
import bcrypt
from db_functions import get_db_connection, signup, login, hash_password

app = Flask(__name__)

# Initialize the database connection
get_db_connection()


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/signup", methods=["GET", "POST"])
def signup_route():
    if request.method == "POST":
        # call da signup function from db_functions and pass the request object
        return signup(request)
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login_route():
    if request.method == "POST":
        # call da login function from db_functions
        return login(request.form["email"], request.form["password"])
    return render_template("login.html")


@app.route("/appointment")
def appointment():
    return render_template("appointment.html")


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
            "INSERT INTO bookings (email, booking_id) VALUES (?, ?)",
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
    cursor.execute("SELECT * FROM bookings WHERE booking_id = ?", (booking_id,))
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
    app.run(debug=True, port=8000)
