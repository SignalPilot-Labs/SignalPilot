# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "altair==5.5.0",
#     "matplotlib==3.10.6",
#     "pandas==2.3.2",
#     "polars==1.33.1",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import pandas as pd
    import polars as pl
    import matplotlib.pyplot as plt
    import altair

    import signalpilot
    return sp, pd, pl


@app.cell
def _(sp, pd, pl):
    data = {
        "x": [1, 2, 3],
        "y": [float("-inf"), float("nan"), float("inf")],
        "z": [b"a", b"a", b"a"],
        "zz": [sp.ui.button(), sp.ui.button(), sp.ui.button()],
    }
    pandas_df = pd.DataFrame(data)
    polars_df = pl.DataFrame(data)
    sp.vstack([sp.ui.table(data), polars_df, pandas_df], heights=[20, 50, 50])
    return pandas_df, polars_df


@app.cell
def _(sp, pandas_df, polars_df):
    md = sp.md("### Invalid JSON values should be sanitized for charting")
    sp.vstack(
        [md, polars_df.plot.line(x="x", y="y"), pandas_df.plot.line(x="x", y="y")],
        heights=[20, 50, 50],
    )
    return


if __name__ == "__main__":
    app.run()
