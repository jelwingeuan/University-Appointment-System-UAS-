from flask import Blueprint, request, redirect, render_template
from models import db, User,create_dummy_accounts, Credential

auth = Blueprint("auth", __name__, url_prefix="/auth")


@auth.route("/signup", methods=['GET','POST'])
def signup():
    email = request.form.get("email")
    phone_number = request.form.get("phone_number")
    password = request.form.get("password")

    if not email or not phone_number or not password:
        return "Missing required fields", 400

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


@auth.route("/login", methods=['POST'])
def login():
    email = request.form.get("email")
    password = request.form.get("password")

    # Dummy user data
    dummy_users_data = [
        {"email": "joebiden@gmail.com", "password": "Potus_4646"},
        {"email": "donaldtrump@gmail.com", "password": "Potus_4545"},
    ]

    # Check if the entered email and password match any dummy account
    for user_data in dummy_users_data:
        if email == user_data["email"] and password == user_data["password"]:
            return redirect('/')  # Redirect to the home page

    return redirect('/login')  # Redirect to the login page
    
