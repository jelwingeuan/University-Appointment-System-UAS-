from flask import Blueprint, request, redirect, render_template
from models import db, User

auth = Blueprint("auth", __name__, url_prefix="/auth")

@auth.route('/signup', methods=['POST'])
def signup():
    email = request.form.get('email')
    phone_number = request.form.get('phone_number')
    password = request.form.get('password')

    if not email or not phone_number or not password:
        return 'Missing required fields', 400

    # Check if email or phone number already exists
    existing_user = User.query.filter((User.email == email) | (User.phone_number == phone_number)).first()
    if existing_user:
        return 'User already exists', 400

    new_user = User(email=email, phone_number=phone_number, password=password)
    db.session.add(new_user)
    db.session.commit()

    return redirect('/login')

@auth.route('/login', methods=['POST'])
def login():
    email = request.form.get('email')
    password = request.form.get('password')

    if not email or not password:
        return 'Missing email or password', 400

    user = User.query.filter_by(email=email).first()

    if not user or user.password != password:
        return 'Invalid email or password', 401

    # Redirect to the home page after successful login
    return redirect('/')


