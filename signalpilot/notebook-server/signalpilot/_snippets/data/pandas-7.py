# Copyright 2026 SignalPilot. All rights reserved.
import signalpilot

__generated_with = "0.3.8"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # Pandas DataFrame: Filter by Timestamp in DatetimeIndex using `.loc[]`
        """
    )
    return


@app.cell
def __():
    import pandas as pd

    df = pd.DataFrame(
        {
            "time": [
                "2022-09-14 00:52:00-07:00",
                "2022-09-14 00:52:30-07:00",
                "2022-09-14 01:52:30-07:00",
            ],
            "letter": ["A", "B", "C"],
        }
    )
    df["time"] = pd.to_datetime(df.time)
    df.set_index("time", inplace=True)

    df.loc["2022-09-14":"2022-09-14 00:53"]
    return df, pd


@app.cell
def __():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
