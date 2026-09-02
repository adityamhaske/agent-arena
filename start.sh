#!/usr/bin/env bash
# ==============================================================================
# Agent Arena — Local Startup Script
#
# Starts both the Agent Arena Web UI and the Documentation Site locally,
# checks Ollama connectivity, and ensures graceful teardown on exit.
# ==============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

ARENA_PORT="${ARENA_PORT:-8420}"
DOCS_PORT="${DOCS_PORT:-8123}"

# Colors for terminal output
BOLD="\033[1m"
BLUE="\033[34m"
GREEN="\033[32m"
YELLOW="\033[33m"
RESET="\033[0m"

echo -e "${BOLD}${BLUE}"
echo "  ___                    _      _                          "
echo " / _ \                  | |    / \                         "
echo "/ /_\ \ __ _  ___ _ __  | |_  / _ \  _ __ ___ _ __   __ _  "
echo "|  _  |/ _\` |/ _ \ '_ \ | __|/ ___ \| '__/ _ \ '_ \ / _\` | "
echo "| | | | (_| |  __/ | | || |_/ /   \ \ | |  __/ | | | (_| | "
echo "\_| |_/\__, |\___|_| |_| \___\_/   \_/_|  \___|_| |_|\__,_| "
echo "        __/ |                                              "
echo "       |___/                                               "
echo -e "${RESET}"
echo -e "Starting Agent Arena development environment...\n"

# ------------------------------------------------------------------------------
# 1. Environment & Package Verification
# ------------------------------------------------------------------------------
if ! command -v python3 &>/dev/null; then
  echo -e "${YELLOW}! python3 not found. Please install Python 3.10+.${RESET}"
  exit 1
fi

# Ensure package is installed in editable mode
if ! python3 -c "import agent_arena" &>/dev/null; then
  echo -e "Installing agent-arena in editable mode..."
  python3 -m pip install -e . --quiet
fi

# ------------------------------------------------------------------------------
# 2. Check Ollama Status
# ------------------------------------------------------------------------------
echo -ne "Checking local Ollama service... "
if curl -s --connect-timeout 1 http://localhost:11434/api/tags &>/dev/null; then
  echo -e "${GREEN}Running${RESET} (http://localhost:11434)"
elif command -v ollama &>/dev/null; then
  echo -e "${YELLOW}Installed but not running${RESET}"
  echo "  Starting Ollama daemon in background..."
  ollama serve &>/dev/null &
  OLLAMA_PID=$!
  sleep 1.5
  if curl -s --connect-timeout 1 http://localhost:11434/api/tags &>/dev/null; then
    echo -e "  ${GREEN}✓ Ollama started successfully.${RESET}"
  fi
else
  echo -e "${YELLOW}Not installed${RESET} (Optional for local-only sweeps: https://ollama.ai)"
fi

# ------------------------------------------------------------------------------
# 3. Build & Start Documentation Site
# ------------------------------------------------------------------------------
echo -e "\nBuilding documentation site..."
python3 site/build.py

echo -e "Starting documentation server on port ${DOCS_PORT}..."
python3 -m http.server "${DOCS_PORT}" --directory site/_build &>/dev/null &
DOCS_PID=$!

# ------------------------------------------------------------------------------
# 4. Graceful Cleanup Trap
# ------------------------------------------------------------------------------
cleanup() {
  echo -e "\n\nShutting down local servers..."
  if [ -n "${DOCS_PID:-}" ] && kill -0 "$DOCS_PID" 2>/dev/null; then
    kill "$DOCS_PID" 2>/dev/null || true
  fi
  if [ -n "${ARENA_PID:-}" ] && kill -0 "$ARENA_PID" 2>/dev/null; then
    kill "$ARENA_PID" 2>/dev/null || true
  fi
  echo "Cleaned up. Goodbye!"
  exit 0
}
trap cleanup EXIT INT TERM

# ------------------------------------------------------------------------------
# 5. Banner & Launch Web UI
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}${GREEN}✓ All services ready!${RESET}\n"
echo -e "  ${BOLD}Agent Arena Web UI:${RESET}  ${BLUE}http://localhost:${ARENA_PORT}/${RESET}"
echo -e "  ${BOLD}Documentation Site:${RESET}  ${BLUE}http://localhost:${DOCS_PORT}/${RESET}"
echo -e "\n  Press ${BOLD}Ctrl+C${RESET} in this terminal to stop all servers.\n"

# Run Agent Arena UI in foreground
python3 -m agent_arena.cli ui --port "${ARENA_PORT}"
