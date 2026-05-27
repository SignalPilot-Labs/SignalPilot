
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    import leafmap.foliumap as leafmap

    m = leafmap.Map(center=(40, -100), zoom=4)
    return m, mo


@app.cell
def _(m):
    m  # Using our custom formatter
    return


@app.cell
def _(m, sp):
    sp.Html(m._repr_html_())  # Using the built-in ipython formatter
    return


if __name__ == "__main__":
    app.run()
