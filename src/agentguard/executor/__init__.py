"""P3 forced pre-tool authorization. Result content filtering belongs to P4."""

from .guarded import ExecutionResult, GuardedExecutor
from .results import HandledResult, ResultHandler

__all__ = ["ExecutionResult", "GuardedExecutor", "HandledResult", "ResultHandler"]
