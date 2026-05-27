# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "altair",
#     "pandas",
#     "sp",
# ]
# ///
import signalpilot

__generated_with = "0.15.5"
app = sp.App(layout_file="layouts/slides.slides.json")


@app.cell
def _(sp):
    sp.md("""# A Presentation on `Iris` Data""")
    return


@app.cell
def _(sp):
    sp.md("""## By the sp team (`@signalpilot_io`)""")
    return


@app.cell
def _():
    import signalpilot
    import pandas as pd
    import altair as alt
    return alt, sp, pd


@app.cell
def _(pd):
    df = pd.read_csv(
        "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/iris.csv"
    )
    df = pd.concat([df, df.add_suffix("_2")], axis=1)
    return (df,)


@app.cell
def _(df, sp):
    table = sp.ui.table(df, label="Wide Iris Data in a table")
    table
    return


@app.cell
def _(alt, df, sp):
    chart = sp.ui.altair_chart(
        alt.Chart(df)
        .mark_point()
        .encode(x="sepal_length", y="sepal_width", color="species"),
        label="Iris Data in chart",
    )
    chart
    return


@app.cell
def _(sp):
    sp.md("""# Thank you!""")
    return


@app.cell
def _():
    # Some markdown testing
    return


@app.cell
def _(sp):
    sp.md(
        r"""
        # H1 (`H1`)
        ## H2 (`H2`)
        ### H3 (`H3`)
        #### H4 (`H4`)
        ##### H5 (`H5`)
        ###### H6 (`H6`)
        """
    )
    return


@app.cell
def _(sp):
    sp.md(
        r"""
        - Item 1
        - `Item 2`
        - **Item 3**
        - _Item 4_
        """
    )
    return


@app.cell
def _(sp):
    sp.md(
        r"""
        !!! note "Callouts"
            This is a callout
        """
    )
    return


@app.cell
def _(sp):
    sp.callout("""
    This is another callout
    """)
    return


@app.cell
def _():
    return


@app.cell
def _(sp):
    sp.md(r"""## Items that don't quite work in slides""")
    return


@app.cell
def _(sp):
    sp.accordion({"Accodrions too small": sp.md("Content")})
    return


@app.cell
def _(sp):
    sp.ui.tabs({"Tabs to small": sp.md("Content")})
    return


if __name__ == "__main__":
    app.run()
