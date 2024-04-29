from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import bcrypt


app = Flask(__name__)


# function to get database connection
def get_db_connection():
    con = sqlite3.connect("database.db")
    con.row_factory = sqlite3.Row
    return con


# function for hashed password
def hash_password(password):
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed_password.decode("utf-8")


# function for "sign up"
def signup():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        phone_number = request.form.get("phone_number")
        password = request.form.get("password")

        hashed_password = hash_password()

        con = get_db_connection()
        cur = con.cursor()

        # check if email already exists
        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cur.fetchone()

        if user:
            con.close()
            return render_template(
                "signup.html", message="User with this email already exists"
            )
        else:
            cur.execute(
                "INSERT INTO users (username, email, phone_number, password) VALUES (?, ?, ?, ?)",
                (username, email, phone_number, hashed_password),
            )
            con.commit()
            con.close()
            return redirect(url_for("login"))
    else:
        return render_template("signup.html")


# function for "log in"
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        con = get_db_connection()
        cur = con.cursor()
        cur.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        )
        user = cur.fetchone()
        
        # check if the password provided by user is the same as the hashed pw in db
        if user and bcrypt.checkpw(password.encode("utf-8"), user['password'].encode("utf-8")):
            
            return redirect(url_for("home"))
        else:
            
            return render_template("login.html", message="Invalid email or password")
    else:
        return render_template("login.html")
    