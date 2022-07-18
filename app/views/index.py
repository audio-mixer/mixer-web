from app import server
from flask import render_template


@server.route("/", methods=["GET"])
def index():
    return render_template("index.html")
