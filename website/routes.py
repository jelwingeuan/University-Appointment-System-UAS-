from flask import Blueprint, render_template

auth = Blueprint("auth", __name__, url_prefix="/auth")


@auth.route("/")
def home():
    return render_template("home.html")
