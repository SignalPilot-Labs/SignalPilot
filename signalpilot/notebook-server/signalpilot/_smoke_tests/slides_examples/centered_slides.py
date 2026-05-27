import signalpilot

__generated_with = "0.16.0"
app = sp.App(
    width="medium",
    layout_file="layouts/centered_slides.slides.json",
)


@app.cell
def _():
    import signalpilot

    sp.iframe("https://docs.signalpilot.ai/docs/")
    return (sp,)


@app.cell
def _(sp):
    sp.iframe("https://docs.signalpilot.ai/docs/", height="600px")
    return


@app.cell
def _(sp):
    sp.hstack(
        [sp.iframe("https://docs.signalpilot.ai/docs/"), sp.iframe("https://docs.signalpilot.ai/docs/")],
        widths="equal",
    )
    return


@app.cell
def _(sp):
    sp.vstack([sp.iframe("https://docs.signalpilot.ai/docs/"), sp.iframe("https://docs.signalpilot.ai/docs/")])
    return


@app.cell
def _():
    import altair as alt
    import polars as pl

    df = pl.read_parquet(
        "https://github.com/uwdata/mosaic/raw/main/data/athletes.parquet"
    )
    df

    df.plot.bar("sport", "count()", color="sex").properties(height=400)
    return


@app.cell
def _(sp):
    import plotly.express as px

    _df = px.data.gapminder().query("country=='Germany'")
    fig = px.line(_df, x="year", y="lifeExp", title="Life expectancy in Germany")

    sp.ui.plotly(fig)
    return (fig,)


@app.cell
def _(fig, sp):
    sp.vstack([sp.md("## Chart with a title"), sp.ui.plotly(fig)])
    return


if __name__ == "__main__":
    app.run()
