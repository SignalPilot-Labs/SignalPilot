import signalpilot

__generated_with = "0.3.8"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # Pandas: Create a TimeDelta using available kwargs
        """
    )
    return


@app.cell
def __(sp):
    sp.md(
        r"""
        Example keyworded args: {days, seconds, microseconds, milliseconds, minutes, hours, weeks}
        """
    )
    return


@app.cell
def __():
    import pandas as pd

    pd.Timedelta(days=2)
    return (pd,)


@app.cell
def __():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
