# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    import time
    return (sp,)


@app.cell
def _(sp):
    secret = sp.ui.text(label="Type a valid password: ")
    secret
    return (secret,)


@app.cell
def _(sp, secret):
    # Validation 1
    # This cell just depends on the secret
    sp.stop(
        len(secret.value) < 8, sp.md("Must have length 8").callout(kind="warn")
    )

    success_1 = True
    return (success_1,)


@app.cell
def _(sp, secret):
    # Validation 2
    # This cell just depends on the secret
    sp.stop(
        "$" not in secret.value, sp.md("Must contain a **$**").callout(kind="warn")
    )

    success_2 = True
    return (success_2,)


@app.cell
def _(sp, secret, success_1):
    # Validation 3
    # This cell depends on the secret and first validation
    sp.stop(
        "7" not in secret.value and success_1,
        sp.md("Must contain the number 7").callout(kind="warn"),
    )

    success_3 = True
    return (success_3,)


@app.cell
def _(sp, success_1, success_2, success_3):
    # This depends on all the validations, and not the secret
    _success = success_1 and success_2 and success_3
    sp.stop(not _success)

    sp.md("Secret is correct!").callout(kind="success")
    return


if __name__ == "__main__":
    app.run()
