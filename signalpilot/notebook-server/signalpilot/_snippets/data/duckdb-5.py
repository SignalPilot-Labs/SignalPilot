
import signalpilot

__generated_with = "0.11.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md(
        r"""
        # DuckDB: Join Operations & Multi-Table Queries

        This snippet demonstrates how to perform JOIN operations between
        two DataFrames using DuckDB's SQL engine within sp.
        """
    )
    return


@app.cell
def _():
    import polars as pl
    # Create two sample DataFrames to join
    df1 = pl.DataFrame({
        'id': [1, 2, 3, 4],
        'value1': ['A', 'B', 'C', 'D']
    })
    df2 = pl.DataFrame({
        'id': [3, 4, 5, 6],
        'value2': ['X', 'Y', 'Z', 'W']
    })
    return df1, df2, pl


@app.cell
def _(df1, df2, sp):
    join_df = sp.sql(
        f"""
        SELECT a.id, a.value1, b.value2
        FROM df1 a
        INNER JOIN df2 b ON a.id = b.id
        """
    )
    return (join_df,)


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
