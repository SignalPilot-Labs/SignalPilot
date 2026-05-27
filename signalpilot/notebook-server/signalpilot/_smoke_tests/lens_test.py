# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    from functools import partial

    data = []


    def append(v, i):
        del v
        data.append(i)


    dict_template = {
        str(i): sp.ui.button(
            value=i,
            label=str(i),
            on_click=lambda v: v + 1,
            on_change=partial(append, i=i),
        )
        for i in range(3)
    }


    x = sp.ui.dictionary(
        {
            str(i): sp.ui.button(
                value=i,
                label=str(i),
                on_click=lambda v: v + 1,
                on_change=partial(append, i=i),
            )
            for i in range(3)
        }
    )
    # x
    return data, dict_template, x


@app.cell
def _(sp, x):
    sp.ui.table([{"data": "foo", "button": btn} for btn in x.values()])
    return


@app.cell
def _(data, x):
    # x.value counts how many times each button has been clicked
    # data is a log of button clicks
    x.value, data
    return


@app.cell
def _(dict_template, sp):
    composite = sp.ui.array(
        [
            sp.ui.slider(1, 10),
            sp.ui.array([sp.ui.checkbox(False), sp.ui.slider(10, 20)]),
            sp.ui.dictionary(dict_template),
        ]
    )
    return (composite,)


@app.cell
def _():
    10
    return


@app.cell
def _(composite):
    composite[0], composite[1], composite[2]
    return


@app.cell
def _(composite, sp):
    sp.accordion({"Push a button": composite[2]["0"]})
    return


@app.cell
def _(composite):
    composite.value
    return


@app.function
def change_printer(v):
    print("changed ", v)


@app.cell
def _(checkboxes):
    [_item for _item in checkboxes]
    return


@app.cell
def _(sp):
    checkboxes = sp.ui.array(
        [sp.ui.checkbox(False, on_change=change_printer) for i in range(5)]
    )
    return (checkboxes,)


if __name__ == "__main__":
    app.run()
