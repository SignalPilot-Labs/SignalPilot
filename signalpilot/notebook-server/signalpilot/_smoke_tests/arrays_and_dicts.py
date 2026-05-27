# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    items = sp.ui.array(
        [
            sp.ui.text("name", "Name"),
            sp.ui.text("age", "Age"),
            sp.ui.text("email", "Email"),
            sp.ui.text("phone", "Phone"),
            sp.ui.text("address", "Address"),
            sp.ui.text("memo", "Memo"),
        ]
    )
    return (items,)


@app.cell
def _(items):
    items
    return


@app.cell
def _(items):
    items.hstack(gap=2)
    return


@app.cell
def _(sp):
    dictionary = sp.ui.dictionary(
        {
            "name": sp.ui.text("name", "Name"),
            "age": sp.ui.text("age", "Age"),
            "email": sp.ui.text("email", "Email"),
            "phone": sp.ui.text("phone", "Phone"),
            "address": sp.ui.text("address", "Address"),
            "memo": sp.ui.text("memo", "Memo"),
        }
    )
    return (dictionary,)


@app.cell
def _(dictionary):
    dictionary
    return


@app.cell
def _(dictionary):
    dictionary.vstack()
    return


if __name__ == "__main__":
    app.run()
