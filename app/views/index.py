import os

from app import server
from flask import render_template


@server.route("/", methods=["GET"])
def index():
    port = os.getenv("PORT")
    if port is None:
        port = 5000

    return render_template("index.html", socket_port=port)
