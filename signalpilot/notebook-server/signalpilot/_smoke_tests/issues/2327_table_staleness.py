import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import datetime
    return datetime, mo


@app.cell
def _():
    initial_data = [{"x": 1, "y": -1}]
    return (initial_data,)


@app.cell
def _(initial_data, sp):
    get_data, set_data = sp.state(initial_data)
    return get_data, set_data


@app.cell
def _(datetime, get_data, sp, set_data):
    _data = get_data()
    print("Creating new table list", datetime.datetime.utcnow())
    def on_change_wrapper(i, k):    
        def on_change(value):
            print("setting")
            _data = get_data()
            _data[i][k] = value
            set_data(_data)
        return on_change

    table_list = [{k: sp.ui.number(value=v, start=-100, stop=100, on_change=on_change_wrapper(i, k)) for k, v in d.items()} for i, d in enumerate(_data)]
    return (table_list,)


@app.cell
def _(sp, table_list):
    table = sp.ui.table(table_list)
    return (table,)


@app.cell
def _(get_data, sp, set_data):
    def on_click(*value):
        rows = get_data()
        rows.append({"x": 0, "y": 0})
        set_data(rows)



    add_row = sp.ui.button(label="add row", on_click=on_click)
    return (add_row,)


@app.cell
def _(add_row, sp, table):
    sp.vstack([table, add_row])
    return


@app.cell
def _(get_data):
    get_data()
    return


@app.cell
def _(table_list):
    table_list[0]["x"].value
    return


if __name__ == "__main__":
    app.run()
