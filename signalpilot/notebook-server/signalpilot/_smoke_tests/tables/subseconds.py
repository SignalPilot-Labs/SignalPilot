import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import datetime

    import signalpilot
    import pandas as pd
    return datetime, sp, pd


@app.cell
def _(sp):
    sp.md(r"""## Datetime""")
    return


@app.cell
def _(datetime, pd):
    _start = datetime.datetime(2024, 11, 27, 16)
    _slice = datetime.timedelta(days=1)
    pd.DataFrame(
        data={
            "timestamp": [_start + n * _slice for n in range(5)],
        }
    )
    return


@app.cell
def _(sp):
    sp.md(r"""## Seconds""")
    return


@app.cell
def _(datetime, pd):
    _start = datetime.datetime(2024, 11, 27, 16, 17, 7)
    _slice = datetime.timedelta(seconds=1)
    pd.DataFrame(
        data={
            "timestamp": [_start + n * _slice for n in range(5)],
        }
    )
    return


@app.cell
def _(sp):
    sp.md(r"""## Milliseconds""")
    return


@app.cell
def _(datetime, pd):
    _start = datetime.datetime(2024, 11, 27, 16, 17, 7, 742951)
    _slice = datetime.timedelta(microseconds=123456)
    test_df = pd.DataFrame(
        data={
            "timestamp": [_start + n * _slice for n in range(5)],
        }
    )
    return (test_df,)


@app.cell
def _(sp, test_df):
    # Nanoseconds are still missing, because JavaScript (browsers) don't support nanoseconds.
    sp.hstack([sp.plain(test_df), test_df])
    return


@app.cell
def _(sp):
    sp.md(r"""## Nanoseconds""")
    return


@app.cell
def _(test_df):
    nano_df = test_df.copy()
    nano_df["timestamp"] = nano_df["timestamp"].astype(str)
    nano_df
    return


if __name__ == "__main__":
    app.run()
