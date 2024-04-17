from flask import Blueprint, render_template, request, redirect
from app import app

# Create the auth blueprint
auth = Blueprint("auth", __name__, url_prefix="/auth")

# Define routes for the auth blueprint
@auth.route('/login', methods=['POST', 'GET'])  
def login():
    if request.method == 'POST':  
        email = request.form["email"]
        password = request.form["password"]
        if email == "joebiden@gmail.com" and password == "maga":
            return render_template('home.html')
        else:
            return render_template("login.html", error="Invalid email or password")
    return render_template('login.html')

@auth.route('/signup', methods=['GET', 'POST'])
def signup():
    return render_template("signup.html")
