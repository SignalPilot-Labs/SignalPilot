import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.function
def foo():
    print("hi")


@app.cell
def _():
    import threading
    return (threading,)


@app.cell
def _(sp, threading):
    with sp.redirect_stdout():
        threading.Thread(target=foo).start()
    return


@app.cell
def _(sp):
    with sp.redirect_stdout():
        sp.Thread(target=foo).start()
    return


if __name__ == "__main__":
    app.run()
