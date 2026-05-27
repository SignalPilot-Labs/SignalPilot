# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import altair as alt

    alt.data_transformers.enable("signalpilot_csv")
    return


if __name__ == "__main__":
    app.run()
