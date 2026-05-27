---
title: Markdown
sp-version: 0.13.2
author: SignalPilot Team
description: >-
  Markdown is a lightweight markup language with plain text formatting syntax. `sp`
  notebooks can be stored as markdown files, allowing you to work on prose-heavy notebooks
  in your editor of choice.
pyproject: |-
  requires-python = ">=3.12"
  dependencies = [
      "sp",
      "duckdb==1.2.2",
      "matplotlib==3.10.1",
      "sqlglot==26.16.2",
  ]
---

# Markdown file format

By default, sp notebooks are stored as pure Python files. However,
you can also store and edit sp notebooks as `.md` files, letting you
work on prose-heavy sp notebooks in your editor of choice.

_Make sure to look at the markdown
[source code](https://github.com/signalpilot-team/sp/blob/main/sp/_tutorials/markdown_format.md)
of this tutorial!_

## Running markdown notebooks

To edit a markdown notebook, use

```bash
$ sp edit notebook.md
```

To run it as an app, use

```bash
$ sp run notebook.md
```
<!---->
## Exporting from Python

You can export sp notebooks that are stored as Python to the markdown format
by running the following command:

```bash
$ sp export md notebook.py > notebook.md
```
<!---->
## Creating Python cells

When you do need to create a Python cell in the markdown format, you can use a
special code block:

````md
```python {.sp}
import matplotlib.pyplot as plt
plt.plot([1, 2, 3, 4])
```
````

This will create the following cell:

```python {.sp}
import matplotlib.pyplot as plt

plt.plot([1, 2, 3, 4])
plt.gca()
```

As long as your code block contains the word `sp` in a brace, like
`{sp}`, or `{.sp note="Whatever you want"}`, sp will treat it as a Python cell.

## `mo` tricks and tips

You can break up markdown into multiple cells by using an empty html tag `<!---->`:
<!---->
View the source of this notebook to see how this cell was created.
<!---->
You can still hide cell code in markdown notebooks:

````md
```python {.sp hide_code="true"}
form = (
    # ...
    # Just something a bit more complicated
    # you might not want to see in the editor.
    # ...
)
form
```
````

```python {.sp hide_code="true"}
form = (
    sp.md('''
    **Just how great is markdown?.**

    {markdown_is_awesome}

    {signalpilot_is_amazing}
''')
    .batch(
        markdown_is_awesome=sp.ui.text(label="How much do you like markdown?", placeholder="It is pretty swell 🌊"),
        signalpilot_is_amazing=sp.ui.slider(label="How much do you like sp?", start=0, stop=11, value=11),
    )
    .form(show_clear_button=True, bordered=False)
)
form
```

and disable cells too:

````md
```python {.sp disabled="true"}
print("This code cell is disabled, there should be no output!")
```
````

```python {.sp disabled="true"}
print("This code cell is disabled, there should be no output!")
```

Additionally, sp knows when your code has a syntax issue:

````md
```python {.sp}
print("This code cell has a syntax error"
```
````

and on notebook save, will annotate the cell for you:

````md
```python {.sp unparseable="true"}
print("This code cell has a syntax error"
```
````

```python {.sp unparsable="true"}
print("This code cell has a syntax error"
```

## Limitations of the markdown format

sp's markdown support treats markdown as just plain old markdown. This
means that trying to use string interpolation (like this `f"{'🍃' * 7}"`) will
just give you the raw string. This lets you clearly delineate what values are
supposed to be computed, and what values are static. To interpolate Python
values, just use a Python cell:

```python {.sp}
sp.md(f"""Like so: {"🍃" * 7}""")
```

`````python {.sp hide_code="true"}
sp.md(r"""
### Limitations on conversion

Whenever you try to implement a cell block like this:

````md
```python {.sp}
sp.md("This is a markdown cell")
```
````

The markdown format will know to automatically keep this as markdown. However,
some ambiguous cases can't be converted to markdown like this:
""")
`````

````python {.sp}
sp.md("""
This is a markdown cell with an execution block in it
```python {.sp}
# Too ambiguous to convert
```
""")
````

It's not likely that you'll run into this issue, but rest assured that sp
is working behind the scenes to keep your notebooks unambiguous and clean as
possible.
<!---->
### Saving multicolumn mode

Multicolumn mode works, but the first cell in a column must be a python cell in
order to specify column start and to save correctly:

````md
```python {.sp column="1"}
print("First cell in column 1")
```
````
<!---->
### Naming cells

Since the markdown notebook really is just markdown, you can't import from a
markdown notebook cells like you can in a python notebook; but you can still
give your cells a name:

````md
```python {.sp name="maybe"}
# 🎵 Hey, I just met you, and this is crazy
```
````

```python {.sp name="maybe"}
# But here's my `cell_id`, so call me, `maybe` 🎶
```

### SQL in markdown

You can also run SQL queries in markdown cells through sp, using a `sql` code block. For instance:

````md
```sql {.sp}
SELECT GREATEST(x, y), SQRT(z) from uniformly_random_numbers
```
````

The resultant distribution may be surprising! 🎲[^surprise]

[^surprise]: The general distributions should be the same

```sql {.sp}
SELECT GREATEST(a, b), SQRT(c) from uniformly_random_numbers
```

In this SQL format, Python variable interpolation in SQL queries occurs automatically. Additionally, query results can be assigned to a dataframe with the `query` attribute.
For instance, here's how to create a random uniform distribution and assign it to the dataframe `uniformly_random_numbers` used above:

````md
```sql {.sp query="uniformly_random_numbers" hide_output="true"}
SELECT i.range::text AS id,
       random() AS x,
       random() AS y,
       random() AS z
FROM
    -- Note sample_count comes from the slider below!
    range(1, {sample_count.value + 1}) i;
```
````

You can learn more about other SQL use in the SQL tutorial (`sp tutorial sql`)

```python {.sp hide_code="true"}
sample_count = sp.ui.slider(1, 1000, value=1000, label="Sample Count")
sample_count
```

```sql {.sp query="uniformly_random_numbers" hide_output="True"}
SELECT i.range::text AS id,
       random() AS a,
       random() AS b,
       random() AS c
FROM range(1, {sample_count.value + 1}) i;
```

## Converting back to the Python file format

The markdown format is supposed to lower the barrier for writing text heavy
documents, it's not meant to be a full replacement for the Python notebook
format. You can always convert back to a Python notebook if you need to:

```bash
$ sp convert my_signalpilot.md > my_signalpilot.py
```
<!---->
## More on markdown

Be sure to checkout the markdown.py tutorial (`sp tutorial markdown`) for
more information on to type-set and render markdown in sp.

```python {.sp hide_code="true"}
import sp
```