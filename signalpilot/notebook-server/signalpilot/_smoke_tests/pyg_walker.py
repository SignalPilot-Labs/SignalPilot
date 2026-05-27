# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pandas",
#     "pygwalker",
#     "sp",
# ]
# ///
import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import pandas as pd
    import pygwalker as pyg

    import signalpilot
    return sp, pd, pyg


@app.cell
def _(pd):
    df = pd.read_csv(
        "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv"
    )
    return (df,)


@app.cell
def _(df, sp, pyg):
    walker = pyg.walk(df, kernel_computation=True)
    sp.Html(walker.to_html())
    return


if __name__ == "__main__":
    app.run()
