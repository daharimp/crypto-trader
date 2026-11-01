"""Owner alerts for forward sessions (UD-10: console/log, plus one push or chat channel).

Set ``ALERT_WEBHOOK_URL`` (and optionally ``ALERT_WEBHOOK_KIND``: ``ntfy``, ``slack``,
``discord``) to receive critical events on a phone. Alert failures are logged, never raised.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from typing import Any

from trader.common.logging import get_logger
from trader.domain.enums import EventType

log = get_logger("alerts")

CRITICAL = {
    EventType.KILL_SWITCH_ENGAGED,
    EventType.KILL_SWITCH_DISENGAGED,
    EventType.CIRCUIT_BREAKER_OPENED,
    EventType.DAILY_LOCKOUT_STARTED,
    EventType.RECONCILIATION_FAILED,
    EventType.EXECUTION_ERROR,
    EventType.ORDER_FILLED,
    EventType.STOP_TRIGGERED,
    EventType.RUN_FAILED,
    EventType.COOLDOWN_STARTED,
}


def _summary(event: EventType, payload: Any) -> str:
    """
    One-line human summary of an event.

    Args:
        event (EventType): Event type.
        payload (Any): Event payload (model or dict).

    Returns:
        str: Summary text.
    """
    p = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else dict(payload or {})
    if event == EventType.ORDER_FILLED:
        return (
            f"FILLED {p.get('order_intent_id')}: {p.get('filled_quantity')} @ "
            f"{p.get('average_fill_price')} (fee ${p.get('fees_usd')})"
        )
    keys = ("reason", "trigger", "drawdown_pct", "daily_loss_pct", "differences", "message")
    detail = ", ".join(f"{k}={p[k]}" for k in keys if k in p)
    return f"{event.value} {detail}".strip()


class Alerter:
    """Sends selected events to a webhook."""

    def __init__(
        self,
        url: str | None,
        kind: str = "ntfy",
        prefix: str = "trader",
        post: Callable[[urllib.request.Request], Any] | None = None,
    ) -> None:
        """
        Create an alerter (no-op without a URL).

        Args:
            url (str | None): Webhook URL.
            kind (str): ``ntfy``, ``slack``, or ``discord``.
            prefix (str): Text prefix (e.g. ``[LIVE]``).
            post (Callable | None): Transport (tests inject a fake).
        """
        self.url, self.kind, self.prefix = url, kind, prefix
        self._post = post or (lambda req: urllib.request.urlopen(req, timeout=5))  # noqa: S310

    @classmethod
    def from_env(cls, prefix: str) -> Alerter:
        """
        Build from ``ALERT_WEBHOOK_URL`` / ``ALERT_WEBHOOK_KIND``.

        Args:
            prefix (str): Text prefix.

        Returns:
            Alerter: Alerter.
        """
        return cls(
            os.environ.get("ALERT_WEBHOOK_URL") or None,
            os.environ.get("ALERT_WEBHOOK_KIND", "ntfy"),
            prefix,
        )

    def send(self, text: str) -> bool:
        """
        Send a message.

        Args:
            text (str): Message.

        Returns:
            bool: True if delivered (False without a URL or on failure).
        """
        msg = f"{self.prefix} {text}"
        log.warning(msg, extra={"event_type": "ALERT"})
        if not self.url:
            return False
        if self.kind == "slack":
            body, ctype = json.dumps({"text": msg}).encode(), "application/json"
        elif self.kind == "discord":
            body, ctype = json.dumps({"content": msg}).encode(), "application/json"
        else:
            body, ctype = msg.encode(), "text/plain"
        req = urllib.request.Request(
            self.url, data=body, headers={"Content-Type": ctype}, method="POST"
        )
        try:
            self._post(req)
            return True
        except Exception as exc:  # noqa: BLE001 - alerts must never stop trading controls
            log.error(f"alert delivery failed: {exc}")
            return False

    def on_event(self, event: EventType, payload: Any) -> None:
        """
        Hook for ``RunState.on_event``: forward critical events.

        Args:
            event (EventType): Event type.
            payload (Any): Payload.
        """
        if event in CRITICAL:
            self.send(_summary(event, payload))
