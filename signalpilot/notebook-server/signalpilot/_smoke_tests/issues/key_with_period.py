
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    import pandas as pd
    return sp, pd


@app.cell
def _():
    json_list = [{"key.with.period": "value"} for _ in range(10)]
    return (json_list,)


@app.cell
def _(json_list, sp):
    sp.ui.table(json_list)
    return


@app.cell
def _(json_list, sp, pd):
    sp.ui.data_explorer(pd.DataFrame(json_list))
    return


@app.cell
def _(json_list, sp, pd):
    sp.ui.dataframe(pd.DataFrame(json_list))
    return


if __name__ == "__main__":
    app.run()
