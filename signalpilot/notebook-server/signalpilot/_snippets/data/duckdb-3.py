# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.11.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md(
        r"""
        # DuckDB: Advanced SQL with Aggregations & Window Functions

        This snippet demonstrates advanced SQL queries including group-by aggregations
        and window functions (e.g., cumulative sums) using DuckDB.
        """
    )
    return


@app.cell
def _():
    import polars as pl
    # Create sample DataFrame
    data = {
        'group': ['A', 'A', 'B', 'B', 'C', 'C'],
        'value': [10, 15, 20, 25, 30, 35]
    }
    df = pl.DataFrame(data)
    return data, df, pl


@app.cell
def _(df, sp):
    agg_df = sp.sql(
        f"""
        SELECT
            "group",
            CAST(AVG(value) AS FLOAT) as avg_value
        FROM df
        GROUP BY "group"
        """
    )
    return (agg_df,)


@app.cell
def _(df, sp):
    window_df = sp.sql(
        f"""
        SELECT
            *,
            CAST(SUM(value) OVER (PARTITION BY "group" ORDER BY value) AS FLOAT) as cumulative_sum
        FROM df
        """
    )
    return (window_df,)


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
