"""通知服务：企业微信 + 邮件，分级（严重即时 / 一般 30min 汇总）。"""
from __future__ import annotations
import asyncio, logging, smtplib, time
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime

import httpx

from src.settings import settings

logger = logging.getLogger("fiber.notify")

class Notifier:
    def __init__(self) -> None:
        cfg = settings.notify
        self.channels = cfg["channels"]
        self.wecom = cfg.get("wecom_webhook", "")
        self.email_cfg = cfg.get("email", {})
        self.aggregate_interval = cfg["aggregate_interval_minutes"] * 60
        self._buffer: list[tuple[float, str, str]] = []
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._aggregator_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    # ───────── 对外接口 ─────────
    async def send_critical(self, title: str, body: str) -> None:
        """严重告警：即时推送（企业微信 + 邮件）。"""
        logger.error("[CRITICAL] %s: %s", title, body)
        await asyncio.gather(
            self._wecom(f"🔴 【严重】{title}\n{body}"),
            self._email(f"【严重】{title}", body),
            return_exceptions=True)

    def send_normal(self, title: str, body: str) -> None:
        """一般告警：进入 30min 汇总队列。"""
        logger.warning("[NORMAL] %s: %s", title, body)
        self._buffer.append((time.time(), title, body))

    # ───────── 渠道实现 ─────────
    async def _wecom(self, content: str) -> None:
        if "wecom" not in self.channels or not self.wecom:
            return
        async with httpx.AsyncClient(timeout=10) as cli:
            await cli.post(self.wecom, json={
                "msgtype": "text", "text": {"content": content}})

    async def _email(self, subject: str, body: str) -> None:
        if "email" not in self.channels or not self.email_cfg.get("smtp_host"):
            return
        def _send():
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = Header(subject, "utf-8")
            msg["From"] = self.email_cfg["sender"]
            msg["To"] = ", ".join(self.email_cfg["recipients"])
            with smtplib.SMTP_SSL(self.email_cfg["smtp_host"],
                                  self.email_cfg["smtp_port"]) as s:
                s.login(self.email_cfg["username"],
                        self.email_cfg["password"])
                s.sendmail(self.email_cfg["sender"],
                           self.email_cfg["recipients"], msg.as_string())
        await asyncio.to_thread(_send)

    # ───────── 汇总循环 ─────────
    async def _aggregator_loop(self) -> None:
        while True:
            await asyncio.sleep(self.aggregate_interval)
            if not self._buffer:
                continue
            now = time.time()
            due = [b for b in self._buffer
                   if now - b[0] >= self.aggregate_interval]
            self._buffer = [b for b in self._buffer if b not in due]
            if due:
                lines = "\n".join(
                    f"- [{datetime.fromtimestamp(t).strftime('%H:%M')}]"
                    f" {title}: {body}" for t, title, body in due)
                await self._email(
                    f"【汇总】{len(due)} 条一般告警",
                    f"过去 {self.aggregate_interval // 60} 分钟告警汇总：\n{lines}")


notifier = Notifier()