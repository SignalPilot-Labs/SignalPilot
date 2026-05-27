# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    import polars as pl

    pl.DataFrame(data=[{'num': [1], 'x': [2]}]).group_by('num').map_groups(lambda x: pl.DataFrame(data=123))
    return


if __name__ == "__main__":
    app.run()
