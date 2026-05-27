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
    sp.md("""hello""")
    return


@app.cell
def _(sp):
    sp.Html("<script>console.log(document.querySelectorAll('p')[0].textContent)</script>")
    return


if __name__ == "__main__":
    app.run()
