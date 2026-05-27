import signalpilot

__generated_with = "0.23.3"
app = sp.App(
    width="medium",
    layout_file="layouts/nested_slides.slides.json",
)


@app.cell
def _():
    # Cell 1 (skip) — has visible output in the notebook, but dropped from the presentation.
    import signalpilot

    sp.callout(
        sp.md(
            "**Debug (skip):** imports loaded — you should NOT see this in the presentation."
        ),
        kind="info",
    )
    return (sp,)


@app.cell(hide_code=True)
def _(sp):
    # Cell 2 (slide) — title slide.
    sp.md("""
    # Nested Slides Smoke Test

    A deck exercising slides, sub-slides (stacks), fragments, and skip cells.
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 3 (fragment) — first reveal on the title slide.
    sp.md("""
    - Built with `@revealjs/react`
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    - Composed from flat sp cells
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 5 (slide) — agenda.
    sp.md("""
    ## Agenda

    1. Section A — sub-slides & fragments
    2. Section B — layouts across a stack
    3. Section C — fragments only
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 6 (slide) — start of Section A stack.
    sp.md("# Section A").center()
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 7 (sub-slide) — A.1 vertical subslide.
    sp.md("""
    ## A.1 — Plain text
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 8 (fragment) — A.1 first bullet.
    sp.md("""
    - Fragments reveal incrementally
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 9 (fragment) — A.1 second bullet.
    sp.md("""
    - Each `fragment` cell is one reveal step
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 10 (sub-slide) — A.2 vertical subslide.
    sp.md("""
    ## A.2 — Continuation cells
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 11 (no slide type) — treated as a slide.
    sp.md("""
    Cells with no slide type are treated as slides.
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 12 (sub-slide) — A.3 chart subslide.
    import numpy as np

    x = np.linspace(0, 2 * np.pi, 100)
    sp.vstack(
        [
            sp.md("## A.3 — A chart"),
            sp.plain_text(f"sin(x) sampled at {len(x)} points"),
        ]
    )
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 13 (slide) — start of Section B stack.
    sp.md("# Section B").center()
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 14 (sub-slide) — B.1 hstack.
    sp.vstack(
        [
            sp.md("## B.1 — hstack"),
            sp.hstack(
                [sp.md("Left"), sp.md("Middle"), sp.md("Right")], widths="equal"
            ),
        ]
    )
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 15 (fragment) — reveals under B.1.
    sp.md("""
    _hstack items sized equally_
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 16 (sub-slide) — B.2 nested grid.
    sp.vstack(
        [
            sp.md("## B.2 — Nested grid"),
            sp.vstack(
                [
                    sp.hstack(
                        [sp.md("A"), sp.md("B"), sp.md("C")], widths="equal"
                    ),
                    sp.hstack(
                        [sp.md("D"), sp.md("E"), sp.md("F")], widths="equal"
                    ),
                ]
            ),
        ]
    )
    return


@app.cell
def _(sp):
    # Cell 17 (skip) — renders visibly in the notebook but is dropped from the presentation.
    secret = 42

    sp.callout(
        sp.md(
            f"**Debug (skip):** computed `secret = {secret}` — you should NOT see this in the presentation."
        ),
        kind="warn",
    )
    return (secret,)


@app.cell(hide_code=True)
def _(sp):
    # Cell 18 (slide) — Section C title.
    sp.md("# Section C — Fragments").center()
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 19 (fragment).
    sp.md("""
    ### First reveal
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 20 (fragment).
    sp.md("""
    ### Second reveal
    """)
    return


@app.cell(hide_code=True)
def _(sp, secret):
    # Cell 21 (fragment) — pulls in the skipped cell's value.
    sp.md(f"### Third reveal — secret is **{secret}**")
    return


@app.cell
def _(sp):
    _bios_df = {
        "first_name": ["Jane", "Alex", "Doe", "Maria", "Li", "Omar"],
        "last_name": ["Smith", "Johnson", "Brown", "Garcia", "Wei", "Ali"],
        "age": [29, 35, 42, 28, 31, 45],
        "occupation": [
            "Data Scientist",
            "Product Manager",
            "Software Engineer",
            "UX Designer",
            "Researcher",
            "Entrepreneur",
        ],
        "location": [
            "San Francisco, CA",
            "New York, NY",
            "Austin, TX",
            "Boston, MA",
            "Seattle, WA",
            "Dubai, UAE",
        ],
        "email": [
            "jane.smith@example.com",
            "alex.johnson@example.com",
            "doe.brown@example.com",
            "maria.garcia@example.com",
            "li.wei@example.com",
            "omar.ali@example.com",
        ],
        "bio": [
            "Data scientist focused on applied ML and visualization.",
            "Product manager with a background in UX and analytics.",
            "Backend engineer specializing in scalable systems.",
            "UX designer crafting human-centered digital experiences.",
            "Researcher working on human-computer interaction.",
            "Founder and operator of several tech startups.",
        ],
        "interests": [
            "hiking, photography, cooking",
            "reading, strategy games, travel",
            "open-source, biking, woodworking",
            "illustration, prototyping, user research",
            "machine learning, teaching, chess",
            "investing, mentoring, sailing",
        ],
        "joined_date": [
            "2019-06-12",
            "2017-09-03",
            "2015-02-18",
            "2020-11-01",
            "2018-04-22",
            "2010-08-30",
        ],
        "followers": [1240, 5400, 2870, 920, 1500, 10300],
        "active": [True, True, True, True, True, False],
    }

    tbl = sp.ui.table(_bios_df)
    tbl
    return


@app.cell
def _(sp):
    _bios_df = {
        "first_name": ["Jane", "Alex", "Doe", "Maria", "Li", "Omar"],
        "last_name": ["Smith", "Johnson", "Brown", "Garcia", "Wei", "Ali"],
        "age": [29, 35, 42, 28, 31, 45],
        "occupation": [
            "Data Scientist",
            "Product Manager",
            "Software Engineer",
            "UX Designer",
            "Researcher",
            "Entrepreneur",
        ],
        "location": [
            "San Francisco, CA",
            "New York, NY",
            "Austin, TX",
            "Boston, MA",
            "Seattle, WA",
            "Dubai, UAE",
        ],
        "email": [
            "jane.smith@example.com",
            "alex.johnson@example.com",
            "doe.brown@example.com",
            "maria.garcia@example.com",
            "li.wei@example.com",
            "omar.ali@example.com",
        ],
        "bio": [
            "Data scientist focused on applied ML and visualization.",
            "Product manager with a background in UX and analytics.",
            "Backend engineer specializing in scalable systems.",
            "UX designer crafting human-centered digital experiences.",
            "Researcher working on human-computer interaction.",
            "Founder and operator of several tech startups.",
        ],
        "interests": [
            "hiking, photography, cooking",
            "reading, strategy games, travel",
            "open-source, biking, woodworking",
            "illustration, prototyping, user research",
            "machine learning, teaching, chess",
            "investing, mentoring, sailing",
        ],
        "joined_date": [
            "2019-06-12",
            "2017-09-03",
            "2015-02-18",
            "2020-11-01",
            "2018-04-22",
            "2010-08-30",
        ],
        "followers": [1240, 5400, 2870, 920, 1500, 10300],
        "active": [True, True, True, True, True, False],
    }

    sp.ui.table(_bios_df)
    return


@app.cell
def _(sp):
    _bios_df = {
        "first_name": ["Jane", "Alex", "Doe", "Maria", "Li", "Omar"],
        "last_name": ["Smith", "Johnson", "Brown", "Garcia", "Wei", "Ali"],
        "age": [29, 35, 42, 28, 31, 45],
        "occupation": [
            "Data Scientist",
            "Product Manager",
            "Software Engineer",
            "UX Designer",
            "Researcher",
            "Entrepreneur",
        ],
        "location": [
            "San Francisco, CA",
            "New York, NY",
            "Austin, TX",
            "Boston, MA",
            "Seattle, WA",
            "Dubai, UAE",
        ],
        "email": [
            "jane.smith@example.com",
            "alex.johnson@example.com",
            "doe.brown@example.com",
            "maria.garcia@example.com",
            "li.wei@example.com",
            "omar.ali@example.com",
        ],
        "bio": [
            "Data scientist focused on applied ML and visualization.",
            "Product manager with a background in UX and analytics.",
            "Backend engineer specializing in scalable systems.",
            "UX designer crafting human-centered digital experiences.",
            "Researcher working on human-computer interaction.",
            "Founder and operator of several tech startups.",
        ],
        "interests": [
            "hiking, photography, cooking",
            "reading, strategy games, travel",
            "open-source, biking, woodworking",
            "illustration, prototyping, user research",
            "machine learning, teaching, chess",
            "investing, mentoring, sailing",
        ],
        "joined_date": [
            "2019-06-12",
            "2017-09-03",
            "2015-02-18",
            "2020-11-01",
            "2018-04-22",
            "2010-08-30",
        ],
        "followers": [1240, 5400, 2870, 920, 1500, 10300],
        "active": [True, True, True, True, True, False],
    }

    sp.ui.table(_bios_df)
    return


@app.cell
def _(sp):
    _bios_df = {
        "first_name": ["Jane", "Alex", "Doe", "Maria", "Li", "Omar"],
        "last_name": ["Smith", "Johnson", "Brown", "Garcia", "Wei", "Ali"],
        "age": [29, 35, 42, 28, 31, 45],
        "occupation": [
            "Data Scientist",
            "Product Manager",
            "Software Engineer",
            "UX Designer",
            "Researcher",
            "Entrepreneur",
        ],
        "location": [
            "San Francisco, CA",
            "New York, NY",
            "Austin, TX",
            "Boston, MA",
            "Seattle, WA",
            "Dubai, UAE",
        ],
        "email": [
            "jane.smith@example.com",
            "alex.johnson@example.com",
            "doe.brown@example.com",
            "maria.garcia@example.com",
            "li.wei@example.com",
            "omar.ali@example.com",
        ],
        "bio": [
            "Data scientist focused on applied ML and visualization.",
            "Product manager with a background in UX and analytics.",
            "Backend engineer specializing in scalable systems.",
            "UX designer crafting human-centered digital experiences.",
            "Researcher working on human-computer interaction.",
            "Founder and operator of several tech startups.",
        ],
        "interests": [
            "hiking, photography, cooking",
            "reading, strategy games, travel",
            "open-source, biking, woodworking",
            "illustration, prototyping, user research",
            "machine learning, teaching, chess",
            "investing, mentoring, sailing",
        ],
        "joined_date": [
            "2019-06-12",
            "2017-09-03",
            "2015-02-18",
            "2020-11-01",
            "2018-04-22",
            "2010-08-30",
        ],
        "followers": [1240, 5400, 2870, 920, 1500, 10300],
        "active": [True, True, True, True, True, False],
    }

    sp.ui.table(_bios_df)
    return


@app.cell(hide_code=True)
def _(sp):
    # Cell 22 (slide) — closing slide.
    sp.md(
        """
        # Thanks!

        Questions?
        """
    ).center()
    return


if __name__ == "__main__":
    app.run()
