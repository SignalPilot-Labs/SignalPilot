import signalpilot

__generated_with = "0.17.6"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import pandas as pd
    import polars as pl
    import altair as alt
    return alt, sp, pd, pl


@app.cell
def _(sp):
    sp.md(r"""
    # Printing Rich Elements
    """)
    return


@app.cell(hide_code=True)
def _(alt, sp, pd):
    text = sp.ui.text(placeholder="Enter", on_change=lambda x: print("hi"))
    warn_btn = sp.ui.button(
        kind="warn", on_click=lambda x: print("button clicked!")
    )
    password = sp.ui.text(kind="password", value="secret")

    dictionary = sp.ui.dictionary(
        {
            "slider": sp.ui.slider(1, 10),
            "text": sp.ui.text(),
            "date": sp.ui.date(),
        }
    )


    def simple_echo_model(messages, config):
        return f"You said: {messages[-1].content}"


    chat = sp.ui.chat(
        simple_echo_model,
        prompts=["Hello", "How are you?"],
        show_configuration_controls=True,
    )

    img = sp.image(
        src="https://docs.signalpilot.ai/docs/",
        alt="SignalPilot logo",
        width=100,
        height=100,
    )
    html_img = sp.Html(
        "<img src='https://docs.signalpilot.ai/docs/' width='100px' height='100px' alt='SignalPilot logo'>"
    )

    office_characters = [
        {"first_name": "Michael", "last_name": "Scott"},
        {"first_name": "Jenna", "last_name": "Leigh"},
    ]
    table = sp.ui.table(office_characters)

    user_info = sp.md(
        """
        - What's your name?: {name}
        - When were you born?: {birthday}
        """
    ).batch(name=sp.ui.text(), birthday=sp.ui.date())

    source = pd.DataFrame(
        {
            "a": ["A", "B", "C", "D", "E", "F", "G", "H", "I"],
            "b": [28, 55, 43, 91, 81, 53, 19, 87, 52],
        }
    )

    chart = alt.Chart(source).mark_bar().encode(x="a", y="b")

    mermaid = sp.mermaid(
        "graph TD\n  A[Christmas] -->|Get money| B(Go shopping)\n  B --> C{Let me think}\n  C -->|One| D[Laptop]\n  C -->|Two| E[iPhone]\n  C -->|Three| F[Car]"
    )

    tabs = sp.ui.tabs(
        {
            "📈 Sales": chart,
            "📊 Chatbot": chat,
            "💻 Settings": sp.ui.text(placeholder="Key"),
        }
    )


    data = {
        "buttons": [sp.ui.button(kind="warn"), sp.ui.button(kind="invalid")],
        "checkbox": [
            sp.ui.checkbox(value=True, label="True"),
            sp.ui.checkbox(value=False, label="False"),
        ],
        "mixed": [sp.ui.button(kind="info"), "apples"],
        "arrays": sp.ui.array([text] * 2),
        "dictionary": [dictionary, dictionary],
        "raw_objects": [
            {"fruits": ["apples", "bananas"]},
            {"trees": {"plants": "flowers"}},
        ],
        "raw_lists": [
            ["fruits", "trees", "animals"],
            ["humans", "aliens", "life"],
        ],
        "long_text": [
            "lorem_ipsum_dollar_sit" * 20,
            "lorem_ipsum_dollar_sit" * 20,
        ],
        "long_text_with_markup": [
            "lorem link: https://www.google.com" * 4,
            "lorem link: https://www.google.com" * 4,
        ],
        "large_array": [
            [1] * 60,
            [2] * 60,
        ],
        "large_json": [
            [{"key": i, "value": i} for i in range(60)],
            [{"key": i, "value": i} for i in range(60)],
        ],
        "images": [img, html_img],
        "batch": user_info,
        "dropdowns": [
            sp.ui.dropdown(options=["apple", "bananas", "coconut"]),
            sp.ui.multiselect(options=["apple", "bananas", "coconut"]),
        ],
        "markdown": sp.md("## Inputs here"),
        "chat": chat,
        "file": sp.ui.file(),
        "table": table,
        "chart": sp.ui.altair_chart(chart),
        "mermaid": mermaid,
        "tabs": tabs,
    }

    sp.vstack([sp.md("## Dictionary"), data])
    return data, password


@app.cell
def _(data, sp):
    sp.vstack([sp.md("## Table"), sp.ui.table(data, page_size=20)])
    return


@app.cell
def _(data, sp, pd):
    pandas_rich = pd.DataFrame(data).transpose()
    sp.vstack([sp.md("## Pandas dataframe"), pandas_rich])
    return (pandas_rich,)


@app.cell
def _(sp, pandas_rich):
    sp.vstack([sp.md("## Table containing pandas df"), sp.ui.table(pandas_rich)])
    return


@app.cell
def _(data, sp, pl):
    data.pop("arrays", None)
    data.pop("batch", None)
    data.pop("mixed", None)

    pl_df = pl.DataFrame(data)
    sp.vstack([sp.md("## Polars dataframe"), pl_df])
    return (pl_df,)


@app.cell
def _(sp, password):
    sp.md(f"""
    ### Password value: {password.value}
    """)
    return


@app.cell
def _(sp, pl_df):
    sp.vstack([sp.md("## Table containing polars dataframe"), sp.ui.table(pl_df)])
    return


@app.cell
def _(sp):
    sp.md(f"""
    ## This will crash the kernel (hence not enabled)

    `pl.DataFrame(data).transpose()`
    """)
    # pl.DataFrame(data).transpose()
    return


@app.cell
def _(sp, pd, pl):
    pd.DataFrame({"button": [sp.ui.button()]})

    pl.DataFrame({"button": sp.ui.button()})
    sp.ui.table({"button": sp.ui.button()})
    return


@app.cell
def _(data, sp):
    sp.ui.data_editor(data=data, label="Edit Data")
    return


@app.cell
def _(data, sp):
    sp.ui.data_explorer(data)
    return


if __name__ == "__main__":
    app.run()
