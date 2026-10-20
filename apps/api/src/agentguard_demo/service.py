"""Real LangGraph baseline loop with process-local sessions and node event streaming."""

import json
from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langsmith import tracing_context

from agentguard_demo.settings import DemoSettings
from agentguard_demo.tools import SandboxTools


class ProviderFailure(RuntimeError):
    pass


class CallLimit(RuntimeError):
    pass


@dataclass
class Session:
    session_id: str
    messages: list = field(default_factory=list)
    provider_calls: int = 0
    turns: int = 0
    lock: object = field(default_factory=Lock)


class ChatService:
    def __init__(self, settings: DemoSettings, provider):
        self.settings = settings
        self.provider = provider
        self.sessions: dict[str, Session] = {}
        self.lock = Lock()
        self.total_provider_calls = 0

    def create_session(self):
        session = Session(uuid4().hex)
        with self.lock:
            self.sessions[session.session_id] = session
        return session

    def get_session(self, session_id):
        with self.lock:
            return self.sessions.get(session_id)

    def _graph(self, session, tools):
        bound = self.provider.bind_tools(tools)
        by_name = {item.name: item for item in tools}
        tool_count = 0

        def model_node(state):
            if session.provider_calls >= self.settings.max_provider_calls:
                raise CallLimit("provider_call_limit")
            with self.lock:
                if self.total_provider_calls >= self.settings.max_total_provider_calls:
                    raise CallLimit("total_provider_call_limit")
                self.total_provider_calls += 1
                session.provider_calls += 1
            try:
                response = bound.invoke(
                    [
                        SystemMessage(
                            content="You are an unprotected local demo. Use only supplied tools."
                        ),
                        *state["messages"],
                    ],
                    config={"callbacks": []},
                )
            except Exception:
                # Do not expose provider errors, request headers or keys to clients/logs.
                raise ProviderFailure("provider_error") from None
            return {"messages": [response]}

        def tools_node(state):
            nonlocal tool_count
            results = []
            for call in state["messages"][-1].tool_calls:
                if tool_count >= 4:
                    raise CallLimit("tool_call_limit")
                tool_count += 1
                selected = by_name.get(call["name"])
                try:
                    if selected is None:
                        content = json.dumps({"ok": False, "error": "unknown_tool"})
                    else:
                        content = selected.invoke(call["args"])
                except Exception:
                    content = json.dumps({"ok": False, "error": "tool_error"})
                results.append(
                    ToolMessage(content=content, tool_call_id=call["id"], name=call["name"])
                )
            return {"messages": results}

        graph = StateGraph(MessagesState)
        graph.add_node("model", model_node)
        graph.add_node("tools", tools_node)
        graph.add_edge(START, "model")
        graph.add_conditional_edges(
            "model", lambda state: "tools" if state["messages"][-1].tool_calls else END
        )
        graph.add_edge("tools", "model")
        return graph.compile()

    def events(self, session: Session, content: str):
        # A plain Lock may be released on another worker when a sync stream resumes.
        with session.lock:
            session.turns += 1
            trace_id = uuid4().hex
            common = {"session_id": session.session_id, "trace_id": trace_id, "turn": session.turns}

            def event(kind, **data):
                return {"event": kind, "data": {**common, **data}}

            yield event("session", mode="unprotected", provider=self.settings.provider)
            session.messages.append(HumanMessage(content=content))
            try:
                base = self.settings.sandbox_root
                tools = SandboxTools(base / "input", base / "notes" / session.session_id).as_tools()
                graph = self._graph(session, tools)
                with tracing_context(enabled=False):
                    for update in graph.stream(
                        {"messages": list(session.messages)},
                        config={"recursion_limit": 12},
                        stream_mode="updates",
                    ):
                        for state in update.values():
                            for message in state["messages"]:
                                session.messages.append(message)
                                if isinstance(message, AIMessage):
                                    for call in message.tool_calls:
                                        yield event(
                                            "tool_call",
                                            tool_call_id=call["id"],
                                            name=call["name"],
                                            arguments=call["args"],
                                        )
                                    if not message.tool_calls:
                                        yield event("message", content=message.content)
                                elif isinstance(message, ToolMessage):
                                    yield event(
                                        "tool_result",
                                        tool_call_id=message.tool_call_id,
                                        name=message.name,
                                        result=json.loads(message.content),
                                    )
            except CallLimit as exc:
                yield event("error", code=str(exc))
                yield event("done", ok=False)
                return
            except ProviderFailure:
                yield event("error", code="provider_error")
                yield event("done", ok=False)
                return
            except Exception:
                yield event("error", code="turn_failed")
                yield event("done", ok=False)
                return
            yield event("done", ok=True)
