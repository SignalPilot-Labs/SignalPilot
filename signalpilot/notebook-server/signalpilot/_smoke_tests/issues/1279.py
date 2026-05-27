# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import altair as alt
    import polars as pl
    alt.data_transformers.enable("signalpilot_csv")

    counts = pl.DataFrame(
        {
            "category": ["A", "D", "E", "G", "M", "A1", "A2", "G1", "G2", "G3", "G4"],
            "count": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110],
        }
    )

    (
        alt.Chart(counts.to_pandas())
        .encode(
            y="count",
            x=alt.X(
                "category",
            ),
        )
        .mark_bar()
    )
    return


if __name__ == "__main__":
    app.run()
