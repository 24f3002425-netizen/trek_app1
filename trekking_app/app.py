from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
from datetime import date
from functools import wraps

app = Flask(__name__)
app.secret_key = "trekking_secret_key_123"   

DATABASE = os.path.join(os.path.dirname(__file__), "trekking.db")




def get_db():
    """Open a new database connection."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row   
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables if they do not already exist, and add a default admin."""
    conn = get_db()
    cur = conn.cursor()

    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            contact TEXT,
            role TEXT NOT NULL CHECK(role IN ('admin', 'staff', 'user')),
            status TEXT NOT NULL DEFAULT 'active'
        )
    """)
   

    # TREKS table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS treks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            difficulty TEXT NOT NULL CHECK(difficulty IN ('Easy','Moderate','Hard')),
            duration INTEGER NOT NULL,
            total_slots INTEGER NOT NULL,
            available_slots INTEGER NOT NULL,
            assigned_staff_id INTEGER,
            status TEXT NOT NULL DEFAULT 'Pending',
            start_date TEXT,
            end_date TEXT,
            description TEXT,
            FOREIGN KEY (assigned_staff_id) REFERENCES users(id)
        )
    """)
    

    # BOOKINGS table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            trek_id INTEGER NOT NULL,
            booking_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Booked',
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (trek_id) REFERENCES treks(id)
        )
    """)

    
    admin = cur.execute("SELECT * FROM users WHERE role='admin'").fetchone()
    if admin is None:
        cur.execute(
            "INSERT INTO users (name, email, password, contact, role, status) VALUES (?,?,?,?,?,?)",
            ("Admin", "admin@trek.com", generate_password_hash("admin123"), "9999999999", "admin", "active")
        )

    conn.commit()
    conn.close()




def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def role_required(role):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if session.get("role") != role:
                flash("You are not allowed to view that page.", "danger")
                return redirect(url_for("index"))
            return f(*args, **kwargs)
        return wrapper
    return decorator




@app.route("/")
def index():
    conn = get_db()
    treks = conn.execute("SELECT * FROM treks WHERE status='Open' ORDER BY id DESC LIMIT 6").fetchall()
    conn.close()
    return render_template("index.html", treks=treks)



@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        contact = request.form["contact"]
        role = request.form["role"]   # staff or user, chosen from a dropdown

        conn = get_db()
        existing = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            flash("An account with this email already exists.", "danger")
            conn.close()
            return redirect(url_for("register"))

        # staff accounts need admin approval, so status = pending
        status = "pending" if role == "staff" else "active"

        conn.execute(
            "INSERT INTO users (name, email, password, contact, role, status) VALUES (?,?,?,?,?,?)",
            (name, email, generate_password_hash(password), contact, role, status)
        )
        conn.commit()
        conn.close()

        if role == "staff":
            flash("Registration successful! Please wait for admin approval before you can login.", "info")
        else:
            flash("Registration successful! You can now login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")




@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()

        if user is None or not check_password_hash(user["password"], password):
            flash("Wrong email or password.", "danger")
            return redirect(url_for("login"))

        if user["status"] == "blacklisted":
            flash("Your account has been blacklisted. Contact admin.", "danger")
            return redirect(url_for("login"))

        if user["role"] == "staff" and user["status"] == "pending":
            flash("Your staff account is still waiting for admin approval.", "warning")
            return redirect(url_for("login"))

        # login successful - save details in session
        session["user_id"] = user["id"]
        session["name"] = user["name"]
        session["role"] = user["role"]

        flash("Logged in successfully!", "success")

        if user["role"] == "admin":
            return redirect(url_for("admin_dashboard"))
        elif user["role"] == "staff":
            return redirect(url_for("staff_dashboard"))
        else:
            return redirect(url_for("user_dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))



@app.route("/admin/dashboard")
@login_required
@role_required("admin")
def admin_dashboard():
    conn = get_db()
    total_treks = conn.execute("SELECT COUNT(*) FROM treks").fetchone()[0]
    total_users = conn.execute("SELECT COUNT(*) FROM users WHERE role='user'").fetchone()[0]
    total_staff = conn.execute("SELECT COUNT(*) FROM users WHERE role='staff'").fetchone()[0]
    total_bookings = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    pending_staff = conn.execute("SELECT COUNT(*) FROM users WHERE role='staff' AND status='pending'").fetchone()[0]
    conn.close()
    return render_template(
        "admin/dashboard.html",
        total_treks=total_treks,
        total_users=total_users,
        total_staff=total_staff,
        total_bookings=total_bookings,
        pending_staff=pending_staff
    )


@app.route("/admin/treks")
@login_required
@role_required("admin")
def admin_treks():
    conn = get_db()
    treks = conn.execute("""
        SELECT treks.*, users.name AS staff_name
        FROM treks
        LEFT JOIN users ON treks.assigned_staff_id = users.id
        ORDER BY treks.id DESC
    """).fetchall()
    conn.close()
    return render_template("admin/treks.html", treks=treks)


@app.route("/admin/treks/add", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_add_trek():
    conn = get_db()
    staff_list = conn.execute("SELECT * FROM users WHERE role='staff' AND status='approved'").fetchall()

    if request.method == "POST":
        name = request.form["name"]
        location = request.form["location"]
        difficulty = request.form["difficulty"]
        duration = request.form["duration"]
        total_slots = int(request.form["total_slots"])
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]
        description = request.form["description"]
        assigned_staff_id = request.form.get("assigned_staff_id") or None

        conn.execute("""
            INSERT INTO treks (name, location, difficulty, duration, total_slots, available_slots,
                                assigned_staff_id, status, start_date, end_date, description)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (name, location, difficulty, duration, total_slots, total_slots,
              assigned_staff_id, "Pending", start_date, end_date, description))
        conn.commit()
        conn.close()
        flash("Trek created successfully.", "success")
        return redirect(url_for("admin_treks"))

    conn.close()
    return render_template("admin/add_trek.html", staff_list=staff_list)


@app.route("/admin/treks/edit/<int:trek_id>", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_edit_trek(trek_id):
    conn = get_db()
    trek = conn.execute("SELECT * FROM treks WHERE id=?", (trek_id,)).fetchone()
    staff_list = conn.execute("SELECT * FROM users WHERE role='staff' AND status='approved'").fetchall()

    if trek is None:
        flash("Trek not found.", "danger")
        return redirect(url_for("admin_treks"))

    if request.method == "POST":
        name = request.form["name"]
        location = request.form["location"]
        difficulty = request.form["difficulty"]
        duration = request.form["duration"]
        total_slots = int(request.form["total_slots"])
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]
        description = request.form["description"]
        assigned_staff_id = request.form.get("assigned_staff_id") or None
        status = request.form["status"]

        # keep available slots in sync if total slots changed
        already_booked = trek["total_slots"] - trek["available_slots"]
        new_available = max(total_slots - already_booked, 0)

        conn.execute("""
            UPDATE treks SET name=?, location=?, difficulty=?, duration=?, total_slots=?,
                              available_slots=?, assigned_staff_id=?, status=?, start_date=?,
                              end_date=?, description=?
            WHERE id=?
        """, (name, location, difficulty, duration, total_slots, new_available,
              assigned_staff_id, status, start_date, end_date, description, trek_id))
        conn.commit()
        conn.close()
        flash("Trek updated successfully.", "success")
        return redirect(url_for("admin_treks"))

    conn.close()
    return render_template("admin/edit_trek.html", trek=trek, staff_list=staff_list)


@app.route("/admin/treks/delete/<int:trek_id>")
@login_required
@role_required("admin")
def admin_delete_trek(trek_id):
    conn = get_db()
    conn.execute("DELETE FROM treks WHERE id=?", (trek_id,))
    conn.execute("DELETE FROM bookings WHERE trek_id=?", (trek_id,))
    conn.commit()
    conn.close()
    flash("Trek deleted.", "info")
    return redirect(url_for("admin_treks"))


@app.route("/admin/staff")
@login_required
@role_required("admin")
def admin_staff():
    conn = get_db()
    staff = conn.execute("SELECT * FROM users WHERE role='staff' ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("admin/staff.html", staff=staff)


@app.route("/admin/staff/approve/<int:staff_id>")
@login_required
@role_required("admin")
def admin_approve_staff(staff_id):
    conn = get_db()
    conn.execute("UPDATE users SET status='approved' WHERE id=?", (staff_id,))
    conn.commit()
    conn.close()
    flash("Staff approved.", "success")
    return redirect(url_for("admin_staff"))


@app.route("/admin/staff/blacklist/<int:staff_id>")
@login_required
@role_required("admin")
def admin_blacklist_staff(staff_id):
    conn = get_db()
    conn.execute("UPDATE users SET status='blacklisted' WHERE id=?", (staff_id,))
    conn.commit()
    conn.close()
    flash("Staff blacklisted.", "warning")
    return redirect(url_for("admin_staff"))


@app.route("/admin/staff/unblock/<int:staff_id>")
@login_required
@role_required("admin")
def admin_unblock_staff(staff_id):
    conn = get_db()
    conn.execute("UPDATE users SET status='approved' WHERE id=?", (staff_id,))
    conn.commit()
    conn.close()
    flash("Staff account restored.", "success")
    return redirect(url_for("admin_staff"))


@app.route("/admin/users")
@login_required
@role_required("admin")
def admin_users():
    conn = get_db()
    users = conn.execute("SELECT * FROM users WHERE role='user' ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("admin/users.html", users=users)


@app.route("/admin/users/blacklist/<int:user_id>")
@login_required
@role_required("admin")
def admin_blacklist_user(user_id):
    conn = get_db()
    conn.execute("UPDATE users SET status='blacklisted' WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    flash("User blacklisted.", "warning")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/unblock/<int:user_id>")
@login_required
@role_required("admin")
def admin_unblock_user(user_id):
    conn = get_db()
    conn.execute("UPDATE users SET status='active' WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    flash("User account restored.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/bookings")
@login_required
@role_required("admin")
def admin_bookings():
    conn = get_db()
    bookings = conn.execute("""
        SELECT bookings.*, users.name AS user_name, treks.name AS trek_name
        FROM bookings
        JOIN users ON bookings.user_id = users.id
        JOIN treks ON bookings.trek_id = treks.id
        ORDER BY bookings.id DESC
    """).fetchall()
    conn.close()
    return render_template("admin/bookings.html", bookings=bookings)


@app.route("/admin/search")
@login_required
@role_required("admin")
def admin_search():
    query = request.args.get("q", "").strip()
    treks = users = staff = []
    if query:
        conn = get_db()
        like = f"%{query}%"
        treks = conn.execute("SELECT * FROM treks WHERE name LIKE ? OR location LIKE ? OR CAST(id AS TEXT)=?",
                              (like, like, query)).fetchall()
        users = conn.execute("SELECT * FROM users WHERE role='user' AND (name LIKE ? OR CAST(id AS TEXT)=?)",
                              (like, query)).fetchall()
        staff = conn.execute("SELECT * FROM users WHERE role='staff' AND (name LIKE ? OR CAST(id AS TEXT)=?)",
                              (like, query)).fetchall()
        conn.close()
    return render_template("admin/search.html", query=query, treks=treks, users=users, staff=staff)




@app.route("/staff/dashboard")
@login_required
@role_required("staff")
def staff_dashboard():
    conn = get_db()
    treks = conn.execute("SELECT * FROM treks WHERE assigned_staff_id=? ORDER BY id DESC",
                          (session["user_id"],)).fetchall()

    # count how many users registered per trek
    trek_counts = {}
    for t in treks:
        count = conn.execute("SELECT COUNT(*) FROM bookings WHERE trek_id=? AND status='Booked'",
                              (t["id"],)).fetchone()[0]
        trek_counts[t["id"]] = count
    conn.close()
    return render_template("staff/dashboard.html", treks=treks, trek_counts=trek_counts)


@app.route("/staff/trek/<int:trek_id>/update", methods=["GET", "POST"])
@login_required
@role_required("staff")
def staff_update_trek(trek_id):
    conn = get_db()
    trek = conn.execute("SELECT * FROM treks WHERE id=?", (trek_id,)).fetchone()

    if trek is None or trek["assigned_staff_id"] != session["user_id"]:
        flash("You are not assigned to this trek.", "danger")
        conn.close()
        return redirect(url_for("staff_dashboard"))

    if request.method == "POST":
        available_slots = int(request.form["available_slots"])
        status = request.form["status"]
        conn.execute("UPDATE treks SET available_slots=?, status=? WHERE id=?",
                     (available_slots, status, trek_id))
        conn.commit()
        flash("Trek updated.", "success")
        conn.close()
        return redirect(url_for("staff_dashboard"))

    conn.close()
    return render_template("staff/update_trek.html", trek=trek)


@app.route("/staff/trek/<int:trek_id>/participants")
@login_required
@role_required("staff")
def staff_participants(trek_id):
    conn = get_db()
    trek = conn.execute("SELECT * FROM treks WHERE id=?", (trek_id,)).fetchone()

    if trek is None or trek["assigned_staff_id"] != session["user_id"]:
        flash("You are not assigned to this trek.", "danger")
        conn.close()
        return redirect(url_for("staff_dashboard"))

    participants = conn.execute("""
        SELECT bookings.*, users.name AS user_name, users.contact AS user_contact
        FROM bookings JOIN users ON bookings.user_id = users.id
        WHERE bookings.trek_id=?
        ORDER BY bookings.id DESC
    """, (trek_id,)).fetchall()
    conn.close()
    return render_template("staff/participants.html", trek=trek, participants=participants)




@app.route("/user/dashboard")
@login_required
@role_required("user")
def user_dashboard():
    conn = get_db()
    bookings = conn.execute("""
        SELECT bookings.*, treks.name AS trek_name, treks.location, treks.start_date, treks.status AS trek_status
        FROM bookings JOIN treks ON bookings.trek_id = treks.id
        WHERE bookings.user_id=?
        ORDER BY bookings.id DESC
    """, (session["user_id"],)).fetchall()

    open_treks_count = conn.execute("SELECT COUNT(*) FROM treks WHERE status='Open'").fetchone()[0]
    conn.close()
    return render_template("user/dashboard.html", bookings=bookings, open_treks_count=open_treks_count)


@app.route("/user/treks")
@login_required
@role_required("user")
def user_treks():
    difficulty = request.args.get("difficulty", "")
    location = request.args.get("location", "")

    query = "SELECT * FROM treks WHERE status='Open'"
    params = []
    if difficulty:
        query += " AND difficulty=?"
        params.append(difficulty)
    if location:
        query += " AND location LIKE ?"
        params.append(f"%{location}%")
    query += " ORDER BY id DESC"

    conn = get_db()
    treks = conn.execute(query, params).fetchall()
    conn.close()
    return render_template("user/treks.html", treks=treks, difficulty=difficulty, location=location)


@app.route("/user/book/<int:trek_id>")
@login_required
@role_required("user")
def user_book_trek(trek_id):
    conn = get_db()
    trek = conn.execute("SELECT * FROM treks WHERE id=?", (trek_id,)).fetchone()

    if trek is None:
        flash("Trek not found.", "danger")
        conn.close()
        return redirect(url_for("user_treks"))

    if trek["status"] != "Open":
        flash("This trek is not open for booking.", "danger")
        conn.close()
        return redirect(url_for("user_treks"))

    if trek["available_slots"] <= 0:
        flash("Sorry, this trek is fully booked.", "danger")
        conn.close()
        return redirect(url_for("user_treks"))

    # check if already booked
    already = conn.execute("SELECT * FROM bookings WHERE user_id=? AND trek_id=? AND status='Booked'",
                            (session["user_id"], trek_id)).fetchone()
    if already:
        flash("You have already booked this trek.", "warning")
        conn.close()
        return redirect(url_for("user_treks"))

    conn.execute("INSERT INTO bookings (user_id, trek_id, booking_date, status) VALUES (?,?,?,?)",
                 (session["user_id"], trek_id, str(date.today()), "Booked"))
    conn.execute("UPDATE treks SET available_slots = available_slots - 1 WHERE id=?", (trek_id,))
    conn.commit()
    conn.close()
    flash("Trek booked successfully!", "success")
    return redirect(url_for("user_dashboard"))


@app.route("/user/booking/cancel/<int:booking_id>")
@login_required
@role_required("user")
def user_cancel_booking(booking_id):
    conn = get_db()
    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()

    if booking is None or booking["user_id"] != session["user_id"]:
        flash("Booking not found.", "danger")
        conn.close()
        return redirect(url_for("user_dashboard"))

    if booking["status"] == "Booked":
        conn.execute("UPDATE bookings SET status='Cancelled' WHERE id=?", (booking_id,))
        conn.execute("UPDATE treks SET available_slots = available_slots + 1 WHERE id=?", (booking["trek_id"],))
        conn.commit()
        flash("Booking cancelled.", "info")

    conn.close()
    return redirect(url_for("user_dashboard"))


@app.route("/user/profile", methods=["GET", "POST"])
@login_required
@role_required("user")
def user_profile():
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()

    if request.method == "POST":
        name = request.form["name"]
        contact = request.form["contact"]
        conn.execute("UPDATE users SET name=?, contact=? WHERE id=?", (name, contact, session["user_id"]))
        conn.commit()
        session["name"] = name
        flash("Profile updated.", "success")
        conn.close()
        return redirect(url_for("user_profile"))

    conn.close()
    return render_template("user/profile.html", user=user)



if __name__ == "__main__":
    init_db()  
    app.run(debug=True)
