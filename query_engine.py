"""Query engine for Warehouse Voice Analyst.

A small deterministic rule engine. It reads the question, works out which
family it belongs to with plain pattern matching, and then runs a real
aggregation over the sample data in Python. Every number in an answer is
computed from the data at run time. Nothing is hard coded.

Each answer also returns the SQL the agent would run against a real
warehouse (for example Snowflake on AWS). The local demo does not run that
SQL. It is shown so a human can see exactly what query the words map to.
In production the wording layer would sit on Amazon Bedrock and the query
would run through an MCP server, as described in the README.
"""

import re
from collections import defaultdict

MONTH_NAMES = {
    "2026-01": "Jan 2026", "2026-02": "Feb 2026", "2026-03": "Mar 2026",
    "2026-04": "Apr 2026", "2026-05": "May 2026", "2026-06": "Jun 2026",
    "2026-07": "Jul 2026", "2026-08": "Aug 2026", "2026-09": "Sep 2026",
}


def money(value):
    return "$" + format(round(value), ",d")


class QueryEngine:
    def __init__(self, data):
        self.sales = data["sales"]
        self.inventory = data["inventory"]
        self.returns = data["returns"]
        self.months = data["meta"]["months"]
        self.regions = data["meta"]["regions"]
        self.products = sorted({row["product"] for row in self.sales},
                               key=len, reverse=True)

    # ---------- helpers ----------

    def find_product(self, text):
        for name in self.products:
            if name.lower() in text:
                return name
        # Also match on a distinctive single word, for example " blender ".
        for name in self.products:
            for word in name.lower().split():
                if len(word) >= 5 and word in text:
                    return name
        return None

    def find_region(self, text):
        for region in self.regions:
            if region.lower() in text:
                return region
        return None

    def sales_rows(self, product=None, region=None):
        rows = self.sales
        if product:
            rows = [r for r in rows if r["product"] == product]
        if region:
            rows = [r for r in rows if r["region"] == region]
        return rows

    # ---------- intent answers ----------

    def answer_help(self):
        text = ("I am your warehouse voice analyst, running on sample data. "
                "You can ask me about best selling products, sales by region, "
                "the sales trend by month, low stock alerts, and return rates. "
                "Tap one of the example questions below, or type your own.")
        return {
            "answer_text": text,
            "chart": {"type": "none", "labels": [], "values": []},
            "sql_like": "-- No query needed. This is the help response.",
            "explanation": "The help family is matched by words like help or what can you do.",
        }

    def answer_top_products(self, text, product=None):
        match = re.search(r"top\s+(\d+)", text)
        limit = int(match.group(1)) if match else 5
        limit = max(1, min(limit, 10))
        region = self.find_region(text)
        totals = defaultdict(float)
        units = defaultdict(int)
        for row in self.sales_rows(region=region):
            totals[row["product"]] += row["revenue"]
            units[row["product"]] += row["units"]
        ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        scope = " in the %s region" % region if region else ""
        lead = ranked[0]
        text_out = ("Top %d products by revenue%s: %s leads with %s from %s units sold. "
                    % (limit, scope, lead[0], money(lead[1]), format(units[lead[0]], ",d"))
                    + " Next: " + ", ".join("%s (%s)" % (n, money(v)) for n, v in ranked[1:]) + ".")
        where = " WHERE region = '%s'" % region if region else ""
        return {
            "answer_text": text_out,
            "chart": {"type": "bar", "labels": [n for n, v in ranked],
                      "values": [round(v, 2) for n, v in ranked]},
            "sql_like": ("SELECT product_name, SUM(revenue) AS total_revenue, SUM(units) AS units_sold\n"
                         "FROM warehouse.sales%s\n"
                         "GROUP BY product_name\n"
                         "ORDER BY total_revenue DESC\n"
                         "LIMIT %d;" % (where, limit)),
            "explanation": "Groups all sample sales rows by product, sums revenue, sorts high to low, and keeps the top %d." % limit,
        }

    def answer_by_region(self, text, product=None):
        totals = defaultdict(float)
        for row in self.sales_rows(product=product):
            totals[row["region"]] += row["revenue"]
        ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
        scope = " for %s" % product if product else ""
        lead = ranked[0]
        text_out = ("Sales by region%s: %s is the top region with %s. "
                    % (scope, lead[0], money(lead[1]))
                    + " Full list: " + ", ".join("%s %s" % (n, money(v)) for n, v in ranked) + ".")
        where = " WHERE product_name = '%s'" % product if product else ""
        return {
            "answer_text": text_out,
            "chart": {"type": "bar", "labels": [n for n, v in ranked],
                      "values": [round(v, 2) for n, v in ranked]},
            "sql_like": ("SELECT region, SUM(revenue) AS total_revenue\n"
                         "FROM warehouse.sales%s\n"
                         "GROUP BY region\n"
                         "ORDER BY total_revenue DESC;" % where),
            "explanation": "Groups sales by region and sums revenue, optionally filtered to one product.",
        }

    def answer_trend(self, text, product=None):
        region = self.find_region(text)
        totals = defaultdict(float)
        for row in self.sales_rows(product=product, region=region):
            totals[row["month"]] += row["revenue"]
        labels = [MONTH_NAMES[m] for m in self.months]
        values = [round(totals[m], 2) for m in self.months]
        first, last = values[0], values[-1]
        change = ((last - first) / first * 100) if first else 0.0
        scope = ""
        if product:
            scope = " for %s" % product
        if region:
            scope += " in the %s region" % region
        direction = "up" if change >= 0 else "down"
        text_out = ("Monthly sales trend%s: revenue moved from %s in %s to %s in %s, "
                    "%s %.1f percent over the period. The strongest month was %s at %s."
                    % (scope, money(first), labels[0], money(last), labels[-1],
                       direction, abs(change),
                       labels[values.index(max(values))], money(max(values))))
        filters = []
        if product:
            filters.append("product_name = '%s'" % product)
        if region:
            filters.append("region = '%s'" % region)
        where = (" WHERE " + " AND ".join(filters)) if filters else ""
        return {
            "answer_text": text_out,
            "chart": {"type": "line", "labels": labels, "values": values},
            "sql_like": ("SELECT month, SUM(revenue) AS total_revenue\n"
                         "FROM warehouse.sales%s\n"
                         "GROUP BY month\n"
                         "ORDER BY month;" % where),
            "explanation": "Groups sales by month in date order and sums revenue, so the line chart shows the trend.",
        }

    def answer_low_stock(self, text, product=None):
        rows = [r for r in self.inventory if r["stock_on_hand"] <= r["reorder_point"]]
        if product:
            rows = [r for r in rows if r["product"] == product]
        rows.sort(key=lambda r: r["stock_on_hand"])
        if not rows:
            return {
                "answer_text": "Good news: nothing is at or below its reorder point in the sample inventory right now.",
                "chart": {"type": "none", "labels": [], "values": []},
                "sql_like": "SELECT product_name, region, stock_on_hand, reorder_point\nFROM warehouse.inventory\nWHERE stock_on_hand <= reorder_point;",
                "explanation": "Filters inventory to rows where stock on hand is at or below the reorder point.",
            }
        shown = rows[:8]
        labels = ["%s (%s)" % (r["product"], r["region"]) for r in shown]
        values = [r["stock_on_hand"] for r in shown]
        worst = shown[0]
        text_out = ("Low stock alert: %d product and region pairs are at or below their reorder point. "
                    "The most urgent is %s in the %s region with only %d units left (reorder point %d). "
                    "Full list: %s."
                    % (len(rows), worst["product"], worst["region"], worst["stock_on_hand"],
                       worst["reorder_point"],
                       ", ".join("%s in %s has %d left" % (r["product"], r["region"], r["stock_on_hand"]) for r in shown)))
        return {
            "answer_text": text_out,
            "chart": {"type": "bar", "labels": labels, "values": values},
            "sql_like": ("SELECT product_name, region, stock_on_hand, reorder_point\n"
                         "FROM warehouse.inventory\n"
                         "WHERE stock_on_hand <= reorder_point\n"
                         "ORDER BY stock_on_hand ASC;"),
            "explanation": "Filters inventory to rows where stock on hand is at or below the reorder point, lowest stock first. The chart shows units left for the worst cases.",
        }

    def answer_returns(self, text, product=None):
        rows = []
        for row in self.returns:
            rate = row["returned_units"] / row["units_sold"] * 100 if row["units_sold"] else 0.0
            rows.append((row["product"], round(rate, 2), row["returned_units"], row["main_reason"]))
        rows.sort(key=lambda r: r[1], reverse=True)
        if product:
            for name, rate, count, reason in rows:
                if name == product:
                    return {
                        "answer_text": ("%s has a return rate of %.2f percent (%s units returned out of %s sold). "
                                        "The most common reason in the sample data is: %s."
                                        % (name, rate, format(count, ",d"),
                                           format(next(r["units_sold"] for r in self.returns if r["product"] == name), ",d"),
                                           reason)),
                        "chart": {"type": "bar", "labels": [n for n, rt, c, rs in rows[:6]],
                                  "values": [rt for n, rt, c, rs in rows[:6]]},
                        "sql_like": ("SELECT product_name, returned_units, units_sold,\n"
                                     "       returned_units / units_sold * 100 AS return_rate_pct\n"
                                     "FROM warehouse.returns\n"
                                     "WHERE product_name = '%s';" % name),
                        "explanation": "Divides returned units by units sold for the named product, and pulls its top return reason.",
                    }
        shown = rows[:6]
        worst = shown[0]
        text_out = ("Return rates: %s has the highest return rate at %.2f percent (%s units returned). "
                    "The most common reason is: %s. "
                    "Next highest: %s."
                    % (worst[0], worst[1], format(worst[2], ",d"), worst[3],
                       ", ".join("%s at %.2f percent" % (n, rt) for n, rt, c, rs in shown[1:4])))
        return {
            "answer_text": text_out,
            "chart": {"type": "bar", "labels": [n for n, rt, c, rs in shown],
                      "values": [rt for n, rt, c, rs in shown]},
            "sql_like": ("SELECT product_name, returned_units, units_sold,\n"
                         "       returned_units / units_sold * 100 AS return_rate_pct\n"
                         "FROM warehouse.returns\n"
                         "ORDER BY return_rate_pct DESC\n"
                         "LIMIT 6;"),
            "explanation": "Divides returned units by units sold for every product and sorts by return rate, highest first.",
        }

    def answer_total(self, text, product=None):
        rows = self.sales_rows(product=product)
        total_revenue = sum(r["revenue"] for r in rows)
        total_units = sum(r["units"] for r in rows)
        scope = " for %s" % product if product else " across all products and regions"
        text_out = ("Total sales%s in the sample data: %s from %s units, covering %s to %s."
                    % (scope, money(total_revenue), format(total_units, ",d"),
                       MONTH_NAMES[self.months[0]], MONTH_NAMES[self.months[-1]]))
        return {
            "answer_text": text_out,
            "chart": {"type": "none", "labels": [], "values": []},
            "sql_like": "SELECT SUM(revenue) AS total_revenue, SUM(units) AS units_sold\nFROM warehouse.sales;",
            "explanation": "Sums revenue and units over the whole sample sales table.",
        }

    def answer_fallback(self):
        return {
            "answer_text": ("I am not sure how to answer that one yet. I can help with: "
                            "top selling products, sales by region, sales trend by month, "
                            "low stock alerts, and return rates. Try one of the example questions below."),
            "chart": {"type": "none", "labels": [], "values": []},
            "sql_like": "-- No matching question family, so no query was run.",
            "explanation": "The question did not match any known family, so the assistant explains what it can do.",
        }

    # ---------- main entry ----------

    def answer(self, question):
        text = " " + (question or "").lower().strip() + " "
        product = self.find_product(text)

        if any(w in text for w in (" help ", " what can you do", " who are you", " hello ", " hi ")):
            if " hi " in text or " hello " in text:
                if not any(w in text for w in (" help ", " what can you do")):
                    return self.answer_help()
            return self.answer_help()
        if any(w in text for w in ("return", "refund")):
            return self.answer_returns(text, product)
        if any(w in text for w in ("low stock", "out of stock", "inventory", "stock", "reorder", "running low")):
            return self.answer_low_stock(text, product)
        if any(w in text for w in ("trend", "by month", "monthly", "over time", "each month")):
            return self.answer_trend(text, product)
        if any(w in text for w in ("region", "regional")):
            return self.answer_by_region(text, product)
        if any(w in text for w in ("top", "best selling", "best seller", "most popular", "selling")):
            return self.answer_top_products(text, product)
        if any(w in text for w in ("total sales", "total revenue", "how much", "overall sales")):
            return self.answer_total(text, product)
        return self.answer_fallback()
