import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    from time import time
    return sp, time


@app.cell
def _(sp):
    d = sp.ui.dictionary(
        {
            "run_button1": sp.ui.run_button(label="run button 1"),
            "run_button2": sp.ui.run_button(label="run button 2"),
        }
    )
    return (d,)


@app.cell
def _(d):
    d
    return


@app.cell
def _(d, time):
    d.value, time()
    return


@app.cell
def _(d, time):
    _t = time()
    for name, button in d.items():
        if button.value:
            print(f"Clicked: at {_t}", name)
    for n, b in d.items():
        print(button.value, n)
    d.value
    return


@app.cell
def _(sp):
    run_button = sp.ui.run_button(label="single run button")
    run_button
    return (run_button,)


@app.cell
def _(run_button, time):
    if run_button.value:
        print("Clicked run button at time ", time())
    return


if __name__ == "__main__":
    app.run()
