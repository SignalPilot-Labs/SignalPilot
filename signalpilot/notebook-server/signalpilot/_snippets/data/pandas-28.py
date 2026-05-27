# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.11.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md(r"""# Pandas: Pivot Table Operations""")
    return


@app.cell
def _():
    import pandas as pd

    # Create sample DataFrame
    df = pd.DataFrame({
        'date': ['2024-01-01', '2024-01-01', '2024-01-02', '2024-01-02'],
        'category': ['A', 'B', 'A', 'B'],
        'value1': [100, 200, 150, 250],
        'value2': [10, 20, 15, 25]
    })

    # Create pivot table
    pivot_df = pd.pivot_table(
        df,
        index='date',
        columns='category',
        values=['value1', 'value2']
    ).reset_index()

    # Flatten column names for better display
    pivot_df.columns = [f"{col[0]}_{col[1]}" if isinstance(col, tuple) else col
                       for col in pivot_df.columns]

    pivot_df
    return df, pd, pivot_df


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
