# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import pandas as pd

    data = {"col3": range(3), "col1": [0, 1, 2], "col2": [6, 5, 4]}

    df = pd.DataFrame(data)
    df_with_index = pd.DataFrame(data, index=[0, 1, 2])
    df_with_named_index = pd.DataFrame(data)
    df_with_named_index.index.names = ["idx"]
    return df, df_with_index, df_with_named_index, sp, pd


@app.cell
def _(pd):
    _data = pd.DataFrame(
        {
            "Animal": ["Falcon", "Falcon", "Parrot", "Parrot"],
            "Max Speed": [380.0, 370.0, 24.0, 26.0],
        }
    )
    agg_df = _data.groupby(["Animal"]).mean()
    return (agg_df,)


@app.cell
def _(df, df_with_index, df_with_named_index):
    [
        df.index,
        df_with_index.index,
        df_with_named_index.index,
    ]
    return


@app.cell
def _(agg_df, sp):
    sp.ui.table(agg_df)
    return


@app.cell
def _(df, sp):
    sp.ui.table(df)
    return


@app.cell
def _(df_with_index, sp):
    sp.ui.table(df_with_index)
    return


@app.cell
def _(df_with_named_index, sp):
    sp.ui.table(df_with_named_index)
    return


if __name__ == "__main__":
    app.run()
