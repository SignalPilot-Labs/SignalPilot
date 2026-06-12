import signalpilot

__generated_with = "0.3.9"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # Pandas DataFrame: Create from lists of values
        """
    )
    return


@app.cell
def __():
    import pandas as pd

    last_names = ["Connor", "Connor", "Reese"]
    first_names = ["Sarah", "John", "Kyle"]
    df = pd.DataFrame(
        {
            "first_name": first_names,
            "last_name": last_names,
        }
    )
    df
    return df, first_names, last_names, pd


@app.cell
def __():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
