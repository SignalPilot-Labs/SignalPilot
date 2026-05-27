# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    import datetime

    start_date = sp.ui.date(
        label="Start date",
        start=datetime.date(2020, 1, 1),
        stop=datetime.date(2020, 12, 31),
    )
    end_date = sp.ui.date(
        label="End date",
        start=datetime.date(2020, 1, 1),
        stop=datetime.date(2020, 12, 31),
    )
    return datetime, end_date, start_date


@app.cell
def _(end_date, sp, start_date):
    sp.hstack(
        [
            sp.hstack([start_date, "➡️", end_date]).left(),
            sp.md(f"From {start_date.value} to {end_date.value}"),
        ]
    )
    return


@app.cell
def _(datetime, sp):
    start_datetime = sp.ui.datetime(
        label="Start datetime",
        start=datetime.datetime(2021, 1, 1),
        stop=datetime.datetime(2021, 12, 31),
    )
    end_datetime = sp.ui.datetime(
        label="End datetime",
        start=datetime.datetime(2021, 1, 1),
        stop=datetime.datetime(2021, 12, 31),
    )
    return end_datetime, start_datetime


@app.cell
def _(end_datetime, sp, start_datetime):
    sp.hstack(
        [
            sp.hstack([start_datetime, "➡️", end_datetime]).left(),
            sp.md(f"From {start_datetime.value} to {end_datetime.value}"),
        ]
    )
    return


@app.cell
def _(datetime, sp):
    date_range_input = sp.ui.date_range(
        label="Date_range",
        start=datetime.date(2021, 1, 1),
        stop=datetime.date(2021, 12, 31),
    )
    return (date_range_input,)


@app.cell
def _(date_range_input, sp):
    sp.hstack([date_range_input, date_range_input.value])
    return


@app.cell
def _(sp):
    _date = sp.ui.date(label="Input")
    _datetime = sp.ui.datetime(label="Input")
    _date_range = sp.ui.date_range(label="Input")
    return


if __name__ == "__main__":
    app.run()
