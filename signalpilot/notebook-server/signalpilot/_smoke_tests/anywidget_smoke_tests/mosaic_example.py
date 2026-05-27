# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pandas",
#     "mosaic-widget",
#     "sp",
#     "pyyaml",
#     "quak==0.3.2",
#     "polars==1.33.1",
# ]
# ///
# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.19.7"
app = sp.App(width="medium")


@app.cell
def _():
    import pandas as pd
    import signalpilot
    import os
    import yaml

    dir_path = os.path.dirname(os.path.realpath(__file__))


    from mosaic_widget import MosaicWidget

    weather = pd.read_csv(
        "https://uwdata.github.io/mosaic-datasets/data/seattle-weather.csv",
        parse_dates=["date"],
    )

    # Load weather spec, remove data key to ensure load from Pandas
    with open(dir_path + "/weather.yaml") as f:
        spec = yaml.safe_load(f)
        spec.pop("data")

    w = sp.ui.anywidget(MosaicWidget(spec, data={"weather": weather}))
    return sp, w


@app.cell
def _(w):
    w
    return


@app.cell
def _():
    # w.value
    return


@app.cell
def _():
    import quak
    return (quak,)


@app.cell
def _(sp, quak):
    import polars as pl

    _df = pl.read_parquet(
        "https://github.com/uwdata/mosaic/raw/main/data/athletes.parquet"
    )
    q = sp.ui.anywidget(quak.Widget(_df))
    q
    return (q,)


@app.cell
def _():
    thing = {"a": 0}
    return (thing,)


@app.cell
def _(q, thing):
    # Check gets update only once
    thing["a"] += 1
    print(thing["a"])

    q.data()
    return


if __name__ == "__main__":
    app.run()
