# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.11.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md(
        r"""
        # DuckDB: Persistent Database Connection

        This snippet demonstrates connecting to a persistent DuckDB database
        by specifying a database file, performing DDL/DML operations, and querying data.
        """
    )
    return


@app.cell
def _():
    # Define the persistent database file name
    db_file = "persistent_db.duckdb"
    return (db_file,)


@app.cell
def _(sp, persistent_table):
    # Using sp.sql, we create a table (if it doesn't already exist) and insert sample data.
    sp.sql("CREATE TABLE IF NOT EXISTS persistent_table (id INTEGER, value DOUBLE)")
    sp.sql("INSERT INTO persistent_table VALUES (1, 10.5), (2, 20.5)")
    result_df = sp.sql("SELECT * FROM persistent_table")
    return persistent_table, result_df


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
