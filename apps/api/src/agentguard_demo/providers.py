"""Deterministic fake and explicitly enabled DeepSeek-compatible provider."""

import json
from contextlib import nullcontext
from typing import Any
from uuid import uuid4

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, convert_to_openai_messages
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field, SecretStr

from agentguard_demo.settings import DemoSettings


class FakeChatModel(BaseChatModel):
    """Commands: read_file {JSON}, write_note {JSON}, recall, or ordinary echo."""

    tool_names: tuple[str, ...] = ()

    @property
    def _llm_type(self):
        return "agentguard-offline-fake"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"tool_names": tuple(tool.name for tool in tools)})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1]
        if isinstance(last, ToolMessage):
            reply = AIMessage(content=f"工具结果：{last.content}")
        else:
            humans = [message.content for message in messages if isinstance(message, HumanMessage)]
            command, _, payload = str(last.content).partition(" ")
            if command in self.tool_names:
                try:
                    arguments = json.loads(payload)
                    if not isinstance(arguments, dict):
                        raise ValueError
                except (ValueError, TypeError):
                    reply = AIMessage(content="Fake 工具命令需要 JSON 对象参数。")
                else:
                    reply = AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": command,
                                "args": arguments,
                                "id": f"call_{uuid4().hex}",
                                "type": "tool_call",
                            }
                        ],
                    )
            elif last.content == "recall":
                reply = AIMessage(content=str(humans[-2]) if len(humans) > 1 else "无上一轮消息。")
            else:
                reply = AIMessage(content=f"Fake 第 {len(humans)} 轮：{last.content}")
        return ChatResult(generations=[ChatGeneration(message=reply)])


class DeepSeekChatModel(BaseChatModel):
    """Bounded synchronous LangChain provider for DeepSeek's chat completions API."""

    api_key: SecretStr = Field(exclude=True, repr=False)
    model_name: str = "deepseek-chat"
    max_tokens: int = 256
    tool_schemas: tuple[dict, ...] = ()
    http_client: Any = Field(default=None, exclude=True, repr=False)

    @property
    def _llm_type(self):
        return "deepseek-chat-completions"

    @property
    def _identifying_params(self):
        return {"model_name": self.model_name, "max_tokens": self.max_tokens}

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(
            update={"tool_schemas": tuple(convert_to_openai_tool(t) for t in tools)}
        )

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        body = {
            "model": self.model_name,
            "messages": convert_to_openai_messages(messages),
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if self.tool_schemas:
            body["tools"] = list(self.tool_schemas)
        context = (
            nullcontext(self.http_client)
            if self.http_client is not None
            else httpx.Client(timeout=15, trust_env=False)
        )
        try:
            with context as client:
                response = client.post(
                    "https://api.deepseek.com/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key.get_secret_value()}"},
                    timeout=15,
                )
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
            calls = []
            for call in message.get("tool_calls", []):
                arguments = json.loads(call["function"]["arguments"])
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be an object")
                calls.append(
                    {
                        "id": call["id"],
                        "name": call["function"]["name"],
                        "args": arguments,
                        "type": "tool_call",
                    }
                )
            reply = AIMessage(content=message.get("content") or "", tool_calls=calls)
        except Exception:
            raise RuntimeError("provider_request_failed") from None
        return ChatResult(generations=[ChatGeneration(message=reply)])


def make_provider(settings: DemoSettings, *, http_client=None) -> BaseChatModel:
    if not settings.enable_baseline:
        raise ValueError("Unprotected baseline is disabled")
    if settings.provider == "fake":
        if settings.enable_real_api:
            raise ValueError("Real API flag requires deepseek provider")
        return FakeChatModel()
    if not settings.enable_real_api or not settings.api_key.get_secret_value():
        raise ValueError("DeepSeek requires explicit real API enablement and a server-side key")
    return DeepSeekChatModel(
        model_name=settings.model,
        api_key=settings.api_key,
        max_tokens=settings.max_tokens,
        http_client=http_client,
    )
