# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.11.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md(r"""# Pandas: Boolean Indexing and Filtering""")
    return


@app.cell
def _():
    import pandas as pd

    # Create sample DataFrame
    df = pd.DataFrame({
        'name': ['Alice', 'Bob', 'Charlie', 'David', 'Eve'],
        'age': [25, 30, 35, 28, 22],
        'salary': [50000, 60000, 75000, 62000, 45000],
        'department': ['IT', 'HR', 'IT', 'Finance', 'HR']
    })

    # Multiple boolean conditions
    mask = (df['age'] > 25) & (df['salary'] > 60000)
    filtered_df = df[mask]

    filtered_df
    return df, filtered_df, mask, pd


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
