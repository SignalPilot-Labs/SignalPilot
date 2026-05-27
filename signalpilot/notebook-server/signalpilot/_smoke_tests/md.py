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
    sp.md("""# Tables""")
    return


@app.cell
def _(sp):
    sp.md(
        """
        First Header  | Second Header
        ------------- | -------------
        Content Cell  | Content Cell
        $f(x)$        | Content Cell
        """
    )
    return


@app.cell
def _(sp):
    sp.md(
        """
        | Tables        | Are           | Cool  |
        | ------------- |:-------------:| -----:|
        | col 3 is      | right-aligned | $1600 |
        | col 2 is      | centered      |   $12 |
        | zebra stripes | are neat      |    $1 |
        """
    )
    return


@app.cell
def _(sp):
    sp.md("""# Footnotes""")
    return


@app.cell
def _(sp):
    sp.md(
        """
        Here's a short footnote,[^1] and here's a longer one.[^longnote]

        [^1]: This is a short footnote.

        [^longnote]: This is a longer footnote with paragraphs, and code.

            Indent paragraphs to include them in the footnote.

            `{ my code }` add some code, if you like.

            Add as many paragraphs as you need.
        """
    )
    return


@app.cell
def _(sp):
    sp.md("""# External links""")
    return


@app.cell
def _(sp):
    sp.md(
        """
        This is [an example](http://example.com/ "Title") inline link.

        [This link](http://example.net/) has no title attribute.
        """
    )
    return


if __name__ == "__main__":
    app.run()
