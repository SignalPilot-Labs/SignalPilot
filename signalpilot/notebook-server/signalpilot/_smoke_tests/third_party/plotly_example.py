# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "plotly==5.24.1",
#     "pandas==3.0.0",
#     "sp",
#     "vega-datasets==0.9.0",
# ]
# ///

import signalpilot

__generated_with = "0.19.9"
app = sp.App(width="full")


@app.cell
def _(sp):
    sp.md("""
    # Plotly Express Chart
    """)
    return


@app.cell
def _():
    import plotly.express as px

    px.scatter(x=[0, 1, 2, 3, 4], y=[0, 1, 4, 9, 16])
    return (px,)


@app.cell
def _(sp, px):
    plot = sp.ui.plotly(
        px.scatter(x=[0, 1, 2, 3, 4], y=[0, 1, 4, 9, 16], width=600)
    )
    sp.vstack(
        [
            sp.md("# Fixed width"),
            plot,
        ]
    )
    return (plot,)


@app.cell
def _(sp, plot):
    sp.vstack(
        [
            sp.hstack(
                [
                    sp.ui.table(plot.value, label="Points", selection=None),
                    sp.ui.table(
                        [
                            {"start": r[0], "end": r[1], "axis": key}
                            for key, r in plot.ranges.items()
                        ],
                        selection=None,
                        label="Ranges",
                    ),
                ],
                widths="equal",
            ),
            plot.indices,
        ]
    )
    return


@app.cell
def _(sp):
    sp.md("""
    # Plotly Graph Objects Chart
    """)
    return


@app.cell
def _(sp):
    import pandas as pd
    import plotly.graph_objects as go

    df = pd.DataFrame(
        {
            "Fruit": [
                "Apples",
                "Oranges",
                "Bananas",
                "Apples",
                "Oranges",
                "Bananas",
            ],
            "Contestant": [
                "Alex",
                "Alex",
                "Alex",
                "Jordan",
                "Jordan",
                "Jordan",
            ],
            "Number Eaten": [2, 1, 3, 1, 3, 2],
        }
    )

    fig = go.Figure()
    for contestant, group in df.groupby("Contestant"):
        fig.add_trace(
            go.Bar(
                x=group["Fruit"],
                y=group["Number Eaten"],
                name=contestant,
                hovertemplate=(
                    "Contestant=%s<br>Fruit=%%{x}<br>"
                    "Number Eaten=%%{y}<extra></extra>"
                )
                % contestant,
            )
        )
    fig.update_layout(legend_title_text="Contestant")
    fig.update_xaxes(title_text="Fruit")
    fig.update_yaxes(title_text="Number Eaten")

    plot2 = sp.ui.plotly(fig)
    plot2
    return go, pd, plot2


@app.cell
def _(sp, plot2):
    sp.ui.table(plot2.value, selection=None)
    return


@app.cell
def _(sp):
    sp.md("""
    # Re-rendering Chart
    """)
    return


@app.cell
def _():
    import vega_datasets as datasets
    import signalpilot

    cars = datasets.data.cars()
    return cars, mo


@app.cell
def _(cars, sp):
    sample_size = sp.ui.slider(label="Sample", start=100, stop=len(cars), step=100)
    sample_size
    return (sample_size,)


@app.cell
def _(cars, sp, px, sample_size):
    _fig = px.scatter(
        cars.sample(sample_size.value),
        x="Horsepower",
        y="Miles_per_Gallon",
        color="Origin",
        size="Weight_in_lbs",
        hover_data=["Name", "Origin"],
    )

    _fig
    plot3 = sp.ui.plotly(_fig)
    plot3
    return (plot3,)


@app.cell
def _(sp, plot3):
    sp.ui.table(plot3.value, selection=None)
    return


@app.cell
def _(sp):
    sp.md("""
    # 3D Chart
    """)
    return


@app.cell
def _(go, pd):
    # load dataset
    _df = pd.read_csv(
        "https://raw.githubusercontent.com/plotly/datasets/master/volcano.csv"
    )

    # create figure
    _fig = go.Figure()

    # Add surface trace
    _fig.add_trace(go.Surface(z=_df.values.tolist(), colorscale="Viridis"))

    # Update plot sizing
    _fig.update_layout(
        width=800,
        height=900,
        autosize=False,
        margin=dict(t=0, b=0, l=0, r=0),
        template="plotly_white",
    )

    # Update 3D scene options
    _fig.update_scenes(aspectratio=dict(x=1, y=1, z=0.7), aspectmode="manual")

    # Add dropdown
    _fig.update_layout(
        updatemenus=[
            dict(
                type="buttons",
                direction="left",
                buttons=list(
                    [
                        dict(
                            args=["type", "surface"],
                            label="3D Surface",
                            method="restyle",
                        ),
                        dict(
                            args=["type", "heatmap"],
                            label="Heatmap",
                            method="restyle",
                        ),
                    ]
                ),
                pad={"r": 10, "t": 10},
                showactive=True,
                x=0.11,
                xanchor="left",
                y=1.1,
                yanchor="top",
            ),
        ]
    )

    # Add annotation
    _fig.update_layout(
        annotations=[
            dict(
                text="Trace type:",
                showarrow=False,
                x=0,
                y=1.08,
                yref="paper",
                align="left",
            )
        ]
    )

    _fig
    return


@app.cell
def _(sp):
    sp.md("""
    # Heatmap Click
    """)
    return


@app.cell(hide_code=True)
def _(go, sp):
    _fig = go.Figure(
        data=go.Heatmap(
            z=[[1, 20, 30], [20, 1, 60], [30, 60, 1]],
            x=["A", "B", "C"],
            y=["X", "Y", "Z"],
            colorscale="Viridis",
        )
    )
    _fig.update_layout(title="Click on a cell", width=500, height=400)

    heatmap = sp.ui.plotly(_fig)
    heatmap
    return (heatmap,)


@app.cell
def _(heatmap, sp):
    sp.vstack(
        [
            sp.ui.table(heatmap.value, label="Points", selection=None),
            heatmap.indices,
        ]
    )
    return


if __name__ == "__main__":
    app.run()
