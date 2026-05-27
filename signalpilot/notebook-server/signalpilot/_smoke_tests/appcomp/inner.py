
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
def _():
    x_initial_value = 1
    return (x_initial_value,)

@app.cell
def _(sp, x_initial_value):
    x = sp.ui.number(x_initial_value, 10)
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
