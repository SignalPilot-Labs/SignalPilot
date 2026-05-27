import signalpilot

__generated_with = "0.23.1"
app = sp.App(width="columns", auto_download=["ipynb"])


@app.cell(column=0)
def _():
    import signalpilot._code_mode as cm
    import signalpilot

    code_mode = cm
    return cm, mo


@app.cell
def _(sp):
    def display_help(obj):
        with sp.capture_stdout() as cap:
            help(obj)
        return sp.plain_text(cap.getvalue())

    return (display_help,)


@app.cell(column=1)
def _(cm, display_help):
    display_help(cm)
    return


@app.cell
def _(cm, display_help):
    display_help(cm.AsyncCodeModeContext)
    return


@app.cell
def _(cm, display_help):
    display_help(cm.CellStatusType)
    return


@app.cell
def _(cm, display_help):
    display_help(cm.get_context)
    return


@app.cell
def _(cm, display_help):
    display_help(cm.NotebookCell)
    return


@app.cell(column=2)
def _(cm):
    dir(cm)
    return


@app.cell
def _(cm):
    help(cm.get_context)
    return


@app.cell
def _(cm):
    dir(cm.AsyncCodeModeContext)
    return


@app.cell
def _(cm):
    dir(cm.CellStatusType)
    return


@app.cell
def _(cm):
    dir(cm.NotebookCell)
    return


if __name__ == "__main__":
    app.run()
