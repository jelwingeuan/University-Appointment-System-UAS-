from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from user_authentication import (
    User,
)  # assuming User model is defined in user_authentication module

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = (
    "mysql://root:MySQLYyY050904@127.0.0.1:3306/user_authentication"
)

db = SQLAlchemy()
db.init_app(app)


# Def of Booking model
class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


@app.route("/book", methods=["GET", "POST"])
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

        return redirect(url_for("home"))  # Redirect to home page after booking

    # Render the booking form
    return render_template("home.html")

