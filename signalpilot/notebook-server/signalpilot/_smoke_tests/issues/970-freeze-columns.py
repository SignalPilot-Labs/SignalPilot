
import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _(happiness_index, sp, pd):
    df = pd.read_csv(happiness_index)
    sp.ui.table(
        df,
        freeze_columns_left=["Country name", "Ladder score"],
        freeze_columns_right=["Standard error of ladder score"]
    )
    return (df,)


@app.cell
def _(df, sp):
    sp.ui.table(df)
    return


@app.cell
def _():
    import signalpilot
    import pandas as pd
    happiness_index = 'https://raw.githubusercontent.com/MainakRepositor/Datasets/master/World%20Happiness%20Data/2020.csv'
    return happiness_index, sp, pd


if __name__ == "__main__":
    app.run()
