#!/bin/sh
set -eu

runtime_dir=/run/sms-gateway
proc_file="$runtime_dir/gateway.proc"
test -s "$proc_file"
pid=$(cat "$proc_file")
test "$pid" -gt 1
stat_file="/proc/$pid/stat"
test -r "$stat_file"
state=$(cut -d' ' -f3 "$stat_file")
test "$state" != Z
test "$state" != X

python3 - <<'PY'
import os
import sqlite3
path = os.environ.get("DATABASE_PATH", "/data/gateway.sqlite3")
with sqlite3.connect(path) as connection:
    connection.execute("SELECT 1").fetchone()
PY
