
import signalpilot

__generated_with = "0.20.1"
app = sp.App()


@app.cell
def _():
    import signalpilot

    return (sp,)


@app.cell
def _():
    import time

    return (time,)


@app.cell
def _(sp, time):
    def loop_replace():
        for i in range(5):
            sp.output.replace(sp.md(f"Loading {i}/5"))
            time.sleep(.01)

    def loop_append():
        for i in range(5):
            sp.output.append(sp.md(f"Loading {i}/5"))
            time.sleep(.01)

    return loop_append, loop_replace


@app.cell
def _(sp):
    sp.md("""
    ### Replace
    """)
    return


@app.cell
def _(loop_replace, sp):
    loop_replace()
    sp.md("Done!")
    return


@app.cell
def _(loop_replace, sp):
    loop_replace()
    sp.output.replace(sp.md(f"Done"))
    return


@app.cell
def _(sp):
    sp.md("""
    ### Append
    """)
    return


@app.cell
def _(loop_append, sp):
    loop_append()
    sp.md("Done!")
    return


@app.cell
def _(loop_append, sp):
    loop_append()
    sp.output.append(sp.md("Done!"))
    return


@app.cell
def _(sp):
    sp.md("""
    ### Clear
    """)
    return


@app.cell
def _(loop_append, sp):
    loop_append()
    sp.output.append(sp.md("Done!"))
    sp.output.clear()
    return


@app.cell
def _(loop_append, sp):
    loop_append()
    sp.output.append(sp.md("Done!"))
    sp.output.replace(None)
    return


@app.cell
def _(sp):
    sp.md("""
    ### Sleep (stale)
    """)
    return


@app.cell
def _(time):
    time.sleep(2)
    "hello"
    return


@app.cell
def _(sp):
    sp.output.append(sp.md("To be replaced."))
    sp.output.replace_at_index(sp.md("Replaced at index"), 0)
    return


if __name__ == "__main__":
    app.run()
