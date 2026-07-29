"""Callbacks package."""

from .auth import AuthCallback
from .rate_limit import RateLimitCallback
from .tracing import TracingCallback
from .rag_injection import RAGInjectionCallback

__all__ = [
    "AuthCallback",
    "RateLimitCallback",
    "TracingCallback",
    "RAGInjectionCallback",
]


def get_default_callbacks() -> list:
    """Get the default callback pipeline."""
    return [
        AuthCallback(),
        RateLimitCallback(),
        TracingCallback(),
    ]
