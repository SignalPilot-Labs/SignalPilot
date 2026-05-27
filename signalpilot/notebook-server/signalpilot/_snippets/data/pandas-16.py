import signalpilot

__generated_with = "0.3.8"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # Pandas: Create a TimeDelta from a string
        """
    )
    return


@app.cell
def __():
    import pandas as pd

    pd.Timedelta("2 days 2 hours 15 minutes 30 seconds")
    return (pd,)


@app.cell
def __():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
