"""Public-facing routes: landing page and error pages."""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from models import db, Link, ClickEvent, DomainBlocklist

public_bp = Blueprint("public", __name__)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _validate_url(url_str):
    """Validate that a URL uses http:// or https:// scheme."""
    if not url_str or not url_str.strip():
        return False, "Please enter a URL."
    url_str = url_str.strip()
    lower = url_str.lower()
    if not (lower.startswith("http://") or lower.startswith("https://")):
        return False, "Only HTTP and HTTPS URLs are allowed."
    return True, None


def _is_domain_blocked(url_str):
    """Check if the domain of a URL is in the blocklist."""
    from urllib.parse import urlparse
    parsed = urlparse(url_str)
    domain = parsed.netloc.lower().lstrip("www.")
    blocked = DomainBlocklist.query.filter(
        db.or_(
            DomainBlocklist.domain == domain,
            DomainBlocklist.domain == f"www.{domain}",
        )
    ).first()
    return blocked is not None


def _generate_short_code(length=8):
    """Generate a random alphanumeric short code."""
    import string
    import secrets
    alphabet = string.ascii_letters + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(length))
        if not Link.query.filter_by(short_code=code).first():
            return code


# ---------------------------------------------------------------------------
# Landing Page
# ---------------------------------------------------------------------------

@public_bp.route("/")
def landing():
    """Public landing page with URL shortening demo."""
    return render_template("public/landing.html")


# ---------------------------------------------------------------------------
# Quick Shorten (for demo — creates links without login)
# ---------------------------------------------------------------------------

@public_bp.route("/shorten", methods=["POST"])
def shorten():
    """Create a new shortened link (demo mode — no auth required)."""
    original_url = request.form.get("url", "").strip()
    alias = request.form.get("alias", "").strip()
    expires = request.form.get("expires", "").strip()

    valid, error = _validate_url(original_url)
    if not valid:
        flash(error, "danger")
        return render_template("public/landing.html"), 400

    # Check domain blocklist
    if _is_domain_blocked(original_url):
        flash("The destination domain is blocked.", "danger")
        return render_template("public/landing.html"), 400

    # Handle alias
    if alias:
        if Link.query.filter_by(alias=alias).first():
            flash("This alias is already taken. Please choose another.", "danger")
            return render_template("public/landing.html"), 400
        short_code = alias
    else:
        short_code = _generate_short_code()

    # Handle expiration
    expires_at = None
    if expires:
        from datetime import timezone, timedelta
        try:
            exp_lower = expires.lower().strip()
            if exp_lower.endswith("h"):
                hours = int(exp_lower[:-1])
                expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
            elif exp_lower.endswith("m"):
                minutes = int(exp_lower[:-1])
                expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
            elif exp_lower.endswith("d"):
                days = int(exp_lower[:-1])
                expires_at = datetime.now(timezone.utc) + timedelta(days=days)
            else:
                flash("Invalid expiration format. Use e.g. '1h', '30m', '7d'.", "danger")
                return render_template("public/landing.html"), 400
        except (ValueError, IndexError):
            flash("Invalid expiration format. Use e.g. '1h', '30m', '7d'.", "danger")
            return render_template("public/landing.html"), 400

    # For demo mode, create a system user if none exists
    from models import User
    system_user = User.query.filter_by(email="system@linkpulse.local").first()
    if not system_user:
        system_user = User(email="system@linkpulse.local", display_name="System", is_active=True)
        system_user.set_password("system")
        db.session.add(system_user)
        db.session.flush()

    link = Link(
        short_code=short_code,
        original_url=original_url,
        alias=alias if alias else None,
        user_id=system_user.id,
        expires_at=expires_at,
    )
    db.session.add(link)
    db.session.commit()

    short_url = f"{request.scheme}://{request.host}/s/{short_code}"
    flash(f"Your short link is ready: {short_url}", "success")
    return redirect(url_for("public.landing"))


# ---------------------------------------------------------------------------
# Redirect Engine
# ---------------------------------------------------------------------------

@public_bp.route("/s/<short_code>")
def redirect_link(short_code):
    """Redirect a short link to its original URL and record the click."""
    from datetime import datetime, timezone

    link = Link.query.filter_by(short_code=short_code).first()

    if link is None:
        return render_template(
            "public/error.html",
            title="Link Not Found",
            message="The short link you're looking for doesn't exist or may have been removed.",
        ), 404

    # Check if disabled
    if not link.is_active:
        return render_template(
            "public/error.html",
            title="Link Disabled",
            message="This link has been disabled by its owner or the administrator.",
        ), 410

    # Check if expired
    if link.is_expired():
        return render_template(
            "public/error.html",
            title="Link Expired",
            message="This link has expired and is no longer active.",
        ), 410

    # Check click limit
    if link.is_click_limit_reached():
        return render_template(
            "public/error.html",
            title="Click Limit Reached",
            message="This link has reached its maximum number of clicks.",
        ), 410

    # Check domain blocklist
    if _is_domain_blocked(link.original_url):
        return render_template(
            "public/error.html",
            title="Link Blocked",
            message="The destination domain is blocked.",
        ), 403

    # Check password protection
    if link.password_hash:
        # Check if password was already verified in this session
        password_key = f"link_password_{link.id}"
        if password_key not in session:
            return render_template("public/password.html", link_id=link.id, short_code=short_code)

    # Check password form submission
    if link.password_hash and request.method == "POST":
        password = request.form.get("password", "")
        if not link.check_link_password(password):
            return render_template(
                "public/password.html",
                link_id=link.id,
                short_code=short_code,
                error="Incorrect password.",
            )
        # Store verified password in session
        session[f"link_password_{link.id}"] = True
        session.modified = True

    # Detect bot
    user_agent = (request.headers.get("User-Agent") or "")[:500]
    is_bot = _detect_bot(user_agent)

    # Record the click
    referrer = (request.headers.get("Referer") or "")[:500]
    ip_addr = request.remote_addr[:45] if request.remote_addr else None

    click = ClickEvent(
        link_id=link.id,
        referrer=referrer,
        user_agent=user_agent,
        ip_address=ip_addr,
        is_bot=is_bot,
    )
    link.click_count += 1
    db.session.add(click)
    db.session.commit()

    return redirect(link.original_url, code=302)


@public_bp.route("/s/<short_code>/password", methods=["GET", "POST"])
def link_password(short_code):
    """Password verification page for protected links."""
    link = Link.query.filter_by(short_code=short_code).first()

    if link is None:
        return render_template(
            "public/error.html",
            title="Link Not Found",
            message="The short link you're looking for doesn't exist.",
        ), 404

    if not link.password_hash:
        return redirect(link.original_url, code=302)

    if request.method == "POST":
        password = request.form.get("password", "")
        if link.check_link_password(password):
            session[f"link_password_{link.id}"] = True
            session.modified = True
            return redirect(url_for("public.redirect_link", short_code=short_code))
        return render_template(
            "public/password.html",
            link_id=link.id,
            short_code=short_code,
            error="Incorrect password. Please try again.",
        )

    return render_template("public/password.html", link_id=link.id, short_code=short_code)


def _detect_bot(user_agent):
    """Simple bot detection based on user agent string."""
    if not user_agent:
        return True
    bot_indicators = [
        "bot", "crawler", "spider", "scraper", "curl", "wget",
        "python-requests", "httpclient", "libwww", "java/",
        "googlebot", "bingbot", "yandex", "baiduspider",
    ]
    ua_lower = user_agent.lower()
    return any(indicator in ua_lower for indicator in bot_indicators)


from flask import session


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

@public_bp.route("/health")
def health():
    """Health check endpoint for deployment."""
    return jsonify({"status": "ok"}), 200
