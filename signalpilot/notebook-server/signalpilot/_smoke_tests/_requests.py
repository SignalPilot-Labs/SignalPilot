import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    refresh = sp.ui.refresh(default_interval="3s")
    refresh
    return (refresh,)


@app.cell
def _(sp, refresh):
    refresh
    user = sp.app_meta().request.user
    [user]
    return


@app.cell
def _(sp, refresh):
    refresh
    list(sp.app_meta().request.keys())
    return


@app.cell
def _(sp, refresh):
    refresh
    sp.app_meta().request
    return


if __name__ == "__main__":
    app.run()
