import signalpilot

__generated_with = "0.3.8"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # Pandas: Create a TimeDelta using `unit`
        """
    )
    return


@app.cell
def __(sp):
    sp.md(
        r"""
        From an integer.
        `unit` is a string, defaulting to `ns`. Possible values:

        """
    )
    return


@app.cell
def __():
    import pandas as pd

    pd.to_timedelta(1, unit="h")
    return (pd,)


@app.cell
def __():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
