import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import sys
    import time
    return sp, sys, time


@app.cell
def _(sp, sys, time):
    for i in sp.status.progress_bar(range(10)):
        if i % 2 == 0:
            print(f"Step {i}", file=sys.stderr)
        else:
            print(f"Step {i}")
        time.sleep(1)
    return


if __name__ == "__main__":
    app.run()
