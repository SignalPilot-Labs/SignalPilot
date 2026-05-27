# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.11.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md(
        r"""
        # DuckDB: Parameterized & Reactive SQL Queries

        This snippet shows how to parameterize SQL queries with Python variables
        in sp, allowing queries to dynamically reflect changes in Python values.
        """
    )
    return


@app.cell
def _():
    import polars as pl
    # Create a sample DataFrame for reactive filtering
    data = {'id': list(range(1, 21)), 'score': [x * 5 for x in range(1, 21)]}
    df = pl.DataFrame(data)
    return data, df, pl


@app.cell
def _(sp):
    min_score = sp.ui.number(label="Minimum Score", value=50, start=0)
    return (min_score,)


@app.cell
def _(min_score):
    min_score
    return


@app.cell
def _(df, min_score, sp):
    result = sp.sql(
        f"""
        SELECT * FROM df WHERE score >= {min_score.value}
        """
    )
    return (result,)


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
