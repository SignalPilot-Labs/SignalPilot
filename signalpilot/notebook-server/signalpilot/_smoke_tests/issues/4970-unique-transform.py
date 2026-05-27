import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="columns")


@app.cell(column=0)
def _(df_pandas, sp):
    sp.ui.dataframe(df_pandas)
    return


@app.cell
def _(df_polars, sp):
    sp.ui.dataframe(df_polars)
    return


@app.cell
def _(df_ibis, sp):
    sp.ui.dataframe(df_ibis)
    return


@app.cell
def _():
    import signalpilot
    import pandas as pd
    import polars as pl
    import ibis as ib
    from vega_datasets import data
    return data, ib, sp, pd, pl


@app.cell
def _(data, ib, pd, pl):
    iris_dataset = data.iris()
    df_pandas = pd.DataFrame(iris_dataset)
    df_polars = pl.DataFrame(iris_dataset)
    df_ibis = ib.memtable(iris_dataset)
    return df_ibis, df_pandas, df_polars


@app.cell(column=1)
def _(df_pandas):
    df_pandas_next = df_pandas
    df_pandas_next.drop_duplicates(["sepalLength"], keep="first")
    return


@app.cell
def _(df_polars):
    df_polars_next = df_polars
    df_polars_next.unique(subset=["sepalLength"], keep="first")
    return


@app.cell
def _(df_ibis, sp):
    df_ibis_next = df_ibis
    df_ibis_next = df_ibis_next.distinct(on=["sepalLength"], keep="first")
    sp.ui.table(df_ibis_next)
    return


if __name__ == "__main__":
    app.run()
