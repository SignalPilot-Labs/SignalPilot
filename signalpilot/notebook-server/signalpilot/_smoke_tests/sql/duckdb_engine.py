import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _():
    import duckdb

    connection_one = duckdb.connect("one.db")
    connection_two = duckdb.connect("two.db")
    return connection_one, connection_two


@app.cell
def _(connection_one, sp):
    _df = sp.sql(
        f"""
        CREATE OR REPLACE TABLE numbers AS 
        SELECT * FROM range(1, 101) AS n;
        """,
        engine=connection_one
    )
    return


@app.cell
def _(connection_two, sp):
    _df = sp.sql(
        f"""
        CREATE OR REPLACE TABLE other_numbers AS 
        SELECT * FROM range(1, 101) AS n;
        """,
        engine=connection_two
    )
    return


@app.cell
def _(connection_one, sp):
    _df = sp.sql(
        f"""
        SELECT * FROM duckdb_tables();
        """,
        engine=connection_one
    )
    return


@app.cell
def _(connection_two, sp):
    _df = sp.sql(
        f"""
        SELECT * FROM duckdb_tables();
        """,
        engine=connection_two
    )
    return


if __name__ == "__main__":
    app.run()
