import signalpilot

__generated_with = "0.23.6"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot

    return (sp,)


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## 1. Baseline: a few horizontal tabs

    Should look identical to pre-fix behavior — no scrollbar shown,
    nothing visually changed.
    """)
    return


@app.cell
def _(sp):
    sp.ui.tabs(
        {
            "Hello": sp.md("Hello, world! 👋"),
            "Goodbye": sp.md("See you later."),
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## 2. Many horizontal tabs

    With 100 tabs, the tab bar should be **horizontally scrollable** — every
    tab is reachable. Try scrolling with the trackpad/mouse wheel and using
    the keyboard arrow keys after focusing a tab.
    """)
    return


@app.cell
def _(sp):
    sp.ui.tabs({f"tab-{i:02d}": sp.md(f"content {i}") for i in range(100)})
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## 3. Long labels in horizontal tabs

    Long labels should not wrap inside a single trigger; the tab bar
    scrolls horizontally instead.
    """)
    return


@app.cell
def _(sp):
    sp.ui.tabs(
        {
            "A reasonably descriptive section title": sp.md("A"),
            "Another wordy heading that takes up space": sp.md("B"),
            "Yet another deliberately verbose tab label": sp.md("C"),
            "And one more for good measure to force overflow": sp.md("D"),
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## 4. Many tabs, **vertical** orientation

    With `orientation="vertical"`, tabs stack on the left and content
    appears on the right.
    """)
    return


@app.cell
def _(sp):
    sp.ui.tabs(
        {f"Section {i:02d}": sp.md(f"### Content {i}") for i in range(20)},
        orientation="vertical",
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## 5. Vertical orientation with rich content
    """)
    return


@app.cell
def _(sp):
    _user = sp.vstack(
        [
            sp.md("**Edit user**"),
            sp.ui.text(label="First name", value="Ada", placeholder="First name"),
            sp.ui.text(
                label="Last name", value="Lovelace", placeholder="Last name"
            ),
            sp.ui.text(
                label="Email",
                value="ada@example.com",
                placeholder="name@example.com",
            ),
            sp.ui.text(
                label="Phone",
                value="+1 (555) 123-4567",
                placeholder="+1 (555) ...",
            ),
            sp.ui.dropdown(
                options=[
                    "Developer",
                    "Designer",
                    "Product Manager",
                    "Admin",
                    "Other",
                ],
                value="Developer",
                label="Role",
            ),
        ]
    )
    _org = sp.vstack(
        [
            sp.md("**Edit organization**"),
            sp.ui.text(
                label="Organization",
                value="sp",
                placeholder="Organization name",
            ),
            sp.ui.text(
                label="Website",
                value="https://signalpilot.ai",
                placeholder="https://...",
            ),
            sp.ui.number(label="Employees", start=0, stop=10000, value=42),
            sp.ui.dropdown(
                options=[
                    "Software",
                    "Healthcare",
                    "Finance",
                    "Education",
                    "Non-profit",
                    "Other",
                ],
                value="Software",
                label="Industry",
            ),
        ]
    )
    sp.ui.tabs(
        {"🧙 User": _user, "🏢 Organization": _org},
        orientation="vertical",
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## 6. Labeled tabs that overflow

    The label is rendered above the (scrollable) tab bar, and the tab bar
    still scrolls horizontally rather than getting clipped.
    """)
    return


@app.cell
def _(sp):
    sp.ui.tabs(
        {f"option-{i:02d}": sp.md(f"option body {i}") for i in range(30)},
        label="Pick an option",
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## 7. `lazy=True` + many tabs

    Switching tabs should still work; only the active tab's content gets
    materialized. Inspect the DOM and confirm that `sp-lazy` placeholders
    are present for inactive tabs.
    """)
    return


@app.cell
def _(sp):
    sp.ui.tabs(
        {f"lazy-{i:02d}": sp.md(f"lazy content {i}") for i in range(40)},
        lazy=True,
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## 8. Markdown in tab labels

    Tab labels are interpreted as markdown — bold/inline code/emoji should
    all render in the trigger, and the bar should still scroll.
    """)
    return


@app.cell
def _(sp):
    sp.ui.tabs(
        {
            "**Bold**": sp.md("Bold tab"),
            "`code`": sp.md("Code tab"),
            "🚀 Launch": sp.md("Launch tab"),
            "🌗 Theme": sp.md("Theme tab"),
            "_italic_": sp.md("Italic tab"),
            "Plain text": sp.md("Plain tab"),
            "More 1": sp.md("..."),
            "More 2": sp.md("..."),
            "More 3": sp.md("..."),
            "More 4": sp.md("..."),
            "More 5": sp.md("..."),
            "More 6": sp.md("..."),
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## 9. Invalid orientation raises

    Verify that passing a bad `orientation` value raises a clear
    `ValueError`.
    """)
    return


@app.cell
def _(sp):
    # Expected to fail
    sp.ui.tabs({"a": "1"}, orientation="diagonal")
    return


if __name__ == "__main__":
    app.run()
