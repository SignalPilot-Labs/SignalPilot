import signalpilot as sp

__generated_with = "0.1.0"
app = sp.App()


@app.cell
def _():
    import os
    import sys

    return os, sys


@app.cell
def compute():
    x = 1
    y = x + 1
    return x, y


@app.cell
def _(os, sys, x, y):
    print(x, y, os.sep, sys.platform)
    return


if __name__ == "__main__":
    app.run()
