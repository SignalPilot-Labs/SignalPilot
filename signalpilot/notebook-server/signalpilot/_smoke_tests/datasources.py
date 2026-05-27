# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pandas",
#     "vega-datasets",
#     "sp",
#     "polars",
#     "pyarrow",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="full")


@app.cell
def _():
    import signalpilot
    from vega_datasets import data
    import pandas as pd
    return data, sp, pd


@app.cell
def _(pd):
    editable_table = pd.DataFrame({"a": [2, 2, 12], "b": [2, 5, 6]})
    return


@app.cell
def _(pd):
    df_with_list = pd.DataFrame([{"a": [1, 2, 3]}])
    return


@app.cell
def _(data, sp):
    options = data.list_datasets()
    dropdown = sp.ui.dropdown(options)
    dropdown
    return (dropdown,)


@app.cell
def _(data, dropdown, sp):
    sp.stop(not dropdown.value)
    df = data.__call__(dropdown.value)
    return (df,)


@app.cell
def _(df):
    import polars as pl

    polars_df = pl.DataFrame(df)
    return (polars_df,)


@app.cell
def _(df):
    import pyarrow as pa

    pyarrow_df = pa.Table.from_pandas(df)
    return (pyarrow_df,)


@app.cell
def _(sp, polars_df):
    sp.ui.table(polars_df)
    return


@app.cell
def _(sp, pyarrow_df):
    sp.ui.table(pyarrow_df)
    return


@app.cell
def _(df, sp):
    sp.ui.table(df)
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT * FROM polars_df
        """
    )
    return


@app.cell
def _(sp):
    sp.ui.table({"a": [2, 2, 12], "b": [2, 5, 6]})
    return


@app.cell
def _(sp, polars_df):
    sp.plain(polars_df)
    return


@app.cell
def _(pd):
    date_range = pd.date_range(start="2023-01-01", periods=10, freq="D")
    date_indexed_df = pd.DataFrame({"Data": range(10)}, index=date_range)
    date_indexed_df
    return


if __name__ == "__main__":
    app.run()
