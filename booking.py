import random
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from user_authentication import User

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = (
    "mysql://root:MySQLYyY050904@127.0.0.1:3306/user_authentication"
)

db = SQLAlchemy()
db.init_app(app)


# Define Booking model
class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    # Add more fields such as date, time, service, etc.........


@app.route("/appointment", methods=["GET", "POST"]) 
def book_appointment():
    if request.method == "POST":
        # Assuming the user is logged in, might need to implement user authentication
        user_id = request.form.get(
            "user_id"
        )  # Assuming user_id is provided in the form
        # assuming user hav a form with necessary booking information
        # extract the necessary booking information from the form
        # For example:
        # date = request.form.get("date")
        # time = request.form.get("time")
        # service = request.form.get("service")

        # Create a new booking object
        new_booking = Booking(user_id=user_id)  # Add other fields here

        # Add the new booking to the database
        db.session.add(new_booking)
        db.session.commit()

        # Generate a unique booking ID
        booking_id = generate_booking_id()

        # Redirect to the invoice page with the booking ID
        return redirect(url_for("invoice", booking_id=booking_id))

    # Render the booking form
    return render_template("home.html")


def generate_booking_id():
    # Generate a random booking ID here

    return random.randint(100000, 999999)


@app.route("/invoice/<int:booking_id>")
def invoice(booking_id):
    # Render the invoice page with the booking ID
    return render_template("invoice.html", booking_id=booking_id)
