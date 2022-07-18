from flask import Flask
server = Flask(__name__)

# all other imports should be after this line, this is to prevent 'circular imports'
from app.views import index
