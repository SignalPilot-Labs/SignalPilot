
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.function
def error(v):
    raise ValueError(str(v))


@app.cell
def _(sp):
    s = sp.ui.slider(1, 10, on_change=lambda v: error(v))
    s
    return


if __name__ == "__main__":
    app.run()
