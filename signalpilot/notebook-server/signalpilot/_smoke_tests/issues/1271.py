
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    with sp.status.spinner(remove_on_exit=False):
        pass
    return


@app.cell
def _(sp):
    counter_button = sp.ui.button(
        value=0, on_click=lambda value: value + 1, label="increment"
    )
    counter_button
    return (counter_button,)


@app.cell
def _(counter_button, sp):
    sp.vstack([
        counter_button.value,
        sp.status.spinner(remove_on_exit=False) if counter_button.value < 3 else sp.md("Done!"),
    ])
    return


if __name__ == "__main__":
    app.run()
