import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""When viewing this notebook in run mode, the hourglass loading indicator should be stickied to the top left even when scrolling down.""")
    return


@app.cell
def _(sp):
    sp.md("hello world" * 10000)
    return


@app.cell
def _():
    import time

    time.sleep(100)
    return


if __name__ == "__main__":
    app.run()
