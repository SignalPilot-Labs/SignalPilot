import signalpilot

__generated_with = "0.18.2"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import polars as pl
    import pandas as pd
    import numpy as np
    return sp, np, pd, pl


@app.cell
def _(sp, np, pl):
    polars_df = pl.DataFrame({"nans": [1.0, np.nan, np.inf, -np.inf, None]})
    sp.vstack([sp.plain(polars_df), polars_df])
    return


@app.cell
def _(np, pd, pl):
    pl.DataFrame(
        {"nans_not_strict": [1.0, np.nan, np.inf, -np.inf, None, pd.NA, pd.NaT]},
        strict=False,
    )
    return


@app.cell
def _(sp, np, pd):
    pandas_df_obj = pd.DataFrame(
        {"nans": [1, None, pd.NaT, np.nan, pd.NA, np.inf, -np.inf]}
    )
    sp.vstack([sp.plain(pandas_df_obj), pandas_df_obj])
    return


@app.cell
def _(pd):
    # Filtering NaNs work for float types
    pandas_nan_float = pd.DataFrame({"nans": [1, 2, 3, 4, float("nan")]})
    pandas_nan_float
    return


if __name__ == "__main__":
    app.run()
