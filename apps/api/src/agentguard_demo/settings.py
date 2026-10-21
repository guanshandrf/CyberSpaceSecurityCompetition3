"""Trusted server configuration; never accepted from chat requests."""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class DemoSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enable_baseline: bool = False
    enable_protection: bool = False
    guard_permissions: tuple[Literal["file.read", "note.write"], ...] = ("file.read", "note.write")
    max_tool_calls: int = Field(default=8, ge=1, le=64)
    provider: Literal["fake", "deepseek"] = "fake"
    enable_real_api: bool = False
    enable_model_selection: bool = False
    api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    sandbox_root: Path = Path(".cache/demo")
    max_provider_calls: int = Field(default=8, ge=1, le=16)
    max_total_provider_calls: int = Field(default=16, ge=1, le=100)
    max_tokens: int = Field(default=256, ge=1, le=1024)
    model: Literal["deepseek-chat"] = "deepseek-chat"

    @model_validator(mode="after")
    def isolated_modes(self):
        if self.enable_baseline and self.enable_protection:
            raise ValueError("Select one server mode: baseline or protected")
        if self.enable_model_selection and not self.enable_protection:
            raise ValueError("Model selection requires protected server mode")
        return self

    @classmethod
    def from_env(cls):
        def enabled(name):
            value = os.getenv(name, "false").lower()
            if value not in {"true", "false"}:
                raise ValueError(f"{name} must be true or false")
            return value == "true"

        provider = os.getenv("AGENTGUARD_LLM_PROVIDER", "fake")
        selection = enabled("AGENTGUARD_ENABLE_MODEL_SELECTION")
        return cls(
            enable_baseline=enabled("AGENTGUARD_ENABLE_BASELINE"),
            enable_protection=enabled("AGENTGUARD_ENABLE_PROTECTION"),
            provider=provider,
            enable_real_api=enabled("AGENTGUARD_ENABLE_REAL_API"),
            enable_model_selection=selection,
            api_key=SecretStr(
                os.getenv("DEEPSEEK_API_KEY", "") if provider == "deepseek" or selection else ""
            ),
            sandbox_root=Path(os.getenv("AGENTGUARD_SANDBOX_ROOT", ".cache/demo")),
            max_provider_calls=int(os.getenv("AGENTGUARD_MAX_PROVIDER_CALLS", "8")),
            max_total_provider_calls=int(os.getenv("AGENTGUARD_MAX_TOTAL_PROVIDER_CALLS", "16")),
            max_tokens=int(os.getenv("AGENTGUARD_MAX_TOKENS", "256")),
        )
