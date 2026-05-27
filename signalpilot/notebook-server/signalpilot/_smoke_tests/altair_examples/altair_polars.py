# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
#     "altair",
#     "polars",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import altair as alt

    import signalpilot
    return alt, mo


@app.cell
def _():
    import polars as pl

    df = pl.DataFrame(
        {"year": [2020, 2021, 2022], "population": [1000, 2000, 3000]}
    )
    df
    return (df,)


@app.cell
def _(alt, df, sp):
    chart = sp.ui.altair_chart(
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("year:N", axis=alt.Axis(title="Year")),
            y=alt.Y("sum(population):Q", axis=alt.Axis(title="Population")),
        )
    )
    chart
    return (chart,)


@app.cell
def _(chart):
    chart.value
    return


if __name__ == "__main__":
    app.run()
