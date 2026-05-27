# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
#     "pandas",
#     "polars",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import pandas as pd
    import polars as pl
    return sp, pd, pl


@app.cell
def _(pd):
    data = {
        "A": [True, True, True],
        "B": [False, False, False],
        "C": [True, True, False],
    }

    pd.DataFrame(data)
    return (data,)


@app.cell
def _(data, pl):
    pl.DataFrame(data)
    return


@app.cell
def _(data, sp):
    t = sp.ui.table(data)
    t
    return (t,)


@app.cell
def _(t):
    t.value
    return


if __name__ == "__main__":
    app.run()
