from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import random
import os
from db_functions import get_db_connection, signup, login

app = Flask(__name__)

get_db_connection()

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/signup", methods=["GET", "POST"])
def signup_route():
    signup()


@app.route("/login", methods=["GET", "POST"])
def login_route():
    login()


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
