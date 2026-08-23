#!/usr/bin/env bash
# Assemble the Python engine the DMG ships: a relocatable interpreter with the
# goldigger package (and its dependencies) installed into its own site-packages.
#
# The app's spawn assumes the repo checkout is its parent directory, which is
# only true in development. This puts a self-contained engine in
# resources/engine, which electron-builder copies into the .app as
# Resources/engine (see extraResources in package.json) and src/main/api.ts
# prefers when the app is packaged.
#
#   ./scripts/package-engine.sh            # engine only; CLAP downloads on first run
#   ./scripts/package-engine.sh --models   # also bake the CLAP weights in (offline first run)
#
# Then: npm run dist
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"        # golders-desktop
REPO="$(cd "$HERE/.." && pwd)"
ENGINE="$HERE/resources/engine"
PYTHON_VERSION=3.12

BUNDLE_MODELS=0
for arg in "$@"; do
  case "$arg" in
    --models) BUNDLE_MODELS=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

command -v uv >/dev/null || { echo "uv is required: brew install uv" >&2; exit 1; }

rm -rf "$ENGINE"
mkdir -p "$ENGINE"

# uv's managed interpreters are python-build-standalone builds: self-contained
# and relocatable, which living inside a .app bundle requires. A venv is
# neither -- it symlinks back to wherever its base interpreter happened to be --
# and plain `uv python find` prefers the repo's venv, so both flags: --system
# skips venvs, --managed-python refuses a Homebrew/Xcode interpreter.
uv python install "$PYTHON_VERSION"
SRC_BIN="$(uv python find --system --managed-python "$PYTHON_VERSION")"
# -P and -L both matter: uv's install dirs and binaries are reached through
# symlinks, and a copied symlink pointing back into ~/.local/share/uv is a
# bundle that only works on the machine that built it.
SRC_ROOT="$(cd "$(dirname "$SRC_BIN")/.." && pwd -P)"
echo "copying $SRC_ROOT"
cp -RL "$SRC_ROOT" "$ENGINE/python"

PY="$ENGINE/python/bin/python3"
[ -e "$PY" ] || ln -s "python$PYTHON_VERSION" "$PY"

# uv marks its interpreters externally managed so nothing installs into them.
# This copy is ours to fill; without removing the marker, uv pip refuses.
rm -f "$ENGINE/python/lib/python$PYTHON_VERSION"/EXTERNALLY-MANAGED

# A copy that still resolves into uv's install would install the packages into
# the wrong python -- refuse loudly instead of shipping a hollow engine.
PREFIX="$("$PY" -c 'import sys; print(sys.prefix)')"
case "$PREFIX" in
  "$ENGINE"/*) ;;
  *) echo "engine python resolves outside the bundle: $PREFIX" >&2; exit 1 ;;
esac

# Not editable: this site-packages copy is the one the app ships, so the
# package source must live inside it rather than pointing back at the repo.
uv pip install --python "$PY" "$REPO"

# Not a project dependency because Windows cannot pip it (see the README's
# Docker branch) -- but this bundle is macOS by definition, so the DMG carries
# the second opinion natively.
uv pip install --python "$PY" essentia

# what a running engine never imports
find "$ENGINE/python" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -rf "$ENGINE/python/lib/python$PYTHON_VERSION/test"

if [ "$BUNDLE_MODELS" = 1 ]; then
  # Download CLAP into a cache the bundle carries; api.ts points HF_HOME here
  # when the directory exists. tag_vectors() doubles as a smoke test that the
  # packaged engine can actually load and run the model. beat-this fetches its
  # checkpoint through its own cache and is not covered by this.
  mkdir -p "$ENGINE/models"
  HF_HOME="$ENGINE/models" "$PY" -c \
    'from goldigger.features import Clap; Clap(device="cpu").tag_vectors()'
fi

du -sh "$ENGINE"
echo "engine assembled -- npm run dist will fold it into the DMG"
