"""Local-only unprotected baseline API; enabled explicitly by trusted configuration."""

import json
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from agentguard_demo.providers import make_provider
from agentguard_demo.service import ChatService
from agentguard_demo.settings import DemoSettings


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=4096)


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: Literal["fake", "deepseek"]


def create_app(settings: DemoSettings | None = None, *, provider=None):
    settings = settings or DemoSettings.from_env()
    mode = "protected" if settings.enable_protection else "unprotected"

    @asynccontextmanager
    async def lifespan(app):
        app.state.chat = None
        if settings.enable_baseline or settings.enable_protection:
            providers = None
            if settings.enable_model_selection:
                providers = {
                    "fake": make_provider(
                        settings.model_copy(update={"provider": "fake", "enable_real_api": False})
                    )
                }
                if settings.enable_real_api and settings.api_key.get_secret_value():
                    providers["deepseek"] = make_provider(
                        settings.model_copy(update={"provider": "deepseek"})
                    )
                selected = provider if provider is not None else providers[settings.provider]
                providers[settings.provider] = selected
            else:
                selected = provider if provider is not None else make_provider(settings)
            app.state.chat = ChatService(settings, selected, providers=providers)
        yield

    app = FastAPI(title="AgentGuard local demonstration", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        # No cross-site mutation on an unauthenticated local demo (including SSE POST).
        origin = request.headers.get("origin")
        if request.method == "POST" and origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse(status_code=403, content={"detail": "Cross-origin request denied"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Do not reflect raw request values, including accidentally submitted secrets.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": list(error["loc"]), "type": error["type"]} for error in exc.errors()
                ]
            },
        )

    def service():
        if not (settings.enable_baseline or settings.enable_protection) or app.state.chat is None:
            raise HTTPException(503, "Unprotected baseline is disabled")
        return app.state.chat

    def session_or_404(session_id):
        chat = service()
        session = chat.get_session(session_id)
        if session is None:
            raise HTTPException(404, "Unknown session")
        return chat, session

    @app.get("/health")
    def health():
        if settings.enable_protection:
            return {"baseline_enabled": False, "guard": "enabled", "mode": "protected"}
        return {"baseline_enabled": settings.enable_baseline, "guard": "not_implemented"}

    @app.get("/models")
    def models():
        chat = service()
        available = set(chat.providers)
        return {
            "default_provider": settings.provider,
            "selectable": settings.enable_model_selection,
            "models": [
                {"id": name, "available": name in available} for name in ("fake", "deepseek")
            ],
            "limits": {
                "max_output_tokens": settings.max_tokens,
                "max_total_calls": settings.max_total_provider_calls,
                "used_calls": chat.total_provider_calls,
            },
        }

    @app.post("/sessions", status_code=201)
    def create_session(body: SessionRequest | None = None):
        chat = service()
        if body is not None and (
            not settings.enable_model_selection or body.provider not in chat.providers
        ):
            raise HTTPException(403, "Model is not enabled by the backend")
        session = chat.create_session(body.provider if body is not None else None)
        return {"session_id": session.session_id, "mode": mode, "provider": session.provider_name}

    def history_service():
        chat = service()
        if not settings.enable_protection:
            raise HTTPException(409, "Audit history requires protected server mode")
        return chat

    @app.get("/sessions")
    def list_sessions():
        chat = history_service()
        return {
            "sessions": [
                {**s, "active": chat.get_session(s["session_id"]) is not None, "mode": "protected"}
                for s in chat.audit.history.sessions()
            ]
        }

    @app.get("/sessions/{session_id}/history")
    @app.get("/sessions/{session_id}/audit")
    def history(
        request: Request,
        session_id: str,
        after: int = Query(0, ge=0, le=2**63 - 1),
        limit: int = Query(200, ge=1, le=200),
    ):
        chat = history_service()
        if not chat.audit.history.exists(session_id):
            raise HTTPException(404, "Unknown session")
        records = chat.audit.history.events(
            session_id, after=after, limit=limit, audit_only=request.url.path.endswith("/audit")
        )
        return {
            "events": records,
            "next_after": records[-1]["sequence"] if records else after,
            "active": chat.get_session(session_id) is not None,
            "mode": "protected",
            "provider": (
                chat.get_session(session_id).provider_name
                if chat.get_session(session_id) is not None
                else None
            ),
        }

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str):
        _, session = session_or_404(session_id)
        with session.lock:
            return {
                "session_id": session.session_id,
                "turns": session.turns,
                "provider_calls": session.provider_calls,
                "mode": mode,
            }

    @app.post("/sessions/{session_id}/chat")
    def chat(session_id: str, body: ChatRequest):
        chat_service, session = session_or_404(session_id)
        return {"events": list(chat_service.client_events(session, body.message))}

    @app.post("/sessions/{session_id}/stream")
    def stream(session_id: str, body: ChatRequest):
        chat_service, session = session_or_404(session_id)

        def encode():
            for item in chat_service.client_events(session, body.message):
                data = json.dumps(item["data"], ensure_ascii=False)
                sequence = f"id: {item['sequence']}\n" if "sequence" in item else ""
                yield f"{sequence}event: {item['event']}\ndata: {data}\n\n"

        return StreamingResponse(
            encode(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return app


app = create_app()
