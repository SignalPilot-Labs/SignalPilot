import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    data = [{"x": 1, "y": "a", "c": sp.ui.button(label="hello")}, {"x": 2, "y": "b", "c": sp.ui.button(label="world")}]
    return (data,)


@app.cell
def _(data, sp):
    sp.ui.table(data)
    return


if __name__ == "__main__":
    app.run()
