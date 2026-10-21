"""Offline P0 defaults; all temporary project files stay inside the repository."""

import os
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_sandbox(monkeypatch, tmp_path):
    def deny_network(*args, **kwargs):
        raise RuntimeError("P0 tests forbid network access")

    original_connect = socket.socket.connect
    socketpair_code = getattr(socket.socketpair, "__code__", None)

    def guarded_connect(connection, address):
        # Windows asyncio creates its wake-up pipe through stdlib socketpair.
        # Permit that exact implementation's local IPC, never ordinary connections.
        if (
            socketpair_code is not None
            and sys._getframe(1).f_code is socketpair_code
            and isinstance(address, tuple)
            and address[0] in {"127.0.0.1", "::1"}
        ):
            return original_connect(connection, address)
        return deny_network()

    for name in list(os.environ):
        if any(word in name.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("AGENTGUARD_LLM_PROVIDER", "fake")
    monkeypatch.setenv("AGENTGUARD_ENABLE_REAL_API", "false")
    monkeypatch.setenv("AGENTGUARD_ENABLE_MODEL_SELECTION", "false")
    monkeypatch.setenv("AGENTGUARD_ENABLE_BENCHMARKS", "false")
    monkeypatch.setenv("AGENTGUARD_ENABLE_BASELINE", "false")
    monkeypatch.setenv("AGENTGUARD_ENABLE_PROTECTION", "false")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)
    monkeypatch.chdir(tmp_path)
