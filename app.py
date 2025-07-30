"""
Issue Tracker  —  Flask + SQLAlchemy + Flask‑SocketIO
====================================================
• Three roles: admin / employee / user
• SQLite for persistence (swapable to Postgres/MySQL)
• Real‑time toast notifications
      └─ new_issue      → all admins   (namespace '/admin')
      └─ issue_assigned → hired employee (namespace '/emp/<id>')
• NO OTP flow (per your request)

DEV seed logins
---------------
Admin    : admin      / admin123
Employee : employee1  / emp123
User     : user1      / user123
"""
from __future__ import annotations

import os
import threading
import webbrowser
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, flash, redirect, render_template, request,
                   session, url_for,jsonify)
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO

# ────────────────────────────────────────────────────────────────────────
# Flask / DB / SocketIO setup
# ────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "secret123"                        # CHANGE IN PRODUCTION
app.config["SQLALCHEMY_DATABASE_URI"] = (
    "sqlite:///" + os.path.join(app.root_path, "database.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db: SQLAlchemy = SQLAlchemy(app)
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")
  # allow Flutter later

# ────────────────────────────────────────────────────────────────────────
# Database models
# ────────────────────────────────────────────────────────────────────────
class User(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    role     = db.Column(db.String(10),  nullable=False)
    email    = db.Column(db.String(100), unique=True)
    phone    = db.Column(db.String(15))



class Employee(db.Model):
    id      = db.Column(db.Integer, primary_key=True)
    name    = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    user    = db.relationship("User")


class Issue(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    category       = db.Column(db.String(50))
    other_specify  = db.Column(db.String(100))
    client_name    = db.Column(db.String(100))
    status         = db.Column(db.String(20), default="open")  # open / assigned / Solved / Not Solved
    employee_id    = db.Column(db.Integer, db.ForeignKey("employee.id"))
    created_by     = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    location       = db.Column(db.String(60))
    location_other = db.Column(db.String(100))

# ────────────────────────────────────────────────────────────────────────
# DB initialisation & seed data
# ────────────────────────────────────────────────────────────────────────
with app.app_context():
    db.create_all()

    seed_users = [
        ("admin",     "admin123",  "admin"),
        ("employee1", "emp123",    "employee"),
        ("user1",     "user123",   "user")
    ]
    for uname, pwd, role in seed_users:
        if not User.query.filter_by(username=uname).first():
            db.session.add(User(username=uname, password=pwd, role=role))
    db.session.commit()

    # create matching Employee rows
    for u in User.query.filter_by(role="employee").all():
        if not Employee.query.filter_by(user_id=u.id).first():
            db.session.add(Employee(name=u.username.capitalize(), user_id=u.id))
    db.session.commit()

# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────
def login_required(roles: list[str] | None = None):
    def outer(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "role" not in session:
                return redirect(url_for("login"))
            if roles and session["role"] not in roles:
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped
    return outer

# ────────────────────────────────────────────────────────────────────────
# Authentication
# ────────────────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(
            username=request.form["username"],
            password=request.form["password"]
        ).first()
        if not user:
            return render_template("login.html", error="Invalid credentials")

        # duplicate keys: id + user_id help JS build namespace
        session.update({
            "id": user.id,
            "user_id": user.id,
            "username": user.username,
            "role": user.role
        })
        return redirect(url_for({
            "admin":    "index",
            "employee": "employee_dashboard",
            "user":     "user_dashboard"
        }[user.role]))
    return render_template("login.html")


@app.route("/logout")
@login_required()
def logout():
    session.clear()
    return redirect(url_for("login"))

# ────────────────────────────────────────────────────────────────────────
# Dashboards
# ────────────────────────────────────────────────────────────────────────
@app.route("/")
@login_required(["admin"])
def index():
    return render_template("index.html")


@app.route("/employee_dashboard")
@login_required(["employee"])
def employee_dashboard():
    emp = Employee.query.filter_by(user_id=session["user_id"]).first()
    issues = Issue.query.filter_by(employee_id=emp.id).order_by(Issue.created_at.desc()).all() if emp else []
    return render_template("employee_dashboard.html", issues=issues)

# ────────────── USER DASHBOARD (users see only their own issues) ───────────
@app.route('/user_dashboard')
@login_required(['user'])
def user_dashboard():
    # current logged‑in user ID
    uid = session['user_id']

    # ✅ use created_by — that’s the column defined in Issue
    issues = (Issue.query
              .filter_by(created_by=uid)
              .order_by(Issue.created_at.desc())
              .all())

    # map {employee_id: name} for the template
    employees = {e.id: e.name for e in Employee.query.all()}

    return render_template('user_dashboard.html',
                           issues=issues,
                           employees=employees)



# ────────────────────────────────────────────────────────────────────────
# Admin – manage employees & users
# ────────────────────────────────────────────────────────────────────────
@app.route("/add_employee", methods=["GET", "POST"])
@login_required(["admin"])
def add_employee():
    error = None
    if request.method == "POST":
        name    = request.form["name"].strip()
        user_id = request.form.get("user_id")
        if not name or not user_id:
            error = "Both fields required."
        elif Employee.query.filter_by(user_id=user_id).first():
            error = "User already linked."
        else:
            db.session.add(Employee(name=name, user_id=int(user_id)))
            db.session.commit()
            flash("Employee added!", "success")
            return redirect(url_for("add_employee"))

    employees = Employee.query.all()
    users     = User.query.filter_by(role="employee").all()
    return render_template("add_employee.html", employees=employees, users=users, error=error)


@app.route("/add_user", methods=["GET", "POST"])
@login_required(["admin"])
def add_user():
    error = None
    if request.method == "POST":
        username, password, role = (
            request.form["username"].strip(),
            request.form["password"].strip(),
            request.form["role"]
        )
        if not (username and password):
            error = "Username & password required."
        elif User.query.filter_by(username=username).first():
            error = "Username exists."
        else:
            db.session.add(User(username=username, password=password, role=role))
            db.session.commit()
            flash("User added!", "success")
            return redirect(url_for("add_user"))

    users = User.query.order_by(User.id.desc()).all()
    return render_template("add_user.html", users=users, error=error)

# ────────────────────────────────────────────────────────────────────────
# Issue CRUD
# ────────────────────────────────────────────────────────────────────────

@app.route("/view_issues")
@login_required(["admin"])
def view_issues():
    rng = request.args.get("range", "all")
    q   = Issue.query
    if rng == "today":
        q = q.filter(Issue.created_at >= datetime.combine(date.today(), datetime.min.time()))
    elif rng == "week":
        q = q.filter(Issue.created_at >= datetime.utcnow() - timedelta(days=7))

    issues     = q.order_by(Issue.created_at.desc()).all()
    employees  = {e.id: e.name for e in Employee.query.all()}
    employees_db = Employee.query.all()
    return render_template("view_issues.html",
                           issues       = issues,
                           employees    = employees,
                           employees_db = employees_db,
                           range        = rng)


@app.route("/assign_issue/<int:iid>", methods=["POST"])
@login_required(["admin"])
def assign_issue(iid):
    issue = Issue.query.get_or_404(iid)
    emp_id = request.form.get("emp_id")
    if emp_id:
        issue.employee_id = int(emp_id)
        issue.status      = "assigned"
        db.session.commit()

        # realtime alert to that employee
        socketio.emit("issue_assigned",
                      {"id": issue.id, "title": issue.category},
                      namespace=f"/emp/{emp_id}")

    return redirect(url_for("view_issues"))


@app.route("/edit_issue/<int:iid>", methods=["GET", "POST"])
@login_required(["admin"])
def edit_issue(iid):
    issue     = Issue.query.get_or_404(iid)
    employees = Employee.query.all()

    if request.method == "POST":
        issue.category       = request.form.get("category", "")
        issue.other_specify  = request.form.get("other_specify", "")
        issue.location       = request.form.get("location", "")
        issue.location_other = request.form.get("location_other", "")
        issue.client_name    = request.form.get("client_name", "")
        issue.status         = request.form.get("status", issue.status)
        emp_id               = request.form.get("employee_id")
        issue.employee_id    = int(emp_id) if emp_id else None
        db.session.commit()
        return redirect(url_for("view_issues"))

    return render_template("edit_issue.html", issue=issue, employees=employees)

@app.route('/profile')
@login_required(['admin', 'employee'])
def profile():
    user_id = session.get('user_id')
    role = session.get('role')

    employee = None
    if role == 'employee':
        employee = Employee.query.filter_by(user_id=user_id).first()
    else:
        user = User.query.filter_by(id=user_id).first()
    
    return render_template('profile.html', user=session, role=role, employee=employee)

# ---------- AJAX POST from modal ----------
@app.route("/add_issue", methods=["GET", "POST"])
@login_required(["admin", "user"])
def add_issue():
    employees = Employee.query.all()
    is_admin  = session["role"] == "admin"

    if request.method == "POST":
        data = request.form
        issue = Issue(
            category      = data.get("category"),
            other_specify = data.get("other_specify"),
            client_name   = data.get("client_name", session["username"]),
            status        = data.get("status", "Not Solved"),
            employee_id   = int(data["employee_id"]) if data.get("employee_id") else None,
            created_by    = session["user_id"],
            location      = data.get("location"),
            location_other= data.get("location_other")
        )
        db.session.add(issue)
        db.session.commit()

        # notify admins (only if using SocketIO)
        socketio.emit("new_issue", {"id": issue.id, "title": issue.category}, namespace="/admin")

        return redirect(url_for("add_issue"))  # Redirect after POST

    # Handle GET
    issues = Issue.query.order_by(Issue.created_at.desc()).all()
    return render_template("add_issue.html", issues=issues, employees=employees)





@app.route("/toggle_status/<int:iid>")
@login_required(["admin", "employee", "user"])
def toggle_status(iid):
    role  = session["role"]
    issue = Issue.query.get_or_404(iid)

    if role == "employee":
        emp = Employee.query.filter_by(user_id=session["user_id"]).first()
        if not emp or issue.employee_id != emp.id:
            return redirect(url_for("employee_dashboard"))

    if role == "user" and issue.created_by != session["user_id"]:
        return redirect(url_for("user_dashboard"))

    issue.status = "Solved" if issue.status != "Solved" else "Not Solved"
    db.session.commit()
    return redirect(url_for({
        "admin":    "view_issues",
        "employee": "employee_dashboard",
        "user":     "user_dashboard"
    }[role]))

# ────────────────────────────────────────────────────────────────────────
# Utility: open browser on localhost
# ────────────────────────────────────────────────────────────────────────
def open_browser():
    webbrowser.open_new("http://127.0.0.1:5000")

# ────────────────────────────────────────────────────────────────────────
# Main entry point
# ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    threading.Timer(1.0, open_browser).start()
    # IMPORTANT: use socketio.run, not app.run
    socketio.run(app, host="0.0.0.0", port=5000, debug=True) 