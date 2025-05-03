import os
import random
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_mail import Mail
from flask_pymongo import PyMongo
from bson import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
app.secret_key = os.urandom(24)

# MongoDB config
app.config["MONGO_URI"] = ""
mongo = PyMongo(app)

# Email config
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 465
app.config["MAIL_USE_SSL"] = True
app.config["MAIL_USERNAME"] = "@gmail.com"
app.config["MAIL_PASSWORD"] = ""
mail = Mail(app)

# Background scheduler
scheduler = BackgroundScheduler()
scheduler.start()

def generate_otp():
    return random.randint(100000, 999999)

def send_otp_email(email, message, subject="Your OTP"):
    try:
        msg = MIMEText(message)
        msg["Subject"] = subject
        msg["From"] = app.config["MAIL_USERNAME"]
        msg["To"] = email

        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
        server.sendmail(app.config["MAIL_USERNAME"], email, msg.as_string())
        server.quit()

        print(f"[EMAIL SENT] To: {email} | Subject: {subject} | Message: {message}")
    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send email to {email}: {e}")

def check_and_send_reminders():
    now = datetime.now().strftime("%H:%M")
    users = mongo.db.users.find()

    for user in users:
        email = user['email']
        for med in user.get('medicines', []):
            med_id = med["_id"]
            quantity = med.get('quantity', 0)
            medicine_name = med['medicine']

            # --- Send Reminder ---
            if not med.get('reminder_pending', False):
                timings = med.get('timings', {})
                for time_label, time_val in timings.items():
                    if time_val == now:
                        if quantity > 0:
                            # Send only one reminder
                            send_otp_email(
                                email,
                                f"Reminder: Take your medicine '{medicine_name}' now.",
                                "Medicine Reminder"
                            )
                            mongo.db.users.update_one(
                                {"email": email, "medicines._id": med_id},
                                {"$set": {f"medicines.$.reminder_pending": True}}
                            )
                            print(f"[REMINDER SENT] {email} reminded for '{medicine_name}' at {now}")
                        else:
                            send_otp_email(
                                email,
                                f"Stock for '{medicine_name}' is 0. Please restock immediately.",
                                "Low Stock Alert"
                            )
                            print(f"[RESTOCK ALERT] Sent to {email} for '{medicine_name}' (stock=0)")
                        break  # Stop checking other timings after the first match

            # --- Low Stock Alert ---
            if quantity < 2 and not med.get("low_stock_alert_sent", False):
                send_otp_email(
                    email,
                    f"Low stock of '{medicine_name}' ({quantity} left). Please restock.",
                    "Low Stock Alert"
                )
                mongo.db.users.update_one(
                    {"email": email, "medicines._id": med_id},
                    {"$set": {f"medicines.$.low_stock_alert_sent": True}}
                )
                print(f"[LOW STOCK ALERT] {email} warned for '{medicine_name}' (stock={quantity})")


scheduler.add_job(check_and_send_reminders, 'interval', minutes=1)

@app.route('/')
def home():
    return redirect(url_for('register'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        hashed_password = generate_password_hash(password)

        if mongo.db.users.find_one({"email": email}) or mongo.db.otp_verifications.find_one({"email": email}):
            flash("Email already registered or OTP pending verification.", "error")
            return redirect(url_for('register'))

        otp = generate_otp()
        mongo.db.otp_verifications.insert_one({
            "email": email,
            "password": hashed_password,
            "otp": otp,
            "timestamp": datetime.utcnow()
        })

        session['email'] = email
        send_otp_email(email, f"Your OTP is {otp}")
        flash("OTP sent to your email.", "info")
        return redirect(url_for('otp'))

    return render_template('register.html')

@app.route('/otp', methods=['GET', 'POST'])
def otp():
    email = session.get('email')
    if not email:
        flash("Session expired. Please register again.", "error")
        return redirect(url_for('register'))

    if request.method == 'POST':
        input_otp = int(request.form['otp'])
        record = mongo.db.otp_verifications.find_one({"email": email})

        if record and record['otp'] == input_otp:
            mongo.db.users.insert_one({
                "email": record['email'],
                "password": record['password'],
                "medicines": []
            })
            mongo.db.otp_verifications.delete_one({"email": email})
            flash("OTP verified! You can now login.", "success")
            return redirect(url_for('login'))
        else:
            flash("Invalid OTP", "error")
            return redirect(url_for('otp'))

    return render_template('otp.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = mongo.db.users.find_one({"email": email})
        if user and check_password_hash(user['password'], password):
            session['user'] = email
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid credentials.", "danger")
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    user = mongo.db.users.find_one({"email": session['user']})
    return render_template('dashboard.html', medicines=user.get('medicines', []))

@app.route('/stock', methods=['GET', 'POST'])
def stock():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        email = session['user']
        medicine = request.form['medicine']
        quantity = int(request.form['quantity'])
        timings = {}

        for time in ['morning', 'noon', 'evening', 'night']:
            if request.form.get(f'{time}_yes'):
                timings[time] = request.form.get(f'{time}_time')

        mongo.db.users.update_one(
            {"email": email},
            {"$push": {
                "medicines": {
                    "_id": ObjectId(),
                    "medicine": medicine,
                    "quantity": quantity,
                    "timings": timings,
                    "reminder_pending": False,
                    "low_stock_alert_sent": False
                }
            }}
        )
        return redirect(url_for('dashboard'))
    return render_template('stock.html')

@app.route('/take_medicine/<medicine_id>', methods=['POST'])
def take_medicine(medicine_id):
    if 'user' not in session:
        return redirect(url_for('login'))

    took = request.form.get('took_medicine')
    email = session['user']
    user = mongo.db.users.find_one({'email': email})

    for med in user['medicines']:
        if str(med['_id']) == medicine_id:
            if took == 'yes':
                new_qty = max(0, med['quantity'] - 1)
                mongo.db.users.update_one(
                    {"email": email, "medicines._id": med['_id']},
                    {"$set": {
                        "medicines.$.quantity": new_qty,
                        "medicines.$.reminder_pending": False,
                        "medicines.$.low_stock_alert_sent": False if new_qty >= 2 else True
                    }}
                )
                if new_qty < 2:
                    send_otp_email(
                        email,
                        f"Low stock of '{med['medicine']}' ({new_qty} left). Please restock.",
                        "Low Stock Alert"
                    )
            else:
                mongo.db.users.update_one(
                    {"email": email, "medicines._id": med['_id']},
                    {"$set": {"medicines.$.reminder_pending": False}}
                )
            break
    return redirect(url_for('dashboard'))

@app.route('/delete_medicine/<medicine_id>')
def delete_medicine(medicine_id):
    if 'user' not in session:
        return redirect(url_for('login'))
    email = session['user']
    mongo.db.users.update_one(
        {"email": email},
        {"$pull": {"medicines": {"_id": ObjectId(medicine_id)}}}
    )
    return redirect(url_for('dashboard'))

@app.route('/restock/<medicine_id>', methods=['POST'])
def restock(medicine_id):
    if 'user' not in session:
        return redirect(url_for('login'))
    quantity = int(request.form['restock_quantity'])
    email = session['user']
    mongo.db.users.update_one(
        {"email": email, "medicines._id": ObjectId(medicine_id)},
        {"$inc": {"medicines.$.quantity": quantity},
         "$set": {"medicines.$.low_stock_alert_sent": False}}
    )
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
