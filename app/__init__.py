import os

import decouple
from decouple import config
from flask import Flask
from flask_sock import Sock

KEY = os.getenv("API_KEY")
URL = "https://www.googleapis.com/youtube/v3"
if KEY is None:
    try:
        KEY = config("API_KEY")
    except decouple.UndefinedValueError:
        exit(1)

server = Flask(
    __name__,
    static_url_path="/static",
    static_folder="../web/static",
    template_folder="../web/templates"
)

socket = Sock(server)

# all other imports should be after this line, this is to prevent 'circular imports'
from app.views import index
from app.sockets import audio_stream
