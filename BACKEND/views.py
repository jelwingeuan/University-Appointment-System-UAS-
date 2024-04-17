from flask import Blueprint, render_template, request, redirect, url_for

auth = Blueprint("auth", __name__, url_prefix="/auth")

# Defines a route for the login page (/login). The route accepts both 'GET' and 'POST' requests. If it receives a 'POST' request, it extracts the username and password from the form data, checks if they are valid (in this case, we're just checking if the username is 'admin' and the password is 'password'), and redirects the user to the home page if the credentials are correct. If the credentials are incorrect, it renders the login page again with an error message. #
@auth.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        # For here, typically check the username and password against a database #
        # For simplicity, let's assume username is 'joebiden' and password is 'maga' #
        if username == "joebiden" and password == "maga":
            return redirect(url_for("auth.home"))
        else:
            return render_template("login.html", error="Invalid username or password")
    return render_template("login.html")


@auth.route("/")
def home():
    return render_template("home.html")
