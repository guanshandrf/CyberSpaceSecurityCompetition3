"""Tools' own local sandbox, NOT Gate/Policy/Guarded Executor enforcement."""

import json
import os
import stat
from pathlib import Path, PureWindowsPath

from langchain_core.tools import tool

READ_LIMIT = 64 * 1024
WRITE_LIMIT = 16 * 1024
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)
}


class SandboxError(ValueError):
    pass


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


class SandboxTools:
    def __init__(self, read_root: Path, write_root: Path):
        # These roots are trusted server configuration, never model arguments.
        base = Path(os.path.commonpath([read_root.absolute(), write_root.absolute()]))
        if _is_link(base):
            raise SandboxError("sandbox_link")
        base.mkdir(parents=True, exist_ok=True)
        for root in (read_root, write_root):
            current = base
            for part in root.absolute().relative_to(base).parts:
                current = current / part
                if _is_link(current):
                    raise SandboxError("sandbox_link")
                current.mkdir(exist_ok=True)
        self.read_root = read_root.resolve()
        self.write_root = write_root.resolve()

    def _target(self, root: Path, name: str, *, leaf_only=False) -> Path:
        if not name or len(name) > 512 or "\\" in name or PureWindowsPath(name).drive:
            raise SandboxError("invalid_path")
        parts = name.split("/")
        if leaf_only and len(parts) != 1:
            raise SandboxError("invalid_path")
        if any(
            part in {"", ".", ".."}
            or part.endswith((" ", "."))
            or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
            or part.split(".")[0].upper() in RESERVED
            for part in parts
        ):
            raise SandboxError("invalid_path")
        current = root
        for part in parts:
            current = current / part
            if _is_link(current):
                raise SandboxError("sandbox_link")
        if not current.resolve().is_relative_to(root):
            raise SandboxError("outside_sandbox")
        return current

    def read_file(self, path: str) -> dict:
        target = self._target(self.read_root, path)
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_BINARY", 0)
        )
        with os.fdopen(os.open(target, flags), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > READ_LIMIT:
                raise SandboxError("invalid_file")
            content = stream.read(READ_LIMIT + 1)
        if len(content) > READ_LIMIT:
            raise SandboxError("file_too_large")
        text = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        return {"ok": True, "content": text}

    def write_note(self, name: str, content: str) -> dict:
        target = self._target(self.write_root, name, leaf_only=True)
        encoded = content.encode("utf-8")
        if len(encoded) > WRITE_LIMIT:
            raise SandboxError("note_too_large")
        # Exclusive creation also rejects existing hard links and never overwrites.
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0)
        )
        with os.fdopen(os.open(target, flags, 0o600), "wb") as stream:
            stream.write(encoded)
        return {"ok": True, "name": name, "bytes": len(encoded)}

    def as_tools(self):
        @tool
        def read_file(path: str) -> str:
            """Read a bounded UTF-8 file relative to the server's read-only input sandbox."""
            return json.dumps(self.read_file(path), ensure_ascii=False)

        @tool
        def write_note(name: str, content: str) -> str:
            """Create a new bounded note by filename in this session's notes directory."""
            return json.dumps(self.write_note(name, content), ensure_ascii=False)

        return [read_file, write_note]
