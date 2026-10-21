# Warehouse Voice Analyst

A simulated Alexa+ voice analyst for warehouse data. You type a plain English
question about sales, stock, or returns, and the analyst answers with a short
spoken style summary, a chart, and the SQL query it would run on a real data
warehouse.

Built for the "Build, Ship, Shape: Amazon Developer Hackathon" on Devpost,
Alexa+ track, using the simulated Alexa+ experience path. It also enters the
AWS Builder mini challenge (see the production architecture below) and the
Open Source mini challenge (this repo is public under the MIT license).

## The honest part first

This demo runs 100 percent locally with no accounts and no cloud calls.
The language layer is a small deterministic rule engine written in Python,
not a live large language model, and the data is sample data generated for
this project. No real Amazon Bedrock call happens in this demo.

That is on purpose. Judges can clone the repo, run one command, and see the
full experience offline. The README section "How this maps to Alexa+ and AWS
in production" explains exactly which piece each local part stands in for.

## How to run

You only need Python 3. Nothing to install. The server uses only the Python
standard library, and the front end is plain HTML, CSS, and JavaScript.

```bash
cd amazon-warehouse-voice-analyst
python3 server.py
```

Then open this in your browser:

```
http://localhost:8000
```

To use a different port:

```bash
PORT=9000 python3 server.py
```

The sample data is already in the `data` folder. If you ever delete it, the
server rebuilds it on start. You can also rebuild it yourself and tweak the
generator:

```bash
python3 data_gen.py
```

## What you can ask

Tap a chip in the app, or type one of these:

- "What are the top 5 selling products?"
- "Show me sales by region"
- "What is the sales trend by month?"
- "Which products are low on stock?"
- "Which products have the highest return rate?"
- "What can you do?"

You can also name a product, for example "What is the sales trend by month
for the Vortex Blender Pro?" or "What is the return rate for the PureSip
Water Bottle?" Every answer is computed live from the sample data with real
aggregation in Python. Nothing is hard coded.

## What you get back

- A short answer in plain English, the kind of summary Alexa+ would speak.
- A chart drawn in the browser from the answer data (bar or line, inline SVG).
- The SQL the agent would run, plus one line explaining the query in words.
- Optional voice: tick "Speak answers out loud" and the browser reads the
  summary with its built in speech synthesis. This is a simulation of the
  Alexa+ voice reply, using the browser instead of a device.

## The API

```bash
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Which products are low on stock?"}'
```

Response shape:

```json
{
  "answer_text": "Low stock alert: 6 product and region pairs are at or below...",
  "chart": {"type": "bar", "labels": ["..."], "values": [12, 8]},
  "sql_like": "SELECT product_name, region, stock_on_hand, reorder_point FROM warehouse.inventory WHERE ...",
  "explanation": "Filters inventory to rows where stock on hand is at or below the reorder point...",
  "question": "Which products are low on stock?",
  "data_note": "Sample data only, generated for this demo. Not real sales data."
}
```

There is also a health check at `GET /api/health`.

## How it is put together

| File | What it does |
| --- | --- |
| `server.py` | Web server and API. Python standard library only (`http.server`). |
| `query_engine.py` | The rule engine. Matches a question to a family, then aggregates the sample data and builds the answer, chart data, SQL, and explanation. |
| `data_gen.py` | Generates the sample dataset with a fixed random seed, so every judge sees the same numbers. |
| `data/` | `sample_data.json` plus `sales.csv`, `inventory.csv`, and `returns.csv`. Sample data only, clearly labeled. |
| `static/` | The chat web app: `index.html`, `style.css`, `app.js`. No frameworks, no build step. |

The sample dataset covers 12 products, 5 regions, and 9 months of sales
(Jan to Sep 2026), plus one inventory row per product and region, and one
returns row per product with units sold, units returned, and the most common
return reason.

## How this maps to Alexa+ and AWS in production

The demo is a stand-in for this production design:

1. **Alexa+ front door.** The user speaks to Alexa+. In the full Alexa+
   track you would build a self hosted MCP server (Streamable HTTP, MCP
   spec 2025-11-25 or later) or an Agent Skill. This demo uses the
   simulated experience path the rules allow: a web app that shows the
   same conversation.
2. **Amazon Bedrock for language.** In production, Bedrock understands the
   question, picks the right tool, and turns the result rows into a natural
   spoken answer. In the demo, `query_engine.py` does this job with plain
   pattern matching so it runs offline. This documented Bedrock design is
   the AWS Builder mini challenge entry. The demo itself makes no AWS call.
3. **MCP server and AWS Lambda for the query.** The MCP tool call would hit
   a small Lambda function that holds the approved SQL templates, fills in
   the product or region the user named, and runs the query.
4. **A real warehouse behind it.** The SQL shown in the app is written for a
   warehouse table layout (`warehouse.sales`, `warehouse.inventory`,
   `warehouse.returns`). In production that is Snowflake or Amazon Redshift,
   fed by normal data pipelines. This is where a data engineering background
   matters: clean modeled tables are what make the voice answers fast and
   trustworthy.
5. **Voice back out.** Alexa+ speaks the summary and shows the chart on a
   screen device. The demo stands in for this with browser speech synthesis
   and the SVG chart.

## Why this idea

Warehouse and operations teams ask the same five questions every morning:
what sold, where, is it growing, what is about to run out, and what keeps
coming back as returns. Today that means waiting on a dashboard or a data
request. A voice analyst that answers in seconds, and shows its SQL so the
answer can be checked, turns that wait into a conversation.

## License

MIT. See `LICENSE`. Copyright (c) 2026 Shiva Kumar Chakali.
