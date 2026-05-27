import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    sp.md("""# Toast Notification Test""")
    return


@app.cell
def _(sp):
    def show_toast(title, description="", kind=None):
        sp.status.toast(title, description, kind)
        return None
    return (show_toast,)


@app.cell
def _(sp):
    simple_toast = sp.ui.checkbox(label="Simple Toast")
    html_toast = sp.ui.checkbox(label="Toast with HTML description")
    danger_toast = sp.ui.checkbox(label="Danger Toast")
    return danger_toast, html_toast, simple_toast


@app.cell
def _(sp):
    sp.md("""Select a checkbox to trigger a toast notification:""")
    return


@app.cell
def _(danger_toast, html_toast, sp, simple_toast):
    sp.vstack(
        [
            simple_toast,
            html_toast,
            danger_toast,
        ]
    )
    return


@app.cell
def _(danger_toast, html_toast, show_toast, simple_toast):
    if simple_toast.value:
        show_toast("Simple Toast", "This is a basic toast notification")

    if html_toast.value:
        show_toast(
            "HTML Toast", "<b>Bold</b> and <i>italic</i> text in description"
        )

    if danger_toast.value:
        show_toast("Error Occurred", "Something went wrong!", kind="danger")
    return


if __name__ == "__main__":
    app.run()
