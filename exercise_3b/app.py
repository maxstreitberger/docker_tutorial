import os
import socket
import psycopg
from flask import Flask

app = Flask(__name__)

def get_conn():
    with open(os.environ["DB_PASSWORD_FILE"]) as f:
        password = f.read().strip()
    return psycopg.connect(
        host=os.environ["DB_HOST"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=password,
    )

@app.route("/")
def index():
    with get_conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS visits ("
            "id serial PRIMARY KEY, "
            "ts timestamptz DEFAULT now())"
        )
        conn.execute("INSERT INTO visits DEFAULT VALUES")
        count = conn.execute(
            "SELECT count(*) FROM visits"
        ).fetchone()[0]
    name = os.environ.get("APP_NAME", "flask")
    host = socket.gethostname()
    return (
        f"Greetings from {name}! "
        f"Running in container {host}. "
        f"Visits: {count}\n"
    )





