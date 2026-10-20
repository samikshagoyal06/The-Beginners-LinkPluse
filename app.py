"""LinkPulse — URL Shortener & Analytics Platform

Flask application factory with blueprint registration, security headers,
rate limiting, and error handling.
"""

import os
import time
from functools import wraps
from datetime import datetime, timezone

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    abort,
    session,
)

from models import db, User
from config import Config


# ---------------------------------------------------------------------------
# Rate limiting (simple in-memory token bucket)
# ---------------------------------------------------------------------------

_rate_limit_store = {}
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 60  # max requests per window


def _check_rate_limit():
    """Return True if the request is within rate limits."""
    ip = request.remote_addr
    now = time.time()

    if ip not in _rate_limit_store:
        _rate_limit_store[ip] = (now, 1)
        return True

    last_reset, count = _rate_limit_store[ip]

    if now - last_reset > RATE_LIMIT_WINDOW:
        _rate_limit_store[ip] = (now, 1)
        return True

    if count >= RATE_LIMIT_MAX:
        return False

    _rate_limit_store[ip] = (last_reset, count + 1)
    return True


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(config_class=Config):
    """Create and configure the Flask application."""

    app = Flask(__name__)
    app.config.from_object(config_class)

    # Session configuration
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = 3600  # 1 hour

    db.init_app(app)

    with app.app_context():
        db.create_all()

    # -- Register blueprints --
    from routes.public import public_bp
    from routes.auth import auth_bp
    from routes.links import user_bp
    from routes.campaigns import campaigns_bp
    from routes.admin import admin_bp
    from routes.import_export import import_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(import_bp)

    # -- Security headers --
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        if not app.debug:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # -- Rate limiting --
    @app.before_request
    def rate_limit():
        if app.config.get("TESTING"):
            return
        if not _check_rate_limit():
            abort(429, description="Too many requests. Please try again later.")

    # -- Error handlers --
    @app.errorhandler(403)
    def forbidden(error):
        if request.path.startswith("/admin"):
            return render_template(
                "public/error.html",
                title="Access Denied",
                message="You do not have permission to access this resource.",
            ), 403
        return render_template(
            "public/error.html",
            title="Access Denied",
            message="You do not have permission to access this resource.",
        ), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template(
            "public/error.html",
            title="Page Not Found",
            message="The page you're looking for doesn't exist or may have been removed.",
        ), 404

    @app.errorhandler(429)
    def too_many_requests(error):
        return render_template(
            "public/error.html",
            title="Too Many Requests",
            message="You've made too many requests. Please wait a moment and try again.",
        ), 429

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template(
            "public/error.html",
            title="Something Went Wrong",
            message="An internal error occurred. Please try again later.",
        ), 500

    # -- Template context: inject current user --
    @app.context_processor
    def inject_user():
        if "user_id" in session:
            from routes.auth import current_user as get_current_user
            user = get_current_user()
            return {"current_user": user}
        return {"current_user": None}

    return app


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def register_cli(app):
    """Register Flask CLI commands."""
    import click

    @app.cli.command("create-admin")
    @click.option("--email", required=True, help="Admin email address")
    @click.option("--name", required=True, help="Admin display name")
    @click.option("--password", required=True, help="Admin password (min 8 chars)")
    def create_admin(email, name, password):
        """Create the first administrator account."""
        if len(password) < 8:
            click.echo("Error: Password must be at least 8 characters.")
            return

        with app.app_context():
            existing = User.query.filter_by(email=email.lower()).first()
            if existing:
                if existing.is_admin:
                    click.echo(f"User {email} is already an administrator.")
                else:
                    existing.is_admin = True
                    db.session.commit()
                    click.echo(f"User {email} promoted to administrator.")
                return

            user = User(
                email=email.lower(),
                display_name=name,
                is_admin=True,
                is_active=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            click.echo(f"Administrator created: {email}")

    @app.cli.command("create-user")
    @click.option("--email", required=True, help="User email address")
    @click.option("--name", required=True, help="User display name")
    @click.option("--password", required=True, help="User password (min 8 chars)")
    def create_user(email, name, password):
        """Create a regular user account."""
        if len(password) < 8:
            click.echo("Error: Password must be at least 8 characters.")
            return

        with app.app_context():
            existing = User.query.filter_by(email=email.lower()).first()
            if existing:
                click.echo(f"User {email} already exists.")
                return

            user = User(
                email=email.lower(),
                display_name=name,
                is_admin=False,
                is_active=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            click.echo(f"User created: {email}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

app = create_app()
register_cli(app)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
