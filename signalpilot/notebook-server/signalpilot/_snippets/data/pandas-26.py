
import signalpilot

__generated_with = "0.11.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md(r"""# Pandas: Memory Optimization with Category Type""")
    return


@app.cell
def _():
    import pandas as pd

    # Create sample DataFrame
    df = pd.DataFrame({
        'id': range(1000),
        'status': ['active', 'inactive', 'pending'] * 333 + ['active'],
        'category': ['A', 'B', 'C', 'D'] * 250
    })

    # Convert string columns to category
    # Refer: https://pandas.pydata.org/pandas-docs/stable/user_guide/categorical.html
    df['status'] = df['status'].astype('category')
    df['category'] = df['category'].astype('category')

    df.dtypes
    return df, pd


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
