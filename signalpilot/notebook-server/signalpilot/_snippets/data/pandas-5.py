import signalpilot

__generated_with = "0.3.8"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # Pandas DataFrame: Query by Timestamp above a value
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

    df.query('time >= "2022-09-14 00:52:30-07:00"')
    return df, pd


@app.cell
def __():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
