# Copyright 2026 SignalPilot. All rights reserved.
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
#     "polars==1.5.0",
#     "quak==0.1.8",
#     "vega-datasets==0.9.0",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import polars as pl
    import quak
    from vega_datasets import data
    return data, sp, quak


@app.cell
def _(data):
    df = data.cars()
    return (df,)


@app.cell
def _(df, sp, quak):
    qwidget = quak.Widget(df)
    w = sp.ui.anywidget(qwidget)
    w
    return


@app.cell
def _():
    # w.value
    return


if __name__ == "__main__":
    app.run()
