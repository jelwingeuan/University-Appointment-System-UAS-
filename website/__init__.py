from app import app
from views import auth

# Register the auth blueprint with the Flask application
app.register_blueprint(auth)
