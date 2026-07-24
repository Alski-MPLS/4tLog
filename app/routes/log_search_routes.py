from flask import Blueprint, render_template, session
from app.decorators import tab_required
from app import registry

bp = Blueprint("log_search", __name__)

registry.register("log_search", "Log Search", "log_search.index")


@bp.route("/log-search")
@tab_required("log_search")
def index():
    return render_template("log_search.html", user=session["user"])
