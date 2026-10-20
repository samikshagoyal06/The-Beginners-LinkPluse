README
LinkPulse — Professional URL Shortener & Analytics Platform
Built by The Beginners for college hackathons.
LinkPulse is a production-oriented SaaS URL shortener and analytics platform with three distinct roles: Visitor (anonymous link consumer), Registered User (link creator and manager), and Administrator (platform operator).
Features
For Visitors
Open and follow valid short links with fast redirection
Password entry for protected links
Clear error pages for invalid, expired, disabled, or blocked links
Bot detection and filtering
For Registered Users
Authentication: Sign up, login, logout, password recovery with secure tokens
Link Creation: Create short links with custom aliases, titles, passwords, click limits, and expiration
Link Management: Search, sort, filter, paginate, disable, re-enable, and delete links
Campaigns: Organize links into campaigns with campaign-level metrics
Tags: Tag links for organization and filtering
QR Codes: Generate and download QR codes for any link
CSV Bulk Import: Upload CSV files with validation, preview, and row-level error reporting
Analytics: Real click tracking with charts, referrer data, and date filters
Account Settings: Update profile and change password
For Administrators
Platform Dashboard: Overview of users, links, clicks, and blocked domains
User Management: Search, inspect, suspend, and reactivate user accounts
Link Moderation: Search all links, disable abusive links, re-enable when justified
Domain Blocklist: Add, view, edit, and remove blocked domains
Audit Logs: Full record of administrative actions with timestamps
Platform Analytics: Click trends across the entire platform
Security
Password hashing with Werkzeug
Role-based access control (visitor, user, admin)
Resource ownership enforcement (users can only access their own data)
URL validation (HTTP/HTTPS only, no javascript: or file:)
Rate limiting on all endpoints
Security headers (X-Content-Type-Options, X-Frame-Options, HSTS)
Secure session cookies (HttpOnly, SameSite)
Domain blocklist enforcement
Click limit and expiration enforcement
Bot detection in click tracking
Tech Stack
Backend: Python 3.10+ and Flask with blueprints
Database: SQLite (local dev) / PostgreSQL (production) via SQLAlchemy ORM
Frontend: HTML, CSS, vanilla JavaScript
Charts: Chart.js
QR Codes: qrcode library with Pillow
Testing: pytest
Production Server: Gunicorn
Migrations: Flask-Migrate (Alembic)
Installation
Prerequisites
Python 3.10 or higher
pip package manager
Setup (Windows)
# Navigate to the project directory
cd linkpulse

# Create a virtual environment (recommended)
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment example and configure
copy .env.example .env
# Edit .env and set a secure SECRET_KEY
​
Setup (Linux/Mac)
cd linkpulse
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
​
Running Locally
# Windows
cd linkpulse
python app.py
​
# Linux/Mac
cd linkpulse
python app.py
​
Open http://localhost:5000 in your browser.
Creating an Admin Account
The first administrator must be created via CLI — never through the public sign-up form:
# Windows
set FLASK_APP=app.py
flask create-admin --email admin@example.com --name "Platform Admin" --password "securepassword123"
​
# Linux/Mac
export FLASK_APP=app.py
flask create-admin --email admin@example.com --name "Platform Admin" --password "securepassword123"
​
Then log in at **http://localhost:5000/admin/login**.
Running Tests
cd linkpulse
python -m pytest tests/ -v
​
All 41 tests should pass, covering:
Authentication (register, login, logout, password hashing)
Role permissions (anonymous, user, admin access control)
Link creation and redirection
Click tracking and analytics
Disabled/expired/click-limited links
Domain blocklist enforcement
Admin moderation and audit logging
Campaign management
Project Structure
linkpulse/
├── app.py                  # Flask app factory, blueprints, security headers
├── models.py               # All SQLAlchemy models (User, Link, ClickEvent, etc.)
├── config.py               # Database and app configuration
├── requirements.txt        # Python dependencies
├── .gitignore              # Git ignore rules
├── .env.example            # Environment variable placeholders
├── README.md               # This file
├── render.yaml             # Render deployment config
├── routes/
│   ├── auth.py             # Registration, login, logout, password reset
│   ├── public.py           # Landing page, redirect engine, health check
│   ├── links.py            # User dashboard, link CRUD, QR codes, analytics
│   ├── campaigns.py        # Campaign management
│   ├── admin.py            # Admin console (users, links, blocklist, audit)
│   └── import_export.py    # CSV bulk import and analytics export
├── templates/
│   ├── base.html           # Base template with nav/footer
│   ├── public/             # Landing, error, password pages
│   ├── auth/               # Login, register, password reset
│   ├── user/               # Dashboard, links, campaigns, import, settings
│   └── admin/              # Admin dashboard, users, links, blocklist, audit
└── static/
    ├── css/style.css       # Professional SaaS design system
    └── js/app.js           # Copy-to-clipboard, auto-dismiss alerts
​
Database
Models
User: Email, hashed password, display name, admin flag, active status
Link: Short code, original URL, title, alias, owner, campaign, password hash, max clicks, expiry, click count
ClickEvent: Link reference, timestamp, referrer, user agent, IP, bot flag
Campaign: Name, description, owner
Tag: Name, owner (many-to-many with Link)
DomainBlocklist: Domain, reason, created by admin
AuditLog: Admin action, target, reason, timestamp
PasswordResetToken: User reference, token, expiry, used flag
Migrations
For production with PostgreSQL, use Flask-Migrate:
flask db init
flask db migrate -m "Initial migration"
flask db upgrade
​
Deployment
Render.com
Push code to GitHub
Create a new Web Service on Render
Connect your repository
Use the included render.yaml for configuration
Set environment variables:
SECRET_KEY — a random string (use python -c "import secrets; print(secrets.token_urlsafe(32))")
DATABASE_URI — PostgreSQL connection string from Render's managed database
Deploy
Environment Variables
Variable
Description
Default
SECRET_KEY
Flask secret key for sessions
dev-secret-key-change-in-production
DATABASE_URI
Database connection string
sqlite:///linkpulse.db
Known Limitations
No email service: Password reset tokens are shown in flash messages (dev mode). Configure SMTP credentials in .env for production email.
SQLite for local dev: Use PostgreSQL for multi-user production deployments.
No geographic analytics: IP addresses are stored but not geolocated (privacy-conscious design).
In-memory rate limiting: Rate limit state is lost on server restart. Use Redis for production.
No two-factor authentication: Planned for future versions.
Single-tenant: No multi-organization support.
Future Improvements
Email verification on registration
SMTP integration for password reset emails
Geographic and device analytics (with user consent)
API endpoints with API key authentication
Two-factor authentication
Link preview and thumbnail generation
Custom domain support
Redis-based rate limiting
Webhook integrations
License
Built for hackathons by The Beginners. Feel free to use, modify, and learn from this code.
Credits
Built with Flask, SQLAlchemy, Chart.js, and qrcode. Designed with a professional SaaS aesthetic for hackathon demonstration and real-world use.
Built with Flask, SQLAlchemy, Chart.js, and qrcode. Designed with a professional SaaS aesthetic for hackathon demonstration and real-world use.
