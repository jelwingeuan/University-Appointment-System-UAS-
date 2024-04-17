from flask import Flask, render_template, request, redirect
from flask_sqlalchemy import SQLAlchemy
from views import auth  # Assuming your auth blueprint is defined in views.py

app = Flask(__name__)

# Configuring the database connection
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # Disable modification tracking (optional but recommended)
db = SQLAlchemy(app)

# Registers the 'auth' blueprint with the application
app.register_blueprint(auth)



@app.route('/')
def home():
    return render_template('home.html')

@app.route('/login')
def login():
    return render_template('login.html')


if __name__ == "__main__":
    app.run(debug=True, port=5000)
