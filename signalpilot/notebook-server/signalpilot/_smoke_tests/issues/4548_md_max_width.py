import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot

    md = sp.md(
        "> long text goes here long text goes here long text goes here long text goes here long text goes here long text goes here long text goes here long text goes here long text goes here long text goes here long text goes here long text goes here long text goes here long text goes here"
    )
    md
    return md, mo


@app.cell
def _():
    import polars as pl

    pl.DataFrame({"A": [1, 2, 3]})
    return


@app.cell
def _(md, sp):
    sp.vstack([md])
    return


@app.cell
def _(md, sp):
    sp.vstack([sp.hstack([md])])
    return


if __name__ == "__main__":
    app.run()
