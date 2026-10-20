import secrets
from datetime import datetime, timezone, timedelta

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    abort,
)
from werkzeug.security import generate_password_hash

from models import db, User, PasswordResetToken

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def login_required(f):
    """Require the user to be logged in."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login", next=request.full_path))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Require the user to be an administrator."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            abort(403)
        user = User.query.get(session["user_id"])
        if user is None or not user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Register a new user account."""
    if "user_id" in session:
        return redirect(url_for("user.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        display_name = request.form.get("display_name", "").strip()
        confirm = request.form.get("confirm_password", "")

        # Validation
        errors = []
        if not email or "@" not in email:
            errors.append("Please enter a valid email address.")
        if User.query.filter_by(email=email).first():
            errors.append("An account with this email already exists.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if not display_name:
            errors.append("Please enter a display name.")

        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("auth/register.html"), 400

        # Create user
        user = User(
            email=email,
            display_name=display_name,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash("Account created successfully. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Log in an existing user."""
    if "user_id" in session:
        return redirect(url_for("user.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        next_page = request.form.get("next", "") or url_for("user.dashboard")

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password) and user.is_active:
            session["user_id"] = user.id
            session.permanent = True
            user.last_login_at = datetime.now(timezone.utc)
            db.session.commit()
            flash(f"Welcome back, {user.display_name or user.email}!", "success")
            return redirect(next_page)

        # Generic error message
        flash("Invalid email or password.", "danger")
        return render_template("auth/login.html"), 401

    next_page = request.args.get("next", "")
    return render_template("auth/login.html", next=next_page)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Log out the current user."""
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("public.landing"))


# ---------------------------------------------------------------------------
# Password Reset
# ---------------------------------------------------------------------------

@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password_request():
    """Request a password reset email."""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        user = User.query.filter_by(email=email).first()

        if user:
            # Generate reset token
            token = secrets.token_urlsafe(32)
            reset_token = PasswordResetToken(
                user_id=user.id,
                token=token,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            db.session.add(reset_token)
            db.session.commit()

            # In production, send email with reset link
            # For local dev, show the token
            reset_url = url_for("auth.reset_password_confirm", token=token, _external=True)
            flash(
                f"Password reset link generated (dev mode): {reset_url}",
                "info",
            )
        else:
            # Don't reveal whether the email exists
            flash(
                "If an account with that email exists, a password reset link has been generated.",
                "info",
            )

        return redirect(url_for("auth.login"))

    return render_template("auth/reset_request.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password_confirm(token):
    """Confirm password reset with token."""
    reset_token = PasswordResetToken.query.filter_by(token=token).first()

    if not reset_token or not reset_token.is_valid():
        flash("Invalid or expired password reset link.", "danger")
        return redirect(url_for("auth.reset_password_request"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return render_template("auth/reset_confirm.html", token=token), 400
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("auth/reset_confirm.html", token=token), 400

        user = User.query.get(reset_token.user_id)
        if user:
            user.set_password(password)
            reset_token.used = True
            db.session.commit()
            flash("Password updated successfully. Please log in.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/reset_confirm.html", token=token)


# ---------------------------------------------------------------------------
# Helper: Get current user
# ---------------------------------------------------------------------------

def current_user():
    """Get the current logged-in user or None."""
    if "user_id" not in session:
        return None
    return User.query.get(session["user_id"])
