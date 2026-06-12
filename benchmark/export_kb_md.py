"""Export KB entries from JSON to individual markdown files."""
import json
import sys
from pathlib import Path


def export_kb(json_path: str, output_dir: str) -> None:
    entries = json.loads(Path(json_path).read_text())
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for entry in entries:
        title = entry["title"]
        fname = title.replace(" ", "-").replace("/", "-").replace(":", "-")[:80] + ".md"
        body = (
            f"# {title}\n\n"
            f"- **scope**: {entry['scope']}\n"
            f"- **scope_ref**: {entry.get('scope_ref', '')}\n"
            f"- **category**: {entry['category']}\n"
            f"- **created_at**: {entry['created_at']}\n\n"
            f"---\n\n"
            f"{entry['body']}\n"
        )
        (out / fname).write_text(body)

    print(f"{len(entries)} entries written to {output_dir}/")


if __name__ == "__main__":
    export_kb(sys.argv[1], sys.argv[2])
