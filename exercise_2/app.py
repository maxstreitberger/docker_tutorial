import os
import socket
from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    name = os.environ.get("APP_NAME", "flask")
    return f"Hello from {name}! Running in "\
           f"container {socket.gethostname()}\n"




