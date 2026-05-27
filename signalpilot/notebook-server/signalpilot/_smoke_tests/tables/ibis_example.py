import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    import ibis

    memtable = ibis.memtable(
        {
            "rowid": range(3000),
            "a": [1, 2, 3] * 1000,
            "b": [4, 5, 6] * 1000,
            "c": [4, 5, 6] * 1000,
            "d": [4, 5, 6] * 1000,
            "e": [4, 5, 6] * 1000,
        }
    )

    table = sp.ui.table(memtable, page_size=5)
    return (table,)


@app.cell
def _(table):
    table
    return


@app.cell
def _(sp, table):
    sp.ui.table(table.value)
    return


@app.cell
def _(table):
    table.value
    return


if __name__ == "__main__":
    app.run()
