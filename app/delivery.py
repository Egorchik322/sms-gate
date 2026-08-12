"""Independent delivery queue processing.

Network integrations implement ChannelTransport outside this core module. Tests use
RecordingTransport, so the gateway can be exercised without external services.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from .store import GatewayStore

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeliveryResult:
    outcome: str
    retry_after_seconds: int | None = None
    detail: str | None = None


class ChannelTransport(Protocol):
    channel: str

    def send(self, message_id: int, sender: str, received_at: str, text: str) -> DeliveryResult:
        ...


class RecordingTransport:
    """Deterministic transport for development and tests; never performs network I/O."""

    def __init__(self, channel: str, result: DeliveryResult | None = None):
        self.channel = channel
        self.result = result or DeliveryResult("sent")
        self.calls: list[tuple[int, str, str, str]] = []

    def send(self, message_id: int, sender: str, received_at: str, text: str) -> DeliveryResult:
        self.calls.append((message_id, sender, received_at, text))
        return self.result


class DeliveryWorker:
    def __init__(self, store: GatewayStore, transport: ChannelTransport):
        self.store = store
        self.transport = transport

    def run_once(self) -> int:
        delivered = 0
        for row in self.store.due_deliveries(self.transport.channel):
            result = self.transport.send(row["message_id"], row["sender"], row["received_at"], row["text"])
            if result.outcome == "sent":
                self.store.mark_delivery_sent(row["id"])
                delivered += 1
                LOGGER.info("delivery sent message_id=%s channel=%s", row["message_id"], self.transport.channel)
                continue
            self.store.mark_delivery_failure(
                row["id"],
                kind=result.outcome,
                retry_after_seconds=result.retry_after_seconds,
                detail=result.detail,
            )
            LOGGER.warning(
                "delivery failed message_id=%s channel=%s class=%s",
                row["message_id"],
                self.transport.channel,
                result.detail or result.outcome,
            )
        return delivered
