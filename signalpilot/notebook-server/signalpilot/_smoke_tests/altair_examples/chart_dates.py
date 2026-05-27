import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _():
    from datetime import date

    import altair as alt
    import polars as pl
    return alt, date, pl


@app.cell
def _(date, pl):
    df = pl.DataFrame({"x": [date(2025, 1, 1)], "y": [1.0]})
    return (df,)


@app.cell
def _(alt, df):
    chart = alt.Chart(df).mark_bar().encode(x="x:T", y="y:Q")
    chart
    return (chart,)


@app.cell
def _(chart, sp):
    sp.ui.altair_chart(chart)
    return


@app.cell
def _(alt, chart, sp):
    with alt.data_transformers.enable("signalpilot_csv"):
        sp.output.append(chart)
    return


@app.cell
def _(alt, chart, sp):
    with alt.data_transformers.enable("signalpilot_json"):
        sp.output.append(chart)
    return


if __name__ == "__main__":
    app.run()
