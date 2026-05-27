# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "docstring-to-markdown==0.15",
#     "sp",
# ]
# ///

import signalpilot

__generated_with = "0.18.4"
app = sp.App(width="medium")


@app.cell
def _():
    import docstring_to_markdown
    import signalpilot
    from signalpilot._utils.docs import google_docstring_to_markdown
    return docstring_to_markdown, google_docstring_to_markdown, mo


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    This notebook compares `docstring_to_markdown` to our internal `google_docstring_to_markdown`.
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    elements = {
        "button": sp.ui.button,
        "checkbox": sp.ui.checkbox,
        "dropdown": sp.ui.dropdown,
        "text": sp.ui.text,
        "radio": sp.ui.radio,
        "refs": sp.refs,
        "defs": sp.defs,
        "hstack": sp.hstack,
        "vstack": sp.vstack,
    }
    element = sp.ui.dropdown(elements, value="button")
    element
    return (element,)


@app.cell(hide_code=True)
def _(element, sp):
    sp.accordion({"MD doc": sp.plain_text(element.value.__doc__)})
    return


@app.cell
def _(docstring_to_markdown, element, sp):
    sp.md(docstring_to_markdown.convert(element.value.__doc__))
    return


@app.cell
def _(element, google_docstring_to_markdown, sp):
    sp.md(google_docstring_to_markdown(element.value.__doc__))
    return


if __name__ == "__main__":
    app.run()
