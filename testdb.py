from flask import Flask
from flask_pymongo import PyMongo
from pymongo.errors import ConnectionFailure

app = Flask(__name__)

# Replace this URI with your actual connection string
app.config["MONGO_URI"] = "mongodb+srv://commander:LwC72c5UL8xsF5ug@cluster0.bbqab.mongodb.net/"
mongo = PyMongo(app)

try:
    # The 'admin' command 'ping' is used to test connectivity
    mongo.cx.admin.command('ping')
    print("✅ Connected to MongoDB successfully!")
except ConnectionFailure as e:
    print("❌ Could not connect to MongoDB:", e)
