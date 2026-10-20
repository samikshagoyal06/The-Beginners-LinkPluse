"""Campaign management routes."""

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
)

from models import db, Campaign, Link
from routes.auth import login_required, current_user

campaigns_bp = Blueprint("campaigns", __name__, url_prefix="/app/campaigns")


@campaigns_bp.route("/")
@login_required
def list_campaigns():
    """List all campaigns for the current user."""
    user = current_user()
    if not user:
        abort(403)

    campaigns = Campaign.query.filter_by(user_id=user.id).order_by(Campaign.created_at.desc()).all()

    return render_template("user/campaigns.html", campaigns=campaigns, user=user)


@campaigns_bp.route("/new", methods=["GET", "POST"])
@login_required
def create_campaign():
    """Create a new campaign."""
    user = current_user()
    if not user:
        abort(403)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()

        if not name:
            flash("Campaign name is required.", "danger")
            return render_template("user/campaign_create.html", user=user), 400

        campaign = Campaign(
            name=name,
            description=description or None,
            user_id=user.id,
        )
        db.session.add(campaign)
        db.session.commit()

        flash(f"Campaign '{name}' created.", "success")
        return redirect(url_for("campaigns.campaign_detail", campaign_id=campaign.id))

    return render_template("user/campaign_create.html", user=user)


@campaigns_bp.route("/<int:campaign_id>")
@login_required
def campaign_detail(campaign_id):
    """View campaign details and links."""
    user = current_user()
    if not user:
        abort(403)

    campaign = Campaign.query.get_or_404(campaign_id)
    if campaign.user_id != user.id:
        abort(403)

    links = Link.query.filter_by(campaign_id=campaign_id).order_by(Link.created_at.desc()).all()

    return render_template(
        "user/campaign_detail.html",
        campaign=campaign,
        links=links,
        user=user,
    )


@campaigns_bp.route("/<int:campaign_id>/delete", methods=["POST"])
@login_required
def delete_campaign(campaign_id):
    """Delete a campaign."""
    user = current_user()
    if not user:
        abort(403)

    campaign = Campaign.query.get_or_404(campaign_id)
    if campaign.user_id != user.id:
        abort(403)

    # Unassign links from campaign
    Link.query.filter_by(campaign_id=campaign_id).update({"campaign_id": None})
    db.session.delete(campaign)
    db.session.commit()

    flash("Campaign deleted.", "success")
    return redirect(url_for("campaigns.list_campaigns"))
