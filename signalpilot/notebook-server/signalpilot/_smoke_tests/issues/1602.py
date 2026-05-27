# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.class_definition
class Boom:
    def __getattr__(self, _):
        return ...


@app.cell
def _():
    b = Boom()
    return (b,)


@app.cell
def _(b):
    callable(b.__dataframe__)
    return


if __name__ == "__main__":
    app.run()
