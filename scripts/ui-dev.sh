#!/bin/sh
# API (8800) + Vite dev server (127.0.0.1:5173). Run from the repo root (make ui-dev).
# Tracks the two child PIDs, signals only those, and stops both when either exits.
# Never signals a process group.
api=""
vite=""

stop() {
    trap '' INT TERM EXIT
    for pid in $api $vite; do
        kill "$pid" 2>/dev/null
    done
    wait 2>/dev/null
}

trap 'stop; exit 130' INT
trap 'stop; exit 143' TERM
trap 'stop' EXIT

backend/.venv/bin/dataforce ui --no-build-check &
api=$!
(cd frontend && exec npm run dev -- --host 127.0.0.1 --port 5173) &
vite=$!

# POSIX sh has no `wait -n`: poll until either child is gone.
while kill -0 "$api" 2>/dev/null && kill -0 "$vite" 2>/dev/null; do
    sleep 1
done
exit 1
