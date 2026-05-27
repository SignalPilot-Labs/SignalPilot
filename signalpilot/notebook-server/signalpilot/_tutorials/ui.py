
import signalpilot

__generated_with = "0.19.7"
app = sp.App()


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    # UI Elements

    One of sp's most powerful features is its first-class
    support for interactive user interface (UI) elements: interacting
    with a UI element will automatically run cells that reference it.
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## sp.ui
    """)
    return


@app.cell
def _(sp):
    slider = sp.ui.slider(start=1, stop=10, step=1)
    slider

    sp.md(
        f"""
        The `sp.ui` module has a library of pre-built elements.

        For example, here's a `slider`: {slider}
        """
    )
    return (slider,)


@app.cell
def _(sp, slider):
    sp.md(f"and here's its value: **{slider.value}**.")
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ### How interactions run cells

    Whenever you interact with a UI element, its value is sent back to
    Python. When this happens, all cells that reference the global variable
    bound to the UI element, but don't define it, will run.

    This simple rule lets you use UI elements to
    drive the execution of your program, letting you build
    interactive notebooks and tools for yourselves and others.
    """)
    return


@app.cell(hide_code=True)
def _(sp, slider):
    sp.accordion(
        {
            "Tip: assign UI elements to global variables": (
                """
                Interacting with a displayed UI element will only
                trigger reactive execution if the UI element is assigned
                to a global variable.
                """
            ),
            "Tip: accessing an element's value": (
                """
                Every UI element has a value attribute that you can access in
                Python.
                """
            ),
            "Tip: embed UI elements in markdown": sp.md(
                f"""
                You can embed UI elements in markdown using f-strings.

                For example, we can render the slider here: {slider}
                """
            ),
        }
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ### Simple elements
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    sp has a [large library of simple UI elements](https://docs.signalpilot.ai/docs/). Here are a just few examples:
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(
        """
        See our [examples folder](https://docs.signalpilot.ai/docs/) on GitHub for bite-sized notebooks showcasing all our UI elements. For
        a more detailed reference, see our [API docs](https://docs.signalpilot.ai/docs/).
        """
    ).callout()
    return


@app.cell
def _(sp):
    number = sp.ui.number(start=1, stop=10, step=1)
    number
    return (number,)


@app.cell
def _(number):
    number.value
    return


@app.cell
def _(sp):
    checkbox = sp.ui.checkbox(label="checkbox")
    checkbox
    return (checkbox,)


@app.cell
def _(checkbox):
    checkbox.value
    return


@app.cell
def _(sp):
    text = sp.ui.text(placeholder="type some text ...")
    text
    return (text,)


@app.cell
def _(text):
    text.value
    return


@app.cell
def _(sp):
    text_area = sp.ui.text_area(placeholder="type some text ...")
    text_area
    return (text_area,)


@app.cell
def _(text_area):
    text_area.value
    return


@app.cell
def _(sp):
    dropdown = sp.ui.dropdown(["a", "b", "c"])
    dropdown
    return (dropdown,)


@app.cell
def _(dropdown):
    dropdown.value
    return


@app.cell
def _(sp):
    run_button = sp.ui.run_button(label="click me")
    run_button
    return (run_button,)


@app.cell
def _(run_button):
    "Run button was clicked!" if run_button.value else "Click the run button!"
    return


@app.cell
def _(sp):
    file_upload = sp.ui.file(kind="area")
    file_upload
    return (file_upload,)


@app.cell
def _(file_upload):
    file_upload.value
    return


@app.cell
def _(basic_ui_elements, sp):
    sp.md(f"To see more examples, use this dropdown: {basic_ui_elements}")
    return


@app.cell
def _(basic_ui_elements, construct_element, show_element):
    selected_element = construct_element(basic_ui_elements.value)
    show_element(selected_element)
    return (selected_element,)


@app.cell
def _(selected_element, value):
    value(selected_element)
    return


@app.cell
def _(basic_ui_elements, documentation):
    documentation(basic_ui_elements.value)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    `sp.ui.matrix` lets you edit 2D numeric data interactively.
    """)
    return


@app.cell
def _(sp):
    matrix = sp.ui.matrix(
        [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        min_value=-5,
        max_value=5,
        step=0.1,
        precision=1,
        label="$I$",
    )
    matrix
    return (matrix,)


@app.cell
def _(matrix):
    matrix.value
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ### Composite elements

        Composite elements are advanced elements that
        let you build UI elements out of other UI elements.

        Use these powerful elements to logically group together related elements,
        create a dynamic set of UI elements, or reduce the number of global
        variables in your program.
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    This first example shows how to create an array of UI elements using `sp.ui.array`.
    When you interact with an element in the array, all cells that reference the
    array are reactively run. If you instead used a regular Python list, cells referring to the list would _not_ be run.
    """)
    return


@app.cell
def _(sp):
    array = sp.ui.array(
        [sp.ui.text(), sp.ui.slider(start=1, stop=10), sp.ui.date()]
    )
    array
    return (array,)


@app.cell
def _(array):
    array.value
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    sp also comes with `sp.ui.dictionary`, which is analogous to `sp.ui.array`
    """)
    return


@app.cell
def _(sp):
    dictionary = sp.ui.dictionary(
        {
            "text": sp.ui.text(),
            "slider": sp.ui.slider(start=1, stop=10),
            "date": sp.ui.date(),
        }
    )
    dictionary
    return (dictionary,)


@app.cell
def _(dictionary):
    dictionary.value
    return


@app.cell(hide_code=True)
def _(composite_elements, sp):
    sp.md(
        f"To see additional composite elements, use this dropdown: {composite_elements}"
    )
    return


@app.cell
def _(composite_elements, construct_element, show_element):
    composite_element = construct_element(composite_elements.value)
    show_element(composite_element)
    return (composite_element,)


@app.cell
def _(composite_element, value):
    value(composite_element)
    return


@app.cell
def _(composite_elements, documentation):
    documentation(composite_elements.value)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ### Building custom elements

    sp supports third-party UI elements through anywidget — this lets you build
    your own interactive UI elements, or use widgets built by others in the
    community. To learn more, [see our
    docs](https://docs.signalpilot.ai/docs/).
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Appendix
    The remaining cells are helper data structures and functions.
    You can look at their code if you're curious how certain parts of this
    tutorial were implemented.
    """)
    return


@app.cell
def _(sp):
    composite_elements = sp.ui.dropdown(
        options=dict(
            sorted(
                {
                    "array": sp.ui.array,
                    "batch": sp.ui.batch,
                    "dictionary": sp.ui.dictionary,
                    "form": sp.ui.form,
                }.items()
            )
        ),
        allow_select_none=True
    )
    return (composite_elements,)


@app.cell
def _(sp):
    basic_ui_elements = sp.ui.dropdown(
        options=dict(
            sorted(
                {
                    "button": sp.ui.button,
                    "checkbox": sp.ui.checkbox,
                    "date": sp.ui.date,
                    "dropdown": sp.ui.dropdown,
                    "file": sp.ui.file,
                    "matrix": sp.ui.matrix,
                    "multiselect": sp.ui.multiselect,
                    "number": sp.ui.number,
                    "radio": sp.ui.radio,
                    "range_slider": sp.ui.range_slider,
                    "slider": sp.ui.slider,
                    "switch": sp.ui.switch,
                    "tabs": sp.ui.tabs,
                    "table": sp.ui.table,
                    "text": sp.ui.text,
                    "text_area": sp.ui.text_area,
                }.items()
            )
        ),
    )
    return (basic_ui_elements,)


@app.cell
def _(sp):
    def construct_element(value):
        if value == sp.ui.array:
            return sp.ui.array(
                [sp.ui.text(), sp.ui.slider(1, 10), sp.ui.date()]
            )
        elif value == sp.ui.batch:
            return sp.md(
                """
                - Name: {name}
                - Date: {date}
                """
            ).batch(name=sp.ui.text(), date=sp.ui.date())
        elif value == sp.ui.button:
            return sp.ui.button(
                value=0, label="click me", on_click=lambda value: value + 1
            )
        elif value == sp.ui.checkbox:
            return sp.ui.checkbox(label="check me")
        elif value == sp.ui.date:
            return sp.ui.date()
        elif value == sp.ui.dictionary:
            return sp.ui.dictionary(
                {
                    "slider": sp.ui.slider(1, 10),
                    "text": sp.ui.text("type something!"),
                    "array": sp.ui.array(
                        [
                            sp.ui.button(value=0, on_click=lambda v: v + 1)
                            for _ in range(3)
                        ],
                        label="buttons",
                    ),
                }
            )
        elif value == sp.ui.dropdown:
            return sp.ui.dropdown(["a", "b", "c"])
        elif value == sp.ui.file:
            return [sp.ui.file(kind="button"), sp.ui.file(kind="area")]
        elif value == sp.ui.form:
            return sp.ui.text_area(placeholder="...").form()
        elif value == sp.ui.matrix:
            return sp.ui.matrix(
                [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                min_value=-5,
                max_value=5,
                step=0.1,
                precision=1,
                label="$I$",
            )
        elif value == sp.ui.multiselect:
            return sp.ui.multiselect(["a", "b", "c"])
        elif value == sp.ui.number:
            return sp.ui.number(start=1, stop=10, step=0.5)
        elif value == sp.ui.radio:
            return sp.ui.radio(["a", "b", "c"], value="a")
        elif value == sp.ui.range_slider:
            return sp.ui.range_slider(start=1, stop=10, step=0.5)
        elif value == sp.ui.slider:
            return sp.ui.slider(start=1, stop=10, step=0.5)
        elif value == sp.ui.switch:
            return sp.ui.switch()
        elif value == sp.ui.tabs:
            return sp.ui.tabs(
                {
                    "Employee #1": {
                        "first_name": "Michael",
                        "last_name": "Scott",
                    },
                    "Employee #2": {
                        "first_name": "Dwight",
                        "last_name": "Schrute",
                    },
                }
            )
        elif value == sp.ui.table:
            return sp.ui.table(
                data=[
                    {"first_name": "Michael", "last_name": "Scott"},
                    {"first_name": "Dwight", "last_name": "Schrute"},
                ],
                label="Employees",
            )
        elif value == sp.ui.text:
            return sp.ui.text()
        elif value == sp.ui.text_area:
            return sp.ui.text_area()
        return None

    return (construct_element,)


@app.cell
def _(sp):
    def show_element(element):
        if element is not None:
            return sp.hstack([element], justify="center")

    return (show_element,)


@app.cell
def _(sp):
    def value(element):
        if element is not None:
            v = (
                element.value
                if not isinstance(element, sp.ui.file)
                else element.name()
            )
            return sp.md(
                f"""
                The element's current value is {sp.as_html(element.value)}
                """
            )

    return (value,)


@app.cell
def _(sp):
    def documentation(element):
        if element is not None:
            return sp.accordion(
                {
                    f"Documentation on `sp.ui.{element.__name__}`": sp.doc(
                        element
                    )
                }
            )

    return (documentation,)


@app.cell
def _():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
