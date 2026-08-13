#!/bin/sh
set -eu
runtime_dir=/run/sms-gateway
for proc_file in "$runtime_dir/gateway.proc"; do
  test -s "$proc_file" || exit 1
  kill -0 "$(cat "$proc_file")" 2>/dev/null || exit 1
done
python3 - <<'PY'
import os
import sqlite3
path = os.environ.get("DATABASE_PATH", "/data/gateway.sqlite3")
with sqlite3.connect(path) as connection:
    connection.execute("SELECT 1").fetchone()
PY
