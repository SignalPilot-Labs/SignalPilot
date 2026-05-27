# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///
import signalpilot

__generated_with = "0.17.3"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    sp.md(r"""::lucide:alarm-clock::""")
    return


@app.cell(hide_code=True)
def _(sp):
    sp.hstack(
        [
            sp.md("Color"),
            sp.icon("lucide:leaf", size=20),
            sp.icon("lucide:leaf", size=20, color="blue"),
            sp.icon("lucide:leaf", size=20, color="tomato"),
            sp.icon("lucide:leaf", size=20, color="green"),
            sp.icon("lucide:leaf", size=20, color="navy"),
        ],
        justify="start",
    )
    return


@app.cell
def _(sp):
    sp.hstack(
        [
            sp.md("Flip"),
            sp.icon("lucide:leaf", size=20),
            sp.icon("lucide:leaf", size=20, flip="vertical"),
            sp.icon("lucide:leaf", size=20, flip="horizontal"),
            sp.icon("lucide:leaf", size=20, flip="vertical,horizontal"),
        ],
        justify="start",
    )
    return


@app.cell
def _(sp):
    sp.hstack(
        [
            sp.md("Rotate"),
            sp.icon("lucide:leaf", size=20),
            sp.icon("lucide:leaf", size=20, rotate="90deg"),
            sp.icon("lucide:leaf", size=20, rotate="180deg"),
            sp.icon("lucide:leaf", size=20, rotate="270deg"),
        ],
        justify="start",
    )
    return


@app.cell
def _(sp):
    sp.hstack(
        [
            sp.md("In buttons"),
            sp.ui.button(
                label=f"{sp.icon('material-symbols:rocket-launch')} Launch"
            ),
            sp.ui.button(label=f"::material-symbols:rocket-launch:: Launch"),
            sp.ui.button(label=f"Clear ::material-symbols:close-rounded::"),
            # Left and right
            sp.ui.button(
                label=f"::material-symbols:download:: Download ::material-symbols:csv::"
            ),
        ],
        justify="start",
    )
    return


@app.cell
def _(sp):
    sp.md(f"""## {sp.icon('material-symbols:edit')} Icons in markdown""")
    return


@app.cell
def _(sp):
    sp.tabs(
        {
            f"{sp.icon('material-symbols:group')} Overview": sp.md("Tab 1"),
            f"{sp.icon('material-symbols:group-add')} Add": sp.md("Tab 2"),
            f"{sp.icon('material-symbols:group-remove')} Remove": sp.md("Tab 3"),
        }
    )
    return


if __name__ == "__main__":
    app.run()
