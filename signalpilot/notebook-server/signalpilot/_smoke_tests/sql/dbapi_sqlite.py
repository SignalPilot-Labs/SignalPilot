import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _():
    import sqlite3
    return (sqlite3,)


@app.cell
def _(sqlite3):
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE test (
            id INTEGER PRIMARY KEY,
            name TEXT,
            value REAL
        )
    """)
    conn.execute("""
        INSERT INTO test (name, value) VALUES
        ('a', 1.0),
        ('b', 2.0),
        ('c', 3.0)
    """)
    return (conn,)


@app.cell
def _(conn, sp):
    _df = sp.sql(
        f"""
        select * FROM test
        """,
        engine=conn
    )
    return


if __name__ == "__main__":
    app.run()
