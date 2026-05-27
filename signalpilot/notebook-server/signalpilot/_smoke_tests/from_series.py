# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "vega-datasets",
#     "sp",
#     "polars",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    from vega_datasets import data
    return data, mo


@app.cell
def _(data):
    import polars as pl
    polars_df = pl.from_pandas(data.cars())
    return (polars_df,)


@app.cell
def _(sp, polars_df):
    sp.ui.slider.from_series(polars_df["Cylinders"])
    return


@app.cell
def _(sp, polars_df):
    sp.ui.number.from_series(polars_df["Cylinders"])
    return


@app.cell
def _(sp, polars_df):
    sp.ui.radio.from_series(polars_df["Origin"])
    return


@app.cell
def _(sp, polars_df):
    sp.ui.dropdown.from_series(polars_df["Origin"])
    return


@app.cell
def _(sp, polars_df):
    sp.ui.multiselect.from_series(polars_df["Origin"])
    return


@app.cell
def _(sp, polars_df):
    sp.ui.date.from_series(polars_df["Year"])
    return


@app.cell
def _(data, sp):
    pandas_df = data.cars()
    [
        sp.ui.slider.from_series(pandas_df["Cylinders"]),
        sp.ui.number.from_series(pandas_df["Cylinders"]),
        sp.ui.radio.from_series(pandas_df["Origin"]),
        sp.ui.dropdown.from_series(pandas_df["Origin"]),
        sp.ui.multiselect.from_series(pandas_df["Origin"]),
        sp.ui.date.from_series(pandas_df["Year"])
    ]
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
