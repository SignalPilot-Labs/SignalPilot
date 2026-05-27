# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.11.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md(r"""# Pandas: Memory Optimization and Type Management""")
    return


@app.cell
def _():
    import pandas as pd

    # Create sample DataFrame with different data types
    df = pd.DataFrame({
        'int_col': range(1000),
        'float_col': [1.5] * 1000,
        'str_col': ['A'] * 1000,
        'category_col': ['A', 'B', 'C'] * 333 + ['A']  # Make it 1000 rows
    })

    # Memory optimization
    df['category_col'] = df['category_col'].astype('category')
    df['int_col'] = df['int_col'].astype('int32')

    # Get memory usage
    memory_usage = df.memory_usage(deep=True)
    dtypes = df.dtypes
    return df, dtypes, memory_usage, pd


@app.cell
def _(memory_usage):
    memory_usage
    return


@app.cell
def _(dtypes):
    dtypes
    return


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
