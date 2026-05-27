
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _(pd):
    df = pd.DataFrame({"a": [1, 2, 3], "b": [1, 2, 3], "c": [1, 2, 3]})
    renamed = df.rename({"b": "a"}, axis=1)
    renamed
    return (renamed,)


@app.cell
def _(sp, renamed):
    sp.ui.table(renamed)
    return


@app.cell
def _():
    import signalpilot
    import pandas as pd
    return sp, pd


if __name__ == "__main__":
    app.run()
