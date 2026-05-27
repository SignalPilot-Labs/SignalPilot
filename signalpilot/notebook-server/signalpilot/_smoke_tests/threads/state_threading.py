import signalpilot

__generated_with = "0.17.7"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import random
    return sp, random


@app.cell
def _(sp):
    g, s = sp.state(0)

    g(), s(1)
    return g, s


@app.cell
def _(g, random):
    g(), (x := random.randint(0, 10))
    return (x,)


@app.cell
def _(x):
    x
    return


@app.cell
def _(s):
    s(6)
    return


@app.cell
def _(sp):
    def f(s):
        import random
        import time

        thread = sp.current_thread()
        while not thread.should_exit:
            s(random.randint(0, 100000))
            time.sleep(1)
    return (f,)


@app.cell
def _(f, sp, s):
    sp.Thread(target=f, args=(s,)).start()
    return


@app.cell
def _(g):
    g()
    return


if __name__ == "__main__":
    app.run()
