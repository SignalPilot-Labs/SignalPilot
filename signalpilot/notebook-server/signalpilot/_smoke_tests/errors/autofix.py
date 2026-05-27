import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    x = 1
    return


@app.cell
def _():
    x = 2
    x
    return


@app.cell
def _():
    x = 3
    return


@app.cell
def _(sp):
    sp.md()
    return


@app.cell
def _(alt):
    alt.Chart()
    return


if __name__ == "__main__":
    app.run()
