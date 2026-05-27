import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import altair as alt
    import pandas as pd

    import signalpilot

    data = pd.DataFrame({"x": range(10), "y": range(10)})

    alt.renderers.set_embed_options(actions=False)
    # altair.renderers.set_embed_options(actions=True)

    # Plain chart
    chart = alt.Chart(data).mark_line().encode(x="x", y="y")
    chart
    return chart, mo


@app.cell
def _(chart, sp):
    # Wrapped chart
    sp.ui.altair_chart(chart)
    return


if __name__ == "__main__":
    app.run()
