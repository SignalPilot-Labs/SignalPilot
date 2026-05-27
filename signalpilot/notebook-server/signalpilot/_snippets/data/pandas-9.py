# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.10.12"
app = sp.App()


@app.cell
def _(sp):
    sp.md(
        r"""
        # Pandas: Describe Timestamp values in a column
        """
    )
    return


@app.cell
def _():
    import pandas as pd

    df = pd.DataFrame({'timestamp': pd.date_range('2023-01-01', periods=5, freq='D')})

    df['timestamp'].describe()
    return df, pd


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
