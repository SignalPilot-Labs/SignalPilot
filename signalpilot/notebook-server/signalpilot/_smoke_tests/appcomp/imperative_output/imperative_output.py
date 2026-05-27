
import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    sp.md("# hello")
    return


@app.cell
def _(sp, time):
    for i in sp.status.progress_bar(range(5)):
        time.sleep(0.5)
        print(i)
    return


@app.cell
def _(sp):
    import time
    sp.output.replace(sp.md("# output"))
    time.sleep(0.5)
    sp.output.replace(sp.md("# replaced"))
    return (time,)


if __name__ == "__main__":
    app.run()
