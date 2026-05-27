import signalpilot

__generated_with = "0.17.0"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _():
    import altair as alt
    from vega_datasets import data

    source = data.barley()
    chart = (
        alt.Chart(source)
        .mark_bar()
        .encode(
            x="year:O",
            y="sum(yield):Q",
            color="year:N",
            column="site:N",
        )
    )
    chart
    return (chart,)


@app.cell
def _(chart, sp):
    sp.ui.altair_chart(chart)
    return


@app.cell
def _(chart):
    chart.encoding.column
    return


@app.cell
def _(chart):
    type(chart).mro()
    return


if __name__ == "__main__":
    app.run()
