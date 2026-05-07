"""SlackNotifier — sends gate approval requests to a Slack webhook."""

import json
import logging
import uuid
from typing import Any

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)


class SlackNotifier:
    def __init__(self, webhook_url: str | None = None):
        self._webhook_url = webhook_url or get_settings().SLACK_WEBHOOK_URL

    async def notify_gate_pending(
        self,
        run_id: uuid.UUID,
        gate_name: str,
        pipeline_name: str,
        tenant_id: str,
        summary: dict[str, Any] | None = None,
    ) -> bool:
        """
        Post a gate-pending notification to Slack.
        Returns True on success, False if webhook not configured or request fails.
        """
        if not self._webhook_url:
            logger.debug("Slack webhook not configured — skipping notification")
            return False

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Gate Approval Required: {gate_name}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Pipeline:*\n{pipeline_name}"},
                    {"type": "mrkdwn", "text": f"*Tenant:*\n{tenant_id}"},
                    {"type": "mrkdwn", "text": f"*Run ID:*\n{run_id}"},
                    {"type": "mrkdwn", "text": f"*Gate:*\n{gate_name}"},
                ],
            },
        ]

        if summary:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Summary:*\n```{json.dumps(summary, indent=2)[:500]}```",
                    },
                }
            )

        payload = {"blocks": blocks}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self._webhook_url, json=payload)
                resp.raise_for_status()
                return True
        except Exception as exc:
            logger.error("Slack notification failed: %s", exc)
            return False

    async def notify_gate_decided(
        self,
        run_id: uuid.UUID,
        gate_name: str,
        decision: str,
        notes: str = "",
    ) -> bool:
        if not self._webhook_url:
            return False

        emoji = ":white_check_mark:" if decision == "approved" else ":x:"
        text = f"{emoji} Gate *{gate_name}* was *{decision}* for run `{run_id}`"
        if notes:
            text += f"\n> {notes}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self._webhook_url, json={"text": text})
                resp.raise_for_status()
                return True
        except Exception as exc:
            logger.error("Slack notification failed: %s", exc)
            return False
