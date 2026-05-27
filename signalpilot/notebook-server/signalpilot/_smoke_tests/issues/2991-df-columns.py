# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "sp",
#     "numpy==2.1.3",
#     "pandas==2.2.3",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import pandas as pd
    import signalpilot
    import numpy as np
    return sp, np, pd


@app.cell
def _(sp):
    sp.md(r"""## Lots of columns""")
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""Set cols to 10000 to crash the frontend. Number of rows appears to have no effect.""")
    return


@app.cell
def _(sp):
    rows = sp.ui.number(start=1, value=10, label="rows")
    columns = sp.ui.number(start=1, value=50, label="cols")

    sp.hstack([rows, columns], justify="start")
    return columns, rows


@app.cell
def _(columns, np, rows):
    data = np.zeros((rows.value, columns.value))
    return (data,)


@app.cell
def _(data, pd):
    df = pd.DataFrame(data, columns=[str(i) for i in range(1, data.shape[1] + 1)])
    return (df,)


@app.cell
def _(df):
    df
    return


@app.cell
def _(sp):
    sp.md(
        r"""
        ## 20k rows, 40 columns 

        This is the default max to show column summaries
        """
    )
    return


@app.cell
def _(np, pd):
    _data = np.random.rand(20000, 40)
    column_names = [f"col{i}" for i in range(40)]
    large_df = pd.DataFrame(
        {col: _data[:, i] for i, col in enumerate(column_names)}
    )
    large_df
    return


@app.cell
def _():
    # sp.ui.table(df, max_columns=None)
    return


if __name__ == "__main__":
    app.run()
