# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.11.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md(
        r"""
        # Visualization: Heat Map in Altair

        This snippet demonstrates creating a heat map visualization using Altair's
        `rect` mark type with color encoding. Heat maps are excellent for showing
        patterns in matrix-structured data.
        """
    )
    return


@app.cell
def _():
    from vega_datasets import data
    import altair as alt
    import pandas as pd
    return alt, data, pd


@app.cell
def _(alt, data):
    def create_heatmap():

        # Load and prepare data
        source = data.seattle_weather()
        # Create heatmap
        chart = alt.Chart(source).mark_rect().encode(
            x=alt.X('date:O', timeUnit='month', title='Month'),
            y=alt.Y('date:O', timeUnit='day', title='Day'),
            color=alt.Color('temp_max:Q', title='Maximum Temperature (°C)'),
            tooltip=[
                alt.Tooltip('monthdate(date):T', title='Date'),
                alt.Tooltip('temp_max:Q', title='Max Temperature')
            ]
        ).properties(
            width=300,
            height=200,
            title='Seattle Weather Heat Map'
        ).interactive()

        return chart

    create_heatmap()
    return (create_heatmap,)


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
