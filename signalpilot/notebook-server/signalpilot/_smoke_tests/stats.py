# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.18.2"
app = sp.App()


@app.cell
def _():
    import signalpilot
    import polars as pl
    import altair as alt
    return alt, sp, pl


@app.cell
def _(sp):
    _stats = [
        sp.stat("$100", label="Revenue", caption="+ 10%", direction="increase"),
        sp.stat(
            "$20",
            label="Marketing spend",
            caption="+ 10%",
            direction="increase",
            target_direction="decrease",
        ),
        sp.stat("$80", label="Profit", caption="- 10%", direction="decrease"),
        sp.stat(
            "2%",
            label="Churn",
            caption="- 2%",
            direction="decrease",
            target_direction="decrease",
        ),
    ]
    sp.hstack(_stats)
    return


@app.cell
def _(sp):
    _stats = [
        sp.stat(
            "$100",
            label="Revenue",
            caption="+ 10%",
            direction="increase",
            bordered=True,
        ),
        sp.stat(
            "$20",
            label="Marketing spend",
            caption="+ 10%",
            direction="increase",
            bordered=True,
            target_direction="decrease",
        ),
        sp.stat(
            "$80",
            label="Profit",
            caption="- 10%",
            direction="decrease",
            bordered=True,
        ),
        sp.stat(
            "2%",
            label="Churn",
            caption="- 2%",
            direction="decrease",
            bordered=True,
            target_direction="decrease",
        ),
    ]
    sp.hstack(_stats, widths="equal", gap=1)
    return


@app.cell(hide_code=True)
def _(alt, sp, pl):
    findata = pl.DataFrame(
        {
            "revenue": [30, 20, 70, 45, 68, 34, 87, 100],
            "dates": [
                "01/01/2024",
                "01/03/2024",
                "01/06/2024",
                "01/09/2024",
                "01/12/2024",
                "01/15/2024",
                "01/18/2024",
                "01/21/2024",
            ],
        }
    )

    alt.renderers.set_embed_options(actions=False)


    def create_chart(mark: str) -> alt.Chart:
        chart = alt.Chart(findata)
        if mark == "line":
            chart = chart.mark_line(interpolate="monotone")
        else:
            chart = chart.mark_bar()
        chart = (
            chart.encode(
                x=alt.X("dates", axis=None),
                y=alt.Y("revenue", axis=None),
                tooltip=["dates", "revenue"],
            )
            .properties(height=40, width=60, background="transparent")
            .configure_view(strokeWidth=0)
        )
        return chart


    hello_world = sp.Html("<h2><i>Hello, World</i></h2>")

    _stats = [
        sp.stat(
            "$100",
            label="Revenue",
            caption="+ 10%",
            direction="increase",
            bordered=True,
            slot=create_chart("line"),
        ),
        sp.stat(
            "$20",
            label="Marketing spend",
            caption="+ 10%",
            direction="increase",
            target_direction="decrease",
            slot=create_chart("bar"),
        ),
        sp.stat(
            "$80",
            label="Profit",
            caption="- 10%",
            direction="decrease",
            bordered=True,
            slot="🚀🧑‍🚀💰",
        ),
    ]

    _rich = [
        sp.stat(
            "$20",
            label="Marketing spend",
            caption="+ 10%",
            direction="increase",
            target_direction="decrease",
            slot=hello_world,
        ),
        sp.stat(
            "2%",
            label="Churn",
            caption="- 2%",
            direction="decrease",
            bordered=True,
            target_direction="decrease",
            slot=_stats[0],
        ),
    ]


    _first = sp.hstack(_stats, widths="equal", gap=1)
    _second = sp.hstack(_rich, widths="equal", gap=1)

    sp.vstack([_first, _second])
    return


if __name__ == "__main__":
    app.run()
