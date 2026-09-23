#!/bin/sh
# Start Girard on Linux or macOS: audio helper (:8766), agent (:8000), dashboard (:5173).
# Ctrl+C stops all three. Assumes the setup steps in README.md are done.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

(cd "$root/linux-audio-helper" && ./launch.sh --port 8766) &
helper=$!
(cd "$root" && .venv/bin/python agent.py) &
agent=$!
(cd "$root/dashboard" && npx vite dev --port 5173 --strictPort) &
dashboard=$!

trap 'kill $helper $agent $dashboard 2>/dev/null' INT TERM EXIT
echo "Girard: open http://localhost:5173/"
wait
