"""Comprehensive tests for LinkPulse URL shortener."""

import pytest
from datetime import datetime, timezone, timedelta
from models import db, User, Link, ClickEvent, Campaign, Tag, DomainBlocklist, AuditLog


# ---------------------------------------------------------------------------
# Authentication Tests
# ---------------------------------------------------------------------------

class TestAuthentication:
    def test_register_page_loads(self, client):
        response = client.get('/auth/register')
        assert response.status_code == 200

    def test_login_page_loads(self, client):
        response = client.get('/auth/login')
        assert response.status_code == 200

    def test_registration_succeeds(self, client):
        response = client.post('/auth/register', data={
            'email': 'new@example.com',
            'password': 'password123',
            'confirm_password': 'password123',
            'display_name': 'New User',
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Account created' in response.data

    def test_duplicate_registration_fails(self, client):
        client.post('/auth/register', data={
            'email': 'dup@example.com',
            'password': 'password123',
            'confirm_password': 'password123',
            'display_name': 'Dup User',
        })
        response = client.post('/auth/register', data={
            'email': 'dup@example.com',
            'password': 'password123',
            'confirm_password': 'password123',
            'display_name': 'Dup User 2',
        }, follow_redirects=True)
        assert response.status_code == 400
        assert b'already exists' in response.data

    def test_passwords_are_hashed(self, app):
        with app.app_context():
            user = User(email='hash@example.com', display_name='Hash Test')
            user.set_password('mypassword')
            db.session.add(user)
            db.session.commit()
            assert user.password_hash != 'mypassword'
            assert user.check_password('mypassword') is True
            assert user.check_password('wrongpassword') is False
            db.session.delete(user)
            db.session.commit()

    def test_valid_login_works(self, client, sample_user):
        response = client.post('/auth/login', data={
            'email': 'test@example.com',
            'password': 'password123',
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_invalid_login_fails(self, client):
        response = client.post('/auth/login', data={
            'email': 'wrong@example.com',
            'password': 'wrongpassword',
        }, follow_redirects=True)
        assert response.status_code == 401
        assert b'Invalid' in response.data

    def test_logout_works(self, client, sample_user):
        with client.session_transaction() as sess:
            sess['user_id'] = sample_user.id
        response = client.post('/auth/logout', follow_redirects=True)
        assert response.status_code == 200

    def test_protected_pages_reject_anonymous(self, client):
        response = client.get('/app/')
        assert response.status_code in (302, 403)
        response = client.get('/app/links')
        assert response.status_code in (302, 403)

    def test_public_registration_cannot_create_admin(self, client):
        client.post('/auth/register', data={
            'email': 'fakeadmin@example.com',
            'password': 'password123',
            'confirm_password': 'password123',
            'display_name': 'Fake Admin',
        })
        with client.application.app_context():
            user = User.query.filter_by(email='fakeadmin@example.com').first()
            assert user is not None
            assert user.is_admin is False


# ---------------------------------------------------------------------------
# Role and Permission Tests
# ---------------------------------------------------------------------------

class TestPermissions:
    def test_anonymous_cannot_access_dashboard(self, client):
        response = client.get('/app/')
        assert response.status_code in (302, 403)

    def test_user_cannot_access_admin(self, client, sample_user):
        with client.session_transaction() as sess:
            sess['user_id'] = sample_user.id
        response = client.get('/admin/')
        assert response.status_code == 403

    def test_user_cannot_modify_other_user_link(self, client, app):
        with app.app_context():
            user1 = User(email='u1@example.com', display_name='User 1')
            user1.set_password('password123')
            db.session.add(user1)
            user2 = User(email='u2@example.com', display_name='User 2')
            user2.set_password('password123')
            db.session.add(user2)
            db.session.flush()

            link = Link(short_code='other123', original_url='https://example.com', user_id=user2.id)
            db.session.add(link)
            db.session.commit()
            link_id = link.id
            user1_id = user1.id

        with client.session_transaction() as sess:
            sess['user_id'] = user1_id
        response = client.post(f'/app/links/{link_id}/delete', follow_redirects=True)
        assert response.status_code == 403

        with app.app_context():
            link = Link.query.get(link_id)
            if link:
                db.session.delete(link)
            user1 = User.query.filter_by(email='u1@example.com').first()
            if user1:
                db.session.delete(user1)
            user2 = User.query.filter_by(email='u2@example.com').first()
            if user2:
                db.session.delete(user2)
            db.session.commit()

    def test_admin_can_access_dashboard(self, client, sample_admin):
        with client.session_transaction() as sess:
            sess['user_id'] = sample_admin.id
        response = client.get('/admin/')
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Link and Redirect Tests
# ---------------------------------------------------------------------------

class TestLinks:
    def test_valid_link_redirects(self, client, sample_link):
        response = client.get(f'/s/{sample_link.short_code}')
        assert response.status_code in (301, 302, 303, 307, 308)

    def test_click_count_increases(self, client, sample_link):
        client.get(f'/s/{sample_link.short_code}', follow_redirects=False)
        with client.application.app_context():
            link = Link.query.get(sample_link.id)
            assert link.click_count >= 1

    def test_unknown_short_code_returns_404(self, client):
        response = client.get('/s/nonexistent')
        assert response.status_code == 404

    def test_disabled_link_does_not_redirect(self, client, app):
        with app.app_context():
            user = User(email='dis@example.com', display_name='Disabled')
            user.set_password('password123')
            db.session.add(user)
            db.session.flush()
            link = Link(short_code='disabled1', original_url='https://example.com', user_id=user.id, is_active=False)
            db.session.add(link)
            db.session.commit()
        response = client.get('/s/disabled1')
        assert response.status_code == 410
        with app.app_context():
            db.session.delete(link)
            db.session.delete(user)
            db.session.commit()

    def test_expired_link_does_not_redirect(self, client, app):
        with app.app_context():
            user = User(email='exp@example.com', display_name='Expired')
            user.set_password('password123')
            db.session.add(user)
            db.session.flush()
            link = Link(short_code='expired1', original_url='https://example.com', user_id=user.id,
                        expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
            db.session.add(link)
            db.session.commit()
        response = client.get('/s/expired1')
        assert response.status_code == 410
        with app.app_context():
            db.session.delete(link)
            db.session.delete(user)
            db.session.commit()

    def test_click_limit_enforced(self, client, app):
        with app.app_context():
            user = User(email='lim@example.com', display_name='Limit')
            user.set_password('password123')
            db.session.add(user)
            db.session.flush()
            link = Link(short_code='limited1', original_url='https://example.com', user_id=user.id,
                        max_clicks=1, click_count=1)
            db.session.add(link)
            db.session.commit()
        response = client.get('/s/limited1')
        assert response.status_code == 410
        with app.app_context():
            db.session.delete(link)
            db.session.delete(user)
            db.session.commit()

    def test_invalid_url_rejected(self, client):
        response = client.post('/shorten', data={'url': 'javascript:alert(1)'}, follow_redirects=True)
        assert response.status_code == 400

    def test_https_url_accepted(self, client):
        response = client.post('/shorten', data={'url': 'https://example.com'}, follow_redirects=True)
        assert response.status_code == 200

    def test_blocklisted_domain_blocked(self, client, app, sample_blocklist):
        with app.app_context():
            user = User(email='blk@example.com', display_name='Blocked')
            user.set_password('password123')
            db.session.add(user)
            db.session.flush()
            link = Link(short_code='blocked1', original_url='https://badsite.com/evil', user_id=user.id)
            db.session.add(link)
            db.session.commit()
        response = client.get('/s/blocked1')
        assert response.status_code == 403
        with app.app_context():
            db.session.delete(link)
            db.session.delete(user)
            db.session.commit()


# ---------------------------------------------------------------------------
# User Dashboard Tests
# ---------------------------------------------------------------------------

class TestDashboard:
    def test_dashboard_loads_when_logged_in(self, logged_in_client):
        response = logged_in_client.get('/app/')
        assert response.status_code == 200

    def test_dashboard_shows_user_links(self, logged_in_client, sample_link):
        response = logged_in_client.get('/app/')
        assert b'example.com' in response.data

    def test_links_page_loads(self, logged_in_client):
        response = logged_in_client.get('/app/links')
        assert response.status_code == 200

    def test_create_link_page_loads(self, logged_in_client):
        response = logged_in_client.get('/app/links/new')
        assert response.status_code == 200

    def test_link_detail_loads(self, logged_in_client, sample_link):
        response = logged_in_client.get(f'/app/links/{sample_link.id}')
        assert response.status_code == 200

    def test_toggle_link(self, logged_in_client, sample_link):
        response = logged_in_client.post(f'/app/links/{sample_link.id}/toggle', follow_redirects=True)
        assert response.status_code == 200
        with logged_in_client.application.app_context():
            link = Link.query.get(sample_link.id)
            assert link.is_active is False

    def test_delete_link(self, logged_in_client, sample_link):
        link_id = sample_link.id
        response = logged_in_client.post(f'/app/links/{link_id}/delete', follow_redirects=True)
        assert response.status_code == 200
        with logged_in_client.application.app_context():
            assert Link.query.get(link_id) is None


# ---------------------------------------------------------------------------
# Analytics Tests
# ---------------------------------------------------------------------------

class TestAnalytics:
    def test_analytics_api_returns_json(self, logged_in_client, sample_link_with_clicks):
        response = logged_in_client.get(f'/app/links/{sample_link_with_clicks.id}/analytics')
        assert response.status_code == 200
        data = response.get_json()
        assert 'daily_clicks' in data
        assert 'total_clicks' in data

    def test_analytics_scoped_to_user(self, client, app):
        with app.app_context():
            user1 = User(email='a1@example.com', display_name='A1')
            user1.set_password('password123')
            db.session.add(user1)
            user2 = User(email='a2@example.com', display_name='A2')
            user2.set_password('password123')
            db.session.add(user2)
            db.session.flush()
            link = Link(short_code='scoped1', original_url='https://example.com', user_id=user2.id, click_count=5)
            db.session.add(link)
            db.session.commit()
            link_id = link.id
            user1_id = user1.id

        with client.session_transaction() as sess:
            sess['user_id'] = user1_id
        response = client.get(f'/app/links/{link_id}/analytics')
        assert response.status_code == 403

        with app.app_context():
            link = Link.query.get(link_id)
            if link:
                db.session.delete(link)
            user1 = User.query.filter_by(email='a1@example.com').first()
            if user1:
                db.session.delete(user1)
            user2 = User.query.filter_by(email='a2@example.com').first()
            if user2:
                db.session.delete(user2)
            db.session.commit()


# ---------------------------------------------------------------------------
# Admin Tests
# ---------------------------------------------------------------------------

class TestAdmin:
    def test_admin_dashboard_loads(self, admin_client):
        response = admin_client.get('/admin/')
        assert response.status_code == 200

    def test_admin_users_page_loads(self, admin_client):
        response = admin_client.get('/admin/users')
        assert response.status_code == 200

    def test_admin_links_page_loads(self, admin_client):
        response = admin_client.get('/admin/links')
        assert response.status_code == 200

    def test_admin_blocklist_page_loads(self, admin_client):
        response = admin_client.get('/admin/blocklist')
        assert response.status_code == 200

    def test_admin_audit_page_loads(self, admin_client):
        response = admin_client.get('/admin/audit')
        assert response.status_code == 200

    def test_admin_can_disable_link(self, admin_client, sample_link):
        response = admin_client.post(f'/admin/links/{sample_link.id}/disable', follow_redirects=True)
        assert response.status_code == 200
        with admin_client.application.app_context():
            link = Link.query.get(sample_link.id)
            assert link.is_active is False
            audit = AuditLog.query.filter_by(action='disable_link').first()
            assert audit is not None


# ---------------------------------------------------------------------------
# Campaign Tests
# ---------------------------------------------------------------------------

class TestCampaigns:
    def test_campaign_creation(self, logged_in_client):
        response = logged_in_client.post('/app/campaigns/new', data={
            'name': 'My Campaign',
            'description': 'Test campaign',
        }, follow_redirects=True)
        assert response.status_code == 200
        with logged_in_client.application.app_context():
            campaign = Campaign.query.filter_by(name='My Campaign').first()
            assert campaign is not None

    def test_campaign_list_loads(self, logged_in_client):
        response = logged_in_client.get('/app/campaigns/')
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_endpoint(self, client):
        response = client.get('/health')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'
