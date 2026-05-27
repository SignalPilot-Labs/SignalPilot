
import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    sp.md("# Heading 1")
    return


@app.cell
def _(sp):
    sp.carousel([sp.md("# Carousel Heading")])
    return


@app.cell
def _(sp):
    sp.md("# Heading 2 \n\n Headings between carousel and tabs are detected")
    return


@app.cell
def _(sp):
    sp.ui.tabs({"Tab 1": sp.md("# Tabs Heading")})
    return


@app.cell
def _(sp):
    sp.md("# Heading 3 \n\n Headings between tabs and accordion are detected")
    return


@app.cell
def _(sp):
    sp.accordion({"Accordion 1": sp.md("# Accordion Heading")})
    return


@app.cell
def _(sp):
    sp.md("# Heading 4")
    return


if __name__ == "__main__":
    app.run()
