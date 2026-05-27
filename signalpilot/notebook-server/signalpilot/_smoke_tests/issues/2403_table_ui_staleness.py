import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="full")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _():
    keys_1 = [f"123_{x}" for x in range(20)]
    keys_2 = [f"abc_{x}" for x in range(20)]
    return keys_1, keys_2


@app.cell
def _(sp):
    # Toggling this switch should change the keys in the tables and the initial value in the text inputs
    switch = sp.ui.switch()
    switch
    return (switch,)


@app.cell
def button(keys_1, keys_2, switch):
    keys = keys_1 if switch.value else keys_2
    return (keys,)


@app.cell
def display(keys, sp):
    table = sp.ui.table({str(k): sp.ui.text(value=k) for k in keys})
    table
    return


if __name__ == "__main__":
    app.run()
