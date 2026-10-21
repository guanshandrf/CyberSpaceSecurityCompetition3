"""Optional public SDK integration, imported only for server-enabled protection."""

from pathlib import Path

from agentguard.adapters.langgraph import protect
from agentguard.audit import SQLiteAudit
from agentguard.contracts import SecurityContext
from agentguard.detectors import Redactor
from agentguard.policies import PathRule, ToolBinding
from agentguard_demo.history import HistoryStore, PresentationAudit
from agentguard_demo.tools import SandboxTools


def protected_session(settings, session_id, *, audit):
    base = settings.sandbox_root
    sandbox = SandboxTools(base / "input", base / "notes" / session_id)

    def read_file(path):
        return sandbox.read_file(Path(path).relative_to(sandbox.read_root).as_posix())

    def write_note(name, content):
        return sandbox.write_note(Path(name).relative_to(sandbox.write_root).as_posix(), content)

    def schema(**properties):
        return {
            "type": "object",
            "properties": {
                key: {"type": "string", "maxLength": length} for key, length in properties.items()
            },
            "required": list(properties),
            "additionalProperties": False,
        }

    bindings = [
        ToolBinding(
            tool_id="demo.read",
            name="read_file",
            handler=read_file,
            parameters_schema=schema(path=512),
            permissions=("file.read",),
            task_authorizations=("task.demo",),
            paths=(PathRule("path", "input", sandbox.read_root, must_exist=True),),
        ),
        ToolBinding(
            tool_id="demo.write",
            name="write_note",
            handler=write_note,
            parameters_schema=schema(name=512, content=16000),
            permissions=("note.write",),
            task_authorizations=("task.demo",),
            paths=(PathRule("name", "notes", sandbox.write_root, must_exist=False),),
        ),
    ]
    common = dict(
        schema_version="1.0",
        user_id="local.demo",
        session_id=session_id,
        task_authorization="task.demo",
        allowed_resources=("input", "notes"),
        budget={"max_calls": settings.max_tool_calls, "calls_used": 0},
    )
    context = SecurityContext.from_backend(
        **common, context_id="context." + session_id, permissions=settings.guard_permissions
    )
    admin = SecurityContext.from_backend(
        **common,
        context_id="catalog." + session_id,
        permissions=("tool.register", "file.read", "note.write"),
    )
    return protect(
        bindings,
        descriptions={
            "read_file": "Read a bounded UTF-8 file in the input sandbox.",
            "write_note": "Create a new bounded note in this session's notes directory.",
        },
        context=context,
        registration_context=admin,
        audit=audit,
    )


def make_audit(settings):
    settings.sandbox_root.mkdir(parents=True, exist_ok=True)
    path = PathRule("audit", "audit", settings.sandbox_root, must_exist=False).resolve_argument(
        "audit.sqlite"
    )
    ui_path = PathRule(
        "history", "history", settings.sandbox_root, must_exist=False
    ).resolve_argument("history.sqlite")
    secret = settings.api_key.get_secret_value()
    redactor = Redactor(secrets=(secret,) if secret else ())
    return PresentationAudit(
        SQLiteAudit(Path(path)), HistoryStore(Path(ui_path), redact=redactor.redact)
    )


def refresh_protected_session(settings, session_id, adapter):
    """Current local catalog authority, obtained by backend code on each turn."""
    admin = SecurityContext.from_backend(
        schema_version="1.0",
        context_id="catalog." + session_id,
        user_id="local.demo",
        session_id=session_id,
        task_authorization="task.demo",
        allowed_resources=("input", "notes"),
        permissions=("tool.register", "file.read", "note.write"),
        budget={"max_calls": settings.max_tool_calls, "calls_used": 0},
    )
    return adapter.refresh_registrations(admin)
