"""Warehouse Voice Analyst server.

Uses only the Python standard library (http.server). No pip installs.

Run it with:
    python3 server.py
Then open:
    http://localhost:8000

Set a different port with the PORT environment variable if needed.

What it serves:
    GET  /              the chat web app (static/index.html)
    GET  /static/...    CSS and JavaScript
    POST /api/ask       JSON in: {"question": "..."}
                        JSON out: {"answer_text": "...",
                                   "chart": {"type": ..., "labels": [...], "values": [...]},
                                   "sql_like": "SELECT ...",
                                   "explanation": "..."}
    GET  /api/health    simple health check

Architecture note: this local demo is the SIMULATED Alexa+ experience.
The language layer is a deterministic rule engine (query_engine.py) so
judges can run everything offline with zero setup and no accounts.
In production, the words would be understood by Amazon Bedrock, the
request would travel as an MCP call (the Alexa+ track pattern), the SQL
would run on a real warehouse such as Snowflake or Amazon Redshift behind
an AWS Lambda function, and Alexa+ would speak the answer back.
See README.md for the full picture. No real Bedrock call happens here.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import data_gen
from query_engine import QueryEngine

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "data", "sample_data.json")
STATIC_DIR = os.path.join(HERE, "static")

if not os.path.exists(DATA_FILE):
    data_gen.write_data()

with open(DATA_FILE) as f:
    DATA = json.load(f)

ENGINE = QueryEngine(DATA)

CONTENT_TYPES = {".html": "text/html", ".css": "text/css",
                 ".js": "application/javascript", ".json": "application/json"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/health":
            return self.send_json({"status": "ok", "data": DATA["meta"]["label"]})
        path = "/static/index.html" if self.path in ("/", "/index.html") else self.path
        if not path.startswith("/static/"):
            return self.send_json({"error": "not found"}, status=404)
        file_path = os.path.join(HERE, path.lstrip("/"))
        if not os.path.isfile(file_path):
            return self.send_json({"error": "not found"}, status=404)
        ext = os.path.splitext(file_path)[1]
        with open(file_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(ext, "text/plain"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/ask":
            return self.send_json({"error": "not found"}, status=404)
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.send_json({"error": "request body must be JSON"}, status=400)
        question = str(payload.get("question", "")).strip()
        if not question:
            return self.send_json({"error": "please send a question"}, status=400)
        result = ENGINE.answer(question)
        result["question"] = question
        result["data_note"] = DATA["meta"]["label"]
        return self.send_json(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("Warehouse Voice Analyst running at http://localhost:%d" % port)
    print("Sample data only. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
