# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
#     "altair",
#     "polars",
# ]
# ///
import signalpilot

__generated_with = "0.23.1"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import polars as pl
    import altair as alt

    return alt, sp, pl


@app.cell
def _(pl):
    df = pl.read_csv(
        "https://gist.githubusercontent.com/netj/8836201/raw/6f9306ad21398ea43cba4f7d537619d0e07d5ae3/iris.csv"
    )
    return (df,)


@app.cell
def _(df, sp):
    table = sp.ui.table(df, label="Iris Data in a table")
    return (table,)


@app.cell
def _(alt, df, sp):
    chart = sp.ui.altair_chart(
        alt.Chart(df)
        .mark_point()
        .encode(x="sepal.length", y="sepal.width", color="variety"),
        label="Iris Data in chart",
    )
    return (chart,)


@app.cell
def _(chart, sp, table):
    sp.carousel(
        [
            sp.md("# A Presentation on Iris Data"),
            "By the sp team",
            table,
            chart,
            sp.md("# Thank you!"),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
