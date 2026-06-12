import signalpilot

__generated_with = "0.11.0"
app = sp.App(width="medium")


@app.cell(hide_code=True)
def _(sp):
    sp.md(
        r"""
        # OpenAI: Prompt with Streaming Response

        Prompt OpenAI or any OpenAI-compatible endpoint and stream the response back.
        """
    )
    return


@app.cell
def _():
    from openai import OpenAI
    return (OpenAI,)


@app.cell
def _(sp):
    api_key = sp.ui.text(label="API Key", kind="password")
    api_key
    return (api_key,)


@app.cell
def _(OpenAI, api_key):
    client = OpenAI(
        api_key=api_key.value,
        # Change this if you are using a different OpenAI-compatible endpoint.
        # base_url="https://api.openai.com/v1",
    )

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {
                "role": "user",
                "content": "Write a haiku about recursion in programming.",
            },
        ],
        stream=True,
    )
    completion
    return client, completion


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
