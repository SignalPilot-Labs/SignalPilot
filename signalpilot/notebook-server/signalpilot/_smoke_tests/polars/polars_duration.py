import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import polars as pl
    return sp, pl


@app.cell
def _(sp):
    sp.md(r"""## Polars""")
    return


@app.cell
def _(pl):
    df = pl.read_csv(
        "https://raw.githubusercontent.com/vega/vega-datasets/refs/heads/main/data/co2-concentration.csv"
    )
    df = df.with_columns(
        pl.col("CO2").cast(pl.Duration),
    )
    df
    return (df,)


@app.cell
def _(df, sp):
    sp.plain(df)
    return


@app.cell
def _(sp):
    sp.md(r"""## Pandas""")
    return


@app.cell
def _(df):
    df.to_pandas()
    return


@app.cell
def _(df, sp):
    sp.plain(df.to_pandas())
    return


if __name__ == "__main__":
    app.run()
