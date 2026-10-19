"""Offline P0 defaults; all temporary project files stay inside the repository."""

import os
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_sandbox(monkeypatch, tmp_path):
    def deny_network(*args, **kwargs):
        raise RuntimeError("P0 tests forbid network access")

    for name in list(os.environ):
        if any(word in name.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("AGENTGUARD_LLM_PROVIDER", "fake")
    monkeypatch.setenv("AGENTGUARD_ENABLE_REAL_API", "false")
    monkeypatch.setenv("AGENTGUARD_ENABLE_BENCHMARKS", "false")
    monkeypatch.setenv("AGENTGUARD_ENABLE_BASELINE", "false")
    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)
    monkeypatch.chdir(tmp_path)
