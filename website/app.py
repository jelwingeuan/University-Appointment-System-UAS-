from flask import Flask, Blueprint, render_template, request,redirect
from models import User, create_dummy_accounts
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

app = Flask(__name__)

from routes import auth

app.register_blueprint(auth)

# Routes for the existing pages
# link lead to this page

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/about", methods=['GET'])
def about():
    return render_template("about.html")


@app.route("/login", methods=['GET','POST'])
def render_login_form():
    return render_template('login.html')  # Redirect to the login page
    


@app.route("/signup", methods=['GET'])
def render_signup_form():
    return render_template("signup.html")


@app.route("/appointment", methods=['GET'])
def appointment():
    return render_template("appointment.html")


if __name__ == "__main__":
    # Run the application
    app.run(debug=True, port=5000)
