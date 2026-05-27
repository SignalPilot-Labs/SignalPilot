import signalpilot

__generated_with = "0.21.0"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import random
    import polars as pl

    return sp, pl, random


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    # Copy Rich Content from Tables

    Test copying and filtering cells with rich HTML content.

    - **Right-click → Copy cell** should preserve hyperlinks (text/html clipboard)
    - **Ctrl+C multi-cell** should produce an HTML table alongside tab-separated text
    - **Right-click → Filter by this value** should use the raw value, not the HTML
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Table with `format_mapping` (hyperlinks)
    """)
    return


@app.cell
def _(sp):
    data = {
        "id": [1, 2, 3, 4, 5],
        "name": ["Alice", "Bob", "Charlie", "Diana", "Eve"],
        "score": [95, 87, 72, 91, 88],
        "website": [
            "https://example.com/alice",
            "https://example.com/bob",
            "https://example.com/charlie",
            "https://example.com/diana",
            "https://example.com/eve",
        ],
    }

    sp.ui.table(
        data,
        format_mapping={
            "name": lambda name: sp.md(f"**{name}**"),
            "score": lambda score: sp.md(
                f'<span style="color: {"green" if score >= 90 else "orange"}">{score}</span>'
            ),
            "website": lambda url: sp.md(f"[Visit site]({url})"),
        },
        label="Hyperlinks via format_mapping",
    )
    return


@app.cell
def _(sp):
    sp.md("""
    ## Table with mixed content (UI elements + plain values)
    """)
    return


@app.cell
def _(sp):
    sp.ui.table(
        {
            "label": ["Enable feature", "Dark mode", "Notifications"],
            "toggle": [
                sp.ui.checkbox(label="On"),
                sp.ui.checkbox(label="Off"),
                sp.ui.checkbox(label="On", value=True),
            ],
            "priority": [1, 2, 3],
        },
        label="Mixed: UI elements + plain values",
    )
    return


@app.cell
def _(sp):
    sp.md("""
    ## Table with `sp.Html()` (text/html mime)
    """)
    return


@app.cell
def _(sp):
    sp.ui.table(
        {
            "link": [
                sp.Html('<a href="https://docs.signalpilot.ai/docs/">sp</a>'),
                sp.Html('<a href="https://github.com">GitHub</a>'),
                sp.Html('<a href="https://python.org">Python</a>'),
            ],
            "badge": [
                sp.Html(
                    '<span style="background: green; color: white; padding: 2px 6px; border-radius: 4px">Active</span>'
                ),
                sp.Html(
                    '<span style="background: red; color: white; padding: 2px 6px; border-radius: 4px">Inactive</span>'
                ),
                sp.Html(
                    '<span style="background: orange; color: white; padding: 2px 6px; border-radius: 4px">Pending</span>'
                ),
            ],
            "plain": ["alpha", "beta", "gamma"],
        },
        label="Raw HTML via sp.Html()",
    )
    return


@app.cell
def _(sp):
    sp.md("""
    ## Table with inline markdown (no format_mapping)
    """)
    return


@app.cell
def _(sp):
    sp.ui.table(
        {
            "description": [
                sp.md("Contains **bold** text"),
                sp.md("Contains `inline code`"),
                sp.md("[A hyperlink](https://docs.signalpilot.ai/docs/)"),
            ],
            "plain": ["alpha", "beta", "gamma"],
        },
        label="Inline markdown as values (text/markdown mime)",
    )
    return


@app.cell
def _(sp, pl, random):
    def url(k):
        return sp.md(f"[{k}](https://www.google.com/search?q={k})")


    _random_numbers = [random.randint(1, 100) for _ in range(10)]
    df = pl.DataFrame({"filter_by_this": _random_numbers})

    sp.ui.table(df, format_mapping={"filter_by_this": url})
    return


if __name__ == "__main__":
    app.run()
