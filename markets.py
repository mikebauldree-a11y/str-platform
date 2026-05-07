from flask import Blueprint, render_template

markets_bp = Blueprint("markets", __name__, template_folder="templates")

@markets_bp.route("/aruba")
def aruba():
    return render_template("markets/aruba.html")
