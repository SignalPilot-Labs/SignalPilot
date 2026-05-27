
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    v = sp.ui.number(value=0, start=-10, stop=10)
    v
    return (v,)


@app.cell
def _(v):
    v.value
    return


if __name__ == "__main__":
    app.run()
