from . import db
from flask_login import UserMixin
from sqlalchemy.sql import func


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phonenumber = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)