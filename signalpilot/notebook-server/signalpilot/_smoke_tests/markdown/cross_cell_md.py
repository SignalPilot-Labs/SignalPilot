import signalpilot

__generated_with = "0.19.6"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    title = sp.md("# Hello World")
    return (title,)


@app.cell
def _(sp, title):
    sp.vstack([
        title,
        sp.md("This should display above this text."),
    ])
    return


if __name__ == "__main__":
    app.run()
