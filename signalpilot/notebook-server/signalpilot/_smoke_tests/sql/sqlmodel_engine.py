# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "altair==5.5.0",
#     "duckdb==1.1.3",
#     "sp",
#     "polars==1.21.0",
#     "psycopg[binary]==3.2.4",
#     "sqlglot==26.3.9",
#     "sqlmodel==0.0.22",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import altair as alt
    import signalpilot
    return (sp,)


@app.cell(hide_code=True)
def _(sp):
    sp.md("""# SQLModel with `sp.sql()`""")
    return


@app.cell
def _():
    from sqlmodel import text, create_engine
    return (create_engine,)


@app.cell(hide_code=True)
def _(sp):
    sp.md("""## sqlite""")
    return


@app.cell
def _(create_engine, sp):
    # Create an in-memory SQLite database
    sqlite = create_engine("sqlite:///:memory:")

    sp.sql("DROP TABLE IF EXISTS products;", engine=sqlite)

    sp.sql(
        """
    CREATE TABLE products (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        price DECIMAL(10,2) NOT NULL,
        category TEXT NOT NULL
    );
    """,
        engine=sqlite,
    )

    sp.sql(
        """
    INSERT INTO products (name, price, category) VALUES
        ('Laptop', 999.99, 'Electronics'),
        ('Coffee Maker', 49.99, 'Appliances'),
        ('Headphones', 79.99, 'Electronics'),
        ('Toaster', 29.99, 'Appliances'),
        ('Smartphone', 599.99, 'Electronics'),
        ('Blender', 39.99, 'Appliances');
    """,
        engine=sqlite,
    )
    return (sqlite,)


@app.cell
def _(sp, sqlite):
    products_df = sp.sql(
        f"""
        SELECT name, price, category
        FROM products
        ORDER BY price DESC
        """,
        engine=sqlite
    )
    return (products_df,)


@app.cell(hide_code=True)
def _(sp):
    sp.md("""### All Products (sorted by price)""")
    return


@app.cell(hide_code=True)
def _(sp, products_df):
    sp.hstack(
        [
            products_df,
            sp.vstack(
                [
                    sp.md("### Summary"),
                    f"Total products: {len(products_df)}",
                    f"Average price: ${products_df['price'].mean():.2f}",
                ]
            ),
        ]
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""### Category Summary""")
    return


@app.cell
def _(sp, sqlite):
    _df = sp.sql(
        f"""
        -- Category summary
        SELECT
            category,
            COUNT(*) as count,
            ROUND(AVG(price), 2) as avg_price,
            ROUND(MIN(price), 2) as min_price,
            ROUND(MAX(price), 2) as max_price
        FROM products
        GROUP BY category
        ORDER BY avg_price DESC
        """,
        engine=sqlite
    )
    return


@app.cell(hide_code=True)
def _(sp):
    # Interactive price filter
    price_threshold = sp.ui.slider(
        start=0, stop=1000, value=100, label="Max Price $"
    )
    sp.md(f"### Products under {price_threshold}")
    return (price_threshold,)


@app.cell
def _(sp, price_threshold, sqlite):
    _df = sp.sql(
        f"""
        SELECT name, price, category
        FROM products
        WHERE price < {price_threshold.value}
        ORDER BY price DESC
        """,
        engine=sqlite
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""## postgresql""")
    return


@app.cell
def _(sp):
    import os

    psql_url = sp.ui.text(
        kind="password",
        label="PostgreSQL URL",
        placeholder="postgresql://",
        value=os.getenv("POSTGRES_URL") or "",
    )
    psql_url
    return (psql_url,)


@app.cell
def _(create_engine, sp, psql_url):
    sp.stop(not psql_url.value)

    normalized_url = psql_url.value.replace(
        "postgres://", "postgresql+psycopg://"
    ).replace("postgresql://", "postgresql+psycopg://")

    # Create a PostgreSQL database
    my_postgres = create_engine(normalized_url)
    return (my_postgres,)


@app.cell
def _(sp, my_postgres):
    _df = sp.sql(
        f"""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public';
        """,
        engine=my_postgres
    )
    return


@app.cell
def _(connection, sp):
    _df = sp.sql(
        f"""
        SELECT 1
        """,
        engine=connection
    )
    return


@app.cell
def _(sp, sqlite):
    _df = sp.sql(
        f"""
        SELECT * FROM products LIMIT 100
        """,
        engine=sqlite
    )
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        CREATE OR REPLACE TABLE foo AS
        FROM 'hf://datasets/julien040/hacker-news-posts/story.parquet' LIMIT 500
        """
    )
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT "id" FROM memory.main.foo LIMIT 100
        """
    )
    return


if __name__ == "__main__":
    app.run()
