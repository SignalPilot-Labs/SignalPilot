# Regression test for https://docs.signalpilot.ai/docs/
# sp.lazy inside sp.ui.tabs should only execute the function once.
# Previously, the shadow DOM created a duplicate sp-lazy element
# which fired a second load() request.

import signalpilot

__generated_with = "0.13.14"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot

    def lazy_tab():
        import time

        print("LAZYTAB 1")
        time.sleep(1)
        print("LAZYTAB 2")
        return sp.md("Finish loading lazy tab !")

    sp.ui.tabs(
        {
            "normal-tab": sp.md("This is a normal tab"),
            "lazy-tab": sp.lazy(lazy_tab),
        }
    )
    return


if __name__ == "__main__":
    app.run()
