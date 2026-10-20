import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.p1


@pytest.fixture
def tools(tmp_path):
    from agentguard_demo.tools import SandboxTools

    return SandboxTools(tmp_path / "input", tmp_path / "notes")


def test_read_is_utf8_bounded_and_does_not_change_source(tools):
    source = tools.read_root / "hello.txt"
    source.write_text("你好\nworld", encoding="utf-8")
    before = source.read_bytes()
    assert tools.read_file("hello.txt") == {"ok": True, "content": "你好\nworld"}
    assert source.read_bytes() == before


def test_write_creates_only_a_new_note_and_never_overwrites(tools):
    result = tools.write_note("new.txt", "你好")
    assert result == {"ok": True, "name": "new.txt", "bytes": 6}
    with pytest.raises(FileExistsError):
        tools.write_note("new.txt", "replacement")
    assert (tools.write_root / "new.txt").read_text(encoding="utf-8") == "你好"
    assert list(tools.read_root.iterdir()) == []


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "/absolute.txt",
        "C:/outside.txt",
        "C:relative.txt",
        "\\\\host\\share",
        "sub/../../escape.txt",
        "a\\b.txt",
        "",
        ".",
        "..",
        "a//b",
        "note.txt:stream",
        "CON",
        "nul.txt",
        "COM1.txt",
        "trailing.",
        "trailing ",
        "bad\x00.txt",
    ],
)
def test_read_and_write_reject_unsafe_paths_without_side_effects(tools, name):
    from agentguard_demo.tools import SandboxError

    with pytest.raises(SandboxError):
        tools.read_file(name)
    with pytest.raises(SandboxError):
        tools.write_note(name, "never")
    assert list(tools.read_root.iterdir()) == list(tools.write_root.iterdir()) == []


def test_write_rejects_subdirectories_and_oversize_content(tools):
    from agentguard_demo.tools import WRITE_LIMIT, SandboxError

    for name, content in [("nested/new.txt", "x"), ("big.txt", "x" * (WRITE_LIMIT + 1))]:
        with pytest.raises(SandboxError):
            tools.write_note(name, content)
    assert list(tools.write_root.iterdir()) == []


def test_read_rejects_oversize_binary_and_directory(tools):
    from agentguard_demo.tools import READ_LIMIT

    (tools.read_root / "big.txt").write_bytes(b"x" * (READ_LIMIT + 1))
    (tools.read_root / "binary.txt").write_bytes(b"\xff")
    (tools.read_root / "directory").mkdir()
    for name in ["big.txt", "binary.txt", "directory", "missing.txt"]:
        with pytest.raises((ValueError, OSError)):
            tools.read_file(name)


def make_directory_link(link: Path, destination: Path):
    # All link endpoints are isolated fixtures inside the repository, never real private files.
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(destination)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, "Could not create controlled junction fixture"
    else:
        link.symlink_to(destination, target_is_directory=True)


def test_read_rejects_real_directory_link_escape(tools, tmp_path):
    from agentguard_demo.tools import SandboxError

    outside = tmp_path / "outside-fixture"
    outside.mkdir()
    (outside / "private.txt").write_text("fixture-only")
    make_directory_link(tools.read_root / "alias", outside)
    with pytest.raises(SandboxError):
        tools.read_file("alias/private.txt")


def test_sandbox_initialization_rejects_linked_write_parent_before_creating_child(tmp_path):
    from agentguard_demo.tools import SandboxError, SandboxTools

    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside-fixture"
    outside.mkdir()
    make_directory_link(base / "notes", outside)
    with pytest.raises(SandboxError):
        SandboxTools(base / "input", base / "notes" / "session")
    assert list(outside.iterdir()) == []


def test_existing_hardlink_cannot_be_overwritten(tools, tmp_path):
    source = tmp_path / "outside-fixture.txt"
    source.write_text("original")
    os.link(source, tools.write_root / "alias.txt")
    with pytest.raises(FileExistsError):
        tools.write_note("alias.txt", "replacement")
    assert source.read_text() == "original"
