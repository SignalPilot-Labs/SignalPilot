
import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    t = sp.ui.table({"a": [1, 2, 3], "b": [4, 5, 6]})
    return (t,)


@app.cell
def _(t):
    t
    return


if __name__ == "__main__":
    app.run()
