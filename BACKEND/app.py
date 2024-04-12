from flask import Flask
from views import auth

app = Flask(__name__)

# Registers the 'auth' blueprint with the application. #
app.register_blueprint(auth)


if __name__ == "__main__":
    app.run(debug=True, port=8000)
