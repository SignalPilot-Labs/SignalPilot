# Copyright 2026 SignalPilot. All rights reserved.
import signalpilot

__generated_with = "0.3.9"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # Visualization: Bar Plot in Altair

        This shows a simple bar plot in Altair, showing the mean miles per gallon as a function of origin for a number of car models:
        """
    )
    return


@app.cell
def __():
    # load an example dataset
    from vega_datasets import data

    cars = data.cars()

    # plot the dataset, referencing dataframe column names
    import altair as alt

    alt.Chart(cars).mark_bar().encode(
        x="mean(Miles_per_Gallon)", y="Origin", color="Origin"
    )
    return alt, cars, data


@app.cell
def __():
    import signalpilot
    return sp,


if __name__ == "__main__":
    app.run()
