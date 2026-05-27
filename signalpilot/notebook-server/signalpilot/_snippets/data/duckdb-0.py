# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.11.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md(
        r"""
        # DuckDB: Basic SQL Querying and DataFrame Integration

        This snippet demonstrates how to use `sp`'s SQL cells to execute
        queries against a local Pandas DataFrame. We leverage parameterized
        queries through f-string interpolation.
        """
    )
    return


@app.cell
def _():
    import polars as pl
    # Create a sample DataFrame
    data = {
        'id': list(range(1, 11)),
        'value': [x * 10 for x in range(1, 11)]
    }
    df = pl.DataFrame(data)
    return data, df, pl


@app.cell
def _():
    max_rows = 5
    return (max_rows,)


@app.cell
def _(df, max_rows, sp):
    limited_df = sp.sql(
        f"""
        SELECT * FROM df LIMIT {max_rows}
        """
    )
    return (limited_df,)


@app.cell
def _(df, max_rows, sp):
    result_df = sp.sql(
        f"""
        SELECT * FROM df WHERE value > {max_rows * 10}
        """
    )
    return (result_df,)


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
