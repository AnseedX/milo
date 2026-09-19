#!/usr/bin/env bash
# ============================================================
#  milo installer (macOS / Linux)
#  One-liner:
#    curl -fsSL https://raw.githubusercontent.com/AnseedX/milo/main/install.sh | bash
#
#  Clones milo, installs Python deps, and symlinks `milo` onto
#  your PATH so you can run it from any terminal.
#
#  Overrides:  MILO_HOME (install dir)
# ============================================================
set -euo pipefail

REPO="https://github.com/AnseedX/milo.git"
DIR="${MILO_HOME:-$HOME/.milo}"

echo ""
echo "🐈‍⬛  Installing milo..."

# --- prerequisites ---
if ! command -v git >/dev/null 2>&1; then
  echo "✗ git is required. Install it and re-run (macOS: 'xcode-select --install', Linux: your package manager)."
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ Python 3.10+ is required. Install it and re-run."
  exit 1
fi

# --- clone or update ---
if [ -d "$DIR/.git" ]; then
  echo "  • Updating existing install at $DIR"
  git -C "$DIR" pull --ff-only >/dev/null
else
  echo "  • Cloning milo to $DIR"
  git clone --depth 1 "$REPO" "$DIR" >/dev/null 2>&1
fi

# --- python dependencies ---
echo "  • Installing Python dependencies..."
python3 -m pip install --quiet --upgrade httpx openai rich

# --- put milo on PATH via symlink ---
chmod +x "$DIR/milo"
if [ -w "/usr/local/bin" ]; then
  BIN="/usr/local/bin"
else
  BIN="$HOME/.local/bin"
  mkdir -p "$BIN"
fi
ln -sf "$DIR/milo" "$BIN/milo"

echo ""
echo "✅ milo installed!"

# --- LM Studio check ---
if ! command -v lms >/dev/null 2>&1; then
  echo ""
  echo "⚠  LM Studio not detected — milo needs it to run a local model."
  echo "   Install it from https://lmstudio.ai and download a model (e.g. google/gemma-4-e4b)."
fi

case ":$PATH:" in
  *":$BIN:"*) echo "" ; echo "👉 Run:  milo" ;;
  *) echo "" ; echo "👉 Add $BIN to your PATH, then run:  milo" ;;
esac
echo ""
