import signalpilot

__generated_with = "0.3.8"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # Pandas DataFrame: Select rows by an attribute of a column value
        """
    )
    return


@app.cell
def __(sp):
    sp.md(
        r"""
        Use the Series `map()` method.
        E.g. To filter by the length of a column values:
        """
    )
    return


@app.cell
def __():
    import pandas as pd

    df = pd.DataFrame(
        {
            "first_name": ["Sarah", "John", "Kyle"],
            "last_name": ["Connor", "Connor", "Reese"],
        }
    )

    df[df["last_name"].map(len) == 5]
    return df, pd


@app.cell
def __():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
