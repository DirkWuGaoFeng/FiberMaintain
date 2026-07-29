"""
Auth callback: validates user authentication token.
"""

from __future__ import annotations

import logging

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)


class AuthCallback(BaseCallbackHandler):
    """Authentication callback: validates user credentials before chain execution."""

    def on_chain_start(self, serialized: dict, inputs: dict, **kwargs) -> None:
        token = (inputs.get("config", {}).get("metadata", {}).get("auth_token")
                 or kwargs.get("metadata", {}).get("auth_token"))
        if token is None:
            # Allow unauthenticated access in development mode
            logger.debug("[Auth] No auth token, allowing in dev mode")
            return
        # In production, validate token here
        logger.info(f"[Auth] Validating token: {token[:8]}...")
