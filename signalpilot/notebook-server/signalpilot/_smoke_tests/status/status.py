# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///
# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    import time
    return sp, time


@app.cell
def _(sp):
    sleep_time_radio = sp.ui.radio(
        [".01", ".1", "1"], label="Sleep time", value=".01"
    )
    sleep_time_radio
    return (sleep_time_radio,)


@app.cell
def _(sleep_time_radio):
    sleep_time = float(sleep_time_radio.value)
    return (sleep_time,)


@app.cell
def _(sp):
    disabled_switch = sp.ui.switch(label="Disable progress bar")
    disabled_switch
    return (disabled_switch,)


@app.cell
def _(disabled_switch, sp, sleep_time, time):
    for _ in sp.status.progress_bar(
        range(10),
        title="Loading",
        subtitle="Please wait",
        disabled=disabled_switch.value,
    ):
        time.sleep(sleep_time)
    return


@app.cell
def _(disabled_switch, sp, sleep_time, time):
    for _ in sp.status.progress_bar(
        range(10),
        title="Loading",
        subtitle="Please wait",
        show_eta=True,
        show_rate=True,
        disabled=disabled_switch.value,
    ):
        time.sleep(sleep_time)
    return


@app.cell
def _(disabled_switch, sp, sleep_time, time):
    with sp.status.progress_bar(
        title="Loading",
        subtitle="Please wait",
        total=10,
        disabled=disabled_switch.value,
    ) as bar:
        for _ in range(10):
            time.sleep(sleep_time)
            bar.update()
    return


@app.cell
def _(sp, sleep_time, time):
    with sp.status.spinner(title="Loading...", remove_on_exit=True) as _spinner:
        time.sleep(0.1)
        _spinner.update("Almost done")
        time.sleep(sleep_time)
    return


@app.cell
def _(sp, sleep_time, time):
    with sp.status.spinner(title="Loading...", remove_on_exit=True) as _spinner:
        time.sleep(sleep_time)
        _spinner.update("Almost done")
        time.sleep(sleep_time)
    sp.ui.table([1, 2, 3])
    return


@app.cell
def _(disabled_switch, sp, sleep_time, time):
    # Fast updates should be debounced for performance
    for i in sp.status.progress_bar(
        range(1000),
        disabled=disabled_switch.value,
    ):
        time.sleep(sleep_time / 10)
    return


if __name__ == "__main__":
    app.run()
