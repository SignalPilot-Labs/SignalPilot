# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import polars as pl
    import numpy as np

    df = pl.DataFrame(
        {"a": [np.zeros(5) for i in range(5)]}, schema={"a": pl.Array(pl.Float64, 5)}
    )
    df
    return df, mo


@app.cell
def _(df, sp):
    sp.plain(df)
    return


@app.cell
def _(df):
    df.get_columns()[0].dtype
    return


if __name__ == "__main__":
    app.run()
