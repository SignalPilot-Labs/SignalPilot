# Copyright 2026 SignalPilot. All rights reserved.
import signalpilot

__generated_with = "0.3.8"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # Pandas Timestamp: Convert string to Timestamp, using date only
        """
    )
    return


@app.cell
def __(sp):
    sp.md(
        r"""
        I.e. Midnight on the given date.
        """
    )
    return


@app.cell
def __():
    import pandas as pd

    pd.Timestamp("9/27/22").tz_localize("US/Pacific")
    return (pd,)


@app.cell
def __():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
