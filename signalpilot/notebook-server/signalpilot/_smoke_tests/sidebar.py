
import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="full")


@app.cell
def _(sp):
    sp.sidebar(
        [
            sp.md("# sp"),
            sp.nav_menu(
                {
                    "#home": f"{sp.icon('lucide:home')} Home",
                    "#about": f"{sp.icon('lucide:user')} About",
                    "#contact": f"{sp.icon('lucide:phone')} Contact",
                    "Links": {
                        "https://twitter.com/signalpilot_io": "Twitter",
                        "https://docs.signalpilot.ai/docs/": "GitHub",
                    },
                },
                orientation="vertical",
            ),
        ],
        footer=[
            sp.md(
                """

        ### Footer

        - [Twitter](https://twitter.com/signalpilot_io)
        - [GitHub](https://docs.signalpilot.ai/docs/)
        """
            )
        ],
        width="500px",
    )
    return


@app.cell
def _(sp):
    [
        sp.ui.button(
            label=f"{sp.icon('lucide:home')} Home",
        ),
        sp.ui.button(
            label=f"{sp.icon('lucide:home')} Home {sp.icon('lucide:external-link')}",
        ),
    ]
    return


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    sp.nav_menu(
        {
            "#home": f"{sp.icon('lucide:home')} Home",
            "#about": f"{sp.icon('lucide:user')} About",
            "#contact": f"{sp.icon('lucide:phone')} Contact",
        },
        orientation="vertical",
    )
    return


@app.cell
def _(sp):
    sp.nav_menu(
        {
            "#home": f"{sp.icon('lucide:home')} Home",
            "#about": f"{sp.icon('lucide:user')} About",
            "#contact": f"{sp.icon('lucide:phone')} Contact",
        }
    )
    return


if __name__ == "__main__":
    app.run()
