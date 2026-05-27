
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
    reset_button = sp.ui.button(label="Reset")
    reset_button
    return (reset_button,)


@app.cell
def _(sp, random, reset_button):
    reset_button
    my_pick = random.randint(0, 10)
    sp.accordion({"My pick": my_pick})
    return (my_pick,)


@app.cell
def _(sp):
    refresh = sp.ui.refresh(options=["1s", "10s", "1m", "100ms"])
    sp.md(f"Choose an interval to guess {refresh}")
    return (refresh,)


@app.cell
def _(sp, my_pick, random, refresh):
    refresh
    guess = random.randint(0, 10)
    sp.stop(
        guess == my_pick,
        sp.md(f"That is correct: {my_pick}").callout(kind="success"),
    )

    sp.md(f"Not correct, your guess was {random.randint(0, 10)}").callout(
        kind="warn"
    )
    return


if __name__ == "__main__":
    app.run()
