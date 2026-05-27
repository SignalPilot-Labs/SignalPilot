# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App(app_title="1654 - Virtualize Multiselect")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    fuzzy_match_test = ["foo bar", "bar foo", "foob", "foobar", "barfoo"]
    sp.ui.multiselect(fuzzy_match_test, label="Fuzzy match test")
    return


@app.cell
def _(sp):
    (
        sp.ui.multiselect([], label="Empty"),
        sp.ui.multiselect(["1", "2"], label="2 items"),
    )
    return


@app.cell
def _(sp, xs_list):
    v = sp.ui.multiselect(xs_list, label="Extra small list with 10 items")
    v
    return (v,)


@app.cell
def _(v):
    print(v.value)
    return


@app.cell
def _(sp, sm_list):
    sp.ui.multiselect(sm_list, label="Small list with 100 items")
    return


@app.cell
def _(md_list, sp):
    sp.ui.multiselect(md_list, label="Medium list with 500 items")
    return


@app.cell
def _(lg_list, sp):
    sp.ui.multiselect(lg_list, label="Large list with 1K items")
    return


@app.cell
def _(sp, xl_list):
    sp.ui.multiselect(xl_list, label="XL list with 10K items")
    return


@app.cell
def _(sp, xxl_list):
    sp.ui.multiselect(xxl_list, label="XXL list with 100K items")
    return


@app.cell
def _(sp, xxxl_list):
    try:
        sp.ui.multiselect(xxxl_list, label="XXXL list with 200K items")
    except ValueError as e:
        print(e)
    return


@app.cell
def _():
    RANGE = 10000
    xs_list = [f"Row {i}" for i in range(RANGE // 1000)]
    sm_list = [f"Row {i}" for i in range(RANGE // 100)]
    md_list = [f"Row {i}" for i in range(RANGE // 20)]
    lg_list = [f"Row {i}" for i in range(RANGE // 10)]
    xl_list = [f"Row {i}" for i in range(RANGE)]
    xxl_list = [f"Row {i}" for i in range(RANGE * 10)]
    xxxl_list = [f"Row {i}" for i in range(RANGE * 20)]
    return lg_list, md_list, sm_list, xl_list, xs_list, xxl_list, xxxl_list


if __name__ == "__main__":
    app.run()
