"""Seed a demo DuckDB for StoneCraft Supply pricing demo.

Creates a DuckDB file with raw materials, bills of materials, production
runs, and sales orders for a concrete slab manufacturer. Designed to
pair with Notion pages that contain business context (margin definitions,
cost formulas, competitive intel) the agent needs to write correct dbt models.

Usage:
    python scripts/seed_demo_duckdb.py [output_path]

Default output: ~/demo_stonecraft.duckdb
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_OUTPUT_PATH = Path.home() / "demo_stonecraft.duckdb"

LABOR_RATE = 45.00
ENERGY_RATE = 0.14

SLAB_TYPES = [
    ("STD-4", "Standard 4-inch", 4, "standard"),
    ("STD-6", "Standard 6-inch", 6, "standard"),
    ("REINF-4", "Reinforced 4-inch", 4, "reinforced"),
    ("REINF-6", "Reinforced 6-inch", 6, "reinforced"),
]

RAW_MATERIALS = [
    (1, "Portland Cement", 0.12, "lb", "Lehigh Hanson"),
    (2, "Aggregate", 0.04, "lb", "LocalQuarry"),
    (3, "Sand", 0.03, "lb", "LocalQuarry"),
    (4, "Rebar #4", 1.85, "ft", "SteelCo"),
    (5, "Fiber Mesh", 0.95, "sq_ft", "FiberTech"),
    (6, "Form Oil", 0.55, "oz", "ChemRelease"),
    (7, "Curing Compound", 0.40, "oz", "CureTech"),
]

# (slab_type, material_id, qty_per_unit)
BILLS_OF_MATERIALS = [
    # STD-4: cement + aggregate + sand + form oil + curing compound
    ("STD-4", 1, 42.0),
    ("STD-4", 2, 95.0),
    ("STD-4", 3, 60.0),
    ("STD-4", 6, 4.0),
    ("STD-4", 7, 6.0),
    # STD-6: more material for thicker slab
    ("STD-6", 1, 63.0),
    ("STD-6", 2, 140.0),
    ("STD-6", 3, 90.0),
    ("STD-6", 6, 4.0),
    ("STD-6", 7, 8.0),
    # REINF-4: standard 4 + rebar + fiber mesh
    ("REINF-4", 1, 44.0),
    ("REINF-4", 2, 100.0),
    ("REINF-4", 3, 62.0),
    ("REINF-4", 4, 12.0),
    ("REINF-4", 5, 8.0),
    ("REINF-4", 6, 4.0),
    ("REINF-4", 7, 6.0),
    # REINF-6: standard 6 + rebar + fiber mesh
    ("REINF-6", 1, 66.0),
    ("REINF-6", 2, 145.0),
    ("REINF-6", 3, 92.0),
    ("REINF-6", 4, 18.0),
    ("REINF-6", 5, 12.0),
    ("REINF-6", 6, 4.0),
    ("REINF-6", 7, 8.0),
]

# (run_id, slab_type, run_date, units_produced, labor_hours, energy_kwh, waste_pct)
PRODUCTION_RUNS = [
    (1, "STD-4", "2026-03-03", 120, 8.0, 340, 3.2),
    (2, "STD-4", "2026-03-10", 115, 7.5, 320, 2.8),
    (3, "STD-4", "2026-03-17", 125, 8.5, 355, 3.5),
    (4, "STD-4", "2026-03-24", 110, 7.0, 310, 2.5),
    (5, "STD-4", "2026-04-01", 130, 8.0, 350, 3.0),
    (6, "STD-4", "2026-04-08", 118, 7.5, 330, 2.9),
    (7, "STD-4", "2026-04-15", 122, 8.0, 345, 3.1),
    (8, "STD-6", "2026-03-05", 80, 7.0, 380, 3.8),
    (9, "STD-6", "2026-03-12", 75, 6.5, 360, 3.5),
    (10, "STD-6", "2026-03-19", 85, 7.5, 400, 4.0),
    (11, "STD-6", "2026-03-26", 78, 6.5, 370, 3.6),
    (12, "STD-6", "2026-04-02", 82, 7.0, 385, 3.7),
    (13, "STD-6", "2026-04-09", 77, 6.5, 365, 3.4),
    (14, "REINF-4", "2026-03-04", 60, 9.0, 420, 4.2),
    (15, "REINF-4", "2026-03-11", 55, 8.5, 400, 4.5),
    (16, "REINF-4", "2026-03-18", 65, 9.5, 440, 4.0),
    (17, "REINF-4", "2026-03-25", 58, 8.5, 410, 4.3),
    (18, "REINF-4", "2026-04-01", 62, 9.0, 425, 4.1),
    (19, "REINF-4", "2026-04-08", 57, 8.0, 395, 3.9),
    (20, "REINF-6", "2026-03-06", 40, 10.0, 480, 5.0),
    (21, "REINF-6", "2026-03-13", 38, 9.5, 460, 4.8),
    (22, "REINF-6", "2026-03-20", 42, 10.5, 500, 5.2),
    (23, "REINF-6", "2026-03-27", 36, 9.0, 450, 4.6),
    (24, "REINF-6", "2026-04-03", 44, 10.0, 490, 5.1),
    (25, "REINF-6", "2026-04-10", 39, 9.5, 465, 4.9),
]

# (order_id, customer, slab_type, qty, unit_price, order_date, source)
SALES_ORDERS = [
    # STD-4 orders
    (1001, "BuildRight Inc", "STD-4", 50, 28.50, "2026-03-05", "wholesale"),
    (1002, "HomeBase LLC", "STD-4", 20, 30.00, "2026-03-07", "retail"),
    (1003, "Test Account", "STD-4", 1, 0.00, "2026-03-08", "internal"),
    (1004, "CityWorks Dept", "STD-4", 200, 26.00, "2026-03-10", "wholesale"),
    (1005, "Jim's Landscaping", "STD-4", 15, 31.00, "2026-03-12", "retail"),
    (1006, "BuildRight Inc", "STD-4", 80, 27.50, "2026-03-15", "wholesale"),
    (1007, "Patio Pros", "STD-4", 30, 29.50, "2026-03-18", "retail"),
    (1008, "Test Order", "STD-4", 2, 0.00, "2026-03-19", "internal"),
    (1009, "Metro Builders", "STD-4", 150, 26.50, "2026-03-22", "wholesale"),
    (1010, "HomeBase LLC", "STD-4", 25, 30.00, "2026-03-25", "retail"),
    (1011, "BuildRight Inc", "STD-4", 100, 27.00, "2026-03-28", "wholesale"),
    (1012, "Quick Fence Co", "STD-4", 40, 29.00, "2026-04-01", "retail"),
    (1013, "CityWorks Dept", "STD-4", 180, 26.00, "2026-04-05", "wholesale"),
    (1014, "Patio Pros", "STD-4", 35, 29.50, "2026-04-08", "retail"),
    (1015, "Jim's Landscaping", "STD-4", 10, 31.00, "2026-04-12", "retail"),
    # STD-6 orders
    (1016, "BuildRight Inc", "STD-6", 40, 38.00, "2026-03-06", "wholesale"),
    (1017, "Metro Builders", "STD-6", 100, 35.50, "2026-03-09", "wholesale"),
    (1018, "HomeBase LLC", "STD-6", 15, 40.00, "2026-03-11", "retail"),
    (1019, "CityWorks Dept", "STD-6", 120, 34.00, "2026-03-14", "wholesale"),
    (1020, "Patio Pros", "STD-6", 25, 39.00, "2026-03-20", "retail"),
    (1021, "BuildRight Inc", "STD-6", 60, 37.00, "2026-03-23", "wholesale"),
    (1022, "Test Internal", "STD-6", 1, 0.00, "2026-03-24", "internal"),
    (1023, "Metro Builders", "STD-6", 90, 35.50, "2026-03-27", "wholesale"),
    (1024, "HomeBase LLC", "STD-6", 20, 40.00, "2026-04-02", "retail"),
    (1025, "Quick Fence Co", "STD-6", 30, 38.50, "2026-04-06", "retail"),
    (1026, "CityWorks Dept", "STD-6", 100, 34.00, "2026-04-10", "wholesale"),
    # REINF-4 orders
    (1027, "Metro Builders", "REINF-4", 30, 45.00, "2026-03-06", "wholesale"),
    (1028, "BuildRight Inc", "REINF-4", 25, 46.00, "2026-03-10", "wholesale"),
    (1029, "CityWorks Dept", "REINF-4", 80, 42.00, "2026-03-13", "wholesale"),
    (1030, "HomeBase LLC", "REINF-4", 10, 48.00, "2026-03-16", "retail"),
    (1031, "Structural Solutions", "REINF-4", 50, 44.00, "2026-03-19", "wholesale"),
    (1032, "BuildRight Inc", "REINF-4", 35, 45.50, "2026-03-24", "wholesale"),
    (1033, "Test QA", "REINF-4", 1, 0.00, "2026-03-25", "internal"),
    (1034, "Metro Builders", "REINF-4", 40, 44.50, "2026-03-28", "wholesale"),
    (1035, "Structural Solutions", "REINF-4", 45, 44.00, "2026-04-03", "wholesale"),
    (1036, "HomeBase LLC", "REINF-4", 12, 48.00, "2026-04-07", "retail"),
    (1037, "CityWorks Dept", "REINF-4", 70, 42.00, "2026-04-11", "wholesale"),
    # REINF-6 orders
    (1038, "Structural Solutions", "REINF-6", 20, 60.00, "2026-03-07", "wholesale"),
    (1039, "Metro Builders", "REINF-6", 15, 61.00, "2026-03-11", "wholesale"),
    (1040, "BuildRight Inc", "REINF-6", 18, 62.00, "2026-03-15", "wholesale"),
    (1041, "CityWorks Dept", "REINF-6", 50, 56.00, "2026-03-18", "wholesale"),
    (1042, "HomeBase LLC", "REINF-6", 8, 65.00, "2026-03-22", "retail"),
    (1043, "Structural Solutions", "REINF-6", 25, 59.50, "2026-03-26", "wholesale"),
    (1044, "Test Slab", "REINF-6", 1, 0.00, "2026-03-27", "internal"),
    (1045, "Metro Builders", "REINF-6", 20, 60.50, "2026-04-01", "wholesale"),
    (1046, "BuildRight Inc", "REINF-6", 22, 61.50, "2026-04-05", "wholesale"),
    (1047, "CityWorks Dept", "REINF-6", 40, 56.00, "2026-04-09", "wholesale"),
    (1048, "Structural Solutions", "REINF-6", 30, 59.00, "2026-04-13", "wholesale"),
]

# Competitor prices from April trade show
COMPETITOR_PRICES = [
    ("MarketSlab", "STD-4", 26.00),
    ("MarketSlab", "STD-6", 34.00),
    ("MarketSlab", "REINF-4", 38.00),
    ("MarketSlab", "REINF-6", 52.00),
    ("SlabKing", "STD-4", 27.50),
    ("SlabKing", "STD-6", 36.00),
    ("SlabKing", "REINF-4", 41.00),
    ("SlabKing", "REINF-6", 55.00),
]


def _create_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create all tables in the demo database."""
    con.execute("""
        CREATE TABLE slab_types (
            slab_type VARCHAR PRIMARY KEY,
            description VARCHAR NOT NULL,
            thickness_inches INTEGER NOT NULL,
            category VARCHAR NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE raw_materials (
            material_id INTEGER PRIMARY KEY,
            material_name VARCHAR NOT NULL,
            unit_cost DOUBLE NOT NULL,
            unit VARCHAR NOT NULL,
            supplier VARCHAR NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE bills_of_materials (
            slab_type VARCHAR NOT NULL REFERENCES slab_types(slab_type),
            material_id INTEGER NOT NULL REFERENCES raw_materials(material_id),
            qty_per_unit DOUBLE NOT NULL,
            PRIMARY KEY (slab_type, material_id)
        )
    """)
    con.execute("""
        CREATE TABLE production_runs (
            run_id INTEGER PRIMARY KEY,
            slab_type VARCHAR NOT NULL REFERENCES slab_types(slab_type),
            run_date DATE NOT NULL,
            units_produced INTEGER NOT NULL,
            labor_hours DOUBLE NOT NULL,
            energy_kwh DOUBLE NOT NULL,
            waste_pct DOUBLE NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE sales_orders (
            order_id INTEGER PRIMARY KEY,
            customer VARCHAR NOT NULL,
            slab_type VARCHAR NOT NULL REFERENCES slab_types(slab_type),
            qty INTEGER NOT NULL,
            unit_price DOUBLE NOT NULL,
            order_date DATE NOT NULL,
            source VARCHAR NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE competitor_prices (
            competitor VARCHAR NOT NULL,
            slab_type VARCHAR NOT NULL REFERENCES slab_types(slab_type),
            price DOUBLE NOT NULL,
            PRIMARY KEY (competitor, slab_type)
        )
    """)


def _insert_data(con: duckdb.DuckDBPyConnection) -> None:
    """Insert all demo data."""
    con.executemany(
        "INSERT INTO slab_types VALUES (?, ?, ?, ?)", SLAB_TYPES
    )
    con.executemany(
        "INSERT INTO raw_materials VALUES (?, ?, ?, ?, ?)", RAW_MATERIALS
    )
    con.executemany(
        "INSERT INTO bills_of_materials VALUES (?, ?, ?)", BILLS_OF_MATERIALS
    )
    con.executemany(
        "INSERT INTO production_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
        PRODUCTION_RUNS,
    )
    con.executemany(
        "INSERT INTO sales_orders VALUES (?, ?, ?, ?, ?, ?, ?)", SALES_ORDERS
    )
    con.executemany(
        "INSERT INTO competitor_prices VALUES (?, ?, ?)", COMPETITOR_PRICES
    )


def _add_comments(con: duckdb.DuckDBPyConnection) -> None:
    """Add table comments for schema discovery."""
    con.execute(
        "COMMENT ON TABLE slab_types IS "
        "'Slab product catalog — type codes, dimensions, category'"
    )
    con.execute(
        "COMMENT ON TABLE raw_materials IS "
        "'Raw material costs and suppliers'"
    )
    con.execute(
        "COMMENT ON TABLE bills_of_materials IS "
        "'Material recipe per slab type — qty of each material needed per unit'"
    )
    con.execute(
        "COMMENT ON TABLE production_runs IS "
        "'Production batch records — labor, energy, waste per run'"
    )
    con.execute(
        "COMMENT ON TABLE sales_orders IS "
        "'Customer sales orders — includes internal test orders'"
    )
    con.execute(
        "COMMENT ON TABLE competitor_prices IS "
        "'Competitor pricing from April 2026 trade show'"
    )


def main() -> None:
    """Build the demo DuckDB file."""
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT_PATH

    if output_path.exists():
        output_path.unlink()

    con = duckdb.connect(str(output_path))
    _create_schema(con)
    _insert_data(con)
    _add_comments(con)
    con.close()

    print(f"Demo DuckDB created: {output_path}")
    print("Tables: slab_types, raw_materials, bills_of_materials,")
    print("        production_runs, sales_orders, competitor_prices")


if __name__ == "__main__":
    main()
