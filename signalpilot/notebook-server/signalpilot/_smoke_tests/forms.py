# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    import random
    return sp, random


@app.cell
def _(sp):
    sp.md("# Basic form")
    return


@app.cell
def _(sp):
    clear_on_submit_input = sp.ui.checkbox(True, label="Clear on submit")
    bordered_input = sp.ui.checkbox(False, label="Bordered")
    show_clear_button_input = sp.ui.checkbox(False, label="Show clear button")
    sp.hstack([clear_on_submit_input, bordered_input, show_clear_button_input])
    return bordered_input, clear_on_submit_input, show_clear_button_input


@app.cell
def _(bordered_input, clear_on_submit_input, sp, show_clear_button_input):
    form_1 = sp.ui.text_area(
        label="Form label", full_width=True, placeholder="Type..."
    ).form(
        submit_button_label="Go!",
        clear_on_submit=clear_on_submit_input.value,
        submit_button_tooltip="Click me",
        bordered=bordered_input.value,
        show_clear_button=show_clear_button_input.value,
    )
    form_1
    return (form_1,)


@app.cell
def _(form_1, sp, random):
    random_number = random.randint(1, 100)
    sp.vstack(
        [
            sp.md("## Basic form value"),
            sp.md(
                f"Random number (to monitor re-renders) **{random_number}**"
            ),
            form_1.value,
        ]
    )
    return


@app.cell
def _(sp):
    sp.md(
        """
    -------

    # Validating forms"""
    )
    return


@app.cell
def _(sp):
    years_experience = sp.ui.slider(1, 10, value=3)
    fn = sp.ui.text()
    ln = sp.ui.text()

    def validate(value):
        if "first_name" not in value or len(value["first_name"]) == 0:
            return "Missing first name"
        if "last_name" not in value or len(value["last_name"]) == 0:
            return "Missing last name"
        if value["years_experience"] < 4:
            return "Must have at least 4 years experience"

    form_2 = (
        sp.md(
            """
        First name: {first_name}

        Last name: {last_name}

        Years Experience: {years_experience}
        """
        )
        .batch(
            first_name=fn,
            last_name=ln,
            years_experience=years_experience,
        )
        .form(
            bordered=False,
            validate=validate,
            show_clear_button=True,
        )
    )

    form_2
    return (form_2,)


@app.cell
def _(form_2, sp, random):
    _random_number = random.randint(1, 100)
    sp.vstack(
        [
            sp.md("### Validate form value"),
            sp.md(f"Random number **{_random_number}**"),
            form_2.value,
        ]
    )
    return


@app.cell
def _(sp):
    sp.md(
        """
    ------
    # Dictionary"""
    )
    return


@app.cell
def _(sp):
    dict = sp.ui.dictionary(
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
    dict
    return (dict,)


@app.cell
def _(dict, sp):
    sp.vstack(
        [
            sp.md("## Dictionary Value"),
            dict.value,
        ]
    )
    return


if __name__ == "__main__":
    app.run()
