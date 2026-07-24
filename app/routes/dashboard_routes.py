from flask import Blueprint, render_template, session
from app.decorators import tab_required
from app import registry

bp = Blueprint("dashboard", __name__)

registry.register("dashboard", "Dashboard", "dashboard.index")


@bp.route("/")
@tab_required("dashboard")
def index():
    return render_template("dashboard.html", user=session["user"])
