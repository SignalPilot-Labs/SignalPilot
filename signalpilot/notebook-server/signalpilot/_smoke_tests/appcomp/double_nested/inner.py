
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    sp.md("# Innermost")
    return


@app.cell
def _(sp):
    x = sp.ui.number(1, 10)
    return (x,)


@app.cell
def _(x):
    x
    return


@app.cell
def _(sp):
    y = sp.ui.number(1, 10)
    return (y,)


@app.cell
def _(y):
    y
    return


@app.cell
def _(x, y):
    x.value + y.value
    return


if __name__ == "__main__":
    app.run()
