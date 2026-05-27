# /// script
# [tool.sp.runtime]
# auto_instantiate = true
# ///
#
# Smoke test for keyboard_shortcut on ui.button (#4230).
#
# Manual test plan:
#   1. Click into each input/textarea/editor below and press "K".
#   2. The letter "k" should appear in the input — the button must NOT fire.
#   3. Click somewhere neutral (outside any input) and press "K".
#   4. The button SHOULD fire (counter increments).

import signalpilot

__generated_with = "0.22.0"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot

    return (sp,)


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    # Keyboard Shortcut Smoke Test (#4230)

    The **Trigger (K)** button below has `keyboard_shortcut="K"`.
    Pressing **K** while focused in any input should type the letter,
    *not* trigger the button.
    """)
    return


@app.cell
def _(sp):
    fire_count, set_fire_count = sp.state(0)


    def _on_click(_: object) -> None:
        set_fire_count(lambda n: n + 1)


    trigger_button = sp.ui.button(
        label="Trigger action (K)",
        on_click=_on_click,
        keyboard_shortcut="K",
    )
    return fire_count, trigger_button


@app.cell
def _(fire_count, sp, trigger_button):
    counter = fire_count()
    sp.vstack(
        [
            sp.md(f"**Button fired: {counter} time(s)**"),
            trigger_button,
            sp.md("---"),
        ]
    )
    return


@app.cell
def _(sp):
    sp.md("""
    ## Edge Case: Single-key shortcut vs text input
    """)
    return


@app.cell
def _(sp):
    text_input = sp.ui.text(
        label="sp.ui.text — type K here (should NOT fire button)",
        placeholder="type here…",
    )
    text_input
    return


@app.cell
def _(sp):
    text_area = sp.ui.text_area(
        label="sp.ui.text_area — type K here (should NOT fire button)",
        placeholder="type here…",
    )
    text_area
    return


@app.cell
def _(sp):
    number_input = sp.ui.number(
        label="sp.ui.number — focus and press K (should NOT fire button)",
        start=0,
        stop=100,
        value=42,
    )
    number_input
    return


@app.cell
def _(sp):
    dropdown = sp.ui.dropdown(
        label="sp.ui.dropdown — open and press K (should NOT fire button)",
        options=["apple", "kiwi", "kumquat"],
    )
    dropdown
    return


@app.cell
def _(sp):
    sp.md("""
    ## Edge Case: Modifier-key shortcut
    """)
    return


@app.cell
def _(sp):
    mod_count, set_mod_count = sp.state(0)
    key = "Cmd-Shift-L"


    def _on_mod_click(_: object) -> None:
        set_mod_count(lambda n: n + 1)


    mod_button = sp.ui.button(
        label=f"Trigger with {key}",
        on_click=_on_mod_click,
        keyboard_shortcut=key,
    )
    return key, mod_button, mod_count


@app.cell
def _(key, sp, mod_button, mod_count):
    mc = mod_count()
    sp.vstack(
        [
            sp.md(f"**{key} button fired: {mc} time(s)**"),
            mod_button,
            sp.md(
                f"Pressing plain **K** in the text input below should type 'k'. "
                f"Only **{key}** should trigger this button."
            ),
        ]
    )
    return


@app.cell
def _(sp):
    sp.md("""
    ## Edge Case: Multiple buttons with different single-key shortcuts
    """)
    return


@app.cell
def _(sp):
    a_count, set_a_count = sp.state(0)
    b_count, set_b_count = sp.state(0)

    btn_a = sp.ui.button(
        label="Action A (press Shift-A)",
        on_click=lambda _: set_a_count(lambda n: n + 1),
        keyboard_shortcut="Shift-A",
    )
    btn_b = sp.ui.button(
        label="Action B (press Shift-B)",
        on_click=lambda _: set_b_count(lambda n: n + 1),
        keyboard_shortcut="Shift-B",
    )
    return a_count, b_count, btn_a, btn_b


@app.cell
def _(a_count, b_count, btn_a, btn_b, sp):
    ac = a_count()
    bc = b_count()
    sp.vstack(
        [
            sp.hstack([btn_a, btn_b]),
            sp.md(f"Shift-A fired: **{ac}** | Shift-B fired: **{bc}**"),
            sp.md(
                "Both buttons should work when no input is focused. "
                "Neither should fire while typing in the text input below."
            ),
        ]
    )
    return


@app.cell
def _(sp):
    multi_text = sp.ui.text(
        label="Type Shift-A or Shift-B here (buttons should NOT fire)",
        placeholder="type here…",
    )
    multi_text
    return


if __name__ == "__main__":
    app.run()
