# Smoke tests for nested sp custom elements.
# Verifies that interactive widgets, lazy loading, and layout components
# work correctly when nested inside each other (especially inside shadow DOM).
# Related: https://docs.signalpilot.ai/docs/

import signalpilot

__generated_with = "0.19.11"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot

    return (sp,)


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    # Nested components smoke tests
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Table inside tabs
    """)
    return


@app.cell
def _(sp):
    import pandas as pd

    df = pd.DataFrame({"name": ["Alice", "Bob", "Charlie"], "age": [25, 30, 35]})
    table_in_tabs = sp.ui.tabs(
        {
            "Table": sp.ui.table(df),
            "Plain": sp.md("No table here"),
        }
    )
    table_in_tabs
    return (pd,)


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Table inside accordion
    """)
    return


@app.cell
def _(sp, pd):
    df2 = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})
    sp.accordion(
        {
            "Show table": sp.ui.table(df2),
            "Show text": sp.md("Just text"),
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Lazy inside tabs (issue #5129)
    """)
    return


@app.cell
def _(sp):
    call_count_1 = []


    def lazy_fn_1():
        call_count_1.append(1)
        print(f"lazy_fn_1 called (total: {len(call_count_1)}x)")
        return sp.md(f"Loaded! Call count: {len(call_count_1)}")


    lazy_tabs = sp.ui.tabs(
        {
            "Normal": sp.md("This tab is normal"),
            "Lazy": sp.lazy(lazy_fn_1, show_loading_indicator=True),
        }
    )
    lazy_tabs
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Lazy inside accordion
    """)
    return


@app.cell
def _(sp):
    call_count_2 = []


    def lazy_fn_2():
        call_count_2.append(1)
        print(f"lazy_fn_2 called (total: {len(call_count_2)}x)")
        return sp.md(f"Loaded! Call count: {len(call_count_2)}")


    sp.accordion(
        {
            "Click to lazy load": sp.lazy(lazy_fn_2, show_loading_indicator=True),
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Tabs with `lazy=True`
    """)
    return


@app.cell
def _(sp, pd):
    df3 = pd.DataFrame({"a": range(10), "b": range(10, 20)})

    auto_lazy_tabs = sp.ui.tabs(
        {
            "Tab A": sp.md("First tab content"),
            "Tab B": sp.ui.table(df3),
            "Tab C": sp.md("Third tab content"),
        },
        lazy=True,
    )
    auto_lazy_tabs
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Accordion with `lazy=True`
    """)
    return


@app.cell
def _(sp):
    sp.accordion(
        {
            "Section 1": sp.md("Content 1"),
            "Section 2": sp.md("Content 2"),
            "Section 3": sp.md("Content 3"),
        },
        lazy=True,
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Interactive widgets inside tabs
    """)
    return


@app.cell
def _(sp):
    slider = sp.ui.slider(0, 100, value=50, label="Slider in tab")
    checkbox = sp.ui.checkbox(label="Checkbox in tab")
    dropdown = sp.ui.dropdown(
        ["Option A", "Option B", "Option C"], label="Dropdown in tab"
    )
    text_input = sp.ui.text(placeholder="Type here...", label="Text in tab")
    return checkbox, dropdown, slider, text_input


@app.cell
def _(checkbox, dropdown, sp, slider, text_input):
    widget_tabs = sp.ui.tabs(
        {
            "Slider": sp.vstack([slider, sp.md(f"Value: {slider.value}")]),
            "Checkbox": sp.vstack([checkbox, sp.md(f"Checked: {checkbox.value}")]),
            "Dropdown": sp.vstack(
                [dropdown, sp.md(f"Selected: {dropdown.value}")]
            ),
            "Text": sp.vstack([text_input, sp.md(f"Typed: {text_input.value}")]),
        }
    )
    widget_tabs
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Tabs inside tabs
    """)
    return


@app.cell
def _(sp):
    inner_tabs = sp.ui.tabs(
        {
            "Inner A": sp.md("Inner tab A"),
            "Inner B": sp.md("Inner tab B"),
        }
    )
    outer_tabs = sp.ui.tabs(
        {
            "Outer 1": inner_tabs,
            "Outer 2": sp.md("Outer tab 2"),
        }
    )
    outer_tabs
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Accordion inside tabs
    """)
    return


@app.cell
def _(sp):
    sp.ui.tabs(
        {
            "With accordion": sp.accordion(
                {
                    "Section A": sp.md("Accordion content A"),
                    "Section B": sp.md("Accordion content B"),
                }
            ),
            "Plain tab": sp.md("Just a plain tab"),
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Tabs inside accordion
    """)
    return


@app.cell
def _(sp):
    sp.accordion(
        {
            "Open for tabs": sp.ui.tabs(
                {
                    "Tab X": sp.md("Tab X content"),
                    "Tab Y": sp.md("Tab Y content"),
                }
            ),
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Lazy table inside tabs
    """)
    return


@app.cell
def _(sp, pd):
    def lazy_table():
        print("lazy_table called")
        df = pd.DataFrame({"col1": range(5), "col2": range(5, 10)})
        return sp.ui.table(df)


    sp.ui.tabs(
        {
            "Normal": sp.md("Normal content"),
            "Lazy table": sp.lazy(lazy_table, show_loading_indicator=True),
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Deeply nested: lazy inside accordion inside tabs
    """)
    return


@app.cell
def _(sp):
    def deep_lazy_fn():
        print("deep_lazy_fn called")
        return sp.md("Deeply nested lazy content loaded!")


    sp.ui.tabs(
        {
            "Top tab": sp.accordion(
                {
                    "Open for lazy": sp.lazy(
                        deep_lazy_fn, show_loading_indicator=True
                    ),
                }
            ),
            "Other tab": sp.md("Other"),
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## hstack/vstack inside tabs
    """)
    return


@app.cell
def _(sp):
    sp.ui.tabs(
        {
            "Horizontal": sp.hstack(
                [sp.md("**Left**"), sp.md("**Center**"), sp.md("**Right**")],
                justify="space-between",
            ),
            "Vertical": sp.vstack(
                [sp.md("**Top**"), sp.md("**Middle**"), sp.md("**Bottom**")],
                gap=1,
            ),
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Callout inside tabs
    """)
    return


@app.cell
def _(sp):
    sp.ui.tabs(
        {
            "Info": sp.callout(sp.md("This is an info callout"), kind="info"),
            "Warning": sp.callout(sp.md("This is a warning callout"), kind="warn"),
            "Danger": sp.callout(sp.md("This is a danger callout"), kind="danger"),
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Form inside tabs
    """)
    return


@app.cell
def _(sp):
    form = sp.ui.text(placeholder="Enter name").form()
    return (form,)


@app.cell
def _(form, sp):
    sp.ui.tabs(
        {
            "Form tab": form,
            "Result tab": sp.md(f"Submitted: {form.value}"),
        }
    )
    return


if __name__ == "__main__":
    app.run()
