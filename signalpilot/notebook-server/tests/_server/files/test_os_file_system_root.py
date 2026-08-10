from pathlib import Path

import pytest

from signalpilot._server.files.os_file_system import OSFileSystem
from signalpilot._utils.http import HTTPException


def test_rooted_filesystem_resolves_relative_paths(tmp_path: Path) -> None:
    root = tmp_path / "project"
    notebooks = root / "notebooks"
    notebooks.mkdir(parents=True)
    intro = notebooks / "intro.py"
    intro.write_text("print('ready')\n", encoding="utf-8")
    fs = OSFileSystem(root=str(root))

    details = fs.get_details("notebooks/intro.py")
    assert details.contents == "print('ready')\n"
    assert details.file.path == str(intro.resolve())

    fs.update_file("notebooks/intro.py", "print('updated')\n")
    copied = fs.copy_file_or_directory(
        "notebooks/intro.py",
        "notebooks/copy.py",
    )
    moved = fs.move_file_or_directory(
        "notebooks/copy.py",
        "notebooks/moved.py",
    )
    created = fs.create_file_or_directory(
        "notebooks",
        "file",
        "created.sql",
        b"select 1\n",
    )

    assert fs.open_file("notebooks/intro.py") == "print('updated')\n"
    assert copied.path == str((notebooks / "copy.py").resolve())
    assert moved.path == str((notebooks / "moved.py").resolve())
    assert created.path == str((notebooks / "created.sql").resolve())
    assert {item.name for item in fs.list_files("notebooks")} == {
        "created.sql",
        "intro.py",
        "moved.py",
    }
    assert {item.name for item in fs.search("moved")} == {"moved.py"}
    assert fs.delete_file_or_directory("notebooks/moved.py") is True


@pytest.mark.parametrize(
    "candidate",
    ["../outside.txt", "nested/../../outside.txt"],
)
def test_rooted_filesystem_rejects_relative_escape(
    tmp_path: Path,
    candidate: str,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    fs = OSFileSystem(root=str(root))

    with pytest.raises(HTTPException) as exc_info:
        fs.get_details(candidate)
    assert exc_info.value.detail == "Invalid path: outside the filesystem root"


def test_rooted_filesystem_rejects_absolute_escape(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    fs = OSFileSystem(root=str(root))

    with pytest.raises(HTTPException) as exc_info:
        fs.open_file(str(outside))
    assert exc_info.value.detail == "Invalid path: outside the filesystem root"
