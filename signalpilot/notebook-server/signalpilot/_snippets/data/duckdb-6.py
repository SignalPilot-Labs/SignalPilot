
import signalpilot

__generated_with = "0.11.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md(
        r"""
        # DuckDB: Transaction & Error Handling in DML Operations

        This snippet demonstrates transaction management in DuckDB
        using SQLAlchemy. A transaction is used for multiple DML operations,
        and errors are caught and reported. The final result is printed in a
        separate cell.
        """
    )
    return


@app.cell
def _():
    from sqlalchemy import create_engine
    # Create an in-memory DuckDB engine using SQLAlchemy
    engine = create_engine("duckdb:///:memory:")
    return create_engine, engine


@app.cell
def _(engine, sp):
    try:
        # Begin a transaction and execute DML operations
        with engine.begin() as conn:
            conn.execute("CREATE OR REPLACE TABLE transaction_table (id INTEGER, name VARCHAR)")
            conn.execute("INSERT INTO transaction_table VALUES (1, 'Alice'), (2, 'Bob')")
            conn.execute("UPDATE transaction_table SET name = 'Charlie' WHERE id = 2")
            result = conn.execute("SELECT * FROM transaction_table").fetchall()
        print("Transaction successful; changes committed.")
    except Exception as e:
        sp.md(f"Transaction error: {e}")
        result = []
    return conn, result


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
