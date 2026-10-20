"""Test fixtures for LinkPulse."""

import pytest
from app import create_app
from models import db, User, Link, ClickEvent, Campaign, Tag, DomainBlocklist, AuditLog
from datetime import datetime, timezone, timedelta


@pytest.fixture
def app():
    """Create a test app with an in-memory SQLite database."""
    app = create_app()
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['SESSION_COOKIE_SECURE'] = False

    with app.app_context():
        db.create_all()

    yield app

    with app.app_context():
        db.drop_all()


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


@pytest.fixture
def sample_user(app):
    """Create a sample registered user."""
    with app.app_context():
        user = User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
        )
        user.set_password('password123')
        db.session.add(user)
        db.session.commit()
        yield user
        db.session.delete(user)
        db.session.commit()


@pytest.fixture
def sample_admin(app):
    """Create a sample admin user."""
    with app.app_context():
        admin = User(
            email='admin@example.com',
            display_name='Admin User',
            is_admin=True,
            is_active=True,
        )
        admin.set_password('adminpass123')
        db.session.add(admin)
        db.session.commit()
        yield admin
        db.session.delete(admin)
        db.session.commit()


@pytest.fixture
def sample_link(app, sample_user):
    """Create a sample link owned by sample_user."""
    with app.app_context():
        link = Link(
            short_code='abc12345',
            original_url='https://example.com/long/url',
            user_id=sample_user.id,
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(link)
        db.session.commit()
        yield link
        db.session.execute(db.delete(ClickEvent).where(ClickEvent.link_id == link.id))
        db.session.delete(link)
        db.session.commit()


@pytest.fixture
def sample_link_with_clicks(app, sample_user):
    """Create a sample link with click events."""
    with app.app_context():
        link = Link(
            short_code='clicks123',
            original_url='https://example.com/clicked',
            user_id=sample_user.id,
            click_count=3,
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(link)
        db.session.commit()

        for i in range(3):
            click = ClickEvent(
                link_id=link.id,
                clicked_at=datetime.now(timezone.utc) - timedelta(hours=i),
            )
            db.session.add(click)
        db.session.commit()

        yield link
        db.session.execute(db.delete(ClickEvent).where(ClickEvent.link_id == link.id))
        db.session.delete(link)
        db.session.commit()


@pytest.fixture
def logged_in_client(client, sample_user):
    """Create a test client logged in as sample_user."""
    with client.session_transaction() as sess:
        sess['user_id'] = sample_user.id
    return client


@pytest.fixture
def admin_client(client, sample_admin):
    """Create a test client logged in as admin."""
    with client.session_transaction() as sess:
        sess['user_id'] = sample_admin.id
    return client


@pytest.fixture
def sample_campaign(app, sample_user):
    """Create a sample campaign."""
    with app.app_context():
        campaign = Campaign(
            name='Test Campaign',
            description='A test campaign',
            user_id=sample_user.id,
        )
        db.session.add(campaign)
        db.session.commit()
        yield campaign
        db.session.delete(campaign)
        db.session.commit()


@pytest.fixture
def sample_blocklist(app, sample_admin):
    """Create a sample domain blocklist entry."""
    with app.app_context():
        block = DomainBlocklist(
            domain='badsite.com',
            reason='Malware',
            created_by=sample_admin.id,
        )
        db.session.add(block)
        db.session.commit()
        yield block
        db.session.delete(block)
        db.session.commit()
