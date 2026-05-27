
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    import pandas as pd
    return sp, pd


@app.cell
def _(pd):
    all_flights = pd.read_parquet(
    "https://vegafusion-datasets.s3.amazonaws.com/vega/flights_1m.parquet"
    )
    return (all_flights,)


@app.cell
def _(all_flights, sp):
    sp.ui.table(all_flights)
    return


@app.cell
def _(all_flights, sp):
    sp.ui.table(all_flights[0:10])
    return


if __name__ == "__main__":
    app.run()
