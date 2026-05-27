# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import manim_slides
    return


@app.cell
def _():
    print(1)
    return


if __name__ == "__main__":
    app.run()
