# Copyright 2026 SignalPilot. All rights reserved.
import signalpilot

__generated_with = "0.3.8"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # Pandas DataFrame: Drop duplicate rows
        """
    )
    return


@app.cell
def __():
    import pandas as pd

    df = pd.DataFrame(
        {
            "first_name": ["Sarah", "John", "Kyle", "Joe"],
            "last_name": ["Connor", "Connor", "Reese", "Bonnot"],
        }
    )
    df.set_index("last_name", inplace=True)

    df.loc[~df.index.duplicated(), :]
    return df, pd


@app.cell
def __():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
