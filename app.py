from flask import Flask, Blueprint, render_template, request,redirect
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/about", methods=['GET'])
def about():
    return render_template("about.html")


@app.route("/login", methods=['GET','POST'])
def login():
    return render_template('login.html')  # Redirect to the login page


@app.route("/signup", methods=["GET", "POST"])
def signup():
    email = request.form.get("email")
    phone_number = request.form.get("phone_number")
    password = request.form.get("password")

    if not email or not phone_number or not password:
        return "Missing Required Fields", 400

    # Check if email or phone number already exists
    existing_user = User.query.filter(
        (User.email == email) | (User.phone_number == phone_number)
    ).first()
    if existing_user:
        return "User already exists", 400

    new_user = User(email=email, phone_number=phone_number, password=password)
    db.session.add(new_user)
    db.session.commit()

    return redirect("/login")


@app.route("/appointment", methods=['GET'])
def appointment():
    return render_template("appointment.html")


if __name__ == "__main__":
    # Run the application
    app.run(debug=True, port=5000)
