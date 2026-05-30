import signalpilot

__generated_with = "0.13.0"
app = signalpilot.App()


@app.cell
def _():
    import signalpilot as sp
    import pandas as pd
    import numpy as np
    import altair as alt
    import matplotlib.pyplot as plt
    import plotly.express as px
    return (sp, pd, np, alt, plt, px)


@app.cell
def _(sp):
    sp.md("""
    # SignalPilot Visualization Showcase

    Every output type available in `sp.*` and `sp.ui.*`.
    Each cell demonstrates one component.
    """)


@app.cell
def _(sp):
    sp.hstack([
        sp.stat(value="1,234", label="Users", caption="+12%", direction="increase"),
        sp.stat(value="$56K", label="Revenue", caption="+8%", direction="increase"),
        sp.stat(value="98.5%", label="Uptime", caption="-0.2%", direction="decrease"),
        sp.stat(value="42ms", label="Latency", caption="-5ms", direction="decrease", target_direction="decrease"),
    ])


@app.cell
def _(sp):
    sp.vstack([
        sp.callout("This is an **info** callout.", kind="info"),
        sp.callout("This is a **warn** callout.", kind="warn"),
        sp.callout("This is a **danger** callout.", kind="danger"),
        sp.callout("This is a **success** callout.", kind="success"),
    ])


@app.cell
def _(sp):
    sp.accordion({
        "Section 1": sp.md("Content inside accordion **section 1**."),
        "Section 2": sp.md("Content inside accordion **section 2**."),
        "Section 3": sp.md("More content with `code` and [links](https://example.com)."),
    })


@app.cell
def _(sp):
    sp.tabs({
        "Overview": sp.md("## Overview Tab\nThis is the first tab."),
        "Details": sp.md("## Details Tab\nThis is the second tab."),
        "Code": sp.md("```python\nprint('hello')\n```"),
    })


@app.cell
def _(sp):
    sp.tree({
        "project/": {
            "models/": {
                "staging/": ["stg_orders.sql", "stg_customers.sql"],
                "marts/": ["fct_revenue.sql", "dim_customers.sql"],
            },
            "notebooks/": ["analysis.py", "dashboard.py"],
            "dbt_project.yml": None,
        }
    })


@app.cell
def _(pd, np):
    np.random.seed(42)
    _n = 50
    sample_df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=_n, freq="D"),
        "revenue": np.random.uniform(1000, 5000, _n).round(2),
        "orders": np.random.randint(10, 200, _n),
        "category": np.random.choice(["Electronics", "Clothing", "Food", "Books"], _n),
        "region": np.random.choice(["North", "South", "East", "West"], _n),
        "score": np.random.normal(75, 15, _n).round(1),
    })
    return (sample_df,)


@app.cell
def _(sp, sample_df):
    sp.vstack([
        sp.md("## sp.ui.table"),
        sp.ui.table(sample_df.head(10)),
    ])


@app.cell
def _(sp, sample_df):
    sp.vstack([
        sp.md("## sp.ui.dataframe — Data Explorer"),
        sp.ui.dataframe(sample_df),
    ])


@app.cell
def _(sp, sample_df):
    sp.vstack([
        sp.md("## Bare DataFrame — auto-rendered"),
        sample_df.describe(),
    ])


@app.cell
def _(sp, sample_df, alt):
    _chart = alt.Chart(sample_df).mark_bar().encode(
        x=alt.X("category:N", title="Category"),
        y=alt.Y("sum(revenue):Q", title="Total Revenue"),
        color="category:N",
    ).properties(width=500, height=300, title="Revenue by Category")
    sp.vstack([
        sp.md("## Altair Bar Chart"),
        _chart,
    ])


@app.cell
def _(sp, sample_df, alt):
    _line = alt.Chart(sample_df).mark_line(point=True).encode(
        x="date:T",
        y="revenue:Q",
        tooltip=["date:T", "revenue:Q", "category:N"],
    ).properties(width=600, height=300, title="Revenue Over Time")
    sp.vstack([
        sp.md("## Altair Line Chart"),
        _line,
    ])


@app.cell
def _(sp, sample_df, plt):
    _fig, _ax = plt.subplots(figsize=(8, 4))
    _cats = sample_df.groupby("category")["revenue"].sum().sort_values()
    _cats.plot(kind="barh", ax=_ax, color=["#4c78a8", "#f58518", "#e45756", "#72b7b2"])
    _ax.set_title("Revenue by Category (matplotlib)")
    _ax.set_xlabel("Total Revenue ($)")
    plt.tight_layout()
    sp.vstack([
        sp.md("## Matplotlib Chart"),
        _fig,
    ])


@app.cell
def _(sp, sample_df, px):
    _fig = px.scatter(
        sample_df, x="orders", y="revenue", color="category",
        size="score", hover_data=["date", "region"],
        title="Orders vs Revenue (Plotly)",
    )
    sp.vstack([
        sp.md("## Plotly Chart"),
        _fig,
    ])


@app.cell
def _(sp):
    sp.vstack([
        sp.md("## Mermaid Diagram"),
        sp.mermaid("""
        graph LR
            A[Frontend] -->|WebSocket| B[Gateway]
            B -->|Proxy| C[Notebook Pod]
            C -->|kernel-ready| A
            C -->|cell-op| A
            B -->|SQL| D[(Database)]
        """),
    ])


@app.cell
def _(sp):
    sp.md("## Interactive UI Widgets")


@app.cell
def _(sp):
    vis_slider = sp.ui.slider(start=0, stop=100, value=50, label="Slider")
    vis_slider
    return (vis_slider,)


@app.cell
def _(sp, vis_slider):
    sp.md(f"Slider value: **{vis_slider.value}**")


@app.cell
def _(sp):
    vis_dropdown = sp.ui.dropdown(
        options=["Electronics", "Clothing", "Food", "Books"],
        value="Electronics",
        label="Category",
    )
    vis_dropdown
    return (vis_dropdown,)


@app.cell
def _(sp, vis_dropdown):
    sp.md(f"Selected: **{vis_dropdown.value}**")


@app.cell
def _(sp):
    vis_text = sp.ui.text(value="", placeholder="Type something...", label="Text Input")
    vis_text
    return (vis_text,)


@app.cell
def _(sp, vis_text):
    sp.md(f"You typed: **{vis_text.value or '(nothing yet)'}**")


@app.cell
def _(sp):
    vis_checkbox = sp.ui.checkbox(label="Enable feature")
    vis_checkbox
    return (vis_checkbox,)


@app.cell
def _(sp, vis_checkbox):
    sp.md(f"Checkbox: **{'checked' if vis_checkbox.value else 'unchecked'}**")


@app.cell
def _(sp):
    vis_radio = sp.ui.radio(options=["Small", "Medium", "Large"], value="Medium", label="Size")
    vis_radio
    return (vis_radio,)


@app.cell
def _(sp, vis_radio):
    sp.md(f"Radio: **{vis_radio.value}**")


@app.cell
def _(sp):
    vis_number = sp.ui.number(start=0, stop=1000, value=42, label="Number")
    vis_number
    return (vis_number,)


@app.cell
def _(sp):
    vis_switch = sp.ui.switch(value=False, label="Dark mode")
    vis_switch
    return (vis_switch,)


@app.cell
def _(sp, vis_switch):
    sp.md(f"Switch: **{'ON' if vis_switch.value else 'OFF'}**")


@app.cell
def _(sp):
    vis_date = sp.ui.date(value="2024-06-15", label="Pick a date")
    vis_date
    return (vis_date,)


@app.cell
def _(sp, vis_date):
    sp.md(f"Date: **{vis_date.value}**")


@app.cell
def _(sp):
    vis_multi = sp.ui.multiselect(
        options=["Python", "SQL", "JavaScript", "Rust", "Go"],
        value=["Python", "SQL"],
        label="Languages",
    )
    vis_multi
    return (vis_multi,)


@app.cell
def _(sp, vis_multi):
    sp.md(f"Selected: **{', '.join(vis_multi.value)}**")


@app.cell
def _(sp):
    vis_textarea = sp.ui.text_area(
        value="SELECT *\nFROM orders\nLIMIT 10",
        label="SQL Query",
    )
    vis_textarea
    return (vis_textarea,)


@app.cell
def _(sp):
    sp.md("## Reactive Demo — Filter + Chart")


@app.cell
def _(sp):
    category_filter = sp.ui.dropdown(
        options=["All", "Electronics", "Clothing", "Food", "Books"],
        value="All",
        label="Filter by Category",
    )
    category_filter
    return (category_filter,)


@app.cell
def _(sp, sample_df, category_filter, alt):
    _filtered = sample_df if category_filter.value == "All" else sample_df[sample_df["category"] == category_filter.value]
    _chart = alt.Chart(_filtered).mark_bar().encode(
        x=alt.X("region:N"),
        y=alt.Y("mean(revenue):Q", title="Avg Revenue"),
        color="region:N",
    ).properties(width=400, height=250, title=f"Avg Revenue by Region ({category_filter.value})")
    sp.vstack([
        sp.md(f"**{len(_filtered)}** rows selected"),
        _chart,
    ])


@app.cell
def _(sp):
    sp.carousel([
        sp.md("### Slide 1\nFirst slide content"),
        sp.md("### Slide 2\nSecond slide content"),
        sp.md("### Slide 3\nThird slide content"),
    ])


@app.cell
def _(sp):
    sp.vstack([
        sp.md("## Raw JSON Output"),
        {"connections": 5, "orgs": 2, "status": "healthy", "features": ["notebooks", "mcp", "dbt"]},
    ])


if __name__ == "__main__":
    app.run()
