"""
输出过滤器 [v7.1]。

对 Agent 响应进行后处理过滤：
- IP/端口掩码（基于用户角色）
- 敏感字段过滤
- 内部错误信息脱敏
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 敏感数据匹配模式
_IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_PORT_PATTERN = re.compile(r":(\d{2,5})\b")
_INTERNAL_ERROR_PATTERN = re.compile(r"(Traceback|File \"|line \d+|at 0x[0-9a-f]+)", re.IGNORECASE)


class OutputFilter:
    """
    输出脱敏过滤器。

    角色：
    - admin：可见全部内容
    - operator：IP 掩码，端口可见
    - viewer：IP 与端口均掩码
    """

    def __init__(self, role: str = "operator"):
        self.role = role

    def filter(self, text: str) -> str:
        """应用所有输出过滤。"""
        if self.role == "admin":
            return text

        text = self._mask_ips(text)
        if self.role == "viewer":
            text = self._mask_ports(text)
        text = self._sanitize_errors(text)
        return text

    def _mask_ips(self, text: str) -> str:
        """掩码 IP 地址：192.168.1.1 → 192.168.*.*"""

        def _replace_ip(match):
            ip = match.group(0)
            parts = ip.split(".")
            return f"{parts[0]}.{parts[1]}.*.*"

        return _IP_PATTERN.sub(_replace_ip, text)

    def _mask_ports(self, text: str) -> str:
        """掩码端口号：:8080 → :****"""
        return _PORT_PATTERN.sub(":****", text)

    def _sanitize_errors(self, text: str) -> str:
        """从输出中移除内部错误详情。"""
        if _INTERNAL_ERROR_PATTERN.search(text):
            # 用通用消息替换 traceback
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


# 默认过滤器实例
output_filter = OutputFilter(role="operator")
