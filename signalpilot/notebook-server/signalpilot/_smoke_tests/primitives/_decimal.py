import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(alt, df):
    _chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("CAST(10 AS DECIMAL(18,3))", type="quantitative", bin=True),
            y=alt.Y("count()", type="quantitative"),
        )
        .properties(width="container")
    )
    _chart
    return


@app.cell
def _():
    import altair as alt
    return (alt,)


@app.cell
def _(sp):
    df = sp.sql(
        f"""
        SELECT
            10::numeric
        """
    )
    return (df,)


if __name__ == "__main__":
    app.run()
