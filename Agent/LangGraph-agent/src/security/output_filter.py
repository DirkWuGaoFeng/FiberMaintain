"""
Output Filter [v7.1].

Post-processing filter for Agent responses:
- IP/port masking (based on user role)
- Sensitive field filtering
- Internal error message sanitization
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Patterns for sensitive data
_IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_PORT_PATTERN = re.compile(r":(\d{2,5})\b")
_INTERNAL_ERROR_PATTERN = re.compile(
    r"(Traceback|File \"|line \d+|at 0x[0-9a-f]+)", re.IGNORECASE
)


class OutputFilter:
    """
    Output sanitization filter.

    Roles:
    - admin: sees everything
    - operator: IP masked, ports visible
    - viewer: IP + ports masked
    """

    def __init__(self, role: str = "operator"):
        self.role = role

    def filter(self, text: str) -> str:
        """Apply all output filters."""
        if self.role == "admin":
            return text

        text = self._mask_ips(text)
        if self.role == "viewer":
            text = self._mask_ports(text)
        text = self._sanitize_errors(text)
        return text

    def _mask_ips(self, text: str) -> str:
        """Mask IP addresses: 192.168.1.1 → 192.168.*.* """
        def _replace_ip(match):
            ip = match.group(0)
            parts = ip.split(".")
            return f"{parts[0]}.{parts[1]}.*.*"
        return _IP_PATTERN.sub(_replace_ip, text)

    def _mask_ports(self, text: str) -> str:
        """Mask port numbers: :8080 → :**** """
        return _PORT_PATTERN.sub(":****", text)

    def _sanitize_errors(self, text: str) -> str:
        """Remove internal error details from output."""
        if _INTERNAL_ERROR_PATTERN.search(text):
            # Replace traceback with generic message
            lines = text.split("\n")
            sanitized = []
            skip = False
            for line in lines:
                if _INTERNAL_ERROR_PATTERN.search(line):
                    skip = True
                    sanitized.append("（内部错误详情已隐藏）")
                elif skip and (line.startswith("  ") or line.startswith("\t")):
                    continue
                else:
                    skip = False
                    sanitized.append(line)
            return "\n".join(sanitized)
        return text


# Default filter instance
output_filter = OutputFilter(role="operator")
