"""Durable ingestion from the Gammu FILES backend."""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .store import GatewayStore


INBOX_FILE = re.compile(
    r"^IN(?P<date>\d{8})_(?P<time>\d{6})_(?P<serial>\d+)_(?P<sender>.+)_(?P<sequence>\d+)\.(?P<extension>txt|bin|smsbackup)$"
)


@dataclass(frozen=True)
class InboundFile:
    path: Path
    source_identifier: str
    sender: str
    received_at: str
    multipart_sequence: int
    group_identifier: str


def parse_inbox_file(path: Path) -> InboundFile:
    match = INBOX_FILE.match(path.name)
    if not match:
        raise ValueError(f"Unsupported Gammu inbox filename: {path.name}")
    timestamp = datetime.strptime(
        f"{match['date']}{match['time']}", "%Y%m%d%H%M%S"
    ).replace(tzinfo=UTC)
    group_identifier = "IN{date}_{time}_{serial}_{sender}".format(**match.groupdict())
    return InboundFile(
        path=path,
        source_identifier=path.name,
        sender=match["sender"],
        received_at=timestamp.isoformat(),
        multipart_sequence=int(match["sequence"]),
        group_identifier=group_identifier,
    )


def decode_gammu_text(path: Path) -> str:
    """Decode Gammu FILES text without replacing Unicode characters."""
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        if b"\x00" in raw:
            return raw.decode("utf-16")
        return raw.decode("utf-8")


class FilesIngress:
    def __init__(self, store: GatewayStore, inbox_path: Path, archive_path: Path):
        self.store = store
        self.inbox_path = inbox_path
        self.archive_path = archive_path

    def ingest_pending(self) -> list[int]:
        self.inbox_path.mkdir(parents=True, exist_ok=True)
        self.archive_path.mkdir(parents=True, exist_ok=True)
        groups: dict[str, list[InboundFile]] = {}
        for path in sorted(self.inbox_path.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            inbound = parse_inbox_file(path)
            groups.setdefault(inbound.group_identifier, []).append(inbound)

        message_ids: list[int] = []
        for group_identifier, parts in groups.items():
            parts.sort(key=lambda item: item.multipart_sequence)
            first = parts[0]
            text = "".join(decode_gammu_text(part.path) for part in parts)
            message_id, created = self.store.ingest_message(
                source_identifier=group_identifier,
                sender=first.sender,
                received_at=first.received_at,
                text=text,
                multipart_reference=group_identifier if len(parts) > 1 else None,
                multipart_total=len(parts) if len(parts) > 1 else None,
                multipart_sequence=None if len(parts) > 1 else first.multipart_sequence,
            )
            if created:
                message_ids.append(message_id)
            for part in parts:
                shutil.move(str(part.path), self.archive_path / part.path.name)
        return message_ids
