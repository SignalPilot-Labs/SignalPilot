import signalpilot as sp

__generated_with = "0.1.0"
app = sp.App()


@app.cell(hide_code=True)
def _():
    a = 1
    return (a,)


@app.cell(disabled=True)
def hidden(a):
    b = a + 1
    return (b,)


@app.cell(column=1, disabled=True, hide_code=True)
def _(b):
    c = b + 1
    return


if __name__ == "__main__":
    app.run()
