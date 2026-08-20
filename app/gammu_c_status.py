"""Read rich Gammu SMSD shared-memory status through the C helper."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class CStatus:
    signal_percent: int | None
    signal_dbm: int | None
    bit_error_percent: int | None
    sent: int | None
    received: int | None
    failed: int | None
    network_name: str | None
    network_code: str | None
    network_state: str | None
    lac: str | None
    cid: str | None
    gprs_state: str | None
    packet_state: str | None
    packet_lac: str | None
    packet_cid: str | None
    checked_at: str


def _int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def parse_helper_output(output: str, checked_at: str | None = None) -> CStatus | None:
    data = None
    for line in reversed(output.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            data = candidate
            break
    if data is None:
        return None
    return CStatus(
        signal_percent=_int(data.get("signal_percent")),
        signal_dbm=_int(data.get("signal_dbm")),
        bit_error_percent=_int(data.get("bit_error_percent")),
        sent=_int(data.get("sent")),
        received=_int(data.get("received")),
        failed=_int(data.get("failed")),
        network_name=_text(data.get("network_name")),
        network_code=_text(data.get("network_code")),
        network_state=_text(data.get("network_state")),
        lac=_text(data.get("lac")),
        cid=_text(data.get("cid")),
        gprs_state=_text(data.get("gprs_state")),
        packet_state=_text(data.get("packet_state")),
        packet_lac=_text(data.get("packet_lac")),
        packet_cid=_text(data.get("packet_cid")),
        checked_at=checked_at or datetime.now(UTC).replace(microsecond=0).isoformat(),
    )


def read_c_status(config_path: str | Path, helper_path: str = "/usr/local/bin/gammu-smsd-status") -> CStatus | None:
    try:
        result = subprocess.run(
            [helper_path, str(config_path)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return parse_helper_output(result.stdout, datetime.now(UTC).replace(microsecond=0).isoformat())
