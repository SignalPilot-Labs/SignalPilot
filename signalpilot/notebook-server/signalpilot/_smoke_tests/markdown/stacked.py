import signalpilot

__generated_with = "0.17.0"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    items = [
        sp.md("# one"),
        sp.md("# two"),
        sp.md("## three"),
        sp.md("## four"),
    ]
    return (items,)


@app.cell
def _(items, sp):
    sp.hstack(items)
    return


@app.cell
def _(items, sp):
    sp.vstack(items)
    return


@app.cell
def _(items, sp):
    _items = [
        sp.md("a" * 200),
        sp.md("b" * 180),
        sp.md("c" * 160),
    ]
    sp.vstack(
        [
            sp.hstack(items),
            sp.md("---"),
            *_items,
        ]
    )
    return


if __name__ == "__main__":
    app.run()
