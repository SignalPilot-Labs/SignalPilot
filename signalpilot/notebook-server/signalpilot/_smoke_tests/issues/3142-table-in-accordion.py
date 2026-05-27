import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    table=sp.ui.table([{"col1": "hello"},{"col1": "world"}], selection="single")
    return (table,)


@app.cell
def _(sp, table):
    if table.value:
        val = table.value[0]["col1"]
    else:
        val = ""
    text=sp.ui.text(label="Select from table", value=val)
    return (text,)


@app.cell
def _(sp, table, text):
    sp.accordion({"fold down": sp.vstack([table, text])})
    return


if __name__ == "__main__":
    app.run()
