# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _(sp):
    sp.ui.code_editor("print(2 + 2)", min_height=50)
    return


@app.cell
def _(sp):
    sp.ui.code_editor("SELECT * FROM table;", language="sql", theme="light")
    return


@app.cell(hide_code=True)
def _(languages, sp):
    language_select = sp.ui.dropdown(
        languages,
        value="javascript",
        label="Language",
        full_width=True,
    )
    theme_select = sp.ui.radio(["light", "dark"], value="dark", label="Theme")
    sp.hstack([language_select, theme_select], justify="start", gap=2)
    return language_select, theme_select


@app.cell
def _(language_select, sp, samples, theme_select):
    sp.ui.code_editor(
        samples[language_select.value],
        language=language_select.value,
        theme=theme_select.value,
    )
    return


@app.cell
def _():
    languages = ["sql", "python", "javascript", "ruby", "c", "java", "go"]
    samples = {
        "sql": "SELECT * FROM table;",
        "python": "print(2 + 2)",
        "javascript": "console.log(2 + 2)",
        "ruby": "puts 2 + 2",
        "c": 'printf("%d", 2 + 2);',
        "c++": "cout << 2 + 2 << endl;",
        "c#": "Console.WriteLine(2 + 2);",
        "java": "System.out.println(2 + 2);",
        "go": "fmt.Println(2 + 2)",
    }
    return languages, samples


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
