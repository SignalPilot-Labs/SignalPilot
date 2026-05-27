# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    import pandas as pd
    import polars as pl
    return sp, pd, pl


@app.cell
def _():
    list_data = [['meow1', 'meow2'], ['meow1', 'meow2', 'meow3'], ['meow'], ['a', 'b', 'c'], ['meow']]
    json_data = [
        {'acol': 'acol1', 'bcol': 'bcol1'},
        {'acol': 'acol2', 'bcol': 'bcol2'},
        {'acol': 'acol3', 'bcol': 'bcol3'},
        {'acol': 'acol4', 'bcol': 'bcol4'},
        {'acol': 'acol5', 'bcol': 'bcol5'}
    ]
    return json_data, list_data


@app.cell
def _(json_data, list_data, pd, pl):
    df = pd.DataFrame()
    df['list_data'] = list_data
    df['json_data'] = json_data
    df2 = df.copy(deep=True)
    df4 = pl.DataFrame({
        "list_data": list_data,
        "json_data": json_data
    }, strict=True)
    df
    return df, df2, df4


@app.cell
def _(sp):
    sp.md("""### Transformations performed manually with pandas:""")
    return


@app.cell
def _(df, pd):
    df3 = df.copy(deep=True)
    df3 = df.join(pd.DataFrame(df.pop('json_data').values.tolist()))
    df3.explode('list_data')
    return


@app.cell
def _(sp):
    sp.md("""### Transformations on pandas dataframe using `sp.ui.dataframe`:""")
    return


@app.cell
def _(df2, sp):
    sp.ui.dataframe(df2[['list_data', 'json_data']])
    return


@app.cell
def _(sp):
    sp.md(r"""### Transformations on polars dataframe using `sp.ui.dataframe`:""")
    return


@app.cell
def _(df4, sp):
    sp.ui.dataframe(df4[['list_data', 'json_data']])
    return


if __name__ == "__main__":
    app.run()
