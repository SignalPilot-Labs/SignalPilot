
import signalpilot

__generated_with = "0.18.4"
app = sp.App(width="full")


@app.cell
def _():
    import signalpilot
    import requests
    import io
    return io, sp, requests


@app.cell
def _(sp):
    sp.md("""
    # PDFs
    """)
    return


@app.cell
def _(sp):
    page = sp.ui.number(1, 10, label="Starting page number")
    page
    return (page,)


@app.cell
def _(sp, page):
    sp.pdf(
        src="https://arxiv.org/pdf/2104.00282.pdf",
        initial_page=page.value,
        width="100%",
        height="60vh",
    )
    return


@app.cell
def _(io, sp, page, requests):
    downloaded = requests.get("https://arxiv.org/pdf/2104.00282.pdf")
    # This is still performant as it does not pass the full PDF to the frontend,
    # and instead creates a VirtualFile
    pdf = sp.pdf(
        src=io.BytesIO(downloaded.content),
        initial_page=page.value,
        width="100%",
        height="60vh",
    )
    pdf
    return (pdf,)


@app.cell
def _(pdf):
    pdf
    return


if __name__ == "__main__":
    app.run()
