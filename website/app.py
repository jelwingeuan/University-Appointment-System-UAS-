from flask import Flask, Blueprint, render_template
from models import User, create_dummy_accounts
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

app = Flask(__name__)

from routes import auth

app.register_blueprint(auth)


@app.route("/")
def home():
    return render_template("home.html")


# Route to render the signup form
@app.route("/signup", methods=["GET"])
def render_signup_form():
    return render_template("signup.html")


# Route to render the login form
@app.route("/login", methods=["GET"])
def render_login_form():
    return render_template("login.html")


if __name__ == "__main__":
    # Run the application
    app.run(debug=True, port=8000)
