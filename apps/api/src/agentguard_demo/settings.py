"""Trusted server configuration; never accepted from chat requests."""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class DemoSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enable_baseline: bool = False
    provider: Literal["fake", "deepseek"] = "fake"
    enable_real_api: bool = False
    api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    sandbox_root: Path = Path(".cache/demo")
    max_provider_calls: int = Field(default=8, ge=1, le=16)
    max_total_provider_calls: int = Field(default=16, ge=1, le=100)
    max_tokens: int = Field(default=256, ge=1, le=1024)
    model: Literal["deepseek-chat"] = "deepseek-chat"

    @classmethod
    def from_env(cls):
        def enabled(name):
            value = os.getenv(name, "false").lower()
            if value not in {"true", "false"}:
                raise ValueError(f"{name} must be true or false")
            return value == "true"

        provider = os.getenv("AGENTGUARD_LLM_PROVIDER", "fake")
        return cls(
            enable_baseline=enabled("AGENTGUARD_ENABLE_BASELINE"),
            provider=provider,
            enable_real_api=enabled("AGENTGUARD_ENABLE_REAL_API"),
            api_key=SecretStr(os.getenv("DEEPSEEK_API_KEY", "") if provider == "deepseek" else ""),
            sandbox_root=Path(os.getenv("AGENTGUARD_SANDBOX_ROOT", ".cache/demo")),
            max_provider_calls=int(os.getenv("AGENTGUARD_MAX_PROVIDER_CALLS", "8")),
            max_total_provider_calls=int(os.getenv("AGENTGUARD_MAX_TOTAL_PROVIDER_CALLS", "16")),
            max_tokens=int(os.getenv("AGENTGUARD_MAX_TOKENS", "256")),
        )
