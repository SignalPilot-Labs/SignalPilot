import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _():
    import polars as pl
    import pandas as pd
    return pd, pl


@app.cell
def _(pl):
    test_df = pl.DataFrame(
        {
            "str": ["a", "c"],
            "num": [1, 2],
            "list": [["a", "b"], ["c"]],
            "struct": [{"a": 0}, {"a": 1}],
        }
    )
    return (test_df,)


@app.cell
def _(sp, test_df):
    t1 = sp.ui.table(test_df)
    t1
    return (t1,)


@app.cell
def _(t1):
    t1.value
    return


@app.cell
def _(sp, pd, test_df):
    t2 = sp.ui.table(pd.DataFrame(test_df.to_dicts()))
    t2
    return (t2,)


@app.cell
def _(t2):
    t2.value
    return


@app.cell
def _(sp, test_df):
    sp.ui.table(test_df.to_dicts())
    return


if __name__ == "__main__":
    app.run()
