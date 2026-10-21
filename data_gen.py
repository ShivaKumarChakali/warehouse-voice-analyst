"""Generate the sample retail warehouse dataset for Warehouse Voice Analyst.

This is SAMPLE DATA ONLY. It is made up for the demo so judges can run the
app offline. It does not come from any real warehouse or retailer.

Run it with:
    python3 data_gen.py

It writes:
    data/sample_data.json   (everything the server loads)
    data/sales.csv
    data/inventory.csv
    data/returns.csv
"""

import csv
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")

PRODUCTS = [
    # name, category, unit price, base monthly units (popularity)
    ("Aurora Wireless Headphones", "Audio", 89.99, 420),
    ("TrailBlazer Backpack", "Outdoor", 64.50, 260),
    ("ChefPro Knife Set", "Kitchen", 119.00, 180),
    ("LumaDesk Lamp", "Home", 42.99, 310),
    ("Vortex Blender Pro", "Kitchen", 149.99, 150),
    ("FlexFit Yoga Mat", "Fitness", 29.99, 380),
    ("SwiftStep Running Shoes", "Fitness", 99.99, 290),
    ("PureSip Water Bottle", "Outdoor", 19.99, 520),
    ("ClearView Monitor Stand", "Tech", 54.99, 210),
    ("CozyNest Throw Blanket", "Home", 39.99, 240),
    ("VoltDock Charging Station", "Tech", 34.99, 450),
    ("GripMax Dumbbell Set", "Fitness", 79.99, 170),
]

REGIONS = ["North", "South", "East", "West", "Central"]
REGION_FACTOR = {"North": 1.15, "South": 1.05, "East": 0.95, "West": 1.10, "Central": 0.80}

MONTHS = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05",
          "2026-06", "2026-07", "2026-08", "2026-09"]

RETURN_REASONS = {
    "Aurora Wireless Headphones": "Battery stopped holding a charge",
    "TrailBlazer Backpack": "Zipper failed",
    "ChefPro Knife Set": "Arrived with a chipped blade",
    "LumaDesk Lamp": "Wrong color for the buyer",
    "Vortex Blender Pro": "Motor noise reported as too loud",
    "FlexFit Yoga Mat": "Thinner than expected",
    "SwiftStep Running Shoes": "Wrong size ordered",
    "PureSip Water Bottle": "Lid leaked",
    "ClearView Monitor Stand": "Did not fit the desk",
    "CozyNest Throw Blanket": "Color looked different in person",
    "VoltDock Charging Station": "Charging slower than expected",
    "GripMax Dumbbell Set": "Grip coating peeling",
}

# Products where we deliberately create low stock alerts in some regions.
LOW_STOCK_PLAN = {
    ("Aurora Wireless Headphones", "West"),
    ("PureSip Water Bottle", "North"),
    ("VoltDock Charging Station", "East"),
    ("FlexFit Yoga Mat", "South"),
    ("SwiftStep Running Shoes", "Central"),
    ("CozyNest Throw Blanket", "West"),
}


def build_data():
    rng = random.Random(42)
    sales = []
    totals_by_product = {}

    for name, category, price, base_units in PRODUCTS:
        totals_by_product[name] = 0
        for month_index, month in enumerate(MONTHS):
            growth = 1.0 + 0.03 * month_index          # gentle upward trend
            seasonal = 1.12 if month in ("2026-06", "2026-07") else 1.0
            for region in REGIONS:
                units = int(base_units * REGION_FACTOR[region] * growth * seasonal
                            * rng.uniform(0.85, 1.15) / len(REGIONS) * 5)
                revenue = round(units * price, 2)
                sales.append({
                    "month": month,
                    "product": name,
                    "category": category,
                    "region": region,
                    "units": units,
                    "revenue": revenue,
                })
                totals_by_product[name] += units

    inventory = []
    for name, category, price, base_units in PRODUCTS:
        reorder_point = max(20, int(base_units * 0.18))
        for region in REGIONS:
            if (name, region) in LOW_STOCK_PLAN:
                stock = rng.randint(3, max(4, reorder_point - 5))
            else:
                stock = rng.randint(reorder_point + 15, reorder_point + 160)
            inventory.append({
                "product": name,
                "category": category,
                "region": region,
                "stock_on_hand": stock,
                "reorder_point": reorder_point,
            })

    returns = []
    for name, category, price, base_units in PRODUCTS:
        sold = totals_by_product[name]
        # Return rates between about 1.5% and 6.5%, higher for a few products.
        rate_bias = {"PureSip Water Bottle": 0.062, "VoltDock Charging Station": 0.055,
                     "SwiftStep Running Shoes": 0.048}.get(name, rng.uniform(0.015, 0.04))
        returned = int(sold * rate_bias)
        returns.append({
            "product": name,
            "category": category,
            "units_sold": sold,
            "returned_units": returned,
            "main_reason": RETURN_REASONS[name],
        })

    return {
        "meta": {
            "label": "Sample data only, generated for this demo. Not real sales data.",
            "months": MONTHS,
            "regions": REGIONS,
            "product_count": len(PRODUCTS),
        },
        "sales": sales,
        "inventory": inventory,
        "returns": returns,
    }


def write_data(data=None):
    if data is None:
        data = build_data()
    os.makedirs(DATA_DIR, exist_ok=True)

    with open(os.path.join(DATA_DIR, "sample_data.json"), "w") as f:
        json.dump(data, f, indent=1)

    with open(os.path.join(DATA_DIR, "sales.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["month", "product", "category", "region", "units", "revenue"])
        w.writeheader()
        w.writerows(data["sales"])

    with open(os.path.join(DATA_DIR, "inventory.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["product", "category", "region", "stock_on_hand", "reorder_point"])
        w.writeheader()
        w.writerows(data["inventory"])

    with open(os.path.join(DATA_DIR, "returns.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["product", "category", "units_sold", "returned_units", "main_reason"])
        w.writeheader()
        w.writerows(data["returns"])

    return data


if __name__ == "__main__":
    d = write_data()
    print("Wrote sample data: %d sales rows, %d inventory rows, %d return rows."
          % (len(d["sales"]), len(d["inventory"]), len(d["returns"])))
