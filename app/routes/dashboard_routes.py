from flask import Blueprint, jsonify, render_template, session

from app import registry
from app.decorators import tab_required
from app.faz_health_cache import get_all_cached
from app.groups import get_allowed_adoms

bp = Blueprint("dashboard", __name__)

registry.register("dashboard", "Dashboard", "dashboard.index")


@bp.route("/")
@tab_required("dashboard")
def index():
    return render_template("dashboard.html", user=session["user"])


@bp.route("/api/dashboard")
@tab_required("dashboard")
def api_dashboard():
    ad_groups = session.get("ad_groups", [])
    allowed = get_allowed_adoms(session["user"], ad_groups=ad_groups, role=session.get("role"))
    cards = get_all_cached()
    if allowed is not None:
        cards = [c for c in cards if c["label"] in allowed]
    return jsonify(cards)
