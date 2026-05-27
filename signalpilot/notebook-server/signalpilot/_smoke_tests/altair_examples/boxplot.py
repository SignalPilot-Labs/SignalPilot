import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""# Box plots""")
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""## Example 1""")
    return


@app.cell
def _():
    import altair as alt
    import polars as pl

    # Create a sample dataframe
    data = pl.DataFrame(
        {
            "category": ["A", "A", "A", "B", "B", "B", "C", "C", "C"],
            "value": [10, 20, 15, 25, 30, 5, 50, 55, 45],
        }
    )

    # Convert to Pandas DataFrame for compatibility with Altair
    data_pd = data.to_pandas()

    # Create a boxplot
    boxplot = (
        alt.Chart(data_pd).mark_boxplot().encode(x="category:O", y="value:Q")
    )

    boxplot
    return boxplot, pl


@app.cell
def _(boxplot, sp):
    sp.ui.altair_chart(boxplot)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""## Example 2""")
    return


@app.cell
def _(pl):
    import random

    df = pl.DataFrame(
        {
            "val": random.sample(range(1, 100), 50),
            "grp": random.choices(["A", "B", "C"], k=50),
        }
    )

    boxplot2 = df.plot.boxplot(y="grp", x="val", color="grp")
    boxplot2
    return (boxplot2,)


@app.cell
def _(boxplot2, sp):
    sp.ui.altair_chart(boxplot2)
    return


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
