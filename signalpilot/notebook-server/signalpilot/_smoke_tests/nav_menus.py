# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _(sp):
    sp.md("""# Horizontal""")
    return


@app.cell
def _(sp):
    sp.nav_menu(
        {
            "#overview": "Overview",
            "#sales": f"{sp.icon('lucide:shopping-cart')} Sales",
            "#products": f"{sp.icon('lucide:package')} Products",
        }
    )
    return


@app.cell
def _(sp):
    sp.md("""-----""")
    return


@app.cell
def _(sp):
    sp.nav_menu(
        {
            "#overview": "Overview",
            f"{sp.icon('lucide:shopping-cart')} Sales": {
                "/sales-today": "Sales today",
                "/sales-yesterday": "Sales yesterday",
                "/sales-custom": {
                    "label": "Custom",
                    "description": "Create custom filters to query sales",
                },
            },
            f"{sp.icon('lucide:package')} Products": {
                "#products-today": "Products today",
                "#products-yesterday": "Products yesterday",
                "#products-custom": {
                    "label": "Custom",
                    "description": "Create custom filters to query products",
                },
            },
        }
    )
    return


@app.cell
def _(sp):
    sp.md("""# Vertical""")
    return


@app.cell
def _(sp):
    sp.nav_menu(
        {
            "#overview": "Overview",
            "#sales": f"{sp.icon('lucide:shopping-cart')} Sales",
            "#products": f"{sp.icon('lucide:package')} Products",
        },
        orientation="vertical",
    )
    return


@app.cell
def _(sp):
    sp.md("""-----""")
    return


@app.cell
def _(sp):
    sp.nav_menu(
        {
            "#overview": "Overview",
            "Sales": {
                "#sales-today": "Sales today",
                "#sales-yesterday": "Sales yesterday",
                "#sales-custom": {
                    "label": "Custom",
                    "description": "Create custom filters to query sales",
                },
            },
            "Products": {
                "#products-today": "Products today",
                "#products-yesterday": "Products yesterday",
                "#products-custom": {
                    "label": "Custom",
                    "description": "Create custom filters to query products",
                },
            },
        },
        orientation="vertical",
    )
    return


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
