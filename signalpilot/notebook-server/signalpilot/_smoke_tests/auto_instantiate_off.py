import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    sp.md(r"""If you run this first, then this should run and the `import sp` cell should run, but nothing else""")
    return


@app.cell
def _():
    # If you run this first, then this should run, but not `y = x + 1`
    x = 2
    x
    return (x,)


@app.cell
def _(x):
    # If you run this first, then this should run and `x = 2`
    y = x + 2
    y
    return


if __name__ == "__main__":
    app.run()
