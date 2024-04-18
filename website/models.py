from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)


class Credential(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    user = db.relationship("User", backref=db.backref("credentials", lazy=True))


def create_dummy_accounts():
    from models import User, Credential  # Importing models from the same file

    # Dummy user data
    users_data = [
        {"email": "joebiden@gmail.com", "password": "Potus_4646"},
        {"email": "donaldtrump@gmail.com", "password": "Potus_4545"},
    ]

    for user_data in users_data:
        user = User(email=user_data["email"])
        db.session.add(user)

        # Dummy credential data
        credential = Credential(
            user=user, password_hash=user_data["password"]
        )  # Using the relationship directly
        db.session.add(credential)

    # Commit all changes at once
    db.session.commit()
