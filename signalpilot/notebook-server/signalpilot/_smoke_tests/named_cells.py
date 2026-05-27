
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def display_slider(sp):
    slider = sp.ui.slider(1, 10)
    sp.md(f"Here is a slider: {slider}")
    return


@app.cell
def _(sp):
    element = sp.ui.checkbox(False)
    return (element,)


@app.cell
def display_element(element, sp):
    sp.md(f"Here is an element: {element}")
    return


if __name__ == "__main__":
    app.run()
