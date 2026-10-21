"""Self test for the Warehouse Voice Analyst MCP server.

Run it with:
    python3 test_mcp.py

It starts mcp_server.py on a test port (or uses one already running
there), then checks the MCP flow end to end:

    1. initialize returns the server name and a protocol version.
    2. tools/list returns the six warehouse tools.
    3. tools/call for top_products returns real engine numbers.
    4. tools/call for ask_warehouse returns the same answer text and
       chart values as calling query_engine.py directly in this
       process, which proves the MCP layer adds no numbers of its own.
    5. A bad region is refused with isError true.
    6. An unknown tool gets a JSON-RPC error.

Uses only the Python standard library. Exits 0 when every check passes.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("MCP_TEST_PORT", "8002"))
BASE = "http://127.0.0.1:%d" % PORT
ENDPOINT = BASE + "/mcp"

sys.path.insert(0, HERE)
from query_engine import QueryEngine  # noqa: E402

FAILURES = []


def check(label, condition, detail=""):
    print("%s %s%s" % ("PASS" if condition else "FAIL", label,
                       (" :: " + detail) if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def post(payload):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=body,
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8")
        return err.code, (json.loads(raw) if raw else None)


def rpc(req_id, method, params=None):
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    return post(payload)


def server_up():
    try:
        req = urllib.request.Request(BASE + "/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def main():
    proc = None
    if not server_up():
        proc = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "mcp_server.py"), "--port", str(PORT)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(50):
            if server_up():
                break
            time.sleep(0.2)
    try:
        run_checks()
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    print()
    if FAILURES:
        print("FAILED: %d check(s) did not pass: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("All MCP checks passed.")
    return 0


def run_checks():
    with open(os.path.join(HERE, "data", "sample_data.json")) as f:
        engine = QueryEngine(json.load(f))

    # 1. initialize
    status, resp = rpc(1, "initialize", {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test_mcp.py", "version": "1.0.0"},
    })
    result = (resp or {}).get("result", {})
    check("initialize status 200", status == 200, "got %s" % status)
    check("initialize server name",
          result.get("serverInfo", {}).get("name") == "warehouse-voice-analyst",
          "got %r" % result.get("serverInfo"))
    check("initialize protocol version",
          result.get("protocolVersion") == "2025-06-18",
          "got %r" % result.get("protocolVersion"))

    # notification gets a 202 and no body
    status, resp = post({"jsonrpc": "2.0", "method": "notifications/initialized"})
    check("notifications/initialized accepted with 202", status == 202 and resp is None,
          "got status %s body %r" % (status, resp))

    # ping
    status, resp = rpc(2, "ping")
    check("ping returns empty result", (resp or {}).get("result") == {})

    # 2. tools/list
    status, resp = rpc(3, "tools/list")
    tools = (resp or {}).get("result", {}).get("tools", [])
    names = [t["name"] for t in tools]
    expected = ["top_products", "sales_by_region", "monthly_trend",
                "low_stock", "return_rates", "ask_warehouse"]
    check("tools/list returns the six tools", names == expected, "got %r" % names)
    check("every tool has a description and inputSchema",
          all(t.get("description") and t.get("inputSchema", {}).get("type") == "object"
              for t in tools))

    # 3. tools/call top_products with limit 3, compared with the engine
    status, resp = rpc(4, "tools/call", {"name": "top_products", "arguments": {"limit": 3}})
    result = (resp or {}).get("result", {})
    structured = result.get("structuredContent", {})
    direct = engine.answer("What are the top 3 selling products?")
    check("top_products isError false", result.get("isError") is False)
    check("top_products answer matches the engine exactly",
          structured.get("answer_text") == direct["answer_text"],
          "mcp: %r engine: %r" % (structured.get("answer_text"), direct["answer_text"]))
    check("top_products chart values match the engine exactly",
          structured.get("chart", {}).get("values") == direct["chart"]["values"]
          and structured.get("chart", {}).get("labels") == direct["chart"]["labels"])
    print("     top_products answer: %s" % structured.get("answer_text"))

    # 4. tools/call ask_warehouse, compared with the engine
    question = "Which products are low on stock?"
    status, resp = rpc(5, "tools/call", {"name": "ask_warehouse",
                                         "arguments": {"question": question}})
    result = (resp or {}).get("result", {})
    structured = result.get("structuredContent", {})
    direct = engine.answer(question)
    content_texts = [c.get("text", "") for c in result.get("content", [])]
    check("ask_warehouse first content block is the summary",
          bool(content_texts) and content_texts[0] == direct["answer_text"])
    check("ask_warehouse structured answer matches the engine exactly",
          structured.get("answer_text") == direct["answer_text"]
          and structured.get("chart") == direct["chart"]
          and structured.get("sql") == direct["sql_like"])
    print("     ask_warehouse answer: %s" % structured.get("answer_text"))

    # 5. bad input is refused with isError true
    status, resp = rpc(6, "tools/call", {"name": "top_products",
                                         "arguments": {"region": "Nowhere"}})
    result = (resp or {}).get("result", {})
    check("bad region returns isError true", result.get("isError") is True,
          "got %r" % result)

    status, resp = rpc(7, "tools/call", {"name": "ask_warehouse", "arguments": {}})
    result = (resp or {}).get("result", {})
    check("missing question returns isError true", result.get("isError") is True)

    # 6. unknown tool gets a JSON-RPC error
    status, resp = rpc(8, "tools/call", {"name": "no_such_tool", "arguments": {}})
    check("unknown tool returns a JSON-RPC error",
          "error" in (resp or {}), "got %r" % resp)

    # unknown method gets a JSON-RPC error too
    status, resp = rpc(9, "no/such/method")
    check("unknown method returns error code -32601",
          (resp or {}).get("error", {}).get("code") == -32601, "got %r" % resp)


if __name__ == "__main__":
    sys.exit(main())
