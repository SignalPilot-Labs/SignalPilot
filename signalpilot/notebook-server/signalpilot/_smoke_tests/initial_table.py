# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pandas",
#     "sp",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _():
    import pandas as pd

    sample_df = pd.DataFrame(
        {
            "Name": ["Alice", "Bob", "Charlie"],
            "Age": [25, 30, 35],
            "City": ["New York", "Los Angeles", "Chicago"],
        }
    )
    return (sample_df,)


@app.cell
def _(sp, sample_df):
    import time

    sp.output.replace(sample_df)
    time.sleep(5)
    return


if __name__ == "__main__":
    app.run()
