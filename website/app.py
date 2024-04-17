from flask import Flask, render_template
from models import db, create_dummy_accounts

app = Flask(__name__)

# Import routes after initializing Flask app to avoid circular import issues
from routes import auth

# Register blueprints
app.register_blueprint(auth)


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/login")
def login():
    return render_template("login.html")


if __name__ == "__main__":
    # Run the application
    app.run(debug=True, port=5000)

    