import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _(sp):
    sp.md(r"""[Debounce sp.ui.text and sp.ui.text_area #2218](https://docs.signalpilot.ai/docs/)""")
    return


@app.cell
def _(debounce, debounce_options, sp):
    name_input = sp.ui.text(
        label="Enter your name for the greeting of a lifetime:", debounce=debounce
    )
    sp.vstack([debounce_options, name_input, name_input])
    return (name_input,)


@app.cell
def _(name_input):
    if len(name_input.value) > 0:
        print(f"Hello {name_input.value}!")
    return


@app.cell
def _(debounce, debounce_options, sp):
    story_input = sp.ui.text_area(
        label="Now tell me a story from your childhood:", debounce=debounce
    )
    sp.vstack([debounce_options, sp.hstack([story_input, story_input])])
    return (story_input,)


@app.cell
def _(story_input):
    if (len(story_input.value) > 0):
        print(story_input.value)
    return


@app.cell
def _(sp):
    debounce_options = sp.ui.dropdown(
        label="Choose debounce option",
        options=["True", "500", "1000", "False"],
        value="True",
    )
    return (debounce_options,)


@app.cell
def _(debounce_options):
    debounce = debounce_options.value
    debounce = (
        int(debounce) if debounce != "True" and debounce != "False" else debounce
    )
    debounce = debounce == "True" if isinstance(debounce, str) else debounce
    return (debounce,)


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
