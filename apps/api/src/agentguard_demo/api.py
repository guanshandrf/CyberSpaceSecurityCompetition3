"""Local-only unprotected baseline API; enabled explicitly by trusted configuration."""

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from agentguard_demo.providers import make_provider
from agentguard_demo.service import ChatService
from agentguard_demo.settings import DemoSettings


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=4096)


def create_app(settings: DemoSettings | None = None, *, provider=None):
    settings = settings or DemoSettings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        app.state.chat = None
        if settings.enable_baseline:
            selected = provider if provider is not None else make_provider(settings)
            app.state.chat = ChatService(settings, selected)
        yield

    app = FastAPI(title="AgentGuard P1 unprotected local baseline", lifespan=lifespan)

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
        if not settings.enable_baseline or app.state.chat is None:
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
        return {"baseline_enabled": settings.enable_baseline, "guard": "not_implemented"}

    @app.post("/sessions", status_code=201)
    def create_session():
        return {"session_id": service().create_session().session_id, "mode": "unprotected"}

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str):
        _, session = session_or_404(session_id)
        with session.lock:
            return {
                "session_id": session.session_id,
                "turns": session.turns,
                "provider_calls": session.provider_calls,
                "mode": "unprotected",
            }

    @app.post("/sessions/{session_id}/chat")
    def chat(session_id: str, body: ChatRequest):
        chat_service, session = session_or_404(session_id)
        return {"events": list(chat_service.events(session, body.message))}

    @app.post("/sessions/{session_id}/stream")
    def stream(session_id: str, body: ChatRequest):
        chat_service, session = session_or_404(session_id)

        def encode():
            for item in chat_service.events(session, body.message):
                data = json.dumps(item["data"], ensure_ascii=False)
                yield f"event: {item['event']}\ndata: {data}\n\n"

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
