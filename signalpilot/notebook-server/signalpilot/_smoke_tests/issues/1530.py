# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    import pandas as pd
    return sp, pd


@app.cell
def _(pd):
    df = pd.DataFrame(
        {
            "col$special": [1, 2, 3],
            "col@char": [4, 5, 6],
            'col"quote"': [7, 8, 9],
            "col'singlequote'": [10, 11, 12],
            "col<angles>": [13, 14, 15],
            "col{brace}": [16, 17, 18],
            "col[brackets]": [16, 17, 18],
            "col&and": [19, 20, 21],
            "col.period": [19, 20, 21],
            "col\\backslash": [19, 20, 21],
            "col\\backslash.period": [19, 20, 21],
        }
    )
    df
    return (df,)


@app.cell
def _(df, sp):
    sp.ui.table(df)
    return


@app.cell
def _(df, sp):
    sp.ui.dataframe(df)
    return


@app.cell
def _(df, sp):
    sp.ui.data_explorer(df)
    return


@app.cell
def _():
    import altair as alt
    return


if __name__ == "__main__":
    app.run()
