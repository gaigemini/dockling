"""Webhook notification service for terminal async task states.

Delivers a signed notification (HMAC-SHA256) to the ``callback_url`` supplied
at submit time. Delivery failures never affect the task result: the status is
persisted in Redis before the callback is attempted, and polling remains the
fallback channel for clients.
"""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import socket
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

from config import settings
from app.models.task_model import TaskInfo
from app.services.base_service import BaseService
from app.utils.http_client import get_correlated_client


class CallbackService(BaseService):
    """Sends signed webhook notifications to task callback URLs."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def notify(self, task: TaskInfo, result_url: Optional[str] = None) -> bool:
        """POST a signed notification for a terminal task state.

        Args:
            task: The task in a terminal state (status already persisted).
            result_url: Optional presigned URL for the result artifact.

        Returns:
            True when the receiver acknowledged (2xx), False otherwise.
        """
        if not task.callback_url:
            return False

        if not await self._validate_url(task.callback_url):
            self.logger.warning(
                f"Rejected callback URL for task {task.task_id}: {task.callback_url}"
            )
            return False

        payload = self._build_payload(task, result_url)
        body = json.dumps(payload, default=str)
        signature = hmac.new(
            settings.SECRET_KEY.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-Task-Id": task.task_id,
            "X-Signature": f"sha256={signature}",
        }

        for attempt in range(1, settings.CALLBACK_MAX_RETRIES + 1):
            try:
                async with get_correlated_client(
                    timeout=httpx.Timeout(settings.CALLBACK_TIMEOUT)
                ) as client:
                    response = await client.post(
                        task.callback_url,
                        json=payload,
                        headers=headers,
                    )
                if response.status_code < 300:
                    self.logger.info(
                        f"Callback delivered for task {task.task_id} "
                        f"(attempt {attempt}, status {response.status_code})"
                    )
                    return True
                self.logger.warning(
                    f"Callback attempt {attempt} for task {task.task_id} "
                    f"returned HTTP {response.status_code}"
                )
            except Exception as exc:
                self.logger.warning(
                    f"Callback attempt {attempt} for task {task.task_id} failed: {exc}"
                )

            if attempt < settings.CALLBACK_MAX_RETRIES:
                # Exponential backoff: 1s, 2s, 4s ...
                await asyncio.sleep(2 ** (attempt - 1))

        self.logger.error(
            f"Callback permanently failed for task {task.task_id}",
            extra={"task_id": task.task_id, "callback_url": task.callback_url},
        )
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_payload(task: TaskInfo, result_url: Optional[str]) -> Dict[str, Any]:
        """Build the compact webhook payload (no large result inline)."""
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "endpoint": task.endpoint,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "processing_time": task.processing_time,
            "result_summary": task.result_summary,
            "result_url": result_url,
            "error": task.error,
        }

    async def _validate_url(self, url: str) -> bool:
        """Validate the callback URL (scheme + SSRF guard / allowlist)."""
        try:
            parsed = urlparse(url)
        except Exception:
            return False

        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False

        allowlist = {
            host.strip().lower()
            for host in settings.CALLBACK_ALLOWED_HOSTS.split(",")
            if host.strip()
        }
        host = parsed.hostname.lower()

        if allowlist:
            return host in allowlist

        # No allowlist configured: block private/loopback targets (SSRF guard).
        if host in ("localhost", "localhost.localdomain"):
            return False
        try:
            addresses = await asyncio.to_thread(
                socket.getaddrinfo, host, None, proto=socket.IPPROTO_TCP
            )
        except socket.gaierror:
            return False

        for info in addresses:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        return True
