"""MCP server for Warehouse Voice Analyst.

A real Model Context Protocol server, written with only the Python
standard library (http.server). No pip installs, no accounts, no cloud
calls. It speaks the MCP Streamable HTTP transport: one POST endpoint
at /mcp that takes JSON-RPC 2.0 messages.

Run it with:
    python3 mcp_server.py
Then point any MCP client at:
    http://localhost:8001/mcp

Set a different port with the PORT environment variable or --port:
    PORT=9001 python3 mcp_server.py
    python3 mcp_server.py --port 9001

What it does:
    Every tool wraps the same QueryEngine the web app uses
    (query_engine.py) over the same sample data in data/. The numbers
    are computed live by that engine at call time. This file adds no
    numbers of its own, it only translates between MCP tool calls and
    engine answers.

Why this file exists:
    In the production design for the Alexa+ track, Alexa+ is the front
    door, Amazon Bedrock does the language work and picks a tool, and
    the tool call lands on an MCP server like this one, which runs the
    approved query and returns the rows. This server is that layer. It
    runs locally for the demo so judges can test it with curl, and the
    test_mcp.py script in this repo does exactly that. In production
    the same server can sit behind AWS Lambda and API Gateway, with the
    engine pointed at a real warehouse instead of the sample data.
"""

import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import data_gen
from query_engine import QueryEngine

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "data", "sample_data.json")

if not os.path.exists(DATA_FILE):
    data_gen.write_data()

with open(DATA_FILE) as f:
    DATA = json.load(f)

ENGINE = QueryEngine(DATA)

SERVER_NAME = "warehouse-voice-analyst"
SERVER_VERSION = "1.0.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = [
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
]

PRODUCT_NAMES = sorted({row["product"] for row in DATA["sales"]})
REGION_NAMES = DATA["meta"]["regions"]


# ---------- tool definitions ----------

TOOLS = [
    {
        "name": "top_products",
        "description": (
            "Top selling products by revenue, highest first. Answers "
            "questions like 'what are the top 5 selling products'. "
            "Optionally limit the list, or restrict it to one region."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                    "description": "How many products to return. Default 5.",
                },
                "region": {
                    "type": "string",
                    "enum": REGION_NAMES,
                    "description": "Optional. Only count sales in this region.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "sales_by_region",
        "description": (
            "Total sales revenue grouped by region, highest first. "
            "Optionally restrict the answer to a single product."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "product": {
                    "type": "string",
                    "description": "Optional. A product name from the catalog, for example 'Vortex Blender Pro'.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "monthly_trend",
        "description": (
            "Sales revenue by month across the sample period, in date "
            "order, with the overall change across the period. "
            "Optionally restrict to one product and one region."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "product": {
                    "type": "string",
                    "description": "Optional. A product name from the catalog.",
                },
                "region": {
                    "type": "string",
                    "enum": REGION_NAMES,
                    "description": "Optional. Only count sales in this region.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "low_stock",
        "description": (
            "Products at or below their reorder point, lowest stock "
            "first. Use this for reorder and running low questions. "
            "Optionally restrict to a single product."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "product": {
                    "type": "string",
                    "description": "Optional. A product name from the catalog.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "return_rates",
        "description": (
            "Return rate per product, highest first, with the most "
            "common return reason. Optionally ask about a single "
            "product to get its exact rate and reason."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "product": {
                    "type": "string",
                    "description": "Optional. A product name from the catalog.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "ask_warehouse",
        "description": (
            "Free form entry point. Give a plain English question about "
            "sales, regions, the monthly trend, stock, or returns, and "
            "it is routed through the same rule engine the web app uses. "
            "Example: 'What are the top 3 selling products?'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question, in plain English.",
                },
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES = [tool["name"] for tool in TOOLS]


# ---------- helpers ----------

def padded(text):
    """Match the text shape query_engine.answer builds internally."""
    return " " + (text or "").lower().strip() + " "


def resolve_product(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("product must be a product name string, for example 'Vortex Blender Pro'.")
    found = ENGINE.find_product(padded(value))
    if not found:
        raise ValueError(
            "Unknown product '%s'. Products in the sample catalog: %s."
            % (value, ", ".join(PRODUCT_NAMES))
        )
    return found


def resolve_region(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("region must be one of: %s." % ", ".join(REGION_NAMES))
    found = ENGINE.find_region(padded(value))
    if not found:
        raise ValueError(
            "Unknown region '%s'. Regions in the sample data: %s."
            % (value, ", ".join(REGION_NAMES))
        )
    return found


def resolve_limit(value):
    if value is None:
        return 5
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("limit must be a whole number between 1 and 10.")
    if value < 1 or value > 10:
        raise ValueError("limit must be between 1 and 10.")
    return value


def tool_result(engine_result):
    """Shape one engine answer as an MCP tools/call result."""
    detail = "SQL the agent would run:\n%s\n\nWhy this query: %s" % (
        engine_result["sql_like"],
        engine_result["explanation"],
    )
    return {
        "content": [
            {"type": "text", "text": engine_result["answer_text"]},
            {"type": "text", "text": detail},
        ],
        "structuredContent": {
            "answer_text": engine_result["answer_text"],
            "chart": engine_result["chart"],
            "sql": engine_result["sql_like"],
            "explanation": engine_result["explanation"],
            "data_note": DATA["meta"]["label"],
        },
        "isError": False,
    }


def error_result(message):
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


# ---------- tool implementations ----------
# Each one calls the existing QueryEngine methods. No aggregation logic
# lives in this file, so the MCP answers and the web app answers can
# never drift apart.

def run_top_products(args):
    limit = resolve_limit(args.get("limit"))
    region = resolve_region(args.get("region"))
    text = "top %d" % limit
    if region:
        text += " " + region
    return ENGINE.answer_top_products(padded(text))


def run_sales_by_region(args):
    product = resolve_product(args.get("product"))
    return ENGINE.answer_by_region(padded("sales by region"), product=product)


def run_monthly_trend(args):
    product = resolve_product(args.get("product"))
    region = resolve_region(args.get("region"))
    text = "sales trend by month"
    if region:
        text += " " + region
    return ENGINE.answer_trend(padded(text), product=product)


def run_low_stock(args):
    product = resolve_product(args.get("product"))
    return ENGINE.answer_low_stock(padded("low stock"), product=product)


def run_return_rates(args):
    product = resolve_product(args.get("product"))
    return ENGINE.answer_returns(padded("return rates"), product=product)


def run_ask_warehouse(args):
    question = args.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("ask_warehouse needs a non-empty 'question' string.")
    return ENGINE.answer(question)


TOOL_RUNNERS = {
    "top_products": run_top_products,
    "sales_by_region": run_sales_by_region,
    "monthly_trend": run_monthly_trend,
    "low_stock": run_low_stock,
    "return_rates": run_return_rates,
    "ask_warehouse": run_ask_warehouse,
}


# ---------- JSON-RPC handling ----------

def rpc_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


def rpc_result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def handle_rpc(request):
    """Return (http_status, payload_dict_or_None, extra_headers).

    A payload of None means an empty response body, used for
    notifications, which the spec answers with 202 Accepted.
    """
    if not isinstance(request, dict):
        return 400, rpc_error(None, -32600, "Invalid request: expected a JSON-RPC object."), {}

    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params") or {}
    is_notification = "id" not in request

    if isinstance(method, str) and method.startswith("notifications/"):
        return 202, None, {}

    if is_notification:
        # Unknown notification. Nothing to send back.
        return 202, None, {}

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
        result = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
        headers = {"Mcp-Session-Id": uuid.uuid4().hex}
        return 200, rpc_result(req_id, result), headers

    if method == "ping":
        return 200, rpc_result(req_id, {}), {}

    if method == "tools/list":
        return 200, rpc_result(req_id, {"tools": TOOLS}), {}

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in TOOL_RUNNERS:
            return 200, rpc_error(
                req_id, -32602,
                "Unknown tool '%s'. Available tools: %s." % (name, ", ".join(TOOL_NAMES)),
            ), {}
        if not isinstance(arguments, dict):
            return 200, rpc_result(req_id, error_result("Tool arguments must be a JSON object.")), {}
        try:
            engine_result = TOOL_RUNNERS[name](arguments)
        except ValueError as exc:
            return 200, rpc_result(req_id, error_result(str(exc))), {}
        except Exception as exc:  # keep the protocol answer clean
            return 200, rpc_result(req_id, error_result("Tool failed: %s" % exc)), {}
        return 200, rpc_result(req_id, tool_result(engine_result)), {}

    return 200, rpc_error(req_id, -32601, "Method not found: %s" % method), {}


# ---------- HTTP layer ----------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def send_body(self, status, body, content_type="application/json", extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def send_json(self, status, payload, extra_headers=None):
        self.send_body(status, json.dumps(payload).encode("utf-8"),
                       extra_headers=extra_headers)

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/mcp":
            body = json.dumps({
                "error": "This endpoint speaks MCP over POST. Send a JSON-RPC 2.0 POST request."
            }).encode("utf-8")
            return self.send_body(405, body, extra_headers={"Allow": "POST"})
        if path in ("/", "/health"):
            return self.send_json(200, {
                "status": "ok",
                "server": SERVER_NAME,
                "version": SERVER_VERSION,
                "mcp_endpoint": "/mcp",
                "tools": TOOL_NAMES,
                "data": DATA["meta"]["label"],
            })
        return self.send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path != "/mcp":
            return self.send_json(404, {"error": "not found. The MCP endpoint is POST /mcp."})
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            request = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self.send_json(400, rpc_error(None, -32700, "Parse error: request body must be JSON."))
        status, payload, headers = handle_rpc(request)
        if payload is None:
            return self.send_body(status, b"")
        return self.send_json(status, payload, extra_headers=headers)

    def do_DELETE(self):
        # Stateless server, there is no session to end. Answer cleanly.
        self.send_body(405, json.dumps({"error": "Sessions are not used by this server."}).encode("utf-8"),
                       extra_headers={"Allow": "POST"})


def pick_port(argv):
    port = int(os.environ.get("PORT", "8001"))
    if "--port" in argv:
        index = argv.index("--port")
        if index + 1 < len(argv):
            port = int(argv[index + 1])
    return port


if __name__ == "__main__":
    port = pick_port(sys.argv[1:])
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("Warehouse Voice Analyst MCP server running at http://localhost:%d/mcp" % port, flush=True)
    print("Protocol: MCP Streamable HTTP, JSON-RPC 2.0. Sample data only.", flush=True)
    print("Tools:", flush=True)
    for tool in TOOLS:
        print("  %-16s %s" % (tool["name"], tool["description"].split(". ")[0] + "."), flush=True)
    print("Test it with: python3 test_mcp.py", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
