"""CSV bulk import and export routes."""

import csv
import io
from datetime import datetime, timezone, timedelta

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    send_file,
    abort,
)

from models import db, Link, Campaign, Tag, ClickEvent
from routes.auth import login_required, current_user
from routes.links import _validate_url, _is_domain_blocked, _generate_short_code

import_bp = Blueprint("import_export", __name__, url_prefix="/app/import")

MAX_CSV_SIZE = 5 * 1024 * 1024  # 5 MB


@import_bp.route("/")
@login_required
def import_page():
    """CSV import page."""
    user = current_user()
    if not user:
        abort(403)

    campaigns = Campaign.query.filter_by(user_id=user.id).all()
    return render_template("user/import.html", user=user, campaigns=campaigns)


@import_bp.route("/upload", methods=["POST"])
@login_required
def upload_csv():
    """Process CSV upload and import links."""
    user = current_user()
    if not user:
        abort(403)

    # Check file
    if "csv_file" not in request.files:
        flash("No file uploaded.", "danger")
        return redirect(url_for("import_export.import_page"))

    file = request.files["csv_file"]
    if not file.filename or not file.filename.endswith(".csv"):
        flash("Please upload a CSV file.", "danger")
        return redirect(url_for("import_export.import_page"))

    # Read and validate
    try:
        content = file.read()
        if len(content) > MAX_CSV_SIZE:
            flash("File too large. Maximum size is 5 MB.", "danger")
            return redirect(url_for("import_export.import_page"))

        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))

        if not reader.fieldnames:
            flash("CSV file is empty or has no headers.", "danger")
            return redirect(url_for("import_export.import_page"))

        # Expected headers: url, title, alias, campaign, tags, password, max_clicks, expires
        required = ["url"]
        missing = [h for h in required if h not in reader.fieldnames]
        if missing:
            flash(f"Missing required column: {', '.join(missing)}", "danger")
            return redirect(url_for("import_export.import_page"))

        # Parse rows
        rows = list(reader)
        if not rows:
            flash("CSV file contains no data rows.", "danger")
            return redirect(url_for("import_export.import_page"))

        # Validate each row
        results = []
        for i, row in enumerate(rows):
            row_result = {"row": i + 2, "url": row.get("url", "").strip()}
            valid, error = _validate_url(row_result["url"])
            if not valid:
                row_result["error"] = error
                results.append(row_result)
                continue

            if _is_domain_blocked(row_result["url"]):
                row_result["error"] = "Domain blocked"
                results.append(row_result)
                continue

            row_result["valid"] = True
            row_result["title"] = row.get("title", "").strip() or None
            row_result["alias"] = row.get("alias", "").strip() or None
            row_result["campaign"] = row.get("campaign", "").strip() or None
            row_result["tags"] = row.get("tags", "").strip() or None
            row_result["password"] = row.get("password", "").strip() or None
            row_result["max_clicks"] = row.get("max_clicks", "").strip() or None
            row_result["expires"] = row.get("expires", "").strip() or None
            results.append(row_result)

        if request.form.get("action") == "preview":
            valid_rows = [r for r in results if r.get("valid")]
            invalid_rows = [r for r in results if not r.get("valid")]
            return render_template(
                "user/import_preview.html",
                user=user,
                valid_rows=valid_rows,
                invalid_rows=invalid_rows,
                total=len(results),
            )

        elif request.form.get("action") == "import":
            # Import valid rows
            campaign_name_to_id = {}
            for campaign in Campaign.query.filter_by(user_id=user.id).all():
                campaign_name_to_id[campaign.name.lower()] = campaign.id

            success = 0
            skipped = 0
            errors = []

            for row in results:
                if not row.get("valid"):
                    skipped += 1
                    continue

                try:
                    # Alias
                    alias = row.get("alias")
                    if alias:
                        if Link.query.filter_by(alias=alias).first():
                            errors.append(f"Row {row['row']}: Alias '{alias}' already taken.")
                            skipped += 1
                            continue
                        short_code = alias
                    else:
                        short_code = _generate_short_code()

                    # Campaign
                    campaign_id = None
                    if row.get("campaign"):
                        cid = campaign_name_to_id.get(row["campaign"].lower())
                        if cid:
                            campaign_id = cid

                    # Max clicks
                    max_clicks = None
                    if row.get("max_clicks"):
                        try:
                            max_clicks = int(row["max_clicks"])
                        except ValueError:
                            pass

                    # Expiration
                    expires_at = None
                    if row.get("expires"):
                        try:
                            exp_lower = row["expires"].lower().strip()
                            if exp_lower.endswith("h"):
                                expires_at = datetime.now(timezone.utc) + timedelta(hours=int(exp_lower[:-1]))
                            elif exp_lower.endswith("d"):
                                expires_at = datetime.now(timezone.utc) + timedelta(days=int(exp_lower[:-1]))
                        except (ValueError, IndexError):
                            pass

                    link = Link(
                        short_code=short_code,
                        original_url=row["url"],
                        title=row.get("title"),
                        alias=alias,
                        user_id=user.id,
                        campaign_id=campaign_id,
                        max_clicks=max_clicks,
                        expires_at=expires_at,
                    )

                    if row.get("password"):
                        link.set_link_password(row["password"])

                    db.session.add(link)
                    db.session.flush()

                    # Tags
                    if row.get("tags"):
                        for tag_name in row["tags"].split(","):
                            tag_name = tag_name.strip()
                            if tag_name:
                                tag = Tag.query.filter_by(name=tag_name, user_id=user.id).first()
                                if not tag:
                                    tag = Tag(name=tag_name, user_id=user.id)
                                    db.session.add(tag)
                                    db.session.flush()
                                link.tags.append(tag)

                    db.session.commit()
                    success += 1

                except Exception as e:
                    db.session.rollback()
                    errors.append(f"Row {row['row']}: {str(e)}")
                    skipped += 1

            flash(f"Import complete: {success} links created, {skipped} skipped.", "success")
            if errors:
                for error in errors[:10]:
                    flash(error, "warning")

            return redirect(url_for("user.links"))

    except UnicodeDecodeError:
        flash("File encoding error. Please use UTF-8 encoded CSV.", "danger")
    except Exception as e:
        flash(f"Error processing file: {str(e)}", "danger")

    return redirect(url_for("import_export.import_page"))


@import_bp.route("/template")
@login_required
def download_template():
    """Download a CSV template file."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["url", "title", "alias", "campaign", "tags", "password", "max_clicks", "expires"])
    writer.writerow([
        "https://example.com/long-url",
        "My Link",
        "mylink",
        "Summer Campaign",
        "marketing,social",
        "",
        "",
        "7d",
    ])
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="linkpulse_import_template.csv",
    )


# ---------------------------------------------------------------------------
# Analytics Export
# ---------------------------------------------------------------------------

@import_bp.route("/export/analytics")
@login_required
def export_analytics():
    """Export click analytics as CSV."""
    user = current_user()
    if not user:
        abort(403)

    links = Link.query.filter_by(user_id=user.id).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Short Code", "Original URL", "Title", "Clicks", "Created", "Status"])

    for link in links:
        writer.writerow([
            link.short_code,
            link.original_url,
            link.title or "",
            link.click_count,
            link.created_at.strftime("%Y-%m-%d %H:%M"),
            "Active" if link.is_active else "Disabled",
        ])

    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"linkpulse_analytics_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv",
    )
