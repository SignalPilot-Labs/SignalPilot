import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import plotly.express as px

    df = px.data.tips()
    sp.md("# Plotly Selection")
    return df, sp, px


@app.cell
def _(df):
    df
    return


@app.cell
def _(df, sp, px):
    _fig = px.treemap(df, path=[px.Constant("all"), 'day', 'time', 'sex'], values='total_bill')
    plot = sp.ui.plotly(_fig)
    return (plot,)


@app.cell
def _(sp, plot):
    sp.vstack([plot], align="stretch")
    return


@app.cell
def _(plot):
    plot.value
    return


@app.cell
def _(sp, px):
    _data = dict(
        character=["Eve", "Cain", "Seth", "Enos", "Noam", "Abel", "Awan", "Enoch", "Azura"],
        parent=["", "Eve", "Eve", "Seth", "Seth", "Eve", "Eve", "Awan", "Eve" ],
        value=[10, 14, 12, 10, 2, 6, 6, 4, 4])

    sunburst = sp.ui.plotly(px.sunburst(
        _data,
        names='character',
        parents='parent',
        values='value',
    ))

    sunburst
    return (sunburst,)


@app.cell
def _(sunburst):
    sunburst.value
    return


if __name__ == "__main__":
    app.run()
