
import signalpilot

__generated_with = "0.19.7"
app = sp.App()


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    # Layout

    `sp` provides functions to help you lay out your output, such as
    in rows and columns, accordions, tabs, and callouts.
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Rows and columns

    Arrange objects into rows and columns with `sp.hstack` and `sp.vstack`.
    """)
    return


@app.cell
def _(sp):
    sp.hstack(
        [sp.ui.text(label="hello"), sp.ui.slider(1, 10, label="slider")],
        justify="start",
    )
    return


@app.cell
def _(sp):
    sp.vstack([sp.ui.text(label="world"), sp.ui.number(1, 10, label="number")])
    return


@app.cell
def _(sp):
    grid = sp.vstack(
        [
            sp.hstack(
                [sp.ui.text(label="hello"), sp.ui.slider(1, 10, label="slider")],
            ),
            sp.hstack(
                [sp.ui.text(label="world"), sp.ui.number(1, 10, label="number")],
            ),
        ],
    ).center()

    sp.md(
        f"""
        Combine `sp.hstack` with `sp.vstack` to make grids:

        {grid}

        You can pass anything to `sp.hstack` to `sp.vstack` (including
        plots!).
        """
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    **Customization.**
    The presentation of stacked elements can be customized with some arguments
    that are best understood by example.
    """)
    return


@app.cell
def _(sp):
    justify = sp.ui.dropdown(
        ["start", "center", "end", "space-between", "space-around"],
        value="space-between",
        label="justify",
    )
    align = sp.ui.dropdown(
        ["start", "center", "end", "stretch"], value="center", label="align"
    )
    gap = sp.ui.number(start=0, step=0.25, stop=2, value=0.5, label="gap")
    wrap = sp.ui.checkbox(label="wrap")

    sp.hstack([justify, align, gap, wrap], justify="center")
    return align, gap, justify, wrap


@app.cell
def _(sp):
    size = sp.ui.slider(label="box size", start=60, stop=500)
    sp.hstack([size], justify="center")
    return (size,)


@app.cell
def _(align, boxes, gap, justify, sp, wrap):
    sp.hstack(
        boxes,
        align=align.value,
        justify=justify.value,
        gap=gap.value,
        wrap=wrap.value,
    )
    return


@app.cell
def _(align, boxes, gap, sp):
    sp.vstack(
        boxes,
        align=align.value,
        gap=gap.value,
    )
    return


@app.cell
def _(sp, size):
    def create_box(num=1):
        box_size = size.value + num * 10
        return sp.Html(
            f"<div style='min-width: {box_size}px; min-height: {box_size}px; background-color: orange; text-align: center; line-height: {box_size}px'>{str(num)}</div>"
        )


    boxes = [create_box(i) for i in range(1, 5)]
    return (boxes,)


@app.cell(hide_code=True)
def _(sp):
    sp.accordion(
        {
            "Documentation: `sp.hstack`": sp.doc(sp.hstack),
            "Documentation: `sp.vstack`": sp.doc(sp.vstack),
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    **Justifying `Html`.** While you can center or right-justify any object
    using `sp.hstack`, `Html` objects (returned by most sp
    functions, and subclassed by most sp classes) have a shortcut using
    via their `center`, `right`, and `left` methods.
    """)
    return


@app.cell
def _(sp):
    sp.md("""
    This markdown is left-justified.
    """)
    return


@app.cell
def _(sp):
    sp.md("This markdown is centered.").center()
    return


@app.cell
def _(sp):
    sp.md("This markdown is right-justified.").right()
    return


@app.cell(hide_code=True)
def _(sp):
    sp.accordion(
        {
            "Documentation: `Html.center`": sp.doc(sp.Html.center),
            "Documentation: `Html.right`": sp.doc(sp.Html.right),
            "Documentation: `Html.left`": sp.doc(sp.Html.left),
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Accordion

    Create expandable shelves of content using `sp.accordion`:
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    An accordion can contain multiple items:
    """)
    return


@app.cell
def _(sp):
    sp.accordion(
        {
            "Multiple items": "By default, only one item can be open at a time",
            "Allow multiple items to be open": (
                """
                Use the keyword argument `multiple=True` to allow multiple items
                to be open at the same time
                """
            ),
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Tabs

    Use `sp.ui.tabs` to display multiple objects in a single tabbed output:
    """)
    return


@app.cell
def _(sp):
    _settings = sp.vstack(
        [
            sp.md("**Edit User**"),
            sp.ui.text(label="First Name"),
            sp.ui.text(label="Last Name"),
        ]
    )

    _organization = sp.vstack(
        [
            sp.md("**Edit Organization**"),
            sp.ui.text(label="Organization Name"),
            sp.ui.number(label="Number of employees", start=0, stop=1000),
        ]
    )

    sp.ui.tabs(
        {
            "🧙‍♀ User": _settings,
            "🏢 Organization": _organization,
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.accordion({"Documentation: `sp.ui.tabs`": sp.doc(sp.ui.tabs)})
    return


@app.cell
def _(sp):
    _t = [
        sp.md("**Hello!**"),
        sp.md(r"$f(x)$"),
        {"c": sp.ui.slider(1, 10), "d": (sp.ui.checkbox(), sp.ui.switch())},
    ]

    sp.md(
        f"""
        ## Tree

        Display a nested structure of lists, dictionaries, and tuples with
        `sp.tree`:

        {sp.tree(_t)}
        """
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.accordion({"Documentation: `sp.tree`": sp.doc(sp.tree)})
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Callout

    Turn any markdown or HTML into an emphasized callout with the `callout`
    method:
    """)
    return


@app.cell
def _(sp):
    callout_kind = sp.ui.dropdown(
        ["neutral", "warn", "success", "info", "danger"], value="neutral"
    )
    return (callout_kind,)


@app.cell
def _(callout_kind, sp):
    sp.md(
        f"""
        **This is a callout!**

        You can turn any HTML or markdown into an emphasized callout.
        You can choose from a variety of different callout kind. This one is:
        {callout_kind}
        """
    ).callout(kind=callout_kind.value)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.accordion({"Documentation: `sp.callout`": sp.doc(sp.callout)})
    return


@app.cell
def _():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
