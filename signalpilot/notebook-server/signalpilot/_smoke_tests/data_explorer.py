# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "vega-datasets",
#     "sp",
# ]
# ///
# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="full")


@app.cell
def _():
    import signalpilot
    from vega_datasets import data
    return data, mo


@app.cell
def _(data, sp):
    options = data.list_datasets()
    dataset_dropdown = sp.ui.dropdown(options, label="Datasets", value="cars")
    dataset_dropdown
    return (dataset_dropdown,)


@app.cell
def _(data, dataset_dropdown, sp):
    sp.stop(not dataset_dropdown.value)
    selected_dataset = dataset_dropdown.value
    df = data.__call__(selected_dataset)
    return (df,)


@app.cell
def _(df, sp):
    v = sp.ui.data_explorer(df)
    v
    return (v,)


@app.cell
def _(v):
    v.value
    return


if __name__ == "__main__":
    app.run()
