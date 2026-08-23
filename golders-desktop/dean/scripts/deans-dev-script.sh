#!/usr/bin/env bash

# Dean's Gold Digger development launcher.
#
# Starts the shared development stack and records each session in:
#
#   dean/logs/<timestamp>/master.log
#   dean/logs/<timestamp>/frontend.log
#   dean/logs/<timestamp>/backend.log
#
# The shared start.sh options can be passed through. This launcher defaults to
# mock extraction and replaces a stale Gold Digger API for a predictable start.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_DIR="$(cd "$DESKTOP_DIR/.." && pwd)"
LOGS_DIR="$DESKTOP_DIR/dean/logs"
API_SOURCE_LOG="$REPO_DIR/.logs/api.log"
SESSION_NAME="$(date '+%Y-%m-%d_%H-%M-%S')"
SESSION_DIR="$LOGS_DIR/$SESSION_NAME"
MASTER_LOG="$SESSION_DIR/master.log"
FRONTEND_LOG="$SESSION_DIR/frontend.log"
BACKEND_LOG="$SESSION_DIR/backend.log"

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  cat <<'HELP'
Usage: deans-dev-script.sh [start.sh options]

Starts the Python backend and Electron frontend together. Output is shown in
the terminal and saved to separate frontend, backend, and combined master logs.

Defaults: --mock --restart

Common overrides:
  --real       use real audio extractors
  --backend    run only the Python API
  --frontend   run only Electron
  --port PORT  use a different API port

The complete option set is provided by the repository's start.sh.
HELP
  exit 0
fi

[[ -x "$REPO_DIR/start.sh" ]] || {
  printf 'Could not find the shared launcher at %s/start.sh\n' "$REPO_DIR" >&2
  exit 1
}

mkdir -p "$SESSION_DIR" "$REPO_DIR/.logs"
touch "$MASTER_LOG" "$FRONTEND_LOG" "$BACKEND_LOG" "$API_SOURCE_LOG"

# Keep the three files open for the whole session. Child pipelines inherit the
# descriptors, so a formatted line can be written to its own log and the shared
# master log without launching another `tee` process for every line.
exec 3>>"$FRONTEND_LOG"
exec 4>>"$BACKEND_LOG"
exec 5>>"$MASTER_LOG"

write_line() {
  local source="$1"
  local message="$2"
  local timestamp formatted

  timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
  formatted="$timestamp [$source] $message"

  case "$source" in
    frontend) printf '%s\n' "$formatted" >&3 ;;
    backend)  printf '%s\n' "$formatted" >&4 ;;
  esac

  printf '%s\n' "$formatted" >&5
  printf '%s\n' "$formatted"
}

log_stream() {
  local source="$1"
  local line

  while IFS= read -r line || [[ -n "$line" ]]; do
    write_line "$source" "$line"
  done
}

TAIL_PID=""

cleanup() {
  if [[ -n "$TAIL_PID" ]] && kill -0 "$TAIL_PID" 2>/dev/null; then
    kill "$TAIL_PID" 2>/dev/null || true
    wait "$TAIL_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

write_line runner "Gold Digger development session $SESSION_NAME"
write_line runner "Branch: $(git -C "$REPO_DIR" branch --show-current 2>/dev/null || printf unknown)"
write_line runner "Logs: $SESSION_DIR"

# start.sh owns the backend and writes its output here. Following from the end
# avoids replaying a previous session; -F survives start.sh truncating the file.
# Process substitution keeps $! pointed at tail itself, allowing cleanup to
# terminate the actual follower rather than only the downstream formatter.
tail -n 0 -F "$API_SOURCE_LOG" 2>/dev/null > >(log_stream backend) &
TAIL_PID=$!

set +e
"$REPO_DIR/start.sh" --mock --restart "$@" 2>&1 | log_stream frontend
START_STATUS=${PIPESTATUS[0]}
set -e

write_line runner "Development stack exited with status $START_STATUS"
exit "$START_STATUS"
