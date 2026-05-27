# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "sp",
#     "numpy",
#     "pandas",
# ]
# ///

import signalpilot

__generated_with = "0.17.6"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import pandas as pd
    import numpy as np

    # This shouldn't print a runtime warning
    df = pd.DataFrame({"a": [1, 2, 3], "b": [np.nan, np.nan, np.nan]})
    df
    return sp, np, pd


@app.cell
def _(sp, np, pd):
    i = np.random.randint(10000)
    size = 12
    # Prints a runtime warning, but still displays correctly
    nan_df = pd.DataFrame({"id": [i] * size, "all_nan_col": [np.nan] * size})
    sp.ui.table(nan_df)
    return


if __name__ == "__main__":
    app.run()
