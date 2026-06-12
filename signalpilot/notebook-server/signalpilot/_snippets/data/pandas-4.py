import signalpilot

__generated_with = "0.3.9"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # Pandas DataFrame: Query using variable value as a column name
        """
    )
    return


@app.cell
def __(sp):
    sp.md(
        r"""
        Evaluate a variable, to use its value as the name of a column in a query.

        E.g. Query for rows where `John` is the value in the column named `first_name`.
        """
    )
    return


@app.cell
def __():
    import pandas as pd

    df = pd.DataFrame(
        data={
            "first_name": ["Sarah", "John", "Kyle"],
            "last_name": ["Connor", "Connor", "Reese"],
        }
    )

    column_name = "first_name"
    df.query(f"`{column_name}` == 'John'")
    return column_name, df, pd


@app.cell
def __():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
