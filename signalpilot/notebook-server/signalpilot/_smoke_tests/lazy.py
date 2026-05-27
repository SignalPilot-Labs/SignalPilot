
import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="full")


@app.cell
def _(sp):
    slider = sp.ui.slider(0, 10)
    return (slider,)


@app.cell
def _(generate_number, sp, slider, table):
    tabs = sp.ui.tabs(
        {
            "First": [slider, slider.value],
            "Second": sp.lazy(table),
            "Third": sp.lazy(generate_number, show_loading_indicator=True),
        }
    )
    tabs
    return


@app.cell
def _(generate_number, sp, slider, table):
    auto_lazy_tabs = sp.ui.tabs(
        {
            "First": [slider, slider.value],
            "Second": table,
            "Third": generate_number,
        },
        lazy=True,
    )
    auto_lazy_tabs
    return


@app.cell
def _(generate_number, sp):
    sp.accordion({"Open me": sp.lazy(generate_number, show_loading_indicator=True)})
    return


@app.cell
def _(generate_number, sp):
    sp.accordion({"Open me": generate_number}, lazy=True)
    return


@app.cell
def _(generate_number_async, sp):
    sp.accordion({"Lazy async function": sp.lazy(generate_number_async, show_loading_indicator=True)})
    return


@app.cell
def _(random):
    import asyncio
    async def generate_number_async():
        print("Loading...")
        await asyncio.sleep(1)
        print("Loaded!")
        num = random.randint(0, 100)
        return num
    return (generate_number_async,)


@app.cell
def _(random, time):
    def generate_number():
        print("Loading...")
        time.sleep(1)
        print("Loaded!")
        num = random.randint(0, 100)
        return num
    return (generate_number,)


@app.cell
def _():
    import signalpilot
    import pandas as pd
    import random
    import time
    import vega_datasets

    cars = vega_datasets.data.cars()
    table = sp.ui.table(cars)
    return sp, random, table, time


if __name__ == "__main__":
    app.run()
