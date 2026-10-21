"""Trusted backend bindings; not P5 admission or third-party code isolation."""

import hashlib
import inspect
import json
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

from pydantic import TypeAdapter

from agentguard.contracts.models import Identifier, _json_snapshot

from .schema import canonical, validate_schema

_ID = TypeAdapter(Identifier)
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{prefix}{i}" for prefix in ("COM", "LPT") for i in (*"123456789", "¹", "²", "³")
}


def _check_node(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if (
        stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        or (stat.S_ISREG(info.st_mode) and info.st_nlink > 1)
        or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
    ):
        raise ValueError("Unsafe path")


@dataclass(frozen=True)
class PathRule:
    parameter: str
    resource_id: str
    root: Path = field(repr=False)
    must_exist: bool = True

    def __post_init__(self):
        _ID.validate_python(self.parameter, strict=True)
        _ID.validate_python(self.resource_id, strict=True)
        if type(self.must_exist) is not bool or not isinstance(self.root, Path):
            raise ValueError("Invalid path configuration")
        root = self.root.absolute()
        _check_node(root)
        if not root.is_dir() or root.resolve() != root:
            raise ValueError("Path root must be a canonical directory")
        object.__setattr__(self, "root", root)

    def resolve_argument(self, name):
        if (
            type(name) is not str
            or not name
            or len(name) > 512
            or "\\" in name
            or PureWindowsPath(name).drive
        ):
            raise ValueError("Invalid path")
        parts = name.split("/")
        if any(
            part in {"", ".", ".."}
            or part.endswith((" ", "."))
            or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
            or part.split(".")[0].rstrip(" ").upper() in _RESERVED
            for part in parts
        ):
            raise ValueError("Invalid path")
        _check_node(self.root)
        if self.root.resolve() != self.root:
            raise ValueError("Unsafe path")
        target = self.root
        for part in parts:
            target /= part
            _check_node(target)
        resolved = target.resolve(strict=self.must_exist)
        if not resolved.is_relative_to(self.root):
            raise ValueError("Outside resource root")
        if target.exists() and not target.is_file():
            raise ValueError("Invalid file")
        if not target.parent.is_dir():
            raise ValueError("Invalid parent")
        return str(resolved)


@dataclass(frozen=True, init=False)
class ToolBinding:
    tool_id: str
    name: str
    permissions: tuple[str, ...]
    task_authorizations: tuple[str, ...]
    resources: tuple[str, ...]
    paths: tuple[PathRule, ...]
    requires_review: bool
    metadata_digest: str
    _schema: str = field(repr=False)
    _handler: Callable = field(repr=False)

    def __init__(
        self,
        *,
        tool_id,
        name,
        handler,
        parameters_schema,
        permissions,
        task_authorizations,
        resources=(),
        paths=(),
        requires_review=False,
    ):
        schema = _json_snapshot(parameters_schema, limit=16 * 1024)
        validate_schema(schema)
        if (
            schema["type"] != "object"
            or not callable(handler)
            or inspect.iscoroutinefunction(handler)
            or inspect.isasyncgenfunction(handler)
            or type(requires_review) is not bool
        ):
            raise ValueError("Invalid tool configuration")
        values = dict(
            tool_id=tool_id,
            name=name,
            permissions=tuple(permissions),
            task_authorizations=tuple(task_authorizations),
            resources=tuple(resources),
            paths=tuple(paths),
            requires_review=requires_review,
        )
        for value in (
            tool_id,
            name,
            *values["permissions"],
            *values["task_authorizations"],
            *values["resources"],
        ):
            _ID.validate_python(value, strict=True)
        if not values["permissions"] or not values["task_authorizations"]:
            raise ValueError("Tools require explicit permissions and task authorizations")
        if any(type(rule) is not PathRule for rule in values["paths"]):
            raise ValueError("Invalid path rules")
        if len({p.parameter for p in values["paths"]}) != len(values["paths"]):
            raise ValueError("Duplicate path parameter")
        for rule in values["paths"]:
            if schema.get("properties", {}).get(rule.parameter, {}).get("type") != "string":
                raise ValueError("Path parameter must have a string schema")
            if rule.parameter not in schema.get("required", []):
                raise ValueError("Path parameter must be required")
        digest_data = {
            **values,
            "paths": [
                [p.parameter, p.resource_id, str(p.root), p.must_exist] for p in values["paths"]
            ],
            "parameters_schema": schema,
        }
        for key, value in values.items():
            object.__setattr__(self, key, value)
        object.__setattr__(self, "_schema", canonical(schema))
        object.__setattr__(self, "_handler", handler)
        object.__setattr__(
            self,
            "metadata_digest",
            hashlib.sha256(canonical(digest_data).encode("utf-8")).hexdigest(),
        )

    @property
    def parameters_schema(self):
        return json.loads(self._schema)
