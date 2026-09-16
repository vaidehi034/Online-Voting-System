from flask import Flask, render_template, request, redirect, url_for, session
import mysql.connector
import bcrypt
import os

app = Flask(__name__)

# Session secret
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-before-deployment"
)


# =========================
# DATABASE CONNECTION
# =========================

def connect_db():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "Movie@123"),
        database=os.environ.get(
            "DB_NAME",
            "online_voting_system"
        )
    )


# =========================
# HOME
# =========================

@app.route("/")
def home():

    if "user_id" in session:
        return redirect(url_for("dashboard"))

    return render_template("index.html")


# =========================
# LOGIN
# =========================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or not password:
            return render_template(
                "index.html",
                login_error="Email and password are required."
            )

        conn = None
        cursor = None

        try:

            conn = connect_db()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT user_id, name, email, password, has_voted
                FROM users
                WHERE email = %s
                """,
                (email,)
            )

            user = cursor.fetchone()

            if not user:
                return render_template(
                    "index.html",
                    login_error="Invalid credentials!"
                )

            user_id = user[0]
            name = user[1]
            user_email = user[2]
            stored_password = user[3]

            password_valid = False

            # Bcrypt password
            if stored_password:

                try:
                    password_valid = bcrypt.checkpw(
                        password.encode(),
                        stored_password.encode()
                    )

                except ValueError:
                    password_valid = False

            # Legacy plain-text password
            if not password_valid and stored_password == password:

                password_valid = True

                new_hash = bcrypt.hashpw(
                    password.encode(),
                    bcrypt.gensalt()
                ).decode()

                cursor.execute(
                    """
                    UPDATE users
                    SET password = %s
                    WHERE user_id = %s
                    """,
                    (new_hash, user_id)
                )

                conn.commit()

            if not password_valid:

                return render_template(
                    "index.html",
                    login_error="Invalid credentials!"
                )

            # Store user in session
            session["user_id"] = user_id
            session["user_name"] = name
            session["user_email"] = user_email

            session["is_admin"] = (
                user_email.lower() == "admin"
            )

            return redirect(url_for("dashboard"))

        except mysql.connector.Error as error:

            return render_template(
                "index.html",
                login_error=f"Database error: {error}"
            )

        finally:

            if cursor:
                cursor.close()

            if conn:
                conn.close()

    return render_template("index.html")


# =========================
# REGISTER
# =========================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not name or not email or not password:

            return render_template(
                "register.html",
                register_error="All fields required!"
            )

        hashed_password = bcrypt.hashpw(
            password.encode(),
            bcrypt.gensalt()
        ).decode()

        conn = None
        cursor = None

        try:

            conn = connect_db()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO users
                (name, email, password)
                VALUES (%s, %s, %s)
                """,
                (name, email, hashed_password)
            )

            user_id = cursor.lastrowid

            conn.commit()

            cursor.execute(
                """
                INSERT INTO user_profiles (user_id)
                VALUES (%s)
                """,
                (user_id,)
            )

            conn.commit()

            return redirect(
                url_for("home", registered="1")
            )

        except mysql.connector.Error:

            if conn:
                conn.rollback()

            return render_template(
                "register.html",
                register_error="Email already exists or database error."
            )

        finally:

            if cursor:
                cursor.close()

            if conn:
                conn.close()

    return render_template("register.html")


# =========================
# DASHBOARD
# =========================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect(url_for("home"))

    conn = None
    cursor = None

    try:

        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM votes")
        total_votes = cursor.fetchone()[0]

        return render_template(
            "dashboard.html",
            user_name=session.get("user_name"),
            user_email=session.get("user_email"),
            is_admin=session.get("is_admin", False),
            total_users=total_users,
            total_votes=total_votes
        )

    except mysql.connector.Error as error:

        return f"Database error: {error}"

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()


# =========================
# VOTING
# =========================

@app.route("/voting", methods=["GET", "POST"])
def voting():

    if "user_id" not in session:
        return redirect(url_for("home"))

    user_id = session["user_id"]

    conn = None
    cursor = None

    try:

        conn = connect_db()
        cursor = conn.cursor()

        # Check whether user already voted
        cursor.execute(
            """
            SELECT has_voted
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        user = cursor.fetchone()

        if not user:
            return redirect(url_for("logout"))

        has_voted = bool(user[0])

        # Submit vote
        if request.method == "POST":

            if has_voted:

                return render_template(
                    "voting.html",
                    candidates=[],
                    has_voted=True,
                    error="You have already voted."
                )

            candidate_id = request.form.get(
                "candidate_id"
            )

            if not candidate_id:

                return render_template(
                    "voting.html",
                    candidates=[],
                    has_voted=False,
                    error="Please select a candidate."
                )

            # Check candidate
            cursor.execute(
                """
                SELECT candidate_id
                FROM candidates
                WHERE candidate_id = %s
                """,
                (candidate_id,)
            )

            candidate = cursor.fetchone()

            if not candidate:

                return render_template(
                    "voting.html",
                    candidates=[],
                    has_voted=False,
                    error="Invalid candidate selected."
                )

            # Insert vote
            cursor.execute(
                """
                INSERT INTO votes
                (user_id, candidate_id)
                VALUES (%s, %s)
                """,
                (user_id, candidate_id)
            )

            # Mark user as voted
            cursor.execute(
                """
                UPDATE users
                SET has_voted = TRUE
                WHERE user_id = %s
                """,
                (user_id,)
            )

            conn.commit()

            return render_template(
                "voting.html",
                candidates=[],
                has_voted=True,
                error="Your vote has been submitted successfully!"
            )

        # Load candidates
        cursor.execute(
            """
            SELECT candidate_id,
                   candidate_name,
                   party_name
            FROM candidates
            """
        )

        candidates = cursor.fetchall()

        return render_template(
            "voting.html",
            candidates=candidates,
            has_voted=has_voted
        )

    except mysql.connector.Error as error:

        if conn:
            conn.rollback()

        return render_template(
            "voting.html",
            candidates=[],
            has_voted=False,
            error=f"Database error: {error}"
        )

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()


# =========================
# LOGOUT
# =========================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("home"))


# =========================
# RUN APPLICATION
# =========================

if __name__ == "__main__":
    app.run(debug=True)