"""Link management routes for authenticated users."""

import string
import secrets
from datetime import datetime, timezone, timedelta
from io import BytesIO

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
    send_file,
    abort,
)

from models import db, Link, ClickEvent, Campaign, Tag, User
from routes.auth import login_required, current_user

user_bp = Blueprint("user", __name__, url_prefix="/app")


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
    from models import DomainBlocklist
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
    alphabet = string.ascii_letters + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(length))
        if not Link.query.filter_by(short_code=code).first():
            return code


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@user_bp.route("/")
@login_required
def dashboard():
    """User dashboard with stats and recent links."""
    user = current_user()
    if not user:
        abort(403)

    links = Link.query.filter_by(user_id=user.id).order_by(Link.created_at.desc()).limit(20).all()
    total_links = Link.query.filter_by(user_id=user.id).count()
    total_clicks = db.session.query(db.func.sum(Link.click_count)).filter_by(user_id=user.id).scalar() or 0
    active_links = Link.query.filter_by(user_id=user.id, is_active=True).count()
    campaigns = Campaign.query.filter_by(user_id=user.id).all()

    return render_template(
        "user/dashboard.html",
        links=links,
        total_links=total_links,
        total_clicks=total_clicks,
        active_links=active_links,
        campaigns=campaigns,
        user=user,
    )


# ---------------------------------------------------------------------------
# Link List
# ---------------------------------------------------------------------------

@user_bp.route("/links")
@login_required
def links():
    """List all links for the current user with search and filters."""
    user = current_user()
    if not user:
        abort(403)

    query = Link.query.filter_by(user_id=user.id)

    # Search
    search = request.args.get("search", "").strip()
    if search:
        query = query.filter(
            db.or_(
                Link.original_url.contains(search),
                Link.short_code.contains(search),
                Link.title.contains(search),
            )
        )

    # Filter by status
    status = request.args.get("status", "")
    if status == "active":
        query = query.filter_by(is_active=True)
    elif status == "disabled":
        query = query.filter_by(is_active=False)

    # Filter by campaign
    campaign_id = request.args.get("campaign_id", "")
    if campaign_id:
        query = query.filter_by(campaign_id=campaign_id)

    # Sort
    sort = request.args.get("sort", "created_at")
    order = request.args.get("order", "desc")
    if sort == "clicks":
        sort_col = Link.click_count
    elif sort == "url":
        sort_col = Link.original_url
    else:
        sort_col = Link.created_at
    if order == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    # Pagination
    page = request.args.get("page", 1, type=int)
    pagination = query.paginate(page=page, per_page=20, error_out=False)

    campaigns = Campaign.query.filter_by(user_id=user.id).all()

    return render_template(
        "user/links.html",
        pagination=pagination,
        campaigns=campaigns,
        search=search,
        status=status,
        sort=sort,
        order=order,
        user=user,
    )


# ---------------------------------------------------------------------------
# Link Creation
# ---------------------------------------------------------------------------

@user_bp.route("/links/new", methods=["GET", "POST"])
@login_required
def create_link():
    """Create a new shortened link."""
    user = current_user()
    if not user:
        abort(403)

    if request.method == "POST":
        original_url = request.form.get("url", "").strip()
        title = request.form.get("title", "").strip()
        alias = request.form.get("alias", "").strip()
        password = request.form.get("password", "").strip()
        max_clicks_str = request.form.get("max_clicks", "").strip()
        expires = request.form.get("expires", "").strip()
        campaign_id = request.form.get("campaign_id", "").strip()
        tags_str = request.form.get("tags", "").strip()

        # Validate URL
        valid, error = _validate_url(original_url)
        if not valid:
            flash(error, "danger")
            return render_template("user/link_create.html", user=user), 400

        # Check domain blocklist
        if _is_domain_blocked(original_url):
            flash("The destination domain is blocked.", "danger")
            return render_template("user/link_create.html", user=user), 400

        # Handle alias
        if alias:
            if Link.query.filter_by(alias=alias).first():
                flash("This alias is already taken.", "danger")
                return render_template("user/link_create.html", user=user), 400
            short_code = alias
        else:
            short_code = _generate_short_code()

        # Handle max clicks
        max_clicks = None
        if max_clicks_str:
            try:
                max_clicks = int(max_clicks_str)
                if max_clicks <= 0:
                    flash("Max clicks must be a positive number.", "danger")
                    return render_template("user/link_create.html", user=user), 400
            except ValueError:
                flash("Invalid max clicks value.", "danger")
                return render_template("user/link_create.html", user=user), 400

        # Handle expiration
        expires_at = None
        if expires:
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
                    return render_template("user/link_create.html", user=user), 400
            except (ValueError, IndexError):
                flash("Invalid expiration format.", "danger")
                return render_template("user/link_create.html", user=user), 400

        # Create link
        link = Link(
            short_code=short_code,
            original_url=original_url,
            title=title or None,
            alias=alias if alias else None,
            user_id=user.id,
            max_clicks=max_clicks,
            expires_at=expires_at,
        )

        if password:
            link.set_link_password(password)

        if campaign_id:
            campaign = Campaign.query.get(int(campaign_id))
            if campaign and campaign.user_id == user.id:
                link.campaign_id = campaign.id

        db.session.add(link)
        db.session.flush()

        # Handle tags
        if tags_str:
            for tag_name in tags_str.split(","):
                tag_name = tag_name.strip()
                if tag_name:
                    tag = Tag.query.filter_by(name=tag_name, user_id=user.id).first()
                    if not tag:
                        tag = Tag(name=tag_name, user_id=user.id)
                        db.session.add(tag)
                        db.session.flush()
                    link.tags.append(tag)

        db.session.commit()

        flash(f"Link created: {link.short_url()}", "success")
        return redirect(url_for("user.link_detail", link_id=link.id))

    campaigns = Campaign.query.filter_by(user_id=user.id).all()
    return render_template("user/link_create.html", user=user, campaigns=campaigns)


# ---------------------------------------------------------------------------
# Link Detail
# ---------------------------------------------------------------------------

@user_bp.route("/links/<int:link_id>")
@login_required
def link_detail(link_id):
    """Detail page for a single link."""
    user = current_user()
    if not user:
        abort(403)

    link = Link.query.get_or_404(link_id)
    if link.user_id != user.id:
        abort(403)

    clicks = ClickEvent.query.filter_by(link_id=link_id).order_by(ClickEvent.clicked_at.desc()).limit(50).all()

    return render_template("user/link_detail.html", link=link, clicks=clicks, user=user)


@user_bp.route("/links/<int:link_id>/analytics")
@login_required
def link_analytics(link_id):
    """API endpoint for link click analytics."""
    user = current_user()
    if not user:
        abort(403)

    link = Link.query.get_or_404(link_id)
    if link.user_id != user.id:
        abort(403)

    clicks = ClickEvent.query.filter_by(link_id=link_id).order_by(ClickEvent.clicked_at).all()

    # Group by date
    daily = {}
    for click in clicks:
        day = click.clicked_at.strftime("%Y-%m-%d")
        daily[day] = daily.get(day, 0) + 1

    # Referrer breakdown
    referrers = {}
    for click in clicks:
        ref = click.referrer or "Direct"
        referrers[ref] = referrers.get(ref, 0) + 1

    return jsonify({
        "link_id": link.id,
        "short_code": link.short_code,
        "total_clicks": link.click_count,
        "daily_clicks": daily,
        "referrers": referrers,
    })


# ---------------------------------------------------------------------------
# Link Management
# ---------------------------------------------------------------------------

@user_bp.route("/links/<int:link_id>/toggle", methods=["POST"])
@login_required
def toggle_link(link_id):
    """Toggle a link's active status."""
    user = current_user()
    if not user:
        abort(403)

    link = Link.query.get_or_404(link_id)
    if link.user_id != user.id:
        abort(403)

    link.is_active = not link.is_active
    db.session.commit()
    status = "enabled" if link.is_active else "disabled"
    flash(f"Link has been {status}.", "info")
    return redirect(url_for("user.link_detail", link_id=link_id))


@user_bp.route("/links/<int:link_id>/delete", methods=["POST"])
@login_required
def delete_link(link_id):
    """Delete a link."""
    user = current_user()
    if not user:
        abort(403)

    link = Link.query.get_or_404(link_id)
    if link.user_id != user.id:
        abort(403)

    db.session.delete(link)
    db.session.commit()
    flash("Link has been deleted.", "success")
    return redirect(url_for("user.links"))


# ---------------------------------------------------------------------------
# QR Code
# ---------------------------------------------------------------------------

@user_bp.route("/links/<int:link_id>/qr")
@login_required
def qr_code(link_id):
    """Generate and download QR code for a link."""
    user = current_user()
    if not user:
        abort(403)

    link = Link.query.get_or_404(link_id)
    if link.user_id != user.id:
        abort(403)

    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(link.short_url())
        qr.make(fit=True)
        img = qr.make_image(fill_color="000000", back_color="ffffff")

        img_bytes = BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)

        return send_file(
            img_bytes,
            mimetype="image/png",
            as_attachment=True,
            download_name=f"qr_{link.short_code}.png",
        )
    except ImportError:
        flash("QR code generation is not available. Install the qrcode package.", "warning")
        return redirect(url_for("user.link_detail", link_id=link_id))


# ---------------------------------------------------------------------------
# Account Settings
# ---------------------------------------------------------------------------

@user_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    """Account settings page."""
    user = current_user()
    if not user:
        abort(403)

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if display_name:
            user.display_name = display_name

        if new_password:
            if not user.check_password(current_password):
                flash("Current password is incorrect.", "danger")
                return render_template("user/settings.html", user=user), 400
            if len(new_password) < 8:
                flash("New password must be at least 8 characters.", "danger")
                return render_template("user/settings.html", user=user), 400
            if new_password != confirm_password:
                flash("New passwords do not match.", "danger")
                return render_template("user/settings.html", user=user), 400
            user.set_password(new_password)

        db.session.commit()
        flash("Settings updated.", "success")
        return redirect(url_for("user.settings"))

    return render_template("user/settings.html", user=user)
