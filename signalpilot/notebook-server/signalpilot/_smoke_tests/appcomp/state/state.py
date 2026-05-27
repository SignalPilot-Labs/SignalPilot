
import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    get_state, set_state = sp.state(False)
    return get_state, set_state


@app.cell
def _(sp, set_state):
    b = sp.ui.button(on_change=lambda x: set_state(True))
    b
    return


@app.cell
def _(get_state):
    "button was clicked" if get_state() else "button was not clicked"
    return


if __name__ == "__main__":
    app.run()
