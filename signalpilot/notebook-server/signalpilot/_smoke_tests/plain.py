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
    import polars as pl
    return data, sp, pl


@app.cell
def _(data, pl):
    df = pl.from_pandas(data.cars())
    df
    return (df,)


@app.cell
def _(df, sp):
    sp.ui.table(df)
    return


@app.cell
def _(df, sp):
    sp.plain(df)
    return


@app.cell
def _(df, sp):
    sp.hstack(["hstack", sp.vstack(["vstack", df])])
    return


@app.cell
def _(df, sp):
    sp.hstack(["hstack", sp.vstack(["vstack", sp.plain(df)])])
    return


if __name__ == "__main__":
    app.run()
