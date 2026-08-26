import signalpilot

__generated_with = "0.3.9"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # Pandas DataFrame: Query by variable value
        """
    )
    return


@app.cell
def __(sp):
    sp.md(
        r"""
        Evaluate a variable as the value to find.
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

    foo = "Connor"
    df.query("last_name == @foo")
    return df, foo, pd


@app.cell
def __():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
