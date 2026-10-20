"""Admin console routes for platform management."""

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    jsonify,
)
from datetime import datetime, timezone

from models import db, User, Link, ClickEvent, DomainBlocklist, AuditLog, Campaign
from routes.auth import login_required, admin_required, current_user

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ---------------------------------------------------------------------------
# Admin Login
# ---------------------------------------------------------------------------

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    """Admin login page."""
    if "user_id" in session:
        user = User.query.get(session["user_id"])
        if user and user.is_admin:
            return redirect(url_for("admin.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password) and user.is_admin and user.is_active:
            session["user_id"] = user.id
            session.permanent = True
            flash("Welcome, Administrator.", "success")
            return redirect(url_for("admin.dashboard"))

        flash("Invalid credentials or not an administrator.", "danger")
        return render_template("admin/login.html"), 401

    return render_template("admin/login.html")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@admin_bp.route("/")
@admin_required
def dashboard():
    """Admin dashboard with platform-wide stats."""
    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    total_links = Link.query.count()
    active_links = Link.query.filter_by(is_active=True).count()
    total_clicks = db.session.query(db.func.sum(Link.click_count)).scalar() or 0
    total_campaigns = Campaign.query.count()
    blocked_domains = DomainBlocklist.query.count()
    recent_audit = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(10).all()

    # Recent suspicious links (disabled links)
    disabled_links = Link.query.filter_by(is_active=False).order_by(Link.created_at.desc()).limit(10).all()

    return render_template(
        "admin/dashboard.html",
        total_users=total_users,
        active_users=active_users,
        total_links=total_links,
        active_links=active_links,
        total_clicks=total_clicks,
        total_campaigns=total_campaigns,
        blocked_domains=blocked_domains,
        recent_audit=recent_audit,
        disabled_links=disabled_links,
    )


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------

@admin_bp.route("/users")
@admin_required
def users():
    """List and manage users."""
    search = request.args.get("search", "").strip()
    query = User.query

    if search:
        query = query.filter(
            db.or_(
                User.email.contains(search),
                User.display_name.contains(search),
            )
        )

    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20, error_out=False)

    return render_template("admin/users.html", pagination=pagination, search=search)


@admin_bp.route("/users/<int:user_id>/suspend", methods=["POST"])
@admin_required
def suspend_user(user_id):
    """Suspend a user account."""
    admin = current_user()
    user = User.query.get_or_404(user_id)

    if user.is_admin:
        flash("Cannot suspend an administrator account.", "danger")
        return redirect(url_for("admin.users"))

    user.is_active = False
    db.session.add(AuditLog(
        admin_id=admin.id,
        action="suspend_user",
        target_type="user",
        target_id=user_id,
        reason=request.form.get("reason", ""),
    ))
    db.session.commit()

    flash(f"User {user.email} has been suspended.", "info")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/reactivate", methods=["POST"])
@admin_required
def reactivate_user(user_id):
    """Reactivate a suspended user."""
    admin = current_user()
    user = User.query.get_or_404(user_id)

    user.is_active = True
    db.session.add(AuditLog(
        admin_id=admin.id,
        action="reactivate_user",
        target_type="user",
        target_id=user_id,
        reason=request.form.get("reason", ""),
    ))
    db.session.commit()

    flash(f"User {user.email} has been reactivated.", "success")
    return redirect(url_for("admin.users"))


# ---------------------------------------------------------------------------
# Link Moderation
# ---------------------------------------------------------------------------

@admin_bp.route("/links")
@admin_required
def links():
    """Search and moderate all links."""
    search = request.args.get("search", "").strip()
    query = Link.query.join(User)

    if search:
        query = query.filter(
            db.or_(
                Link.original_url.contains(search),
                Link.short_code.contains(search),
                User.email.contains(search),
            )
        )

    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(Link.created_at.desc()).paginate(page=page, per_page=20, error_out=False)

    return render_template("admin/links.html", pagination=pagination, search=search)


@admin_bp.route("/links/<int:link_id>/disable", methods=["POST"])
@admin_required
def disable_link(link_id):
    """Disable a link immediately."""
    admin = current_user()
    link = Link.query.get_or_404(link_id)

    link.is_active = False
    db.session.add(AuditLog(
        admin_id=admin.id,
        action="disable_link",
        target_type="link",
        target_id=link_id,
        reason=request.form.get("reason", "Abusive content"),
    ))
    db.session.commit()

    flash(f"Link {link.short_code} has been disabled.", "info")
    return redirect(url_for("admin.links"))


@admin_bp.route("/links/<int:link_id>/enable", methods=["POST"])
@admin_required
def enable_link(link_id):
    """Re-enable a disabled link."""
    admin = current_user()
    link = Link.query.get_or_404(link_id)

    link.is_active = True
    db.session.add(AuditLog(
        admin_id=admin.id,
        action="enable_link",
        target_type="link",
        target_id=link_id,
        reason=request.form.get("reason", ""),
    ))
    db.session.commit()

    flash(f"Link {link.short_code} has been re-enabled.", "success")
    return redirect(url_for("admin.links"))


# ---------------------------------------------------------------------------
# Domain Blocklist
# ---------------------------------------------------------------------------

@admin_bp.route("/blocklist")
@admin_required
def blocklist():
    """View and manage the domain blocklist."""
    domains = DomainBlocklist.query.order_by(DomainBlocklist.created_at.desc()).all()
    return render_template("admin/blocklist.html", domains=domains)


@admin_bp.route("/blocklist/add", methods=["POST"])
@admin_required
def add_blocklist():
    """Add a domain to the blocklist."""
    admin = current_user()
    domain = request.form.get("domain", "").strip().lower()
    reason = request.form.get("reason", "").strip()

    if not domain:
        flash("Domain is required.", "danger")
        return redirect(url_for("admin.blocklist"))

    if DomainBlocklist.query.filter_by(domain=domain).first():
        flash("Domain is already blocked.", "warning")
        return redirect(url_for("admin.blocklist"))

    db.session.add(DomainBlocklist(
        domain=domain,
        reason=reason or None,
        created_by=admin.id,
    ))
    db.session.add(AuditLog(
        admin_id=admin.id,
        action="block_domain",
        target_type="domain",
        reason=f"Blocked domain: {domain}. {reason}",
    ))
    db.session.commit()

    flash(f"Domain '{domain}' added to blocklist.", "success")
    return redirect(url_for("admin.blocklist"))


@admin_bp.route("/blocklist/<int:block_id>/remove", methods=["POST"])
@admin_required
def remove_blocklist(block_id):
    """Remove a domain from the blocklist."""
    admin = current_user()
    block = DomainBlocklist.query.get_or_404(block_id)

    domain = block.domain
    db.session.delete(block)
    db.session.add(AuditLog(
        admin_id=admin.id,
        action="unblock_domain",
        target_type="domain",
        reason=f"Unblocked domain: {domain}",
    ))
    db.session.commit()

    flash(f"Domain '{domain}' removed from blocklist.", "success")
    return redirect(url_for("admin.blocklist"))


# ---------------------------------------------------------------------------
# Audit Logs
# ---------------------------------------------------------------------------

@admin_bp.route("/audit")
@admin_required
def audit_logs():
    """View audit logs."""
    action = request.args.get("action", "")
    query = AuditLog.query

    if action:
        query = query.filter_by(action=action)

    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=50, error_out=False)

    return render_template("admin/audit.html", pagination=pagination, action=action)


# ---------------------------------------------------------------------------
# Platform Analytics
# ---------------------------------------------------------------------------

@admin_bp.route("/analytics")
@admin_required
def analytics():
    """Platform-wide analytics."""
    # Clicks over time (last 30 days)
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)

    daily_clicks = db.session.query(
        db.func.date(ClickEvent.clicked_at).label("day"),
        db.func.count().label("count"),
    ).filter(
        ClickEvent.clicked_at >= thirty_days_ago,
        ClickEvent.is_bot == False,
    ).group_by("day").order_by("day").all()

    return render_template(
        "admin/analytics.html",
        daily_clicks=dict((str(d.day), d.count) for d in daily_clicks),
    )


from flask import session
