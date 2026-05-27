# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _(sp):
    sp.md(
        """
    # Bug 852

    Explanation: The table was rendering incorrectly due to javascript number precision.
    """
    )
    return


@app.cell
def _():
    import signalpilot
    import pandas as pd
    return sp, pd


@app.cell
def _(pd):
    df = pd.DataFrame({"data": [912312851340981241284, None, "abc"]})
    df
    return (df,)


@app.cell
def _(df, sp):
    table = sp.ui.table(df)
    table
    return


if __name__ == "__main__":
    app.run()
