from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = 'secret123'          # change later for production
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
db = SQLAlchemy(app)

# ─────────── DATABASE MODELS ───────────
class User(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))
    role     = db.Column(db.String(10))          # 'admin' or 'employee'

class Employee(db.Model):
    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))

class Issue(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    category      = db.Column(db.String(50))
    other_specify = db.Column(db.String(100))
    client_name   = db.Column(db.String(100))
    status        = db.Column(db.String(20))     # Solved / Not Solved
    employee_id   = db.Column(db.Integer, db.ForeignKey('employee.id'))

# ─────────── AUTH ROUTES ───────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form['username']
        p = request.form['password']
        user = User.query.filter_by(username=u, password=p).first()
        if not user:
            return render_template('login.html', error='Invalid credentials')
        session['user_id'] = user.id
        session['username'] = user.username
        session['role'] = user.role
        return redirect(url_for('index') if user.role == 'admin' else url_for('employee_dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─────────── ADMIN PAGES ───────────
@app.route('/')
def index():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    return render_template('index.html', username=session['username'])

# (pages for adding / viewing employees & issues will be added later)

# ─────────── EMPLOYEE DASHBOARD ───────────
@app.route('/employee_dashboard')
def employee_dashboard():
    if session.get('role') != 'employee':
        return redirect(url_for('login'))
    employee = Employee.query.filter_by(name=session['username']).first()
    issues = Issue.query.filter_by(employee_id=employee.id).all() if employee else []
    return render_template('employee_dashboard.html', issues=issues)

# ─────────── ONE‑TIME DB SEED ───────────
@app.before_first_request
def create_tables():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        db.session.add(User(username='admin', password='admin123', role='admin'))
        db.session.commit()

# ─────────── MAIN ───────────
if __name__ == '__main__':
    app.run(debug=True)
