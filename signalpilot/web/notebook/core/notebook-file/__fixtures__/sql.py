import signalpilot as sp

__generated_with = "0.1.0"
app = sp.App()


@app.cell
def _(my_table, sp):
    df = sp.sql(
        f"""
        SELECT *
        FROM my_table
        LIMIT 10
        """
    )
    return


if __name__ == "__main__":
    app.run()
