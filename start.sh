#!/usr/bin/env bash
#
# Start Gold Digger: the Python API, then the Electron app.
#
# The desktop app adopts an already-listening API rather than spawning its own,
# so starting the backend here keeps both sets of logs in one place and makes a
# stale server obvious instead of silent.
#
#   ./start.sh                 both, real extractors (beat-this + CLAP)
#   ./start.sh --mock          both, synthesized features -- fast, but the
#                              DISTANCE dial is then ranking noise
#   ./start.sh --backend       API only, in the foreground
#   ./start.sh --frontend      Electron only, against whatever is on the port
#   ./start.sh --restart       replace an API already listening on the port
#   ./start.sh --port 8500     use a different port
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$ROOT/golders-desktop"
PYTHON="$ROOT/.venv/bin/python3"
LOG_DIR="$ROOT/.logs"
LOG="$LOG_DIR/api.log"

PORT=8420
# The engine's own default is mock, for the test suite and the CLI. Running the
# app means wanting answers, and under mock the CLAP vector -- the whole basis of
# "sounds like" -- is synthesized from the file hash.
MOCK=0
RUN_BACKEND=1
RUN_FRONTEND=1
RESTART=0
BOOT_TIMEOUT=90

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mock)     MOCK=1 ;;
    --real)     MOCK=0 ;;      # kept: it was the default's opposite
    --backend)  RUN_FRONTEND=0 ;;
    --frontend) RUN_BACKEND=0 ;;
    --restart)  RESTART=1 ;;
    --port)     PORT="${2:?--port needs a number}"; shift ;;
    -h|--help)  sed -n '3,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)          echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '\033[1;33m▸\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

health() { curl -fsS -m 2 "http://127.0.0.1:$PORT/health" 2>/dev/null; }

# Only ever targets our own API, never some unrelated process on the port.
# Both spawn forms have to match. This script and the Electron main process run
# `-m uvicorn goldigger.api:app`, but the command the docs tell people to use is
# `golddigger serve`, whose command line is `-m goldigger.cli serve`. Matching
# only the first meant --restart could not see a server started the documented
# way: listener_pid returned 1, the port check below decided the listener was
# somebody else's, and start.sh refused to run at all -- while the desktop app
# was printing "restart it (./start.sh --restart)" as the remedy.
listener_pid() {
  local pid
  for pid in $(lsof -tnP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null); do
    if ps -p "$pid" -o command= | grep -qE 'goldigger\.(api|cli)'; then
      echo "$pid"
      return 0
    fi
  done
  return 1
}

# ---------------------------------------------------------------- preflight

[[ -x "$PYTHON" ]] || fail "no venv at $PYTHON — run: uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e '.[dev]'"

# The bin, not the folder: a half-finished install leaves node_modules in place
# with an empty .bin, and `npm run dev` then fails with "command not found".
if [[ $RUN_FRONTEND -eq 1 && ! -x "$APP/node_modules/.bin/electron-vite" ]]; then
  say "installing desktop dependencies"
  (cd "$APP" && npm install)
fi

# Electron's runtime is a postinstall download, not part of the package. Skipped
# scripts leave the module in place and electron-vite dies with "Electron uninstall".
if [[ $RUN_FRONTEND -eq 1 && ! -e "$APP/node_modules/electron/path.txt" ]]; then
  say "downloading the electron runtime"
  (cd "$APP" && node node_modules/electron/install.js)
fi

# ---------------------------------------------------------------- backend

API_PID=""

cleanup() {
  if [[ -n "$API_PID" ]] && kill -0 "$API_PID" 2>/dev/null; then
    say "stopping api (pid $API_PID)"
    kill "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ $RUN_BACKEND -eq 1 ]]; then
  if existing="$(listener_pid)"; then
    if [[ $RESTART -eq 1 ]]; then
      say "replacing api on :$PORT (pid $existing)"
      kill "$existing"
      while kill -0 "$existing" 2>/dev/null; do sleep 0.2; done
    else
      say "api already listening on :$PORT (pid $existing) — reusing it"
      say "it will NOT have picked up edits since it started; re-run with --restart"
      RUN_BACKEND=0
    fi
  elif health >/dev/null; then
    fail "something that is not our api is listening on :$PORT"
  fi
fi

if [[ $RUN_BACKEND -eq 1 ]]; then
  if [[ $RUN_FRONTEND -eq 0 ]]; then
    # Nothing to run afterwards, so hand the terminal to uvicorn.
    say "starting api on :$PORT (GOLDDIGGER_MOCK=$MOCK)"
    exec env GOLDDIGGER_MOCK="$MOCK" PYTHONUNBUFFERED=1 \
      "$PYTHON" -m uvicorn goldigger.api:app --host 127.0.0.1 --port "$PORT"
  fi

  mkdir -p "$LOG_DIR"
  say "starting api on :$PORT (GOLDDIGGER_MOCK=$MOCK) → .logs/api.log"

  ( cd "$ROOT" && GOLDDIGGER_MOCK="$MOCK" PYTHONUNBUFFERED=1 \
      "$PYTHON" -m uvicorn goldigger.api:app --host 127.0.0.1 --port "$PORT" ) >"$LOG" 2>&1 &
  API_PID=$!

  # Importing the package pulls in torch even in mock mode, so this is not quick.
  deadline=$((SECONDS + BOOT_TIMEOUT))
  until health >/dev/null; do
    kill -0 "$API_PID" 2>/dev/null || { tail -20 "$LOG" >&2; fail "api exited during boot"; }
    (( SECONDS < deadline )) || { tail -20 "$LOG" >&2; fail "api did not answer within ${BOOT_TIMEOUT}s"; }
    sleep 0.4
  done
fi

if [[ $RUN_FRONTEND -eq 1 ]]; then
  health >/dev/null || say "no api on :$PORT — the app will try to start its own"
fi

health | sed 's/^/  /' || true

# ---------------------------------------------------------------- frontend

if [[ $RUN_FRONTEND -eq 1 ]]; then
  say "starting desktop app"
  cd "$APP"
  npm run dev
fi
