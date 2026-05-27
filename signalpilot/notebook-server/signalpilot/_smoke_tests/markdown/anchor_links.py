"""Test anchor links preserving query parameters.

This example demonstrates that anchor links in markdown properly preserve
query parameters (like ?file=test.py) when navigating within the document.

To test:
 Run this file with: sp edit anchor_links.py
"""

import signalpilot

__generated_with = "0.16.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell(hide_code=True)
def _(sp):
    sp.md(
        """
    # Anchor Link Test

    This document tests that anchor links preserve query parameters when 
    navigating between sections.

    ## Table of Contents

    - [Go to Section 1](#section-1)
    - [Go to Section 2](#section-2)
    - [Go to Section 3](#section-3)
    """
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(
        """
    # Section 1

    This is the first section. You can navigate to:
    - [Section 2](#section-2)
    - [Section 3](#section-3)
    - [Back to top](#anchor-link-test)
    """
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(
        """
    # Section 2

    This is the second section. You can navigate to:
    - [Section 1](#section-1)
    - [Section 3](#section-3)
    - [Back to top](#anchor-link-test)
    """
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(
        """
    # Section 3

    This is the third section. You can navigate to:
    - [Section 1](#section-1)
    - [Section 2](#section-2)
    - [Back to top](#anchor-link-test)
    """
    )
    return


if __name__ == "__main__":
    app.run()
