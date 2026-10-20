from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# ---------------------------------------------------------------------------
# Association Tables
# ---------------------------------------------------------------------------

link_tag = db.Table(
    "link_tag",
    db.Column("link_id", db.Integer, db.ForeignKey("links.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tags.id"), primary_key=True),
)


# ---------------------------------------------------------------------------
# User Model
# ---------------------------------------------------------------------------

class User(db.Model):
    """Registered user of the platform."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100), nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    links = db.relationship("Link", backref="owner", lazy="dynamic")
    campaigns = db.relationship("Campaign", backref="owner", lazy="dynamic", cascade="all, delete-orphan")
    tags = db.relationship("Tag", backref="owner", lazy="dynamic", cascade="all, delete-orphan")

    def set_password(self, password):
        """Hash and store the password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify a password against the stored hash."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.email}>"


# ---------------------------------------------------------------------------
# Link Model
# ---------------------------------------------------------------------------

class Link(db.Model):
    """A shortened link stored in the database."""

    __tablename__ = "links"

    id = db.Column(db.Integer, primary_key=True)
    short_code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    original_url = db.Column(db.Text, nullable=False)
    title = db.Column(db.String(200), nullable=True)
    alias = db.Column(db.String(50), unique=True, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    max_clicks = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    click_count = db.Column(db.Integer, default=0, nullable=False)

    clicks = db.relationship("ClickEvent", backref="link", lazy="dynamic", cascade="all, delete-orphan")
    tags = db.relationship("Tag", secondary=link_tag, backref=db.backref("links", lazy="dynamic"))

    def set_link_password(self, password):
        """Hash and store a link password."""
        self.password_hash = generate_password_hash(password)

    def check_link_password(self, password):
        """Verify a password against the stored link hash."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def is_expired(self):
        """Return True if the link has an expiry date in the past."""
        if self.expires_at is None:
            return False
        now = datetime.now(timezone.utc)
        if self.expires_at.tzinfo is None:
            expires = self.expires_at.replace(tzinfo=timezone.utc)
        else:
            expires = self.expires_at
        return now > expires

    def is_click_limit_reached(self):
        """Return True if the link has reached its max click limit."""
        if self.max_clicks is None:
            return False
        return self.click_count >= self.max_clicks

    def short_url(self, base_url=None):
        """Build the full short URL."""
        if base_url is None:
            from flask import request
            base_url = f"{request.scheme}://{request.host}"
        return f"{base_url}/s/{self.short_code}"

    def __repr__(self):
        return f"<Link {self.short_code}>"


# ---------------------------------------------------------------------------
# ClickEvent Model
# ---------------------------------------------------------------------------

class ClickEvent(db.Model):
    """A single click recorded when a short link is visited."""

    __tablename__ = "click_events"

    id = db.Column(db.Integer, primary_key=True)
    link_id = db.Column(db.Integer, db.ForeignKey("links.id"), nullable=False, index=True)
    clicked_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    referrer = db.Column(db.String(500), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    is_bot = db.Column(db.Boolean, default=False, nullable=False)

    def __repr__(self):
        return f"<ClickEvent {self.id}>"


# ---------------------------------------------------------------------------
# Campaign Model
# ---------------------------------------------------------------------------

class Campaign(db.Model):
    """A campaign that groups related links."""

    __tablename__ = "campaigns"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    links = db.relationship("Link", backref="campaign", lazy="dynamic")

    def total_clicks(self):
        """Return the total clicks across all links in this campaign."""
        return sum(link.click_count for link in self.links.all())

    def __repr__(self):
        return f"<Campaign {self.name}>"


# ---------------------------------------------------------------------------
# Tag Model
# ---------------------------------------------------------------------------

class Tag(db.Model):
    """A tag for organizing links."""

    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint("name", "user_id", name="uq_tag_name_user"),
    )

    def __repr__(self):
        return f"<Tag {self.name}>"


# ---------------------------------------------------------------------------
# DomainBlocklist Model
# ---------------------------------------------------------------------------

class DomainBlocklist(db.Model):
    """A blocked domain that prevents link creation and redirection."""

    __tablename__ = "domain_blocklist"

    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(255), unique=True, nullable=False, index=True)
    reason = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f"<DomainBlocklist {self.domain}>"


# ---------------------------------------------------------------------------
# AuditLog Model
# ---------------------------------------------------------------------------

class AuditLog(db.Model):
    """Record of administrative actions for accountability."""

    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    target_type = db.Column(db.String(50), nullable=False)
    target_id = db.Column(db.Integer, nullable=True)
    reason = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    admin = db.relationship("User", backref="audit_logs")

    def __repr__(self):
        return f"<AuditLog {self.action} on {self.target_type}>"


# ---------------------------------------------------------------------------
# PasswordResetToken Model
# ---------------------------------------------------------------------------

class PasswordResetToken(db.Model):
    """One-time token for password recovery."""

    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    token = db.Column(db.String(100), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)

    user = db.relationship("User")

    def is_valid(self):
        """Check if the token is still valid (not expired and not used)."""
        now = datetime.now(timezone.utc)
        if self.used:
            return False
        if self.expires_at.tzinfo is None:
            expires = self.expires_at.replace(tzinfo=timezone.utc)
        else:
            expires = self.expires_at
        return now <= expires

    def __repr__(self):
        return f"<PasswordResetToken {self.token[:8]}...>"
