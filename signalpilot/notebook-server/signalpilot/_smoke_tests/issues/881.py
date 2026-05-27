# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import pandas as pd
    import signalpilot
    df = pd.DataFrame({"data": [2.0]})
    sp.ui.table(df)
    return


if __name__ == "__main__":
    app.run()
