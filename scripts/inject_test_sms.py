#!/usr/bin/env python3
"""Inject a fake Gammu FILES message in development mode only."""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    if os.environ.get("GATEWAY_DEVELOPMENT_MODE", "false").lower() != "true":
        raise SystemExit("development mode is required")
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox", default=os.environ.get("GAMMU_INBOX_PATH", "data/gammu/inbox"))
    parser.add_argument("--sender", default="+15550001001")
    parser.add_argument("--text", required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    filename = f"IN{now:%Y%m%d_%H%M%S}_00_{args.sender}_00.txt"
    inbox = Path(args.inbox)
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / filename).write_text(args.text, encoding="utf-8")
    print(filename)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
