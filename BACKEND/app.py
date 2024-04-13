from flask import Flask, render_template
from views import auth

app = Flask(__name__)

# Registers the 'auth' blueprint with the application. #
app.register_blueprint(auth)

@app.route('/')
def home():
    return render_template('login.html')

if __name__ == "__main__":
    app.run(debug=True, port=8000)
