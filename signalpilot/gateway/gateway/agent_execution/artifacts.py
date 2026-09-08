"""Bounded archive validation and portable text patches. Never extract on the gateway."""
import difflib
import io
import tarfile

from gateway.workspace_store.paths import confine_relpath

MAX_BYTES = 32 * 1024 * 1024
MAX_FILES = 2000
EXCLUDED = {".git", ".claude", ".mcp.json", ".env", "node_modules", ".venv", "target", "logs", "dbt_packages"}


def read_archive(data: bytes) -> dict[str, bytes]:
    if len(data) > MAX_BYTES:
        raise ValueError("Project archive exceeds 32 MiB")
    files = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        seen = set()
        for index, item in enumerate(archive):
            if index >= MAX_FILES * 2:
                raise ValueError("Archive contains too many entries")
            path = confine_relpath(item.name)
            if any(ord(c) < 32 or ord(c) == 127 for c in path):
                raise ValueError("Control characters in archive paths are unsupported")
            if path in seen:
                raise ValueError("Archive contains duplicate paths")
            seen.add(path)
            if item.isdir():
                continue
            if not item.isfile() or path in files:
                raise ValueError("Archive contains links, special files, or duplicate paths")
            if any(part in EXCLUDED or part.startswith(".env.") for part in path.split("/")):
                continue
            total += item.size
            if total > MAX_BYTES or len(files) >= MAX_FILES:
                raise ValueError("Project exceeds file or byte limit")
            handle = archive.extractfile(item)
            if handle is None:
                raise ValueError("Unreadable archive entry")
            files[path] = handle.read()
    return files


def pack(files: dict[str, bytes]) -> bytes:
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w:gz") as archive:
        for path, data in sorted(files.items()):
            info = tarfile.TarInfo(confine_relpath(path))
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    return result.getvalue()


def patch(before: dict[str, bytes], after: dict[str, bytes]) -> tuple[list[str], bytes]:
    changed = [p for p in sorted(before.keys() | after.keys()) if before.get(p) != after.get(p)]
    chunks = []
    for path in changed:
        try:
            old = before.get(path, b"").decode("utf-8")
            new = after.get(path, b"").decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Agent changed a binary file; patch cannot be published") from exc
        if "\x00" in old or "\x00" in new:
            raise ValueError("Binary file changes are unsupported")
        lines = difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile="a/" + path if path in before else "/dev/null",
            tofile="b/" + path if path in after else "/dev/null")
        for line in lines:
            chunks.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    output = "".join(chunks).encode()
    if len(output) > MAX_BYTES:
        raise ValueError("Patch exceeds limit")
    return changed, output
