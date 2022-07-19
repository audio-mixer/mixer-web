from flask import Flask
from flask_sock import Sock
server = Flask(__name__)
socket = Sock(server)

# all other imports should be after this line, this is to prevent 'circular imports'
from app.views import index
from app.sockets import audio_stream
