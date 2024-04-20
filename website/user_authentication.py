
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy


app = Flask(__name__)                          #username:passowrd@hostname:post/database_name
app.config["SQALCHEMY_DATABASE_URL"] = "mysql://root:MySQLYyY050904@127.0.0.1:3306/user_authentication"
app.config["SQALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


class User(db.Model):
    user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(255), unique=True nullable=False)
    username = db.Column(db.string(255), unique=True nullable=False)
    phone_number = db.Column(db.string(100), unique=True nullable=False)
    last_login = db.Column(db.TIMESTAMP, nullable=False, default=None)
    created_at = db.Column(db.TIMESTAMP, nullable=False, default=db.func.current_timestamp())
    credentials = db.relationship("Credential", backref="user", lazy=True) #create relationship between two tables
    
class Credential(db.Model):
    credential_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.user_id"), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    

@app.route("/create_user", methods=["POST"])
def create_user():
    data = request.json #extracts json data from http request to python dictionary
    if not all(key in data for key in ["email", "username", "phone_number"]): #check if any missing fields
        return jsonify({"message": "Missing required fields"}), 400
    
    new_user = User(email=data["email"], username=data["username"], phone_number=data["phone_number"])
    db.session.add(new_user)
    try:
        db.session.commit()
        return jsonify({"message": "User created successfully"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Error creating user: {str(e)}"}), 500
    
@app.route('/create_credential', methods=['POST'])
def create_credential():
    data = request.json
    if not all(key in data for key in ["email", "password_hash"]):
        return jsonify({"message": "Missing required fields"}), 400
    
    user = User.query.filter_by(email=data["email"].first())
    if not user:
            return jsonify({"message": "User does not exist"}), 404 
    
    new_credential = Credential(user_id=user.user_id, password_hash=data["password_hash"])
    db.session.add(new_credential)
    try:
        db.session.commit()
        return jsonify({"message": "Credential created successfully"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Error creating crendential: {str(e)}"}), 500
    

app.run(debug=True)
        
        

    

    