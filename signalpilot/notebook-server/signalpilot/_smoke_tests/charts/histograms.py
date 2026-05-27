import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="full")


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""This is some experimental work to see if we can pre-aggregate column charts on the backend for performance. We are trying to use the dataframe of choice, to avoid additional dependencies.""")
    return


@app.cell(hide_code=True)
def _(pl):
    df = pl.read_csv("hf://datasets/scikit-learn/Fish/Fish.csv")
    df
    return (df,)


@app.cell(hide_code=True)
def _(alt, charts, sp):
    _charts = []
    for _col, data in charts.items():
        chart = sp.ui.altair_chart(
            alt.Chart(alt.Data(values=data))
            .mark_bar()
            .encode(
                x=alt.X("breakpoint:Q", bin=alt.Bin(maxbins=10), title=f"{_col}"),
                y="count:Q",
            )
            .properties(title=f"Histogram of {_col}"),
            chart_selection=None,
            legend_selection=None,
        )
        _charts.append(chart)
    sp.hstack(_charts)
    return


@app.cell
def _(df, pl):
    charts = {}
    for col in df.columns:
        if df[col].dtype in [pl.datatypes.Float64, pl.datatypes.Int64]:
            hist_data = df[col].hist().to_dicts()
            charts[col] = hist_data

    charts.keys()
    return (charts,)


@app.cell
def _(df):
    res = df["Weight"].hist().to_dicts()
    res[0]
    return


@app.cell
def _():
    import signalpilot
    import polars as pl
    import altair as alt
    return alt, sp, pl


if __name__ == "__main__":
    app.run()
