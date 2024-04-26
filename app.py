from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = (
    "mysql://root:MySQLYyY050904@127.0.0.1:3306/user_authentication"
)

# create SQLAlchemy obj
db = SQLAlchemy()

# initialize SQLAlchemy with the Flask app
db.init_app(app)

# import models after initializing SQLAlchemy
from user_authentication import User


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/about", methods=["GET"])
def about():
    return render_template("about.html")


@app.route("/signup", methods=["GET", "POST"])
def render_signup_form():
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def render_login_form():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            # Redirect to the home page upon successful login
            return redirect(url_for("home"))

        # If email/password is invalid, render login page with a message
        return render_template("login.html", message="Invalid email or password")

    # If request method is GET, render the login page
    return render_template("login.html")


@app.route("/appointment", methods=["GET"])
def appointment():
    return render_template("appointment.html")


@app.route("/admin", methods=["GET"])
def admin():
    return render_template("admin.html")


if __name__ == "__main__":
    # Run the application
    app.run(debug=True, port=5000)
